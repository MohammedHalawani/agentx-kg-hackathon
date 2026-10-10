"""Build a world and cut it into V2 bundles.

  build_world(config)              physical simulation + observation + truth (all splits, one connected world)
  export_bundle(build, live_split) the V2 import world and provider feed for one live split:
                                     earlier booking days imported in full (V2 split "history", with verified
                                     outcomes), the live split fed through the provider feed (V2 "development"),
                                     later days left out entirely.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
import time

from dataset_v2.contracts import Edge, Node, Provenance, World, digest, instant, iso
from dataset_v2.feed import SHARED_OBSERVATIONS, WORLD_FEED_KINDS, Reference, channel_for, feed_item
from world.bookings import generate_bookings
from world.config import WORLD_SPLITS, WORLD_VERSION, WorldConfig
from world.mechanisms import MechanismPlan
from world.monitor import Replica, deliver_at
from world.network import Network
from world.observe import Observer
from world.rand import Draws
from world.schedule import Scheduler
from world.truth import TruthBuilder

ROUTINE_SUBTYPE = {"RECIPIENT_NOT_REACHED": "NOT_HOME", "CUSTOMER_REQUESTED_RESCHEDULE": "RESCHEDULED_BY_RECIPIENT",
                   "OTP_NOT_CONFIRMED": "CODE_NOT_PROVIDED", "ADDRESS_NOT_FOUND": "BUILDING_NOT_FOUND",
                   "ACCESS_NOT_COMPLETED": "ACCESS_REFUSED", "NOT_ATTEMPTED_TIME": "ROUTE_NOT_COMPLETED", "OTHER": "NOT_HOME"}
RETRANSMIT = {"DRIVER_APP": .05, "CARRIER_EDI": .04, "SPL_CORE": .006, "TELEMATICS": .01, "MESSAGING": .01, "MDM": .0,
              "RECIPIENT_PORTAL": .0, "TRAFFIC": .0}


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
    touched: dict = field(default_factory=dict)
    as_of: dict = field(default_factory=dict)
    first_opening: dict = field(default_factory=dict)
    retransmissions: dict = field(default_factory=dict)   # node id -> retransmission deliver instant
    history_reports: dict = field(default_factory=dict)   # live split -> precedents authored / not imported
    rounds: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)


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
    touched = {mid: set(sids) for mid, sids in scheduler.affected(sim).items()}
    observer = Observer(config, network, draws, shipments, sim, scheduler.plan)
    world = observer.build()
    timings["observation"] = round(time.perf_counter() - clock, 2)
    build = WorldBuild(config, network, shipments, scheduler.plan, sim, observer, world, rounds=scheduler.rounds)
    retransmissions(build, draws)
    background_mechanisms(build, touched)
    for mid, sids in build.touched_extra.items():
        touched.setdefault(mid, set()).update(sids)
    build.touched = touched
    snapshot_times(build)
    timings["snapshots"] = round(time.perf_counter() - clock, 2)
    build.truth = TruthBuilder(build).rows(touched)
    timings["truth"] = round(time.perf_counter() - clock, 2)
    build.timings = timings
    return build


def claim_start_at_handover(plan, sim, shipments):
    """A non-receipt claim acts from the moment the parcel was handed over in the final simulation run (the scheduler
    placed it using an earlier run's delivery time)."""
    from world.mechanisms import CLAIM_SUBTYPE
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
    build.touched_extra = defaultdict(set)
    for sid, rows in sorted(per_ship.items()):
        mid = plan.add("DUPLICATE_EVENTS", "PROVIDER_RETRANSMISSION", min(t for _, t in rows), None, origin="base",
                       records={sid: sorted(n for n, _ in rows)}, retransmitted_at={sid: sorted(iso(t) for _, t in rows)})
        build.touched_extra[mid].add(sid)


def background_mechanisms(build, touched):
    """Natural causes nobody scheduled: a recipient who was out (or asked for another day) on an express promise."""
    sim, plan = build.sim, build.plan
    explained = defaultdict(set)
    for mid, sids in touched.items():
        if plan.items[mid].type not in ("DUPLICATE_EVENTS", "CUSTOMER_COMPLAINT"):
            for sid in sids:
                explained[sid].add(mid)
    failed = defaultdict(list)
    for a in sim.acts:
        if a["type"] == "attempt" and a["disposition"] == "FAILED":
            failed[a["sid"]].append(a)
    for sid, s in sorted(build.shipments.items()):
        handed = [row[0] for p in s.parcels for row in sim.p[p.pid].timeline if row[1] == "PERSON"]
        late = not handed or min(handed) > s.promise_at
        if not late or explained.get(sid):
            continue
        attempts = sorted(failed.get(sid, []), key=lambda a: a["t"])
        if attempts:
            first = attempts[0]["t"]
            subtype = ROUTINE_SUBTYPE.get(attempts[0]["reason"], "NOT_HOME")
            mid = plan.add("ROUTINE_FAILED_ATTEMPT", subtype, first, None, origin="background", sid=sid)
            build.touched_extra[mid].add(sid)
            for a in failed[sid]:
                a["mech"].append(mid)
            for nid, meta in build.observer.records.items():
                if meta["act"] in {a["act"] for a in failed[sid]}:
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
    """History shipments that must not become precedents: a mechanism instance touching them is still active
    at or after the cut-off (addendum A2). Private: never written into the graph."""
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
    from dataset_v2.derive import derive_world
    from dataset_v2.generate import close_custody_intervals
    from world.history import author_history
    config = build.config
    labels = labels_for(live_split)
    label = {sid: labels[s.split] for sid, s in build.shipments.items()}
    included = {sid for sid, value in label.items() if value}
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
    for sid in included:
        world.nodes[sid].properties["as_of"] = iso(build.as_of[sid])
        world.gold[sid] = {"shipment_id": sid, "holdout_group": sid, "split": label[sid], "initial_snapshot_at": iso(build.as_of[sid]),
                           "reference_kind": "world-1 scoring row; mechanisms and causes live only in the external truth directory"}
    derive_world(world)
    imported_ids = {sid for sid in included if label[sid] == "history"}
    live_start = config.live_start(live_split)
    excluded = precedent_exclusions(build, imported_ids, live_start)
    build.history_reports[live_split] = author_history(world, build.as_of, Draws(config.seed), live_start, excluded)
    for node in list(world.nodes.values()):
        p = node.properties
        if node.kind == "CustodyEvent" and p.get("event_type") == "LOADED" and p.get("holdout_group") in imported_ids and p.get("vehicle_id"):
            from dataset_v2.derive import custody_corroborated
            if custody_corroborated(world, node, instant(world.config.as_of)):
                world.edge(p["holdout_group"], "LOADED_ON", p["to_id"], valid_from=p["occurred_at"], valid_to=None,
                           interval_status="OPEN_OBSERVATION_GAP", custody_event_id=node.id, provenance=str(Provenance.DERIVED),
                           package_id=p["package_id"])
    close_custody_intervals(world)
    live = {sid for sid in included if label[sid] == "development"}
    ref = Reference.from_world(world)
    moving = set()
    booked = {sid: build.shipments[sid].booked_at for sid in live}
    for key, node in world.nodes.items():
        owner = node.properties.get("holdout_group")
        if owner in live and node.kind not in ("Case", "Exception") and instant(node.properties["recorded_at"]) > booked[owner]:
            moving.add(key)   # Created during the journey: reaches Suhail through the provider feed.
        elif owner is None and node.kind in SHARED_OBSERVATIONS and instant(node.properties["recorded_at"]) >= live_start:
            moving.add(key)
    derived = {n.id for n in world.nodes.values() if n.kind in ("Case", "Exception") and n.properties.get("holdout_group") in live}
    items = []
    for key in sorted(moving):
        node = world.nodes[key]
        if node.kind not in WORLD_FEED_KINDS:
            raise ValueError(f"A live record of kind {node.kind} cannot travel through the provider feed")
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
    imported.edges = {k: e for k, e in world.edges.items() if e.start not in removed and e.end not in removed
                      and e.properties.get("custody_event_id") not in removed and e.properties.get("end_evidence_id") not in removed}
    imported.gold = {k: dict(v) for k, v in world.gold.items()}
    items.sort(key=lambda item: (item["deliver_at"], item["feed_id"]))
    truth = {sid: build.truth[sid] for sid in sorted(included)}
    return imported, items, truth, live_start


def world_manifest(build, live_split, imported, items, truth):
    """Scenario weighting and provenance of one export (separate from the frozen V2 manifest)."""
    config = build.config
    rates = {}
    for split in WORLD_SPLITS:
        sids = [sid for sid, s in build.shipments.items() if s.split == split]
        per_type = defaultdict(set)
        for sid in sids:
            for m in build.truth[sid]["mechanisms"]:
                per_type[m["type"]].add(sid)
        rates[split] = {"shipments": len(sids), "days": config.days_of(split),
                        "affected_shipments": {t: len(v) for t, v in sorted(per_type.items())},
                        "affected_share": {t: round(len(v) / max(1, len(sids)), 3) for t, v in sorted(per_type.items())}}
    instances = defaultdict(lambda: defaultdict(int))
    for mech in build.plan.items.values():
        instances[mech.type][mech.origin] += 1
    return {"world_version": WORLD_VERSION, "dataset_id": config.dataset_id, "seed": config.seed, "total": config.total,
            "days": config.days, "split_days": list(config.split_days), "start_date": config.start_date,
            "horizon_days": config.horizon_days, "live_split": live_split, "live_start": iso(config.live_start(live_split)),
            "v2_split_labels": labels_for(live_split), "synthetic": True,
            "scenario_weighting": {"note": "Committed over-sampling rates (world/config.py MECHANISM_RATES): scenario weighting, "
                                           "not real frequencies. target = max(1, round(rate x shipments in the split)).",
                                   "rates": {m: {"history": h, "live": l} for m, h, l in config.rates},
                                   "targets": {split: {m: config.target(m, split, rates[split]["shipments"]) for m, _, _ in config.rates}
                                               for split in WORLD_SPLITS},
                                   "achieved": rates,
                                   "instances": {t: dict(v) for t, v in sorted(instances.items())}},
            "precedents": {"authored": build.history_reports.get(live_split, {}).get("authored"),
                           "not_imported_by_reason": dict(Counter(build.history_reports.get(live_split, {}).get("not_imported", {}).values()))},
            "counts": {"imported_nodes": len(imported.nodes), "imported_edges": len(imported.edges), "feed_items": len(items),
                       "shipments": dict(sorted(defaultdict(int, {k: sum(1 for r in truth.values() if r["split"] == k) for k in WORLD_SPLITS}).items()))},
            "hashes": {"truth": digest([truth[k] for k in sorted(truth)]), "feed": digest(items), "v2_manifest": digest(imported.manifest())},
            "scheduler_rounds": build.rounds, "timings_seconds": build.timings}
