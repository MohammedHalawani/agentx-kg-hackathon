"""The static network: organizations, facilities, devices, providers, fleet, lanes and trip schedules.

Synthetic and scaled to a ~100 shipments/day world: capacities are set relative to that volume, not to
real SPL throughput. Lanes, departure times and cutoffs are plausible assumptions, not SPL schedules.
"""
from dataclasses import dataclass, field
from datetime import timedelta
import math

from world.config import WorldConfig, local_dt
from world.geo import CITIES, CITY, REGION_HUB, offset_point, road_km
from world.rand import Draws

PROVIDERS = {
    "DEMO-PROV-SPL": {"provider_type": "IN_HOUSE", "name": "Synthetic SPL in-house fleet", "channel": "SPL_CORE"},
    "DEMO-PROV-3PL-01": {"provider_type": "CONTRACTOR_3PL", "name": "Synthetic contracted linehaul carrier", "channel": "CARRIER_EDI"},
    "DEMO-PROV-LMC-01": {"provider_type": "CONTRACTOR_LAST_MILE", "name": "Synthetic last-mile contractor", "channel": "SPL_CORE"},
    "DEMO-PROV-INDEP-01": {"provider_type": "INDEPENDENT_PLATFORM", "name": "Synthetic independent-driver platform", "channel": "DRIVER_APP"},
    "DEMO-PROV-MSG-01": {"provider_type": "MESSAGING_GATEWAY", "name": "Synthetic SMS/WhatsApp gateway", "channel": "MESSAGING"},
}
SPL_OPERATOR = "DEMO-ORG-SPL-OPS"

# key -> (payload kg, volume m3, handling, modes, label)
VEHICLE_TYPES = {
    "LM-VAN": (800., 6., ["standard", "bulky"], ["last_mile"], "Last-mile van"),
    "PRIVATE-CAR": (300., 1.5, ["standard"], ["last_mile"], "Private car"),
    "FM-VAN": (1500., 10., ["standard", "bulky"], ["local_transfer"], "Collection van"),
    "FEEDER": (7000., 30., ["standard", "bulky"], ["local_transfer"], "Feeder truck"),
    "LINEHAUL": (12000., 60., ["standard", "bulky"], ["linehaul"], "Linehaul truck"),
}
LINEHAUL_DEPARTURES = {("RUH", "JED"): ("21:30", "02:30"), ("JED", "RUH"): ("21:00", "02:00"),
                       ("RUH", "DMM"): ("23:00", "04:00"), ("DMM", "RUH"): ("22:30", "03:30"),
                       ("JED", "DMM"): ("19:00",), ("DMM", "JED"): ("19:30",)}
# Average moving speeds (km/h) and mandated rest per driving block on long legs.
SPEED = {"LINEHAUL": 82., "FEEDER": 72., "FM_INTERCITY": 75., "URBAN": 30.}
REST_EVERY_HOURS, REST_MINUTES = 4.5, 40
FEEDER_TARGET_ARRIVAL = "05:45"


@dataclass
class Facility:
    id: str
    kind: str
    city: str
    name: str
    name_ar: str
    lat: float
    lng: float
    operator: str
    capacity_per_hour: int = 0
    shifts: tuple = ()
    devices: dict = field(default_factory=dict)  # role -> device id

    @property
    def region(self):
        return CITY[self.city].region


@dataclass
class Device:
    id: str
    kind: str                 # FACILITY_HANDHELD, SORTER_READER, SCALE, DRIVER_APP
    facility_id: str | None
    driver_id: str | None
    provider_id: str
    telemetry: str            # MDM_HEARTBEAT or NONE (legacy scanner without a management agent)
    heartbeat_seconds: int
    always_on: bool           # beats around the clock (docked) vs only while its facility/driver works
    hours: tuple = ("00:00", "24:00")


@dataclass
class Vehicle:
    id: str
    type_key: str
    ownership: str            # COMPANY, PROVIDER, CONTRACTOR, PRIVATE
    provider_id: str
    vehicle_class: str
    base: str                 # facility id
    plate_ref: str

    @property
    def payload_kg(self):
        return VEHICLE_TYPES[self.type_key][0]

    @property
    def volume_m3(self):
        return VEHICLE_TYPES[self.type_key][1]


@dataclass
class Driver:
    id: str
    provider_id: str
    employment: str           # EMPLOYEE, CONTRACTOR, INDEPENDENT
    base: str
    vehicle: str | None
    device: str
    role: str                 # LAST_MILE, COLLECTION, FEEDER, LINEHAUL
    off_weekday: int = 4      # Friday by default


@dataclass
class Lane:
    id: str
    kind: str                 # FIRST_MILE, LINEHAUL, FEEDER
    origin: str               # facility id (FIRST_MILE: the city's first stop)
    destination: str
    stops: tuple              # FIRST_MILE: origin facilities visited in order
    distance_km: float
    departures: tuple         # local HH:MM
    provider_id: str
    vehicle_type: str


@dataclass
class TripPlan:
    id: str
    lane: str
    kind: str
    origin: str
    destination: str
    stops: tuple
    scheduled_departure: object
    scheduled_arrival: object
    cutoff: object
    vehicle: str
    driver: str
    provider_id: str
    distance_km: float


def device_for_facility(facility_id):
    return "DEMO-DEV-HH-" + facility_id.removeprefix("DEMO-")


def device_for_driver(driver_id):
    return "DEMO-DEV-APP-" + driver_id.removeprefix("DEMO-")


class Network:
    def __init__(self, config: WorldConfig, draws: Draws):
        self.config, self.draws = config, draws
        self.organizations = {}   # id -> props
        self.facilities = {}      # id -> Facility
        self.devices = {}         # id -> Device
        self.vehicles = {}        # id -> Vehicle
        self.drivers = {}         # id -> Driver
        self.lanes = {}           # id -> Lane
        self.trips = {}           # id -> TripPlan
        self.depots_by_city = {}
        self.merchants = {}       # city -> [org ids]
        self.businesses = {}      # city -> [org ids]
        self.origin_facilities = {}  # city -> {"Branch": id, "OrganizationWarehouse": [...], "FulfillmentWarehouse": id}
        self.sort_of_region, self.hub_of_region = {}, {}
        self.depot_drivers = {}   # depot -> [driver ids]
        self.depot_spares = {}    # depot -> [vehicle ids]
        self._build()

    # ------------------------------------------------------------------ build
    def _facility(self, kind, prefix, city, suffix, name, name_ar, north_km, east_km, operator=SPL_OPERATOR, **kw):
        c = CITY[city]
        lat, lng = offset_point(c.lat, c.lng, north_km, east_km)
        fid = f"DEMO-{prefix}-{city}-{suffix}"
        self.facilities[fid] = Facility(fid, kind, city, name, name_ar, round(lat, 5), round(lng, 5), operator, **kw)
        return fid

    def _device(self, did, kind, *, facility=None, driver=None, provider="DEMO-PROV-SPL", telemetry="MDM_HEARTBEAT",
                seconds=1800, always_on=True, hours=("00:00", "24:00")):
        self.devices[did] = Device(did, kind, facility, driver, provider, telemetry, seconds, always_on, hours)
        if facility:
            self.facilities[facility].devices.setdefault(kind, did)
        return did

    def _build(self):
        self.organizations[SPL_OPERATOR] = {"name": "Synthetic SPL operations (fictional)", "organization_type": "postal_operator", "city": "RUH"}
        for c in CITIES:
            merchants = 3 if c.code == "RUH" else 2 if c.code in ("JED", "DMM") else 1 if c.code in ("KHB", "MAK", "MED") else 0
            self.merchants[c.code] = []
            for n in range(1, merchants + 1):
                org = f"DEMO-ORG-{c.code}-M{n}"
                self.organizations[org] = {"name": f"Synthetic merchant {c.code}-{n}", "organization_type": "merchant", "city": c.code}
                self.merchants[c.code].append(org)
            self.businesses[c.code] = []
            for n in range(1, 3):
                org = f"DEMO-ORG-{c.code}-B{n}"
                self.organizations[org] = {"name": f"Synthetic business {c.code}-{n}", "organization_type": "business", "city": c.code}
                self.businesses[c.code].append(org)
        for region, code in REGION_HUB.items():
            capacity = {"RUH": 90, "JED": 70, "DMM": 50}[code]
            sort = self._facility("SortingCenter", "SORT", code, "01", f"Synthetic {CITY[code].name} sorting center", f"مركز فرز {CITY[code].name_ar} (تجريبي)",
                                  -6.0, 4.0, capacity_per_hour=capacity,
                                  shifts=(("06:00", "14:00", 1.0), ("14:00", "22:00", 1.0), ("22:00", "06:00", .5)))
            hub = self._facility("Hub", "HUB", code, "01", f"Synthetic {CITY[code].name} regional hub", f"المركز الإقليمي {CITY[code].name_ar} (تجريبي)",
                                 -6.4, 4.6, capacity_per_hour=40, shifts=(("00:00", "24:00", 1.0),))
            self.sort_of_region[region], self.hub_of_region[region] = sort, hub
            self._device(device_for_facility(sort), "FACILITY_HANDHELD", facility=sort)
            self._device(f"DEMO-DEV-SR-SORT-{code}-01", "SORTER_READER", facility=sort, seconds=900)
            for n in (1, 2):
                self._device(f"DEMO-DEV-SCL-SORT-{code}-01-{n}", "SCALE", facility=sort, seconds=1800)
            self._device(device_for_facility(hub), "FACILITY_HANDHELD", facility=hub)
            fulfill = self._facility("FulfillmentWarehouse", "FULFILL", code, "01", f"Synthetic {CITY[code].name} fulfillment warehouse",
                                     f"مستودع تجهيز {CITY[code].name_ar} (تجريبي)", 8.0, -7.0)
            self._device(device_for_facility(fulfill), "FACILITY_HANDHELD", facility=fulfill, always_on=False, hours=("07:00", "23:30"))
        for c in CITIES:
            origin = {"OrganizationWarehouse": []}
            branch = self._facility("Branch", "BRANCH", c.code, "01", f"Synthetic {c.name} post branch", f"فرع بريد {c.name_ar} (تجريبي)", 1.2, -1.0)
            origin["Branch"] = branch
            # Small-city branch counters use legacy scanners without a device-management agent.
            telemetry = "MDM_HEARTBEAT" if c.code in ("RUH", "JED", "DMM", "KHB", "MAK", "MED") else "NONE"
            self._device(device_for_facility(branch), "FACILITY_HANDHELD", facility=branch, telemetry=telemetry, always_on=False, hours=("08:00", "22:00"))
            for n, org in enumerate(self.merchants[c.code], 1):
                wh = self._facility("OrganizationWarehouse", "ORGWH", c.code, f"{n:02d}", f"Synthetic merchant warehouse {c.code}-{n}",
                                    f"مستودع تاجر {c.code}-{n} (تجريبي)", -3.0 + n * 2.2, 5.5 - n, operator=org)
                origin["OrganizationWarehouse"].append(wh)
                self._device(device_for_facility(wh), "FACILITY_HANDHELD", facility=wh, always_on=False, hours=("07:00", "23:30"))
            if c.code in REGION_HUB.values():
                origin["FulfillmentWarehouse"] = f"DEMO-FULFILL-{c.code}-01"
            self.origin_facilities[c.code] = origin
            depots = (("N", 4.0, 1.0), ("S", -4.5, -1.5)) if c.code == "RUH" else (("01", 2.5, 2.0),)
            self.depots_by_city[c.code] = []
            size = "large" if c.code in ("RUH", "JED", "DMM") else "medium" if c.code in ("KHB", "MAK", "MED") else "small"
            for suffix, dn, de in depots:
                cap = {"large": 60, "medium": 40, "small": 25}[size]
                depot = self._facility("DeliveryDepot", "DEPOT", c.code, suffix, f"Synthetic {c.name} delivery depot {suffix}",
                                       f"مستودع توصيل {c.name_ar} {suffix} (تجريبي)", dn, de, capacity_per_hour=cap,
                                       shifts=(("05:00", "23:00", 1.0),))
                self.depots_by_city[c.code].append(depot)
                self._device(device_for_facility(depot), "FACILITY_HANDHELD", facility=depot)
                # A check scale for exception and audit re-weighing at the destination.
                self._device(f"DEMO-DEV-SCL-{depot.removeprefix('DEMO-')}", "SCALE", facility=depot, seconds=1800)
                self._depot_fleet(depot, size, c.code)
        self._lanes()
        self._schedule_trips()

    def _new_driver(self, did, provider, employment, base, vehicle, role, off_weekday):
        device = self._device(device_for_driver(did), "DRIVER_APP", driver=did, provider=provider, seconds=900, always_on=False)
        self.drivers[did] = Driver(did, provider, employment, base, vehicle, device, role, off_weekday)
        return did

    def _new_vehicle(self, vid, type_key, ownership, provider, base):
        vclass = {"LM-VAN": "VAN", "PRIVATE-CAR": "PRIVATE_CAR", "FM-VAN": "VAN", "FEEDER": "TRUCK", "LINEHAUL": "TRUCK"}[type_key]
        plate = "SYN-" + vid.removeprefix("DEMO-VEH-")
        self.vehicles[vid] = Vehicle(vid, type_key, ownership, provider, vclass, base, plate)
        return vid

    def _depot_fleet(self, depot, size, city):
        mix = {"large": ("EMPLOYEE", "EMPLOYEE", "CONTRACTOR", "INDEPENDENT", "INDEPENDENT"),
               "medium": ("EMPLOYEE", "CONTRACTOR", "INDEPENDENT"), "small": ("EMPLOYEE", "INDEPENDENT")}[size]
        code = depot.removeprefix("DEMO-DEPOT-")
        drivers = []
        for n, employment in enumerate(mix, 1):
            did = f"DEMO-DRV-{code}-{n:02d}"
            if employment == "INDEPENDENT":
                vid = self._new_vehicle(f"DEMO-VEH-PRIVATE-{code}-{n:02d}", "PRIVATE-CAR", "PRIVATE", "DEMO-PROV-INDEP-01", depot)
                provider = "DEMO-PROV-INDEP-01"
            elif employment == "CONTRACTOR":
                vid = self._new_vehicle(f"DEMO-VEH-{code}-{n:02d}", "LM-VAN", "CONTRACTOR", "DEMO-PROV-LMC-01", depot)
                provider = "DEMO-PROV-LMC-01"
            else:
                vid = self._new_vehicle(f"DEMO-VEH-{code}-{n:02d}", "LM-VAN", "COMPANY", "DEMO-PROV-SPL", depot)
                provider = "DEMO-PROV-SPL"
            off = self.draws.integer(0, 6, "offday", did)
            drivers.append(self._new_driver(did, provider, employment, depot, vid, "LAST_MILE", off))
        self.depot_drivers[depot] = drivers
        self.depot_spares[depot] = [self._new_vehicle(f"DEMO-VEH-{code}-SP", "LM-VAN", "COMPANY", "DEMO-PROV-SPL", depot)] if size != "small" else []

    def _lanes(self):
        for c in CITIES:
            region = c.region
            sort = self.facilities[self.sort_of_region[region]]
            stops = [self.origin_facilities[c.code]["Branch"], *self.origin_facilities[c.code]["OrganizationWarehouse"]]
            if self.origin_facilities[c.code].get("FulfillmentWarehouse"):
                stops.append(self.origin_facilities[c.code]["FulfillmentWarehouse"])
            first = self.facilities[stops[0]]
            distance = road_km(first.lat, first.lng, sort.lat, sort.lng, urban=c.code == sort.city)
            departures = ("13:30", "18:30") if distance < 120 else ("16:00",)
            self.lanes[f"DEMO-LANE-FM-{c.code}"] = Lane(f"DEMO-LANE-FM-{c.code}", "FIRST_MILE", stops[0], sort.id, tuple(stops),
                                                        round(distance, 1), departures, "DEMO-PROV-SPL", "FM-VAN")
        for (a, b), departures in LINEHAUL_DEPARTURES.items():
            ha, hb = self.facilities[self.hub_of_region[CITY[a].region]], self.facilities[self.hub_of_region[CITY[b].region]]
            provider = "DEMO-PROV-3PL-01" if "DMM" in (a, b) else "DEMO-PROV-SPL"
            lid = f"DEMO-LANE-LH-{a}-{b}"
            self.lanes[lid] = Lane(lid, "LINEHAUL", ha.id, hb.id, (), round(road_km(ha.lat, ha.lng, hb.lat, hb.lng), 1), departures, provider, "LINEHAUL")
        for region, hub_id in self.hub_of_region.items():
            hub = self.facilities[hub_id]
            for c in CITIES:
                if c.region != region:
                    continue
                for depot_id in self.depots_by_city[c.code]:
                    depot = self.facilities[depot_id]
                    same_city = depot.city == hub.city
                    distance = road_km(hub.lat, hub.lng, depot.lat, depot.lng, urban=same_city)
                    transit = travel_seconds(distance, "URBAN" if same_city else "FEEDER")
                    early = local_dt(self.config.day1, FEEDER_TARGET_ARRIVAL) - timedelta(seconds=transit + 900)
                    early_text = early.astimezone(depot_tz()).strftime("%H:%M")
                    departures = (early_text, "12:30") if transit <= 5 * 3600 else (early_text,)
                    provider = "DEMO-PROV-3PL-01" if region == "east" else "DEMO-PROV-SPL"
                    lid = f"DEMO-LANE-FD-{depot_id.removeprefix('DEMO-DEPOT-')}"
                    self.lanes[lid] = Lane(lid, "FEEDER", hub_id, depot_id, (), round(distance, 1), departures, provider, "FEEDER")

    # ------------------------------------------------------------------ schedule
    def lane_duration(self, lane: Lane) -> float:
        if lane.kind == "FIRST_MILE":
            return fm_seconds(self, lane)
        if lane.kind == "LINEHAUL":
            return travel_seconds(lane.distance_km, "LINEHAUL")
        same_city = self.facilities[lane.origin].city == self.facilities[lane.destination].city
        return travel_seconds(lane.distance_km, "URBAN" if same_city else "FEEDER")

    def _schedule_trips(self):
        """Planned trips for every lane departure; vehicles and drivers allocated by planned intervals."""
        config = self.config
        first = config.day1 - timedelta(days=1)
        horizon = config.days + config.horizon_days
        plans = []
        for lane in sorted(self.lanes.values(), key=lambda l: l.id):
            duration = self.lane_duration(lane)
            for offset in range(horizon + 1):
                day = first + timedelta(days=offset)
                for hhmm in lane.departures:
                    departure = local_dt(day, hhmm)
                    cutoff = departure - timedelta(minutes=60 if lane.kind == "LINEHAUL" else 45 if lane.kind == "FEEDER" else 0)
                    tid = f"DEMO-TRIP-{lane.id.removeprefix('DEMO-LANE-')}-{day.strftime('%m%d')}-{hhmm.replace(':', '')}"
                    plans.append((departure, tid, lane, departure + timedelta(seconds=duration), cutoff))
        plans.sort(key=lambda row: (row[0], row[1]))
        vehicle_free, driver_free = {}, {}   # id -> (available_at, location facility)
        pools = {}
        for departure, tid, lane, arrival, cutoff in plans:
            # Collection vans and feeder trucks are dedicated to their lane and return to base; linehaul trucks
            # of one carrier turn around at whichever hub they reached.
            key = lane.id if lane.kind != "LINEHAUL" else (lane.kind, lane.provider_id)
            pool = pools.setdefault(key, [])
            start_point = lane.origin
            # Dispatch rotates the vehicles and drivers that are free (seeded per trip), so a run is not tied to one
            # vehicle or driver from day to day.
            free = [v for v in pool if vehicle_free[v][0] <= departure - timedelta(minutes=30) and vehicle_free[v][1] == start_point]
            vehicle = self.draws.choice(free, "dispatch-vehicle", tid) if free else None
            if vehicle is None:
                n = sum(1 for v in self.vehicles.values() if v.type_key == lane.vehicle_type and v.provider_id == lane.provider_id) + 1
                tag = {"FIRST_MILE": "FM", "LINEHAUL": "LH", "FEEDER": "FD"}[lane.kind]
                owner = "PROVIDER" if lane.provider_id == "DEMO-PROV-3PL-01" else "COMPANY"
                vehicle = self._new_vehicle(f"DEMO-VEH-{tag}-{self.facilities[start_point].city}-{n:03d}", lane.vehicle_type, owner,
                                            lane.provider_id, start_point)
                pool.append(vehicle)
            driver_pool = pools.setdefault(("drivers", key), [])
            free = [d for d in driver_pool if driver_free[d][0] <= departure - timedelta(minutes=30) and driver_free[d][1] == start_point]
            driver = self.draws.choice(free, "dispatch-driver", tid) if free else None
            if driver is None:
                n = sum(1 for d in self.drivers.values() if d.role == lane.kind and d.provider_id == lane.provider_id) + 1
                tag = {"FIRST_MILE": "FM", "LINEHAUL": "LH", "FEEDER": "FD"}[lane.kind]
                employment = "CONTRACTOR" if lane.provider_id == "DEMO-PROV-3PL-01" else "EMPLOYEE"
                driver = self._new_driver(f"DEMO-DRV-{tag}-{self.facilities[start_point].city}-{n:03d}", lane.provider_id, employment,
                                          start_point, vehicle, lane.kind, 7)
                driver_pool.append(driver)
            rest = timedelta(hours=10) if (arrival - departure) > timedelta(hours=6) else timedelta(hours=1)
            if lane.kind == "LINEHAUL":
                back, arrival_back = lane.destination, arrival
            else:
                back, arrival_back = lane.origin, arrival + (arrival - departure)  # Round trip back to base.
            vehicle_free[vehicle] = (arrival_back + timedelta(minutes=45), back)
            driver_free[driver] = (arrival_back + rest, back)
            self.trips[tid] = TripPlan(tid, lane.id, lane.kind, lane.origin, lane.destination, lane.stops, departure, arrival, cutoff,
                                       vehicle, driver, lane.provider_id, lane.distance_km)

    # ------------------------------------------------------------------ queries
    def region_sort(self, city):
        return self.sort_of_region[CITY[city].region]

    def region_hub(self, city):
        return self.hub_of_region[CITY[city].region]

    def fm_lane(self, city):
        return self.lanes[f"DEMO-LANE-FM-{city}"]

    def feeder_lane(self, depot):
        return self.lanes[f"DEMO-LANE-FD-{depot.removeprefix('DEMO-DEPOT-')}"]

    def linehaul_lane(self, hub_a, hub_b):
        a, b = self.facilities[hub_a].city, self.facilities[hub_b].city
        return self.lanes.get(f"DEMO-LANE-LH-{a}-{b}")

    def trips_of_lane(self, lane_id):
        return sorted((t for t in self.trips.values() if t.lane == lane_id), key=lambda t: t.scheduled_departure)

    def next_trip(self, lane_id, ready, *, by_cutoff=True):
        """First planned trip whose cutoff (or departure) is at or after `ready`."""
        for trip in self._lane_index().get(lane_id, []):
            if (trip.cutoff if by_cutoff else trip.scheduled_departure) >= ready:
                return trip
        return None

    def latest_trip(self, lane_id, arrive_by):
        """Last planned trip that arrives at or before `arrive_by`."""
        best = None
        for trip in self._lane_index().get(lane_id, []):
            if trip.scheduled_arrival <= arrive_by:
                best = trip
        return best

    def _lane_index(self):
        if not hasattr(self, "_index"):
            self._index = {}
            for trip in sorted(self.trips.values(), key=lambda t: (t.scheduled_departure, t.id)):
                self._index.setdefault(trip.lane, []).append(trip)
        return self._index

    def fm_stop_time(self, trip: TripPlan, facility_id):
        """Planned arrival of a collection run at one of its origin stops."""
        t = trip.scheduled_departure
        previous = None
        for stop in trip.stops:
            if previous is not None:
                a, b = self.facilities[previous], self.facilities[stop]
                t = t + timedelta(seconds=travel_seconds(road_km(a.lat, a.lng, b.lat, b.lng, urban=True), "URBAN") + 600)
            if stop == facility_id:
                return t
            previous = stop
        return None


def depot_tz():
    from world.config import LOCAL
    return LOCAL


def travel_seconds(distance_km, mode):
    hours = distance_km / SPEED[mode]
    if mode in ("LINEHAUL", "FEEDER", "FM_INTERCITY"):
        hours += math.floor(hours / REST_EVERY_HOURS) * REST_MINUTES / 60
    return round(hours * 3600 + 600)  # plus 10 minutes to leave and enter the yards


def fm_seconds(network: Network, lane: Lane):
    """A collection run: urban hops between its stops (10 minutes loading at each), then the leg to the sort."""
    seconds = 0
    for a, b in zip(lane.stops, lane.stops[1:]):
        fa, fb = network.facilities[a], network.facilities[b]
        seconds += travel_seconds(road_km(fa.lat, fa.lng, fb.lat, fb.lng, urban=True), "URBAN") + 600
    last = network.facilities[lane.stops[-1]]
    sort = network.facilities[lane.destination]
    same_city = last.city == sort.city
    distance = road_km(last.lat, last.lng, sort.lat, sort.lng, urban=same_city)
    return seconds + 600 + travel_seconds(distance, "URBAN" if same_city else "FM_INTERCITY")
