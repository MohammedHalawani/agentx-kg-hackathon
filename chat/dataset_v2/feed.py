"""Provider feeds for the live network dataset: raw messages, adapters and the import split.

Live (development) shipments are not imported with their observations. Each observation becomes
a raw message from the provider channel that would really send it, in that channel's own format:

  SPL_CORE         SPL facility handhelds, SPL driver app, depot system, tracking status
  DRIVER_APP       the independent-driver platform's app (barcodes not package ids, local time)
  CARRIER_EDI      the contracted 3PL carrier's EDI-style status messages and truck positions
  TELEMATICS       SPL fleet vehicle positions (epoch seconds)
  RECIPIENT_PORTAL recipient reports and location pins
  TRAFFIC          road delay observations
  MDM              device management heartbeats (handhelds and driver apps)

A message carries the provider's event time and is delivered to Suhail's gateway at deliver_at
(network lag, an offline device's late upload, or a provider retransmission). The ingestion
worker normalizes messages back into canonical evidence; decode(encode(node)) is exact apart
from the ingestion clock. Nothing here reads truth.
"""
from datetime import datetime, timedelta, timezone

from dataset_v2.contracts import RIYADH, World, canonical, digest, instant, iso
from dataset_v2.context import OBSERVATIONS
from dataset_v2.network import device_for_driver, stable_fraction

FEED_VERSION = "provider-feed-1"
CHANNELS = ("SPL_CORE", "DRIVER_APP", "CARRIER_EDI", "TELEMATICS", "RECIPIENT_PORTAL", "TRAFFIC", "MDM")
# Mechanism world (chat/world) only: the messaging gateway's delivery reports (SMS/WhatsApp/email).
# Kept out of CHANNELS so the live-network dataset's channel set is unchanged.
WORLD_CHANNELS = ("MESSAGING",)
FEED_KINDS = frozenset(OBSERVATIONS | {"DeviceHeartbeat"})
# Mechanism world: observations that are about a facility, trip, device or road rather than one parcel.
# They are shared records (no shipment group) delivered through the feed like any provider message.
SHARED_OBSERVATIONS = frozenset(("DeviceHeartbeat", "FacilityThroughput", "TripEvent", "TrafficEvent", "GPSObservation"))
# Mechanism world: per-shipment context created during the journey (a route's session and assignment, a
# corrected address, the person a parcel was handed to). Dated records, so a live shipment receives them
# through the feed instead of the import.
DATED_CONTEXT = frozenset(("DeliverySession", "VehicleAssignment", "AddressVersion", "Customer"))
WORLD_FEED_KINDS = frozenset(FEED_KINDS | SHARED_OBSERVATIONS | DATED_CONTEXT)
# The gateway also accepts an AddressVersion: a recipient confirms or corrects an address via the portal.
INGESTIBLE_KINDS = frozenset(FEED_KINDS | {"AddressVersion"} | WORLD_FEED_KINDS)
# Envelope fields the gateway sets itself; never carried in a provider payload.
ENVELOPE = frozenset(("entity_id", "dataset_id", "schema_version", "synthetic", "provenance", "split", "holdout_group",
                      "recorded_at", "shipment_id", "occurred_at"))
CHANNEL_PROVIDER = {"SPL_CORE": "DEMO-PROV-SPL", "DRIVER_APP": "DEMO-PROV-INDEP-01", "CARRIER_EDI": "DEMO-PROV-3PL-01",
                    "TELEMATICS": "DEMO-PROV-SPL", "RECIPIENT_PORTAL": "DEMO-PROV-SPL", "TRAFFIC": "DEMO-PROV-SPL", "MDM": "DEMO-PROV-SPL",
                    "MESSAGING": "DEMO-PROV-MSG-01"}

APP_TYPES = {"ScanEvent": "PARCEL_SCAN", "CustodyEvent": "HANDOVER", "DeliveryAttempt": "STOP_RESULT", "ContactAttempt": "CALL_LOG",
             "DeliveryProof": "POD", "AuthenticationEvidence": "POD_OTP", "SignatureEvidence": "POD_SIGNATURE",
             "PhotoEvidence": "POD_PHOTO", "HandoffEvidence": "POD_HANDOFF", "GPSObservation": "PHONE_LOCATION", "Manifest": "SHIFT_MANIFEST"}
APP_RENAME = {"disposition": "stop_outcome", "failed_reason": "reason_code", "used_address_version_id": "address_ref",
              "observed_gate": "gate_seen", "attempt_id": "stop_ref", "vehicle_id": "car_ref", "assignment_id": "job_ref",
              "session_id": "shift_ref", "accuracy_m": "geo_acc_m", "driver_id": "driver_ref"}
APP_VALUES = {"stop_outcome": {"DELIVERED": "DONE", "FAILED": "NOT_DONE"}}
EDI_CODES = {"LOADED": "AF", "RECEIVED": "X1", "DELIVERED": "D1", "RETURNED": "RT",
             # Mechanism world: carrier trip status (departure, arrival, ETA revision).
             "DEPARTED": "P1", "ARRIVED": "X3", "ETA_REVISED": "AG"}
EDI_RENAME = {"from_id": "origin_party", "to_id": "destination_party", "vehicle_id": "equipment", "facility_id": "location"}
# Messaging gateway delivery reports (mechanism world): the gateway's own field names and epoch time.
MSG_RENAME = {"recipient_id": "subscriber_ref", "purpose": "template_purpose", "delivery_status": "dlr_status",
              "channel_type": "bearer", "carrier_route": "route", "attempt_id": "context_ref", "direction": "flow"}


def _without(props, *drop):
    return {k: v for k, v in props.items() if k not in ENVELOPE and k not in drop}


def _local(when):
    return instant(when).astimezone(RIYADH).strftime("%Y-%m-%d %H:%M:%S%z")


def _from_local(text):
    return iso(datetime.strptime(text, "%Y-%m-%d %H:%M:%S%z"))


def _edi_time(when):
    return instant(when).strftime("%Y%m%d%H%M%S")


def _from_edi(text):
    return iso(datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc))


class Reference:
    """Lookups the gateway needs from imported reference data (barcodes, tracking numbers)."""

    def __init__(self, packages, shipments):
        self.package_by_barcode = {p["manifest_barcode"]: p["entity_id"] for p in packages}
        self.barcode_by_package = {v: k for k, v in self.package_by_barcode.items()}
        self.shipment_by_tracking = {s["tracking_id"]: s["entity_id"] for s in shipments}
        self.tracking_by_shipment = {v: k for k, v in self.shipment_by_tracking.items()}

    @classmethod
    def from_world(cls, world):
        return cls([n.properties for n in world.of_kind("Package")], [n.properties for n in world.of_kind("Shipment")])


def encode(node, channel, ref):
    """Canonical observation -> (message_type, payload) in the channel's own format."""
    p, kind = node.properties, node.kind
    sid = p.get("shipment_id")
    if channel == "DRIVER_APP":
        attrs = {}
        for key, value in _without(p).items():
            name = APP_RENAME.get(key, key)
            if key == "package_id":
                name, value = "parcel_barcode", ref.barcode_by_package[value]
            elif key == "package_ids":
                name, value = "parcel_barcodes", [ref.barcode_by_package[v] for v in value]
            if name in attrs:
                raise ValueError(f"Driver-app field collision: {name}")
            attrs[name] = APP_VALUES[name].get(value, value) if name in APP_VALUES else value
        return APP_TYPES[kind], {"event_ref": node.id, "tracking_no": ref.tracking_by_shipment.get(sid),
                                 "local_time": _local(p["occurred_at"]), "attrs": attrs}
    if channel == "CARRIER_EDI":
        segments = {EDI_RENAME.get(k, k): v for k, v in _without(p).items()}
        code = EDI_CODES.get(p.get("event_type"), "POS" if kind == "GPSObservation" else "OBS")
        return f"EDI214:{code}", {"ref": node.id, "pro_number": ref.tracking_by_shipment.get(sid), "kind": kind,
                                  "ts": _edi_time(p["occurred_at"]), "segments": segments}
    if channel == "TELEMATICS":
        rest = _without(p, "vehicle_id", "lat", "lng", "accuracy_m")
        return "FIX", {"unit": p["vehicle_id"], "ref": node.id, "tracking_no": ref.tracking_by_shipment.get(sid),
                       "fix_time_epoch": int(instant(p["occurred_at"]).timestamp()), "lat": p["lat"], "lon": p["lng"],
                       "hdop_m": p["accuracy_m"], "extra": rest}
    if channel == "MDM":
        return "HEARTBEAT", {"device_serial": p["device_id"], "ref": node.id, "seen_at": p["occurred_at"], "src": p["source_ref"],
                             "queue_depth": p["pending_uploads"], "last_upload": p["last_upload_at"], "net": p["connectivity"]}
    if channel == "MESSAGING":
        attrs = {}
        for key, value in _without(p).items():
            name = MSG_RENAME.get(key, key)
            if name in attrs:
                raise ValueError(f"Messaging field collision: {name}")
            attrs[name] = value
        return "DLR", {"msg_id": node.id, "tracking_no": ref.tracking_by_shipment.get(sid),
                       "submitted_epoch": int(instant(p["occurred_at"]).timestamp()), "dlr": attrs}
    # SPL_CORE, RECIPIENT_PORTAL, TRAFFIC: canonical names, UTC.
    return kind.upper(), {"type": kind, "id": node.id, "shipment": sid, "at": p["occurred_at"], "fields": _without(p)}


def decode(channel, message_type, payload, ref):
    """Raw message -> (kind, entity_id, shipment_id, occurred_at, canonical properties)."""
    if channel == "DRIVER_APP":
        kind = next(k for k, v in APP_TYPES.items() if v == message_type)
        inverse = {v: k for k, v in APP_RENAME.items()}
        props = {}
        for name, value in payload["attrs"].items():
            if name == "parcel_barcode":
                props["package_id"] = ref.package_by_barcode[value]
                continue
            if name == "parcel_barcodes":
                props["package_ids"] = [ref.package_by_barcode[v] for v in value]
                continue
            if name in APP_VALUES:
                value = {v: k for k, v in APP_VALUES[name].items()}.get(value, value)
            props[inverse.get(name, name)] = value
        sid = ref.shipment_by_tracking.get(payload["tracking_no"])
        return kind, payload["event_ref"], sid, _from_local(payload["local_time"]), props
    if channel == "CARRIER_EDI":
        inverse = {v: k for k, v in EDI_RENAME.items()}
        props = {inverse.get(k, k): v for k, v in payload["segments"].items()}
        return payload["kind"], payload["ref"], ref.shipment_by_tracking.get(payload["pro_number"]), _from_edi(payload["ts"]), props
    if channel == "TELEMATICS":
        props = {**payload["extra"], "vehicle_id": payload["unit"], "lat": payload["lat"], "lng": payload["lon"], "accuracy_m": payload["hdop_m"]}
        when = iso(datetime.fromtimestamp(payload["fix_time_epoch"], tz=timezone.utc))
        return "GPSObservation", payload["ref"], ref.shipment_by_tracking.get(payload["tracking_no"]), when, props
    if channel == "MDM":
        props = {"device_id": payload["device_serial"], "pending_uploads": payload["queue_depth"], "source_ref": payload["src"],
                 "last_upload_at": payload["last_upload"], "connectivity": payload["net"]}
        return "DeviceHeartbeat", payload["ref"], None, payload["seen_at"], props
    if channel == "MESSAGING":
        inverse = {v: k for k, v in MSG_RENAME.items()}
        props = {inverse.get(k, k): v for k, v in payload["dlr"].items()}
        when = iso(datetime.fromtimestamp(payload["submitted_epoch"], tz=timezone.utc))
        return "CommunicationEvent", payload["msg_id"], ref.shipment_by_tracking.get(payload["tracking_no"]), when, props
    return payload["type"], payload["id"], payload["shipment"], payload["at"], dict(payload["fields"])


def channel_for(world, node):
    """Which provider system reports this observation."""
    p, kind = node.properties, node.kind
    nodes = world.nodes
    def vehicle_channel(vehicle_id):
        vehicle = nodes.get(vehicle_id)
        ownership = vehicle.properties.get("ownership") if vehicle else None
        return {"PRIVATE": "DRIVER_APP", "PROVIDER": "CARRIER_EDI"}.get(ownership, "SPL_CORE")
    def device_channel(device_ref):
        device = nodes.get(device_ref)
        if device and device.properties.get("device_kind") == "DRIVER_APP":
            provider = device.properties.get("provider_id")
            return {"DEMO-PROV-INDEP-01": "DRIVER_APP", "DEMO-PROV-3PL-01": "CARRIER_EDI"}.get(provider, "SPL_CORE")
        return "SPL_CORE"
    def assignment_channel(assignment_id):
        assignment = nodes.get(assignment_id)
        return vehicle_channel(assignment.properties["vehicle_id"]) if assignment else "SPL_CORE"
    if kind == "DeviceHeartbeat":
        return "MDM"
    if kind in ("TrafficObservation", "TrafficEvent"):
        return "TRAFFIC"
    if kind in ("RecipientReport", "LocationPin", "AddressVersion"):
        return "RECIPIENT_PORTAL"
    if kind == "CommunicationEvent":
        return "MESSAGING"
    if kind == "TripEvent":
        return vehicle_channel(p.get("vehicle_id"))
    if kind == "GPSObservation":
        channel = vehicle_channel(p["vehicle_id"])
        return "TELEMATICS" if channel == "SPL_CORE" else channel
    if kind == "Manifest":
        return "DRIVER_APP" if p.get("provider_id") == "DEMO-PROV-INDEP-01" else "SPL_CORE"
    if kind == "ScanEvent":
        return device_channel(p.get("device_ref"))
    if kind == "CustodyEvent":
        raw = nodes.get(p.get("source_event_id"))
        return device_channel(raw.properties.get("device_ref")) if raw else "SPL_CORE"
    if kind in ("DeliveryAttempt",):
        return assignment_channel(p.get("assignment_id"))
    if kind in ("ContactAttempt", "DeliveryProof", "AuthenticationEvidence", "SignatureEvidence", "PhotoEvidence", "HandoffEvidence"):
        attempt = nodes.get(p.get("attempt_id"))
        return assignment_channel(attempt.properties.get("assignment_id")) if attempt else "SPL_CORE"
    return "SPL_CORE"


def feed_item(world, node, ref, *, deliver_at=None, sequence=0, origin="PROVIDER"):
    channel = channel_for(world, node)
    message_type, payload = encode(node, channel, ref)
    p = node.properties
    # Records sent together by one device share a delivery: a transfer with its source scan, POD parts with the attempt.
    bundle = p.get("source_event_id") if node.kind == "CustodyEvent" else p.get("attempt_id") if node.kind in (
        "ContactAttempt", "DeliveryProof", "AuthenticationEvidence", "SignatureEvidence", "PhotoEvidence", "HandoffEvidence") else node.id
    lag = 5 + int(85 * stable_fraction(bundle or node.id, sequence))
    deliver = deliver_at or iso(instant(node.properties["recorded_at"]) + timedelta(seconds=lag))
    feed_id = "DEMO-FEED-" + digest([node.id, sequence, origin])[:24]
    return {"feed_id": feed_id, "channel": channel, "provider_id": CHANNEL_PROVIDER[channel], "message_type": message_type,
            "source_event_id": node.id, "deliver_at": deliver, "origin": origin, "payload_json": canonical(payload),
            "payload_hash": digest(payload), "feed_version": FEED_VERSION}


def split_feed(world: World, truth: dict):
    """(import world, feed items). Live observations leave the import and become provider messages."""
    ref = Reference.from_world(world)
    live = {sid for sid, row in truth.items() if row["split"] == "development"}
    moving = {n.id for n in world.nodes.values()
              if (n.kind in FEED_KINDS and n.properties.get("holdout_group") in live) or n.kind == "DeviceHeartbeat"}
    # Offline-derived development Case/Exception nodes are never imported: the live monitor opens cases.
    derived = {n.id for n in world.nodes.values() if n.kind in ("Case", "Exception") and n.properties.get("holdout_group") in live}
    items = []
    for key in sorted(moving):
        node = world.nodes[key]
        items.append(feed_item(world, node, ref))
        row = truth.get(node.properties.get("holdout_group"))
        if row and row["recipe"] == "duplicate_provider_events" and channel_for(world, node) == "DRIVER_APP" and node.kind in ("CustodyEvent", "DeliveryAttempt"):
            # The provider's app retransmits the same event a few minutes later (identical payload).
            items.append(feed_item(world, node, ref, sequence=1, deliver_at=iso(instant(items[-1]["deliver_at"]) + timedelta(minutes=3))))
    imported = World(world.config)
    removed = moving | derived
    for key, node in world.nodes.items():
        if key in removed:
            continue
        props = dict(node.properties)
        if props.get("holdout_group") in live and node.kind in ("Shipment", "JourneyPlan"):
            props.pop("as_of", None)  # Generator bookkeeping: the end of the shipment's whole story.
            if node.kind == "Shipment":
                props["status"] = "CREATED"
        imported.nodes[key] = type(node)(node.id, node.kind, props)
    # Derived parcel/vehicle intervals (LOADED_ON) cite custody evidence that is now in the feed.
    imported.edges = {k: e for k, e in world.edges.items() if e.start not in removed and e.end not in removed
                      and e.properties.get("custody_event_id") not in removed and e.properties.get("end_evidence_id") not in removed}
    imported.gold = dict(world.gold)
    items.sort(key=lambda item: (item["deliver_at"], item["feed_id"]))
    return imported, items


def reconstitute(imported: World, items):
    """Decode every first delivery back onto the import world, recorded when it was delivered."""
    import json
    full = World(imported.config)
    full.nodes = {k: type(n)(n.id, n.kind, dict(n.properties)) for k, n in imported.nodes.items()}
    full.edges = dict(imported.edges)
    full.gold = {k: dict(v) for k, v in imported.gold.items()}  # derive_world writes assessments into gold rows.
    ref = Reference.from_world(imported)
    for item in items:
        kind, entity_id, sid, occurred_at, props = decode(item["channel"], item["message_type"], json.loads(item["payload_json"]), ref)
        if entity_id in full.nodes:
            continue
        split = imported.nodes[sid].properties["split"] if sid else "shared"
        full.node(kind, entity_id, shipment_id=sid, split=split, occurred_at=occurred_at, recorded_at=item["deliver_at"], **props)
    return full


def validate_live_bundle(imported: World, items):
    """The import world plus its feed must reconstitute a domain-valid world.

    The offline-only story end (Shipment.as_of) is restored from the scoring record solely so the
    foundation validator can re-derive the offline Cases it requires; nothing here is imported.
    """
    from dataset_v2.derive import derive_world
    from dataset_v2.validate import validate_world
    full = reconstitute(imported, items)
    for sid, row in full.gold.items():
        shipment = full.nodes[sid].properties
        if "as_of" not in shipment:
            shipment["as_of"] = row["initial_snapshot_at"]
    derive_world(full)
    result = validate_world(full)
    duplicates = [i for i in items if i["origin"] == "PROVIDER"]
    result["feed"] = {"items": len(items), "channels": sorted({i["channel"] for i in items}),
                      "retransmissions": len(items) - len({i["source_event_id"] for i in duplicates})}
    return result
