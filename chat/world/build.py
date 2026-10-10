"""Build a world and cut it into V2 bundles.

  build_world(config)              physical simulation + observation + truth (all splits, one connected world)
  export_bundle(build, live_split) the V2 import world and provider feed for one live split, cut by TIME:
                                     everything recorded at or before the live start is imported (earlier booking
                                     days as V2 split "history", with verified outcomes); everything recorded after
                                     it, of any shipment or shared resource, travels the provider feed; later
                                     booking days are left out entirely. The one exception is the booking-time
                                     context of a live shipment (its order, parcels, address and plan, all stamped
                                     at booking), which the foundation contract imports up front and every reader
                                     filters by recorded_at.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
import time

from dataset_v2.contracts import Edge, Node, Provenance, World, digest, instant, iso
from dataset_v2.feed import WORLD_FEED_KINDS, Reference, channel_for, feed_item
from world.bookings import generate_bookings
from world.config import WORLD_SPLITS, WORLD_VERSION, WorldConfig
from world.mechanisms import CLAIM_SUBTYPE, MechanismPlan
from world.monitor import Replica, deliver_at
from world.network import Network
from world.observe import Observer
from world.rand import Draws
from world.schedule import Scheduler
from world.truth import TruthBuilder

ROUTINE_SUBTYPE = {"RECIPIENT_NOT_REACHED": "NOT_HOME", "CUSTOMER_REQUESTED_RESCHEDULE": "RESCHEDULED_BY_RECIPIENT",
                   "OTP_NOT_CONFIRMED": "CODE_NOT_PROVIDED", "ADDRESS_NOT_FOUND": "BUILDING_NOT_FOUND",
                   "ACCESS_NOT_COMPLETED": "ACCESS_REFUSED", "NOT_ATTEMPTED_TIME": "ROUTE_NOT_COMPLETED", "OTHER": "NOT_HOME"}
# Mechanisms that are the cause of the failed attempt they are recorded on.
ATTEMPT_CAUSES = {"RECIPIENT_UNAVAILABLE", "WRONG_ADDRESS", "WRONG_GATE", "OTP_NOT_RECEIVED", "TRAFFIC_DISRUPTION"}
RETRANSMIT = {"DRIVER_APP": .05, "CARRIER_EDI": .04, "SPL_CORE": .006, "TELEMATICS": .01, "MESSAGING": .01, "MDM": .0,
              "RECIPIENT_PORTAL": .0, "TRAFFIC": .0}
# Booking-time context of a shipment: stamped at booking, imported with the shipment (never a feed message).
BOOKING_CONTEXT = frozenset(("Shipment", "Package", "Customer", "Address", "AddressVersion", "LocationPin", "DeliveryInstruction",
                             "InventoryRecord", "Route", "JourneyPlan", "RouteSegment", "RouteMilestone", "ExpectedMilestone"))


@dataclass
class WorldBuild:
    config: WorldConfig
    network: Network
    shipments: dict
    plan: MechanismPlan
    sim: object
    observer: Observer
    world: World
    truth: dict = field(default_factory=dict)
    caused: dict = field(default_factory=dict)            # mid -> shipments the mechanism caused a deviation on
    exposed: dict = field(default_factory=dict)           # mid -> shipments it touched without consequence
    as_of: dict = field(default_factory=dict)
    first_opening: dict = field(default_factory=dict)
    retransmissions: dict = field(default_factory=dict)   # node id -> retransmission deliver instant
    history_reports: dict = field(default_factory=dict)   # live split -> precedents authored / not imported
    rounds: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    @property
    def touched(self):
        return self.caused


def build_world(config: WorldConfig | None = None) -> WorldBuild:
    config = config or WorldConfig()
    clock = time.perf_counter()
    timings = {}
    draws = Draws(config.seed)
    network = Network(config, draws)
    shipments = generate_bookings(config, network, draws)
    scheduler = Scheduler(config, network, draws, shipments)
    sim = scheduler.run()
    claim_start_at_handover(scheduler.plan, sim, shipments)
    timings["simulation"] = round(time.perf_counter() - clock, 2)
    observer = Observer(config, network, draws, shipments, sim, scheduler.plan)
    world = observer.build()
    timings["observation"] = round(time.perf_counter() - clock, 2)
    build = WorldBuild(config, network, shipments, scheduler.plan, sim, observer, world, rounds=scheduler.rounds)
    build.caused = {mid: set(sids) for mid, sids in scheduler.caused.items()}
    build.exposed = {mid: set(sids) for mid, sids in scheduler.exposed.items()}
    retransmissions(build, draws)
    ordinary_failed_attempts(build)
    snapshot_times(build)
    timings["snapshots"] = round(time.perf_counter() - clock, 2)
    build.truth = TruthBuilder(build).rows()
    timings["truth"] = round(time.perf_counter() - clock, 2)
    build.timings = timings
    return build


def claim_start_at_handover(plan, sim, shipments):
    """A non-receipt claim acts from the moment the parcel was handed over in the final simulation run (the scheduler
    placed it using an earlier run's delivery time)."""
    for mech in plan.items.values():
        if mech.type == "CUSTOMER_COMPLAINT" and mech.subtype == CLAIM_SUBTYPE:
            handed = [row[0] for p in shipments[mech.params["sid"]].parcels for row in sim.p[p.pid].timeline if row[1] == "PERSON"]
            if handed:
                mech.started_at = min(handed)


def retransmissions(build, draws):
    """Providers resend some messages (same identity, same payload) a few minutes later: never a case."""
    world, plan = build.world, build.plan
    per_ship = defaultdict(list)
    for nid in sorted(build.observer.records):
        node = world.nodes[nid]
        if not node.properties.get("occurred_at"):
            continue
        channel = channel_for(world, node)
        if draws.chance(RETRANSMIT.get(channel, 0), "retransmit", nid):
            again = deliver_at(node) + timedelta(seconds=draws.integer(90, 900, "retransmit-delay", nid))
            build.retransmissions[nid] = again
            sid = node.properties.get("holdout_group")
            if sid:
                per_ship[sid].append((nid, again))
    for sid, rows in sorted(per_ship.items()):
        mid = plan.add("DUPLICATE_EVENTS", "PROVIDER_RETRANSMISSION", min(t for _, t in rows), None, origin="base",
                       records={sid: sorted(n for n, _ in rows)}, retransmitted_at={sid: sorted(iso(t) for _, t in rows)})
        build.exposed.setdefault(mid, set()).add(sid)


def ordinary_failed_attempts(build):
    """Every failed attempt has a cause. The ones no scheduled mechanism produced are ordinary (the recipient was out,
    asked for another day, the building was not found, the route ran out of time): one ROUTINE_FAILED_ATTEMPT instance
    per shipment, with the cause read from the attempt's reason. It needs an answer when the shipment misses its promise
    or when the monitor's rules flag the attempt (an unreached recipient with an unanswered call); otherwise it is
    ordinary variation of a healthy shipment."""
    sim, plan = build.sim, build.plan
    unanswered = {a["attempt"] for a in sim.acts if a["type"] == "contact" and a["result"] == "NO_RESPONSE"}
    failed = defaultdict(list)
    for a in sim.acts:
        if a["type"] == "attempt" and a["disposition"] == "FAILED" and not any(plan.items[m].type in ATTEMPT_CAUSES for m in a["mech"]):
            failed[a["sid"]].append(a)
    for sid, attempts in sorted(failed.items()):
        s = build.shipments[sid]
        attempts.sort(key=lambda a: (a["t"], a["act"]))
        handed = [row[0] for p in s.parcels for row in sim.p[p.pid].timeline if row[1] == "PERSON"]
        late = not handed or min(handed) > s.promise_at
        flagged = any(a["reason"] == "RECIPIENT_NOT_REACHED" and a["act"] in unanswered for a in attempts)
        subtype = ROUTINE_SUBTYPE.get(attempts[0]["reason"], "NOT_HOME")
        mid = plan.add("ROUTINE_FAILED_ATTEMPT", subtype, attempts[0]["t"], None, origin="background", sid=sid, benign=not (late or flagged))
        build.caused.setdefault(mid, set()).add(sid)
        acts = {a["act"] for a in attempts}
        for a in attempts:
            a["mech"].append(mid)
        for meta in build.observer.records.values():
            if meta["act"] and (meta["act"] in acts or sim.acts_by_id(meta["act"]).get("attempt") in acts):
                meta["mech"] = sorted(set(meta["mech"]) | {mid})


def snapshot_times(build):
    """Shipment.as_of: when the monitor would first open a case (hourly ticks, 900 s allowance), else the end of
    the shipment's recorded story. Bookkeeping only: removed from live shipments before export."""
    config = build.config
    replica = Replica(build.world, config.start_at, evidence_ids=set(build.observer.records))
    build.replica = replica
    end = config.end_at
    for sid in sorted(build.shipments):
        opening = replica.opening(sid, end)
        if opening:
            build.as_of[sid] = opening[0]
            build.first_opening[sid] = {"at": iso(opening[0]), "codes": opening[1], "symptoms": opening[2]}
        else:
            times = [replica.visible[n.id] for nodes in replica.index.groups[sid].values() for n in nodes if n.id in replica.visible]
            build.as_of[sid] = min(max(times) + timedelta(hours=1), instant(build.world.config.as_of))


# ---------------------------------------------------------------------- history cut-off (addendum A2)
def shipment_left_at(build, sid):
    """When every parcel of the shipment had left the network (handed to a person), else None."""
    ends = []
    for parcel in build.shipments[sid].parcels:
        t, kind, _ = build.sim.p[parcel.pid].timeline[-1]
        if kind != "PERSON":
            return None
        ends.append(t)
    return max(ends)


# Faults with no natural recovery keep acting on the parcel until it leaves the network (catalogue: natural recovery "none").
PERSISTENT = {"WRONG_LABEL_APPLIED", "DECLARED_WEIGHT_WRONG", "MANIFEST_ERROR", "MISDELIVERY", "CONTRACTOR_RETAINS", "UNRECORDED_HANDOFF",
              "DELIVERY_SCAN_SKIPPED"}


def mechanism_active_until(build, mechanism, sid):
    """Last instant a mechanism instance acted on a shipment: the end of its window, the arrival of every record it
    shaped for the shipment and of its discriminating evidence, and, for a fault with no natural recovery (or one
    with neither a window nor records), the moment the shipment's parcels left the network. None: still active."""
    world = build.world
    times = [instant(mechanism["started_at"])] if mechanism["started_at"] else []
    times += [deliver_at(world.nodes[n]) for n in mechanism["evidence_ids"] if n in world.nodes and world.nodes[n].properties.get("recorded_at")]
    for group in mechanism["discrimination"]["any_of"]:
        for item in group["all_of"]:
            if "record" in item and item["record"] in world.nodes:
                times.append(deliver_at(world.nodes[item["record"]]))
            elif "absence" in item:
                times.append(instant(item["absence"]["overdue_at"]))
    if mechanism["type"] == "DUPLICATE_EVENTS":
        times += [instant(t) for t in build.plan.items[mechanism["mechanism_id"]].params.get("retransmitted_at", {}).get(sid, [])]
    if mechanism["ended_at"]:
        times.append(instant(mechanism["ended_at"]))
    if mechanism["type"] in PERSISTENT or (not mechanism["ended_at"] and not mechanism["evidence_ids"]):
        left = shipment_left_at(build, sid)
        if left is None:
            return None
        times.append(left)
    return max(times) if times else None


# A provider retransmission repeats a record already counted (same identity, same payload) and is never a case: it
# carries nothing about a history case's outcome, so it does not block a precedent.
CUTOFF_EXEMPT = {"DUPLICATE_EVENTS"}


def precedent_exclusions(build, sids, live_start):
    """History shipments that must not become precedents: a mechanism instance that caused something on them is still
    active at or after the cut-off (addendum A2). Private: never written into the graph."""
    out = {}
    for sid in sorted(sids):
        for mechanism in build.truth[sid]["mechanisms"]:
            if mechanism["type"] in CUTOFF_EXEMPT:
                continue
            until = mechanism_active_until(build, mechanism, sid)
            if until is None or until >= live_start:
                out[sid] = "MECHANISM_ACTIVE_AT_OR_AFTER_CUTOFF"
                break
    return out


# ---------------------------------------------------------------------- export
def labels_for(live_split):
    position = WORLD_SPLITS.index(live_split)
    return {split: "history" if i < position else "development" if i == position else None for i, split in enumerate(WORLD_SPLITS)}


def export_bundle(build: WorldBuild, live_split="development"):
    """(imported V2 world, feed items, truth rows for the included shipments, live start)."""
    from dataset_v2.derive import custody_corroborated, derive_world
    from dataset_v2.generate import close_custody_intervals
    from world.history import author_history
    config = build.config
    labels = labels_for(live_split)
    label = {sid: labels[s.split] for sid, s in build.shipments.items()}
    included = {sid for sid, value in label.items() if value}
    history = {sid for sid in included if label[sid] == "history"}
    live = {sid for sid in included if label[sid] == "development"}
    live_start = config.live_start(live_split)
    counts = defaultdict(int)
    for sid in included:
        counts[label[sid]] += 1
    world = World(config.v2_config(dict(counts)))
    for key, node in build.world.nodes.items():
        owner = node.properties.get("holdout_group")
        if owner and owner not in included:
            continue
        props = dict(node.properties)
        if owner:
            props["split"] = label[owner]
        world.nodes[key] = Node(node.id, node.kind, props)
    for key, edge in build.world.edges.items():
        if edge.start not in world.nodes or edge.end not in world.nodes:
            continue
        props = dict(edge.properties)
        owner = props.get("holdout_group")
        if owner:
            props["split"] = label[owner]
        world.edges[key] = Edge(edge.id, edge.kind, edge.start, edge.end, props)
    horizon = instant(world.config.as_of)
    snapshot = {}
    for sid in included:
        # A history shipment is known as far as the live start, never later; its case, if the monitor would have
        # opened one by then, is the case at its opening. A live shipment's scoring row carries no hindsight: the
        # foundation validator re-derives it at the end of the horizon.
        snapshot[sid] = min(build.as_of[sid], live_start) if sid in history else horizon
        world.nodes[sid].properties["as_of"] = iso(snapshot[sid])
        world.gold[sid] = {"shipment_id": sid, "holdout_group": sid, "split": label[sid], "initial_snapshot_at": iso(snapshot[sid]),
                           "reference_kind": "world-1 scoring row; mechanisms and causes live only in the external truth directory"}
    derive_world(world)
    excluded = precedent_exclusions(build, history, live_start)
    build.history_reports[live_split] = author_history(world, snapshot, Draws(config.seed), live_start, excluded)
    ref = Reference.from_world(world)
    moving, kept_booking = set(), 0
    booked = {sid: build.shipments[sid].booked_at for sid in included}
    for key, node in world.nodes.items():
        if node.kind in ("Case", "Exception"):
            continue
        owner = node.properties.get("holdout_group")
        recorded = instant(node.properties["recorded_at"])
        if owner in live and recorded > booked[owner]:
            moving.add(key)      # Created during the journey: reaches Suhail through the provider feed.
        elif recorded > live_start:
            if owner in live and node.kind in BOOKING_CONTEXT and recorded == booked[owner]:
                kept_booking += 1    # The foundation contract: a live shipment's order is imported, stamped at booking.
            else:
                moving.add(key)  # Later evidence of an earlier booking day, or a later shared record.
    derived = {n.id for n in world.nodes.values() if n.kind in ("Case", "Exception") and n.properties.get("holdout_group") in live}
    items = []
    for key in sorted(moving):
        node = world.nodes[key]
        if node.kind not in WORLD_FEED_KINDS or not node.properties.get("occurred_at"):
            raise ValueError(f"A record of kind {node.kind} recorded after the live start cannot travel the provider feed: {key}")
        items.append(feed_item(world, node, ref))
        again = build.retransmissions.get(key)
        if again is not None:
            items.append(feed_item(world, node, ref, sequence=1, deliver_at=iso(again)))
    removed = moving | derived
    imported = World(world.config)
    for key, node in world.nodes.items():
        if key in removed:
            continue
        props = dict(node.properties)
        if props.get("holdout_group") in live and node.kind in ("Shipment", "JourneyPlan"):
            props.pop("as_of", None)
            if node.kind == "Shipment":
                props["status"] = "CREATED"
        imported.nodes[key] = Node(node.id, node.kind, props)
    imported.edges = {k: e for k, e in world.edges.items() if e.start not in removed and e.end not in removed}
    # Parcel-on-vehicle intervals are derived from the imported custody records only (what was known at the live start).
    for node in list(imported.nodes.values()):
        p = node.properties
        if node.kind == "CustodyEvent" and p.get("event_type") == "LOADED" and p.get("holdout_group") in history and p.get("vehicle_id"):
            if custody_corroborated(imported, node, live_start):
                imported.edge(p["holdout_group"], "LOADED_ON", p["to_id"], valid_from=p["occurred_at"], valid_to=None,
                              interval_status="OPEN_OBSERVATION_GAP", custody_event_id=node.id, provenance=str(Provenance.DERIVED),
                              package_id=p["package_id"])
    close_custody_intervals(imported)
    imported.gold = {k: {f: v for f, v in row.items() if not (k in live and f == "assessment")} for k, row in world.gold.items()}
    items.sort(key=lambda item: (item["deliver_at"], item["feed_id"]))
    truth = TruthBuilder(build, included).rows()
    build.import_reports = getattr(build, "import_reports", {})
    build.import_reports[live_split] = {"live_booking_context_records_imported": kept_booking,
                                        "fed_records_of_earlier_booking_days": sum(1 for k in moving if world.nodes[k].properties.get("holdout_group") in history),
                                        "fed_shared_records": sum(1 for k in moving if not world.nodes[k].properties.get("holdout_group"))}
    return imported, items, truth, live_start


def world_manifest(build, live_split, imported, items, truth):
    """Provenance of one export and the committed scenario weighting (separate from the frozen V2 manifest). It names
    no per-shipment outcome and no achieved count per mechanism: those are in the truth directory."""
    config = build.config
    labels = labels_for(live_split)
    sizes = {split: sum(1 for s in build.shipments.values() if s.split == split) for split in WORLD_SPLITS if labels[split]}
    return {"world_version": WORLD_VERSION, "dataset_id": config.dataset_id, "seed": config.seed, "total": config.total,
            "days": config.days, "split_days": list(config.split_days), "start_date": config.start_date,
            "horizon_days": config.horizon_days, "live_split": live_split, "live_start": iso(config.live_start(live_split)),
            "v2_split_labels": {k: v for k, v in labels.items() if v}, "synthetic": True,
            "scenario_weighting": {"note": "Committed over-sampling rates (world/config.py MECHANISM_RATES): scenario weighting, "
                                           "not real frequencies. target = max(1, round(rate x shipments in the split)) shipments on "
                                           "which the mechanism is the cause of a deviation.",
                                   "rates": {m: {"history": h, "live": l} for m, h, l in config.rates},
                                   "targets": {split: {m: config.target(m, split, sizes[split]) for m, _, _ in config.rates} for split in sizes}},
            "counts": {"imported_nodes": len(imported.nodes), "imported_edges": len(imported.edges), "feed_items": len(items),
                       "shipments": sizes, **getattr(build, "import_reports", {}).get(live_split, {})},
            "hashes": {"feed": digest(items), "v2_manifest": digest(imported.manifest())},
            "timings_seconds": build.timings}


def truth_manifest(build, live_split, truth):
    """What the scenario weighting achieved in one export (truth directory only)."""
    achieved = {}
    for split in WORLD_SPLITS:
        rows = [r for r in truth.values() if r["split"] == split]
        if not rows:
            continue
        caused, exposed = defaultdict(set), defaultdict(set)
        for r in rows:
            for m in r["mechanisms"]:
                caused[m["type"]].add(r["shipment_id"])
            for m in r["exposures"]:
                exposed[m["type"]].add(r["shipment_id"])
        achieved[split] = {"shipments": len(rows), "caused": {t: len(v) for t, v in sorted(caused.items())},
                           "exposed_only": {t: len(v - caused[t]) for t, v in sorted(exposed.items())}}
    instances = defaultdict(lambda: defaultdict(int))
    for mech in build.plan.items.values():
        instances[mech.type][mech.origin] += 1
    return {"live_split": live_split, "achieved": achieved, "instances": {t: dict(v) for t, v in sorted(instances.items())},
            "precedents": {"authored": build.history_reports.get(live_split, {}).get("authored"),
                           "not_imported_by_reason": dict(Counter(build.history_reports.get(live_split, {}).get("not_imported", {}).values()))},
            "scheduler_rounds": build.rounds, "truth_hash": digest([truth[k] for k in sorted(truth)])}
