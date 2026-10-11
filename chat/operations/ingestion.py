"""Provider gateway: normalize delivered feed messages into canonical, provenance-stamped evidence.

A message becomes visible to Suhail only when the simulation clock reaches its delivery time.
The gateway decodes the channel's format, resolves provider references (barcodes, tracking
numbers), de-duplicates by source event identity, and writes one immutable evidence node
(:V2Entity:<Kind>:LiveIngested).

Three times are kept apart. occurred_at stays the provider's event time. recorded_at is when the
provider delivered the message to the gateway (the feed's deliver_at), not the clock tick at which
the gateway got round to it: a coarse tick must not make an ordinary record look an hour late.
ingested_at is that tick. A late upload stays visibly late (its delivery time is late), and no
record is ever back-dated: recorded_at is never before occurred_at, never after the tick, and a
message that turns up with a delivery time at or before a clock the gateway had already drained
(one enqueued late) is stamped at the tick instead, so a snapshot taken earlier can never gain a
record afterwards.

Every message, including duplicates and rejects, keeps its raw payload and outcome on its
ProviderFeedItem. No truth, gold or scenario data is read here.
"""
import json
from datetime import timedelta

from dataset_v2.contracts import ALIASES, SCHEMA_VERSION, UTC_FIELDS, digest, instant
from dataset_v2.feed import INGESTIBLE_KINDS, Reference, decode, ingestible_kinds

INGEST_SOURCE_REF = "live-ingestion-1"
# (kind, property, relationship, outward): outward means (node)-[rel]->(referenced), else (referenced)-[rel]->(node).
EDGE_RULES = (
    ("ScanEvent", "package_id", "HAS_SCAN", False),
    ("CustodyEvent", "package_id", "HAS_CUSTODY_EVENT", False), ("CustodyEvent", "source_event_id", "OBSERVED_BY", True),
    ("CustodyEvent", "from_id", "FROM_CUSTODIAN", True), ("CustodyEvent", "to_id", "TO_CUSTODIAN", True),
    ("DeliveryAttempt", "package_id", "HAS_ATTEMPT", False), ("DeliveryAttempt", "used_address_version_id", "USED_ADDRESS", True),
    ("ContactAttempt", "attempt_id", "HAS_CONTACT", False), ("DeliveryProof", "attempt_id", "HAS_PROOF", False),
    ("DeliveryProof", "authentication_id", "HAS_AUTHENTICATION", True), ("DeliveryProof", "signature_id", "HAS_SIGNATURE", True),
    ("DeliveryProof", "photo_id", "HAS_PHOTO", True), ("DeliveryProof", "handoff_id", "HAS_HANDOFF", True),
    ("RecipientReport", "shipment_id", "HAS_REPORT", False), ("RecipientReport", "pin_id", "HAS_PIN", True),
    ("DepotReconciliation", "shipment_id", "HAS_RECONCILIATION", False), ("StatusEvent", "shipment_id", "HAS_STATUS", False),
    ("GPSObservation", "vehicle_id", "HAS_TELEMETRY", False), ("DeviceHeartbeat", "device_id", "HAS_TELEMETRY", False),
    ("Manifest", "assignment_id", "HAS_MANIFEST", False), ("Manifest", "package_ids", "LISTS", True),
    ("Manifest", "supersedes_id", "SUPERSEDES", True), ("LocationPin", "address_version_id", "HAS_PIN", False),
    ("TrafficObservation", "segment_id", "HAS_DELAY_EVIDENCE", False),
    # Mechanism world (chat/world), additive: a parcel's record links to the shared container, trip or route
    # run it shared with other parcels; shared observations link to their facility, trip or city; dated
    # per-shipment context (sessions, assignments, corrected addresses) links like its imported equivalent.
    # None of these properties or kinds occur in the live-network dataset.
    ("ScanEvent", "container_id", "IN_CONTAINER", True), ("CustodyEvent", "trip_id", "ON_TRIP", True),
    ("CustodyEvent", "route_run_id", "ON_ROUTE_RUN", True), ("DeliveryAttempt", "route_run_id", "ON_ROUTE_RUN", True),
    ("Manifest", "route_manifest_ref", "ON_ROUTE_RUN", True), ("CommunicationEvent", "shipment_id", "HAS_COMMUNICATION", False),
    ("FacilityThroughput", "facility_id", "HAS_THROUGHPUT", False), ("TripEvent", "trip_id", "HAS_TRIP_EVENT", False),
    ("GPSObservation", "trip_id", "ON_TRIP", True), ("GPSObservation", "route_run_id", "ON_ROUTE_RUN", True),
    ("TrafficEvent", "city_id", "IN_CITY", True),
    ("AddressVersion", "address_id", "VERSION_OF", True), ("AddressVersion", "supersedes_id", "SUPERSEDES", True),
    ("AddressVersion", "shipment_id", "HAS_ADDRESS_VERSION", False),
    ("DeliverySession", "depot_id", "AT_FACILITY", True), ("DeliverySession", "route_run_id", "ON_ROUTE_RUN", True),
    ("VehicleAssignment", "vehicle_id", "USES_VEHICLE", True), ("VehicleAssignment", "driver_id", "ASSIGNED_DRIVER", True),
    ("VehicleAssignment", "session_id", "IN_SESSION", True), ("VehicleAssignment", "package_ids", "CARRIES", True),
    ("VehicleAssignment", "route_run_id", "ON_ROUTE_RUN", True), ("VehicleAssignment", "trip_id", "ON_TRIP", True),
    # Mechanism world, additive: shared transport records created after the live start arrive as messages and link
    # like their imported equivalents (a trip to its lane, vehicle, driver, ends and provider; a container to its
    # ends; a route run to its depot, vehicle, driver and driver app).
    ("Trip", "lane_id", "ON_LANE", True), ("Trip", "vehicle_id", "USES_VEHICLE", True), ("Trip", "driver_id", "ASSIGNED_DRIVER", True),
    ("Trip", "from_facility_id", "FROM", True), ("Trip", "to_facility_id", "TO", True), ("Trip", "provider_id", "OPERATED_BY", True),
    ("Container", "origin_facility_id", "FROM", True), ("Container", "destination_facility_id", "TO", True),
    ("RouteRun", "depot_id", "AT_FACILITY", True), ("RouteRun", "vehicle_id", "USES_VEHICLE", True),
    ("RouteRun", "driver_id", "ASSIGNED_DRIVER", True), ("RouteRun", "device_ref", "USES_DEVICE", True),
)


# Properties that reference other feed evidence (everything else references imported reference data).
REFERENCED_KIND = {"source_event_id": "ScanEvent", "attempt_id": "DeliveryAttempt", "authentication_id": "AuthenticationEvidence",
                   "signature_id": "SignatureEvidence", "photo_id": "PhotoEvidence", "handoff_id": "HandoffEvidence",
                   "pin_id": "LocationPin", "supersedes_id": "Manifest",
                   # Mechanism world: an assignment may arrive before the session it belongs to.
                   "session_id": "DeliverySession"}


def _neo(props):
    """UTC strings become Neo4j temporal values; JSON nulls become absent properties."""
    out = {}
    for key, value in props.items():
        if value is None:
            continue
        out[key] = instant(value) if key in UTC_FIELDS and isinstance(value, str) else value
    return out


class Gateway:
    def __init__(self, driver, database, dataset_id):
        self.driver, self.database, self.dataset_id = driver, database, dataset_id
        self._reference = None
        self._drained = None   # The latest clock by which every delivered message had been ingested.

    def reference(self):
        if self._reference is None:
            with self.driver.session(database=self.database, default_access_mode="READ") as session:
                packages = [dict(r["p"]) for r in session.run(
                    "MATCH (p:V2Entity:Package {dataset_id:$d}) RETURN p {.entity_id,.manifest_barcode} AS p", d=self.dataset_id)]
                shipments = [dict(r["s"]) for r in session.run(
                    "MATCH (s:V2Entity:Shipment {dataset_id:$d}) RETURN s {.entity_id,.tracking_id,.split} AS s", d=self.dataset_id)]
            self._reference = Reference(packages, shipments)
            self._splits = {s["entity_id"]: s["split"] for s in shipments}
        return self._reference

    def pending(self, clock):
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            row = session.run("MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.deliver_at <= $clock RETURN count(f) AS n",
                              clock=instant(clock)).single()
        return row["n"]

    def ingest_due(self, clock, limit=500, not_before=None):
        """Normalize up to `limit` messages delivered by `clock`. Returns counts and touched shipments.

        not_before: a clock by which the caller knows every delivered message was already ingested (the store passes
        its previous clock). The gateway also remembers the clocks it drained itself."""
        ref = self.reference()
        clock_at = instant(clock)
        floors = [t for t in (instant(not_before) if isinstance(not_before, str) else not_before, self._drained) if t is not None]
        floor = max(floors) if floors else None
        with self.driver.session(database=self.database) as session:
            result = session.execute_write(lambda tx: self._ingest(tx, ref, clock_at, limit, floor))
        if result["messages"] < limit and (self._drained is None or clock_at > self._drained):
            self._drained = clock_at
        return result

    @staticmethod
    def recorded_time(deliver_at, occurred_at, clock_at, floor=None):
        """When the provider delivered the record: never before it occurred, never after the tick that ingested it, and
        the tick itself for a message delivered at or before a clock that had already been drained."""
        if deliver_at is None or (floor is not None and deliver_at <= floor):
            return clock_at
        return min(clock_at, max(deliver_at, occurred_at))

    def _ingest(self, tx, ref, clock_at, limit, floor=None):
        items = [dict(r["f"]) for r in tx.run(
            "MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.deliver_at <= $clock "
            "RETURN f ORDER BY f.deliver_at, f.feed_id LIMIT $limit", clock=clock_at, limit=limit)]
        counts = {"ingested": 0, "duplicate": 0, "conflicting_duplicate": 0, "rejected": 0}
        touched, lags, ingested = set(), [], []
        for item in items:
            status, entity_id, sid, error = self._one(tx, ref, item, clock_at, floor)
            counts[status.lower()] += 1
            if sid and status == "INGESTED":
                touched.add(sid)
            if status == "INGESTED":
                ingested.append((sid, self._last_kind, entity_id))
                lags.append((clock_at - item["deliver_at"].to_native()).total_seconds() if hasattr(item["deliver_at"], "to_native") else 0)
            tx.run("MATCH (f:ProviderFeedItem {feed_id:$id}) SET f.status=$status, f.ingested_at=$at, "
                   "f.normalized_entity_id=$entity, f.error=$error",
                   id=item["feed_id"], status=status, at=clock_at, entity=entity_id, error=error).consume()
        return {**counts, "messages": len(items), "shipments": sorted(touched), "items": ingested,
                "max_lag_seconds": max(lags, default=0)}

    def _one(self, tx, ref, item, clock_at, floor=None):
        try:
            kind, entity_id, sid, occurred_at, props = decode(item["channel"], item["message_type"], json.loads(item["payload_json"]), ref)
        except (KeyError, ValueError, StopIteration, TypeError):
            return "REJECTED", None, None, "undecodable_or_unresolvable_payload"
        if kind not in ingestible_kinds(self.dataset_id) or not str(entity_id).startswith("DEMO-") or (sid and sid not in self._splits):
            return "REJECTED", None, None, "unknown_kind_identity_or_shipment"
        existing = tx.run("MATCH (n:V2Entity {entity_id:$id}) RETURN n.raw_payload_hash AS hash, n:LiveIngested AS live",
                          id=entity_id).single()
        if existing is not None:
            if existing["live"] and existing["hash"] == item["payload_hash"]:
                return "DUPLICATE", entity_id, sid, None
            return "CONFLICTING_DUPLICATE", entity_id, sid, "same_source_event_different_payload"
        if instant(occurred_at) > clock_at:
            return "REJECTED", entity_id, sid, "event_time_after_receipt"
        split = self._splits[sid] if sid else "shared"
        delivered = item.get("deliver_at")
        delivered = delivered.to_native() if hasattr(delivered, "to_native") else instant(delivered) if isinstance(delivered, str) else delivered
        recorded = self.recorded_time(delivered, instant(occurred_at), clock_at, floor)
        envelope = {"entity_id": entity_id, "dataset_id": self.dataset_id, "schema_version": SCHEMA_VERSION, "synthetic": True,
                    "provenance": "SYNTHETIC_DEMO_ASSUMPTION", "split": split, "holdout_group": sid, "shipment_id": sid,
                    "occurred_at": occurred_at, "recorded_at": recorded.isoformat(), "ingested_at": clock_at.isoformat(),
                    "feed_id": item["feed_id"], "channel": item["channel"], "provider_id": item["provider_id"],
                    "raw_payload_hash": item["payload_hash"], "feed_origin": item["origin"],
                    # How long after the event the provider delivered it (not how long the gateway's tick took to reach it).
                    "ingest_lag_seconds": int((recorded - instant(occurred_at)).total_seconds())}
        labels = ":".join(("V2Entity", kind, "LiveIngested", *ALIASES.get(kind, ())))
        self._last_kind = kind
        tx.run(f"CREATE (n:{labels}) SET n=$props", props=_neo({**props, **envelope})).consume()
        self._edges(tx, kind, entity_id, props, sid, split, recorded)
        return "INGESTED", entity_id, sid, None

    def _edges(self, tx, kind, entity_id, props, sid, split, clock_at):
        def link(start, rel, end):
            edge_id = "DEMO-EDGE-" + digest([start, rel, end, INGEST_SOURCE_REF])[:24]
            edge = {"edge_id": edge_id, "dataset_id": self.dataset_id, "schema_version": SCHEMA_VERSION, "synthetic": True,
                    "provenance": "SYNTHETIC_DEMO_ASSUMPTION", "source_ref": INGEST_SOURCE_REF, "split": split,
                    "holdout_group": sid, "recorded_at": clock_at}
            tx.run(f"MATCH (a:V2Entity {{entity_id:$a}}),(b:V2Entity {{entity_id:$b}}) "
                   f"MERGE (a)-[r:{rel} {{edge_id:$id}}]->(b) ON CREATE SET r=$props",
                   a=start, b=end, id=edge_id, props={k: v for k, v in edge.items() if v is not None}).consume()
        for rule_kind, prop, rel, outward in EDGE_RULES:
            if rule_kind == kind:
                targets = props.get(prop) if prop != "shipment_id" else sid
                for target in (targets if isinstance(targets, list) else [targets]):
                    if isinstance(target, str) and target.startswith("DEMO-"):
                        link(entity_id, rel, target) if outward else link(target, rel, entity_id)
            # Messages arrive out of order: evidence ingested earlier that references this node links now.
            if REFERENCED_KIND.get(prop) == kind:
                for row in tx.run(f"MATCH (o:LiveIngested:{rule_kind}) WHERE o.{prop} = $id AND o.holdout_group = $sid "
                                  "RETURN o.entity_id AS id LIMIT 20", id=entity_id, sid=sid):
                    link(row["id"], rel, entity_id) if outward else link(entity_id, rel, row["id"])

    def enqueue(self, items):
        """Append messages (e.g. operational simulator responses) to the provider feed."""
        with self.driver.session(database=self.database) as session:
            rows = [{**item, "deliver_at": instant(item["deliver_at"]), "status": "PENDING", "dataset_id": self.dataset_id,
                     "synthetic": True} for item in items]
            session.run("UNWIND $rows AS row MERGE (f:ProviderFeedItem {feed_id:row.feed_id}) ON CREATE SET f=row", rows=rows).consume()

    def pending_feed_ids(self, source_event_ids):
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            return [r["id"] for r in session.run("MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.source_event_id IN $ids "
                                                 "RETURN f.feed_id AS id", ids=list(source_event_ids))]

    def reschedule(self, feed_ids, deliver_at):
        """A device sync request makes the device upload what it buffered: earlier delivery, same messages."""
        with self.driver.session(database=self.database) as session:
            return session.run("MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.feed_id IN $ids AND f.deliver_at > $at "
                               "SET f.original_deliver_at=coalesce(f.original_deliver_at,f.deliver_at), f.deliver_at=$at, "
                               "f.rescheduled=true RETURN count(f) AS n",
                               ids=list(feed_ids), at=instant(deliver_at)).single()["n"]

    def reset(self):
        """New live session: remove normalized evidence and simulator messages; provider messages return to PENDING."""
        self._drained = None
        with self.driver.session(database=self.database) as session:
            session.run("MATCH (n:LiveIngested {dataset_id:$d}) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 2000 ROWS",
                        d=self.dataset_id).consume()
            session.run("MATCH (f:ProviderFeedItem) WHERE f.origin <> 'PROVIDER' DETACH DELETE f").consume()
            session.run("MATCH (f:ProviderFeedItem {origin:'PROVIDER'}) WHERE f.status <> 'PENDING' OR f.rescheduled "
                        "CALL (f) { SET f.status='PENDING', f.ingested_at=null, f.normalized_entity_id=null, f.error=null, "
                        "f.rescheduled=null, f.deliver_at=coalesce(f.original_deliver_at,f.deliver_at), f.original_deliver_at=null } "
                        "IN TRANSACTIONS OF 2000 ROWS").consume()

    def first_delivery(self):
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            row = session.run("MATCH (f:ProviderFeedItem {origin:'PROVIDER'}) RETURN min(f.deliver_at) AS t").single()
        return row["t"].to_native().isoformat() if row and row["t"] else None
