"""The field's answer to an executed action in a mechanism world (Stage 4): the store's execution adapter.

This stands in for SPL facilities, devices, drivers and recipients in development only. It reads the export's private
PHYSICAL state (where every parcel really is over time, what each device holds and when it reconnects, the label and
weight a parcel really has, where a recipient really lives and when they are away) and never a truth label: no cause
code, no mechanism, no scoring row. It answers causally and per action:

  REQUEST_DEVICE_SYNC              only the targeted device uploads, and only what it holds at that moment
  REQUEST_RESCAN / REQUEST_REWEIGH a new read where the parcel physically is, of the label and weight it really has
  REQUEST_HUB_CHECK /
  INITIATE_CUSTODY_RECONCILIATION  the asked facility finds the parcel only if it is there, else answers "not found"
  REQUEST_ADDRESS_CONFIRMATION     the recipient confirms or corrects the address; nothing is delivered
  PRIORITIZE_NEXT_SESSION          an attempt in the next session only for a parcel at the depot; its result follows
                                   who is home and the address in force
  REQUEST_ADDITIONAL_EVIDENCE      the shipment's records a device still holds, if any
  REROUTE_TO_CONFIRMED_DESTINATION,
  RETURN_TO_SENDER                 the parcel moves from where it is (simplified, see docs/api/demo-lifecycle.md)

Every answer is an ordinary provider message with its own event time and a later delivery time. It reaches Suhail only
through the ingestion gateway, and the outcome verifier judges it like any other evidence. The receipt says that a
request was delivered, never what will be found. Nothing here is reachable from the investigator, its tools, the
reviewer or an API route: only the runtime that builds the store attaches it.
"""
import json
import math
import os
from datetime import timedelta
from pathlib import Path

from dataset_v2.contracts import RIYADH, Node, canonical, digest, instant, iso
from dataset_v2.feed import CHANNEL_PROVIDER, FEED_VERSION, encode
from operations.outcome_engine import FACILITIES, NOT_FOUND
from operations.reasoning import evidence_world

NAME = "world_operational_simulator"
STATE_ENVIRONMENT = "SUHAIL_SIM_STATE_ROOT"   # The physical-state root; the truth-label root is never read here.
STATE_FILES = ("parcels", "containers", "devices", "recipients", "routes")
# Files of the truth-label directory. A directory holding any of them is not a physical-state directory.
LABEL_FILES = ("truth.jsonl", "mechanisms.jsonl", "record_index.jsonl", "truth_manifest.json", "monitor_replay.json")
SOURCE = "synthetic:field-response"
VERIFICATION_POLICY = "synthetic_bound_delivery_v1"
# What a field system acknowledges: which request reached whom. Never the field state or the result.
RECEIPTS = {
    "REQUEST_DEVICE_SYNC": "Sync request delivered to the device's management channel.",
    "REQUEST_RESCAN": "Rescan request sent to the facility expected to hold the parcel.",
    "REQUEST_REWEIGH": "Reweigh request sent to the facility expected to hold the parcel.",
    "REQUEST_HUB_CHECK": "Check request sent to the expected facility.",
    "INITIATE_CUSTODY_RECONCILIATION": "Custody reconciliation request sent to the facility.",
    "REQUEST_ADDRESS_CONFIRMATION": "Address confirmation request sent to the recipient.",
    "PRIORITIZE_NEXT_SESSION": "Priority request sent to the depot for the next delivery session.",
    "REQUEST_ADDITIONAL_EVIDENCE": "Evidence request sent to the systems that handled the parcel.",
    "REROUTE_TO_CONFIRMED_DESTINATION": "Reroute request sent to the depot.",
    "RETURN_TO_SENDER": "Return request sent to the facility expected to hold the parcel.",
}
UNDELIVERABLE = "The request could not be delivered: no known recipient system for it."
# Minutes until a request reaches the people or system that act on it.
DELAY = {"REQUEST_DEVICE_SYNC": 10, "REQUEST_RESCAN": 45, "REQUEST_REWEIGH": 60, "REQUEST_HUB_CHECK": 60,
         "INITIATE_CUSTODY_RECONCILIATION": 90, "REQUEST_ADDRESS_CONFIRMATION": 120, "PRIORITIZE_NEXT_SESSION": 15,
         "REQUEST_ADDITIONAL_EVIDENCE": 30, "REROUTE_TO_CONFIRMED_DESTINATION": 30, "RETURN_TO_SENDER": 60}
# Minutes after a request reaches the field by which its answer, if one comes, has normally reached Suhail: the device
# upload lag (20 to 90 s), or the recipient's time to answer (10 to 120 min). A fixed schedule per request type, so the
# expected time shown with an execution is the same whatever the field will answer, and when it will not answer at all.
# Requests answered in a depot's next delivery session, or by a return journey, have no fixed time (None).
RESPONSE_ALLOWANCE = {"REQUEST_DEVICE_SYNC": 1, "REQUEST_ADDITIONAL_EVIDENCE": 1, "REQUEST_RESCAN": 2, "REQUEST_REWEIGH": 2,
                      "REQUEST_HUB_CHECK": 2, "INITIATE_CUSTODY_RECONCILIATION": 2, "REQUEST_ADDRESS_CONFIRMATION": 121}
ADDRESS_TOLERANCE_M = 150.0     # A recipient who lives further than this from the address in force is not found there.
RETURN_TRANSIT_HOURS = 26       # A parcel sent back reaches its origin facility about a day later (2 h within one site).
AVAILABILITY = {"HOME": .96, "IRREGULAR": .82}


class StateUnavailable(ValueError):
    pass


def distance_m(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    x = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6_371_000 * 2 * math.asin(min(1, math.sqrt(x)))


def fraction(*key):
    """A fixed number in [0, 1) for a key: the same request always gets the same answer."""
    return int(digest(list(key))[:8], 16) / 0x100000000


def message(node, channel, deliver_at):
    message_type, payload = encode(node, channel, None)
    return {"feed_id": "DEMO-FEED-" + digest([node.id, "SIMULATOR"])[:24], "channel": channel, "provider_id": CHANNEL_PROVIDER[channel],
            "message_type": message_type, "source_event_id": node.id, "deliver_at": deliver_at, "origin": "SIMULATOR",
            "payload_json": canonical(payload), "payload_hash": digest(payload), "feed_version": FEED_VERSION}


def state_directory_for(root, dataset_id, split="development"):
    """The export's physical-state folder under a state root: <root>/<dataset_id>/<split>, <root>/<split> or <root>."""
    root = Path(root)
    for candidate in (root / dataset_id / split, root / split, root):
        if (candidate / "parcels.jsonl").is_file():
            return candidate
    raise StateUnavailable("No physical state for this dataset under the given state root")


class PhysicalState:
    """The private physical record of one export, as the generator wrote it. Opened by the simulator only."""

    def __init__(self, tables):
        self.parcels = {row["package_id"]: row for row in tables.get("parcels", [])}
        self.containers = {row["container_id"]: row for row in tables.get("containers", [])}
        self.devices = {row["device_id"]: row for row in tables.get("devices", [])}
        self.recipients = {row["shipment_id"]: row for row in tables.get("recipients", [])}
        self.routes = sorted(tables.get("routes", []), key=lambda row: (row.get("date") or "", row["route_run_id"]))
        self.depots = {row["depot_id"] for row in self.routes}

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        if not (directory / "parcels.jsonl").is_file():
            raise StateUnavailable("Not a physical-state directory")
        for folder in (directory, directory.parent):
            if any((folder / name).exists() for name in LABEL_FILES):
                raise StateUnavailable("This directory holds evaluation labels; the simulator reads physical state only")
        tables = {}
        for name in STATE_FILES:   # Nothing else is opened, whatever the directory holds.
            path = directory / f"{name}.jsonl"
            tables[name] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
        return cls(tables)


class Request:
    def __init__(self, execution, now, at, world):
        self.execution, self.now, self.at, self.world = execution, now, at, world
        self.sid = execution["shipment_id"]
        self.key = execution.get("entity_id") or execution.get("idempotency_key") or "execution"
        self.packages = sorted((n for n in world.nodes.values() if n.kind == "Package"), key=lambda n: n.id)
        self.shipment = world.nodes[self.sid].properties if self.sid in world.nodes else {}


class WorldOperationalSimulator:
    name = NAME

    def __init__(self, gateway, reader, state, config):
        self.gateway, self.reader, self.state, self.config = gateway, reader, state, config
        self.reset()

    def reset(self):
        """A new session: forget what earlier requests changed in the field."""
        self.moves = {}       # package id -> [[time, kind, ref], ...] where the simulator itself moved the parcel
        self.addresses = {}   # shipment id -> the address the recipient confirmed to this simulator
        self.answered = {}    # execution key -> receipt (a re-dispatch after a restart answers once)

    # ------------------------------------------------------------------ entry
    def expected_response_at(self, execution, now):
        """When an answer to this kind of request, if one comes, is expected to have reached Suhail (simulation clock),
        or None when the request type has no fixed time. From the request type alone: never from the physical state."""
        action = execution.get("action_type")
        if action not in DELAY or action not in RESPONSE_ALLOWANCE:
            return None
        return iso(instant(now) + timedelta(minutes=DELAY[action] + RESPONSE_ALLOWANCE[action]))

    def respond(self, execution, now):
        """Schedule the field's answer to an executed action; return the receipt (which says nothing about the answer)."""
        action = execution["action_type"]
        handler = getattr(self, "_" + action.lower(), None)
        if handler is None or action not in RECEIPTS:
            return {"acknowledged": False, "behaviour": "No field system accepts this request type."}
        key = execution.get("entity_id")
        if key and key in self.answered:
            return self.answered[key]
        world = evidence_world(self.reader.evidence(execution["shipment_id"], now), self.config)
        request = Request(execution, instant(now), instant(now) + timedelta(minutes=DELAY[action]), world)
        items = handler(request)
        if items is None:
            receipt = {"acknowledged": False, "behaviour": UNDELIVERABLE}
        else:
            if items:
                self.gateway.enqueue(items)
            receipt = {"acknowledged": True, "behaviour": RECEIPTS[action]}
        if key:
            self.answered[key] = receipt
        return receipt

    # ------------------------------------------------------------------ physical facts
    def timeline(self, package_id):
        base = [[instant(t), kind, ref] for t, kind, ref in (self.state.parcels.get(package_id) or {}).get("timeline", [])]
        moved = self.moves.get(package_id)
        if moved:
            base = [row for row in base if row[0] < moved[0][0]] + moved
        return base

    def where(self, package_id, at):
        """(kind, ref, inside a container) at an instant, or None before the parcel exists."""
        rows = [row for row in self.timeline(package_id) if row[0] <= at]
        if not rows:
            return None
        _, kind, ref = rows[-1]
        if kind != "CONTAINER":
            return kind, ref, False
        inside = [row for row in (self.state.containers.get(ref) or {}).get("timeline", []) if instant(row[0]) <= at]
        return (inside[-1][1], inside[-1][2], True) if inside else None

    def facility_of(self, package_id, at, *, loose=False):
        """The facility the parcel is physically at (loose: on a shelf, not sealed in a container there)."""
        place = self.where(package_id, at)
        if not place or place[0] != "FACILITY" or (loose and place[2]):
            return None
        return place[1]

    def held_by(self, device, at):
        """Record ids the device made and still holds at an instant (offline buffer or stuck outbox), with their shipments."""
        held = []
        for window in device.get("offline") or []:
            if instant(window["from"]) <= at < instant(window["reconnect_at"]):
                held += window.get("buffered_records") or []
        for window in device.get("upload_stuck") or []:
            if instant(window["from"]) <= at < instant(window.get("uploaded_at") or window["until"]):
                held += window.get("stuck_records") or []
        return held

    def upload_time(self, device_id, made):
        """When a record made on a device reaches the gateway: seconds later, or at reconnect when the device is offline."""
        deliver = made + timedelta(seconds=20 + int(70 * fraction(device_id, iso(made), "lag")))
        for window in (self.state.devices.get(device_id) or {}).get("offline") or []:
            if instant(window["from"]) <= made < instant(window["reconnect_at"]):
                deliver = max(deliver, instant(window["reconnect_at"]) + timedelta(seconds=30))
        return iso(deliver)

    @staticmethod
    def handheld(facility):
        return "DEMO-DEV-HH-" + facility.removeprefix("DEMO-")

    def scales(self, facility):
        prefix = "DEMO-DEV-SCL-" + facility.removeprefix("DEMO-")
        return sorted(d for d, row in self.state.devices.items() if row.get("kind") == "SCALE" and d.startswith(prefix))

    def scale_offset(self, device_id, at):
        for window in (self.state.devices.get(device_id) or {}).get("scale_offset") or []:
            if instant(window["from"]) <= at < instant(window["until"]):
                return window["relative_offset"]
        return 0.0

    # ------------------------------------------------------------------ records
    def _node(self, request, kind, tag, when, package=None, **props):
        identifier = f"{request.sid}-SIM-{tag}-{digest([request.key, kind, tag, package.id if package else None])[:10]}"
        fields = {"shipment_id": request.sid, "occurred_at": iso(when), "recorded_at": iso(when), "source_ref": SOURCE, **props}
        if package is not None:
            fields["package_id"] = package.id
        return Node(identifier, kind, fields)

    def _scan(self, request, package, tag, when, device, *, facility=None, barcode=None, weight=None, observation=None, **extra):
        props = {"readable": True, "confidence": .99, "facility_id": facility, "device_ref": device, "observation_type": observation or tag,
                 "calibrated": weight is not None, **extra}
        if weight is not None:
            props.update(measured_weight_kg=weight, measurement_units="kg")
        else:
            props["observed_barcode"] = barcode
        return self._node(request, "ScanEvent", tag, when, package, **props)

    def _custody(self, request, package, tag, when, event, source, to, scan, **extra):
        return self._node(request, "CustodyEvent", tag, when, package, from_id=source, to_id=to, event_type=event, source_event_id=scan.id,
                          required_acknowledgments=2, received_acknowledgments=2, source_quality="CORROBORATED", **extra)

    def label(self, package):
        row = self.state.parcels.get(package.id) or {}
        return row.get("label_barcode") or row.get("manifest_barcode") or package.properties.get("manifest_barcode")

    def _withdraw_future(self, request, after):
        """The simulator moved the parcel: provider messages about what would otherwise have happened to this shipment
        later no longer describe the world, so they are withdrawn before they are delivered."""
        later = [row["feed_id"] for row in self.gateway.pending_records(prefix=request.sid + "-") if instant(row["occurred_at"]) > after]
        if later:
            self.gateway.withdraw(later, "superseded_by_field_action")

    # ------------------------------------------------------------------ device sync, held evidence
    def _flush(self, held, at, deliver):
        pending = [row for row in self.gateway.pending_records([item["record"] for item in held]) if instant(row["occurred_at"]) <= at] if held else []
        if pending:
            self.gateway.reschedule([row["feed_id"] for row in pending], iso(deliver))
        return pending

    def _request_device_sync(self, request):
        """Only the targeted device answers, with what it holds when the request reaches it. A device that holds
        nothing uploads nothing; another device's buffer stays where it is until that device reconnects by itself."""
        target = request.execution.get("target_device")
        device = self.state.devices.get(target) if target else None
        if device is None or device.get("telemetry") == "NONE":
            return None   # No such device, or one with no management channel: nothing to deliver the request to.
        uploaded = self._flush(self.held_by(device, request.at), request.at, request.at + timedelta(seconds=20))
        beat = Node(f"{target}-HB-SYNC-{request.at.strftime('%Y%m%dT%H%M%S')}", "DeviceHeartbeat",
                    {"occurred_at": iso(request.at), "recorded_at": iso(request.at), "device_id": target, "connectivity": "ONLINE",
                     # As a reconnecting device reports it: the queue it is uploading now (zero for a healthy device).
                     "pending_uploads": len(uploaded), "last_upload_at": iso(request.at), "source_ref": "mdm"})
        return [message(beat, "MDM", iso(request.at + timedelta(seconds=5)))]

    def _request_additional_evidence(self, request):
        """The records of this shipment that a device made and still holds are fetched now. If nothing is held
        anywhere, nothing arrives."""
        held = [item for device in self.state.devices.values() for item in self.held_by(device, request.at) if item.get("shipment_id") == request.sid]
        self._flush(held, request.at, request.at + timedelta(seconds=40))
        return []

    # ------------------------------------------------------------------ rescan, reweigh
    def _request_rescan(self, request):
        """A new read of the label the parcel really carries, at the facility where it really is. A misread reads right
        the second time; a wrong label reads wrong again. A parcel that is not on a facility shelf is not rescanned."""
        items = []
        for package in request.packages:
            facility = self.facility_of(package.id, request.at, loose=True)
            if not facility:
                continue
            device = self.handheld(facility)
            scan = self._scan(request, package, "RESCAN", request.at, device, facility=facility, barcode=self.label(package))
            items.append(message(scan, "SPL_CORE", self.upload_time(device, request.at)))
        return items

    def _request_reweigh(self, request):
        """The parcel's real weight on a scale of the facility where it is: a scale that is not drifting now when the
        facility has one. A wrong declaration stays wrong; a facility with no scale cannot reweigh."""
        items = []
        for package in request.packages:
            facility = self.facility_of(package.id, request.at, loose=True)
            scales = self.scales(facility) if facility else []
            true = (self.state.parcels.get(package.id) or {}).get("true_kg")
            if not scales or true is None:
                continue
            device = next((d for d in scales if not self.scale_offset(d, request.at)), scales[0])
            weight = round(true * (1 + self.scale_offset(device, request.at)), 3)
            scan = self._scan(request, package, "REWEIGH", request.at, device, facility=facility, weight=weight, observation="SCALE_WEIGH")
            items.append(message(scan, "SPL_CORE", self.upload_time(device, request.at)))
        return items

    # ------------------------------------------------------------------ hub check, custody reconciliation
    def _asked(self, request):
        """Facilities the system can name from visible evidence, per package: the last corroborated holder when it is a
        facility, and the expected location of each missing observation."""
        from dataset_v2.derive import assess_shipment
        holders = {row["package_id"]: row["last_corroborated_holder_id"] for row in assess_shipment(request.world, request.sid, iso(request.now))["custody"]}
        expected = [e for e in request.execution.get("expected_evidence") or [] if isinstance(e, dict) and e.get("location_id")]
        asked = {}
        for package in request.packages:
            holder = holders.get(package.id)
            node = request.world.nodes.get(holder)
            names = [holder] if node is not None and node.kind in FACILITIES else []
            names += [e["location_id"] for e in expected if e.get("package_id") in (None, package.id)]
            asked[package.id] = (list(dict.fromkeys(names)), holder)
        return asked

    def _check(self, request, reconcile):
        """Each asked facility looks. It finds the parcel (and scans the label it carries) only if the parcel is
        physically there; otherwise it answers that it did not find it. Nobody reports from anywhere else."""
        asked = self._asked(request)
        if not any(names for names, _ in asked.values()):
            return None   # No facility can be named from the evidence: there is nobody to send the request to.
        items = []
        for package in request.packages:
            names, holder = asked[package.id]
            present = self.facility_of(package.id, request.at)
            for facility in names:
                device = self.handheld(facility)
                deliver = self.upload_time(device, request.at)
                if facility != present:
                    absent = self._node(request, "ScanEvent", "NOTFOUND-" + facility.removeprefix("DEMO-"), request.at, package, readable=False,
                                        observation_type=NOT_FOUND, checked_facility_id=facility, device_ref=device, facility_id=None)
                    items.append(message(absent, "SPL_CORE", deliver))
                    continue
                scan = self._scan(request, package, "CHECK", request.at, device, facility=facility, barcode=self.label(package),
                                  observation="FACILITY_CHECK_SCAN")
                items.append(message(scan, "SPL_CORE", deliver))
                if reconcile:
                    event = self._custody(request, package, "RECONCILE", request.at, "RECEIVED", holder or facility, facility, scan, facility_id=facility)
                    items.append(message(event, "SPL_CORE", deliver))
        return items

    def _request_hub_check(self, request):
        return self._check(request, reconcile=False)

    def _initiate_custody_reconciliation(self, request):
        return self._check(request, reconcile=True)

    # ------------------------------------------------------------------ recipient
    def _address_in_force(self, request):
        versions = sorted((n for n in request.world.nodes.values() if n.kind == "AddressVersion"), key=lambda n: (n.properties.get("version") or 0, n.id))
        own = self.addresses.get(request.sid)
        if own:
            return own
        if not versions:
            return None
        p = versions[-1].properties
        return {"id": versions[-1].id, "point": (p.get("lat"), p.get("lng")), "version": p.get("version") or 1, "properties": p,
                "confirmed": p.get("verification_status") == "VERIFIED" and bool(p.get("confirmed_by"))}

    def _request_address_confirmation(self, request):
        """The recipient answers through the portal: the address in force when they live there, their real address
        when they do not. An answer is a record about the address. It delivers nothing."""
        recipient = self.state.recipients.get(request.sid)
        current = self._address_in_force(request)
        if recipient is None or current is None or None in current["point"]:
            return None
        answered = request.at
        for window in recipient.get("sms_unreachable") or []:   # The request reaches the recipient when their number does.
            if window.get("from") and instant(window["from"]) <= answered < instant(window["until"]):
                answered = instant(window["until"])
        answered += timedelta(minutes=10 + int(110 * fraction(request.sid, request.key, "answer")))
        home = tuple(recipient["home_point"])
        lives_there = distance_m(home, current["point"]) <= ADDRESS_TOLERANCE_M
        point = current["point"] if lives_there else home
        base = current["properties"]
        version = self._node(request, "AddressVersion", "ADDR", answered, address_id=base.get("address_id"), version=current["version"] + 1,
                             valid_from=iso(answered), valid_to=None, lat=point[0], lng=point[1], accuracy_m=base.get("accuracy_m") or 20.,
                             city=base.get("city"), verification_status="VERIFIED", confirmed_by=recipient.get("recipient_id"),
                             supersedes_id=current["id"], confirmed_gate=recipient.get("gate"),
                             address_text=(base.get("address_text") or "") + (" (confirmed by the recipient)" if lives_there else " (replaced by the recipient's own address)"),
                             source_ref="recipient-portal")
        self.addresses[request.sid] = {"id": version.id, "point": point, "version": current["version"] + 1, "properties": version.properties,
                                       "confirmed": True, "from": answered}
        return [message(version, "RECIPIENT_PORTAL", iso(answered + timedelta(seconds=30)))]

    def _at_home(self, recipient, when, attempts):
        for window in recipient.get("away") or []:
            if window.get("from") and instant(window["from"]) <= when < instant(window["until"]):
                return False
        hour = when.astimezone(RIYADH).hour
        pattern = recipient.get("availability")
        p = AVAILABILITY.get(pattern) or ((.97 if 8 <= hour < 17 else .15) if pattern == "BUSINESS_HOURS" else (.45 if hour < 15 else .93))
        if attempts:
            p = max(p, .90)   # After a failed attempt the recipient expects the parcel.
        return fraction(recipient["shipment_id"], iso(when), "home") < p

    # ------------------------------------------------------------------ delivery from the depot
    def _dispatch(self, request, address, *, forced):
        """An attempt in the next delivery session, for the packages that are physically on a depot shelf. The result
        follows the physical world: who is home then, and whether the address used is where the recipient lives."""
        recipient = self.state.recipients.get(request.sid)
        shelved = [(p, self.facility_of(p.id, request.at, loose=True)) for p in request.packages]
        shelved = [(p, f) for p, f in shelved if f in self.state.depots]
        if recipient is None or address is None or not shelved:
            return []   # Not at a depot (in transit, with a driver, delivered, lost): nothing can be prioritised.
        depot = shelved[0][1]
        route = next((row for row in self.state.routes if row["depot_id"] == depot and (row.get("departed_at") or row.get("login_at"))
                      and instant(row.get("departed_at") or row["login_at"]) > request.at), None)
        if route is None:
            return []   # No later session runs from this depot in this world.
        start = instant(route.get("departed_at") or route["login_at"])
        day_end = start + timedelta(hours=14)
        if not forced and any(kind == "VEHICLE" and request.at < moved <= day_end for p, _ in shelved for moved, kind, _ in self.timeline(p.id)):
            return []   # The depot loads it in that session anyway: the world's own records follow.
        when = start + timedelta(minutes=60 + int(120 * fraction(request.sid, request.key, "stop")))
        attempts = max((self.state.parcels.get(p.id) or {}).get("attempts") or 0 for p, _ in shelved)
        found = distance_m(tuple(recipient["home_point"]), address["point"]) <= ADDRESS_TOLERANCE_M
        delivered = found and self._at_home(recipient, when, attempts)
        device, vehicle, run = route.get("device_id"), route["vehicle_id"], route["route_run_id"]
        refs = {"route_run_id": run, "vehicle_id": vehicle}
        items = []

        def send(node, made):
            items.append(message(node, "SPL_CORE", self.upload_time(device, made)))
            return node
        loaded = max(start - timedelta(minutes=20), request.at + timedelta(minutes=1))
        for n, (package, _) in enumerate(shelved):
            t = when + timedelta(seconds=40 * n)
            scan = send(self._scan(request, package, "LOAD", loaded, device, facility=depot, barcode=self.label(package),
                                   observation="LOAD_CONFIRMATION", **refs), loaded)
            send(self._custody(request, package, "LOADED", loaded, "LOADED", depot, vehicle, scan, facility_id=depot, **refs), loaded)
            attempt = send(self._node(request, "DeliveryAttempt", "ATT", t, package, used_address_version_id=address["id"],
                                      observed_gate=recipient.get("gate"), disposition="DELIVERED" if delivered else "FAILED",
                                      failed_reason=None if delivered else ("RECIPIENT_NOT_REACHED" if found else "ADDRESS_NOT_FOUND"),
                                      session_id=None, assignment_id=None, driver_id=route.get("driver_id"), source_ref="driver-app", **refs), t)
            if not delivered:
                if found:
                    send(self._node(request, "ContactAttempt", "CONTACT", t - timedelta(minutes=3), package, attempt_id=attempt.id,
                                    result="NO_RESPONSE", channel="phone_call", source_actor_id=recipient.get("recipient_id"), source_ref="driver-app"), t)
                back = start + timedelta(hours=9)
                device_in = self.handheld(depot)
                returned = self._scan(request, package, "RETURN", back, device_in, facility=depot, barcode=self.label(package),
                                      observation="RETURN_SCAN", **refs)
                items.append(message(returned, "SPL_CORE", self.upload_time(device_in, back)))
                items.append(message(self._custody(request, package, "RETURNED", back, "RETURNED", vehicle, depot, returned, facility_id=depot, **refs),
                                     "SPL_CORE", self.upload_time(device_in, back)))
                self.moves[package.id] = [[loaded, "VEHICLE", vehicle], [back, "FACILITY", depot]]
                continue
            lat, lng = address["point"]
            bound = {"attempt_id": attempt.id, "source_ref": "driver-app"}
            auth = send(self._node(request, "AuthenticationEvidence", "AUTH", t, package, method="SYNTHETIC_OTP", result="PASS",
                                   authorized_recipient_id=recipient.get("recipient_id"), expires_at=iso(t + timedelta(minutes=5)),
                                   verification_policy=VERIFICATION_POLICY, secret_value_stored=False, **bound), t)
            handoff = send(self._node(request, "HandoffEvidence", "HANDOFF", t, package, recipient_id=recipient.get("recipient_id"),
                                      recipient_type="EXPECTED_RECIPIENT", authorization_ref=None, **bound), t)
            proof = send(self._node(request, "DeliveryProof", "PROOF", t, package, address_version_id=address["id"], lat=lat, lng=lng,
                                    accuracy_m=10., authentication_id=auth.id, signature_id=None, photo_id=None, handoff_id=handoff.id,
                                    verification_policy=VERIFICATION_POLICY, **bound), t)
            done = send(self._scan(request, package, "DELIVERY", t, device, barcode=self.label(package), observation="DELIVERY_SCAN", **refs), t)
            send(self._custody(request, package, "DELIVERED", t, "DELIVERED", vehicle, recipient.get("recipient_id"), done, proof_id=proof.id, **refs), t)
            self.moves[package.id] = [[loaded, "VEHICLE", vehicle], [t, "PERSON", recipient.get("recipient_id")]]
        if delivered:
            self._withdraw_future(request, loaded)   # After a failed attempt the parcel is back on the shelf: its later days stand.
        return items

    def _prioritize_next_session(self, request):
        return self._dispatch(request, self._address_in_force(request), forced=False)

    def _reroute_to_confirmed_destination(self, request):
        """Simplified: delivery from the depot where the parcel is to the address the recipient confirmed. With no
        confirmed address, or a parcel that is not at a depot, nothing moves."""
        address = self._address_in_force(request)
        return self._dispatch(request, address, forced=True) if address and address.get("confirmed") else []

    def _return_to_sender(self, request):
        """Simplified: each package on a facility shelf is sent back to the facility it was first handed over at, and is
        received there about a day later. A package that is anywhere else does not move."""
        items = []
        for package in request.packages:
            facility = self.facility_of(package.id, request.at, loose=True)
            origin = next((ref for _, kind, ref in self.timeline(package.id) if kind == "FACILITY"), None)
            if not facility or not origin:
                continue
            arrive = request.at + timedelta(hours=2 if facility == origin else RETURN_TRANSIT_HOURS)
            out_device, in_device = self.handheld(facility), self.handheld(origin)
            out = self._scan(request, package, "RTS-OUT", request.at, out_device, facility=facility, barcode=self.label(package),
                             observation="RETURN_DISPATCH_SCAN")
            back = self._scan(request, package, "RTS-IN", arrive, in_device, facility=origin, barcode=self.label(package),
                              observation="RETURN_RECEIPT_SCAN")
            items += [message(out, "SPL_CORE", self.upload_time(out_device, request.at)),
                      message(back, "SPL_CORE", self.upload_time(in_device, arrive)),
                      message(self._custody(request, package, "RTS", arrive, "RECEIVED", facility, origin, back, facility_id=origin),
                              "SPL_CORE", self.upload_time(in_device, arrive))]
            self.moves[package.id] = [[request.at, "VEHICLE", "RETURN"], [arrive, "FACILITY", origin]]
        if items:
            self._withdraw_future(request, request.at)
        return items


def attach(store, reader, manifest, *, state_root=None, split="development"):
    """Attach the world simulator as the store's execution adapter, when a physical-state root is given (argument, or
    the state-root environment variable). Returns the adapter, or None with the store left without one: an authorized
    action is then recorded as not acknowledged and the case goes to a person."""
    from operations.datasets import is_world_dataset
    root = state_root or os.environ.get(STATE_ENVIRONMENT)
    if not getattr(store, "live", False) or not is_world_dataset(manifest.get("dataset_id")) or not root:
        return None
    state = PhysicalState.load(state_directory_for(root, manifest["dataset_id"], split))
    # The state must be this dataset's: every shipment it describes is one the gateway knows.
    known = store.gateway.reference().tracking_by_shipment
    if not state.recipients or not set(state.recipients) <= set(known):
        raise StateUnavailable("The physical state does not belong to the imported dataset")
    store.adapter = WorldOperationalSimulator(store.gateway, reader, state, store.config)
    return store.adapter
