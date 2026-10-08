"""Deterministic Saudi demo world. Observation recipes perturb healthy journeys.

No database, environment, provider, external reference lookup or wall clock is used.
Recipe names and scoring expectations exist only in World.gold, never node properties.
"""
from datetime import datetime, timedelta
import math
import random

from dataset_v2.contracts import Config, POLICY_VERSION, Provenance, RIYADH, World, instant, iso

CITIES = (
    ("RUH", "Riyadh", 24.71, 46.67, "central"),
    ("JED", "Jeddah", 21.54, 39.17, "west"),
    ("MAK", "Makkah", 21.42, 39.83, "west"),
    ("MED", "Madinah", 24.47, 39.61, "west"),
    ("DMM", "Dammam", 26.43, 50.10, "east"),
    ("KHB", "Khobar", 26.22, 50.20, "east"),
    ("DHA", "Dhahran", 26.29, 50.14, "east"),
    ("HOF", "Hofuf", 25.38, 49.59, "east"),
    ("JUB", "Jubail", 27.01, 49.66, "east"),
)
VEHICLE_TYPES = {
    "LMV": (750., 6., ["standard"], ["last_mile", "local_transfer"]),
    "LARGE": (2000., 14., ["standard", "bulky"], ["last_mile", "local_transfer"]),
    "LHV": (1200., 10., ["standard"], ["linehaul", "local_transfer"]),
    "TRUCK": (10000., 50., ["standard", "bulky"], ["linehaul"]),
    "HEAVY": (16000., 80., ["standard", "bulky"], ["linehaul", "last_mile", "local_transfer"]),
}
NORMAL_RECIPES = ("on_time", "next_day", "second_attempt", "accounted_return", "bulky_normal", "fulfillment")
# These recipes alter observable values or remove observations; labels are derived later.
PERTURBATIONS = (
    "different_barcode", "different_weight", "different_gate", "obsolete_address",
    "later_hub_departure", "traffic_safe_return", "absent_session_receipt",
    "absent_transfer_receipt", "unanswered_contact", "report_with_corroboration",
    "report_different_location", "report_failed_authentication", "report_photo_only",
    "report_authorized_alternate", "weight_and_obsolete_address", "partial_packages",
    "conflicting_custody_sources", "report_after_prior_outcome",
)


def _id(kind, index):
    return f"DEMO-{kind}-{index:06d}"


def _day_time(day: datetime, value: str) -> datetime:
    hour, minute = map(int, value.split(":"))
    return day.astimezone(RIYADH).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _session(config, ready):
    start = _day_time(ready, config.session_start)
    end = _day_time(ready, config.session_end)
    if max(ready, start) + timedelta(hours=3) > end:
        start += timedelta(days=1)
        end += timedelta(days=1)
    return start, end, max(ready, start)


def _linehaul_hours(origin, destination):
    # Synthetic duration from approximate city anchors, not an actual road route/schedule.
    lat1, lon1, lat2, lon2 = map(math.radians, (origin[2], origin[3], destination[2], destination[3]))
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    kilometres = 6371 * 2 * math.asin(math.sqrt(a))
    return max(1., round(kilometres / 65 + .5, 2))


class Builder:
    def __init__(self, config):
        self.world = World(config)
        self.rng = random.Random(config.seed)
        self.calendars = {}
        self.vehicle_numbers = {key: 0 for key in VEHICLE_TYPES}
        self.assignment_number = 0
        self.facilities = {}
        self.organizations = {}

    def catalog(self):
        w = self.world
        for code, name, lat, lng, _ in CITIES:
            city = f"DEMO-CITY-{code}"
            w.node("City", city, name=name, lat=lat, lng=lng, coordinate_accuracy_m=5000,
                   provenance=Provenance.REFERENCE_DATA, source_ref="user-provided-city-scope",
                   coordinate_provenance="SYNTHETIC_DEMO_ASSUMPTION")
            for num in (1, 2, 3):
                org = f"DEMO-ORG-{code}-{num:02d}"
                w.node("Organization", org, name=f"{org} synthetic organization",
                       organization_type="fulfillment_operator" if num == 3 else "merchant")
                w.edge(org, "IN_CITY", city)
                self.organizations[code, num] = org
            for index, (kind, prefix) in enumerate((
                    ("Branch", "BRANCH"), ("Hub", "HUB"), ("SortingCenter", "SORT"),
                    ("DeliveryDepot", "DEPOT"), ("FulfillmentWarehouse", "FULFILL"))):
                key = f"DEMO-{prefix}-{code}-01"
                w.node(kind, key, name=f"{key} synthetic facility", city=name,
                       lat=round(lat + .006 * index, 5), lng=round(lng + .004 * index, 5),
                       accuracy_m=1000, operating_assumption="synthetic demo only",
                       operator_org_id=self.organizations[code, 3])
                w.edge(key, "IN_CITY", city)
                w.edge(self.organizations[code, 3], "OPERATES", key)
                self.facilities[code, kind] = key
            for num in (1, 2):
                key = f"DEMO-ORGWH-{code}-{num:02d}"
                w.node("OrganizationWarehouse", key, name=f"{key} synthetic owned warehouse",
                       city=name, lat=lat-.01*num, lng=lng-.008*num, accuracy_m=1000,
                       owner_org_id=self.organizations[code, num])
                w.edge(self.organizations[code, num], "OWNS", key)
                w.edge(key, "IN_CITY", city)
                self.facilities[code, f"OrganizationWarehouse{num}"] = key
        for key, (payload, volume, handling, modes) in VEHICLE_TYPES.items():
            w.node("VehicleType", f"DEMO-VTYPE-{key}", payload_kg=payload, volume_m3=volume,
                   handling=handling, modes=modes)
        for key, max_weight, handling in (("SMALL", 30., "standard"), ("BULKY", 300., "bulky")):
            w.node("ShipmentType", f"DEMO-STYPE-{key}", class_name=key, maximum_package_kg=max_weight,
                   handling=handling)
            w.node("HandlingRequirement", f"DEMO-HANDLING-{key}", handling=handling)
        for key, allowance in (("EXPRESS", 1800), ("STANDARD", 5400), ("APPOINTMENT", 10800)):
            w.node("ServiceLevel", f"DEMO-SERVICE-{key}", name=key, milestone_tolerance_seconds=allowance,
                   promise_kind="synthetic contextual journey")
        w.node("Policy", "DEMO-POLICY-01", version=POLICY_VERSION,
               barcode_min_confidence=.9, weight_absolute_kg=.5, weight_relative_fraction=.1,
               retry_limit=3, reconciliation_grace_seconds=w.config.reconciliation_grace_minutes*60,
               verification_policy="synthetic_bound_delivery_v1",
               scope="synthetic evidence rules, not SPL operating policy")

    def vehicle(self, type_key, city, start, end):
        w = self.world
        for key in sorted(self.calendars):
            node = w.nodes[key]
            if node.properties["type_id"] != f"DEMO-VTYPE-{type_key}" or node.properties["base_city"] != city:
                continue
            if all(end <= a or start >= b for a, b in self.calendars[key]):
                self.calendars[key].append((start, end))
                return key
        self.vehicle_numbers[type_key] += 1
        num = self.vehicle_numbers[type_key]
        key = f"DEMO-VEH-{type_key}-{city}-{num:04d}"
        driver = f"DEMO-DRV-{type_key}-{city}-{num:04d}"
        payload, volume, handling, modes = VEHICLE_TYPES[type_key]
        w.node("Driver", driver, display_name=f"{driver} synthetic assigned driver")
        w.node("Vehicle", key, type_id=f"DEMO-VTYPE-{type_key}", driver_id=driver,
               base_city=city, payload_kg=payload, volume_m3=volume, handling=handling, modes=modes)
        w.edge(key, "HAS_TYPE", f"DEMO-VTYPE-{type_key}")
        self.calendars[key] = [(start, end)]
        return key

    def shipment(self, index, split, recipe):
        w, rng, config = self.world, self.rng, self.world.config
        sid = _id("SHP", index)
        origin = CITIES[(index-1) % len(CITIES)]
        destination = origin if index % 4 == 0 else CITIES[((index-1) % 9 + rng.randrange(1, 9)) % 9]
        oc, dc = origin[0], destination[0]
        flow = ("C2C",)*3 + ("B2C",)*5 + ("B2B",)*2
        flow = flow[(index-1) % 10]
        bulky = recipe == "bulky_normal" or (flow == "B2B" and index % 2 == 0)
        service = "APPOINTMENT" if bulky else "EXPRESS" if index % 3 == 0 else "STANDARD"
        handling = "bulky" if bulky else "standard"
        type_key = "BULKY" if bulky else "SMALL"
        count = 3 + index % 2 if flow == "B2B" or recipe == "partial_packages" else 1 + int(index % 7 == 0)
        t0 = _day_time(instant(config.start_at)+timedelta(days=(index-1) % config.simulation_days), "08:00")
        w.node("Shipment", sid, shipment_id=sid, split=split, tracking_id=_id("TRACK", index),
               flow_type=flow, origin_city=origin[1], destination_city=destination[1],
               status="CREATED", policy_id="DEMO-POLICY-01", handling=handling,
               occurred_at=iso(t0), recorded_at=iso(t0), collection_mode="dropoff" if index % 2 else "pickup")

        def n(kind, suffix, when=None, **props):
            key = f"{sid}-{suffix}"
            if when is not None:
                props = {"occurred_at": iso(when), "recorded_at": iso(when), **props}
            w.node(kind, key, shipment_id=sid, split=split, **props)
            return key

        sender = self.organizations[oc, 1]
        if flow == "C2C":
            sender = n("Customer", "SENDER", display_name=f"{sid} synthetic sender", contact_ref=f"sender-{index}@demo.invalid")
        recipient = self.organizations[dc, 2] if flow == "B2B" else n(
            "Customer", "RECIPIENT", display_name=f"{sid} synthetic recipient", contact_ref=f"recipient-{index}@demo.invalid")
        w.nodes[sid].properties.update(sender_id=sender, recipient_id=recipient)
        w.edge(sender, "SENDS", sid)
        w.edge(recipient, "RECEIVES", sid)
        for kind, end in (("HAS_TYPE", f"DEMO-STYPE-{type_key}"), ("USES_SERVICE", f"DEMO-SERVICE-{service}"),
                          ("REQUIRES", f"DEMO-HANDLING-{type_key}"), ("GOVERNED_BY", "DEMO-POLICY-01")):
            w.edge(sid, kind, end)
        origin_facility = self.facilities[oc, "Branch"] if flow == "C2C" else self.facilities[
            oc, "FulfillmentWarehouse" if recipe == "fulfillment" or index % 3 == 0 else "OrganizationWarehouse1"]
        address = n("Address", "ADDRESS", city=destination[1])
        address2 = recipe in ("obsolete_address", "weight_and_obsolete_address")
        old_lat, old_lng = destination[2]+.015, destination[3]+.012
        version1 = n("AddressVersion", "ADDR-01", address_id=address, version=1,
                     valid_from=iso(t0-timedelta(days=1)), valid_to=iso(t0+timedelta(hours=6)) if address2 else None,
                     lat=old_lat, lng=old_lng, accuracy_m=20., city=destination[1],
                     address_text=f"DEMO address {index}, {destination[1]}")
        w.edge(version1, "VERSION_OF", address)
        w.edge(sid, "HAS_ADDRESS_VERSION", version1)
        current = version1
        if address2:
            current = n("AddressVersion", "ADDR-02", address_id=address, version=2,
                        valid_from=iso(t0+timedelta(hours=6)), valid_to=None,
                        lat=old_lat+.03, lng=old_lng+.02, accuracy_m=20., city=destination[1],
                        address_text=f"DEMO updated address {index}, {destination[1]}")
            w.edge(current, "VERSION_OF", address)
            w.edge(current, "SUPERSEDES", version1)
            w.edge(sid, "HAS_ADDRESS_VERSION", current)
        av = w.nodes[current].properties
        pin = n("LocationPin", "PIN", t0+timedelta(hours=6), address_version_id=current,
                supplier_id=recipient, purpose="recipient_supplied_destination", lat=av["lat"], lng=av["lng"],
                accuracy_m=20., verification_status="ATTRIBUTED_REPORT")
        w.edge(current, "HAS_PIN", pin)
        instruction = n("DeliveryInstruction", "INSTRUCTION", address_version_id=current, gate="Gate 4",
                        version=2 if address2 else 1, valid_from=w.nodes[current].properties["valid_from"], valid_to=None,
                        supplied_by=recipient, verification_status="ATTRIBUTED_REPORT")
        w.edge(current, "HAS_INSTRUCTION", instruction)
        w.nodes[sid].properties["current_address_version_id"] = current
        packages = []
        for number in range(1, count+1):
            weight = round(rng.uniform(170, 250) if bulky else rng.uniform(.5, 15), 2)
            dims = (1.2, .8, .7) if bulky else (.35, .25, .2)
            key = n("Package", f"PKG-{number:02d}", package_id=f"{sid}-PKG-{number:02d}",
                    manifest_barcode=f"DM{index:07d}{number:02d}", weight_kg=weight,
                    length_m=dims[0], width_m=dims[1], height_m=dims[2],
                    volume_m3=round(math.prod(dims), 6), handling=handling,
                    declared_class="synthetic bulky goods" if bulky else "synthetic standard goods")
            packages.append(key)
            w.edge(sid, "HAS_PACKAGE", key)
            if flow != "C2C":
                inventory = n("InventoryRecord", f"INVENTORY-{number:02d}", t0-timedelta(hours=1),
                              package_id=key, organization_id=sender, facility_id=origin_facility,
                              available_quantity=1, reserved_quantity=1)
                w.edge(sender, "OWNS", inventory)
                w.edge(inventory, "STORED_AT", origin_facility)
                w.edge(inventory, "ALLOCATES", key)
        w.nodes[sid].properties["package_ids"] = packages

        intercity = oc != dc
        sorting, hub, depot = self.facilities[oc, "SortingCenter"], self.facilities[oc, "Hub"], self.facilities[dc, "DeliveryDepot"]
        d_hub, d_sorting = self.facilities[dc, "Hub"], self.facilities[dc, "SortingCenter"]
        line_start = _day_time(t0, "20:00")
        line_end = line_start + timedelta(hours=_linehaul_hours(origin, destination))
        depot_time = (line_end+timedelta(hours=4)) if intercity else t0+timedelta(hours=6)
        if recipe == "next_day":
            depot_time += timedelta(days=1)
        session_start, session_end, load_at = _session(config, depot_time+timedelta(hours=1))
        if recipe == "accounted_return":
            promise_session_start, promise_session_end = session_start+timedelta(days=1), session_end+timedelta(days=1)
        else:
            promise_session_start, promise_session_end = session_start, session_end
        grace = timedelta(minutes=config.reconciliation_grace_minutes)
        cutoff = session_end+grace+timedelta(minutes=1)
        w.nodes[sid].properties["as_of"] = iso(cutoff)
        tolerance = w.nodes[f"DEMO-SERVICE-{service}"].properties["milestone_tolerance_seconds"]
        route = n("Route", "ROUTE", version=1)
        journey = n("JourneyPlan", "JOURNEY", t0, route_id=route, service_id=f"DEMO-SERVICE-{service}",
                    type_id=f"DEMO-STYPE-{type_key}", policy_id="DEMO-POLICY-01", policy_version=POLICY_VERSION,
                    promise_at=iso(promise_session_end), as_of=iso(cutoff), version=1, effective_at=iso(t0))
        w.nodes[sid].properties["journey_id"] = journey
        w.edge(sid, "EXPECTED_ROUTE", route)
        w.edge(sid, "HAS_PLAN", journey)
        facility_path = [origin_facility, sorting, hub] + ([d_hub, d_sorting] if intercity else []) + [depot, address]
        segments = []
        for seq, (a, b) in enumerate(zip(facility_path, facility_path[1:]), 1):
            mode = "last_mile" if b == address else "linehaul" if a == hub and b == d_hub and intercity else "local_transfer"
            duration = _linehaul_hours(origin, destination)*3600 if mode == "linehaul" else 7200
            seg = n("RouteSegment", f"SEG-{seq:02d}", from_id=a, to_id=b, sequence=seq, mode=mode,
                    minimum_seconds=round(duration*.8), maximum_seconds=round(duration*1.3))
            segments.append(seg)
            w.edge(route, "CONTAINS", seg, sequence=seq)
            w.edge(seg, "FROM", a)
            w.edge(seg, "TO", b)
        w.nodes[route].properties["segment_ids"] = segments
        lm_segment = segments[-1]
        line_segment = next((key for key in segments if w.nodes[key].properties["mode"] == "linehaul"), None)
        session = n("DeliverySession", "SESSION", depot_id=depot, start_at=iso(session_start), end_at=iso(session_end),
                    timezone="Asia/Riyadh", grace_seconds=int(grace.total_seconds()),
                    start_local=config.session_start, end_local=config.session_end,
                    operating_assumption="configurable synthetic local delivery session")
        w.edge(session, "AT_FACILITY", depot)
        next_session = n("DeliverySession", "NEXT-SESSION", depot_id=depot,
                         start_at=iso(session_start+timedelta(days=1)), end_at=iso(session_end+timedelta(days=1)),
                         timezone="Asia/Riyadh", grace_seconds=int(grace.total_seconds()),
                         start_local=config.session_start, end_local=config.session_end)
        w.edge(session, "NEXT_SESSION", next_session)

        actual_shift = timedelta(hours=12) if recipe == "later_hub_departure" else timedelta(0)
        actual_depot = depot_time+actual_shift
        actual_ss, actual_se, actual_load = _session(config, actual_depot+timedelta(hours=1))
        actual_session = session
        if actual_ss != session_start:
            actual_session = n("DeliverySession", "ACTUAL-SESSION", depot_id=depot,
                               start_at=iso(actual_ss), end_at=iso(actual_se), timezone="Asia/Riyadh",
                               grace_seconds=int(grace.total_seconds()), start_local=config.session_start, end_local=config.session_end)

        total_weight = round(sum(w.nodes[p].properties["weight_kg"] for p in packages), 4)
        total_volume = round(sum(w.nodes[p].properties["volume_m3"] for p in packages), 6)

        def assignment(mode, start, end, seg, active_session=None):
            type_v = "HEAVY" if bulky and total_weight > 900 else "TRUCK" if bulky and mode == "linehaul" else "LARGE" if bulky else "LHV" if mode == "linehaul" else "LMV"
            if mode == "linehaul" and type_v == "LARGE":
                type_v = "TRUCK"
            vehicle = self.vehicle(type_v, oc if mode == "linehaul" else dc, start, end)
            self.assignment_number += 1
            a = n("VehicleAssignment", f"ASSIGN-{mode.upper()}", vehicle_id=vehicle,
                  driver_id=w.nodes[vehicle].properties["driver_id"], valid_from=iso(start), valid_to=iso(end),
                  package_ids=packages, weight_kg=total_weight, volume_m3=total_volume, mode=mode,
                  segment_id=seg, session_id=active_session)
            w.edge(vehicle, "HAS_ASSIGNMENT", a)
            w.edge(a, "USES_VEHICLE", vehicle)
            w.edge(a, "ASSIGNED_DRIVER", w.nodes[vehicle].properties["driver_id"])
            w.edge(a, "ON_SEGMENT", seg)
            if active_session:
                w.edge(a, "IN_SESSION", active_session)
            for pkg in packages:
                w.edge(a, "CARRIES", pkg)
            return a, vehicle

        line_assignment, line_vehicle = (None, None)
        if intercity:
            line_assignment, line_vehicle = assignment("linehaul", line_start+actual_shift,
                                                       line_end+actual_shift+timedelta(minutes=15), line_segment)
        lm_assignment, lm_vehicle = assignment("last_mile", actual_load,
                                               actual_se+grace, lm_segment, actual_session)

        def custody(pkg, seq, when, from_id, to_id, event_type, facility=None, vehicle=None, assigned=None, ack=2, quality="CORROBORATED"):
            raw = n("ScanEvent", f"RAW-CUST-{pkg.rsplit('-', 1)[-1]}-{seq:02d}", when,
                    package_id=pkg, observed_barcode=w.nodes[pkg].properties["manifest_barcode"],
                    readable=True, confidence=.99, calibrated=False,
                    facility_id=facility, device_ref="DEMO-HANDOVER-READER",
                    observation_type="HANDOVER_BARCODE_READ",
                    source_ref=f"synthetic:{quality}:handover-observation")
            w.edge(pkg, "HAS_SCAN", raw)
            key = n("CustodyEvent", f"CUST-{pkg.rsplit('-', 1)[-1]}-{seq:02d}", when,
                    package_id=pkg, from_id=from_id, to_id=to_id, event_type=event_type,
                    source_event_id=raw,
                    required_acknowledgments=2, received_acknowledgments=ack,
                    source_quality=quality, source_ref=f"synthetic:{quality}:handover-observation",
                    facility_id=facility, vehicle_id=vehicle, assignment_id=assigned)
            w.edge(pkg, "HAS_CUSTODY_EVENT", key)
            w.edge(sid, "HAS_CUSTODY_EVENT", key)
            w.edge(key, "FROM_CUSTODIAN", from_id)
            w.edge(key, "TO_CUSTODIAN", to_id)
            w.edge(key, "OBSERVED_BY", raw)
            if vehicle and event_type == "LOADED" and ack==2 and quality=="CORROBORATED":
                w.edge(sid, "LOADED_ON", vehicle, valid_from=iso(when), valid_to=None,
                       interval_status="OPEN_OBSERVATION_GAP", custody_event_id=key,
                       provenance=str(Provenance.DERIVED), package_id=pkg)
            return key

        expected = [("RECEIVED", origin_facility, t0), ("RECEIVED", sorting, t0+timedelta(hours=2)),
                    ("RECEIVED", hub, t0+timedelta(hours=4))]
        if intercity:
            expected += [("LOADED", hub, line_start), ("RECEIVED", d_hub, line_end),
                         ("RECEIVED", d_sorting, line_end+timedelta(hours=2))]
        expected += [("RECEIVED", depot, depot_time), ("LOADED", depot, load_at),
                     ("DELIVERED", recipient, max(load_at,promise_session_start)+timedelta(hours=2))]
        for pkg in packages:
            for seq, (predicate, location, when) in enumerate(expected, 1):
                milestone = n("RouteMilestone", f"RM-{pkg.rsplit('-', 1)[-1]}-{seq:02d}", sequence=seq,
                              predicate=predicate, location_id=location)
                em = n("ExpectedMilestone", f"EM-{pkg.rsplit('-', 1)[-1]}-{seq:02d}", package_id=pkg,
                       sequence=seq, predicate=predicate, location_id=location,
                       earliest_at=iso(when-timedelta(minutes=15)),
                       latest_at=iso(promise_session_end if predicate=="DELIVERED" else when+timedelta(seconds=tolerance)),
                       grace_seconds=0, session_id=next_session if recipe=="accounted_return" and predicate=="DELIVERED" else session)
                w.edge(route, "CONTAINS", milestone, sequence=seq)
                w.edge(journey, "EXPECTS", em)
                w.edge(em, "BASED_ON", milestone)
                w.edge(em, "FOR_PACKAGE", pkg)
                seq_c = 1
            last, seq_c = sender, 0
            for facility, when in ((origin_facility, t0), (sorting, t0+timedelta(hours=2)), (hub, t0+timedelta(hours=4))):
                seq_c += 1
                custody(pkg, seq_c, when, last, facility, "RECEIVED", facility)
                last = facility
            scan = n("ScanEvent", f"SCAN-{pkg.rsplit('-', 1)[-1]}", t0+timedelta(hours=2, minutes=5),
                     package_id=pkg, observed_barcode=w.nodes[pkg].properties["manifest_barcode"], readable=True,
                     confidence=.99, measured_weight_kg=w.nodes[pkg].properties["weight_kg"], calibrated=True,
                     measurement_units="kg", facility_id=sorting, device_ref=f"DEMO-SCALE-{oc}-01")
            if pkg == packages[0] and recipe == "different_barcode":
                w.nodes[scan].properties["observed_barcode"] += "8"
            if pkg == packages[0] and recipe in ("different_weight", "weight_and_obsolete_address"):
                w.nodes[scan].properties["measured_weight_kg"] = round(w.nodes[pkg].properties["weight_kg"]*.65, 2)
            w.edge(pkg, "HAS_SCAN", scan)
            w.edge(sid, "HAS_SCAN", scan)
            if intercity:
                seq_c += 1
                custody(pkg, seq_c, line_start+actual_shift, hub, line_vehicle, "LOADED", hub, line_vehicle, line_assignment)
                last = line_vehicle
                if recipe == "absent_transfer_receipt":
                    continue
                for facility, when in ((d_hub, line_end+actual_shift), (d_sorting, line_end+actual_shift+timedelta(hours=2))):
                    seq_c += 1
                    custody(pkg, seq_c, when, last, facility, "RECEIVED", facility, line_vehicle if last==line_vehicle else None, line_assignment if last==line_vehicle else None)
                    last = facility
            seq_c += 1
            custody(pkg, seq_c, actual_depot, last, depot, "RECEIVED", depot)
            seq_c += 1
            disputed_load=recipe=="conflicting_custody_sources" and pkg==packages[0]
            first_load=custody(pkg, seq_c, actual_load, depot, lm_vehicle, "LOADED", depot, lm_vehicle, lm_assignment,
                              quality="ATTRIBUTED_REPORT" if disputed_load else "CORROBORATED")
            last = lm_vehicle
            if recipe == "conflicting_custody_sources" and pkg == packages[0]:
                alt_vehicle = next((v.id for v in w.of_kind("Vehicle") if v.id != lm_vehicle), line_vehicle)
                if not alt_vehicle:
                    # Reserve a second plausible resource for a conflicting source report.
                    alt_vehicle = self.vehicle("LMV", dc, actual_load, actual_se+grace)
                other_load=custody(pkg, seq_c+1, actual_load, depot, alt_vehicle, "LOADED", depot,
                                   alt_vehicle, None, quality="ATTRIBUTED_REPORT")
                for load,source in ((first_load,"synthetic:carrier-handover-report"),(other_load,"synthetic:depot-handover-report")):
                    w.nodes[load].properties["source_ref"]=source
                    w.nodes[w.nodes[load].properties["source_event_id"]].properties["source_ref"]=source
                continue
            if recipe in ("absent_session_receipt", "partial_packages") and (recipe != "partial_packages" or pkg == packages[-1]):
                continue
            failed = recipe in ("different_gate", "obsolete_address", "unanswered_contact", "traffic_safe_return",
                                "accounted_return", "weight_and_obsolete_address")
            delivered_at = actual_load+timedelta(hours=2)
            attempt_address = version1 if address2 else current
            attempts = 2 if recipe in ("unanswered_contact", "second_attempt") else 1
            final_attempt = None
            for attempt_num in range(1, attempts+1):
                when = delivered_at+timedelta(hours=attempt_num-1)
                fail_this = failed or (recipe=="second_attempt" and attempt_num==1)
                reason = "RECIPIENT_NOT_REACHED" if recipe=="unanswered_contact" else "SESSION_CAPACITY_EXHAUSTED" if recipe=="traffic_safe_return" else "SESSION_WINDOW_CLOSED" if recipe=="accounted_return" else "ACCESS_NOT_COMPLETED" if recipe in ("different_gate", "obsolete_address", "weight_and_obsolete_address") else "CONTACT_AGREED_NEXT_ATTEMPT" if fail_this else None
                attempt = n("DeliveryAttempt", f"ATT-{pkg.rsplit('-', 1)[-1]}-{attempt_num}", when,
                            package_id=pkg, used_address_version_id=attempt_address,
                            observed_gate="Gate 1" if recipe=="different_gate" else "Gate 4",
                            disposition="FAILED" if fail_this else "DELIVERED", failed_reason=reason,
                            session_id=actual_session, assignment_id=lm_assignment)
                final_attempt = attempt
                w.edge(sid, "HAS_ATTEMPT", attempt)
                w.edge(pkg, "HAS_ATTEMPT", attempt)
                w.edge(attempt, "USED_ADDRESS", attempt_address)
                contact = n("ContactAttempt", f"CONTACT-{pkg.rsplit('-', 1)[-1]}-{attempt_num}", when-timedelta(minutes=5),
                            package_id=pkg, attempt_id=attempt,
                            result="NO_RESPONSE" if recipe=="unanswered_contact" else "AGREED_SAME_SESSION_RETRY" if recipe=="second_attempt" and fail_this else "AGREED_NEXT_SESSION" if fail_this else "CONTACTED",
                            channel="synthetic_phone", source_actor_id=recipient)
                w.edge(attempt, "HAS_CONTACT", contact)
            if failed:
                seq_c += 1
                receipt = custody(pkg, seq_c, actual_se+timedelta(minutes=15), lm_vehicle, depot, "RETURNED", depot, lm_vehicle, lm_assignment)
                recon = n("DepotReconciliation", f"RECON-{pkg.rsplit('-', 1)[-1]}", actual_se+timedelta(minutes=16),
                          package_id=pkg, session_id=actual_session, result="RETURNED", attempt_id=final_attempt, receipt_id=receipt)
                w.edge(sid, "HAS_RECONCILIATION", recon)
                w.edge(recon, "SUPPORTED_BY", receipt)
                continue
            delivered_at += timedelta(hours=attempts-1)
            address_proof = attempt_address
            proof_lat, proof_lng = av["lat"], av["lng"]
            if recipe == "report_different_location":
                proof_lat += .04
                proof_lng += .04
            alternate = recipe == "report_authorized_alternate"
            handoff_recipient = recipient
            if alternate or recipe=="report_different_location":
                handoff_recipient = n("Customer", f"HANDOFF-{pkg.rsplit('-', 1)[-1]}", display_name=f"{sid} synthetic alternate recipient")
            handoff = n("HandoffEvidence", f"HANDOFF-EV-{pkg.rsplit('-', 1)[-1]}", delivered_at,
                        package_id=pkg, attempt_id=final_attempt, recipient_id=handoff_recipient,
                        recipient_type="AUTHORIZED_ALTERNATE" if alternate else "UNVERIFIED_PERSON" if recipe=="report_photo_only" else "OTHER_PERSON" if handoff_recipient!=recipient else "EXPECTED_RECIPIENT",
                        authorization_ref=f"{sid}-SYNTHETIC-CONSENT" if alternate else None)
            photo = n("PhotoEvidence", f"PHOTO-{pkg.rsplit('-', 1)[-1]}", delivered_at,
                      package_id=pkg, attempt_id=final_attempt, address_version_id=address_proof,
                      lat=proof_lat, lng=proof_lng, accuracy_m=20., subject="door_metadata",
                      media_ref=f"synthetic://{sid}/photo-metadata", no_image_generated=True)
            authentication = None
            signature = None
            if recipe != "report_photo_only":
                authentication = n("AuthenticationEvidence", f"AUTH-{pkg.rsplit('-', 1)[-1]}", delivered_at,
                                   package_id=pkg, attempt_id=final_attempt, method="SYNTHETIC_PIN" if index%2 else "SYNTHETIC_OTP",
                                   result="FAIL" if recipe=="report_failed_authentication" else "PASS",
                                   authorized_recipient_id=handoff_recipient if alternate else recipient,
                                   expires_at=iso(delivered_at+timedelta(minutes=5)),
                                   verification_policy="synthetic_bound_delivery_v1", secret_value_stored=False)
                signature = n("SignatureEvidence", f"SIGN-{pkg.rsplit('-', 1)[-1]}", delivered_at,
                              package_id=pkg, attempt_id=final_attempt, recipient_id=handoff_recipient,
                              proof_type="SYNTHETIC_ACKNOWLEDGMENT", actual_signature_stored=False)
            proof = n("DeliveryProof", f"PROOF-{pkg.rsplit('-', 1)[-1]}", delivered_at,
                      package_id=pkg, attempt_id=final_attempt, address_version_id=address_proof,
                      lat=proof_lat, lng=proof_lng, accuracy_m=20., authentication_id=authentication,
                      signature_id=signature, photo_id=photo, handoff_id=handoff,
                      verification_policy="synthetic_bound_delivery_v1")
            w.edge(final_attempt, "HAS_PROOF", proof)
            for kind, end in (("HAS_AUTHENTICATION", authentication), ("HAS_SIGNATURE", signature),
                              ("HAS_PHOTO", photo), ("HAS_HANDOFF", handoff)):
                if end:
                    w.edge(proof, kind, end)
            invalid_proof = recipe in ("report_failed_authentication", "report_photo_only")
            seq_c += 1
            receipt = custody(pkg, seq_c, delivered_at, lm_vehicle, handoff_recipient, "DELIVERED", depot,
                              lm_vehicle, lm_assignment, ack=1 if invalid_proof else 2,
                              quality="INCOMPLETE_ACK" if invalid_proof else "CORROBORATED")
            w.nodes[receipt].properties["proof_id"] = proof
            recon = n("DepotReconciliation", f"RECON-{pkg.rsplit('-', 1)[-1]}", delivered_at+timedelta(minutes=1),
                      package_id=pkg, session_id=actual_session, result="DELIVERED", proof_id=proof,
                      receipt_id=receipt, attempt_id=final_attempt)
            w.edge(sid, "HAS_RECONCILIATION", recon)
            w.edge(recon, "SUPPORTED_BY", proof)
            if recipe.startswith("report_"):
                report = n("RecipientReport", f"REPORT-{pkg.rsplit('-', 1)[-1]}", delivered_at+timedelta(minutes=30),
                           package_id=pkg, report_code="NOT_RECEIVED", reporter_id=recipient, pin_id=pin,
                           statement_en="Tracking indicates delivered; the recipient reports the parcel was not received.",
                           statement_ar="يُظهر التتبع التسليم، ويبلغ المستلم أنه لم يستلم الطرد.",
                           verification_status="ATTRIBUTED_REPORT")
                w.edge(sid, "HAS_REPORT", report)
                w.edge(report, "HAS_PIN", pin)
                if recipe=="report_after_prior_outcome":
                    # A later attributed report reopens closure; it does not negate POD
                    # or accuse either party. The old outcome becomes ineligible history.
                    prefix=f"PRIOR-{pkg.rsplit('-',1)[-1]}"
                    prior_run=n("AnalysisRun",prefix+"-RUN",delivered_at-timedelta(minutes=31),
                                model="none:synthetic_rule_fixture",actor_type="SYNTHETIC_RULE_FIXTURE",iteration=0)
                    prior_rec=n("Recommendation",prefix+"-REC",delivered_at-timedelta(minutes=30),
                                action_code="VERIFY_DELIVERY",action_type="delivery_reconciliation",proposal_version=1)
                    prior_review=n("Review",prefix+"-REVIEW",delivered_at-timedelta(minutes=20),
                                   verdict="accept",reviewer_kind="synthetic_policy_fixture")
                    prior_decision=n("OperatorDecision",prefix+"-DECISION",delivered_at-timedelta(minutes=15),
                                     provenance=Provenance.OPERATOR_DECISION,actor_id="DEMO-OPERATOR-01",decision="approve",proposal_version=1)
                    prior_exec=n("ActionExecution",prefix+"-EXEC",delivered_at-timedelta(minutes=10),
                                 action_type="delivery_reconciliation",status="ACKNOWLEDGED_FIXTURE",adapter_kind="offline_fixture",
                                 command_id=f"{sid}-{prefix}-COMMAND",receipt_ref=f"{sid}-{prefix}-SYNTHETIC-RECEIPT")
                    prior_resolution=n("Resolution",prefix+"-RES",delivered_at+timedelta(minutes=2),
                                       provenance=Provenance.VERIFIED_OUTCOME,action_type="delivery_reconciliation",
                                       evidence_ids=[proof,receipt],resolved_at=iso(delivered_at+timedelta(minutes=2)),
                                       verification_policy="synthetic_bound_delivery_v1",policy_version=POLICY_VERSION)
                    prior_out=n("Outcome",prefix+"-OUT",delivered_at+timedelta(minutes=2),
                                provenance=Provenance.VERIFIED_OUTCOME,action_type="delivery_reconciliation",
                                status="succeeded",success=True,verification_status="VERIFIED",evidence_ids=[proof,receipt],
                                verified_at=iso(delivered_at+timedelta(minutes=2)),invalidated=True,
                                invalidated_at=iso(delivered_at+timedelta(minutes=30)),
                                invalidation_reason="Attributed nonreceipt report requires renewed verification",
                                verification_policy="synthetic_bound_delivery_v1",policy_version=POLICY_VERSION)
                    world_links=((prior_run,"PROPOSES",prior_rec),(prior_rec,"REVIEWED_BY",prior_review),
                                 (prior_rec,"HAS_DECISION",prior_decision),(prior_decision,"INITIATES",prior_exec),
                                 (prior_exec,"RESOLVED_BY",prior_resolution),(prior_resolution,"HAS_OUTCOME",prior_out),
                                 (prior_out,"VERIFIED_BY",prior_decision),(prior_resolution,"SUPPORTED_BY",proof),
                                 (prior_resolution,"SUPPORTED_BY",receipt),(prior_out,"SUPPORTED_BY",report))
                    for a,kind,b in world_links:w.edge(a,kind,b)
        for tag, vehicle, when, point in (("LM-LOAD", lm_vehicle, actual_load, w.nodes[depot].properties),
                                           ("LM-END", lm_vehicle, actual_se+timedelta(minutes=15), w.nodes[depot].properties),
                                           ("LINE-ARRIVAL", line_vehicle, line_end+actual_shift, w.nodes[d_hub].properties)):
            if vehicle:
                gps = n("GPSObservation", f"GPS-{tag}", when, vehicle_id=vehicle,
                        lat=point["lat"], lng=point["lng"], accuracy_m=30., position_scope="VEHICLE_ONLY")
                w.edge(vehicle, "HAS_TELEMETRY", gps)
        if recipe == "traffic_safe_return":
            traffic = n("TrafficObservation", "TRAFFIC", actual_load+timedelta(minutes=10),
                        segment_id=lm_segment, start_at=iso(actual_load), end_at=iso(actual_se),
                        delay_seconds=9*3600, confidence=.95, source_ref="synthetic_route_delay_observation")
            w.edge(lm_segment, "HAS_DELAY_EVIDENCE", traffic)
        if recipe == "absent_transfer_receipt" and not intercity:
            # A local transfer recipe omits the depot receipt/load/attempt evidence instead.
            # This is applied as observation removal, including all dangling links.
            removed = {node.id for node in w.owned(sid) if node.kind in (
                "CustodyEvent", "ScanEvent", "DeliveryAttempt", "ContactAttempt", "DeliveryProof", "AuthenticationEvidence",
                "SignatureEvidence", "PhotoEvidence", "HandoffEvidence", "DepotReconciliation")
                and node.properties.get("occurred_at") and instant(node.properties["occurred_at"]) >= depot_time}
            for key in removed:
                del w.nodes[key]
            w.edges = {key: edge for key, edge in w.edges.items() if edge.start not in removed and edge.end not in removed
                       and edge.properties.get("custody_event_id") not in removed}
        if recipe in ("absent_session_receipt", "conflicting_custody_sources", "partial_packages"):
            status, status_time = "OUT_FOR_DELIVERY", actual_load
        elif recipe in ("absent_transfer_receipt", "later_hub_departure"):
            status, status_time = "IN_TRANSIT", line_start+actual_shift if intercity else t0+timedelta(hours=4)
        elif recipe in ("different_gate", "obsolete_address", "unanswered_contact", "traffic_safe_return", "accounted_return", "weight_and_obsolete_address"):
            status, status_time = "RETURNED_TO_DEPOT", actual_se+timedelta(minutes=15)
        else:
            status, status_time = "DELIVERED", actual_load+timedelta(hours=3 if recipe=="second_attempt" else 2)
        status_node = n("StatusEvent", "STATUS", status_time, status=status, assertion_source="synthetic_tracking")
        w.edge(sid, "HAS_STATUS", status_node)
        w.nodes[sid].properties["status"] = status
        w.gold[sid] = {"shipment_id": sid, "holdout_group": sid, "split": split,
                       "recipe_id": recipe, "intended_healthy": recipe in NORMAL_RECIPES,
                       "initial_snapshot_at": iso(cutoff), "reference_kind": "synthetic evidence rule, not human SPL gold"}

    def observed_world(self):
        self.catalog()
        split_jobs = []
        for split, count in self.world.config.split_counts.items():
            healthy = round(count*self.world.config.normal_fraction)
            recipes = [NORMAL_RECIPES[i%len(NORMAL_RECIPES)] for i in range(healthy)]
            recipes += [PERTURBATIONS[i%len(PERTURBATIONS)] for i in range(count-healthy)]
            self.rng.shuffle(recipes)
            split_jobs.extend((split, recipe) for recipe in recipes)
        # IDs do not encode split/recipe and the splits do not share shipment groups.
        self.rng.shuffle(split_jobs)
        for index, (split, recipe) in enumerate(split_jobs, 1):
            self.shipment(index, split, recipe)
        return self.world


def generate(config: Config | None = None, *, with_derivation: bool = True) -> World:
    builder = Builder(config or Config())
    world = builder.observed_world()
    if with_derivation:
        from dataset_v2.derive import derive_world
        derive_world(world)
        reopen_invalidated_cases(world)
        historical_outcomes(world, builder)
    close_custody_intervals(world)
    return world


def close_custody_intervals(world: World):
    """Observed handoff closes vehicle association; a deadline cannot close custody."""
    from dataset_v2.derive import EvidenceIndex,custody_corroborated
    index=EvidenceIndex(world)
    by_package={}
    for node in index.kinds["CustodyEvent"]:
        by_package.setdefault(node.properties["package_id"],[]).append(node)
    for events in by_package.values():events.sort(key=lambda n:(n.properties["occurred_at"],n.id))
    cutoff=instant(world.config.as_of)
    for edge in world.edges.values():
        if edge.kind!="LOADED_ON":continue
        p=edge.properties
        end=next((node for node in by_package[p["package_id"]]
                  if node.properties["occurred_at"]>p["valid_from"] and node.properties["from_id"]==edge.end
                  and custody_corroborated(world,node,cutoff)),None)
        p["valid_to"]=end.properties["occurred_at"] if end else None
        p["interval_status"]="OBSERVED_HANDOFF" if end else "OPEN_OBSERVATION_GAP"
        if end:p["end_evidence_id"]=end.id


def reopen_invalidated_cases(world: World):
    """Reopen from observed invalidation, independent of private recipe identities."""
    grouped={}
    for node in world.nodes.values():
        grouped.setdefault(node.properties.get("holdout_group"),[]).append(node)
    for case in world.of_kind("Case"):
        sid=case.properties["holdout_group"]
        cutoff=instant(world.nodes[sid].properties["as_of"])
        prior=[node for node in grouped[sid] if node.kind=="Outcome" and node.properties.get("invalidated") is True
               and instant(node.properties["invalidated_at"])<=cutoff]
        if not prior:continue
        case.properties.update(state="REOPENED",operationally_resolved=False,state_version=2)
        for edge in list(world.edges.values()):
            if edge.kind=="HAS_OUTCOME" and edge.end in {node.id for node in prior}:
                world.edge(case.id,"RESOLVED_BY",edge.start)
        for node in grouped[sid]:
            if node.kind=="AnalysisRun":world.edge(case.id,"HAS_RUN",node.id)


def historical_outcomes(world: World, builder: Builder):
    """Synthetic fixture verification after the frozen investigation snapshot.

    Active and held-out cases remain unresolved. Normal shipments need no remediation.
    This is an offline history author, never a live approval/execution endpoint.
    """
    by_group = {}
    for node in world.nodes.values():
        by_group.setdefault(node.properties.get("holdout_group"), []).append(node)
    for shipment in world.of_kind("Shipment"):
        sid, p = shipment.id, shipment.properties
        if p["split"] != "history":
            continue
        cases = [node for node in by_group.get(sid, []) if node.kind == "Case"]
        if not cases:
            continue
        cutoff = instant(p["as_of"])
        packages = p["package_ids"]
        # Follow-up observations are outside the initial snapshot but inside the manifest clock.
        last_observation=max((instant(node.properties["occurred_at"]) for node in by_group[sid]
                              if node.properties.get("occurred_at")),default=cutoff)
        start = max(cutoff,last_observation)+timedelta(hours=1)
        current = p["current_address_version_id"]
        recipient = p["recipient_id"]
        depot = next(node.id for node in world.of_kind("DeliveryDepot") if node.properties["city"]==p["destination_city"])
        def n(kind, suffix, when, provenance=Provenance.SYNTHETIC_DEMO_ASSUMPTION, **props):
            key=f"{sid}-{suffix}"
            world.node(kind,key,shipment_id=sid,split="history",provenance=provenance,
                       occurred_at=iso(when),recorded_at=iso(when),**props)
            return key
        recovery = start + timedelta(minutes=15)
        ss, se, loaded = _session(world.config, recovery+timedelta(hours=1))
        delivered = loaded+timedelta(hours=2)
        verified = delivered+timedelta(minutes=2)
        session = n("DeliverySession", "FOLLOWUP-SESSION", start, depot_id=depot,
                    start_at=iso(ss), end_at=iso(se), timezone="Asia/Riyadh",
                    grace_seconds=world.config.reconciliation_grace_minutes*60,
                    start_local=world.config.session_start, end_local=world.config.session_end,
                    operating_assumption="synthetic approved recovery session")
        world.edge(session,"AT_FACILITY",depot)
        weight=sum(world.nodes[pkg].properties["weight_kg"] for pkg in packages)
        volume=sum(world.nodes[pkg].properties["volume_m3"] for pkg in packages)
        type_key="HEAVY" if p["handling"]=="bulky" and weight>900 else "LARGE" if p["handling"]=="bulky" else "LMV"
        vehicle=builder.vehicle(type_key,p["destination_city"],loaded,se+timedelta(hours=1))
        segment=next(node.id for node in by_group[sid] if node.kind=="RouteSegment" and node.properties["mode"]=="last_mile")
        assignment=n("VehicleAssignment","FOLLOWUP-ASSIGN",start,vehicle_id=vehicle,
                     driver_id=world.nodes[vehicle].properties["driver_id"],valid_from=iso(loaded),valid_to=iso(se+timedelta(hours=1)),
                     package_ids=packages,weight_kg=weight,volume_m3=volume,mode="last_mile",segment_id=segment,session_id=session)
        world.edge(vehicle,"HAS_ASSIGNMENT",assignment);world.edge(assignment,"USES_VEHICLE",vehicle)
        world.edge(assignment,"ASSIGNED_DRIVER",world.nodes[vehicle].properties["driver_id"])
        world.edge(assignment,"ON_SEGMENT",segment);world.edge(assignment,"IN_SESSION",session)
        evidence=[]
        initial_evidence=sorted({key for node in by_group[sid] if node.kind=="Exception"
                                 for key in node.properties.get("evidence_ids",[])})
        def receipt(number,pkg,tag,when,frm,to,event,proof=None):
            raw=n("ScanEvent",f"FOLLOWUP-{tag}-RAW-{number}",when,package_id=pkg,
                  observed_barcode=world.nodes[pkg].properties["manifest_barcode"],readable=True,confidence=.99,
                  calibrated=False,facility_id=depot if event!="DELIVERED" else None,
                  device_ref="DEMO-RECOVERY-READER",observation_type="HANDOVER_BARCODE_READ")
            key=n("CustodyEvent",f"FOLLOWUP-{tag}-CUST-{number}",when,package_id=pkg,
                  from_id=frm,to_id=to,event_type=event,facility_id=depot if event!="DELIVERED" else None,
                  source_event_id=raw,required_acknowledgments=2,received_acknowledgments=2,
                  source_quality="CORROBORATED",verification_policy="synthetic_fixture_followup_v1",
                  vehicle_id=vehicle if event in ("LOADED","DELIVERED") else None,
                  assignment_id=assignment if event in ("LOADED","DELIVERED") else None,proof_id=proof)
            world.edge(pkg,"HAS_SCAN",raw);world.edge(pkg,"HAS_CUSTODY_EVENT",key)
            world.edge(sid,"HAS_CUSTODY_EVENT",key);world.edge(key,"OBSERVED_BY",raw)
            world.edge(key,"FROM_CUSTODIAN",frm);world.edge(key,"TO_CUSTODIAN",to)
            return key
        for number,pkg in enumerate(packages,1):
            nodes = [node for node in by_group.get(sid,[]) if node.kind=="CustodyEvent" and node.properties.get("package_id")==pkg]
            confirmed = [node for node in nodes if node.properties["received_acknowledgments"]>=node.properties["required_acknowledgments"]
                         and instant(node.properties["occurred_at"])<=start and node.properties.get("source_quality")=="CORROBORATED"]
            # Invalid prior POD does not move the last corroborated physical holder.
            from dataset_v2.derive import proof_assessment
            confirmed=[node for node in confirmed if node.properties["event_type"]!="DELIVERED" or
                       proof_assessment(world,world.nodes[node.properties["proof_id"]],start)["corroborated"]]
            holder=max(confirmed,key=lambda node:node.properties["occurred_at"]).properties["to_id"] if confirmed else p["sender_id"]
            recovered=receipt(number,pkg,"RECOVER",recovery,holder,depot,"RECEIVED")
            scan=n("ScanEvent",f"FOLLOWUP-SCAN-{number}",recovery+timedelta(minutes=1),package_id=pkg,
                   observed_barcode=world.nodes[pkg].properties["manifest_barcode"],readable=True,confidence=.99,
                   measured_weight_kg=world.nodes[pkg].properties["weight_kg"],calibrated=True,measurement_units="kg",
                   facility_id=depot,device_ref="DEMO-VERIFICATION-SCALE")
            world.edge(pkg,"HAS_SCAN",scan);world.edge(assignment,"CARRIES",pkg)
            load=receipt(number,pkg,"LOAD",loaded,depot,vehicle,"LOADED")
            world.edge(sid,"LOADED_ON",vehicle,valid_from=iso(loaded),valid_to=iso(delivered),
                       custody_event_id=load,package_id=pkg,provenance=str(Provenance.DERIVED))
            attempt=n("DeliveryAttempt",f"FOLLOWUP-ATT-{number}",delivered,package_id=pkg,
                      used_address_version_id=current,observed_gate="Gate 4",disposition="DELIVERED",
                      session_id=session,assignment_id=assignment)
            world.edge(pkg,"HAS_ATTEMPT",attempt);world.edge(sid,"HAS_ATTEMPT",attempt);world.edge(attempt,"USED_ADDRESS",current)
            auth=n("AuthenticationEvidence",f"FOLLOWUP-AUTH-{number}",delivered,package_id=pkg,attempt_id=attempt,
                   method="SYNTHETIC_OTP",result="PASS",authorized_recipient_id=recipient,
                   expires_at=iso(delivered+timedelta(minutes=5)),secret_value_stored=False,
                   verification_policy="synthetic_bound_delivery_v1")
            handoff=n("HandoffEvidence",f"FOLLOWUP-HANDOFF-{number}",delivered,package_id=pkg,attempt_id=attempt,
                      recipient_id=recipient,recipient_type="EXPECTED_RECIPIENT")
            av=world.nodes[current].properties
            proof=n("DeliveryProof",f"FOLLOWUP-PROOF-{number}",delivered,package_id=pkg,attempt_id=attempt,
                    address_version_id=current,lat=av["lat"],lng=av["lng"],accuracy_m=20.,authentication_id=auth,
                    handoff_id=handoff,verification_status="VERIFIED",verification_policy="synthetic_bound_delivery_v1")
            world.edge(attempt,"HAS_PROOF",proof);world.edge(proof,"HAS_AUTHENTICATION",auth);world.edge(proof,"HAS_HANDOFF",handoff)
            delivered_receipt=receipt(number,pkg,"DELIVERY",delivered,vehicle,recipient,"DELIVERED",proof)
            recon=n("DepotReconciliation",f"FOLLOWUP-RECON-{number}",delivered+timedelta(minutes=1),package_id=pkg,
                    session_id=session,result="DELIVERED",attempt_id=attempt,receipt_id=delivered_receipt,proof_id=proof,
                    verification_status="VERIFIED")
            world.edge(sid,"HAS_RECONCILIATION",recon);world.edge(recon,"SUPPORTED_BY",proof)
            evidence.extend([recovered,scan,load,proof,delivered_receipt,recon])
        for number,case in enumerate(cases,1):
            prefix=f"HISTORY-{number}"
            run=n("AnalysisRun",prefix+"-RUN",start,model="none:synthetic_rule_fixture",
                  actor_type="SYNTHETIC_RULE_FIXTURE",iteration=0)
            recommendation=n("Recommendation",prefix+"-REC",start,action_code="VERIFY_AND_RECONCILE",
                             action_type="delivery_reconciliation",status="ACCEPTED_FIXTURE",proposal_version=1,
                             evidence_ids=initial_evidence,source_ref="synthetic_fixture_author")
            review=n("Review",prefix+"-REVIEW",start+timedelta(minutes=1),verdict="accept",
                     reviewer_kind="synthetic_policy_fixture",score=1.,evidence_ids=initial_evidence)
            operator=n("OperatorDecision",prefix+"-DECISION",start+timedelta(minutes=2),
                       provenance=Provenance.OPERATOR_DECISION,actor_id="DEMO-OPERATOR-01",role="fixture_verifier",
                       decision="approve",proposal_version=1,evidence_version=1)
            execution=n("ActionExecution",prefix+"-EXEC",start+timedelta(minutes=3),
                        command_id=f"{sid}-{prefix}-COMMAND",receipt_ref=f"{sid}-{prefix}-SYNTHETIC-RECEIPT",
                        status="ACKNOWLEDGED_FIXTURE",adapter_kind="offline_fixture",action_type="delivery_reconciliation")
            resolution=n("Resolution",prefix+"-RES",verified,
                         provenance=Provenance.VERIFIED_OUTCOME,action_type="delivery_reconciliation",
                         action="Verified synthetic follow-up reconciliation",evidence_ids=evidence,
                         verification_policy="synthetic_fixture_followup_v1",policy_version=POLICY_VERSION,
                         resolved_at=iso(verified),verifier_id="DEMO-OPERATOR-01")
            outcome=n("Outcome",prefix+"-OUT",verified,
                      provenance=Provenance.VERIFIED_OUTCOME,status="succeeded",success=True,
                      action_type="delivery_reconciliation",verification_status="VERIFIED",evidence_ids=evidence,
                      verification_policy="synthetic_fixture_followup_v1",policy_version=POLICY_VERSION,
                      verified_at=iso(verified),verifier_id="DEMO-OPERATOR-01",invalidated=False)
            world.edge(case.id,"HAS_RUN",run);world.edge(run,"PROPOSES",recommendation)
            world.edge(recommendation,"REVIEWED_BY",review);world.edge(recommendation,"HAS_DECISION",operator)
            world.edge(operator,"INITIATES",execution);world.edge(case.id,"RESOLVED_BY",resolution)
            world.edge(execution,"RESOLVED_BY",resolution)
            world.edge(resolution,"HAS_OUTCOME",outcome);world.edge(outcome,"VERIFIED_BY",operator)
            for eid in evidence:world.edge(resolution,"SUPPORTED_BY",eid)
            case.properties.update(state="RESOLVED",operationally_resolved=True,state_version=2,
                                   resolved_at=iso(verified),resolution_id=resolution)
            for step,(state,when) in enumerate((('OPEN',start),('AWAITING_APPROVAL',start+timedelta(minutes=1)),
                                                ('ACTION_INITIATED',start+timedelta(minutes=3)),('RESOLVED',verified))):
                audit=n("AuditEvent",f"{prefix}-AUDIT-{step}",when,
                        provenance=Provenance.DERIVED,event_type="SYNTHETIC_FIXTURE_TRANSITION",to_state=state,
                        actor_id="DEMO-OPERATOR-01",entity_ref=case.id)
                world.edge(case.id,"HAS_AUDIT",audit)
            notification=n("Notification",prefix+"-NOTIFY",verified+timedelta(minutes=1),mode="dry_run",
                           status="RECORDED_ONLY",provider_calls=0,template_ref="synthetic_reconciliation_v1",
                           recipient_ref=f"shipment-{sid}@demo.invalid")
            world.edge(case.id,"HAS_NOTIFICATION",notification)


if __name__ == "__main__":
    from dataset_v2.export import main
    main()
