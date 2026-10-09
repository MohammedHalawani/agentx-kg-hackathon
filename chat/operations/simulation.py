"""Synthetic operational world: how the (simulated) field responds to an executed action.

This stands in for real SPL, carrier and recipient systems in the development environment only.
It knows the scenario's physical facts (truth: whether a label was misread or wrongly applied,
whether a device buffered scans, where a parcel really is) and answers an executed action by
scheduling ordinary provider messages, which reach Suhail only through the normal ingestion
gateway at their delivery time. It never writes evidence directly, never marks anything verified,
and is never reachable from the investigator, its tools or the reviewer.
"""
from datetime import timedelta

from dataset_v2.contracts import Node, canonical, digest, instant, iso
from dataset_v2.feed import CHANNEL_PROVIDER, FEED_VERSION, encode
from operations.reasoning import evidence_world

# The receipt is what a field system acknowledges when it accepts a request: which request reached whom.
# It never describes the outcome or the field state (which only the simulator knows); the outcome
# reaches Suhail solely as ordinary provider messages through ingestion, judged by the verifier.
RECEIPTS = {
    "REQUEST_DEVICE_SYNC": "Sync request delivered to the device.",
    "REQUEST_RESCAN": "Rescan request sent to the facility holding the parcel.",
    "REQUEST_REWEIGH": "Reweigh request sent to the facility holding the parcel.",
    "REQUEST_HUB_CHECK": "Check request sent to the expected facility.",
    "INITIATE_CUSTODY_RECONCILIATION": "Custody reconciliation request sent to the facility.",
    "REQUEST_ADDRESS_CONFIRMATION": "Address confirmation request sent to the recipient.",
    "PRIORITIZE_NEXT_SESSION": "Shipment prioritized for the next delivery session.",
}
RESPONSE_DELAY = {"REQUEST_DEVICE_SYNC": 10, "REQUEST_RESCAN": 45, "REQUEST_REWEIGH": 60, "REQUEST_HUB_CHECK": 60,
                  "INITIATE_CUSTODY_RECONCILIATION": 90, "REQUEST_ADDRESS_CONFIRMATION": 120, "PRIORITIZE_NEXT_SESSION": None}
FACILITIES = ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse")


def message(node, channel, deliver_at):
    message_type, payload = encode(node, channel, None)
    return {"feed_id": "DEMO-FEED-" + digest([node.id, "SIMULATOR"])[:24], "channel": channel, "provider_id": CHANNEL_PROVIDER[channel],
            "message_type": message_type, "source_event_id": node.id, "deliver_at": deliver_at, "origin": "SIMULATOR",
            "payload_json": canonical(payload), "payload_hash": digest(payload), "feed_version": FEED_VERSION}


class OperationalSimulator:
    def __init__(self, gateway, reader, truth, config):
        self.gateway, self.reader, self.truth, self.config = gateway, reader, truth, config

    def respond(self, execution, now):
        """Schedule the field's response to an executed action. Returns what was scheduled (for the receipt)."""
        sid, action = execution["shipment_id"], execution["action_type"]
        physical = (self.truth.get(sid) or {}).get("physical") or {}
        context = self.reader.evidence(sid, now)
        world = evidence_world(context, self.config)
        handler = getattr(self, "_" + action.lower(), None)
        if handler is None:
            return {"acknowledged": False, "behaviour": "No field system accepts this request type."}
        at = instant(now)
        delay = RESPONSE_DELAY.get(action)
        items = handler(world, sid, physical, at, at + timedelta(minutes=delay or 0), execution)
        if items:
            self.gateway.enqueue(items)
        # The receipt depends on the action alone: nothing about what the field will report.
        return {"acknowledged": True, "behaviour": RECEIPTS[action]}

    # -- helpers ---------------------------------------------------------------------------
    def _node(self, kind, sid, key, when, **props):
        return Node(f"{sid}-SIM-{key}-{digest([kind, when.isoformat(), props.get('package_id')])[:8]}", kind,
                    {"shipment_id": sid, "occurred_at": iso(when), "recorded_at": iso(when), "source_ref": "synthetic:simulator-response", **props})

    def _packages(self, world):
        return sorted((n for n in world.nodes.values() if n.kind == "Package"), key=lambda n: n.id)

    def _holder_facility(self, world, package_id):
        """Facility of the last corroborated custody holder, else the session depot."""
        from dataset_v2.derive import custody_corroborated
        events = sorted((n for n in world.nodes.values() if n.kind == "CustodyEvent" and n.properties.get("package_id") == package_id),
                        key=lambda n: n.properties["occurred_at"])
        cutoff = max((instant(n.properties["recorded_at"]) for n in events), default=None)
        for event in reversed(events):
            holder = world.nodes.get(event.properties.get("to_id"))
            if holder is not None and holder.kind in FACILITIES and cutoff and custody_corroborated(world, event, cutoff):
                return holder.id
        session = next((n for n in world.nodes.values() if n.kind == "DeliverySession"), None)
        return session.properties.get("depot_id") if session else None

    def _scan(self, sid, package, facility, when, *, barcode=None, weight=None, kind="RESCAN"):
        # Requested checks are made with the facility's check workflow device, never with a handheld the
        # system may be showing as silent.
        props = {"package_id": package.id, "readable": True, "confidence": .99, "facility_id": facility,
                 "device_ref": "DEMO-DEV-CHK-" + facility.removeprefix("DEMO-"), "observation_type": kind,
                 "observed_barcode": barcode if barcode is not None else package.properties.get("manifest_barcode"),
                 "calibrated": weight is not None}
        if weight is not None:
            props.update(measured_weight_kg=weight, measurement_units="kg")
        return self._node("ScanEvent", sid, kind, when, **props)

    # -- action responses --------------------------------------------------------------------
    def _request_device_sync(self, world, sid, physical, now, at, execution):
        """Only the device the request targeted answers. The field state decides whether that device holds
        buffered scans, never which device answers: a request to the wrong device (or to none) leaves the
        offline handheld offline, and its scans arrive at its natural reconnect."""
        target = execution.get("target_device")
        if not target:
            return []
        if (physical.get("device") == "buffered_upload" and physical.get("device_id") == target
                and instant(physical["offline_from"]) <= now < instant(physical["natural_reconnect_at"])):
            feed_ids = self.gateway.pending_feed_ids(physical.get("buffered_event_ids", []))
            if feed_ids:
                self.gateway.reschedule(feed_ids, iso(at))
        beat = Node(f"{target}-HB-SIM-{at.strftime('%Y%m%dT%H%M')}", "DeviceHeartbeat",
                    {"occurred_at": iso(at), "recorded_at": iso(at), "device_id": target, "connectivity": "ONLINE",
                     "pending_uploads": 0, "last_upload_at": iso(at), "source_ref": "synthetic:simulator-response"})
        return [message(beat, "MDM", iso(at))]

    def _request_rescan(self, world, sid, physical, now, at, execution):
        items = []
        for package in self._packages(world):
            facility = self._holder_facility(world, package.id)
            if not facility:
                continue
            wrong = physical.get("label") == "wrong_label"
            observed = next((n.properties.get("observed_barcode") for n in world.nodes.values() if n.kind == "ScanEvent"
                             and n.properties.get("package_id") == package.id
                             and n.properties.get("observed_barcode") not in (None, package.properties.get("manifest_barcode"))), None)
            barcode = observed if wrong and observed else None
            items.append(message(self._scan(sid, package, facility, at, barcode=barcode), "SPL_CORE", iso(at + timedelta(seconds=40))))
        return items

    def _request_reweigh(self, world, sid, physical, now, at, execution):
        items = []
        for package in self._packages(world):
            facility = self._holder_facility(world, package.id)
            if not facility:
                continue
            weight = package.properties.get("weight_kg")
            if physical.get("scale") == "declared_weight_wrong":
                previous = [n.properties.get("measured_weight_kg") for n in world.nodes.values() if n.kind == "ScanEvent"
                            and n.properties.get("package_id") == package.id and n.properties.get("calibrated") is True]
                weight = previous[-1] if previous else weight
            items.append(message(self._scan(sid, package, facility, at, weight=weight, kind="REWEIGH"), "SPL_CORE", iso(at + timedelta(seconds=40))))
        return items

    def _located(self, world, sid, physical, at, custody, execution):
        """The request reaches the facilities the system can name from visible evidence: the last corroborated
        holder (else the session depot) and the expected location of each missing observation. The field
        state decides only whether the parcel is at one of them; if it is elsewhere, nobody finds it."""
        if physical.get("parcel") == "retained_by_contractor" or physical.get("contractor") == "unresponsive":
            return []  # Nobody answers: no messages follow.
        expected = {e.get("location_id") for e in execution.get("expected_evidence") or []
                    if isinstance(e, dict) and e.get("location_id")}
        items = []
        for package in self._packages(world):
            holder = self._holder_facility(world, package.id)
            asked = {f for f in (holder, *expected) if f}
            # Where the parcel physically is: at the depot when it was left there, returned unscanned, or received
            # by a handheld that was offline; otherwise at its last corroborated facility.
            at_depot = physical.get("parcel") in ("left_at_depot", "returned_unscanned") or physical.get("device") == "buffered_upload"
            facility = (physical.get("depot_id") if at_depot else None) or holder
            if not facility or facility not in asked:
                continue
            scan = self._scan(sid, package, facility, at, kind="CUSTODY_CHECK_SCAN")
            items.append(message(scan, "SPL_CORE", iso(at + timedelta(seconds=30))))
            if custody:
                last = sorted((n for n in world.nodes.values() if n.kind == "CustodyEvent" and n.properties.get("package_id") == package.id),
                              key=lambda n: n.properties["occurred_at"])
                source = last[-1].properties.get("to_id") if last else facility
                event = self._node("CustodyEvent", sid, "RECONCILE", at, package_id=package.id, from_id=source, to_id=facility,
                                   event_type="RECEIVED", source_event_id=scan.id, required_acknowledgments=2, received_acknowledgments=2,
                                   source_quality="CORROBORATED", facility_id=facility)
                items.append(message(event, "SPL_CORE", iso(at + timedelta(seconds=30))))
        return items

    def _request_hub_check(self, world, sid, physical, now, at, execution):
        return self._located(world, sid, physical, at, custody=False, execution=execution)

    def _initiate_custody_reconciliation(self, world, sid, physical, now, at, execution):
        return self._located(world, sid, physical, at, custody=True, execution=execution)

    def _request_address_confirmation(self, world, sid, physical, now, at, execution):
        if physical.get("recipient") not in ("confirms_address",):
            return []
        current = sorted((n for n in world.nodes.values() if n.kind == "AddressVersion"), key=lambda n: n.properties.get("version", 0))
        if not current:
            return []
        base = current[-1].properties
        shipment = world.nodes[sid].properties
        version = self._node("AddressVersion", sid, "ADDR-CONFIRMED", at, address_id=base.get("address_id"), version=(base.get("version") or 1) + 1,
                             valid_from=iso(at), valid_to=None, lat=base.get("lat"), lng=base.get("lng"), accuracy_m=base.get("accuracy_m"),
                             city=base.get("city"), address_text=base.get("address_text"), verification_status="VERIFIED",
                             confirmed_by=shipment.get("recipient_id"))
        return [message(version, "RECIPIENT_PORTAL", iso(at))]

    def _prioritize_next_session(self, world, sid, physical, now, at, execution):
        sessions = sorted((n for n in world.nodes.values() if n.kind == "DeliverySession" and instant(n.properties["start_at"]) > now),
                          key=lambda n: n.properties["start_at"])
        if not sessions:
            return []
        session = sessions[0]
        when = instant(session.properties["start_at"]) + timedelta(hours=2)
        shipment = world.nodes[sid].properties
        address = sorted((n for n in world.nodes.values() if n.kind == "AddressVersion"), key=lambda n: n.properties.get("version", 0))[-1]
        assignment = next((n for n in world.nodes.values() if n.kind == "VehicleAssignment" and n.properties.get("mode") == "last_mile"), None)
        items = []
        for package in self._packages(world):
            delivered = physical.get("recipient") != "unreachable"
            attempt = self._node("DeliveryAttempt", sid, "ATTEMPT", when, package_id=package.id, used_address_version_id=address.id,
                                 observed_gate="Gate 4", disposition="DELIVERED" if delivered else "FAILED",
                                 failed_reason=None if delivered else "RECIPIENT_NOT_REACHED", session_id=session.id,
                                 assignment_id=assignment.id if assignment else None)
            items.append(message(attempt, "SPL_CORE", iso(when + timedelta(seconds=30))))
            if not delivered:
                contact = self._node("ContactAttempt", sid, "CONTACT", when - timedelta(minutes=5), package_id=package.id, attempt_id=attempt.id,
                                     result="NO_RESPONSE", channel="synthetic_phone", source_actor_id=shipment.get("recipient_id"))
                items.append(message(contact, "SPL_CORE", iso(when + timedelta(seconds=30))))
                continue
            ap = address.properties
            auth = self._node("AuthenticationEvidence", sid, "AUTH", when, package_id=package.id, attempt_id=attempt.id, method="SYNTHETIC_OTP",
                              result="PASS", authorized_recipient_id=shipment.get("recipient_id"), expires_at=iso(when + timedelta(minutes=5)),
                              verification_policy="synthetic_bound_delivery_v1", secret_value_stored=False)
            handoff = self._node("HandoffEvidence", sid, "HANDOFF", when, package_id=package.id, attempt_id=attempt.id,
                                 recipient_id=shipment.get("recipient_id"), recipient_type="EXPECTED_RECIPIENT")
            proof = self._node("DeliveryProof", sid, "PROOF", when, package_id=package.id, attempt_id=attempt.id, address_version_id=address.id,
                               lat=ap.get("lat"), lng=ap.get("lng"), accuracy_m=20., authentication_id=auth.id, handoff_id=handoff.id,
                               verification_policy="synthetic_bound_delivery_v1")
            for node in (auth, handoff, proof):
                items.append(message(node, "SPL_CORE", iso(when + timedelta(seconds=30))))
        return items

