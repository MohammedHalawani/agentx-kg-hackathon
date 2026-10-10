"""Private physical simulation: a discrete-event model of the network over simulated days.

The simulation decides where every parcel physically is at every instant (a facility, a container, a
vehicle or a person), who holds it, and which observation acts happen (a device reading a label, a driver
app confirming a load, a depot reconciling a session). Whether and when those acts reach Suhail is the
observation layer's job (world.observe). Mechanisms change what physically happens (capacity, delays,
wrong containers, parcels kept or handed to the wrong person) or which acts happen (skipped scans).

Nothing produced here is imported: the physical event log, the location timelines and the act list are
private inputs to the observation layer, the truth and the Stage 4 operational simulator.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
import heapq
import math

from world.bookings import Shipment
from world.config import WorldConfig, is_friday, local_dt, local_hour
from world.geo import haversine_km, interpolate, offset_point, road_km
from world.mechanisms import MechanismPlan
from world.network import Network, TripPlan, travel_seconds
from world.rand import Draws

MAX_ATTEMPTS = 3
ROUTE_MAX_STOPS = {"LM-VAN": 20, "PRIVATE-CAR": 14}
LOAD_WINDOW_END = "08:50"
STOCK_CHECK = "21:30"
PLANNING = "07:15"


@dataclass
class PState:
    parcel: object
    shipment: Shipment
    timeline: list = field(default_factory=list)     # [t, kind, ref]
    custody: list = field(default_factory=list)      # [t, holder]
    target_depot: str = ""
    routed_depot: str = ""
    container: str | None = None
    status: str = "BOOKED"
    attempts: int = 0
    delivered: bool = False
    held: bool = False
    retained: bool = False
    reschedule_until: object = None
    last_custody_act: str | None = None
    last_custody_to: str | None = None
    shelf_since: object = None
    expected_shelf_at: object = None
    route: str | None = None
    receipts: int = 0

    @property
    def location(self):
        return self.timeline[-1] if self.timeline else None


@dataclass
class ContainerState:
    cid: str
    origin: str           # facility where it was built
    depot: str            # destination depot it was built for
    trip: str             # trip it is assigned to
    created_at: object
    parcels: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    sealed_at: object = None
    opened_at: object = None
    physical_trip: str | None = None
    hub_ready_at: object = None


@dataclass
class TripState:
    plan: TripPlan
    departed_at: object = None
    arrived_at: object = None
    containers: list = field(default_factory=list)
    parcels: list = field(default_factory=list)
    cancelled: bool = False
    delay_mid: str | None = None
    breakdown: tuple | None = None   # (start, end)
    positions: list = field(default_factory=list)
    stop_times: list = field(default_factory=list)


@dataclass
class RouteState:
    rid: str
    depot: str
    date: object
    slot: int
    driver: str
    vehicle: str
    device: str
    planned_at: object
    shipments: list = field(default_factory=list)   # ordered sids
    parcels: list = field(default_factory=list)
    loaded: list = field(default_factory=list)
    stops: list = field(default_factory=list)       # [{"sids": [...], "point": (lat,lng), ...}]
    departed_at: object = None
    returned_at: object = None
    mechs: dict = field(default_factory=dict)
    handed_in: list = field(default_factory=list)   # parcels received from another driver
    handed_out: list = field(default_factory=list)
    retained: bool = False
    timeline: list = field(default_factory=list)    # (t, lat, lng, phase)
    login_at: object = None
    logout_at: object = None
    late_session: tuple | None = None


class Simulation:
    def __init__(self, config: WorldConfig, network: Network, draws: Draws, shipments: dict, plan: MechanismPlan):
        self.config, self.net, self.d, self.shipments, self.mech = config, network, draws, shipments, plan
        self.heap, self.seq = [], 0
        self.acts, self.events = [], []
        self.p = {}
        for shipment in shipments.values():
            for parcel in shipment.parcels:
                self.p[parcel.pid] = PState(parcel, shipment, target_depot=shipment.depot, routed_depot=shipment.depot)
        self.containers, self.trips, self.routes = {}, {}, {}
        self.open_containers = {}               # (origin facility, depot, trip) -> cid
        self.at_origin = defaultdict(list)      # facility -> [pid]
        self.shelf = defaultdict(set)           # depot -> {pid}
        self.server_free = {}                   # facility -> next free instant (FIFO single server)
        self.processed = defaultdict(int)       # (facility, hour start) -> count
        self.service_log = defaultdict(list)    # facility -> [(ready, done, pid)]
        self.queue_peak = defaultdict(int)
        self.vehicle_free = {}                  # vehicle -> actual available instant
        self.touch = defaultdict(set)           # mid -> {pid}
        self.touch_ship = defaultdict(set)      # mid -> {sid}
        self.corrections = {}                   # sid -> instant the correction was applied by dispatch
        self.container_seq = defaultdict(int)
        self.person_seq = defaultdict(int)
        self.end = config.end_at

    # ------------------------------------------------------------------ plumbing
    def at(self, t, kind, *args):
        heapq.heappush(self.heap, (t, self.seq, kind, args))
        self.seq += 1

    def act(self, kind, t, **fields):
        aid = f"A{len(self.acts) + 1:07d}"
        row = {"act": aid, "type": kind, "t": t.replace(microsecond=0), **fields}
        row.setdefault("mech", [])
        self.acts.append(row)
        return aid

    def log(self, t, kind, **fields):
        self.events.append({"t": t.replace(microsecond=0), "type": kind, **fields})

    def mark(self, mid, pid=None, sid=None):
        if not mid:
            return
        if pid:
            self.touch[mid].add(pid)
            self.touch_ship[mid].add(self.p[pid].shipment.sid)
        if sid:
            self.touch_ship[mid].add(sid)

    def move(self, pid, t, kind, ref):
        state = self.p[pid]
        t = t.replace(microsecond=0)
        if state.timeline and state.timeline[-1][0] > t:
            t = state.timeline[-1][0]
        if not state.timeline or (state.timeline[-1][1], state.timeline[-1][2]) != (kind, ref):
            state.timeline.append([t, kind, ref])

    def hold(self, pid, t, holder):
        state = self.p[pid]
        t = t.replace(microsecond=0)
        if not state.custody or state.custody[-1][1] != holder:
            state.custody.append([t, holder])

    def custody_act(self, pid, t, event, frm, to, source, *, facility=None, vehicle=None, trip=None, route=None, acks=2,
                    quality="CORROBORATED", proof=None, mech=()):
        state = self.p[pid]
        aid = self.act("custody", t, pid=pid, sid=state.shipment.sid, event=event, frm=frm, to=to, source=source,
                       facility=facility, vehicle=vehicle, trip=trip, route=route, acks=acks, quality=quality, proof=proof,
                       device=self.acts_by_id(source)["device"] if source else None, mech=list(mech))
        state.last_custody_act, state.last_custody_to = aid, to
        return aid

    def acts_by_id(self, aid):
        return self.acts[int(aid[1:]) - 1]

    def scan(self, pid, t, device, obs, *, facility=None, barcode=None, readable=True, confidence=None, weight=None,
             container=None, trip=None, route=None, vehicle=None, mech=(), bundle=None):
        state = self.p[pid]
        key = ("scan", pid, obs, t.isoformat())
        if confidence is None:
            confidence = round(self.d.uniform(.95, .999, *key, "conf"), 3)
        if barcode is None and obs not in ("CONTAINER_SCAN", "CONTAINER_BAGGING"):
            barcode = state.parcel.label_barcode
        if barcode is not None and barcode == state.parcel.label_barcode != state.parcel.barcode:
            flag = self.mech.parcel_flag(pid, "WRONG_LABEL_APPLIED")
            if flag:
                mech = [*mech, flag[0]]
        return self.act("scan", t, pid=pid, sid=state.shipment.sid, device=device, obs=obs, facility=facility, barcode=barcode,
                        readable=readable, confidence=confidence, weight=weight, container=container, trip=trip,
                        route=route, vehicle=vehicle, mech=list(mech), bundle=bundle)

    def status(self, sid, t, status, trigger):
        return self.act("status", t, sid=sid, status=status, trigger=trigger)

    # ------------------------------------------------------------------ run
    def run(self):
        for sid in sorted(self.shipments, key=lambda s: (self.shipments[s].booked_at, s)):
            shipment = self.shipments[sid]
            self.at(shipment.booked_at, "book", sid)
            self.at(shipment.handover_at, "handover", sid)
        for tid, trip in sorted(self.net.trips.items()):
            self.trips[tid] = TripState(trip)
            if trip.scheduled_departure >= self.end or trip.scheduled_departure < self.config.start_at - timedelta(days=1):
                continue
            if trip.kind == "FIRST_MILE":
                self.at(trip.scheduled_departure, "fm_start", tid)
            else:
                self.at(trip.scheduled_departure, "depart", tid)   # Containers seal at the cutoff on their own events.
        day = self.config.day1
        while local_dt(day, "00:00") < self.end:
            for depot in sorted(f for f in self.net.facilities if self.net.facilities[f].kind == "DeliveryDepot"):
                if not is_friday(day):
                    self.at(local_dt(day, PLANNING), "plan", depot, day)
                self.at(local_dt(day, STOCK_CHECK), "stock_check", depot, day)
            day += timedelta(days=1)
        for city, district, start, end, factor, mid in self.mech.traffic:
            provider_type = {"ROAD_CLOSURE": "CLOSURE", "ACCIDENT": "COLLISION", "HEAVY_CONGESTION": "CONGESTION"}[self.mech.items[mid].subtype]
            self.act("traffic_event", start + timedelta(minutes=self.d.integer(4, 15, "traffic-pub", mid)), city=city, district=district,
                     start=start, end=end, severity=self.d.weighted((("HIGH", .7), ("MODERATE", .3)), "traffic-sev", mid),
                     event_type=provider_type, factor=factor, mech=[mid])
        while self.heap:
            t, _, kind, args = heapq.heappop(self.heap)
            if t >= self.end:
                break
            getattr(self, "_" + kind)(t, *args)
        return self

    # ------------------------------------------------------------------ origin
    def _book(self, t, sid):
        shipment = self.shipments[sid]
        if (shipment.recipient_kind == "Customer" and not self.mech.shipment_flag(sid, "WRONG_ADDRESS")
                and self.d.chance(.025, "minor-correction", sid)):
            self.at(t + timedelta(hours=self.d.uniform(1, 20, "minor-correction-t", sid)), "minor_correction", sid)
        for parcel in shipment.parcels:
            flag = self.mech.parcel_flag(parcel.pid, "WRONG_LABEL_APPLIED")
            if flag:
                parcel.label_barcode = flag[1]["barcode"]
                self.mark(flag[0], parcel.pid)
        self.status(sid, t, "CREATED", None)
        self.log(t, "booked", sid=sid)

    def _handover(self, t, sid):
        shipment = self.shipments[sid]
        facility = shipment.origin_facility
        device = self.net.facilities[facility].devices["FACILITY_HANDHELD"]
        first = None
        for n, parcel in enumerate(shipment.parcels):
            when = t + timedelta(seconds=25 * n)
            self.move(parcel.pid, when, "FACILITY", facility)
            self.hold(parcel.pid, when, facility)
            scan = self.scan(parcel.pid, when, device, "HANDHELD_RECEIPT", facility=facility)
            custody = self.custody_act(parcel.pid, when, "RECEIVED", shipment.sender_id, facility, scan, facility=facility)
            first = first or custody
            self.p[parcel.pid].status = "ACCEPTED"
            self.at_origin[facility].append(parcel.pid)
        self.status(sid, t, "ACCEPTED", first)
        self.log(t, "handover", sid=sid, facility=facility)

    # ------------------------------------------------------------------ first mile
    def _fm_start(self, t, tid):
        state = self.trips[tid]
        plan = state.plan
        jitter = timedelta(seconds=round(self.d.lognormal(240, .6, "fm-jitter", tid)))
        when = t + jitter
        state.departed_at = when
        previous = None
        for i, stop in enumerate(plan.stops):
            if previous is not None:
                a, b = self.net.facilities[previous], self.net.facilities[stop]
                hop = travel_seconds(road_km(a.lat, a.lng, b.lat, b.lng, urban=True), "URBAN") * self.d.uniform(.9, 1.25, "fm-hop", tid, i)
                when = when + timedelta(seconds=round(hop + 600))
            state.stop_times.append(when)
            self.at(when, "fm_stop", tid, i)
            previous = stop

    def _fm_stop(self, t, tid, i):
        state = self.trips[tid]
        plan = state.plan
        facility = plan.stops[i]
        vehicle, driver = plan.vehicle, plan.driver
        device = self.net.drivers[driver].device
        waiting = [pid for pid in self.at_origin[facility] if self.p[pid].timeline[-1][0] <= t - timedelta(minutes=10)]
        for n, pid in enumerate(sorted(waiting, key=lambda p: (self.p[p].timeline[-1][0], p))):
            when = t + timedelta(seconds=20 * (n + 1))
            ready = self.p[pid].timeline[-1][0]
            self.trip_assign(pid, tid, min(when, max(ready + timedelta(minutes=1), when - timedelta(minutes=30))))  # Pickup list.
            self.at_origin[facility].remove(pid)
            self.move(pid, when, "VEHICLE", vehicle)
            self.hold(pid, when, vehicle)
            scan = self.scan(pid, when, device, "LOAD_CONFIRMATION", facility=facility, trip=tid, vehicle=vehicle)
            self.custody_act(pid, when, "LOADED", facility, vehicle, scan, facility=facility, vehicle=vehicle, trip=tid)
            state.parcels.append(pid)
            self.p[pid].status = "COLLECTED"
        if i == len(plan.stops) - 1:
            if not state.parcels:
                state.cancelled = True
                return
            last = self.net.facilities[facility]
            sort = self.net.facilities[plan.destination]
            same_city = last.city == sort.city
            leg = travel_seconds(road_km(last.lat, last.lng, sort.lat, sort.lng, urban=same_city), "URBAN" if same_city else "FM_INTERCITY")
            leg *= self.d.uniform(.95, 1.15, "fm-leg", tid)
            self.at(t + timedelta(seconds=round(leg + 600)), "trip_arrive", tid)

    def trip_assign(self, pid, tid, when):
        """The dispatch system books this shipment's parcels on a trip (one record per shipment and trip)."""
        state = self.p[pid]
        key = (state.shipment.sid, tid)
        if not hasattr(self, "_assigned"):
            self._assigned = {}
        if key in self._assigned:
            self.acts_by_id(self._assigned[key])["pids"].append(pid)
            return
        self._assigned[key] = self.act("trip_assign", when, sid=state.shipment.sid, pids=[pid], trip=tid)

    # ------------------------------------------------------------------ trips
    def _depart(self, t, tid):
        state = self.trips[tid]
        plan = state.plan
        delay = self.mech.trip_delay.get(tid)
        jitter = self.d.lognormal(360, .7, "dep-jitter", tid)
        if self.d.chance(.10, "dep-late", tid):
            jitter += self.d.uniform(900, 2700, "dep-late-s", tid)  # ordinary late departures (waiting for a dock or a driver)
        actual = plan.scheduled_departure + timedelta(seconds=round(jitter))
        free = self.vehicle_free.get(plan.vehicle)
        if free and free + timedelta(minutes=40) > actual:
            actual = free + timedelta(minutes=40)   # the truck is late from its previous run
        if delay and delay[0] == "DEPARTURE_DELAY":
            actual += timedelta(seconds=delay[1])
            state.delay_mid = delay[3]
        self.at(actual, "depart_actual", tid)

    def _depart_actual(self, t, tid):
        state = self.trips[tid]
        plan = state.plan
        hub = plan.origin
        device = self.net.facilities[hub].devices["FACILITY_HANDHELD"]
        assigned = sorted((c for c in self.containers.values() if c.trip == tid and c.opened_at is None
                           and c.timeline and c.timeline[-1][1] == "FACILITY" and c.timeline[-1][2] == hub), key=lambda c: c.cid)
        late = sorted((c for c in self.containers.values() if c.trip == tid and c not in assigned and c.opened_at is None
                       and c.physical_trip is None), key=lambda c: c.cid)
        misload = self.mech.misload.get(tid)
        physical = list(assigned)
        if misload and assigned:
            victim = max(assigned, key=lambda c: (len(c.parcels), c.cid))
            victim.physical_trip = misload[0]
            victim.misload_mid = misload[1]
            physical.remove(victim)
            for pid in victim.parcels:
                self.mark(misload[1], pid)
            # The dock scan records the intended trip; the container itself waits for the other truck.
            for n, pid in enumerate(victim.parcels):
                when = t + timedelta(seconds=15 * n)
                scan = self.scan(pid, when, device, "CONTAINER_SCAN", facility=hub, container=victim.cid, trip=tid, vehicle=plan.vehicle)
                self.custody_act(pid, when, "LOADED", hub, plan.vehicle, scan, facility=hub, vehicle=plan.vehicle, trip=tid, mech=[misload[1]])
        mis_in = sorted((c for c in self.containers.values() if c.physical_trip == tid and c.opened_at is None
                         and c.timeline and c.timeline[-1][2] == hub), key=lambda c: c.cid)
        for c in late:
            self.reassign_container(c, t, reason="missed")
        if not physical and not mis_in:
            if not assigned:
                state.cancelled = True
                return
        state.departed_at = t
        n = 0
        for c in physical + mis_in:
            for pid in c.parcels:
                when = t - timedelta(minutes=10) + timedelta(seconds=15 * n)
                n += 1
                self.hold(pid, when, plan.vehicle)
                if c in physical:
                    scan = self.scan(pid, when, device, "CONTAINER_SCAN", facility=hub, container=c.cid, trip=tid, vehicle=plan.vehicle)
                    self.custody_act(pid, when, "LOADED", hub, plan.vehicle, scan, facility=hub, vehicle=plan.vehicle, trip=tid)
                    self.p[pid].status = "IN_TRANSIT"
            c.timeline.append([t - timedelta(minutes=10), "VEHICLE", plan.vehicle])
            state.containers.append(c.cid)
            state.parcels.extend(c.parcels)
        duration = self.net.lane_duration(self.net.lanes[plan.lane]) * self.d.uniform(.96, 1.08, "dur", tid)
        delay = self.mech.trip_delay.get(tid)
        breakdown = None
        if delay and delay[0] == "BREAKDOWN":
            start = t + timedelta(seconds=round(duration * delay[2]))
            breakdown = (start, start + timedelta(seconds=delay[1]))
            duration += delay[1]
            state.delay_mid = delay[3]
        state.breakdown = breakdown
        arrival = t + timedelta(seconds=round(duration))
        state.arrived_at = arrival
        self.vehicle_free[plan.vehicle] = arrival + (arrival - t if plan.kind == "FEEDER" else timedelta(0))
        if state.delay_mid:
            for pid in state.parcels:
                self.mark(state.delay_mid, pid)
        self.trip_events(state, t, arrival)
        self.at(arrival, "trip_arrive", tid)

    def trip_events(self, state, departed, arrival):
        plan = state.plan
        slip = (arrival - plan.scheduled_arrival).total_seconds()
        mid = [state.delay_mid] if state.delay_mid else []
        self.act("trip_event", departed, trip=plan.id, event="DEPARTED", eta=plan.scheduled_arrival + timedelta(seconds=max(0, (departed - plan.scheduled_departure).total_seconds())),
                 vehicle=plan.vehicle, mech=mid)
        if state.breakdown:
            start, end = state.breakdown
            when = start + timedelta(minutes=self.d.integer(15, 40, "bd-report", plan.id))
            reason = self.d.weighted((("VEHICLE_ISSUE", .6), ("OTHER", .4)), "bd-reason", plan.id)
            self.act("trip_event", when, trip=plan.id, event="ETA_REVISED", eta=arrival, vehicle=plan.vehicle, reason=reason, mech=mid)
        elif slip > 1800:
            reason = (self.d.weighted((("LOADING_DELAY", .45), ("OTHER", .35), ("TRAFFIC", .2)), "slip-reason", plan.id) if state.delay_mid
                      else self.d.weighted((("TRAFFIC", .4), ("LOADING_DELAY", .35), ("OTHER", .2), ("VEHICLE_ISSUE", .05)), "slip-reason", plan.id))
            self.act("trip_event", departed + timedelta(minutes=self.d.integer(5, 25, "slip-report", plan.id)), trip=plan.id,
                     event="ETA_REVISED", eta=arrival, vehicle=plan.vehicle, reason=reason, mech=mid)
        self.act("trip_event", arrival, trip=plan.id, event="ARRIVED", eta=arrival, vehicle=plan.vehicle, mech=mid)
        # Vehicle positions every 30 minutes (vehicle position only, never a parcel position).
        origin, destination = self.net.facilities[plan.origin], self.net.facilities[plan.destination]
        moving = (arrival - departed).total_seconds() - ((state.breakdown[1] - state.breakdown[0]).total_seconds() if state.breakdown else 0)
        t = departed + timedelta(minutes=30)
        while t < arrival:
            if state.breakdown and state.breakdown[0] <= t < state.breakdown[1]:
                elapsed = (state.breakdown[0] - departed).total_seconds()
                speed = 0.0
            else:
                elapsed = (t - departed).total_seconds() - ((min(t, state.breakdown[1]) - state.breakdown[0]).total_seconds()
                                                            if state.breakdown and t >= state.breakdown[0] else 0)
                speed = round(self.d.uniform(55, 95, "spd", plan.id, t.isoformat()), 1)
            lat, lng = interpolate((origin.lat, origin.lng), (destination.lat, destination.lng), min(1.0, max(0.0, elapsed / max(moving, 1))))
            lat, lng = offset_point(lat, lng, self.d.normal(0, .05, "gps-n", plan.id, t.isoformat()), self.d.normal(0, .05, "gps-e", plan.id, t.isoformat()))
            state.positions.append((t, round(lat, 5), round(lng, 5), speed))
            t += timedelta(minutes=30)

    def _trip_arrive(self, t, tid):
        state = self.trips[tid]
        plan = state.plan
        if plan.kind == "FIRST_MILE":
            state.arrived_at = t
            self.trip_events(state, state.departed_at, t)
            sort = plan.destination
            for n, pid in enumerate(sorted(state.parcels)):
                when = t + timedelta(minutes=10, seconds=20 * n)
                self.move(pid, when, "FACILITY", sort)
                self.hold(pid, when, sort)
                slot = self.serve(sort, when, pid)
                self.at(slot, "induct", pid, sort, tid)
            return
        destination = plan.destination
        kind = self.net.facilities[destination].kind
        unload = t + timedelta(minutes=self.d.integer(12, 30, "unload", tid))
        loaded = [c for c in state.containers]
        if kind == "Hub":
            device = self.net.facilities[destination].devices["FACILITY_HANDHELD"]
            n = 0
            for cid in loaded:
                c = self.containers[cid]
                c.timeline.append([unload, "FACILITY", destination])
                for pid in c.parcels:
                    when = unload + timedelta(seconds=15 * n)
                    n += 1
                    self.hold(pid, when, destination)
                    unexpected = [getattr(c, "misload_mid", None)] if self.net.region_hub(self.net.facilities[c.depot].city) != destination else []
                    scan = self.scan(pid, when, device, "CONTAINER_SCAN", facility=destination, container=cid, trip=tid,
                                     mech=[m for m in unexpected if m])
                    # The receiving hub records the truck it unloaded.
                    self.custody_act(pid, when, "RECEIVED", plan.vehicle, destination, scan, facility=destination, vehicle=plan.vehicle, trip=tid)
                self.crossdock(c, unload + timedelta(seconds=15 * n))
        else:  # a depot: bags are opened and every parcel is scanned in, in arrival order
            for cid in loaded:
                c = self.containers[cid]
                c.timeline.append([unload, "FACILITY", destination])
                c.opened_at = unload + timedelta(minutes=self.d.integer(3, 12, "open", cid))
                for pid in sorted(c.parcels):
                    slot = self.serve(destination, c.opened_at, pid)
                    self.p[pid].expected_shelf_at = slot
                    self.at(slot, "receive", pid, destination, tid, cid)

    def crossdock(self, c, ready):
        hub = c.timeline[-1][2]
        depot_region_hub = self.net.region_hub(self.net.facilities[c.depot].city)
        if depot_region_hub == hub:
            lane = self.net.feeder_lane(c.depot)
            trip = self.net.next_trip(lane.id, ready)
        else:
            lane = self.net.linehaul_lane(hub, depot_region_hub)
            trip = self.net.next_trip(lane.id, ready + timedelta(minutes=30))
        if trip is None:
            c.trip = None
            return
        c.trip = trip.id
        c.physical_trip = None
        for pid in c.parcels:
            self.trip_assign(pid, trip.id, ready)

    def reassign_container(self, c, t, reason):
        lane = self.net.trips[c.trip].lane
        trip = self.net.next_trip(lane, t + timedelta(minutes=5))
        if trip is None:
            c.trip = None
            return
        c.trip = trip.id
        for pid in c.parcels:
            self.trip_assign(pid, trip.id, t)

    # ------------------------------------------------------------------ facilities
    def capacity(self, facility, t):
        f = self.net.facilities[facility]
        base = f.capacity_per_hour or 60
        hour = local_hour(t)
        factor = 1.0
        for start, end, value in f.shifts:
            a, b = _hours(start), _hours(end)
            inside = a <= hour < b if a < b else (hour >= a or hour < b)
            if inside:
                factor = value
                break
        backlog, mid = self.mech.backlog_at(facility, t)
        return base * factor * backlog, mid

    def serve(self, facility, ready, pid):
        """FIFO single server with a time-varying rate: processing never exceeds hourly capacity."""
        start = max(ready, self.server_free.get(facility, ready))
        rate, mid = self.capacity(facility, start)
        service = 3600.0 / max(rate, .5)
        done = start + timedelta(seconds=round(service * self.d.uniform(.85, 1.15, "svc", facility, pid)))
        self.server_free[facility] = done
        # Delay beyond an ordinary service at nominal capacity: a backlog touches the parcel when it costs a
        # quarter of an hour or more, during the backlog or in the queue it leaves behind.
        nominal = 3600.0 / max(rate / self.mech.backlog_at(facility, start)[0], .5)
        extra = (done - ready).total_seconds() - nominal * 1.15
        if extra > 900:
            if mid:
                self.mark(mid, pid)
            else:
                for row in self.mech.backlog.get(facility, ()):
                    if row[0] <= ready <= row[1] + timedelta(hours=6):
                        self.mark(row[3], pid)
        hour = done.replace(minute=0, second=0, microsecond=0)
        self.processed[(facility, hour)] += 1
        self.service_log[facility].append((ready, done, pid))
        return done

    def _induct(self, t, pid, sort, tid):
        state = self.p[pid]
        parcel = state.parcel
        facility = self.net.facilities[sort]
        reader = facility.devices["SORTER_READER"]
        handheld = facility.devices["FACILITY_HANDHELD"]
        key = ("induct", pid, t.isoformat())
        misread = self.mech.parcel_flag(pid, "LABEL_MISREAD")
        source = None
        if misread and misread[1].get("stage") == "sort" and not misread[1].get("done"):
            misread[1]["done"] = True
            wrong = _mutate(parcel.label_barcode, self.d, pid)
            self.scan(pid, t, reader, "SORTER_READ", facility=sort, barcode=wrong, confidence=round(self.d.uniform(.91, .97, *key, "c"), 3),
                      mech=[misread[0]])
            self.mark(misread[0], pid)
            manual = t + timedelta(minutes=self.d.integer(2, 9, *key, "manual"))
            source = self.scan(pid, manual, handheld, "HANDHELD_EXCEPTION_SCAN", facility=sort)
            when = manual
        elif self.d.chance(.02, *key, "noread"):
            self.scan(pid, t, reader, "SORTER_READ", facility=sort, barcode=None, readable=False,
                      confidence=round(self.d.uniform(.2, .6, *key, "c"), 3))
            manual = t + timedelta(minutes=self.d.integer(2, 9, *key, "manual"))
            source = self.scan(pid, manual, handheld, "HANDHELD_EXCEPTION_SCAN", facility=sort)
            when = manual
        else:
            source = self.scan(pid, t, reader, "SORTER_READ", facility=sort)
            when = t
            if parcel.label_barcode != parcel.barcode:
                # A wrong label reads cleanly but matches no pre-advice: the exception desk scans it by hand.
                manual = t + timedelta(minutes=self.d.integer(2, 9, *key, "manual"))
                source = self.scan(pid, manual, handheld, "HANDHELD_EXCEPTION_SCAN", facility=sort)
                when = manual
        line = 1 + int(self.d.u("line", pid) * 2)
        scale = f"DEMO-DEV-SCL-{sort.removeprefix('DEMO-')}-{line}"
        drift, drift_mid = self.mech.drift_at(scale, t)
        measured = parcel.true_kg * (1 + self.d.normal(0, .012, *key, "w") + drift)
        state.sort_weight = round(max(.01, measured), 2)
        state.sort_drift_mid = drift_mid
        self.scan(pid, t + timedelta(seconds=8), scale, "SCALE_WEIGH", facility=sort, weight=state.sort_weight,
                  mech=[drift_mid] if drift_mid else [])
        if drift_mid:
            self.mark(drift_mid, pid)
        flag = self.mech.parcel_flag(pid, "DECLARED_WEIGHT_WRONG")
        if flag:
            self.mark(flag[0], pid)
            self.acts[-1]["mech"].append(flag[0])
        if parcel.label_barcode != parcel.barcode:
            self.mark(self.mech.parcel_flag(pid, "WRONG_LABEL_APPLIED")[0], pid)
        previous = state.last_custody_to
        self.custody_act(pid, when, "RECEIVED", previous if previous and previous.startswith("DEMO-VEH") else self.net.trips[tid].vehicle,
                         sort, source, facility=sort, vehicle=self.net.trips[tid].vehicle, trip=tid)
        state.status = "IN_TRANSIT"
        if state.receipts == 0:
            self.status(state.shipment.sid, when, "IN_TRANSIT", source)
        state.receipts += 1
        missort = self.mech.parcel_flag(pid, "MISSORT")
        if missort and not missort[1].get("done"):
            missort[1]["done"] = True
            state.routed_depot = missort[1]["depot"]
            state.missort_mid = missort[0]
            self.mark(missort[0], pid)
        self.bag(pid, sort, when + timedelta(minutes=self.d.integer(1, 4, *key, "bag")))

    def bag(self, pid, facility, when):
        state = self.p[pid]
        depot = state.routed_depot
        region_hub = self.net.region_hub(self.net.facilities[facility].city)
        depot_hub = self.net.region_hub(self.net.facilities[depot].city)
        if region_hub == depot_hub:
            lane = self.net.feeder_lane(depot)
            trip = self.net.next_trip(lane.id, when + timedelta(minutes=10))
        else:
            lane = self.net.linehaul_lane(region_hub, depot_hub)
            trip = self.net.next_trip(lane.id, when + timedelta(minutes=10))
        if trip is None:
            return  # Beyond the simulated schedule: the parcel waits at the sort.
        key = (facility, depot, trip.id)
        cid = self.open_containers.get(key)
        if cid is None or self.containers[cid].sealed_at is not None:
            city = self.net.facilities[facility].city
            self.container_seq[city] += 1
            cid = f"DEMO-CTR-{city}-{self.container_seq[city]:05d}"
            self.containers[cid] = ContainerState(cid, facility, depot, trip.id, when, timeline=[[when, "FACILITY", facility]])
            self.open_containers[key] = cid
            self.at(max(trip.cutoff, when + timedelta(minutes=1)), "seal", cid)
        c = self.containers[cid]
        if when < c.created_at:
            # Bag events are scheduled a few minutes after induction, so a later-inducted parcel can be bagged first.
            c.created_at = when
            c.timeline[0][0] = when
        c.parcels.append(pid)
        device = self.net.facilities[facility].devices["FACILITY_HANDHELD"]
        self.scan(pid, when, device, "CONTAINER_BAGGING", facility=facility, container=cid)
        self.move(pid, when, "CONTAINER", cid)
        state.container = cid
        self.trip_assign(pid, trip.id, when)

    def _seal(self, t, cid):
        c = self.containers[cid]
        if c.sealed_at is not None:
            return
        c.sealed_at = t
        facility = c.origin
        if self.net.facilities[facility].kind == "Hub":
            c.hub_ready_at = t
            return
        hub = self.net.region_hub(self.net.facilities[facility].city)
        self.at(t + timedelta(minutes=self.d.integer(15, 30, "yard", cid)), "hub_in", cid, hub)

    def _hub_in(self, t, cid, hub):
        c = self.containers[cid]
        c.timeline.append([t, "FACILITY", hub])
        c.hub_ready_at = t
        device = self.net.facilities[hub].devices["FACILITY_HANDHELD"]
        for n, pid in enumerate(c.parcels):
            when = t + timedelta(seconds=12 * n)
            self.hold(pid, when, hub)
            skip = self.mech.parcel_flag(pid, "SCAN_SKIPPED_AT_RECEIPT")
            if skip and skip[1].get("stage") == "hub" and not skip[1].get("done"):
                skip[1]["done"] = True
                self.mark(skip[0], pid)
                self.log(when, "received_unscanned", pid=pid, hub=hub)
                continue
            scan = self.scan(pid, when, device, "CONTAINER_SCAN", facility=hub, container=cid)
            self.custody_act(pid, when, "RECEIVED", c.origin, hub, scan, facility=hub)

    # ------------------------------------------------------------------ depot
    def _receive(self, t, pid, depot, tid, cid):
        state = self.p[pid]
        self.move(pid, t, "FACILITY", depot)
        self.hold(pid, t, depot)
        state.container = None
        state.expected_shelf_at = None
        device = self.net.facilities[depot].devices["FACILITY_HANDHELD"]
        vehicle = self.net.trips[tid].vehicle if tid in self.net.trips else self.trips[tid].plan.vehicle
        skip = self.mech.parcel_flag(pid, "SCAN_SKIPPED_AT_RECEIPT")
        misread = self.mech.parcel_flag(pid, "LABEL_MISREAD")
        if skip and skip[1].get("stage") == "depot" and not skip[1].get("done"):
            skip[1]["done"] = True
            self.mark(skip[0], pid)
            self.log(t, "received_unscanned", pid=pid, depot=depot)
        else:
            mech, barcode, confidence = [], None, None
            if misread and misread[1].get("stage") == "depot" and not misread[1].get("done"):
                misread[1]["done"] = True
                barcode, confidence, mech = _mutate(state.parcel.label_barcode, self.d, pid), round(self.d.uniform(.91, .97, "mr", pid), 3), [misread[0]]
                self.mark(misread[0], pid)
            if depot != state.target_depot and getattr(state, "missort_mid", None):
                mech = [*mech, state.missort_mid]
            scan = self.scan(pid, t, device, "HANDHELD_RECEIPT", facility=depot, barcode=barcode, confidence=confidence, trip=tid,
                             container=cid, mech=mech)
            self.custody_act(pid, t, "RECEIVED", vehicle, depot, scan, facility=depot, vehicle=vehicle, trip=tid)
            if state.status != "AT_DEPOT":
                self.status(state.shipment.sid, t, "AT_DELIVERY_DEPOT", scan)
            self.check_weigh(pid, depot, t)
        state.status = "AT_DEPOT"
        if state.routed_depot != state.target_depot and depot != state.target_depot:
            # A foreign parcel: the depot sends it back to the hub on the feeder's return leg.
            self.send_back(pid, depot, t, tid)
            return
        self.shelf[depot].add(pid)
        state.shelf_since = max(t, getattr(state, "weighed_at", t))

    def check_weigh(self, pid, depot, t):
        """Destination check scale: parcels the sort weighing flagged against the declaration, plus an audit sample."""
        state = self.p[pid]
        parcel = state.parcel
        measured = getattr(state, "sort_weight", None)
        if measured is None or getattr(state, "check_weighed", False):
            return
        tolerance = max(.5, parcel.declared_kg * .1)
        if abs(measured - parcel.declared_kg) <= tolerance and not self.d.chance(.08, "audit-weigh", pid):
            return
        state.check_weighed = True
        mech = [m for m in (getattr(state, "sort_drift_mid", None),) if m]
        flag = self.mech.parcel_flag(pid, "DECLARED_WEIGHT_WRONG")
        if flag:
            mech.append(flag[0])
        weight = round(max(.01, parcel.true_kg * (1 + self.d.normal(0, .012, "check-weigh", pid))), 2)
        when = t + timedelta(minutes=self.d.integer(2, 9, "check-weigh-t", pid))
        self.scan(pid, when, f"DEMO-DEV-SCL-{depot.removeprefix('DEMO-')}", "SCALE_WEIGH", facility=depot, weight=weight, mech=mech)
        state.weighed_at = when

    def send_back(self, pid, depot, t, tid):
        plan = self.trips[tid].plan
        hub = plan.origin
        rid = f"{tid}-R"
        if rid not in self.trips:
            back = TripPlan(rid, plan.lane, "FEEDER", depot, hub, (), self.trips[tid].arrived_at + timedelta(minutes=60),
                            self.trips[tid].arrived_at + timedelta(minutes=60) + (plan.scheduled_arrival - plan.scheduled_departure),
                            self.trips[tid].arrived_at + timedelta(minutes=45), plan.vehicle, plan.driver, plan.provider_id, plan.distance_km)
            state = TripState(back)
            self.trips[rid] = state
            self.net.trips[rid] = back
            depart = max(back.scheduled_departure, t + timedelta(minutes=20))
            state.departed_at = depart
            duration = back.scheduled_arrival - back.scheduled_departure
            state.arrived_at = depart + duration
            self.at(depart, "return_depart", rid)
            self.at(state.arrived_at, "return_arrive", rid)
        self.trips[rid].parcels.append(pid)
        self.trip_assign(pid, rid, t + timedelta(minutes=5))

    def _return_depart(self, t, rid):
        state = self.trips[rid]
        device = self.net.drivers[state.plan.driver].device
        for n, pid in enumerate(state.parcels):
            when = t - timedelta(minutes=5) + timedelta(seconds=15 * n)
            self.move(pid, when, "VEHICLE", state.plan.vehicle)
            self.hold(pid, when, state.plan.vehicle)
            scan = self.scan(pid, when, device, "LOAD_CONFIRMATION", facility=state.plan.origin, trip=rid, vehicle=state.plan.vehicle)
            self.custody_act(pid, when, "LOADED", state.plan.origin, state.plan.vehicle, scan, facility=state.plan.origin,
                             vehicle=state.plan.vehicle, trip=rid)
        self.trip_events(state, t, state.arrived_at)

    def _return_arrive(self, t, rid):
        state = self.trips[rid]
        hub = state.plan.destination
        device = self.net.facilities[hub].devices["FACILITY_HANDHELD"]
        for n, pid in enumerate(state.parcels):
            when = t + timedelta(minutes=15, seconds=20 * n)
            self.move(pid, when, "FACILITY", hub)
            self.hold(pid, when, hub)
            scan = self.scan(pid, when, device, "HANDHELD_RECEIPT", facility=hub, trip=rid)
            self.custody_act(pid, when, "RECEIVED", state.plan.vehicle, hub, scan, facility=hub, vehicle=state.plan.vehicle, trip=rid)
            ps = self.p[pid]
            ps.routed_depot = ps.target_depot
            self.rebag_at_hub(pid, hub, when + timedelta(minutes=self.d.integer(10, 40, "rebag", pid)))

    def rebag_at_hub(self, pid, hub, when):
        state = self.p[pid]
        depot = state.target_depot
        depot_hub = self.net.region_hub(self.net.facilities[depot].city)
        lane = self.net.feeder_lane(depot) if depot_hub == hub else self.net.linehaul_lane(hub, depot_hub)
        trip = self.net.next_trip(lane.id, when + timedelta(minutes=10))
        if trip is None:
            return  # Beyond the simulated schedule: the parcel waits at the hub.
        city = self.net.facilities[hub].city
        self.container_seq[city] += 1
        cid = f"DEMO-CTR-{city}-{self.container_seq[city]:05d}"
        c = ContainerState(cid, hub, depot, trip.id, when, timeline=[[when, "FACILITY", hub]])
        self.containers[cid] = c
        c.parcels.append(pid)
        c.hub_ready_at = when
        device = self.net.facilities[hub].devices["FACILITY_HANDHELD"]
        self.scan(pid, when, device, "CONTAINER_BAGGING", facility=hub, container=cid)
        self.move(pid, when, "CONTAINER", cid)
        self.trip_assign(pid, trip.id, when)
        self.at(max(trip.cutoff, when + timedelta(minutes=1)), "seal", cid)

    def _stock_check(self, t, depot, day):
        device = self.net.facilities[depot].devices["FACILITY_HANDHELD"]
        found = []
        for n, pid in enumerate(sorted(self.shelf[depot])):
            state = self.p[pid]
            if state.timeline[-1][1:] != ["FACILITY", depot]:
                continue
            when = t + timedelta(seconds=30 * n)
            scan = self.scan(pid, when, device, "INVENTORY_CHECK", facility=depot)
            if state.last_custody_to != depot:
                # The depot logs a parcel its records place elsewhere: found on the shelf.
                custody = self.custody_act(pid, when, "RECEIVED", state.last_custody_to or depot, depot, scan, facility=depot)
                found.append((pid, custody, when))
        for pid, custody, when in found:
            state = self.p[pid]
            pending = getattr(state, "pending_reconcile", None)
            if pending:
                route, attempt = pending
                self.act("reconcile", when + timedelta(minutes=2), pid=pid, sid=state.shipment.sid, route=route, result="RETURNED",
                         attempt=attempt, receipt=custody, proof=None, late=True)
                state.pending_reconcile = None

    # ------------------------------------------------------------------ last mile
    def _plan(self, t, depot, day):
        candidates = set()
        for pid in self.shelf[depot]:
            state = self.p[pid]
            if (state.timeline[-1][1:] == ["FACILITY", depot] and not state.delivered and not state.held
                    and (state.reschedule_until is None or state.reschedule_until <= day)):
                candidates.add(pid)
        cutoff = local_dt(day, "07:45")
        for c in self.containers.values():
            trip = self.trips.get(c.trip)
            if (c.depot == depot and c.opened_at is None and trip and trip.arrived_at and trip.arrived_at <= cutoff
                    and trip.plan.destination == depot and c.cid in trip.containers):
                for pid in c.parcels:
                    if self.p[pid].target_depot == depot:
                        candidates.add(pid)
        # Bags already opened whose parcels are still being scanned in (pre-advised to this depot).
        for pid, state in self.p.items():
            if (state.expected_shelf_at is not None and state.expected_shelf_at <= local_dt(day, "08:40")
                    and state.target_depot == depot and state.routed_depot == depot and not state.delivered):
                candidates.add(pid)
        if not candidates:
            return
        by_ship = defaultdict(list)
        for pid in sorted(candidates):
            by_ship[self.p[pid].shipment.sid].append(pid)
        facility = self.net.facilities[depot]
        def bearing(sid):
            point = self.stop_point(self.shipments[sid], t)
            return (math.atan2(point[0] - facility.lat, point[1] - facility.lng), sid)
        ordered = sorted(by_ship, key=bearing)
        weekday = day.weekday()
        drivers = [d for d in self.net.depot_drivers[depot] if self.net.drivers[d].off_weekday != weekday]
        rotation = (day - self.config.day1).days % max(1, len(drivers))
        drivers = drivers[rotation:] + drivers[:rotation]
        if not drivers:
            return
        n_routes = min(len(drivers), max(1, math.ceil(len(ordered) / 12)))
        if "UNRECORDED_HANDOFF" in self.mech.depot_day.get((depot, day), {}) and len(ordered) >= 4:
            n_routes = max(n_routes, min(2, len(drivers)))   # A second driver works the depot's area that day.
        if any(self.shipments[sid].bulky for sid in ordered) and all(
                self.net.vehicles[self.net.drivers[d].vehicle].type_key == "PRIVATE-CAR" for d in drivers[:n_routes]):
            vans = [d for d in drivers if self.net.vehicles[self.net.drivers[d].vehicle].type_key != "PRIVATE-CAR"]
            if vans:
                drivers.remove(vans[0])
                drivers.insert(0, vans[0])
        target_size = math.ceil(len(ordered) / n_routes)
        queue = list(ordered)
        spares = list(self.net.depot_spares.get(depot, []))
        for slot, driver in enumerate(drivers):
            if not queue:
                break
            dinfo = self.net.drivers[driver]
            vehicle = dinfo.vehicle
            if dinfo.employment != "INDEPENDENT" and spares and self.d.chance(.08, "swap", depot, day.isoformat(), slot):
                vehicle = spares.pop(0)   # The usual van is in maintenance: the driver takes a spare.
            vtype = self.net.vehicles[vehicle].type_key
            limit = min(ROUTE_MAX_STOPS[vtype], target_size if slot < n_routes else ROUTE_MAX_STOPS[vtype])
            keep, weight = [], 0.0
            for sid in list(queue):
                if len(keep) >= limit:
                    break
                shipment = self.shipments[sid]
                parcels_kg = sum(self.p[p].parcel.declared_kg for p in by_ship[sid])
                if (shipment.bulky and vtype == "PRIVATE-CAR") or weight + parcels_kg > self.net.vehicles[vehicle].payload_kg * .9:
                    continue
                keep.append(sid)
                queue.remove(sid)
                weight += parcels_kg
            if not keep:
                continue
            rid = f"DEMO-RR-{depot.removeprefix('DEMO-DEPOT-')}-{day.strftime('%m%d')}-{slot + 1}"
            route = RouteState(rid, depot, day, slot, driver, vehicle, dinfo.device, t)
            route.shipments = keep
            route.parcels = [p for sid in keep for p in by_ship[sid]]
            self.routes[rid] = route
            for key, value in self.mech.route.get((depot, day, slot), {}).items():
                route.mechs[key] = value
            plan_at = t + timedelta(minutes=self.d.integer(0, 8, "plan", rid))
            for sid in keep:
                pids = by_ship[sid]
                self.act("dispatch", plan_at, sid=sid, pids=list(pids), route=rid, date=day, vehicle=vehicle, driver=driver, depot=depot)
                for pid in pids:
                    self.p[pid].route = rid
            publish = local_dt(day, "07:30") + timedelta(minutes=self.d.integer(0, 9, "publish", rid))
            for sid in keep:
                self.act("manifest", publish, sid=sid, route=rid, version=1, pids=list(by_ship[sid]), status="PUBLISHED")
            self.at(local_dt(day, "08:00") + timedelta(minutes=self.d.integer(0, 10, "load", rid)), "load", rid)

    def stop_point(self, shipment, t):
        """Where the driver goes: the registered address (or a correction dispatch has applied by now)."""
        applied = self.corrections.get(shipment.sid)
        if applied and applied <= t:
            return shipment.recipient["home"]
        return shipment.recipient["registered_point"]

    def _load(self, t, rid):
        route = self.routes[rid]
        window_end = local_dt(route.date, LOAD_WINDOW_END)
        when = t
        route.login_at = t - timedelta(minutes=15)
        late = []
        for pid in route.parcels:
            state = self.p[pid]
            ready = state.expected_shelf_at or state.shelf_since or when
            slot = max(when + timedelta(seconds=self.d.integer(35, 95, "ld", rid, pid)), ready + timedelta(minutes=2))
            if slot > window_end:
                late.append(pid)   # Not on the shelf in time: the dispatcher drops it from this route.
                continue
            when = slot
            flag = self.mech.parcel_flag(pid, "ASSIGNED_NOT_LOADED")
            if flag and not flag[1].get("done"):
                flag[1]["done"] = True
                self.mark(flag[0], pid)
                continue           # Left on the shelf; nobody notices at loading.
            self.at(slot, "load_parcel", rid, pid)
            route.loaded.append(pid)
        depart = when + timedelta(minutes=self.d.integer(5, 12, "depart", rid))
        route.departed_at = depart
        revision = route.mechs.get("MANIFEST_ERROR")
        if revision or late or self.d.chance(.12, "revise", rid):
            # Version 2 of the route manifest: every shipment on the route gets its line, changed or not.
            at = depart - timedelta(minutes=self.d.integer(2, 6, "rev", rid))
            dropped, mid = None, None
            if revision and route.loaded:
                mid = revision[0]
                prefer = [p for p in route.loaded if p in revision[1].get("prefer", ())] or route.loaded
                dropped = prefer[int(self.d.u("drop", rid) * len(prefer))]
                self.mark(mid, dropped)
            for sid in route.shipments:
                pids = [p for p in route.parcels if self.p[p].shipment.sid == sid]
                lines = [p for p in pids if p != dropped and p not in late]
                self.act("manifest", at, sid=sid, route=rid, version=2, pids=lines, status="REVISED",
                         mech=[mid] if mid and dropped in pids else [])
        self.at(depart, "route_depart", rid)

    def _load_parcel(self, t, rid, pid):
        route = self.routes[rid]
        state = self.p[pid]
        if state.timeline[-1][1:] != ["FACILITY", route.depot]:
            route.loaded.remove(pid)
            return
        self.shelf[route.depot].discard(pid)
        self.move(pid, t, "VEHICLE", route.vehicle)
        self.hold(pid, t, route.vehicle)
        scan = self.scan(pid, t, route.device, "LOAD_CONFIRMATION", facility=route.depot, route=rid, vehicle=route.vehicle)
        custody = self.custody_act(pid, t, "LOADED", route.depot, route.vehicle, scan, facility=route.depot, vehicle=route.vehicle, route=rid)
        state.status = "OUT_FOR_DELIVERY"
        key = (state.shipment.sid, rid)
        if key not in route.mechs.setdefault("_ofd", set()):
            route.mechs["_ofd"].add(key)
            self.status(state.shipment.sid, t, "OUT_FOR_DELIVERY", custody)

    def _route_depart(self, t, rid):
        route = self.routes[rid]
        depot = self.net.facilities[route.depot]
        stops = []
        for sid in route.shipments:
            pids = [p for p in route.loaded if self.p[p].shipment.sid == sid]
            if pids:
                stops.append({"sid": sid, "pids": pids})
        # Nearest-neighbour stop order from the depot.
        position, ordered = (depot.lat, depot.lng), []
        remaining = list(stops)
        while remaining:
            nxt = min(remaining, key=lambda s: (haversine_km(*position, *self.stop_point(self.shipments[s["sid"]], t)), s["sid"]))
            remaining.remove(nxt)
            ordered.append(nxt)
            position = self.stop_point(self.shipments[nxt["sid"]], t)
        route.stops = ordered
        route.timeline.append((t, depot.lat, depot.lng, "DEPART"))
        handoff = self.mech.depot_day.get((route.depot, route.date), {}).get("UNRECORDED_HANDOFF")
        route.position = (depot.lat, depot.lng)
        route.clock = t
        route.cursor = 0
        route.early_end = (local_dt(route.date, "13:00") + timedelta(minutes=self.d.integer(0, 240, "early-end-t", rid))
                           if self.d.chance(.04, "early-end", rid) else None)   # A personal or vehicle problem cuts the shift short.
        self.at(t, "route_next", rid)

    def _route_next(self, t, rid):
        route = self.routes[rid]
        city = self.net.facilities[route.depot].city
        depot = self.net.facilities[route.depot]
        session_end = local_dt(route.date, self.config.session_end)
        handoff = self.mech.depot_day.get((route.depot, route.date), {}).get("UNRECORDED_HANDOFF")
        if handoff and handoff[1]["from"] == route.slot and route.cursor == handoff[1]["after"] and not handoff[1].get("done"):
            target = next((r for r in self.routes.values() if r.depot == route.depot and r.date == route.date and r.slot == handoff[1]["to"]
                           and r.departed_at is not None and r.departed_at <= t and r.returned_at is None
                           and getattr(r, "cursor", 0) < len(r.stops)), None)
            pending = [s for s in route.stops[route.cursor:]]
            moved = pending[: handoff[1]["k"]]
            if target is not None and moved:
                handoff[1]["done"] = True
                for stop in moved:
                    route.stops.remove(stop)
                    for pid in stop["pids"]:
                        self.move(pid, t + timedelta(minutes=10), "VEHICLE", target.vehicle)
                        self.hold(pid, t + timedelta(minutes=10), target.vehicle)
                        self.mark(handoff[0], pid)
                        route.handed_out.append(pid)
                        target.handed_in.append(pid)
                    target.stops.append({**stop, "foreign": True, "mech": handoff[0]})
                self.log(t, "unrecorded_handoff", from_route=rid, to_route=target.rid, parcels=[p for s in moved for p in s["pids"]])
                t = t + timedelta(minutes=15)
        if route.cursor >= len(route.stops):
            back = road_km(*route.position, depot.lat, depot.lng, urban=True)
            arrival = t + timedelta(seconds=round(back / 28 * 3600))
            self.at(arrival, "route_end", rid)
            return
        stop = route.stops[route.cursor]
        shipment = self.shipments[stop["sid"]]
        point = self.misdelivery_point(shipment) or self.stop_point(shipment, t)
        distance = road_km(*route.position, *point, urban=True)
        speed = 28 * self.d.uniform(.8, 1.2, "speed", rid, route.cursor) * _rush(t)
        district = shipment.recipient["district"]
        factor, mid = self.mech.traffic_at(city, district, t)
        travel = distance / speed * 3600 * factor
        arrive = t + timedelta(seconds=round(travel))
        if mid and factor > 1:
            for pid in stop["pids"]:
                self.mark(mid, pid)
        back = road_km(*point, depot.lat, depot.lng, urban=True) / 28 * 3600
        if arrive + timedelta(minutes=8) + timedelta(seconds=back) > session_end or (route.early_end and arrive > route.early_end):
            # Out of time: the remaining stops are recorded as not attempted and come back to the depot.
            for rest in route.stops[route.cursor:]:
                for pid in rest["pids"]:
                    self.not_attempted(route, rest, pid, t)
                    if mid:
                        self.mark(mid, pid)
                    for row in self.mech.traffic:
                        if row[0] == city and row[2] <= t <= row[3] + timedelta(hours=2):
                            self.mark(row[5], pid)
            route.cursor = len(route.stops)
            self.at(t, "route_next", rid)
            return
        route.position = point
        route.timeline.append((arrive, point[0], point[1], "STOP"))
        finish = self.attempt_stop(route, stop, arrive)
        route.cursor += 1
        self.at(finish, "route_next", rid)

    def misdelivery_point(self, shipment):
        flag = self.mech.shipment_flag(shipment.sid, "MISDELIVERY")
        if flag and not flag[1].get("done"):
            home = shipment.recipient["home"]
            return offset_point(home[0], home[1], flag[1]["north_km"], flag[1]["east_km"])
        return None

    def not_attempted(self, route, stop, pid, t):
        state = self.p[pid]
        state.attempts += 1
        attempt = self.act("attempt", t, pid=pid, sid=stop["sid"], route=route.rid, vehicle=route.vehicle, driver=route.driver,
                           device=route.device, disposition="FAILED", reason="NOT_ATTEMPTED_TIME", gate=None,
                           address=self.address_tag(state.shipment, t), point=None)
        state.last_attempt = attempt
        state.last_attempt_failed = True

    def address_tag(self, shipment, t):
        applied = self.corrections.get(shipment.sid)
        return "v2" if applied and applied <= t else "v1"

    def available(self, shipment, t, attempt_no):
        """Whether the recipient can receive in person at t (keyed draw; mechanisms override)."""
        flag = self.mech.shipment_flag(shipment.sid, "RECIPIENT_UNAVAILABLE")
        if flag and flag[1]["start"] <= t < flag[1]["end"]:
            return False, flag[0]
        pattern = shipment.recipient["availability"]
        hour = local_hour(t)
        p = {"HOME": .96, "IRREGULAR": .82, "BUSINESS_HOURS": .97 if 8 <= hour < 17 else .15,
             "EVENINGS": .45 if hour < 15 else .93}[pattern]
        if attempt_no >= 2:
            p = max(p, .90)  # After a failed attempt the recipient expects the parcel (the failure notice set a window).
        return self.d.chance(p, "avail", shipment.sid, attempt_no), None

    def attempt_stop(self, route, stop, arrive):
        shipment = self.shipments[stop["sid"]]
        sid = shipment.sid
        key = ("stop", sid, arrive.isoformat())
        t = arrive + timedelta(minutes=self.d.integer(2, 5, *key, "walk"))
        pids = stop["pids"]
        attempt_no = max(self.p[p].attempts for p in pids) + 1
        foreign = stop.get("foreign", False)
        device = route.device
        # --- where the driver actually stands
        misdelivery = self.mech.shipment_flag(sid, "MISDELIVERY")
        wrong_address = self.mech.shipment_flag(sid, "WRONG_ADDRESS")
        at_old_address = wrong_address and self.address_tag(shipment, t) == "v1"
        gate_flag = self.mech.shipment_flag(sid, "WRONG_GATE")
        gates = shipment.recipient["gates"]
        gate = None
        if gates:
            gate = shipment.recipient["gate"]
            if gate_flag and not gate_flag[1].get("resolved"):
                gate = gate_flag[1]["pin_gate"]
                for pid in pids:
                    self.mark(gate_flag[0], pid)
        available, unavailable_mid = self.available(shipment, t, attempt_no)
        neighbour_flag = self.mech.shipment_flag(sid, "NEIGHBOUR_RECEIVES")
        if neighbour_flag and not neighbour_flag[1].get("done"):
            available = False   # The recipient has stepped out; a neighbour offers to take the parcel.
        if unavailable_mid:
            for pid in pids:
                self.mark(unavailable_mid, pid)
        otp_mode = None
        online = self.mech.down(device, t) is None
        if shipment.otp_required:
            # Some merchants issue a static delivery PIN; an offline app falls back to the PIN as well.
            if not online or self.d.chance(.30, "pinmerchant", sid):
                otp_mode = "PIN"
            else:
                otp_mode = "OTP"
        outcome, reason, recipient_type, receiver, auth_result, signer = None, None, None, None, None, None
        contact_result = None
        mech_fields = [unavailable_mid] if unavailable_mid else []
        if foreign and stop.get("mech"):
            mech_fields.append(stop["mech"])
        notes = {}
        routine = None
        if shipment.recipient_kind == "Customer" and attempt_no == 1 and not at_old_address and not (misdelivery and not misdelivery[1].get("done")):
            if self.d.chance(.015, *key, "bg-address"):
                routine = "ADDRESS_NOT_FOUND"
            elif self.d.chance(.05 if gates else .01, *key, "bg-access"):
                routine = "ACCESS_NOT_COMPLETED"
        if routine:
            outcome, reason = "FAILED", routine
            contact_result = "ANSWERED" if self.d.chance(.6, *key, "bg-call") else "NO_RESPONSE"
        elif at_old_address:
            for pid in pids:
                self.mark(wrong_address[0], pid)
            mech_fields.append(wrong_address[0])
            available = False
            contact_result = self.d.weighted((("NO_RESPONSE", .45), ("ANSWERED", .55)), *key, "wa-call")
            reason = self.d.weighted((("ADDRESS_NOT_FOUND", .55), ("RECIPIENT_NOT_REACHED", .30), ("OTHER", .15)), *key, "wa-reason")
            if contact_result == "NO_RESPONSE" and reason == "ADDRESS_NOT_FOUND":
                reason = self.d.weighted((("ADDRESS_NOT_FOUND", .6), ("RECIPIENT_NOT_REACHED", .4)), *key, "wa-reason2")
            outcome = "FAILED"
            if not wrong_address[1].get("correction_at"):
                delay = self.d.lognormal(4 * 3600, .7, *key, "corr")
                if self.d.chance(.85, *key, "corr-happens"):
                    wrong_address[1]["correction_at"] = t + timedelta(seconds=round(min(delay, 30 * 3600)))
                    self.at(wrong_address[1]["correction_at"], "correction", sid)
        elif misdelivery and not misdelivery[1].get("done"):
            misdelivery[1]["done"] = True
            for pid in pids:
                self.mark(misdelivery[0], pid)
            mech_fields.append(misdelivery[0])
            outcome = "DELIVERED"
            recipient_type = self.d.weighted((("EXPECTED_RECIPIENT", .5), ("OTHER_PERSON", .3), ("LEFT_AT_DOOR", .2)), *key, "md-type")
            receiver = "OCCUPANT"
            if self.d.chance(.55, *key, "md-call"):
                # Like any driver whose recipient does not come to the door, the driver may call first.
                contact_result = "ANSWERED" if self.d.chance(.55, *key, "md-call-answer") else "NO_RESPONSE"
            auth_result = "FAIL" if shipment.otp_required and recipient_type != "LEFT_AT_DOOR" else None
            notes["away"] = True
        elif gate and gate_flag and not gate_flag[1].get("resolved"):
            contact_result = self.d.weighted((("ANSWERED", .6), ("NO_RESPONSE", .4)), *key, "gate-call")
            if contact_result == "ANSWERED" and available:
                gate_flag[1]["resolved"] = True
                outcome = "DELIVERED"
                recipient_type, receiver = "EXPECTED_RECIPIENT", "RECIPIENT"
                t += timedelta(minutes=self.d.integer(6, 15, *key, "gate-wait"))
            else:
                outcome, reason = "FAILED", "ACCESS_NOT_COMPLETED"
                if self.d.chance(.5, *key, "gate-fix"):
                    gate_flag[1]["resolved"] = True  # The recipient updates the instruction for next time.
            mech_fields.append(gate_flag[0])
        elif available:
            outcome = "DELIVERED"
            if shipment.flow == "B2B":
                recipient_type = "EXPECTED_RECIPIENT" if shipment.recipient["preference"] == "STANDARD" else "AUTHORIZED_ALTERNATE"
                receiver = "RECIPIENT" if recipient_type == "EXPECTED_RECIPIENT" else "RECEPTION"
            elif shipment.recipient["preference"] == "LEAVE_AT_DOOR" and self.d.chance(.6, *key, "door"):
                recipient_type, receiver = "LEFT_AT_DOOR", "DOOR"
            elif self.d.chance(.06, *key, "family"):
                recipient_type, receiver = "AUTHORIZED_ALTERNATE", "FAMILY"
            else:
                recipient_type, receiver = "EXPECTED_RECIPIENT", "RECIPIENT"
        else:
            contact_result = "ANSWERED" if self.d.chance(.55 if not unavailable_mid else .25, *key, "call") else "NO_RESPONSE"
            neighbour = self.mech.shipment_flag(sid, "NEIGHBOUR_RECEIVES")
            pref = shipment.recipient["preference"]
            if neighbour and not neighbour[1].get("done"):
                neighbour[1]["done"] = True
                for pid in pids:
                    self.mark(neighbour[0], pid)
                mech_fields.append(neighbour[0])
                outcome = "DELIVERED"
                if not self.d.chance(.55, *key, "nb-call"):
                    contact_result = None   # The neighbour offered at the door before the driver called.
                recipient_type = self.d.weighted((("OTHER_PERSON", .6), ("AUTHORIZED_ALTERNATE", .4)), *key, "nb-type")
                receiver = "NEIGHBOUR_UNAUTHORIZED"
                auth_result = "FAIL" if otp_mode else None
            elif contact_result == "ANSWERED":
                choice = self.d.weighted((("COME_DOWN", .45), ("ALTERNATE", .25 if pref in ("AUTHORIZED_NEIGHBOUR", "RECEPTION") else .05),
                                          ("DOOR", .25 if pref == "LEAVE_AT_DOOR" else .0), ("RESCHEDULE", .22)), *key, "answer")
                if unavailable_mid:
                    choice = "RESCHEDULE"
                if choice == "COME_DOWN":
                    outcome, recipient_type, receiver = "DELIVERED", "EXPECTED_RECIPIENT", "RECIPIENT"
                    t += timedelta(minutes=self.d.integer(4, 12, *key, "wait"))
                elif choice == "ALTERNATE":
                    outcome, recipient_type, receiver = "DELIVERED", "AUTHORIZED_ALTERNATE", "NEIGHBOUR_AUTHORIZED" if pref == "AUTHORIZED_NEIGHBOUR" else "RECEPTION"
                elif choice == "DOOR":
                    outcome, recipient_type, receiver = "DELIVERED", "LEFT_AT_DOOR", "DOOR"
                else:
                    outcome, reason = "FAILED", "CUSTOMER_REQUESTED_RESCHEDULE"
            else:
                outcome, reason = "FAILED", "RECIPIENT_NOT_REACHED"
        # --- one-time code
        otp_failed = False
        if outcome == "DELIVERED" and otp_mode == "OTP" and receiver == "OCCUPANT":
            # The code reaches the real recipient's phone; the person at the wrong door cannot give it.
            self.act("comm", t, sid=sid, pid=pids[0], purpose="OTP", channel_type="SMS", status="DELIVERED",
                     carrier=shipment.recipient["carrier_route"])
        elif outcome == "DELIVERED" and otp_mode == "OTP" and receiver in ("RECIPIENT", "FAMILY"):
            route_name = shipment.recipient["carrier_route"]
            outage = self.mech.sms_down(route_name, t)
            individual = self.mech.shipment_flag(sid, "OTP_NOT_RECEIVED")
            if individual and individual[1].get("from") and not (individual[1]["from"] <= t < individual[1]["until"]):
                individual = None
            first_ok = not outage and not individual and not self.d.chance(.025, *key, "sms1")
            self.act("comm", t, sid=sid, pid=pids[0], purpose="OTP", channel_type="SMS", status="DELIVERED" if first_ok else "FAILED",
                     carrier=route_name, mech=[m for m in (outage, individual[0] if individual else None) if m])
            resend = not first_ok or self.d.chance(.12, *key, "resend")   # The code expired or was not noticed.
            ok = first_ok
            if resend:
                second_ok = not outage and not individual and not self.d.chance(.10, *key, "sms2")
                self.act("comm", t + timedelta(minutes=2), sid=sid, pid=pids[0], purpose="OTP_RESEND", channel_type="SMS",
                         status="DELIVERED" if second_ok else "FAILED", carrier=route_name,
                         mech=[m for m in (outage, individual[0] if individual else None) if m])
                ok = first_ok or second_ok
                t += timedelta(minutes=3)
            mids = [m for m in (outage, individual[0] if individual else None) if m]
            for m in mids:
                for pid in pids:
                    self.mark(m, pid)
            if not ok:
                otp_failed = True
                mech_fields += mids
                # The recipient is at the door; like the other branches, the driver calls the number on file only sometimes.
                if not contact_result and self.d.chance(.55, *key, "otp-call"):
                    contact_result = "ANSWERED" if self.d.chance(.55, *key, "otp-call-answer") else "NO_RESPONSE"
                if self.d.chance(.35, *key, "override"):
                    auth_result = "FAIL"
                    notes["override"] = True
                else:
                    outcome = "FAILED"
                    reason = self.d.weighted((("OTP_NOT_CONFIRMED", .55), ("RECIPIENT_NOT_REACHED", .25), ("OTHER", .20)), *key, "otp-reason")
            elif self.d.chance(.03, *key, "code-not-given"):
                # The code arrived but the recipient cannot produce it (phone elsewhere): ordinary, rescheduled.
                outcome = "FAILED"
                reason = "OTP_NOT_CONFIRMED"
                contact_result = contact_result or "ANSWERED"
            elif auth_result is None:
                auth_result = "PASS"
        elif outcome == "DELIVERED" and otp_mode == "PIN" and receiver in ("RECIPIENT", "FAMILY"):
            auth_result = "PASS"
        # --- records of the attempt
        scan_skipped = self.mech.shipment_flag(sid, "DELIVERY_SCAN_SKIPPED")
        skip_records = outcome == "DELIVERED" and scan_skipped and not scan_skipped[1].get("done") and receiver in ("RECIPIENT", "FAMILY", "DOOR")
        if skip_records:
            scan_skipped[1]["done"] = True
            for pid in pids:
                self.mark(scan_skipped[0], pid)
        person = None
        if outcome == "DELIVERED" and receiver in ("NEIGHBOUR_UNAUTHORIZED", "NEIGHBOUR_AUTHORIZED", "RECEPTION", "FAMILY") or (
                outcome == "DELIVERED" and receiver == "OCCUPANT" and recipient_type == "OTHER_PERSON"):
            self.person_seq[sid] += 1
            person = f"{sid}-PERSON-{self.person_seq[sid]}"
            self.act("person", t, sid=sid, person=person, role=receiver)
        holder = {"RECIPIENT": shipment.recipient_id, "FAMILY": person, "DOOR": shipment.recipient_id, "RECEPTION": person,
                  "NEIGHBOUR_AUTHORIZED": person, "NEIGHBOUR_UNAUTHORIZED": person,
                  "OCCUPANT": person or f"PRIVATE-OCCUPANT-{sid}"}.get(receiver)
        point = self.misdelivery_point(shipment) if receiver == "OCCUPANT" else None
        if receiver == "OCCUPANT":
            home = shipment.recipient["home"]
            flag = self.mech.shipment_flag(sid, "MISDELIVERY")
            point = offset_point(home[0], home[1], flag[1]["north_km"], flag[1]["east_km"])
        else:
            point = self.stop_point(shipment, t) if not at_old_address else shipment.recipient["registered_point"]
        if outcome == "FAILED" and reason not in ("NOT_ATTEMPTED_TIME", None) and self.d.chance(.08, *key, "reason-other"):
            reason = "OTHER"   # Driver-entered reason codes are noisy: some failures are filed under OTHER.
        for n, pid in enumerate(pids):
            state = self.p[pid]
            state.attempts += 1
            when = t + timedelta(seconds=40 * n)
            if outcome == "DELIVERED":
                self.move(pid, when, "PERSON", holder)
                self.hold(pid, when, holder)
                state.delivered = True
                state.status = "DELIVERED"
                if skip_records:
                    self.log(when, "delivered_unrecorded", pid=pid, route=route.rid)
                    continue
            if skip_records:
                continue
            address_tag = self.address_tag(shipment, when) if not at_old_address else "v1"
            notes["address"] = address_tag
            attempt = self.act("attempt", when, pid=pid, sid=sid, route=route.rid, vehicle=route.vehicle, driver=route.driver,
                               device=device, disposition=outcome, reason=reason if outcome == "FAILED" else None, gate=gate,
                               address=address_tag, point=point, foreign=foreign, mech=list(mech_fields))
            state.last_attempt = attempt
            state.last_attempt_failed = outcome == "FAILED"
            if contact_result:
                self.act("contact", when - timedelta(minutes=3), pid=pid, sid=sid, attempt=attempt, result=contact_result, device=device)
            if outcome != "DELIVERED":
                if reason == "CUSTOMER_REQUESTED_RESCHEDULE":
                    state.reschedule_until = route.date + timedelta(days=1 if self.d.chance(.8, *key, "resched") else 2)
                continue
            proof = self.pod(route, shipment, pid, when, attempt, recipient_type, receiver, person, auth_result, otp_mode, point, notes)
            scan = self.scan(pid, when, device, "DELIVERY_SCAN", route=route.rid, vehicle=route.vehicle, bundle=attempt)
            complete = recipient_type in ("EXPECTED_RECIPIENT", "LEFT_AT_DOOR") and auth_result != "FAIL" and receiver != "OCCUPANT" or (
                recipient_type == "AUTHORIZED_ALTERNATE" and receiver in ("NEIGHBOUR_AUTHORIZED", "RECEPTION", "FAMILY"))
            # Custody passes to the consignee (through an agent when someone else takes it); the handoff record
            # names who physically took the parcel.
            self.custody_act(pid, when, "DELIVERED", route.vehicle, shipment.recipient_id,
                             scan, vehicle=route.vehicle, route=route.rid, acks=2 if complete else 1,
                             quality="CORROBORATED" if complete else "INCOMPLETE_ACK", proof=proof, mech=mech_fields)
            state.delivered_proof = proof
        first_attempt = getattr(self.p[pids[0]], "last_attempt", None)
        if outcome == "DELIVERED" and not skip_records:
            self.status(sid, t, "DELIVERED", first_attempt)
        elif outcome == "FAILED":
            self.status(sid, t, "DELIVERY_ATTEMPTED", first_attempt)
        service = self.d.integer(3, 7, *key, "service")
        return t + timedelta(minutes=service, seconds=40 * len(pids))

    def pod(self, route, shipment, pid, when, attempt, recipient_type, receiver, person, auth_result, otp_mode, point, notes):
        key = ("pod", pid, when.isoformat())
        sid = shipment.sid
        accuracy = round(self.d.uniform(6, 22, *key, "acc"), 1)
        lat, lng = point
        # GPS noise around the stop; a small share of fixes in dense blocks drift further than reported.
        sigma = accuracy / 2.4 if not self.d.chance(.012, *key, "canyon") else accuracy * 2.2
        lat, lng = offset_point(lat, lng, self.d.normal(0, sigma / 1000, *key, "n"), self.d.normal(0, sigma / 1000, *key, "e"))
        auth = sign = None
        authorized = recipient_type == "AUTHORIZED_ALTERNATE" and receiver in ("NEIGHBOUR_AUTHORIZED", "RECEPTION", "FAMILY")
        if auth_result is not None:
            auth = self.act("auth", when, pid=pid, sid=sid, attempt=attempt, method="OTP" if otp_mode == "OTP" else "PIN",
                            result=auth_result, authorized=person if authorized else shipment.recipient_id)
        if shipment.flow == "B2B" or receiver in ("NEIGHBOUR_UNAUTHORIZED", "NEIGHBOUR_AUTHORIZED", "RECEPTION", "FAMILY") or notes.get("override"):
            sign = self.act("signature", when, pid=pid, sid=sid, attempt=attempt, signer=person or shipment.recipient_id)
        subject = "parcel_at_door" if recipient_type == "LEFT_AT_DOOR" else self.d.choice(("door", "handover", "building_entrance"), *key, "subj")
        photo = self.act("photo", when, pid=pid, sid=sid, attempt=attempt, lat=round(lat, 6), lng=round(lng, 6), accuracy=accuracy,
                         subject=subject, address=notes["address"])
        handoff = self.act("handoff", when, pid=pid, sid=sid, attempt=attempt, person=person or shipment.recipient_id,
                           person_type=recipient_type, authorized=authorized or recipient_type == "LEFT_AT_DOOR" and receiver == "DOOR")
        return self.act("proof", when, pid=pid, sid=sid, attempt=attempt, lat=round(lat, 6), lng=round(lng, 6), accuracy=accuracy,
                        auth=auth, signature=sign, photo=photo, handoff=handoff, address=self.acts_by_id(photo)["address"])

    def _minor_correction(self, t, sid):
        """A recipient refines the pin or adds a unit number; the delivery point moves a few metres."""
        shipment = self.shipments[sid]
        if any(self.p[p.pid].delivered for p in shipment.parcels):
            return
        home = shipment.recipient["registered_point"]
        moved = offset_point(home[0], home[1], self.d.uniform(-.012, .012, "mc-n", sid), self.d.uniform(-.012, .012, "mc-e", sid))
        shipment.recipient["home"] = (round(moved[0], 6), round(moved[1], 6))
        self.act("address_v2", t, sid=sid, point=shipment.recipient["home"], minor=True)
        self.corrections[sid] = t + timedelta(minutes=self.d.integer(20, 90, "apply", sid))

    def _correction(self, t, sid):
        shipment = self.shipments[sid]
        self.act("address_v2", t, sid=sid, point=shipment.recipient["home"], mech=[self.mech.shipment_flag(sid, "WRONG_ADDRESS")[0]])
        # Dispatch applies the correction to the next planning run (or a route still out, if the app syncs it).
        self.corrections[sid] = t + timedelta(minutes=self.d.integer(20, 90, "apply", sid))

    def _route_end(self, t, rid):
        route = self.routes[rid]
        depot = self.net.facilities[route.depot]
        route.returned_at = t
        route.timeline.append((t, depot.lat, depot.lng, "RETURN"))
        retains = route.mechs.get("CONTRACTOR_RETAINS")
        handheld = depot.devices["FACILITY_HANDHELD"]
        on_board = [pid for pid in route.loaded + route.handed_in if pid not in route.handed_out
                    and self.p[pid].timeline[-1][1:] == ["VEHICLE", route.vehicle]]
        if retains and on_board:
            route.retained = True
            for pid in on_board:
                self.p[pid].retained = True
                self.mark(retains[0], pid)
            route.logout_at = None  # The app goes silent: no check-in, no logout.
            self.log(t, "contractor_retains", route=rid, parcels=on_board)
            if retains[1].get("returns_after_hours"):
                self.at(t + timedelta(hours=retains[1]["returns_after_hours"]), "late_return", rid)
            self.reconcile_route(route, t, exclude=set(on_board))
            return
        route.logout_at = t + timedelta(minutes=20)
        skip = None
        for n, pid in enumerate(on_board):
            when = t + timedelta(minutes=5, seconds=40 * n)
            state = self.p[pid]
            self.move(pid, when, "FACILITY", route.depot)
            self.hold(pid, when, route.depot)
            self.shelf[route.depot].add(pid)
            state.shelf_since = when
            if state.attempts >= MAX_ATTEMPTS:
                state.held = True
            flag = self.mech.parcel_flag(pid, "RETURN_SCAN_SKIPPED")
            if flag and not flag[1].get("done"):
                flag[1]["done"] = True
                self.mark(flag[0], pid)
                state.pending_reconcile = (rid, getattr(state, "last_attempt", None))
                self.log(when, "returned_unscanned", pid=pid, route=rid)
                continue
            scan = self.scan(pid, when, handheld, "RETURN_SCAN", facility=route.depot, route=rid, vehicle=route.vehicle)
            receipt = self.custody_act(pid, when, "RETURNED", route.vehicle, route.depot, scan, facility=route.depot,
                                       vehicle=route.vehicle, route=rid)
            state.return_receipt = receipt
            if state.status != "HELD":
                state.status = "RETURNED_TO_DEPOT"
        statuses = {}
        for pid in on_board:
            receipt = getattr(self.p[pid], "return_receipt", None)
            if receipt and self.acts_by_id(receipt)["route"] == rid:
                statuses.setdefault(self.p[pid].shipment.sid, receipt)
        for sid in sorted(statuses):
            self.status(sid, self.acts_by_id(statuses[sid])["t"], "RETURNED_TO_DEPOT", statuses[sid])
        self.reconcile_route(route, t + timedelta(minutes=8), exclude=set())

    def reconcile_route(self, route, t, exclude):
        n = 0
        for pid in route.loaded + route.handed_in:
            if pid in exclude or pid in route.handed_out:
                continue
            state = self.p[pid]
            attempt = getattr(state, "last_attempt", None)
            if attempt is None or self.acts_by_id(attempt)["route"] != route.rid and pid not in route.handed_in:
                continue
            when = t + timedelta(seconds=20 * n)
            n += 1
            if state.delivered and getattr(state, "delivered_proof", None) and self.acts_by_id(state.delivered_proof)["t"] <= when:
                self.act("reconcile", when, pid=pid, sid=state.shipment.sid, route=route.rid, result="DELIVERED", attempt=attempt,
                         receipt=None, proof=state.delivered_proof)
            elif getattr(state, "return_receipt", None) and self.acts_by_id(state.return_receipt)["route"] == route.rid:
                self.act("reconcile", when, pid=pid, sid=state.shipment.sid, route=route.rid, result="RETURNED", attempt=attempt,
                         receipt=state.return_receipt, proof=None)

    def _late_return(self, t, rid):
        route = self.routes[rid]
        handheld = self.net.facilities[route.depot].devices["FACILITY_HANDHELD"]
        for n, pid in enumerate(sorted(p for p in route.loaded if self.p[p].retained)):
            state = self.p[pid]
            if state.timeline[-1][1:] != ["VEHICLE", route.vehicle]:
                continue
            when = t + timedelta(seconds=40 * n)
            state.retained = False
            self.move(pid, when, "FACILITY", route.depot)
            self.hold(pid, when, route.depot)
            self.shelf[route.depot].add(pid)
            state.shelf_since = when
            scan = self.scan(pid, when, handheld, "RETURN_SCAN", facility=route.depot, route=rid, vehicle=route.vehicle)
            receipt = self.custody_act(pid, when, "RETURNED", route.vehicle, route.depot, scan, facility=route.depot, vehicle=route.vehicle, route=rid)
            state.return_receipt = receipt
            if state.attempts >= MAX_ATTEMPTS:
                state.held = True
            attempt = getattr(state, "last_attempt", None)
            if attempt:
                self.act("reconcile", when + timedelta(minutes=3), pid=pid, sid=state.shipment.sid, route=rid, result="RETURNED",
                         attempt=attempt, receipt=receipt, proof=None, late=True)
        route.late_session = (t - timedelta(minutes=10), t + timedelta(minutes=20))

    # ------------------------------------------------------------------ outputs
    def throughput(self):
        """Hourly processed counts per sort and depot (the facility's own WMS report)."""
        rows = []
        for (facility, hour), count in sorted(self.processed.items()):
            rows.append((facility, hour, count))
        return rows


def _hours(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h + m / 60


def _rush(t):
    hour = local_hour(t)
    return .75 if 7 <= hour < 9 or 16 <= hour < 19 else 1.0


def _mutate(barcode, draws, pid):
    """One misread digit: a plausible wrong read of the same label."""
    digits = [i for i, ch in enumerate(barcode) if ch.isdigit()]
    position = digits[int(draws.u("misread-pos", pid) * len(digits))]
    original = barcode[position]
    replacement = str((int(original) + 1 + int(draws.u("misread-digit", pid) * 8)) % 10)
    return barcode[:position] + replacement + barcode[position + 1:]
