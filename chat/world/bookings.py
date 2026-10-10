"""Shipments as booked: flows, services, parcels, recipients and the journey plan stamped at booking.

The plan is computed from the published schedule at booking time only: the nominal (earliest) journey and
the latest journey that still meets the service promise. ExpectedMilestone windows run from just before
the nominal time to the latest feasible time plus the service tolerance, so a parcel that misses one
connection but still makes its promise is late against the nominal plan without breaching a milestone.
"""
from dataclasses import dataclass, field
from datetime import timedelta
import math

from world.config import WorldConfig, is_friday, local_date, local_dt
from world.geo import CITIES, CITY, districts, offset_point
from world.network import Network
from world.rand import Draws

FLOWS = (("B2C", .60), ("C2C", .25), ("B2B", .15))
WEEKDAY_DEMAND = {5: 1.0, 6: 1.15, 0: 1.10, 1: 1.05, 2: 1.0, 3: .90, 4: .35}  # Sat..Fri (weekday(): Mon=0)
SERVICE_TOLERANCE = {"EXPRESS": 1800, "STANDARD": 3600}
# Intermediate milestones also absorb ordinary handling slips (a truck waiting for a dock, a long unload).
INTERMEDIATE_SLACK = 3600
GATE_SETS = (("Gate 1", "Gate 2", "Gate 3"), ("North Gate", "South Gate"), ("Gate A", "Gate B", "Gate C", "Gate D"),
             ("Main Gate", "Service Gate"), ("Gate 4", "Gate 5", "Gate 6"))
STREETS = ("King Fahd Road", "Prince Sultan Street", "Al Madinah Road", "Omar Bin Abdulaziz Street", "Al Imam Saud Road",
           "Prince Mohammed Street", "Al Khaleej Road", "Abu Bakr Street", "Al Hijrah Street", "Street 14", "Street 27",
           "Street 9", "Al Andalus Street", "Ibn Khaldun Street")


@dataclass
class Parcel:
    pid: str
    sid: str
    number: int
    barcode: str
    true_kg: float
    declared_kg: float
    dims: tuple
    volume: float
    handling: str
    label_barcode: str = ""   # what is physically printed on the parcel (normally the manifest barcode)


@dataclass
class Shipment:
    sid: str
    index: int
    day: int
    split: str
    flow: str
    service: str
    booked_at: object
    handover_at: object
    origin_city: str
    dest_city: str
    origin_facility: str
    depot: str
    sender_id: str
    sender_kind: str           # Customer / Organization
    recipient_id: str
    recipient_kind: str
    tracking: str
    parcels: list
    recipient: dict            # profile: availability, contact, route, preference, home point, address fields
    otp_required: bool
    plan: dict = field(default_factory=dict)
    promise_at: object = None

    @property
    def bulky(self):
        return any(p.handling == "bulky" for p in self.parcels)

    @property
    def inter_region(self):
        return CITY[self.origin_city].region != CITY[self.dest_city].region


def s10(serial: int, prefix: str) -> str:
    digits = f"{serial:08d}"
    total = sum(int(d) * w for d, w in zip(digits, (8, 6, 4, 2, 3, 5, 9, 7)))
    check = 11 - total % 11
    check = 0 if check == 10 else 5 if check == 11 else check
    return f"{prefix}{digits}{check}SA"


def _counts_per_day(config: WorldConfig):
    weights = [WEEKDAY_DEMAND[config.booking_date(d).weekday()] for d in range(1, config.days + 1)]
    raw = [config.total * w / sum(weights) for w in weights]
    counts = [math.floor(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: (-(raw[i] - counts[i]), i))[: config.total - sum(counts)]:
        counts[i] += 1
    return counts


def generate_bookings(config: WorldConfig, network: Network, draws: Draws) -> dict:
    counts = _counts_per_day(config)
    permutation = draws.shuffled(range(1, config.total + 1), "shipment-ids")
    used_serials = set()
    shipments, index = {}, 0
    origin_cities = [(c.code, c.origin_weight) for c in CITIES]
    dest_cities = [(c.code, c.destination_weight) for c in CITIES]
    merchant_cities = [(c.code, c.origin_weight) for c in CITIES if network.merchants[c.code]]
    for day, count in enumerate(counts, 1):
        for n in range(count):
            key = ("booking", day, n)
            number = permutation[index]
            index += 1
            sid = f"DEMO-SHP-{number:06d}"
            flow = draws.weighted(FLOWS, *key, "flow")
            origin = draws.weighted(origin_cities if flow == "C2C" else merchant_cities, *key, "origin")
            dest = draws.weighted(dest_cities, *key, "dest")
            service = "EXPRESS" if draws.chance({"B2C": .30, "C2C": .20, "B2B": .10}[flow], *key, "service") else "STANDARD"
            facilities = network.origin_facilities[origin]
            if flow == "C2C":
                origin_facility = facilities["Branch"]
                sender_id, sender_kind = f"{sid}-SENDER", "Customer"
            else:
                use_fulfillment = flow == "B2C" and facilities.get("FulfillmentWarehouse") and draws.chance(.45, *key, "ff")
                if use_fulfillment:
                    origin_facility = facilities["FulfillmentWarehouse"]
                    sender_id = draws.choice(network.merchants[origin], *key, "seller")
                else:
                    warehouses = facilities["OrganizationWarehouse"]
                    slot = draws.integer(0, len(warehouses) - 1, *key, "wh")
                    origin_facility = warehouses[slot]
                    sender_id = network.merchants[origin][slot]
                sender_kind = "Organization"
            if flow == "B2B":
                recipient_id, recipient_kind = draws.choice(network.businesses[dest], *key, "business"), "Organization"
            else:
                recipient_id, recipient_kind = f"{sid}-RECIPIENT", "Customer"
            depots = network.depots_by_city[dest]
            booked_hour = draws.weighted(((h, w) for h, w in ((7, .5), (8, 1), (9, 1.4), (10, 1.6), (11, 1.6), (12, 1.4), (13, 1.2),
                                                                (14, 1.1), (15, 1.0), (16, 1.0), (17, .9), (18, .8), (19, .7), (20, .5), (21, .3))),
                                         *key, "hour")
            if flow == "C2C":
                booked_hour = max(booked_hour, 9)
            booked_at = local_dt(config.booking_date(day), f"{booked_hour:02d}:00") + timedelta(minutes=draws.integer(0, 59, *key, "minute"),
                                                                                                    seconds=draws.integer(0, 59, *key, "sec"))
            prep = draws.uniform(60, 600, *key, "prep") if flow == "C2C" else draws.lognormal(5400, .45, *key, "prep")
            handover_at = (booked_at + timedelta(seconds=round(prep))).replace(microsecond=0)
            profile = _recipient(network, draws, sid, dest, flow, key)
            depot = depots[0] if len(depots) == 1 else min(depots, key=lambda d: _dist(network.facilities[d], profile["home"]))
            parcels = []
            count_parcels = (draws.integer(2, 5, *key, "count") if flow == "B2B" else
                             draws.weighted(((1, .85), (2, .12), (3, .03)), *key, "count") if flow == "B2C" else
                             draws.weighted(((1, .95), (2, .05)), *key, "count"))
            bulky = flow == "B2B" and draws.chance(.15, *key, "bulky")
            for p in range(1, count_parcels + 1):
                pkey = (*key, "parcel", p)
                serial = draws.integer(10_000_000, 99_999_999, *pkey, "serial")
                bump = 0
                while serial in used_serials:
                    bump += 1
                    serial = draws.integer(10_000_000, 99_999_999, *pkey, "serial", bump)
                used_serials.add(serial)
                if bulky and p == 1:
                    true_kg = round(draws.uniform(32, 85, *pkey, "kg"), 2)
                else:
                    median, sigma, low, high = {"C2C": (1.8, .8, .2, 25.), "B2C": (1.2, .9, .1, 20.), "B2B": (6., .7, 1., 28.)}[flow]
                    true_kg = round(min(high, max(low, draws.lognormal(median, sigma, *pkey, "kg"))), 2)
                handling = "bulky" if true_kg > 30 else "standard"
                density = draws.uniform(140, 320, *pkey, "density")
                volume_target = max(.002, true_kg / density)
                ratios = (draws.uniform(1.2, 1.8, *pkey, "l"), 1.0, draws.uniform(.45, .9, *pkey, "h"))
                base = (volume_target / math.prod(ratios)) ** (1 / 3)
                dims = tuple(round(max(.05, base * r), 3) for r in ratios)
                volume = round(dims[0] * dims[1] * dims[2], 9)
                declared = round(true_kg * draws.normal(1.0, .025, *pkey, "declared"), 2)
                barcode = s10(serial, "RB" if flow == "C2C" else "EE" if service == "EXPRESS" else "CP")
                parcels.append(Parcel(f"{sid}-PKG-{p:02d}", sid, p, barcode, true_kg, max(.05, declared), dims, volume, handling, barcode))
            tracking = f"SYN{draws.integer(10**9, 10**10 - 1, *key, 'tracking'):010d}"
            otp = flow != "B2B" and profile["preference"] != "LEAVE_AT_DOOR" and draws.chance(.85, *key, "otp")
            shipments[sid] = Shipment(sid, number, day, config.split_of_day(day), flow, service, booked_at, handover_at, origin, dest,
                                      origin_facility, depot, sender_id, sender_kind, recipient_id, recipient_kind, tracking, parcels,
                                      profile, otp)
    for shipment in shipments.values():
        plan_journey(config, network, shipment)
    return shipments


def _dist(facility, point):
    return (facility.lat - point[0]) ** 2 + ((facility.lng - point[1]) * math.cos(math.radians(point[0]))) ** 2


def _recipient(network, draws, sid, city, flow, key):
    names = districts(city)
    district = draws.choice(names, *key, "district")
    lat, lng = offset_point(district[2], district[3], draws.normal(0, 1.1, *key, "dn"), draws.normal(0, 1.1, *key, "de"))
    compound = draws.chance(.40 if flow == "B2B" else .18, *key, "compound")
    gates = draws.choice(GATE_SETS, *key, "gates") if compound else ()
    gate = draws.choice(gates, *key, "gate") if gates else None
    if flow == "B2B":
        availability, preference = "BUSINESS_HOURS", draws.weighted((("STANDARD", .7), ("RECEPTION", .3)), *key, "pref")
    else:
        availability = draws.weighted((("HOME", .55), ("EVENINGS", .25), ("IRREGULAR", .20)), *key, "avail")
        preference = draws.weighted((("STANDARD", .80), ("LEAVE_AT_DOOR", .07), ("RECEPTION", .08 if compound else 0),
                                     ("AUTHORIZED_NEIGHBOUR", .03)), *key, "pref")
    return {"district": district[0], "district_ar": district[1], "home": (round(lat, 6), round(lng, 6)),
            "geocode_accuracy_m": round(draws.uniform(8, 30, *key, "acc"), 1),
            "building": draws.integer(1000, 9999, *key, "building"), "street": draws.choice(STREETS, *key, "street"),
            "unit": draws.integer(1, 40, *key, "unit") if flow != "B2B" else None,
            "gates": list(gates), "gate": gate, "pin_gate": gate,
            "availability": availability, "contact": draws.weighted((("CALL", .5), ("SMS", .3), ("WHATSAPP", .2)), *key, "contact"),
            "carrier_route": draws.weighted((("OP-1", .45), ("OP-2", .35), ("OP-3", .20)), *key, "route"),
            "preference": preference, "registered_point": (round(lat, 6), round(lng, 6))}


# ---------------------------------------------------------------------- journey plan
def delivery_day_for(receipt_at, config):
    """First non-Friday local date whose route planning (07:15) happens after the depot receipt."""
    day = local_date(receipt_at)
    if receipt_at > local_dt(day, "07:15"):
        day += timedelta(days=1)
    while is_friday(day):
        day += timedelta(days=1)
    return day


def plan_journey(config: WorldConfig, network: Network, shipment: Shipment):
    sort, hub = network.region_sort(shipment.origin_city), network.region_hub(shipment.origin_city)
    d_hub = network.region_hub(shipment.dest_city)
    depot = shipment.depot
    fm_lane = network.fm_lane(shipment.origin_city)
    inter = hub != d_hub
    nominal = {}
    fm = _next_fm(network, fm_lane, shipment.origin_facility, shipment.handover_at + timedelta(minutes=15))
    nominal["origin_receipt"] = shipment.handover_at
    nominal["sort_receipt"] = fm.scheduled_arrival + timedelta(minutes=45)
    ready = nominal["sort_receipt"] + timedelta(minutes=30)
    if inter:
        lh = network.next_trip(network.linehaul_lane(hub, d_hub).id, ready)
        nominal["hub_load"] = lh.scheduled_departure - timedelta(minutes=15)
        nominal["dhub_receipt"] = lh.scheduled_arrival + timedelta(minutes=30)
        feeder = network.next_trip(network.feeder_lane(depot).id, nominal["dhub_receipt"] + timedelta(minutes=15))
    else:
        feeder = network.next_trip(network.feeder_lane(depot).id, ready)
    nominal["depot_receipt"] = feeder.scheduled_arrival + timedelta(minutes=30)
    day = delivery_day_for(nominal["depot_receipt"], config)
    nominal["lm_load"] = local_dt(day, "08:30")
    nominal["delivered"] = local_dt(day, "13:00")
    promise_day = day
    if shipment.service == "STANDARD":
        promise_day += timedelta(days=1)
        while is_friday(promise_day):
            promise_day += timedelta(days=1)
    promise = local_dt(promise_day, config.session_end)
    # Latest feasible journey for the promise, walking the published schedule backwards.
    latest = {"delivered": promise, "lm_load": local_dt(promise_day, "10:00"), "depot_receipt": local_dt(promise_day, "07:15")}
    feeder_l = network.latest_trip(network.feeder_lane(depot).id, latest["depot_receipt"] - timedelta(minutes=30)) or feeder
    if inter:
        latest["dhub_receipt"] = feeder_l.cutoff - timedelta(minutes=15)
        lh_l = network.latest_trip(network.linehaul_lane(hub, d_hub).id, latest["dhub_receipt"] - timedelta(minutes=30)) or lh
        latest["hub_load"] = lh_l.scheduled_departure
        out_cutoff = lh_l.cutoff
    else:
        out_cutoff = feeder_l.cutoff
    latest["sort_receipt"] = out_cutoff - timedelta(minutes=30)
    fm_l = network.latest_trip(fm_lane.id, latest["sort_receipt"] - timedelta(minutes=45))
    stop = network.fm_stop_time(fm_l, shipment.origin_facility) if fm_l else None
    latest["origin_receipt"] = (stop - timedelta(minutes=15)) if stop else nominal["origin_receipt"] + timedelta(hours=2)
    for key, value in nominal.items():
        latest[key] = max(latest.get(key, value), value)
    shipment.plan = {"nominal": nominal, "latest": latest, "inter_region": inter, "sort": sort, "hub": hub, "d_hub": d_hub,
                     "delivery_day": day.isoformat(), "promise_day": promise_day.isoformat()}
    shipment.promise_at = promise


def _next_fm(network, lane, facility, ready):
    for trip in network._lane_index().get(lane.id, []):
        stop = network.fm_stop_time(trip, facility)
        if stop is not None and stop >= ready:
            return trip
    raise ValueError("No collection run after booking within the schedule horizon")


def milestones(shipment: Shipment):
    """(sequence, predicate, location, nominal, latest_at, key) per package, in journey order.

    latest_at is the latest feasible time for the promise plus the service tolerance (and, for milestones
    before the final delivery, an hour of handling slack); for DELIVERED it is the promise itself."""
    plan = shipment.plan
    rows = [("RECEIVED", shipment.origin_facility, "origin_receipt"), ("RECEIVED", plan["sort"], "sort_receipt")]
    if plan["inter_region"]:
        rows += [("LOADED", plan["hub"], "hub_load"), ("RECEIVED", plan["d_hub"], "dhub_receipt")]
    rows += [("RECEIVED", shipment.depot, "depot_receipt"), ("LOADED", shipment.depot, "lm_load"), ("DELIVERED", shipment.recipient_id, "delivered")]
    out = []
    for seq, (predicate, location, key) in enumerate(rows, 1):
        latest = plan["latest"][key]
        if key != "delivered":
            latest = latest + timedelta(seconds=SERVICE_TOLERANCE[shipment.service] + INTERMEDIATE_SLACK)
        out.append((seq, predicate, location, plan["nominal"][key], latest, key))
    return out
