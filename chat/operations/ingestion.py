"""Provider gateway: normalize delivered feed messages into canonical, provenance-stamped evidence.

A message becomes visible to Suhail only when the simulation clock reaches its delivery time.
The gateway decodes the channel's format, resolves provider references (barcodes, tracking
numbers), de-duplicates by source event identity, and writes one immutable evidence node
(:V2Entity:<Kind>:LiveIngested) whose recorded_at is the ingestion time. occurred_at stays the
provider's event time, so a late upload is visible as late, never back-dated into the past.
Every message, including duplicates and rejects, keeps its raw payload and outcome on its
ProviderFeedItem. No truth, gold or scenario data is read here.
"""
import json
from datetime import timedelta

from dataset_v2.contracts import ALIASES, SCHEMA_VERSION, UTC_FIELDS, digest, instant
from dataset_v2.feed import FEED_KINDS, Reference, decode

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
)


# Properties that reference other feed evidence (everything else references imported reference data).
REFERENCED_KIND = {"source_event_id": "ScanEvent", "attempt_id": "DeliveryAttempt", "authentication_id": "AuthenticationEvidence",
                   "signature_id": "SignatureEvidence", "photo_id": "PhotoEvidence", "handoff_id": "HandoffEvidence",
                   "pin_id": "LocationPin", "supersedes_id": "Manifest"}


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

    def ingest_due(self, clock, limit=500):
        """Normalize up to `limit` messages delivered by `clock`. Returns counts and touched shipments."""
        ref = self.reference()
        clock_at = instant(clock)
        with self.driver.session(database=self.database) as session:
            return session.execute_write(lambda tx: self._ingest(tx, ref, clock_at, limit))

    def _ingest(self, tx, ref, clock_at, limit):
        items = [dict(r["f"]) for r in tx.run(
            "MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.deliver_at <= $clock "
            "RETURN f ORDER BY f.deliver_at, f.feed_id LIMIT $limit", clock=clock_at, limit=limit)]
        counts = {"ingested": 0, "duplicate": 0, "conflicting_duplicate": 0, "rejected": 0}
        touched, lags, ingested = set(), [], []
        for item in items:
            status, entity_id, sid, error = self._one(tx, ref, item, clock_at)
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

    def _one(self, tx, ref, item, clock_at):
        try:
            kind, entity_id, sid, occurred_at, props = decode(item["channel"], item["message_type"], json.loads(item["payload_json"]), ref)
        except (KeyError, ValueError, StopIteration, TypeError):
            return "REJECTED", None, None, "undecodable_or_unresolvable_payload"
        if kind not in FEED_KINDS or not str(entity_id).startswith("DEMO-") or (sid and sid not in self._splits):
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
        envelope = {"entity_id": entity_id, "dataset_id": self.dataset_id, "schema_version": SCHEMA_VERSION, "synthetic": True,
                    "provenance": "SYNTHETIC_DEMO_ASSUMPTION", "split": split, "holdout_group": sid, "shipment_id": sid,
                    "occurred_at": occurred_at, "recorded_at": clock_at.isoformat(), "ingested_at": clock_at.isoformat(),
                    "feed_id": item["feed_id"], "channel": item["channel"], "provider_id": item["provider_id"],
                    "raw_payload_hash": item["payload_hash"], "feed_origin": item["origin"],
                    "ingest_lag_seconds": int((clock_at - instant(occurred_at)).total_seconds())}
        labels = ":".join(("V2Entity", kind, "LiveIngested", *ALIASES.get(kind, ())))
        self._last_kind = kind
        tx.run(f"CREATE (n:{labels}) SET n=$props", props=_neo({**props, **envelope})).consume()
        self._edges(tx, kind, entity_id, props, sid, split, clock_at)
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

    def reschedule(self, feed_ids, deliver_at):
        """A device sync request makes the device upload what it buffered: earlier delivery, same messages."""
        with self.driver.session(database=self.database) as session:
            return session.run("MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.feed_id IN $ids AND f.deliver_at > $at "
                               "SET f.original_deliver_at=coalesce(f.original_deliver_at,f.deliver_at), f.deliver_at=$at, "
                               "f.rescheduled=true RETURN count(f) AS n",
                               ids=list(feed_ids), at=instant(deliver_at)).single()["n"]

    def reset(self):
        """New live session: remove normalized evidence and simulator messages; provider messages return to PENDING."""
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
