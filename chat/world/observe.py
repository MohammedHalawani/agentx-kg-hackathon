"""Observation layer: what devices, people and systems recorded, and when Suhail's gateway received it.

Each physical act from world.physical becomes V2 evidence with the property schema of dataset_v2
(generate.py / network.py) for every existing kind. occurred_at is when it happened; recorded_at is when
the provider system sent it (a device's upload, a carrier's EDI batch, a delivery report); the gateway's
own receipt is recorded_at plus the feed lag (dataset_v2.feed.feed_item). A device that is offline buffers
its records and uploads them at reconnect; a device with stuck uploads keeps them until the nightly sync.

The private index `records` maps every evidence id to its act, device, times and the mechanisms that
shaped it. It is truth-side and never written into a node, edge or feed message.
"""
from collections import defaultdict
from datetime import timedelta

from dataset_v2.contracts import Provenance, World, iso
from world.bookings import SERVICE_TOLERANCE, milestones
from world.config import LOCAL, local_dt, next_local
from world.geo import CITIES, CITY
from world.mechanisms import CLAIM_SUBTYPE
from world.network import PROVIDERS, SPL_OPERATOR, VEHICLE_TYPES

POLICY_ID = "DEMO-POLICY-W1"
VERIFICATION_POLICY = "synthetic_bound_delivery_v1"
HEARTBEAT_SECONDS = {"FACILITY_HANDHELD": 1800, "SORTER_READER": 1800, "SCALE": 1800, "DRIVER_APP": 900}
SOURCE = {"FACILITY_HANDHELD": "spl-core:handheld", "SORTER_READER": "spl-core:sorter", "SCALE": "spl-core:scale",
          "DRIVER_APP": "driver-app"}
FACILITY_KINDS = ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse")

# Inbound message templates (synthetic). {t} is the tracking number, {d} a day word.
REPORT_TEXT = {
    "NOT_RECEIVED": (
        ("Tracking {t} says delivered but I have not received anything.", "رقم التتبع {t} يظهر أنه تم التسليم لكنني لم أستلم شيئًا."),
        ("My parcel {t} shows as delivered {d}. Nobody here received it.", "شحنتي {t} تظهر مسلّمة {d} ولم يستلمها أحد هنا."),
        ("I was home all day and no parcel arrived for {t}.", "كنت في المنزل طوال اليوم ولم تصل أي شحنة للرقم {t}."),
        ("Please check {t}: marked delivered, not with me.", "يرجى التحقق من {t}: مسجلة كمسلّمة وليست لدي."),
        ("Where is my order? The app says delivered ({t}).", "أين طلبي؟ التطبيق يقول تم التسليم ({t})."),
    ),
    "WHERE_IS_PARCEL": (
        ("When will {t} arrive? It was expected {d}.", "متى تصل الشحنة {t}؟ كان من المتوقع وصولها {d}."),
        ("Any update on {t}? No movement in tracking.", "هل من تحديث على {t}؟ لا يوجد تغيير في التتبع."),
        ("My parcel {t} is late. Please advise.", "شحنتي {t} متأخرة. أرجو الإفادة."),
        ("Is {t} still on its way?", "هل ما زالت الشحنة {t} في الطريق؟"),
    ),
    "RECEIVED_CONFIRMATION": (
        ("I have received {t}, thank you.", "استلمت الشحنة {t}، شكرًا."),
        ("Got the parcel {t}. A neighbour passed it to me.", "وصلتني الشحنة {t}، سلّمها لي أحد الجيران."),
        ("Parcel {t} found, a family member had taken it.", "وجدت الشحنة {t}، كان أحد أفراد الأسرة قد استلمها."),
        ("Received {t} {d}. You can close this.", "استلمت {t} {d}. يمكنكم إغلاق الطلب."),
    ),
    "ADDRESS_CORRECTION": (
        ("I moved. Please deliver {t} to my new address.", "انتقلت إلى عنوان جديد. أرجو توصيل {t} إليه."),
        ("The address on {t} needs updating. New location attached.", "العنوان في {t} يحتاج إلى تحديث. أرفقت الموقع الجديد."),
        ("Please use the pin I sent for {t}; the old address is outdated.", "أرجو استخدام الموقع المرسل للشحنة {t}؛ العنوان القديم لم يعد صالحًا."),
    ),
    "RESCHEDULE_REQUEST": (
        ("I am travelling. Please deliver {t} after {d}.", "أنا مسافر. أرجو توصيل {t} بعد {d}."),
        ("Can you hold {t} for a couple of days?", "هل يمكن الاحتفاظ بالشحنة {t} ليومين؟"),
        ("Not available this week for {t}, please reschedule.", "لست متاحًا هذا الأسبوع لاستلام {t}، أرجو إعادة الجدولة."),
    ),
}
REPORT_CHANNELS = (("PORTAL", .4), ("EMAIL", .25), ("CALL_CENTER", .2), ("WHATSAPP", .15))


class Observer:
    def __init__(self, config, network, draws, shipments, sim, plan):
        self.config, self.net, self.d, self.shipments, self.sim, self.mech = config, network, draws, shipments, sim, plan
        counts = defaultdict(int)
        for s in shipments.values():
            counts[s.split] += 1
        self.world = World(config.v2_config(counts))
        self.records = {}
        self.node_of_act = {}
        self.counters = defaultdict(int)
        self.recorded = {}          # act id -> recorded instant
        self.assign_node = {}       # (sid, trip or route) -> VehicleAssignment id
        self.session_node = {}      # (sid, date) -> DeliverySession id
        self.manifest_node = {}     # (sid, route, version) -> Manifest id
        self.device_records = defaultdict(list)   # device -> [(occurred, recorded, node id)]
        self.address_v1 = {}
        self.address_v2 = {}
        self.ran_trips = set()
        self.recipient_pin = {}
        self.segments = {}
        self.persons = {}
        self.handoff_by_person = {}

    # ------------------------------------------------------------------ helpers
    def nid(self, sid, prefix):
        self.counters[(sid, prefix)] += 1
        return f"{sid}-{prefix}-{self.counters[(sid, prefix)]:03d}"

    def owned(self, kind, identifier, sid, occurred, recorded, *, provenance=Provenance.SYNTHETIC_DEMO_ASSUMPTION, act=None,
              device=None, mech=(), **props):
        shipment = self.shipments[sid]
        fields = {"recorded_at": iso(recorded), "source_ref": props.pop("source_ref", "spl-core:system"), **props}
        if occurred is not None:
            fields["occurred_at"] = iso(occurred)
        self.world.node(kind, identifier, shipment_id=sid, split=shipment.split, provenance=provenance, **fields)
        self.records[identifier] = {"kind": kind, "sid": sid, "act": act, "device": device, "occurred": occurred,
                                    "recorded": recorded, "mech": sorted(set(m for m in mech if m))}
        if device:
            self.device_records[device].append((occurred, recorded, identifier))
        return identifier

    def shared(self, kind, identifier, recorded, *, occurred=None, provenance=Provenance.SYNTHETIC_DEMO_ASSUMPTION, act=None,
               device=None, mech=(), source_ref="spl-core:system", **props):
        fields = {"recorded_at": iso(recorded), "source_ref": source_ref, **props}
        if occurred is not None:
            fields["occurred_at"] = iso(occurred)
        self.world.node(kind, identifier, provenance=provenance, **fields)
        if occurred is not None or act is not None:
            self.records[identifier] = {"kind": kind, "sid": None, "act": act, "device": device, "occurred": occurred,
                                        "recorded": recorded, "mech": sorted(set(m for m in mech if m))}
        return identifier

    def lag(self, *key, median=40., sigma=.9):
        return timedelta(seconds=max(2, round(self.d.lognormal(median, sigma, "lag", *key))))

    # ------------------------------------------------------------------ uploads
    def plan_uploads(self):
        """When each act's record reached its provider system: device latency, outages, stuck uploads, batches."""
        sim = self.sim
        heads = {}
        for a in sim.acts:
            kind = a["type"]
            if kind == "custody":
                continue
            if kind in ("contact", "auth", "signature", "photo", "handoff", "proof", "person") or (kind == "scan" and a.get("bundle")):
                continue
            heads[a["act"]] = a
        buffered = defaultdict(list)
        for aid, a in heads.items():
            device = a.get("device")
            t = a["t"]
            mech = []
            if a["type"] in ("scan", "attempt") and device:
                kind = self.net.devices[device].kind if device in self.net.devices else "FACILITY_HANDHELD"
                down = self.mech.down(device, t)
                if down:
                    window = next(w for w in self.mech.device_down[device] if w[0] <= t < w[1])
                    buffered[(device, window[1], down)].append(a)
                    continue
                loss = next((w for w in self.mech.device_loss.get(device, ()) if w[0] <= t < w[1]), None)
                if loss and self.d.chance(loss[2], "lost", aid):
                    sync = next_local(loss[1], "02:30")
                    buffered[(device, sync, loss[3])].append(a)
                    continue
                if kind == "DRIVER_APP":
                    delay = self.lag(aid, median=45, sigma=1.0)
                    if self.d.chance(.04, "batch", aid):
                        delay += timedelta(seconds=self.d.integer(480, 2400, "batch-s", aid))
                elif kind == "SORTER_READER":
                    delay = self.lag(aid, median=5, sigma=.5)
                elif kind == "SCALE":
                    delay = self.lag(aid, median=7, sigma=.5)
                else:
                    delay = self.lag(aid, median=25, sigma=.8)
                    if self.d.chance(.02, "batch", aid):
                        delay += timedelta(seconds=self.d.integer(300, 1500, "batch-s", aid))
                self.recorded[aid] = t + delay
            elif a["type"] == "comm":
                # A delivery receipt: seconds for a delivered message; a failure only after the carrier's retry window.
                if a["status"] == "FAILED":
                    window = min(max(self.d.lognormal(7200, .6, "dlr-fail", aid), 2400), 8 * 3600)
                    self.recorded[aid] = t + timedelta(seconds=round(window))
                else:
                    self.recorded[aid] = t + timedelta(seconds=self.d.integer(3, 40, "dlr", aid))
            elif a["type"] == "trip_event":
                plan = self.net.trips[a["trip"]]
                self.recorded[aid] = t + (timedelta(seconds=self.d.integer(60, 360, "edi", aid)) if plan.provider_id == "DEMO-PROV-3PL-01"
                                          else timedelta(seconds=self.d.integer(15, 90, "tms", aid)))
            else:
                self.recorded[aid] = t + timedelta(seconds=self.d.integer(4, 75, "sys", aid))
        for (device, release, mid), rows in sorted(buffered.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            for n, a in enumerate(sorted(rows, key=lambda r: (r["t"], r["act"]))):
                self.recorded[a["act"]] = max(release, a["t"]) + timedelta(seconds=2 * n + 3)
                a.setdefault("upload_mech", []).append(mid)
        # Bundled acts inherit their head's upload time.
        for a in sim.acts:
            aid = a["act"]
            if aid in self.recorded:
                continue
            if a["type"] == "custody":
                head = a["source"]
            elif a["type"] == "scan":
                head = a["bundle"]
            elif a["type"] == "person":
                head = None
            else:
                head = a.get("attempt")
            if head and head in self.recorded:
                self.recorded[aid] = self.recorded[head]
                a.setdefault("upload_mech", []).extend(sim.acts_by_id(head).get("upload_mech", []))
        for a in sim.acts:
            if a["act"] not in self.recorded:
                self.recorded[a["act"]] = a["t"] + timedelta(seconds=30)
        # Status updates follow the record that triggered them.
        for a in sim.acts:
            if a["type"] == "status":
                trigger = a.get("trigger")
                base = self.recorded[trigger] if trigger else a["t"]
                self.recorded[a["act"]] = max(base, a["t"]) + timedelta(seconds=self.d.integer(20, 120, "status", a["act"]))
                if trigger:
                    a["upload_mech"] = list(sim.acts_by_id(trigger).get("upload_mech", []))

    # ------------------------------------------------------------------ build
    def build(self):
        self.catalog()
        for sid in sorted(self.shipments):
            self.booking_context(self.shipments[sid])
        self.plan_uploads()
        for a in self.sim.acts:
            if a["type"] == "person":
                self.persons[a["person"]] = a
            elif a["type"] == "handoff":
                self.handoff_by_person[a["person"]] = a
        for a in self.sim.acts:
            handler = getattr(self, "_" + a["type"], None)
            if handler:
                handler(a)
        self.notifications()
        self.reports()
        self.trip_records()
        self.route_positions()
        self.throughput()
        self.traffic_background()
        self.heartbeats()
        self.edges()
        return self.world

    # ------------------------------------------------------------------ catalog
    def catalog(self):
        w, net, start = self.world, self.net, self.config.start_at
        rec = iso(start)
        for c in CITIES:
            w.node("City", f"DEMO-CITY-{c.code}", name=c.name, name_ar=c.name_ar, lat=c.lat, lng=c.lng, region=c.region,
                   coordinate_accuracy_m=5000, provenance=Provenance.REFERENCE_DATA, source_ref="public-approximate-city-centre",
                   recorded_at=rec)
        for oid, props in sorted(net.organizations.items()):
            w.node("Organization", oid, name=props["name"], organization_type=props["organization_type"], recorded_at=rec,
                   source_ref="synthetic-catalog")
            w.edge(oid, "IN_CITY", f"DEMO-CITY-{props['city']}")
        for pid, props in sorted(PROVIDERS.items()):
            w.node("Provider", pid, **props, recorded_at=rec, source_ref="synthetic-catalog")
        for fid, f in sorted(net.facilities.items()):
            w.node(f.kind, fid, name=f.name, name_ar=f.name_ar, city=CITY[f.city].name, lat=f.lat, lng=f.lng, accuracy_m=150.,
                   operator_org_id=f.operator, capacity_per_hour=f.capacity_per_hour or None,
                   shifts=[f"{a}-{b}" for a, b, _ in f.shifts] or None, operating_assumption="synthetic world-1 facility",
                   recorded_at=rec, source_ref="synthetic-catalog")
            w.edge(fid, "IN_CITY", f"DEMO-CITY-{f.city}")
            w.edge(f.operator, "OWNS" if f.operator != SPL_OPERATOR and f.kind == "OrganizationWarehouse" else "OPERATES", fid)
        for key, (payload, volume, handling, modes, label) in VEHICLE_TYPES.items():
            w.node("VehicleType", f"DEMO-VTYPE-{key}", payload_kg=payload, volume_m3=volume, handling=handling, modes=modes, label=label,
                   recorded_at=rec, source_ref="synthetic-catalog")
        for key, max_weight, handling in (("SMALL", 30., "standard"), ("BULKY", 300., "bulky")):
            w.node("ShipmentType", f"DEMO-STYPE-{key}", class_name=key, maximum_package_kg=max_weight, handling=handling,
                   recorded_at=rec, source_ref="synthetic-catalog")
            w.node("HandlingRequirement", f"DEMO-HANDLING-{key}", handling=handling, recorded_at=rec, source_ref="synthetic-catalog")
        for key, tolerance in SERVICE_TOLERANCE.items():
            w.node("ServiceLevel", f"DEMO-SERVICE-{key}", name=key, milestone_tolerance_seconds=tolerance,
                   promise_kind="schedule-derived latest delivery session", recorded_at=rec, source_ref="synthetic-catalog")
        w.node("Policy", POLICY_ID, version="world-policy-1", barcode_min_confidence=.9, weight_absolute_kg=.5,
               weight_relative_fraction=.1, retry_limit=3, reconciliation_grace_seconds=self.config.reconciliation_grace_minutes * 60,
               verification_policy=VERIFICATION_POLICY, scope="synthetic evidence rules, not SPL operating policy",
               recorded_at=rec, source_ref="synthetic-catalog")
        for vid, v in sorted(net.vehicles.items()):
            payload, volume, handling, modes, _ = VEHICLE_TYPES[v.type_key]
            w.node("Vehicle", vid, type_id=f"DEMO-VTYPE-{v.type_key}", base_facility_id=v.base, payload_kg=payload, volume_m3=volume,
                   handling=handling, modes=modes, ownership=v.ownership, provider_id=v.provider_id, vehicle_class=v.vehicle_class,
                   plate_ref=v.plate_ref, recorded_at=rec, source_ref="synthetic-catalog")
            w.edge(vid, "HAS_TYPE", f"DEMO-VTYPE-{v.type_key}")
            w.edge(vid, "OPERATED_BY", v.provider_id)
        for did, dr in sorted(net.drivers.items()):
            w.node("Driver", did, display_name=f"Synthetic driver {did.removeprefix('DEMO-DRV-')}", employment=dr.employment,
                   provider_id=dr.provider_id, base_facility_id=dr.base, role=dr.role, recorded_at=rec, source_ref="synthetic-catalog")
            w.edge(did, "WORKS_FOR", dr.provider_id)
        for dev_id, dev in sorted(net.devices.items()):
            w.node("Device", dev_id, device_kind=dev.kind, facility_id=dev.facility_id, driver_id=dev.driver_id, provider_id=dev.provider_id,
                   telemetry_stream=dev.telemetry, heartbeat_interval_seconds=HEARTBEAT_SECONDS[dev.kind] if dev.telemetry != "NONE" else None,
                   recorded_at=rec, source_ref="synthetic-catalog")
            w.edge(dev.facility_id or dev.driver_id, "USES_DEVICE", dev_id)
        for lid, lane in sorted(net.lanes.items()):
            w.node("Lane", lid, lane_type=lane.kind, from_facility_id=lane.origin, to_facility_id=lane.destination,
                   stop_facility_ids=list(lane.stops) or None, distance_km=lane.distance_km, provider_id=lane.provider_id,
                   departures_local=list(lane.departures), nominal_transit_seconds=round(net.lane_duration(lane)),
                   distance_basis="haversine x road factor (approximation, not road geometry)", recorded_at=rec,
                   source_ref="synthetic-catalog")
            w.edge(lid, "FROM", lane.origin)
            w.edge(lid, "TO", lane.destination)
        # Trips that ran (empty scheduled departures are cancelled and leave no record).
        for tid, state in sorted(self.sim.trips.items()):
            if state.cancelled or state.departed_at is None:
                continue
            plan = state.plan
            self.ran_trips.add(tid)
            published = max(start, plan.scheduled_departure - timedelta(hours=36))
            if tid.endswith("-R"):
                published = state.departed_at - timedelta(minutes=30)
            w.node("Trip", tid, trip_type=plan.kind, lane_id=plan.lane,
                   from_facility_id=plan.origin, to_facility_id=plan.destination, start_at=iso(plan.scheduled_departure),
                   end_at=iso(plan.scheduled_arrival), cutoff_at=iso(min(plan.cutoff, plan.scheduled_departure - timedelta(minutes=1))),
                   vehicle_id=plan.vehicle, driver_id=plan.driver, provider_id=plan.provider_id, distance_km=plan.distance_km,
                   recorded_at=iso(published), source_ref="tms:schedule")
            for rel, end in (("ON_LANE", plan.lane), ("USES_VEHICLE", plan.vehicle), ("ASSIGNED_DRIVER", plan.driver),
                             ("FROM", plan.origin), ("TO", plan.destination), ("OPERATED_BY", plan.provider_id)):
                w.edge(tid, rel, end)
        for cid, c in sorted(self.sim.containers.items()):
            w.node("Container", cid, container_type="CAGE" if len(c.parcels) > 18 else "BAG", origin_facility_id=c.origin,
                   destination_facility_id=c.depot, recorded_at=iso(c.created_at), source_ref="wms:container")
            w.edge(cid, "FROM", c.origin)
            w.edge(cid, "TO", c.depot)
        for rid, r in sorted(self.sim.routes.items()):
            w.node("RouteRun", rid, depot_id=r.depot, service_date=r.date.isoformat(), vehicle_id=r.vehicle, driver_id=r.driver,
                   provider_id=self.net.drivers[r.driver].provider_id, device_ref=r.device,
                   start_at=iso(local_dt(r.date, "08:00")), end_at=iso(local_dt(r.date, self.config.session_end)),
                   planned_stops=len(r.shipments), recorded_at=iso(r.planned_at), source_ref="dispatch:route-plan")
            for rel, end in (("AT_FACILITY", r.depot), ("USES_VEHICLE", r.vehicle), ("ASSIGNED_DRIVER", r.driver), ("USES_DEVICE", r.device)):
                w.edge(rid, rel, end)

    # ------------------------------------------------------------------ booking-time context
    def booking_context(self, s):
        w, sid, t0 = self.world, s.sid, s.booked_at
        rec = t0
        r = s.recipient
        if s.sender_kind == "Customer":
            self.owned("Customer", s.sender_id, sid, None, rec, display_name=f"Synthetic sender {s.index:06d}",
                       contact_ref=f"sender-{s.index:06d}@demo.invalid", source_ref="order-system")
        if s.recipient_kind == "Customer":
            self.owned("Customer", s.recipient_id, sid, None, rec, display_name=f"Synthetic recipient {s.index:06d}",
                       contact_ref=f"recipient-{s.index:06d}@demo.invalid", contact_preference=r["contact"],
                       delivery_preference=r["preference"], source_ref="order-system")
        packages = [p.pid for p in s.parcels]
        self.owned("Shipment", sid, sid, t0, rec, tracking_id=s.tracking, flow_type=s.flow, origin_city=CITY[s.origin_city].name,
                   destination_city=CITY[s.dest_city].name, status="CREATED", policy_id=POLICY_ID, handling="bulky" if s.bulky else "standard",
                   collection_mode="dropoff" if s.flow == "C2C" else "pickup", sender_id=s.sender_id, recipient_id=s.recipient_id,
                   package_ids=packages, service_level=s.service, source_ref="order-system")
        w.edge(s.sender_id, "SENDS", sid)
        w.edge(s.recipient_id, "RECEIVES", sid)
        type_key = "BULKY" if s.bulky else "SMALL"
        for rel, end in (("HAS_TYPE", f"DEMO-STYPE-{type_key}"), ("USES_SERVICE", f"DEMO-SERVICE-{s.service}"),
                         ("REQUIRES", f"DEMO-HANDLING-{type_key}"), ("GOVERNED_BY", POLICY_ID)):
            w.edge(sid, rel, end)
        for p in s.parcels:
            self.owned("Package", p.pid, sid, None, rec, package_id=p.pid, manifest_barcode=p.barcode, weight_kg=p.declared_kg,
                       length_m=p.dims[0], width_m=p.dims[1], height_m=p.dims[2], volume_m3=p.volume, handling=p.handling,
                       declared_class="synthetic bulky goods" if p.handling == "bulky" else "synthetic standard goods", source_ref="order-system")
            w.edge(sid, "HAS_PACKAGE", p.pid)
        address = self.owned("Address", f"{sid}-ADDRESS", sid, None, rec, city=CITY[s.dest_city].name, district=r["district"],
                             district_ar=r["district_ar"], source_ref="order-system")
        lat, lng = r["registered_point"]
        unit = f", unit {r['unit']}" if r.get("unit") else ""
        text = f"{r['building']} {r['street']}, {r['district']}, {CITY[s.dest_city].name}{unit} (synthetic)"
        v1 = self.owned("AddressVersion", f"{sid}-ADDR-01", sid, t0, rec, address_id=address, version=1, valid_from=iso(t0 - timedelta(days=1)),
                        valid_to=None, lat=lat, lng=lng, accuracy_m=r["geocode_accuracy_m"], city=CITY[s.dest_city].name, address_text=text,
                        verification_status="ATTRIBUTED_REPORT", source_ref="order-system")
        self.address_v1[sid] = v1
        w.edge(v1, "VERSION_OF", address)
        w.edge(sid, "HAS_ADDRESS_VERSION", v1)
        if s.recipient_kind == "Customer":
            pin = self.owned("LocationPin", f"{sid}-PIN-01", sid, t0, rec, address_version_id=v1, supplier_id=s.recipient_id,
                             purpose="recipient_supplied_destination", lat=lat, lng=lng, accuracy_m=r["geocode_accuracy_m"],
                             verification_status="ATTRIBUTED_REPORT", source_ref="recipient-portal")
            w.edge(v1, "HAS_PIN", pin)
            self.recipient_pin[sid] = pin
        if r["gates"]:
            instruction = self.owned("DeliveryInstruction", f"{sid}-INSTRUCTION", sid, None, rec, address_version_id=v1, gate=r["gate"],
                                     version=1, valid_from=iso(t0 - timedelta(days=1)), valid_to=None, supplied_by=s.recipient_id,
                                     verification_status="ATTRIBUTED_REPORT", source_ref="order-system")
            w.edge(v1, "HAS_INSTRUCTION", instruction)
        if s.flow == "B2C" and s.origin_facility.startswith("DEMO-FULFILL"):
            for p in s.parcels:
                inventory = self.owned("InventoryRecord", f"{sid}-INVENTORY-{p.number:02d}", sid, t0 - timedelta(hours=2), rec,
                                       package_id=p.pid, organization_id=s.sender_id, facility_id=s.origin_facility,
                                       available_quantity=1, reserved_quantity=1, source_ref="wms:inventory")
                w.edge(s.sender_id, "OWNS", inventory)
                w.edge(inventory, "STORED_AT", s.origin_facility)
                w.edge(inventory, "ALLOCATES", p.pid)
        # Planned route and milestones, stamped at booking.
        plan = s.plan
        path = [s.origin_facility, plan["sort"], plan["hub"]] + ([plan["d_hub"]] if plan["inter_region"] else []) + [s.depot, address]
        route = self.owned("Route", f"{sid}-ROUTE", sid, None, rec, version=1, source_ref="planning")
        journey = self.owned("JourneyPlan", f"{sid}-JOURNEY", sid, t0, rec, route_id=route, service_id=f"DEMO-SERVICE-{s.service}",
                             type_id=f"DEMO-STYPE-{type_key}", policy_id=POLICY_ID, policy_version="world-policy-1",
                             promise_at=iso(s.promise_at), version=1, effective_at=iso(t0), source_ref="planning")
        self.world.nodes[sid].properties["journey_id"] = journey
        self.world.nodes[sid].properties["current_address_version_id"] = v1
        w.edge(sid, "EXPECTED_ROUTE", route)
        w.edge(sid, "HAS_PLAN", journey)
        segments = []
        for seq, (a, b) in enumerate(zip(path, path[1:]), 1):
            if b == address:
                mode, low, high = "last_mile", 600, 14 * 3600
            elif self.net.facilities[a].kind == "Hub" and b == plan.get("d_hub") and plan["inter_region"]:
                lane = self.net.linehaul_lane(a, b)
                duration = self.net.lane_duration(lane)
                mode, low, high = "linehaul", round(duration * .85), round(duration * 1.6)
            elif self.net.facilities[a].kind == "Hub":
                duration = self.net.lane_duration(self.net.feeder_lane(b))
                mode, low, high = "local_transfer", round(duration * .85), round(duration * 1.6)
            elif self.net.facilities[a].kind == "SortingCenter":
                mode, low, high = "local_transfer", 900, 12 * 3600
            else:
                duration = self.net.lane_duration(self.net.fm_lane(s.origin_city))
                mode, low, high = "local_transfer", round(duration * .5), round(duration * 1.8) + 8 * 3600
            seg = self.owned("RouteSegment", f"{sid}-SEG-{seq:02d}", sid, None, rec, from_id=a, to_id=b, sequence=seq, mode=mode,
                             minimum_seconds=max(60, low), maximum_seconds=max(high, low + 60), source_ref="planning")
            segments.append(seg)
            w.edge(route, "CONTAINS", seg, sequence=seq)
            w.edge(seg, "FROM", a)
            w.edge(seg, "TO", b)
        w.nodes[route].properties["segment_ids"] = segments
        self.segments[sid] = {(w.nodes[x].properties["from_id"], w.nodes[x].properties["to_id"]): x for x in segments}
        for p in s.parcels:
            for seq, predicate, location, nominal, latest, key in milestones(s):
                rm = self.owned("RouteMilestone", f"{sid}-RM-{p.number:02d}-{seq:02d}", sid, None, rec, sequence=seq, predicate=predicate,
                                location_id=location, source_ref="planning")
                em = self.owned("ExpectedMilestone", f"{sid}-EM-{p.number:02d}-{seq:02d}", sid, None, rec, package_id=p.pid, sequence=seq,
                                predicate=predicate, location_id=location, earliest_at=iso(nominal - timedelta(minutes=15)),
                                latest_at=iso(latest), grace_seconds=0, nominal_at=iso(nominal), source_ref="planning")
                w.edge(route, "CONTAINS", rm, sequence=seq)
                w.edge(journey, "EXPECTS", em)
                w.edge(em, "BASED_ON", rm)
                w.edge(em, "FOR_PACKAGE", p.pid)

    # ------------------------------------------------------------------ evidence from acts
    def rec(self, a):
        return self.recorded[a["act"]]

    def mech_of(self, a):
        return sorted(set(a.get("mech", []) + a.get("upload_mech", [])))

    def _status(self, a):
        sid = a["sid"]
        node = self.owned("StatusEvent", self.nid(sid, "STATUS"), sid, a["t"], self.rec(a), act=a["act"], mech=self.mech_of(a),
                          status=a["status"], assertion_source="tracking_system", source_ref="spl-core:tracking")
        self.node_of_act[a["act"]] = node
        self.world.nodes[sid].properties.setdefault("_statuses", []).append(a["status"])

    def _scan(self, a):
        sid = a["sid"]
        device = a["device"]
        dev = self.net.devices.get(device)
        props = {"package_id": a["pid"], "readable": a["readable"], "confidence": a["confidence"], "calibrated": a["obs"] == "SCALE_WEIGH",
                 "facility_id": a.get("facility"), "device_ref": device, "observation_type": a["obs"],
                 "container_id": a.get("container"), "trip_id": a.get("trip") if a.get("trip") in self.ran_trips else None,
                 "route_run_id": a.get("route"), "vehicle_id": a.get("vehicle")}
        if a.get("weight") is not None:
            props.update(measured_weight_kg=a["weight"], measurement_units="kg")
        elif a.get("barcode") is not None:
            props["observed_barcode"] = a["barcode"]
        node = self.owned("ScanEvent", self.nid(sid, "SCAN"), sid, a["t"], self.rec(a), act=a["act"], device=device, mech=self.mech_of(a),
                          source_ref=SOURCE.get(dev.kind if dev else "FACILITY_HANDHELD", "spl-core:handheld"), **props)
        self.node_of_act[a["act"]] = node

    def _custody(self, a):
        sid = a["sid"]
        source = self.node_of_act[a["source"]]
        assignment = None
        if a.get("route"):
            assignment = self.assign_node.get((sid, a["route"]))
        elif a.get("trip"):
            assignment = self.assign_node.get((sid, a["trip"]))
        proof = self.node_of_act.get(a["proof"]) if a.get("proof") else None
        node = self.owned("CustodyEvent", self.nid(sid, "CUST"), sid, a["t"], self.rec(a), act=a["act"], device=a.get("device"),
                          mech=self.mech_of(a), package_id=a["pid"], from_id=a["frm"], to_id=a["to"], event_type=a["event"],
                          source_event_id=source, required_acknowledgments=2, received_acknowledgments=a["acks"],
                          source_quality=a["quality"], facility_id=a.get("facility"), vehicle_id=a.get("vehicle"),
                          assignment_id=assignment, proof_id=proof, trip_id=a.get("trip") if a.get("trip") in self.ran_trips else None,
                          route_run_id=a.get("route"), source_ref=self.world.nodes[source].properties["source_ref"])
        self.node_of_act[a["act"]] = node

    def _trip_assign(self, a):
        sid = a["sid"]
        tid = a["trip"]
        if tid not in self.ran_trips:
            return
        plan = self.net.trips[tid]
        pids = sorted(set(a["pids"]))
        weight = round(sum(self.world.nodes[p].properties["weight_kg"] for p in pids), 6)
        volume = sum(self.world.nodes[p].properties["volume_m3"] for p in pids)
        mode = "linehaul" if plan.kind == "LINEHAUL" else "local_transfer"
        segment = None
        if plan.kind in ("LINEHAUL", "FEEDER") and not tid.endswith("-R"):
            segment = self.segments[sid].get((plan.origin, plan.destination))
        valid_to = plan.scheduled_arrival + timedelta(minutes=30)
        node = self.owned("VehicleAssignment", self.nid(sid, "ASSIGN"), sid, a["t"], self.rec(a), act=a["act"], vehicle_id=plan.vehicle,
                          driver_id=plan.driver, valid_from=iso(plan.scheduled_departure), valid_to=iso(valid_to), package_ids=pids,
                          weight_kg=weight, volume_m3=volume, mode=mode, segment_id=segment, trip_id=tid, source_ref="tms:assignment")
        self.assign_node[(sid, tid)] = node
        self.node_of_act[a["act"]] = node

    def _dispatch(self, a):
        sid, rid, day = a["sid"], a["route"], a["date"]
        route = self.sim.routes[rid]
        grace = self.config.reconciliation_grace_minutes * 60
        key = (sid, day)
        if key not in self.session_node:
            self.session_node[key] = self.owned(
                "DeliverySession", f"{sid}-SESSION-{day.strftime('%m%d')}", sid, a["t"], self.rec(a), act=a["act"], depot_id=route.depot,
                start_at=iso(local_dt(day, self.config.session_start)), end_at=iso(local_dt(day, self.config.session_end)),
                timezone="Asia/Riyadh", grace_seconds=grace, start_local=self.config.session_start, end_local=self.config.session_end,
                route_run_id=rid, operating_assumption="depot delivery session (synthetic local window)", source_ref="dispatch:route-plan")
        pids = sorted(a["pids"])
        weight = round(sum(self.world.nodes[p].properties["weight_kg"] for p in pids), 6)
        volume = sum(self.world.nodes[p].properties["volume_m3"] for p in pids)
        node = self.owned("VehicleAssignment", self.nid(sid, "ASSIGN"), sid, a["t"], self.rec(a), act=a["act"], vehicle_id=a["vehicle"],
                          driver_id=a["driver"], valid_from=iso(local_dt(day, "08:00")),
                          valid_to=iso(local_dt(day, self.config.session_end) + timedelta(seconds=grace)), package_ids=pids, weight_kg=weight,
                          volume_m3=volume, mode="last_mile", session_id=self.session_node[key], route_run_id=rid, source_ref="dispatch:route-plan")
        self.assign_node[(sid, rid)] = node
        self.node_of_act[a["act"]] = node

    def _manifest(self, a):
        sid, rid = a["sid"], a["route"]
        route = self.sim.routes[rid]
        previous = self.manifest_node.get((sid, rid, a["version"] - 1))
        node = self.owned("Manifest", f"{sid}-MANIFEST-{rid.removeprefix('DEMO-RR-')}-V{a['version']}", sid, a["t"], self.rec(a), act=a["act"],
                          mech=self.mech_of(a), assignment_id=self.assign_node[(sid, rid)], session_id=self.session_node[(sid, route.date)],
                          vehicle_id=route.vehicle, driver_id=route.driver, provider_id=self.net.drivers[route.driver].provider_id,
                          version=a["version"], package_ids=sorted(a["pids"]), manifest_status=a["status"], supersedes_id=previous,
                          route_manifest_ref=rid, source_ref="dispatch:manifest")
        self.manifest_node[(sid, rid, a["version"])] = node
        self.node_of_act[a["act"]] = node

    def address_version_of(self, sid, tag):
        return self.address_v2.get(sid) if tag == "v2" and sid in self.address_v2 else self.address_v1[sid]

    def _attempt(self, a):
        sid = a["sid"]
        route = self.sim.routes[a["route"]]
        session = self.session_node.get((sid, route.date))
        node = self.owned("DeliveryAttempt", self.nid(sid, "ATT"), sid, a["t"], self.rec(a), act=a["act"], device=a["device"],
                          mech=self.mech_of(a), package_id=a["pid"], used_address_version_id=self.address_version_of(sid, a["address"]),
                          observed_gate=a.get("gate"), disposition=a["disposition"], failed_reason=a.get("reason"), session_id=session,
                          assignment_id=self.assign_node.get((sid, a["route"])), route_run_id=a["route"], driver_id=a["driver"],
                          vehicle_id=a["vehicle"], source_ref="driver-app")
        self.node_of_act[a["act"]] = node

    def _contact(self, a):
        sid = a["sid"]
        node = self.owned("ContactAttempt", self.nid(sid, "CONTACT"), sid, a["t"], self.recorded[a["attempt"]], act=a["act"],
                          mech=self.mech_of(a), package_id=a["pid"], attempt_id=self.node_of_act[a["attempt"]], result=a["result"],
                          channel="phone_call", source_actor_id=self.shipments[sid].recipient_id, source_ref="driver-app")
        self.node_of_act[a["act"]] = node

    def _person(self, a):
        sid = a["sid"]
        handoff = self.handoff_by_person.get(a["person"])
        recorded = self.recorded[handoff["attempt"]] if handoff else a["t"] + timedelta(seconds=40)
        self.counters[("PERSON",)] += 1
        node = self.owned("Customer", a["person"], sid, a["t"], recorded, act=a["act"],
                          display_name=f"Synthetic person {self.counters[('PERSON',)]:05d}", source_ref="driver-app")
        self.node_of_act[a["act"]] = node

    def _auth(self, a):
        sid = a["sid"]
        node = self.owned("AuthenticationEvidence", self.nid(sid, "AUTH"), sid, a["t"], self.rec(a), act=a["act"], mech=self.mech_of(a),
                          package_id=a["pid"], attempt_id=self.node_of_act[a["attempt"]],
                          method="SYNTHETIC_OTP" if a["method"] == "OTP" else "SYNTHETIC_PIN", result=a["result"],
                          authorized_recipient_id=a["authorized"], expires_at=iso(a["t"] + timedelta(minutes=5)),
                          verification_policy=VERIFICATION_POLICY, secret_value_stored=False, source_ref="driver-app")
        self.node_of_act[a["act"]] = node

    def _signature(self, a):
        sid = a["sid"]
        node = self.owned("SignatureEvidence", self.nid(sid, "SIGN"), sid, a["t"], self.rec(a), act=a["act"], package_id=a["pid"],
                          attempt_id=self.node_of_act[a["attempt"]], recipient_id=a["signer"], proof_type="SYNTHETIC_ACKNOWLEDGMENT",
                          actual_signature_stored=False, source_ref="driver-app")
        self.node_of_act[a["act"]] = node

    def _photo(self, a):
        sid = a["sid"]
        node = self.owned("PhotoEvidence", self.nid(sid, "PHOTO"), sid, a["t"], self.rec(a), act=a["act"], mech=self.mech_of(a),
                          package_id=a["pid"], attempt_id=self.node_of_act[a["attempt"]],
                          address_version_id=self.address_version_of(sid, a["address"]), lat=a["lat"], lng=a["lng"],
                          accuracy_m=a["accuracy"], subject=a["subject"], media_ref=f"synthetic://{sid}/photo-{self.counters[(sid, 'PHOTO')] + 1}",
                          no_image_generated=True, source_ref="driver-app")
        self.node_of_act[a["act"]] = node

    def _handoff(self, a):
        sid = a["sid"]
        authorization = f"DEMO-CONSENT-{sid.removeprefix('DEMO-')}-{self.counters[(sid, 'HANDOFF')] + 1}" if a["authorized"] else None
        node = self.owned("HandoffEvidence", self.nid(sid, "HANDOFF"), sid, a["t"], self.rec(a), act=a["act"], mech=self.mech_of(a),
                          package_id=a["pid"], attempt_id=self.node_of_act[a["attempt"]], recipient_id=a["person"],
                          recipient_type=a["person_type"], authorization_ref=authorization, source_ref="driver-app")
        self.node_of_act[a["act"]] = node

    def _proof(self, a):
        sid = a["sid"]
        node = self.owned("DeliveryProof", self.nid(sid, "PROOF"), sid, a["t"], self.rec(a), act=a["act"], mech=self.mech_of(a),
                          package_id=a["pid"], attempt_id=self.node_of_act[a["attempt"]],
                          address_version_id=self.address_version_of(sid, a["address"]), lat=a["lat"], lng=a["lng"],
                          accuracy_m=a["accuracy"], authentication_id=self.node_of_act.get(a["auth"]) if a.get("auth") else None,
                          signature_id=self.node_of_act.get(a["signature"]) if a.get("signature") else None,
                          photo_id=self.node_of_act[a["photo"]], handoff_id=self.node_of_act[a["handoff"]],
                          verification_policy=VERIFICATION_POLICY, source_ref="driver-app")
        self.node_of_act[a["act"]] = node

    def _reconcile(self, a):
        sid = a["sid"]
        route = self.sim.routes[a["route"]]
        session = self.session_node.get((sid, route.date))
        node = self.owned("DepotReconciliation", self.nid(sid, "RECON"), sid, a["t"], self.rec(a), act=a["act"], mech=self.mech_of(a),
                          package_id=a["pid"], session_id=session, result=a["result"],
                          attempt_id=self.node_of_act.get(a["attempt"]) if a.get("attempt") else None,
                          receipt_id=self.node_of_act.get(a["receipt"]) if a.get("receipt") else None,
                          proof_id=self.node_of_act.get(a["proof"]) if a.get("proof") else None, route_run_id=a["route"],
                          source_ref="depot-system:reconciliation")
        self.node_of_act[a["act"]] = node

    def _comm(self, a):
        sid = a["sid"]
        s = self.shipments[sid]
        node = self.owned("CommunicationEvent", self.nid(sid, "COMM"), sid, a["t"], self.rec(a), act=a["act"], mech=self.mech_of(a),
                          package_id=a.get("pid"), direction="OUTBOUND", channel_type=a["channel_type"], purpose=a["purpose"],
                          delivery_status=a["status"], carrier_route=a["carrier"], recipient_id=s.recipient_id,
                          template_ref=f"tpl-{a['purpose'].lower()}-v2",
                          secret_value_stored=False if a["purpose"].startswith("OTP") else None, source_ref="messaging-gateway")
        self.node_of_act[a["act"]] = node

    def _address_v2(self, a):
        sid = a["sid"]
        s = self.shipments[sid]
        r = s.recipient
        recorded = a["t"] + timedelta(seconds=self.d.integer(5, 60, "portal", a["act"]))
        lat, lng = a["point"]
        v1 = self.address_v1[sid]
        if a.get("minor"):
            text = f"{r['building']} {r['street']}, {r['district']}, {CITY[s.dest_city].name}, entrance {1 + int(self.d.u('entrance', sid) * 4)} (synthetic, pin refined)"
        else:
            text = f"{r['building'] + 7} {r['street']}, {r['district']}, {CITY[s.dest_city].name} (synthetic, updated)"
        v2 = self.owned("AddressVersion", f"{sid}-ADDR-02", sid, a["t"], recorded, act=a["act"], mech=self.mech_of(a),
                        address_id=f"{sid}-ADDRESS", version=2, valid_from=iso(a["t"]), valid_to=None, lat=lat, lng=lng,
                        accuracy_m=r["geocode_accuracy_m"], city=CITY[s.dest_city].name, address_text=text,
                        verification_status="ATTRIBUTED_REPORT", supersedes_id=v1, source_ref="recipient-portal")
        self.address_v2[sid] = v2
        pin = self.owned("LocationPin", f"{sid}-PIN-02", sid, a["t"], recorded, act=a["act"], mech=self.mech_of(a), address_version_id=v2,
                         supplier_id=s.recipient_id, purpose="recipient_supplied_destination", lat=lat, lng=lng,
                         accuracy_m=r["geocode_accuracy_m"], verification_status="ATTRIBUTED_REPORT", source_ref="recipient-portal")
        self.report(s, "ADDRESS_CORRECTION", a["t"], mech=self.mech_of(a), pin=pin, recorded=recorded)
        self.node_of_act[a["act"]] = v2

    def _trip_event(self, a):
        tid = a["trip"]
        if tid not in self.ran_trips:
            return
        self.counters[(tid, "EV")] += 1
        node = self.shared("TripEvent", f"{tid}-EV-{self.counters[(tid, 'EV')]:02d}", self.rec(a), occurred=a["t"], act=a["act"],
                           mech=self.mech_of(a), trip_id=tid, vehicle_id=a["vehicle"], event_type=a["event"],
                           estimated_arrival_at=iso(a["eta"]), reason_code=a.get("reason"),
                           source_ref="carrier-edi" if self.net.trips[tid].provider_id == "DEMO-PROV-3PL-01" else "tms:trip-status")
        self.node_of_act[a["act"]] = node

    def _traffic_event(self, a):
        city = a["city"]
        district = next(d for d in districts_of(city) if d[0] == a["district"])
        self.counters[("TRAFFIC", city)] += 1
        recorded = a["t"] + timedelta(seconds=self.d.integer(30, 150, "traffic-rec", a["act"]))
        node = self.shared("TrafficEvent", f"DEMO-TRAFFIC-{city}-{self.counters[('TRAFFIC', city)]:03d}", recorded, occurred=a["t"],
                           act=a["act"], mech=self.mech_of(a), city_id=f"DEMO-CITY-{city}", district=a["district"], lat=district[2],
                           lng=district[3], radius_km=round(self.d.uniform(1.5, 3.5, "radius", a["act"]), 1), start_at=iso(a["start"]),
                           end_at=iso(a["end"]), event_type=a["event_type"], severity=a["severity"], confidence=.9,
                           source_ref="traffic-feed")
        self.node_of_act[a["act"]] = node

    # ------------------------------------------------------------------ system notifications and inbound messages
    def notifications(self):
        """Messages the platform sends: out for delivery when the route manifest is published (dispatch), failed
        attempt and delivered when it sees the status record."""
        for a in self.sim.acts:
            if a["type"] == "manifest" and a["version"] == 1:
                base, purpose = a["t"], "OUT_FOR_DELIVERY"
            elif a["type"] == "status" and a["status"] in ("DELIVERY_ATTEMPTED", "DELIVERED"):
                base, purpose = self.recorded[a["act"]], {"DELIVERY_ATTEMPTED": "ATTEMPT_FAILED", "DELIVERED": "DELIVERED"}[a["status"]]
            else:
                continue
            s = self.shipments[a["sid"]]
            when = base + timedelta(seconds=self.d.integer(15, 90, "notify", a["act"]))
            channel = "EMAIL" if s.recipient_kind == "Organization" else {"CALL": "SMS", "SMS": "SMS", "WHATSAPP": "WHATSAPP"}[s.recipient["contact"]]
            outage = self.mech.sms_down(s.recipient["carrier_route"], when) if channel == "SMS" else None
            failed = bool(outage) or self.d.chance(.025, "notify-fail", a["act"])
            # A delivery receipt: seconds for a delivered message; a failure only after the carrier's retry window.
            recorded = when + (timedelta(seconds=round(min(max(self.d.lognormal(7200, .6, "dlr-fail", a["act"]), 2400), 8 * 3600))) if failed
                               else timedelta(seconds=self.d.integer(3, 40, "dlr", a["act"])))
            if when >= self.config.end_at:
                continue
            self.owned("CommunicationEvent", self.nid(s.sid, "COMM"), s.sid, when, recorded, package_id=s.parcels[0].pid,
                       direction="OUTBOUND", channel_type=channel, purpose=purpose, delivery_status="FAILED" if failed else "DELIVERED",
                       carrier_route=s.recipient["carrier_route"] if channel == "SMS" else None, recipient_id=s.recipient_id,
                       template_ref=f"tpl-{purpose.lower()}-v2", secret_value_stored=None,
                       source_ref="messaging-gateway")

    def report(self, s, code, when, *, mech=(), pin=None, recorded=None):
        if when >= self.config.end_at:
            return None
        key = (s.sid, code, when.isoformat())
        en, ar = self.d.choice(REPORT_TEXT[code], *key, "text")
        day = self.d.choice(("yesterday", "today", "on Sunday", "two days ago", "this morning"), *key, "day")
        day_ar = {"yesterday": "أمس", "today": "اليوم", "on Sunday": "يوم الأحد", "two days ago": "قبل يومين", "this morning": "هذا الصباح"}[day]
        channel = self.d.weighted(REPORT_CHANNELS, *key, "channel")
        recorded = recorded or when + timedelta(seconds=self.d.integer(5, 60, *key, "rec") if channel in ("PORTAL", "WHATSAPP")
                                                else self.d.integer(120, 1200, *key, "rec"))
        return self.owned("RecipientReport", self.nid(s.sid, "REPORT"), s.sid, when, recorded, mech=mech, package_id=s.parcels[0].pid,
                          report_code=code, reporter_id=s.recipient_id, pin_id=pin if pin else self.recipient_pin.get(s.sid) if code == "NOT_RECEIVED" else None,
                          statement_en=en.format(t=s.tracking, d=day), statement_ar=ar.format(t=s.tracking, d=day_ar),
                          verification_status="ATTRIBUTED_REPORT", channel=channel, source_ref="recipient-portal")

    def reports(self):
        """Inbound recipient messages: some caused by what happened, some ordinary questions."""
        delivered_at, first_failed, rescheduled = {}, {}, {}
        for a in self.sim.acts:
            if a["type"] == "attempt":
                if a["disposition"] == "DELIVERED":
                    delivered_at.setdefault(a["sid"], a["t"])
                else:
                    first_failed.setdefault(a["sid"], a["t"])
                    if a.get("reason") == "CUSTOMER_REQUESTED_RESCHEDULE":
                        rescheduled.setdefault(a["sid"], a["t"])
        for sid in sorted(self.shipments):
            s = self.shipments[sid]
            if s.recipient_kind != "Customer":
                continue
            handed = [row[0] for x in s.parcels for row in self.sim.p[x.pid].timeline if row[1] == "PERSON"]
            handed_at = min(handed) if handed else None
            for mtype in ("NEIGHBOUR_RECEIVES", "MISDELIVERY", "DELIVERY_SCAN_SKIPPED", "CUSTOMER_COMPLAINT", "RECIPIENT_UNAVAILABLE"):
                flag = self.mech.shipment_flag(sid, mtype)
                if not flag:
                    continue
                mid, params = flag
                key = (sid, mtype)
                if mtype == "NEIGHBOUR_RECEIVES" and handed_at and params.get("done"):
                    if self.d.chance(.65, *key, "report"):
                        self.report(s, "NOT_RECEIVED", handed_at + timedelta(hours=self.d.uniform(2, 30, *key, "h")), mech=[mid])
                    elif self.d.chance(.6, *key, "confirm"):
                        self.report(s, "RECEIVED_CONFIRMATION", handed_at + timedelta(hours=self.d.uniform(3, 24, *key, "h")), mech=[mid])
                elif mtype == "MISDELIVERY" and handed_at and params.get("done"):
                    if self.d.chance(.85, *key, "report"):
                        self.report(s, "NOT_RECEIVED", handed_at + timedelta(hours=self.d.uniform(3, 40, *key, "h")), mech=[mid])
                elif mtype == "DELIVERY_SCAN_SKIPPED" and handed_at and params.get("done"):
                    if self.d.chance(.4, *key, "confirm"):
                        self.report(s, "RECEIVED_CONFIRMATION", handed_at + timedelta(hours=self.d.uniform(10, 30, *key, "h")), mech=[mid])
                elif mtype == "RECIPIENT_UNAVAILABLE" and sid in first_failed:
                    if self.d.chance(.35, *key, "resched"):
                        self.report(s, "RESCHEDULE_REQUEST", first_failed[sid] + timedelta(hours=self.d.uniform(1, 8, *key, "h")), mech=[mid])
                elif mtype == "CUSTOMER_COMPLAINT":
                    if params["subtype"] == CLAIM_SUBTYPE and handed_at:
                        first = handed_at + timedelta(hours=self.d.uniform(4, 40, *key, "h"))
                        self.report(s, "NOT_RECEIVED", first, mech=[mid])
                        if self.d.chance(.4, *key, "found"):
                            self.report(s, "RECEIVED_CONFIRMATION", first + timedelta(hours=self.d.uniform(5, 36, *key, "h2")), mech=[mid])
                    elif params["subtype"] != CLAIM_SUBTYPE:
                        when = params["at"]
                        if handed_at is None or when < handed_at:
                            self.report(s, "WHERE_IS_PARCEL", when, mech=[mid])
            # Ordinary messages: a reply to a failed-attempt notice asking for another day, a thank-you after delivery.
            if sid in rescheduled and self.d.chance(.3, sid, "bg-resched"):
                self.report(s, "RESCHEDULE_REQUEST", rescheduled[sid] + timedelta(minutes=self.d.integer(10, 120, sid, "bg-resched-m")))
            if sid in delivered_at and self.d.chance(.02, sid, "bg-thanks"):
                self.report(s, "RECEIVED_CONFIRMATION", delivered_at[sid] + timedelta(hours=self.d.uniform(1, 12, sid, "bg-thanks-h")))
            # A shipment that is late for any reason draws a question from some recipients.
            if (handed_at is None or handed_at > s.promise_at) and self.d.chance(.3, sid, "late-question"):
                self.report(s, "WHERE_IS_PARCEL", s.promise_at + timedelta(hours=self.d.uniform(3, 28, sid, "late-h")))
            for x in s.parcels:
                retained = self.sim.p[x.pid].retained
                if retained and self.d.chance(.5, sid, "retained-question"):
                    self.report(s, "WHERE_IS_PARCEL", s.promise_at + timedelta(hours=self.d.uniform(2, 20, sid, "ret-h")))
                    break

    # ------------------------------------------------------------------ shared observations
    def trip_records(self):
        for tid, state in sorted(self.sim.trips.items()):
            if tid not in self.ran_trips:
                continue
            plan = state.plan
            vehicle = self.net.vehicles[plan.vehicle]
            for t, lat, lng, speed in state.positions:
                self.gps(vehicle, t, lat, lng, speed, trip=tid, mech=[state.delay_mid] if state.delay_mid and speed == 0 else [])

    def gps(self, vehicle, t, lat, lng, speed, *, trip=None, route=None, device=None, mech=()):
        if t >= self.config.end_at:
            return
        identifier = f"DEMO-GPS-{vehicle.id.removeprefix('DEMO-VEH-')}-{t.strftime('%Y%m%dT%H%M%S')}"
        if identifier in self.world.nodes:
            return
        if vehicle.ownership == "PRIVATE" and device:
            down = self.mech.down(device, t)
            recorded = (next(w[1] for w in self.mech.device_down[device] if w[0] <= t < w[1]) + timedelta(seconds=5)) if down else t + self.lag(identifier, median=50, sigma=.9)
            mech = list(mech) + ([down] if down else [])
            source = "driver-app:location"
        else:
            recorded = t + self.lag(identifier, median=20, sigma=.6)
            source = "carrier-edi" if vehicle.ownership == "PROVIDER" else "telematics"
        self.shared("GPSObservation", identifier, recorded, occurred=t, mech=mech, vehicle_id=vehicle.id, lat=lat, lng=lng,
                    accuracy_m=round(self.d.uniform(5, 25, "gps-acc", identifier), 1), position_scope="VEHICLE_ONLY",
                    speed_kmh=speed, trip_id=trip, route_run_id=route, source_ref=source, device=device if vehicle.ownership == "PRIVATE" else None)

    def route_positions(self):
        for rid, route in sorted(self.sim.routes.items()):
            if not route.timeline or route.departed_at is None:
                continue
            vehicle = self.net.vehicles[route.vehicle]
            points = route.timeline
            end = route.returned_at or points[-1][0]
            t = route.departed_at + timedelta(minutes=30)
            while t < end:
                before = [p for p in points if p[0] <= t]
                after = [p for p in points if p[0] > t]
                a = before[-1] if before else points[0]
                b = after[0] if after else a
                span = max(1, (b[0] - a[0]).total_seconds())
                fraction = min(1.0, (t - a[0]).total_seconds() / span)
                lat = a[1] + (b[1] - a[1]) * fraction
                lng = a[2] + (b[2] - a[2]) * fraction
                speed = round(self.d.uniform(0, 45, "lm-speed", rid, t.isoformat()), 1) if b is not a else 0.0
                self.gps(vehicle, t, round(lat, 5), round(lng, 5), speed, route=rid, device=route.device)
                t += timedelta(minutes=30)

    def throughput(self):
        for facility, log in sorted(self.sim.service_log.items()):
            f = self.net.facilities[facility]
            if f.kind not in ("SortingCenter", "DeliveryDepot"):
                continue
            start = self.config.start_at
            end = self.config.end_at
            counts = defaultdict(int)
            for ready, done, pid in log:
                counts[done.replace(minute=0, second=0, microsecond=0)] += 1
            hour = start
            while hour < end:
                h_end = hour + timedelta(hours=1)
                processed = counts.get(hour, 0)
                queue = sum(1 for ready, done, pid in log if ready <= h_end < done)
                local = h_end.astimezone(LOCAL).hour
                in_shift = any(_inside(local - .5, sh) for sh in f.shifts) if f.shifts else True
                if processed or queue or in_shift:
                    rate, mid = self.sim.capacity(facility, hour)
                    recorded = h_end + timedelta(seconds=self.d.integer(90, 300, "tp", facility, hour.isoformat()))
                    self.shared("FacilityThroughput", f"DEMO-TP-{facility.removeprefix('DEMO-')}-{hour.strftime('%Y%m%dT%H')}", recorded,
                                occurred=h_end, mech=[mid] if mid else [], facility_id=facility, start_at=iso(hour), end_at=iso(h_end),
                                processed_count=processed, queue_depth=queue, nominal_capacity_per_hour=f.capacity_per_hour,
                                source_ref="wms:throughput")
                hour = h_end

    def traffic_background(self):
        """Ordinary rush-hour congestion reports in the large cities (no mechanism): normal variation."""
        day = self.config.day1
        while local_dt(day, "00:00") < self.config.end_at:
            for city in ("RUH", "JED", "DMM"):
                for slot in ("07:00", "16:30"):
                    key = ("bg-traffic", city, day.isoformat(), slot)
                    if not self.d.chance(.7, *key):
                        continue
                    district = self.d.choice(districts_of(city), *key, "district")
                    start = local_dt(day, slot) + timedelta(minutes=self.d.integer(0, 50, *key, "m"))
                    end = start + timedelta(minutes=self.d.integer(60, 150, *key, "len"))
                    self.counters[("TRAFFIC", city)] += 1
                    occurred = start + timedelta(minutes=self.d.integer(3, 15, *key, "pub"))
                    self.shared("TrafficEvent", f"DEMO-TRAFFIC-{city}-{self.counters[('TRAFFIC', city)]:03d}",
                                occurred + timedelta(seconds=self.d.integer(30, 150, *key, "rec")), occurred=occurred, city_id=f"DEMO-CITY-{city}",
                                district=district[0], lat=district[2], lng=district[3], radius_km=round(self.d.uniform(1, 3, *key, "r"), 1),
                                start_at=iso(start), end_at=iso(end), event_type="CONGESTION",
                                severity=self.d.weighted((("LOW", .6), ("MODERATE", .35), ("HIGH", .05)), *key, "sev"), confidence=.9,
                                source_ref="traffic-feed")
            day += timedelta(days=1)

    def heartbeats(self):
        """Device telemetry: a beat every interval while the device is powered (docked) or its user is logged in."""
        windows = defaultdict(list)   # device -> [(start, end, logout)]
        start, end = self.config.start_at, self.config.end_at
        for dev_id, dev in self.net.devices.items():
            if dev.telemetry == "NONE" or dev.kind == "DRIVER_APP":
                continue
            if dev.always_on:
                windows[dev_id].append((start, end, False))
            else:
                day = self.config.day1
                while local_dt(day, "00:00") < end:
                    a, b = dev.hours
                    windows[dev_id].append((local_dt(day, a), local_dt(day, b) if b != "24:00" else local_dt(day + timedelta(days=1), "00:00"), False))
                    day += timedelta(days=1)
        for rid, route in self.sim.routes.items():
            if route.login_at is None:
                continue
            if route.logout_at is not None:
                windows[route.device].append((route.login_at, route.logout_at, True))
            else:
                last = max((a["t"] for a in self.sim.acts if a.get("route") == rid and a.get("device") == route.device), default=route.login_at)
                windows[route.device].append((route.login_at, last + timedelta(minutes=5), False))
            if route.late_session:
                windows[route.device].append((route.late_session[0], route.late_session[1], True))
        for tid, state in self.sim.trips.items():
            if tid not in self.ran_trips or state.arrived_at is None:
                continue
            device = self.net.drivers[state.plan.driver].device
            windows[device].append((state.departed_at - timedelta(minutes=30), state.arrived_at + timedelta(minutes=15), True))
        import bisect
        occurred_index = {dev: sorted(r[0] for r in rows if r[0] is not None) for dev, rows in self.device_records.items()}
        recorded_index = {dev: sorted(r[1] for r in rows if r[0] is not None) for dev, rows in self.device_records.items()}
        for dev_id in sorted(windows):
            dev = self.net.devices[dev_id]
            interval = timedelta(seconds=HEARTBEAT_SECONDS[dev.kind])
            phase = timedelta(seconds=int(self.d.u("phase", dev_id) * interval.total_seconds()))
            outages = self.mech.device_down.get(dev_id, [])
            losses = self.mech.device_loss.get(dev_id, [])
            occ = occurred_index.get(dev_id, [])
            rec = recorded_index.get(dev_id, [])
            for a, b, logout in sorted(windows[dev_id], key=lambda w: w[0]):
                t = a + ((phase - (a - start)) % interval) if dev.always_on else a
                while t < min(b, end):
                    outage = next((o for o in outages if o[0] <= t < o[1]), None)
                    if outage:
                        t = outage[1]  # Silent until reconnect; the reconnect beat reports what was buffered.
                        pending = bisect.bisect_left(occ, outage[1]) - bisect.bisect_left(occ, outage[0])
                        self.beat(dev_id, t, pending, outage[0], mech=[outage[2]])
                        t += interval
                        continue
                    pending = bisect.bisect_right(occ, t) - bisect.bisect_right(rec, t)
                    stuck = [l for l in losses if l[0] <= t < next_local(l[1], "02:30")]
                    done = bisect.bisect_right(rec, t)
                    last_upload = rec[done - 1] if done else None
                    self.beat(dev_id, t, pending, last_upload or t, mech=[l[3] for l in stuck if pending])
                    t += interval
                if logout and b < end and not any(o[0] <= b < o[1] for o in outages):
                    self.beat(dev_id, b, 0, b, connectivity="LOGGED_OUT")
            # A device that went offline reports its buffer when it reconnects, even after its user logged out.
            for o_start, o_end, mid in outages:
                pending = bisect.bisect_left(occ, o_end) - bisect.bisect_left(occ, o_start)
                if pending and f"{dev_id}-HB-{o_end.strftime('%Y%m%dT%H%M%S')}" not in self.world.nodes:
                    self.beat(dev_id, o_end, pending, o_start, mech=[mid])

    def beat(self, device, t, pending, last_upload, *, connectivity="ONLINE", mech=()):
        t = t.replace(microsecond=0)
        identifier = f"{device}-HB-{t.strftime('%Y%m%dT%H%M%S')}"
        if identifier in self.world.nodes or t >= self.config.end_at:
            return
        self.shared("DeviceHeartbeat", identifier, t + timedelta(seconds=self.d.integer(1, 6, "hb", identifier)), occurred=t, mech=mech,
                    device_id=device, connectivity=connectivity, pending_uploads=pending, last_upload_at=iso(min(last_upload, t)),
                    source_ref="mdm")

    # ------------------------------------------------------------------ edges
    def edges(self):
        """Evidence links exactly as the ingestion gateway creates them (operations.ingestion.EDGE_RULES)."""
        from operations.ingestion import EDGE_RULES
        w = self.world
        rules = defaultdict(list)
        for kind, prop, rel, outward in EDGE_RULES:
            rules[kind].append((prop, rel, outward))
        for identifier in sorted(self.records):
            node = w.nodes.get(identifier)
            if node is None or node.kind not in rules:
                continue
            p = node.properties
            for prop, rel, outward in rules[node.kind]:
                targets = p.get(prop) if prop != "shipment_id" else p.get("holdout_group")
                for target in (targets if isinstance(targets, list) else [targets]):
                    if isinstance(target, str) and target.startswith("DEMO-") and target in w.nodes:
                        if outward:
                            w.edge(identifier, rel, target)
                        else:
                            w.edge(target, rel, identifier)
        for sid in self.shipments:
            w.nodes[sid].properties.pop("_statuses", None)


def _inside(hour, shift):
    a, b = (int(x.split(":")[0]) + int(x.split(":")[1]) / 60 for x in shift[:2])
    hour %= 24
    return a <= hour < b if a < b else (hour >= a or hour < b)


def districts_of(city):
    from world.geo import districts
    return districts(city)

