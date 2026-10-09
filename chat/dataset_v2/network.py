"""Live network dataset (DEMO-SUHAIL-LIVE-*): carriers, contractors, devices and provider feeds.

Builds on the V2 foundation generator and adds, deterministically from the seed:
- Providers: an SPL in-house fleet, a contracted 3PL linehaul carrier and an independent-driver
  platform whose drivers use private cars.
- Drivers with an employment type and provider; vehicles with ownership and class.
- Devices (facility handhelds, driver apps, scales). Every scan names the device that made it, and
  a driver-app scan at loading is the explicit physical custody confirmation.
- Versioned dispatch manifests per last-mile assignment and device heartbeat telemetry.
- Live scenario recipes layered on the foundation recipes (offline device upload, unreturned
  contractor parcel, unconfirmed pickup, conflicting manifest, label/scale variants).

The returned truth (scenario recipe, expected cause, physical facts the simulator needs) is kept
apart from the world: it is written next to the bundle for evaluation and the simulator only, and
is never a node property, an import record or an investigator input. Everything is synthetic.
"""
from dataclasses import replace
from datetime import timedelta
import hashlib

from dataset_v2.contracts import Config, Provenance, instant, iso
from dataset_v2.generate import Builder, NORMAL_RECIPES, PERTURBATIONS, close_custody_intervals, reopen_invalidated_cases, historical_outcomes

LIVE_DATASET_ID = "DEMO-SUHAIL-LIVE-1"
HEARTBEAT_MINUTES = 30  # Facility handheld telemetry cadence; silence across several beats is an outage signal.
NETWORK_VERSION = "live-network-1"

PROVIDERS = {
    "DEMO-PROV-SPL": {"provider_type": "IN_HOUSE", "name": "Synthetic SPL in-house fleet", "channel": "SPL_CORE"},
    "DEMO-PROV-3PL-01": {"provider_type": "CONTRACTOR_3PL", "name": "Synthetic contracted linehaul carrier", "channel": "CARRIER_EDI"},
    "DEMO-PROV-INDEP-01": {"provider_type": "INDEPENDENT_PLATFORM", "name": "Synthetic independent-driver platform", "channel": "DRIVER_APP"},
}

# live recipe -> (foundation recipe it perturbs, last-mile operator)
LIVE_NORMAL = {
    **{recipe: (recipe, "SPL") for recipe in NORMAL_RECIPES},
    "contractor_on_time": ("on_time", "INDEPENDENT"),
    "contractor_second_attempt": ("second_attempt", "INDEPENDENT"),
    "late_upload_within_tolerance": ("on_time", "SPL"),
    "duplicate_provider_events": ("on_time", "INDEPENDENT"),
}
LIVE_ABNORMAL = {
    **{recipe: (recipe, "SPL") for recipe in PERTURBATIONS},
    "offline_device_sync": ("on_time", "SPL"),
    "contractor_unreturned": ("unanswered_contact", "INDEPENDENT"),
    "contractor_unconfirmed_pickup": ("absent_session_receipt", "INDEPENDENT"),
    "conflicting_manifest": ("on_time", "INDEPENDENT"),
    "wrong_label_applied": ("different_barcode", "SPL"),
    "declared_weight_wrong": ("different_weight", "SPL"),
}
# Scenario recipes guaranteed to appear in the live (development) split.
REQUIRED_LIVE = ("offline_device_sync", "contractor_unreturned", "contractor_unconfirmed_pickup", "conflicting_manifest",
                 "wrong_label_applied", "different_barcode", "different_weight", "declared_weight_wrong",
                 "late_upload_within_tolerance", "duplicate_provider_events", "contractor_on_time")

ROOT_CAUSE = {
    "different_barcode": "BARCODE_MISMATCH", "wrong_label_applied": "BARCODE_MISMATCH",
    "different_weight": "WEIGHT_MISMATCH", "declared_weight_wrong": "WEIGHT_MISMATCH",
    "different_gate": "WRONG_GATE", "obsolete_address": "ADDRESS_CONFLICT", "later_hub_departure": "HUB_DELAY",
    "traffic_safe_return": "TRAFFIC_DELAY", "absent_session_receipt": "UNRECONCILED_CUSTODY",
    "absent_transfer_receipt": "CUSTODY_GAP", "unanswered_contact": "RECIPIENT_UNAVAILABLE",
    "report_with_corroboration": "DELIVERY_DISPUTE", "report_different_location": "POSSIBLE_MISDELIVERY",
    "report_failed_authentication": "PROOF_INSUFFICIENT", "report_photo_only": "PROOF_INSUFFICIENT",
    "report_authorized_alternate": "DELIVERY_DISPUTE", "weight_and_obsolete_address": "ADDRESS_CONFLICT",
    "partial_packages": "UNRECONCILED_CUSTODY", "conflicting_custody_sources": "CONFLICTING_CUSTODY",
    "report_after_prior_outcome": "DELIVERY_DISPUTE", "offline_device_sync": "DELAYED_SYNC",
    "contractor_unreturned": "UNRECONCILED_CUSTODY", "contractor_unconfirmed_pickup": "CUSTODY_GAP",
    "conflicting_manifest": "MANIFEST_CONFLICT",
}
# Causes an evaluator also accepts, because the same evidence legitimately supports them.
ACCEPTABLE = {
    "weight_and_obsolete_address": {"ADDRESS_CONFLICT", "WEIGHT_MISMATCH"},
    "report_different_location": {"POSSIBLE_MISDELIVERY", "DELIVERY_DISPUTE"},
    "report_failed_authentication": {"PROOF_INSUFFICIENT", "DELIVERY_DISPUTE"},
    "report_photo_only": {"PROOF_INSUFFICIENT", "DELIVERY_DISPUTE"},
    "report_authorized_alternate": {"DELIVERY_DISPUTE", "PROOF_INSUFFICIENT"},
    "report_with_corroboration": {"DELIVERY_DISPUTE"},
    "report_after_prior_outcome": {"DELIVERY_DISPUTE"},
    "absent_transfer_receipt": {"CUSTODY_GAP", "MISSED_MILESTONE"},
    "later_hub_departure": {"HUB_DELAY", "JOURNEY_DELAY", "MISSED_MILESTONE"},
    "traffic_safe_return": {"TRAFFIC_DELAY", "ROUTE_DELAY"},
    "contractor_unconfirmed_pickup": {"CUSTODY_GAP", "UNRECONCILED_CUSTODY"},
    "partial_packages": {"UNRECONCILED_CUSTODY", "CUSTODY_GAP"},
    "offline_device_sync": {"DELAYED_SYNC"},
}
# What resolution the scenario permits if Suhail acts correctly (evaluation only).
EXPECTED_RESOLUTION = {
    "different_barcode": "AUTO", "different_weight": "AUTO", "offline_device_sync": "AUTO",
    "contractor_unconfirmed_pickup": "AUTO", "later_hub_departure": "AUTO", "absent_session_receipt": "AUTO",
    "partial_packages": "AUTO", "absent_transfer_receipt": "AUTO",
    "wrong_label_applied": "HUMAN", "declared_weight_wrong": "HUMAN", "contractor_unreturned": "HUMAN",
    "conflicting_manifest": "HUMAN", "conflicting_custody_sources": "HUMAN",
    "report_with_corroboration": "HUMAN", "report_different_location": "HUMAN", "report_failed_authentication": "HUMAN",
    "report_photo_only": "HUMAN", "report_authorized_alternate": "HUMAN", "report_after_prior_outcome": "HUMAN",
    "different_gate": "AUTO", "obsolete_address": "AUTO", "weight_and_obsolete_address": "HUMAN",
    "traffic_safe_return": "AUTO", "unanswered_contact": "APPROVAL",
}
# Physical facts the operational simulator consults when Suhail requests an action.
PHYSICAL = {
    "different_barcode": {"label": "misread"}, "wrong_label_applied": {"label": "wrong_label"},
    "different_weight": {"scale": "miscalibrated"}, "declared_weight_wrong": {"scale": "declared_weight_wrong"},
    "weight_and_obsolete_address": {"scale": "declared_weight_wrong", "recipient": "confirms_address"},
    "different_gate": {"recipient": "confirms_address"}, "obsolete_address": {"recipient": "confirms_address"},
    "later_hub_departure": {"parcel": "at_origin_hub_delayed"}, "traffic_safe_return": {"recipient": "available_next_session"},
    "absent_session_receipt": {"parcel": "returned_unscanned"}, "partial_packages": {"parcel": "returned_unscanned"},
    "absent_transfer_receipt": {"parcel": "received_unscanned"}, "unanswered_contact": {"recipient": "unreachable"},
    "contractor_unreturned": {"parcel": "retained_by_contractor", "contractor": "unresponsive"},
    "contractor_unconfirmed_pickup": {"parcel": "left_at_depot"},
    "conflicting_manifest": {"parcel": "on_vehicle_manifest_error"},
    "offline_device_sync": {"device": "buffered_upload"},
}


def stable_fraction(*parts):
    """Deterministic [0,1) from text, independent of Python hash randomization."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0x100000000


def device_for_facility(facility_id):
    return "DEMO-DEV-HH-" + facility_id.removeprefix("DEMO-")


def device_for_driver(driver_id):
    return "DEMO-DEV-APP-" + driver_id.removeprefix("DEMO-")


class LiveBuilder(Builder):
    """Foundation builder whose last-mile allocation can use independent drivers with private cars."""

    def __init__(self, config):
        super().__init__(config)
        self.operator = "SPL"
        self.private_calendars = {}
        self.private_number = 0

    def vehicle(self, type_key, city, start, end):
        if self.operator != "INDEPENDENT" or type_key != "LMV":
            return super().vehicle(type_key, city, start, end)
        w = self.world
        for key in sorted(self.private_calendars):
            if w.nodes[key].properties["base_city"] == city and all(end <= a or start >= b for a, b in self.private_calendars[key]):
                self.private_calendars[key].append((start, end))
                return key
        self.private_number += 1
        key = f"DEMO-VEH-PRIVATE-{city}-{self.private_number:04d}"
        driver = f"DEMO-DRV-INDEP-{city}-{self.private_number:04d}"
        w.node("Driver", driver, display_name=f"{driver} synthetic independent driver", employment="INDEPENDENT",
               provider_id="DEMO-PROV-INDEP-01")
        # A private car: small payload, standard parcels only, last-mile use.
        w.node("Vehicle", key, type_id="DEMO-VTYPE-LMV", driver_id=driver, base_city=city, payload_kg=400., volume_m3=1.5,
               handling=["standard"], modes=["last_mile"], ownership="PRIVATE", vehicle_class="PRIVATE_CAR",
               provider_id="DEMO-PROV-INDEP-01", plate_ref=f"SYN-{city}-{self.private_number:04d}")
        w.edge(key, "HAS_TYPE", "DEMO-VTYPE-LMV")
        self.private_calendars[key] = [(start, end)]
        return key

    def recipes(self):
        """Assign live recipes per split; every required scenario recipe appears in development."""
        config = self.world.config
        normal, abnormal = sorted(LIVE_NORMAL), sorted(LIVE_ABNORMAL)
        jobs = []
        for split, count in config.split_counts.items():
            healthy = round(count * config.normal_fraction)
            first_normal = [r for r in REQUIRED_LIVE if r in LIVE_NORMAL] if split == "development" else []
            first_abnormal = [r for r in REQUIRED_LIVE if r in LIVE_ABNORMAL] if split == "development" else []
            pool = normal
            recipes = (first_normal + [pool[i % len(pool)] for i in range(healthy - len(first_normal))]
                       + first_abnormal + [abnormal[i % len(abnormal)] for i in range(count - healthy - len(first_abnormal))])
            self.rng.shuffle(recipes)
            jobs.extend((split, recipe) for recipe in recipes)
        self.rng.shuffle(jobs)
        return jobs

    def observed_world(self):
        self.catalog()
        self.network_catalog()
        self.truth = {}
        for index, (split, recipe) in enumerate(self.recipes(), 1):
            base, operator = {**LIVE_NORMAL, **LIVE_ABNORMAL}[recipe]
            # Roughly a third of ordinary last-mile work also goes to independent drivers.
            self.operator = operator if operator == "INDEPENDENT" else (
                "INDEPENDENT" if stable_fraction(self.world.config.seed, index) < .3 else "SPL")
            self.shipment(index, split, base)
            sid = f"DEMO-SHP-{index:06d}"
            self.world.gold[sid].update(live_recipe=recipe, foundation_recipe=base, intended_healthy=recipe in LIVE_NORMAL)
            self.truth[sid] = {"shipment_id": sid, "split": split, "recipe": recipe, "foundation_recipe": base,
                               "healthy": recipe in LIVE_NORMAL, "root_cause": ROOT_CAUSE.get(recipe),
                               "acceptable_causes": sorted(ACCEPTABLE.get(recipe, {ROOT_CAUSE.get(recipe)} - {None})),
                               "expected_resolution": "NONE" if recipe in LIVE_NORMAL else EXPECTED_RESOLUTION.get(recipe, "HUMAN"),
                               "physical": dict(PHYSICAL.get(recipe, {})), "key_evidence": []}
        self.operator = "SPL"
        return self.world

    def network_catalog(self):
        w = self.world
        for key, props in PROVIDERS.items():
            w.node("Provider", key, **props)


def fleet(w):
    """Provider, ownership and device for every vehicle and driver (idempotent; reruns cover late allocations)."""
    # Fleet ownership: linehaul trucks belong to the contracted 3PL; everything else is in-house.
    for vehicle in w.of_kind("Vehicle"):
        p = vehicle.properties
        if p.get("ownership"):
            continue
        third_party = p["type_id"] in ("DEMO-VTYPE-TRUCK", "DEMO-VTYPE-LHV") and p["base_city"] in ("DMM", "KHB", "DHA", "HOF", "JUB")
        provider = "DEMO-PROV-3PL-01" if third_party else "DEMO-PROV-SPL"
        p.update(ownership="PROVIDER" if third_party else "COMPANY", provider_id=provider,
                 vehicle_class={"DEMO-VTYPE-TRUCK": "TRUCK", "DEMO-VTYPE-HEAVY": "TRUCK", "DEMO-VTYPE-LHV": "VAN"}.get(p["type_id"], "VAN"))
        driver = w.nodes[p["driver_id"]].properties
        driver.update(employment="CONTRACTOR" if third_party else "EMPLOYEE", provider_id=provider)
    for driver in w.of_kind("Driver"):
        w.edge(driver.id, "WORKS_FOR", driver.properties["provider_id"])
    for vehicle in w.of_kind("Vehicle"):
        w.edge(vehicle.id, "OPERATED_BY", vehicle.properties["provider_id"])
    # Devices: facility handhelds, driver apps and the existing sorting scales.
    def device(key, kind, **props):
        if key not in w.nodes:
            w.node("Device", key, device_kind=kind, **props)
        return key
    for kind in ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse"):
        for facility in w.of_kind(kind):
            w.edge(facility.id, "USES_DEVICE", device(device_for_facility(facility.id), "FACILITY_HANDHELD", facility_id=facility.id))
    for driver in w.of_kind("Driver"):
        w.edge(driver.id, "USES_DEVICE", device(device_for_driver(driver.id), "DRIVER_APP", driver_id=driver.id,
                                                provider_id=driver.properties["provider_id"]))
    return device


def overlay(world, builder):
    """Providers, devices, manifests and live recipes on the generated foundation world."""
    truth = builder.truth
    w = world
    device = fleet(w)
    for scan in w.of_kind("ScanEvent"):
        ref = scan.properties.get("device_ref", "")
        if ref.startswith("DEMO-SCALE-") or ref in ("DEMO-VERIFICATION-SCALE",):
            device(ref, "CALIBRATED_SCALE")
    # Scans name the device that made them; a driver-app read at loading confirms physical custody.
    custody_by_raw = {c.properties["source_event_id"]: c for c in w.of_kind("CustodyEvent")}
    for scan in w.of_kind("ScanEvent"):
        p = scan.properties
        event = custody_by_raw.get(scan.id)
        if event is None:
            continue
        ep = event.properties
        vehicle = w.nodes.get(ep.get("vehicle_id")) if ep.get("vehicle_id") else None
        if ep["event_type"] in ("LOADED", "DELIVERED") and vehicle is not None:
            p["device_ref"] = device_for_driver(vehicle.properties["driver_id"])
            if ep["event_type"] == "LOADED":
                p["observation_type"] = "CUSTODY_CONFIRMATION"
        elif ep.get("to_id") in w.nodes and w.nodes[ep["to_id"]].kind in ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse"):
            p["device_ref"] = device_for_facility(ep["to_id"])
        elif ep.get("facility_id"):
            p["device_ref"] = device_for_facility(ep["facility_id"])
    # Dispatch manifests: one published version per last-mile assignment.
    for assignment in w.of_kind("VehicleAssignment"):
        ap = assignment.properties
        if ap.get("mode") != "last_mile":
            continue
        sid = ap["shipment_id"]
        vehicle = w.nodes[ap["vehicle_id"]].properties
        published = instant(ap["valid_from"]) - timedelta(minutes=20)
        manifest = w.node("Manifest", f"{assignment.id}-MANIFEST-V1", shipment_id=sid, split=ap["split"],
                          occurred_at=iso(published), recorded_at=iso(published), assignment_id=assignment.id,
                          session_id=ap.get("session_id"), vehicle_id=ap["vehicle_id"], driver_id=ap["driver_id"],
                          provider_id=vehicle["provider_id"], version=1, package_ids=list(ap["package_ids"]), manifest_status="PUBLISHED")
        w.edge(assignment.id, "HAS_MANIFEST", manifest)
        for pkg in ap["package_ids"]:
            w.edge(manifest, "LISTS", pkg)
    for sid, row in truth.items():
        apply = RECIPE_OVERLAYS.get(row["recipe"])
        if apply:
            apply(w, sid, row)
        if row["recipe"] == "accounted_return":
            _accounted_return(w, sid, row, builder)
    propagate_outages(w, truth)
    fleet(w)  # Vehicles allocated by recipe overlays (next-session redelivery) get providers and devices too.
    for sid, row in truth.items():
        last_mile = next((a for a in _owned(w, sid, "VehicleAssignment") if a.properties.get("mode") == "last_mile"), None)
        vehicle = w.nodes[last_mile.properties["vehicle_id"]].properties if last_mile else {}
        row.update(last_mile_vehicle_ownership=vehicle.get("ownership"), last_mile_provider_id=vehicle.get("provider_id"))
    heartbeats(w, truth)
    return truth


def propagate_outages(w, truth):
    """Every receipt the offline handheld made during its outage uploads late, for any shipment."""
    outages = [(row["physical"]["device_id"], instant(row["physical"]["offline_from"]), instant(row["physical"]["natural_reconnect_at"]))
               for row in truth.values() if row["physical"].get("device") == "buffered_upload" and row["physical"].get("device_id")]
    for device, start, reconnect in outages:
        for event in w.of_kind("CustodyEvent"):
            raw = w.nodes.get(event.properties["source_event_id"])
            if raw is None or raw.properties.get("device_ref") != device:
                continue
            if not start <= instant(event.properties["occurred_at"]) < reconnect or event.properties["recorded_at"] == iso(reconnect):
                continue
            for node in (raw, event):
                _delay(node, reconnect)
            row = truth[event.properties["shipment_id"]]
            row.setdefault("outage_affected_event_ids", []).extend([raw.id, event.id])
            if not row["healthy"] and "DELAYED_SYNC" not in row["acceptable_causes"]:
                # Two genuine issues: its own scenario and this device's late upload. Either is a correct finding.
                row["acceptable_causes"] = sorted({*row["acceptable_causes"], "DELAYED_SYNC"})
                row["secondary_issue"] = "DELAYED_SYNC"
            if row["healthy"]:
                # The parcel moved normally; only its receipt upload is late. That is now this shipment's cause.
                row.update(healthy=False, root_cause="DELAYED_SYNC", acceptable_causes=["DELAYED_SYNC"], expected_resolution="AUTO",
                           physical={"device": "buffered_upload", "device_id": device, "offline_from": iso(start),
                                     "natural_reconnect_at": iso(reconnect), "buffered_event_ids": [raw.id, event.id]},
                           key_evidence=[raw.id, event.id], secondary_effect_of="offline_device_sync")


def _owned(w, sid, kind):
    return sorted(w.owned(sid, kind), key=lambda n: (n.properties.get("occurred_at", ""), n.id))


def _last_mile_loads(w, sid):
    """LOADED transitions onto the last-mile vehicle (not the linehaul truck)."""
    out = []
    for event in _owned(w, sid, "CustodyEvent"):
        assignment = w.nodes.get(event.properties.get("assignment_id"))
        if event.properties["event_type"] == "LOADED" and assignment is not None and assignment.properties.get("mode") == "last_mile":
            out.append(event)
    return out


def _delay(node, until):
    node.properties["recorded_at"] = iso(until)


def _offline_device_sync(w, sid, row):
    """The destination depot's handheld goes offline: its receipt scans upload ~20h late."""
    shipment = w.nodes[sid].properties
    receipts = [c for c in _owned(w, sid, "CustodyEvent") if c.properties["event_type"] == "RECEIVED"
                and w.nodes[c.properties["to_id"]].kind == "DeliveryDepot"]
    if not receipts:
        return
    depot = receipts[0].properties["to_id"]
    device = device_for_facility(depot)
    start = instant(receipts[0].properties["occurred_at"]) - timedelta(minutes=40)
    reconnect = instant(receipts[0].properties["occurred_at"]) + timedelta(hours=20)
    buffered = []
    for event in receipts:
        raw = w.nodes[event.properties["source_event_id"]]
        for node in (raw, event):
            _delay(node, reconnect)
            buffered.append(node.id)
    row["physical"].update(device_id=device, offline_from=iso(start), natural_reconnect_at=iso(reconnect),
                           buffered_event_ids=buffered, depot_id=depot)
    row["outage_affected_event_ids"] = list(buffered)
    row["key_evidence"] = buffered


def _late_upload_within_tolerance(w, sid, row):
    """Driver-app uploads arrive ten minutes late: inside every tolerance, never a case."""
    for event in _owned(w, sid, "CustodyEvent"):
        if event.properties["event_type"] in ("LOADED", "DELIVERED"):
            for node in (event, w.nodes[event.properties["source_event_id"]]):
                _delay(node, instant(node.properties["occurred_at"]) + timedelta(minutes=10))
    row["physical"].update(upload_delay_minutes=10)


def _contractor_unreturned(w, sid, row):
    """Independent driver fails delivery, never returns the parcel; the private car does return."""
    removed = set()
    for event in _owned(w, sid, "CustodyEvent"):
        if event.properties["event_type"] == "RETURNED":
            removed |= {event.id, event.properties["source_event_id"]}
    removed |= {n.id for n in _owned(w, sid, "DepotReconciliation")}
    _remove(w, removed)
    status = next(n for n in _owned(w, sid, "StatusEvent"))
    status.properties["status"] = "OUT_FOR_DELIVERY"
    loaded = _last_mile_loads(w, sid)[0]
    attempts = _owned(w, sid, "DeliveryAttempt")
    row["physical"].update(vehicle_id=loaded.properties["to_id"], driver_id=w.nodes[loaded.properties["to_id"]].properties["driver_id"],
                           last_activity_at=attempts[-1].properties["occurred_at"] if attempts else loaded.properties["occurred_at"])
    row["key_evidence"] = [loaded.id, *[a.id for a in attempts]]


def _contractor_unconfirmed_pickup(w, sid, row):
    """The depot dispatched the parcel to the driver, but the driver app never confirmed pickup."""
    for event in _last_mile_loads(w, sid):
        event.properties.update(received_acknowledgments=1, source_quality="INCOMPLETE_ACK",
                                source_ref="synthetic:INCOMPLETE_ACK:depot-dispatch-scan")
        raw = w.nodes[event.properties["source_event_id"]]
        raw.properties.update(observation_type="DEPOT_DISPATCH_SCAN", device_ref=device_for_facility(event.properties["facility_id"]),
                              source_ref="synthetic:INCOMPLETE_ACK:depot-dispatch-scan")
        row["physical"].update(depot_id=event.properties["facility_id"], vehicle_id=event.properties["to_id"])
        row["key_evidence"] = [*row.get("key_evidence", []), event.id, raw.id]
        # No corroborated load, so no parcel/vehicle custody interval either.
        w.edges = {k: e for k, e in w.edges.items() if not (e.kind == "LOADED_ON" and e.properties.get("custody_event_id") == event.id)}
    row["root_cause"] = "CUSTODY_GAP"


def _conflicting_manifest(w, sid, row):
    """After the driver confirmed custody, a revised manifest drops the first package."""
    manifest = next(n for n in _owned(w, sid, "Manifest"))
    mp = manifest.properties
    loaded = _last_mile_loads(w, sid)[0]
    revised_at = instant(loaded.properties["occurred_at"]) + timedelta(minutes=35)
    dropped = mp["package_ids"][0]
    revised = w.node("Manifest", manifest.id.replace("-V1", "-V2"), shipment_id=sid, split=mp["split"],
                     occurred_at=iso(revised_at), recorded_at=iso(revised_at), assignment_id=mp["assignment_id"],
                     session_id=mp.get("session_id"), vehicle_id=mp["vehicle_id"], driver_id=mp["driver_id"],
                     provider_id=mp["provider_id"], version=2, package_ids=[p for p in mp["package_ids"] if p != dropped] or ["NONE"],
                     manifest_status="REVISED", supersedes_id=manifest.id)
    if revised and w.nodes[revised].properties["package_ids"] == ["NONE"]:
        w.nodes[revised].properties["package_ids"] = []
    w.edge(mp["assignment_id"], "HAS_MANIFEST", revised)
    w.edge(revised, "SUPERSEDES", manifest.id)
    for pkg in w.nodes[revised].properties["package_ids"]:
        w.edge(revised, "LISTS", pkg)
    row["physical"].update(dropped_package_id=dropped)
    row["key_evidence"] = [manifest.id, revised, loaded.id]


def _remove(w, removed):
    for key in removed:
        w.nodes.pop(key, None)
    w.edges = {k: e for k, e in w.edges.items() if e.start not in removed and e.end not in removed
               and e.properties.get("custody_event_id") not in removed and e.properties.get("end_evidence_id") not in removed}


def _accounted_return(w, sid, row, builder):
    """The agreed next session happens: the returned parcel is loaded again and delivered with bound proof."""
    shipment = w.nodes[sid].properties
    split = shipment["split"]
    session = next(n for n in _owned(w, sid, "DeliverySession") if n.id.endswith("NEXT-SESSION"))
    sp = session.properties
    start, end = instant(sp["start_at"]), instant(sp["end_at"])
    last_mile = next(a for a in _owned(w, sid, "VehicleAssignment") if a.properties.get("mode") == "last_mile")
    lp = last_mile.properties
    old_vehicle = w.nodes[lp["vehicle_id"]].properties
    builder.operator = "INDEPENDENT" if old_vehicle.get("ownership") == "PRIVATE" else "SPL"
    load_at = start + timedelta(minutes=30)
    grace = timedelta(seconds=sp.get("grace_seconds") or 0)
    vehicle = builder.vehicle("LARGE" if shipment["handling"] == "bulky" else "LMV", old_vehicle["base_city"], load_at, end + grace)
    builder.operator = "SPL"
    driver = w.nodes[vehicle].properties["driver_id"]
    def n(kind, suffix, when=None, **props):
        key = f"{sid}-{suffix}"
        if when is not None:
            props = {"occurred_at": iso(when), "recorded_at": iso(when), **props}
        w.node(kind, key, shipment_id=sid, split=split, **props)
        return key
    assignment = n("VehicleAssignment", "ASSIGN-NEXT-SESSION", vehicle_id=vehicle, driver_id=driver, valid_from=iso(load_at),
                   valid_to=iso(end + grace), package_ids=list(lp["package_ids"]), weight_kg=lp["weight_kg"], volume_m3=lp["volume_m3"],
                   mode="last_mile", segment_id=lp["segment_id"], session_id=session.id)
    for kind, end_id in (("USES_VEHICLE", vehicle), ("ASSIGNED_DRIVER", driver), ("ON_SEGMENT", lp["segment_id"]), ("IN_SESSION", session.id)):
        w.edge(assignment, kind, end_id)
    w.edge(vehicle, "HAS_ASSIGNMENT", assignment)
    depot = sp["depot_id"]
    recipient = shipment["recipient_id"]
    address = w.nodes[shipment["current_address_version_id"]]
    av = address.properties
    delivered_at = load_at + timedelta(hours=2)
    for pkg in lp["package_ids"]:
        tag = pkg.rsplit("-", 1)[-1]
        w.edge(assignment, "CARRIES", pkg)
        def custody(seq, when, frm, to, event, device, proof=None, observation="HANDOVER_BARCODE_READ"):
            raw = n("ScanEvent", f"RAW-NEXT-{tag}-{seq}", when, package_id=pkg, observed_barcode=w.nodes[pkg].properties["manifest_barcode"],
                    readable=True, confidence=.99, calibrated=False, facility_id=depot if event != "DELIVERED" else None,
                    device_ref=device, observation_type=observation, source_ref="synthetic:CORROBORATED:handover-observation")
            key = n("CustodyEvent", f"CUST-NEXT-{tag}-{seq}", when, package_id=pkg, from_id=frm, to_id=to, event_type=event, source_event_id=raw,
                    required_acknowledgments=2, received_acknowledgments=2, source_quality="CORROBORATED",
                    source_ref="synthetic:CORROBORATED:handover-observation", facility_id=depot if event != "DELIVERED" else None,
                    vehicle_id=vehicle, assignment_id=assignment, **({"proof_id": proof} if proof else {}))
            w.edge(pkg, "HAS_SCAN", raw); w.edge(pkg, "HAS_CUSTODY_EVENT", key); w.edge(sid, "HAS_CUSTODY_EVENT", key)
            w.edge(key, "OBSERVED_BY", raw); w.edge(key, "FROM_CUSTODIAN", frm); w.edge(key, "TO_CUSTODIAN", to)
            return key
        app = device_for_driver(driver)
        custody(1, load_at, depot, vehicle, "LOADED", app, observation="CUSTODY_CONFIRMATION")
        attempt = n("DeliveryAttempt", f"ATT-NEXT-{tag}", delivered_at, package_id=pkg, used_address_version_id=address.id,
                    observed_gate="Gate 4", disposition="DELIVERED", failed_reason=None, session_id=session.id, assignment_id=assignment)
        w.edge(sid, "HAS_ATTEMPT", attempt); w.edge(pkg, "HAS_ATTEMPT", attempt); w.edge(attempt, "USED_ADDRESS", address.id)
        auth = n("AuthenticationEvidence", f"AUTH-NEXT-{tag}", delivered_at, package_id=pkg, attempt_id=attempt, method="SYNTHETIC_OTP",
                 result="PASS", authorized_recipient_id=recipient, expires_at=iso(delivered_at + timedelta(minutes=5)),
                 verification_policy="synthetic_bound_delivery_v1", secret_value_stored=False)
        handoff = n("HandoffEvidence", f"HANDOFF-NEXT-{tag}", delivered_at, package_id=pkg, attempt_id=attempt, recipient_id=recipient,
                    recipient_type="EXPECTED_RECIPIENT", authorization_ref=None)
        photo = n("PhotoEvidence", f"PHOTO-NEXT-{tag}", delivered_at, package_id=pkg, attempt_id=attempt, address_version_id=address.id,
                  lat=av["lat"], lng=av["lng"], accuracy_m=20., subject="door_metadata", media_ref=f"synthetic://{sid}/next-photo", no_image_generated=True)
        proof = n("DeliveryProof", f"PROOF-NEXT-{tag}", delivered_at, package_id=pkg, attempt_id=attempt, address_version_id=address.id,
                  lat=av["lat"], lng=av["lng"], accuracy_m=20., authentication_id=auth, signature_id=None, photo_id=photo, handoff_id=handoff,
                  verification_policy="synthetic_bound_delivery_v1")
        w.edge(attempt, "HAS_PROOF", proof)
        for kind, end_id in (("HAS_AUTHENTICATION", auth), ("HAS_PHOTO", photo), ("HAS_HANDOFF", handoff)):
            w.edge(proof, kind, end_id)
        receipt = custody(2, delivered_at, vehicle, recipient, "DELIVERED", app, proof=proof)
        recon = n("DepotReconciliation", f"RECON-NEXT-{tag}", delivered_at + timedelta(minutes=1), package_id=pkg, session_id=session.id,
                  result="DELIVERED", proof_id=proof, receipt_id=receipt, attempt_id=attempt)
        w.edge(sid, "HAS_RECONCILIATION", recon); w.edge(recon, "SUPPORTED_BY", proof)
    status = n("StatusEvent", "STATUS-NEXT-SESSION", delivered_at, status="DELIVERED", assertion_source="synthetic_tracking")
    w.edge(sid, "HAS_STATUS", status)
    # A manifest for the new dispatch, like every other last-mile assignment.
    published = load_at - timedelta(minutes=20)
    manifest = n("Manifest", "ASSIGN-NEXT-SESSION-MANIFEST-V1", published, assignment_id=assignment, session_id=session.id,
                 vehicle_id=vehicle, driver_id=driver, provider_id=w.nodes[vehicle].properties.get("provider_id", "DEMO-PROV-SPL"), version=1,
                 package_ids=list(lp["package_ids"]), manifest_status="PUBLISHED")
    w.edge(assignment, "HAS_MANIFEST", manifest)
    for pkg in lp["package_ids"]:
        w.edge(manifest, "LISTS", pkg)


RECIPE_OVERLAYS = {"offline_device_sync": _offline_device_sync, "late_upload_within_tolerance": _late_upload_within_tolerance,
                   "contractor_unreturned": _contractor_unreturned, "contractor_unconfirmed_pickup": _contractor_unconfirmed_pickup,
                   "conflicting_manifest": _conflicting_manifest}


def heartbeats(w, truth):
    """Device telemetry: depot handhelds every 30 min, independent-driver apps hourly while assigned.

    An offline handheld sends nothing until it reconnects; its first heartbeat then reports the
    uploads it had buffered. An unreturned contractor's app goes silent after the last attempt.
    """
    start, end = instant(w.config.start_at), instant(w.config.as_of)
    outages = {}
    for row in truth.values():
        phys = row["physical"]
        if phys.get("device") == "buffered_upload" and phys.get("device_id"):
            outages.setdefault(phys["device_id"], []).append((instant(phys["offline_from"]), instant(phys["natural_reconnect_at"]),
                                                              len(phys["buffered_event_ids"]) // 2))
    silent = {row["physical"]["driver_id"]: instant(row["physical"]["last_activity_at"]) for row in truth.values()
              if row["recipe"] == "contractor_unreturned" and row["physical"].get("driver_id")}
    def beat(device, when, pending=0, last_upload=None):
        key = f"{device}-HB-{when.strftime('%Y%m%dT%H%M')}"
        if key in w.nodes:
            return
        w.node("DeviceHeartbeat", key, occurred_at=iso(when), recorded_at=iso(when), device_id=device,
               connectivity="ONLINE", pending_uploads=pending, last_upload_at=iso(last_upload or when))
        w.edge(device, "HAS_TELEMETRY", key)
    for depot in w.of_kind("DeliveryDepot"):
        device = device_for_facility(depot.id)
        windows = outages.get(device, [])
        for a, b, pending in windows:  # The reconnect beat reports what was buffered; it wins over a regular beat.
            beat(device, b, pending=pending, last_upload=a)
        when = start
        while when <= end:
            if not any(a <= when < b for a, b, _ in windows):
                beat(device, when)
            when += timedelta(minutes=HEARTBEAT_MINUTES)
    for assignment in w.of_kind("VehicleAssignment"):
        p = assignment.properties
        driver = w.nodes[p["driver_id"]].properties
        if driver.get("employment") != "INDEPENDENT":
            continue
        device = device_for_driver(p["driver_id"])
        when, finish = instant(p["valid_from"]), instant(p["valid_to"])
        while when <= finish:
            if p["driver_id"] not in silent or when <= silent[p["driver_id"]]:
                beat(device, when)
            when += timedelta(hours=1)


def live_history_outcomes(world, truth):
    """History precedents name the catalog action that fits each cause and its verified result.

    The foundation history author records every resolution as generic delivery reconciliation.
    Here the action type follows the scenario, and scenarios whose first action does not work
    (wrong label, declared weight wrong, unreturned contractor parcel) record a failed outcome.
    """
    action_for = {"BARCODE_MISMATCH": "REQUEST_RESCAN", "WEIGHT_MISMATCH": "REQUEST_REWEIGH", "DELAYED_SYNC": "REQUEST_DEVICE_SYNC",
                  "UNRECONCILED_CUSTODY": "INITIATE_CUSTODY_RECONCILIATION", "CUSTODY_GAP": "INITIATE_CUSTODY_RECONCILIATION",
                  "HUB_DELAY": "REQUEST_HUB_CHECK", "ADDRESS_CONFLICT": "REQUEST_ADDRESS_CONFIRMATION", "WRONG_GATE": "REQUEST_ADDRESS_CONFIRMATION",
                  "TRAFFIC_DELAY": "PRIORITIZE_NEXT_SESSION", "RECIPIENT_UNAVAILABLE": "PRIORITIZE_NEXT_SESSION"}
    failing = {"wrong_label_applied", "declared_weight_wrong", "contractor_unreturned"}
    by_group = {}
    for node in world.nodes.values():
        by_group.setdefault(node.properties.get("holdout_group"), []).append(node)
    for sid, row in truth.items():
        if row["split"] != "history" or row["healthy"]:
            continue
        action = action_for.get(row["root_cause"])
        if not action:
            continue
        nodes = by_group.get(sid, [])
        for node in nodes:
            if node.kind in ("Recommendation", "ActionExecution", "Resolution", "Outcome") and node.properties.get("action_type") == "delivery_reconciliation":
                node.properties["action_type"] = action
            if node.kind == "Resolution":
                node.properties["action"] = f"{action} (synthetic verified history)"
        if row["recipe"] in failing:
            for node in nodes:
                if node.kind == "Outcome" and node.properties.get("invalidated") is False:
                    node.properties.update(success=False, status="failed")
                if node.kind == "Case" and node.properties.get("state") == "RESOLVED":
                    node.properties.update(state="ESCALATED", operationally_resolved=False)
                    node.properties.pop("resolved_at", None)
                    node.properties.pop("resolution_id", None)


def live_config(**overrides):
    values = dict(total=600, seed=7, simulation_days=10, dataset_id=LIVE_DATASET_ID, normal_fraction=.70)
    values.update(overrides)
    return Config(**values)


def generate_live(config=None):
    """Full live world (all splits, all evidence) plus truth. The feed split happens in feed.py."""
    config = config or live_config()
    builder = LiveBuilder(config)
    world = builder.observed_world()
    truth = overlay(world, builder)
    from dataset_v2.derive import derive_world
    derive_world(world)
    reopen_invalidated_cases(world)
    historical_outcomes(world, builder)
    fleet(world)  # Recovery vehicles allocated by the history author.
    for scan in world.of_kind("ScanEvent"):
        ref = scan.properties.get("device_ref", "")
        if ref and ref not in world.nodes:
            world.node("Device", ref, device_kind="CALIBRATED_SCALE" if "SCALE" in ref else "FACILITY_HANDHELD")
    live_history_outcomes(world, truth)
    close_custody_intervals(world)
    return world, truth
