"""Private truth labels: what happened to each shipment, what discriminates it, and what would resolve it.

Per shipment: whether it is healthy, every mechanism that CAUSED something on it (type, cause code from the
current catalogue, start and end, the evidence it produced, the resolution it permits and the catalogue
action), a DISCRIMINATION SPEC per mechanism, the mechanisms that only touched it without consequence
(`exposures`, never scored), and a compatibility view with the live-network truth fields (split, healthy,
root_cause, acceptable_causes, expected_resolution, physical) so existing scoring code can read it. Every row
carries the world's canary token (addendum B2); the isolation scans require it never to appear in anything the
runtime can see.

Cause, not touch. A mechanism is in `mechanisms` only where it produced a deviation on this shipment: a missed
connection, route or deadline, a record held past a monitor deadline, a tolerance breach, a failed or
misrecorded handover (world.physical and world.observe.held_past_deadline decide it from the physical log).
Every failed attempt has a cause: the scheduled mechanism that produced it, or an ordinary one
(ROUTINE_FAILED_ATTEMPT, by the reason of the attempt; it needs an answer only when the shipment missed its
promise or the monitor's rules flag the attempt). acceptable_causes are built from the causing mechanisms that
explain the opening rule codes of the case (mechanisms.RULE_CODES), not from everything on the shipment.

Discrimination spec (addendum A1). knowable is not "first evidence reaching the gateway". For each mechanism
on a shipment, `discrimination` lists the evidence that separates it from the other mechanisms that produce
the same opening symptoms:

  {"opening_symptoms": [...], "shares_opening_with": [cause codes], "alternative_mechanisms": [types],
   "any_of": [{"all_of": [item, ...]}, ...]}

  item = {"record": evidence_id}       satisfied once that record has been ingested
       | {"absence": {"expected", "match", "expected_by", "threshold_seconds", "overdue_at", "cancelled_by"}}
                                       satisfied at t when t >= overdue_at (the expected observation is overdue
                                       by the monitor's 900 s threshold) and no record in cancelled_by (every
                                       record in this world matching `match`) has been ingested

Every group holds at least one item tied to the shipment itself: one of its own records (its weighing on that
scale, its record made through that device, its scan at that facility, its load on that trip, its attempt in
that closure) or an absence about its own parcel. A shared record alone (a heartbeat, a throughput report,
another parcel's weighing) never makes a cause knowable for a shipment, so nothing is knowable before the
shipment is booked or before the linking record has arrived.

A mechanism is identifiable at t when every item of at least one group is satisfied. labels_at(row, t,
ingested) decides this from a run's actual ingestion log: `ingested` is the set of evidence ids recorded at
or before t (an imported record counts from its own recorded_at, a fed record from its ingestion). If nothing
discriminates any mechanism of an abnormal shipment at t, INSUFFICIENT_EVIDENCE is the correct answer.
knowable_at_estimate is only a generator-side convenience: the earliest t at which the spec is satisfied if
every record is ingested at its provider-feed delivery time (dataset_v2.feed lag rule); scorers use labels_at.

Truth rows are built per export (TruthBuilder(build, included)): a spec cites only records of shipments that
export contains, so every estimate can be reached in a run of that export.
"""
from collections import defaultdict
from datetime import timedelta
import hashlib

from dataset_v2.contracts import instant, iso
from operations.store import DETECTION_ALLOWANCE_SECONDS
from world.config import local_dt
from world.mechanisms import CATALOGUE, CLAIM_SUBTYPE, RULE_CODES, cause_of, resolution_of
from world.monitor import deliver_at

TRUTH_SCHEMA = "world-truth-3"
THRESHOLD = timedelta(seconds=DETECTION_ALLOWANCE_SECONDS)
STOCK_CHECK = "21:30"
STOCK_CHECK_SPAN = timedelta(minutes=30)
RESOLUTION_ORDER = {"NONE": 0, "AUTO": 1, "APPROVAL": 2, "HUMAN": 3}
COMPAT_PHYSICAL = {
    "DEVICE_OUTAGE": {"device": "buffered_upload"}, "PARTIAL_UPLOAD_LOSS": {"device": "buffered_upload"},
    "SCAN_SKIPPED_AT_RECEIPT": {"parcel": "received_unscanned"}, "FACILITY_BACKLOG": {"parcel": "at_origin_hub_delayed"},
    "LATE_LINEHAUL": {"parcel": "on_late_trip"}, "MISSORT": {"parcel": "routed_to_wrong_site"},
    "ASSIGNED_NOT_LOADED": {"parcel": "left_at_depot"}, "DELIVERY_SCAN_SKIPPED": {"parcel": "delivered_unscanned"},
    "RETURN_SCAN_SKIPPED": {"parcel": "returned_unscanned"},
    "CONTRACTOR_RETAINS": {"parcel": "retained_by_contractor", "contractor": "unresponsive"},
    "UNRECORDED_HANDOFF": {"parcel": "moved_between_drivers_unrecorded"}, "RECIPIENT_UNAVAILABLE": {"recipient": "unreachable"},
    "WRONG_ADDRESS": {"recipient": "confirms_address"}, "WRONG_GATE": {"recipient": "confirms_address"},
    "OTP_NOT_RECEIVED": {"recipient": "code_not_delivered"}, "NEIGHBOUR_RECEIVES": {"parcel": "with_unauthorised_person"},
    "MISDELIVERY": {"parcel": "left_at_wrong_building"}, "LABEL_MISREAD": {"label": "misread"},
    "WRONG_LABEL_APPLIED": {"label": "wrong_label"}, "SCALE_DRIFT": {"scale": "miscalibrated"},
    "DECLARED_WEIGHT_WRONG": {"scale": "declared_weight_wrong"}, "MANIFEST_ERROR": {"parcel": "on_vehicle_manifest_error"},
    "TRAFFIC_DISRUPTION": {"recipient": "available_next_session"}, "CUSTOMER_COMPLAINT": {}, "DUPLICATE_EVENTS": {},
}
# What discriminates each mechanism from the others that open with the same symptoms (the README table's last column).
DISCRIMINATORS = {
    "DEVICE_OUTAGE": "a record of the shipment made through the device arriving long after it happened; or the device's heartbeats "
                     "overdue (two intervals plus 900 s), or its reconnect heartbeat reporting the buffered queue, together with a "
                     "record of the shipment that places its parcel with that device (its route, its facility, an inbound trip)",
    "PARTIAL_UPLOAD_LOSS": "the stuck record of the shipment arriving late; or heartbeats that keep arriving but report a pending "
                           "upload queue, together with a record of the shipment that places its parcel with that device",
    "SCAN_SKIPPED_AT_RECEIPT": "the parcel's next handling scan after the skipped receipt (it is physically there), together with the "
                               "on-time receipt scans of the other parcels in the same container (the device worked)",
    "FACILITY_BACKLOG": "the facility's throughput report for the hours of the backlog (processed far below what the shift could do, "
                        "the oldest item waiting for hours), together with the parcel's own scan at that facility",
    "LATE_LINEHAUL": "the carrier's trip status (departure delay notice, ETA revision) or its stationary positions, together with the "
                     "shipment's own record on that trip (its assignment, its container scan)",
    "MISSORT": "a receipt or handling scan of the parcel at a site other than its planned one; its assignment to a lane that is not "
               "in its journey plan",
    "ASSIGNED_NOT_LOADED": "no load confirmation of the parcel by the route's departure (overdue by 900 s) while the route's other "
                           "parcels were confirmed, or the evening stock-check scan finding it on the depot shelf",
    "DELIVERY_SCAN_SKIPPED": "the recipient's receipt confirmation, or: loaded on the route, the route checked in, no return scan of "
                             "the parcel by session end and no stock-check scan of it that evening",
    "RETURN_SCAN_SKIPPED": "the stock-check scan finding the parcel back on the depot shelf, or its load confirmation on a later route",
    "CONTRACTOR_RETAINS": "the parcel's load confirmation on the route, the driver app's heartbeats overdue and no check-in of the "
                          "route by session end plus grace (both overdue by 900 s)",
    "UNRECORDED_HANDOFF": "another driver's app recording the parcel the first driver loaded (the attempt names a route run, driver "
                          "and vehicle other than those of the job it was dispatched on)",
    "RECIPIENT_UNAVAILABLE": "the unanswered contact attempts recorded with the failed attempt",
    "WRONG_ADDRESS": "the recipient's dated address correction (or address report)",
    "WRONG_GATE": "the attempt's recorded gate, which differs from the delivery instruction's gate",
    "OTP_NOT_RECEIVED": "a failed SMS delivery report for the one-time code",
    "NEIGHBOUR_RECEIVES": "the handoff evidence naming a person other than the recipient, with no authorisation on record",
    "MISDELIVERY": "the proof or photo location away from the address, or the recipient's non-receipt report",
    "LABEL_MISREAD": "the next read of the same label, which returns the manifest barcode; at once when the read is one digit off "
                     "the manifest barcode (it fails the check digit, so no printed label reads so)",
    "WRONG_LABEL_APPLIED": "the next read of the same label, which returns the same other-order barcode; at once when the barcode "
                           "read is the manifest barcode of another parcel",
    "SCALE_DRIFT": "the parcel's own weighing together with another parcel weighed on the same scale in the window, also off its "
                   "declaration, or with the destination check weigh agreeing with the declaration",
    "DECLARED_WEIGHT_WRONG": "the parcel's own sort weighing together with the destination check weigh agreeing with it, or with a "
                             "nearby weighing on the same scale that agrees with its own declaration",
    "MANIFEST_ERROR": "the revised route manifest without the parcel (for a one-parcel shipment: an empty line), together with the "
                      "parcel's load confirmation on that route",
    "TRAFFIC_DISRUPTION": "the traffic incident report for the district together with the shipment's not-attempted stop in it",
    "ROUTINE_FAILED_ATTEMPT": "the failed attempt record itself (reason and contact attempts); no fault elsewhere",
    "CUSTOMER_COMPLAINT": "the recipient's message together with the delivery proof of the parcel",
    "DUPLICATE_EVENTS": "the retransmitted message has the identity of one already received (never a case)",
}


def canary_token(config) -> str:
    """A random-looking token derived from the seed, stored in every truth-label row (addendum B2)."""
    return "CNRY" + hashlib.sha256(f"suhail-world-canary|{config.seed}|{config.dataset_id}".encode()).hexdigest()[:24].upper()


def mechanism_resolution(mech):
    """(resolution, action) of one instance. An ordinary failed attempt that neither misses the promise nor is flagged
    by the monitor's rules needs no answer (the next session delivers)."""
    if mech.type == "ROUTINE_FAILED_ATTEMPT" and mech.params.get("benign"):
        return "NONE", None
    return resolution_of(mech.type, mech.subtype)


# ---------------------------------------------------------------------- spec evaluation (scorer side)
def _when(t):
    return instant(t) if isinstance(t, str) else t


def item_satisfied(item, when, ingested) -> bool:
    if "record" in item:
        return item["record"] in ingested
    absence = item["absence"]
    return _when(when) >= instant(absence["overdue_at"]) and not any(n in ingested for n in absence["cancelled_by"])


def discriminated(spec, when, ingested) -> bool:
    when = _when(when)
    return any(group["all_of"] and all(item_satisfied(i, when, ingested) for i in group["all_of"]) for group in spec["any_of"])


def labels_at(row, t, ingested):
    """Causes identifiable at instant t given `ingested`, the evidence ids recorded at or before t.

    [] for a healthy shipment, ["INSUFFICIENT_EVIDENCE"] for an abnormal one whose mechanisms nothing
    discriminates yet."""
    when = _when(t)
    causes = sorted({m["cause_code"] for m in row["mechanisms"]
                     if m["cause_code"] and m["resolution"] != "NONE" and discriminated(m["discrimination"], when, ingested)})
    if causes:
        return causes
    return [] if row["healthy"] else ["INSUFFICIENT_EVIDENCE"]


def labels_at_estimate(row, t):
    """Convenience only (generator-side estimate from feed delivery times); scorers use labels_at."""
    when = _when(t)
    causes = sorted({m["cause_code"] for m in row["mechanisms"] if m["cause_code"] and m["resolution"] != "NONE"
                     and m["knowable_at_estimate"] and instant(m["knowable_at_estimate"]) <= when})
    if causes:
        return causes
    return [] if row["healthy"] else ["INSUFFICIENT_EVIDENCE"]


def spec_estimate(spec, delivered):
    """Earliest instant the spec is satisfied when record r is ingested at delivered[r] (None if never)."""
    best = None
    for group in spec["any_of"]:
        times = []
        for item in group["all_of"]:
            if "record" in item:
                times.append(delivered.get(item["record"]))
            else:
                absence = item["absence"]
                cancel = [delivered[n] for n in absence["cancelled_by"] if n in delivered]
                overdue = instant(absence["overdue_at"])
                times.append(None if cancel and min(cancel) <= overdue else overdue)
        if group["all_of"] and None not in times:
            best = max(times) if best is None else min(best, max(times))
    return best


def match_node(node, match) -> bool:
    """Does a record satisfy an absence item's expectation? (kind, equal properties, occurred window)."""
    if node.kind != match["kind"]:
        return False
    p = node.properties
    for key, value in match.items():
        if key == "kind":
            continue
        if key == "occurred_after":
            if not p.get("occurred_at") or instant(p["occurred_at"]) <= instant(value):
                return False
        elif key == "occurred_until":
            if not p.get("occurred_at") or instant(p["occurred_at"]) > instant(value):
                return False
        elif p.get(key) != value:
            return False
    return True


def own_item(item, sid, packages, owner_of) -> bool:
    """Is this spec item tied to the shipment itself (its own record, or an absence about its own parcel)?"""
    if "record" in item:
        return owner_of(item["record"]) == sid
    return item["absence"]["match"].get("package_id") in packages


def _record(nid):
    return {"record": nid} if nid else None


def _absence(expected, match, expected_by, cancelled_by):
    return {"absence": {"expected": expected, "match": match, "expected_by": iso(expected_by),
                        "threshold_seconds": DETECTION_ALLOWANCE_SECONDS, "overdue_at": iso(expected_by + THRESHOLD),
                        "cancelled_by": sorted(cancelled_by)}}


class TruthBuilder:
    def __init__(self, build, included=None):
        """included: shipments whose records a spec may cite (one export's shipments); None means the whole world."""
        self.b = build
        self.world, self.obs, self.sim, self.plan = build.world, build.observer, build.sim, build.plan
        self.included = set(build.shipments) if included is None else set(included)
        self.deliver = {}
        usable = {}
        for nid, meta in self.obs.records.items():
            node = self.world.nodes.get(nid)
            if node is None or (meta["sid"] and meta["sid"] not in self.included):
                continue
            usable[nid] = meta
            if node.properties.get("recorded_at"):
                self.deliver[nid] = deliver_at(node)
        self.usable = usable
        self.by_mech_ship = defaultdict(list)          # (mid, sid) -> evidence ids (owned)
        self.by_mech_shared = defaultdict(list)        # mid -> shared evidence ids
        self.records_of = defaultdict(list)
        self.by_route = defaultdict(list)
        self.by_package = defaultdict(list)
        self.weighs = defaultdict(list)
        self.receipts_by_container = defaultdict(list)
        self.beats = defaultdict(list)
        for nid, meta in sorted(usable.items()):
            for mid in meta["mech"]:
                if meta["sid"]:
                    self.by_mech_ship[(mid, meta["sid"])].append(nid)
                else:
                    self.by_mech_shared[mid].append(nid)
            node = self.world.nodes[nid]
            p = node.properties
            if meta["sid"]:
                self.records_of[meta["sid"]].append(nid)
                if p.get("route_run_id"):
                    self.by_route[p["route_run_id"]].append(nid)
                if p.get("package_id"):
                    self.by_package[p["package_id"]].append(nid)
                if node.kind == "ScanEvent" and p.get("observation_type") in ("HANDHELD_RECEIPT", "CONTAINER_SCAN") and p.get("container_id"):
                    self.receipts_by_container[p["container_id"]].append(nid)
                if node.kind == "ScanEvent" and p.get("observation_type") == "SCALE_WEIGH":
                    self.weighs[p["device_ref"]].append(nid)
            elif node.kind == "DeviceHeartbeat":
                self.beats[p["device_id"]].append(nid)
        self.openings = getattr(build, "first_opening", {})
        self.per_ship = defaultdict(list)
        for mid in sorted(build.caused):
            for sid in sorted(build.caused[mid]):
                self.per_ship[sid].append(mid)
        self.alternatives = self.opening_alternatives()

    # ------------------------------------------------------------------ helpers
    def occurred(self, nid):
        return self.obs.records[nid]["occurred"]

    def owner(self, nid):
        meta = self.obs.records.get(nid)
        return meta["sid"] if meta else None

    def props(self, nid):
        return self.world.nodes[nid].properties

    def kind(self, nid):
        return self.world.nodes[nid].kind

    def first(self, ids):
        ids = [n for n in ids if n in self.deliver]
        return min(ids, key=lambda n: (self.deliver[n], n)) if ids else None

    def pick(self, ids, kinds, **equal):
        return self.first([n for n in ids if self.kind(n) in kinds and all(self.props(n).get(k) == v for k, v in equal.items())])

    def scans(self, pid, observation_type, **equal):
        return [n for n in self.by_package.get(pid, []) if self.kind(n) == "ScanEvent"
                and self.props(n).get("observation_type") == observation_type and all(self.props(n).get(k) == v for k, v in equal.items())]

    def cancelled(self, candidates, match):
        return [n for n in candidates if match_node(self.world.nodes[n], match)]

    def parcel_of(self, mech, sid):
        pid = mech.params.get("pid")
        if pid:
            return pid
        touched = sorted(p.pid for p in self.b.shipments[sid].parcels if p.pid in self.sim.touch.get(mech.mid, set()))
        return touched[0] if touched else self.b.shipments[sid].parcels[0].pid

    def explains(self, mech, codes):
        return bool(set(RULE_CODES[mech.type]) & set(codes))

    def opening_alternatives(self):
        """Opening symptom set -> (cause codes, mechanism types) of the mechanisms that explain cases opening with it."""
        out = defaultdict(lambda: (set(), set()))
        for sid, opening in self.openings.items():
            key = tuple(opening["symptoms"])
            for mid in self.per_ship.get(sid, ()):
                mech = self.plan.items[mid]
                cause, _ = cause_of(mech.type, mech.subtype)
                if mechanism_resolution(mech)[0] != "NONE" and cause and self.explains(mech, opening["codes"]):
                    out[key][0].add(cause)
                    out[key][1].add(mech.type)
        return dict(out)

    def link(self, sid, mid, device):
        """The shipment's earliest record, not shaped by this mechanism, that places its parcel with the device: made
        through it, on the route run of its driver app, at its facility, or on a trip to its facility."""
        info = self.b.network.devices.get(device)
        facility = info.facility_id if info else None
        nodes = self.world.nodes

        def places(nid):
            p = nodes[nid].properties
            if mid in self.obs.records[nid]["mech"]:
                return False
            if p.get("device_ref") == device or (facility and p.get("facility_id") == facility):
                return True
            route = self.sim.routes.get(p.get("route_run_id")) if p.get("route_run_id") else None
            if route is not None and route.device == device:
                return True
            trip = self.b.network.trips.get(p.get("trip_id")) if p.get("trip_id") else None
            return bool(facility and trip is not None and trip.destination == facility)
        return self.first([n for n in self.records_of[sid] if places(n)])

    # ------------------------------------------------------------------ evidence the mechanism shaped
    def evidence(self, mech, sid):
        """(own evidence ids, shared evidence ids): every record the mechanism shaped for this shipment."""
        mid, mtype = mech.mid, mech.type
        own = set(self.by_mech_ship.get((mid, sid), []))
        nodes = self.world.nodes
        # What a driver app records with an attempt the mechanism shaped (the calls, the proof and its parts) is shaped
        # by it too: the proof location of a misdelivery, the handoff naming a neighbour.
        attempts = {n for n in own if nodes[n].kind == "DeliveryAttempt"}
        own = sorted(own | {n for n in self.records_of[sid] if nodes[n].properties.get("attempt_id") in attempts})
        shared = sorted(set(self.by_mech_shared.get(mid, [])))
        extra = shared
        if mtype in ("FACILITY_BACKLOG", "LATE_LINEHAUL", "TRAFFIC_DISRUPTION"):
            extra = sorted(shared, key=lambda n: (self.deliver.get(n, mech.started_at), n))[:8]
            if mtype == "LATE_LINEHAUL":
                trip = mech.params["trip"]
                own = sorted(set(own) | {n for n in self.records_of[sid] if nodes[n].properties.get("trip_id") == trip
                                         and nodes[n].kind in ("ScanEvent", "CustodyEvent", "VehicleAssignment")})
        elif mtype == "PARTIAL_UPLOAD_LOSS":
            extra = sorted(n for n in shared if nodes[n].kind == "DeviceHeartbeat")[:6]
        elif mtype == "DEVICE_OUTAGE":
            extra = sorted(n for n in shared if nodes[n].kind == "DeviceHeartbeat")[:6]
        elif mtype == "DUPLICATE_EVENTS":
            own, extra = sorted(n for n in mech.params.get("records", {}).get(sid, []) if n in self.usable), []
        return own, extra

    # ------------------------------------------------------------------ discrimination specs
    def spec(self, mech, sid, own, shared):
        mtype = mech.type
        groups = []

        def group(*items):
            if items and all(items):
                groups.append({"all_of": list(items)})

        if mtype == "DEVICE_OUTAGE":
            device = mech.params["device"]
            dev = self.b.network.devices[device]
            link = _record(self.link(sid, mech.mid, device))
            group(_record(self.first(own)))
            # The parcel's first record made through the device while it was offline: before that the shipment is not
            # affected, however silent the device is.
            affected_at = min((self.occurred(n) for n in own if self.occurred(n) is not None), default=None)
            if dev.telemetry != "NONE" and affected_at is not None:
                interval = timedelta(seconds=900 if dev.kind == "DRIVER_APP" else 1800)
                previous = [self.occurred(n) for n in self.beats.get(device, []) if self.occurred(n) < mech.started_at]
                last = max(previous, default=None)
                # A device that was beating goes visibly silent; one that was not (an app not yet logged in) is silent
                # from the outage start.
                base = last if last is not None and last >= mech.started_at - interval else mech.started_at
                expected_by = base + 2 * interval
                match = {"kind": "DeviceHeartbeat", "device_id": device, "occurred_after": iso(base), "occurred_until": iso(expected_by)}
                if affected_at <= expected_by + THRESHOLD:
                    group(_absence(f"two heartbeats from {device}", match, expected_by, self.cancelled(self.beats.get(device, []), match)), link)
            # The reconnect heartbeat reports what was buffered (it comes after every buffered record was made).
            reconnect = [n for n in self.by_mech_shared.get(mech.mid, []) if self.kind(n) == "DeviceHeartbeat"
                         and (affected_at is None or self.occurred(n) >= affected_at)]
            group(_record(self.first(reconnect)), link)
        elif mtype == "PARTIAL_UPLOAD_LOSS":
            group(_record(self.first(own)))
            # A heartbeat reporting a pending queue counts for this shipment only once its own record is in that queue.
            affected_at = min((self.occurred(n) for n in own if self.occurred(n) is not None), default=None)
            pending = [n for n in self.by_mech_shared.get(mech.mid, []) if self.kind(n) == "DeviceHeartbeat"
                       and affected_at is not None and self.occurred(n) >= affected_at]
            group(_record(self.first(pending)), _record(self.link(sid, mech.mid, mech.params["device"])))
        elif mtype == "SCAN_SKIPPED_AT_RECEIPT":
            pid = self.parcel_of(mech, sid)
            skipped, facility = self.skip_event(pid)
            after = [n for n in self.by_package.get(pid, []) if self.kind(n) in ("ScanEvent", "CustodyEvent") and self.occurred(n) >= skipped]
            mates = [n for n in self.container_mates_receipts(pid, facility) if self.owner(n) != sid]
            group(_record(self.first(after)), _record(mates[0] if mates else None))
            if not groups:
                # Nobody else's receipt to compare with (a container scanned by nobody, a parcel that came alone): the
                # parcel's next scan and the next custody record after it show it moved on without the receipt.
                later = sorted((n for n in after if n in self.deliver), key=lambda n: (self.deliver[n], n))
                group(_record(later[0] if later else None), _record(later[1] if len(later) > 1 else None))
        elif mtype == "FACILITY_BACKLOG":
            facility = mech.params["facility"]
            at_facility = [n for n in self.records_of[sid] if self.kind(n) == "ScanEvent" and self.props(n).get("facility_id") == facility
                           and self.occurred(n) >= mech.started_at - timedelta(hours=1)]
            group(_record(self.pick(shared, ("FacilityThroughput",))), _record(self.first(at_facility)))
        elif mtype == "LATE_LINEHAUL":
            trip = mech.params["trip"]
            on_trip = _record(self.first([n for n in self.records_of[sid] if self.props(n).get("trip_id") == trip]))
            status = [n for n in shared if self.kind(n) == "TripEvent" and self.props(n).get("event_type") in ("HELD_AT_ORIGIN", "ETA_REVISED")]
            group(_record(self.first(status)), on_trip)
            group(_record(self.pick(shared, ("GPSObservation",))), on_trip)
            if not groups:
                group(_record(self.pick(shared, ("TripEvent",))), on_trip)
        elif mtype == "TRAFFIC_DISRUPTION":
            group(_record(self.pick(shared, ("TrafficEvent",))), _record(self.pick(own, ("DeliveryAttempt",))))
        elif mtype in ("MISSORT", "UNRECORDED_HANDOFF"):
            group(_record(self.first(own)))
        elif mtype == "ASSIGNED_NOT_LOADED":
            pid = self.parcel_of(mech, sid)
            route = self.fault_route(mech, sid, pid)
            if route is not None and route.departed_at:
                loads = [n for n in self.route_records(route, exclude_sid=sid)
                         if self.kind(n) == "ScanEvent" and self.props(n).get("observation_type") == "LOAD_CONFIRMATION"]
                last_load = max(loads, key=lambda n: (self.deliver[n], n)) if loads else None
                match = {"kind": "ScanEvent", "package_id": pid, "observation_type": "LOAD_CONFIRMATION", "route_run_id": route.rid}
                group(_record(last_load), _absence(f"load confirmation of {pid} on {route.rid}", match, route.departed_at,
                                                   self.cancelled(self.by_package.get(pid, []), match)))
                found = [n for n in self.scans(pid, "INVENTORY_CHECK", facility_id=route.depot) if self.occurred(n) > route.departed_at]
                group(_record(self.first(found)))
        elif mtype == "DELIVERY_SCAN_SKIPPED":
            pid = self.parcel_of(mech, sid)
            group(_record(self.pick(own, ("RecipientReport",), report_code="RECEIVED_CONFIRMATION")))
            route = self.fault_route(mech, sid, pid)
            pid = next((e["pid"] for e in self.sim.events if e["type"] == "delivered_unrecorded" and route is not None
                        and e.get("route") == route.rid and e["pid"].startswith(sid + "-")), pid)
            if route is not None and route.departed_at:
                load = self.first(self.scans(pid, "LOAD_CONFIRMATION", route_run_id=route.rid))
                checkin = self.first([n for n in self.route_records(route, exclude_sid=sid) if self.kind(n) == "DepotReconciliation"
                                      or (self.kind(n) == "ScanEvent" and self.props(n).get("observation_type") == "RETURN_SCAN")])
                session_end = local_dt(route.date, self.b.config.session_end) + timedelta(minutes=self.b.config.reconciliation_grace_minutes)
                stock_by = local_dt(route.date, STOCK_CHECK) + STOCK_CHECK_SPAN
                returned = {"kind": "ScanEvent", "package_id": pid, "observation_type": "RETURN_SCAN", "route_run_id": route.rid}
                shelf = {"kind": "ScanEvent", "package_id": pid, "observation_type": "INVENTORY_CHECK", "facility_id": route.depot,
                         "occurred_after": iso(route.departed_at), "occurred_until": iso(stock_by)}
                candidates = self.by_package.get(pid, [])
                group(_record(load), _record(checkin),
                      _absence(f"return scan of {pid} from {route.rid}", returned, session_end, self.cancelled(candidates, returned)),
                      _absence(f"stock-check scan of {pid} at {route.depot}", shelf, stock_by, self.cancelled(candidates, shelf)))
        elif mtype == "RETURN_SCAN_SKIPPED":
            pid = self.parcel_of(mech, sid)
            route = self.fault_route(mech, sid, pid)
            since = route.departed_at if route is not None and route.departed_at else mech.started_at
            group(_record(self.first([n for n in self.scans(pid, "INVENTORY_CHECK") if self.occurred(n) > since])))
            # Not seen by a stock check (it sat in the returns cage): its next load confirmation at the depot, on a later
            # route, shows it had come back.
            again = [n for n in self.scans(pid, "LOAD_CONFIRMATION") if self.occurred(n) > since
                     and (route is None or self.props(n).get("route_run_id") != route.rid)]
            group(_record(self.first(again)))
        elif mtype == "CONTRACTOR_RETAINS":
            pid = self.parcel_of(mech, sid)
            route = self.fault_route(mech, sid, pid)
            if route is not None and route.login_at:
                items = [_record(self.first(self.scans(pid, "LOAD_CONFIRMATION", route_run_id=route.rid)))]
                device = route.device
                window_end = (route.returned_at or route.login_at) + timedelta(hours=1)
                beats = [n for n in self.beats.get(device, []) if route.login_at <= self.occurred(n) <= window_end]
                if beats:
                    last = max(self.occurred(n) for n in beats)
                    expected_by = last + timedelta(seconds=1800)
                    match = {"kind": "DeviceHeartbeat", "device_id": device, "occurred_after": iso(last), "occurred_until": iso(expected_by)}
                    items.append(_absence(f"two heartbeats from {device}", match, expected_by, self.cancelled(self.beats.get(device, []), match)))
                session_end = local_dt(route.date, self.b.config.session_end) + timedelta(minutes=self.b.config.reconciliation_grace_minutes)
                match = {"kind": "ScanEvent", "observation_type": "RETURN_SCAN", "route_run_id": route.rid, "occurred_until": iso(session_end)}
                items.append(_absence(f"check-in of route {route.rid}", match, session_end, self.cancelled(self.by_route.get(route.rid, []), match)))
                group(*items)
        elif mtype == "RECIPIENT_UNAVAILABLE":
            group(_record(self.pick(own, ("ContactAttempt",))))
            if not groups:
                group(_record(self.first(own)))
        elif mtype == "WRONG_ADDRESS":
            group(_record(self.pick(own, ("AddressVersion",))))
            group(_record(self.pick(own, ("RecipientReport",))))
            if not groups:
                group(_record(self.first(own)))
        elif mtype == "WRONG_GATE":
            group(_record(self.pick(own, ("DeliveryAttempt",))))
        elif mtype == "OTP_NOT_RECEIVED":
            group(_record(self.pick(own, ("CommunicationEvent",), delivery_status="FAILED")))
            if not groups:
                group(_record(self.first(own)))
        elif mtype == "NEIGHBOUR_RECEIVES":
            group(_record(self.pick(own, ("HandoffEvidence",))))
            if not groups:
                group(_record(self.first(own)))
        elif mtype == "MISDELIVERY":
            group(_record(self.pick(own, ("DeliveryProof", "PhotoEvidence"))))
            group(_record(self.pick(own, ("RecipientReport",))))
        elif mtype in ("LABEL_MISREAD", "WRONG_LABEL_APPLIED"):
            for pid in sorted(p.pid for p in self.b.shipments[sid].parcels if p.pid in self.sim.touch.get(mech.mid, set())):
                reads = sorted((n for n in self.by_package.get(pid, []) if self.kind(n) == "ScanEvent" and self.props(n).get("observed_barcode")),
                               key=lambda n: (self.occurred(n), n))
                marked = [n for n in reads if n in set(own)]
                if marked:
                    anchor = marked[0]
                    later = [n for n in reads if (self.occurred(n), n) > (self.occurred(anchor), anchor)]
                    group(_record(later[0] if later else None))
                    expected = self.world.nodes[pid].properties["manifest_barcode"]
                    off = sum(1 for x, y in zip(self.props(anchor)["observed_barcode"], expected) if x != y)
                    if mtype == "WRONG_LABEL_APPLIED" and self.sim.label_source.get(pid) == "other_parcel":
                        group(_record(anchor))   # The read returns another parcel's manifest barcode: no misread does that.
                    elif mtype == "LABEL_MISREAD" and off == 1:
                        group(_record(anchor))   # One digit off fails the barcode's check digit: no printed label reads so.
        elif mtype == "SCALE_DRIFT":
            pid = self.parcel_of(mech, sid)
            weighs = sorted(self.scans(pid, "SCALE_WEIGH"), key=lambda n: (self.occurred(n), n))
            marked = [n for n in weighs if n in set(own)]
            if marked:
                scale = self.props(marked[0])["device_ref"]
                others = [n for n in self.weighs.get(scale, []) if self.owner(n) != sid and mech.mid in self.obs.records[n]["mech"]]
                group(_record(marked[0]), _record(self.first(others)))
                checks = [n for n in weighs if self.props(n)["device_ref"] != scale]
                group(_record(marked[0]), _record(self.first(checks)))
        elif mtype == "DECLARED_WEIGHT_WRONG":
            pid = self.parcel_of(mech, sid)
            weighs = sorted(self.scans(pid, "SCALE_WEIGH"), key=lambda n: (self.occurred(n), n))
            if weighs:
                scale, at = self.props(weighs[0])["device_ref"], self.occurred(weighs[0])
                group(_record(weighs[0]), _record(weighs[1] if len(weighs) > 1 else None))
                normal = [n for n in self.weighs.get(scale, []) if self.owner(n) != sid and not self.obs.records[n]["mech"]
                          and abs((self.occurred(n) - at).total_seconds()) <= 7200]
                if normal:
                    group(_record(weighs[0]), _record(min(normal, key=lambda n: (abs((self.occurred(n) - at).total_seconds()), n))))
        elif mtype == "MANIFEST_ERROR":
            revised = self.pick(own, ("Manifest",))
            if revised:
                route = self.props(revised).get("route_manifest_ref")
                pid = self.parcel_of(mech, sid)
                group(_record(revised), _record(self.first(self.scans(pid, "LOAD_CONFIRMATION", route_run_id=route))))
        elif mtype == "ROUTINE_FAILED_ATTEMPT":
            group(_record(self.pick(own, ("DeliveryAttempt",))))
            if not groups:
                group(_record(self.first(own)))
        elif mtype == "CUSTOMER_COMPLAINT":
            reports = [n for n in own if self.kind(n) == "RecipientReport"]
            report = self.first([n for n in reports if self.occurred(n) >= mech.started_at]) or self.first(reports)
            proof = self.first([n for n in self.records_of[sid] if self.kind(n) == "DeliveryProof"]) if mech.subtype == CLAIM_SUBTYPE else None
            if mech.subtype == CLAIM_SUBTYPE:
                group(_record(report), _record(proof))
            else:
                group(_record(report))
        elif mtype == "DUPLICATE_EVENTS":
            group(_record(self.first(own)))
        return groups

    def skip_event(self, pid):
        for row in self.sim.events:
            if row["type"] == "received_unscanned" and row.get("pid") == pid:
                return row["t"], row.get("depot") or row.get("hub")
        state = self.sim.p[pid]
        return state.timeline[0][0], None

    def container_mates_receipts(self, pid, facility):
        """On-time receipt scans of the other parcels that arrived in the same container (another shipment's records)."""
        out = []
        for c in sorted(self.sim.containers.values(), key=lambda c: c.cid):
            if pid in c.parcels:
                out += [n for n in self.receipts_by_container.get(c.cid, [])
                        if facility is None or self.props(n).get("facility_id") == facility]
        return sorted(set(out), key=lambda n: (self.deliver.get(n), n))

    def fault_route(self, mech, sid, pid):
        """The route on which the fault acted (a parcel can ride several routes; the latest is not always the one)."""
        if mech.params.get("route"):
            return self.sim.routes.get(mech.params["route"])
        state = self.sim.p.get(pid) if pid else None
        if state and state.route:
            return self.sim.routes.get(state.route)
        for parcel in self.b.shipments[sid].parcels:
            route = self.sim.p[parcel.pid].route
            if route:
                return self.sim.routes.get(route)
        return None

    def route_records(self, route, exclude_sid=None):
        return [nid for nid in self.by_route.get(route.rid, []) if self.obs.records[nid]["sid"] != exclude_sid]

    # ------------------------------------------------------------------ rows
    def rows(self):
        """Truth rows by shipment, for the included shipments."""
        canary = canary_token(self.b.config)
        exposed = defaultdict(list)
        for mid in sorted(self.b.exposed):
            for sid in self.b.exposed[mid]:
                exposed[sid].append(mid)
        out = {}
        for sid in sorted(self.included):
            s = self.b.shipments[sid]
            packages = {p.pid for p in s.parcels}
            opening = self.openings.get(sid)
            symptoms = list(opening["symptoms"]) if opening else []
            alt_causes, alt_types = self.alternatives.get(tuple(symptoms), (set(), set())) if opening else (set(), set())
            mechs = []
            for mid in self.per_ship.get(sid, []):
                mech = self.plan.items[mid]
                own, shared = self.evidence(mech, sid)
                resolution, action = mechanism_resolution(mech)
                cause, acceptable = cause_of(mech.type, mech.subtype)
                groups = self.spec(mech, sid, own, shared)
                # A group counts only when it holds something of the shipment's own.
                groups = [g for g in groups if any(own_item(i, sid, packages, self.owner) for i in g["all_of"])]
                spec = {"opening_symptoms": symptoms, "shares_opening_with": sorted(alt_causes - {cause}),
                        "alternative_mechanisms": sorted(alt_types - {mech.type}), "any_of": groups}
                estimate = spec_estimate(spec, self.deliver)
                mechs.append({"mechanism_id": mid, "type": mech.type, "subtype": mech.subtype, "origin": mech.origin,
                              "cause_code": cause, "acceptable_causes": acceptable, "resolution": resolution, "action": action,
                              "fault": CATALOGUE[mech.type][4] or (mech.type == "CUSTOMER_COMPLAINT" and mech.subtype == CLAIM_SUBTYPE),
                              "explains_opening": bool(opening) and resolution != "NONE" and self.explains(mech, opening["codes"]),
                              "started_at": iso(mech.started_at) if mech.started_at else None,
                              "ended_at": iso(mech.ended_at) if mech.ended_at else None,
                              "discrimination": spec, "knowable_at_estimate": iso(estimate) if estimate else None,
                              "evidence_ids": own, "shared_evidence_ids": shared,
                              "packages": sorted(p for p in packages if p in self.sim.touch.get(mid, set())) or sorted(packages)})
            mechs.sort(key=lambda m: (m["knowable_at_estimate"] or "9999", m["mechanism_id"]))
            actionable = [m for m in mechs if m["resolution"] != "NONE"]
            explaining = [m for m in actionable if m["explains_opening"]] if opening else actionable
            scored = explaining or actionable
            primary = scored[0] if scored else None
            physical = dict(COMPAT_PHYSICAL.get(primary["type"], {})) if primary else {}
            if primary and primary["type"] in ("DEVICE_OUTAGE", "PARTIAL_UPLOAD_LOSS"):
                mech = self.plan.items[primary["mechanism_id"]]
                physical.update(device_id=mech.params["device"], offline_from=iso(mech.started_at), natural_reconnect_at=iso(mech.ended_at),
                                buffered_event_ids=primary["evidence_ids"])
            if primary and primary["type"] in ("ASSIGNED_NOT_LOADED", "RETURN_SCAN_SKIPPED"):
                physical["depot_id"] = s.depot
            out[sid] = {
                "truth_schema": TRUTH_SCHEMA, "canary": canary,
                "shipment_id": sid, "split": s.split, "booking_day": s.day, "booked_at": iso(s.booked_at), "promise_at": iso(s.promise_at),
                "service": s.service, "flow": s.flow, "healthy": not actionable,
                "physically_healthy": not any(m["fault"] for m in mechs), "mechanisms": mechs,
                # Touched without consequence: listed for the record, never scored, never a label.
                "exposures": [{"mechanism_id": mid, "type": self.plan.items[mid].type, "subtype": self.plan.items[mid].subtype,
                               "origin": self.plan.items[mid].origin} for mid in sorted(exposed.get(sid, []))],
                "first_opening": dict(opening) if opening else None,
                # An opened case none of the shipment's causes explains (the monitor's rules fired on ordinary variation).
                "opening_explained": bool(explaining) if opening and actionable else None,
                # Compatibility view (live-network truth fields).
                "recipe": primary["type"].lower() if primary else "healthy", "root_cause": primary["cause_code"] if primary else None,
                "acceptable_causes": sorted({c for m in scored for c in m["acceptable_causes"]}),
                "expected_resolution": max((m["resolution"] for m in scored), key=RESOLUTION_ORDER.get, default="NONE"),
                "physical": physical, "key_evidence": primary["evidence_ids"][:20] if primary else [],
                "secondary_issue": next((m["cause_code"] for m in actionable if m is not primary and m["cause_code"] != primary["cause_code"]), None) if primary else None,
                "knowable_at_estimate": primary["knowable_at_estimate"] if primary else None,
                "final_location": self.final_location(s),
            }
        return out

    def final_location(self, s):
        rows = []
        for p in s.parcels:
            t, kind, ref = self.sim.p[p.pid].timeline[-1]
            if kind == "PERSON" and not ref.startswith("DEMO-"):
                ref = "PRIVATE_PERSON"
            rows.append({"package_id": p.pid, "at": iso(t), "kind": kind, "ref": ref})
        return rows
