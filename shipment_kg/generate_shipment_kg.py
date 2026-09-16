"""
Generates a synthetic shipment dataset (300 shipments) as a Cypher import
script for Neo4j, built from the real Saudi Arabia cities/districts JSON
data in the project root.

Usage:
    uv run shipment_kg/generate_shipment_kg.py
"""

import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
JSON_DIR = ROOT / "json"
OUT_FILE = Path(__file__).resolve().parent / "shipment_dataset.cypher"
CENTROID_CACHE = Path(__file__).resolve().parent / "district_centroids.cache.json"

TOTAL_SHIPMENTS = 300
COUNTS = {
    "success": 80,
    "address_conflict": 55,
    "recipient_unavailable": 55,
    "failed_attempt": 55,
    "hub_delay": 35,
    "escalation": 20,
}
assert sum(COUNTS.values()) == TOTAL_SHIPMENTS

FAILED_CATEGORIES = [
    "address_conflict",
    "recipient_unavailable",
    "failed_attempt",
    "hub_delay",
    "escalation",
]
TOTAL_FAILED = sum(COUNTS[c] for c in FAILED_CATEGORIES)  # 220
RESOLVED_COUNT = 150
LIVE_COUNT = TOTAL_FAILED - RESOLVED_COUNT  # 70

# Real-world-ish adjacency between the 13 Saudi regions (by region_id), used
# to keep routes geographically sensible.
REGION_ADJACENCY = {
    1: [4, 5, 8, 2, 11, 6],   # Riyadh
    2: [1, 3, 10, 6, 12],     # Makkah
    3: [2, 7, 8, 13],         # Madinah
    4: [1, 8, 13],            # Qassim
    5: [1, 8, 9],             # Eastern Province
    6: [1, 2, 10, 11, 12],    # Asir
    7: [3, 13, 9],            # Tabuk
    8: [3, 4, 5, 13, 9, 1],   # Hail
    9: [7, 8, 13, 5],         # Northern Borders
    10: [2, 6],               # Jazan
    11: [1, 6],               # Najran
    12: [2, 6],               # Bahah
    13: [3, 4, 7, 8, 9],      # Jawf
}

# Warehouse hubs used as shipment origins (major logistics cities).
WAREHOUSES = [
    {"id": "WH-RUH", "name": "مستودع الرياض المركزي", "city_id": 3, "region_id": 1},
    {"id": "WH-JED", "name": "مستودع جدة اللوجستي", "city_id": 18, "region_id": 2},
    {"id": "WH-DMM", "name": "مستودع الدمام الصناعي", "city_id": 13, "region_id": 5},
    {"id": "WH-MAD", "name": "مستودع المدينة المنورة", "city_id": 14, "region_id": 3},
    {"id": "WH-ABH", "name": "مستودع أبها الإقليمي", "city_id": 15, "region_id": 6},
    {"id": "WH-HAIL", "name": "مستودع حائل", "city_id": 10, "region_id": 8},
]
HUB_CITY_IDS = {w["city_id"] for w in WAREHOUSES}

COURIER_NAMES = [
    "سعود العتيبي", "فهد الشمري", "خالد القحطاني", "عبدالله الحربي", "ماجد الدوسري",
    "تركي الغامدي", "بندر العنزي", "ناصر المالكي", "يوسف الزهراني", "سلطان السبيعي",
    "عمر الرشيدي", "طلال المطيري", "زياد الحارثي", "راشد البلوي", "حمد العمري",
    "فيصل الجهني", "وليد الشهري", "عبدالعزيز اليامي", "إبراهيم القرني", "مشعل السلمي",
    "أحمد الزهيري", "سامي البقمي", "محمد الفيفي", "علي الشريف", "جابر الثقفي",
]

POLICIES = [
    {"id": "POL-STD", "name": "Standard", "sla_days": 3, "retry_limit": 2},
    {"id": "POL-EXP", "name": "Express", "sla_days": 1, "retry_limit": 1},
    {"id": "POL-ECO", "name": "Economy", "sla_days": 5, "retry_limit": 3},
]

RESOLUTION_ACTIONS = {
    "address_conflict": [
        "تأكيد العنوان الصحيح مع العميل وإعادة التوجيه",
        "تصحيح العنوان في النظام وإعادة الجدولة",
        "التواصل مع العميل لتحديد الموقع عبر الإحداثيات",
    ],
    "recipient_unavailable": [
        "إعادة جدولة التسليم في يوم آخر",
        "التنسيق مع العميل عبر الهاتف لتحديد وقت بديل",
        "تسليم لجهة بديلة بموافقة العميل",
    ],
    "failed_attempt": [
        "إعادة محاولة التسليم بعد تصحيح بيانات الشحنة",
        "استبدال الملصق وإعادة فحص الشحنة",
        "تحويل الشحنة إلى مندوب آخر لإعادة المحاولة",
    ],
    "hub_delay": [
        "إعادة توجيه الشحنة عبر مركز فرز بديل",
        "تسريع الشحنة عبر خط نقل مباشر",
        "إبلاغ العميل بالتأخير وتحديث موعد التسليم",
    ],
    "escalation": [
        "تصعيد الحالة للمشرف واتخاذ إجراء مركب لتصحيح العنوان وإعادة التسليم",
        "التنسيق بين فريق المستودع والمندوب لحل الحالة المركبة",
        "إعادة فتح الطلب ومعالجة جميع أسباب الفشل مجتمعاً",
    ],
}

FAILURE_DESCRIPTIONS = {
    "address_conflict": "تعارض في العنوان: نسخة العنوان المسجلة تختلف عن الموقع الفعلي للتسليم",
    "recipient_unavailable": "المستلم غير متواجد في العنوان وقت محاولة التسليم",
    "failed_attempt_wrong_gate": "محاولة تسليم فاشلة: بوابة دخول خاطئة",
    "failed_attempt_barcode_mismatch": "محاولة تسليم فاشلة: عدم تطابق الباركود مع الشحنة",
    "failed_attempt_weight_mismatch": "محاولة تسليم فاشلة: عدم تطابق وزن الشحنة مع السجل",
    "hub_delay": "تأخير في مركز الفرز أدى إلى تجاوز مدة اتفاقية مستوى الخدمة",
}

FAILED_ATTEMPT_SUBTYPES = [
    "failed_attempt_wrong_gate",
    "failed_attempt_barcode_mismatch",
    "failed_attempt_weight_mismatch",
]

CUSTOMER_FIRST_NAMES = [
    "محمد", "عبدالرحمن", "سارة", "نورة", "فهد", "منيرة", "عبدالله", "ريم",
    "خالد", "لمى", "أحمد", "هند", "سلمان", "عائشة", "يزيد", "أمل", "طارق", "دانة",
]
CUSTOMER_LAST_NAMES = [
    "العتيبي", "القحطاني", "الحربي", "الدوسري", "الغامدي", "العنزي", "المالكي",
    "الزهراني", "السبيعي", "الرشيدي", "المطيري", "الحارثي", "البلوي", "العمري",
]


def esc(value) -> str:
    """Escape a python value into a Cypher literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    s = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def props(d: dict) -> str:
    return "{" + ", ".join(f"{k}: {esc(v)}" for k, v in d.items()) + "}"


def load_json(name):
    with open(JSON_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def build_district_centroid_cache():
    if CENTROID_CACHE.exists():
        with open(CENTROID_CACHE, encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}

    print("Computing district centroids from districts.json (one-time, ~58MB)...")
    districts_full = load_json("districts.json")
    cache = {}
    for d in districts_full:
        ring = d["boundaries"][0]
        lat = sum(p[0] for p in ring) / len(ring)
        lng = sum(p[1] for p in ring) / len(ring)
        cache[d["district_id"]] = [round(lat, 6), round(lng, 6)]
    del districts_full

    with open(CENTROID_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    return cache


def main():
    regions = load_json("regions_lite.json")
    cities = load_json("cities.json")
    districts = load_json("districts_lite.json")
    centroids = build_district_centroid_cache()

    region_by_id = {r["region_id"]: r for r in regions}
    city_by_id = {c["city_id"]: c for c in cities}

    cities_by_region = {}
    for c in cities:
        if c.get("center"):
            cities_by_region.setdefault(c["region_id"], []).append(c)

    districts_by_city = {}
    for d in districts:
        districts_by_city.setdefault(d["city_id"], []).append(d)

    def pick_city_with_districts(region_id, exclude_city_id=None):
        candidates = [
            c for c in cities_by_region.get(region_id, [])
            if districts_by_city.get(c["city_id"]) and c["city_id"] != exclude_city_id
        ]
        if not candidates:
            return None
        return random.choice(candidates)

    def pick_destination_city(origin_region_id):
        roll = random.random()
        if roll < 0.55:
            region_id = origin_region_id
        elif roll < 0.90:
            region_id = random.choice(REGION_ADJACENCY[origin_region_id])
        else:
            # Hub route: long-haul between major logistics cities.
            hub_regions = [w["region_id"] for w in WAREHOUSES]
            region_id = random.choice(hub_regions)
        city = pick_city_with_districts(region_id)
        if city is None:
            # Fallback: any city that has districts, anywhere.
            city = random.choice([c for c in cities if districts_by_city.get(c["city_id"])])
        return city

    def district_coords(district, city):
        base = centroids.get(district["district_id"])
        if base is None:
            base = city["center"]
        jitter = lambda v: round(v + random.uniform(-0.0015, 0.0015), 6)
        return jitter(base[0]), jitter(base[1])

    def make_address(city, district, version=1):
        street = random.randint(1, 50)
        building = random.randint(1, 20)
        lat, lng = district_coords(district, city)
        full = f"مبنى {building}، شارع {street}، {district['name_ar']}، {city['name_ar']}"
        return {
            "address_id": f"ADR-{uuid.uuid4().hex[:10]}",
            "full_address": full,
            "district": district["name_ar"],
            "city": city["name_ar"],
            "lat": lat,
            "lng": lng,
            "version": version,
        }

    def make_customer(city, address_id):
        name = f"{random.choice(CUSTOMER_FIRST_NAMES)} {random.choice(CUSTOMER_LAST_NAMES)}"
        return {
            "customer_id": f"CUS-{uuid.uuid4().hex[:10]}",
            "name": name,
            "city": city["name_ar"],
            "address_id": address_id,
        }

    # ---- shipment plan: category assignment + resolved/live split ----
    plan = []
    for category, count in COUNTS.items():
        plan.extend([category] * count)
    random.shuffle(plan)

    failed_indices = [i for i, c in enumerate(plan) if c != "success"]
    random.shuffle(failed_indices)
    resolved_set = set(failed_indices[:RESOLVED_COUNT])
    live_set = set(failed_indices[RESOLVED_COUNT:])
    assert len(resolved_set) == RESOLVED_COUNT
    assert len(live_set) == LIVE_COUNT

    now = datetime(2026, 9, 1, 8, 0, 0)

    nodes = {
        "policies": [],
        "couriers": [],
        "addresses": [],
        "customers": [],
        "orders": [],
        "shipments": [],
        "events": [],
        "failure_reasons": [],
        "resolutions": [],
        "outcomes": [],
    }
    rels = {
        "has_shipment": [],
        "delivered_to": [],
        "has_event": [],
        "assigned_to": [],
        "placed_by": [],
        "lives_at": [],
        "governed_by": [],
        "caused_by": [],
        "resolves_with": [],
        "had_outcome": [],
    }

    for p in POLICIES:
        nodes["policies"].append(p)

    couriers = []
    for i, name in enumerate(COURIER_NAMES, start=1):
        courier = {"courier_id": f"COU-{i:03d}", "name": name}
        couriers.append(courier)
        nodes["couriers"].append(courier)

    def new_event(shipment_id, event_type, ts, extra=None):
        e = {
            "event_id": f"EVT-{uuid.uuid4().hex[:10]}",
            "shipment_id": shipment_id,
            "event_type": event_type,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if extra:
            e.update(extra)
        nodes["events"].append(e)
        rels["has_event"].append((shipment_id, e["event_id"]))
        return e

    def new_failure_reason(category, description, city, district, courier_name, ts, resolved, category_detail=None):
        fr = {
            "failure_id": f"FR-{uuid.uuid4().hex[:10]}",
            "category": category_detail or category,
            "description": description,
            "city": city,
            "district": district,
            "courier": courier_name,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if resolved:
            fr["case_summary"] = (
                f"{category_detail or category} | city={city} | district={district} "
                f"| courier={courier_name} | {description} | timestamp={fr['timestamp']}"
            )
        nodes["failure_reasons"].append(fr)
        return fr

    def new_resolution_chain(failure_id, category, base_ts):
        action = random.choice(RESOLUTION_ACTIONS[category])
        res_ts = base_ts + timedelta(hours=random.randint(2, 48))
        resolution = {
            "resolution_id": f"RES-{uuid.uuid4().hex[:10]}",
            "action": action,
            "timestamp": res_ts.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        nodes["resolutions"].append(resolution)
        rels["resolves_with"].append((failure_id, resolution["resolution_id"]))

        succeeded = random.random() < 0.85
        out_ts = res_ts + timedelta(hours=random.randint(1, 24))
        outcome = {
            "outcome_id": f"OUT-{uuid.uuid4().hex[:10]}",
            "success": succeeded,
            "notes": "تم حل الحالة بنجاح وتسليم الشحنة" if succeeded else "فشلت محاولة الحل، تم تصعيد الحالة",
            "timestamp": out_ts.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        nodes["outcomes"].append(outcome)
        rels["had_outcome"].append((resolution["resolution_id"], outcome["outcome_id"]))

    order_counter = 0
    shipment_counter = 0

    for idx, category in enumerate(plan):
        order_counter += 1
        shipment_counter += 1

        warehouse = random.choice(WAREHOUSES)
        origin_city = city_by_id[warehouse["city_id"]]
        dest_city = pick_destination_city(warehouse["region_id"])
        dest_district = random.choice(districts_by_city[dest_city["city_id"]])

        address_v1 = make_address(dest_city, dest_district, version=1)
        customer = make_customer(dest_city, address_v1["address_id"])
        courier = random.choice(couriers)
        policy = random.choice(POLICIES)

        order_id = f"ORD-{order_counter:04d}"
        shipment_id = f"SHP-{shipment_counter:04d}"
        tracking_id = f"SPL{100000000 + shipment_counter}"

        order = {
            "order_id": order_id,
            "origin_warehouse": warehouse["name"],
            "origin_warehouse_id": warehouse["id"],
            "destination_address": address_v1["full_address"],
        }
        nodes["orders"].append(order)

        shipment = {
            "shipment_id": shipment_id,
            "tracking_id": tracking_id,
            "order_id": order_id,
            "carrier": "SPL",
            "status": None,  # filled below
        }

        nodes["addresses"].append(address_v1)
        nodes["customers"].append(customer)

        rels["has_shipment"].append((order_id, shipment_id))
        rels["placed_by"].append((order_id, customer["customer_id"]))
        rels["lives_at"].append((customer["customer_id"], address_v1["address_id"]))
        rels["delivered_to"].append((shipment_id, address_v1["address_id"]))
        rels["assigned_to"].append((shipment_id, courier["courier_id"]))
        rels["governed_by"].append((shipment_id, policy["id"]))

        created_ts = now - timedelta(days=random.randint(1, 60), hours=random.randint(0, 23))
        t = created_ts
        new_event(shipment_id, "CREATED", t)
        t += timedelta(hours=random.randint(2, 6))
        new_event(shipment_id, "PICKED_UP", t)
        t += timedelta(hours=random.randint(4, 12))
        new_event(shipment_id, "IN_TRANSIT", t)

        is_failed = category != "success"
        resolved = idx in resolved_set

        if category == "success":
            t += timedelta(hours=random.randint(4, 10))
            new_event(shipment_id, "OUT_FOR_DELIVERY", t)
            t += timedelta(hours=random.randint(1, 6))
            new_event(shipment_id, "DELIVERED", t)
            shipment["status"] = "DELIVERED"

        elif category == "address_conflict":
            wrong_city = random.choice(
                [c for c in cities_by_region.get(dest_city["region_id"], []) if c["city_id"] != dest_city["city_id"]]
                or [dest_city]
            )
            wrong_districts = districts_by_city.get(wrong_city["city_id"]) or districts_by_city[dest_city["city_id"]]
            wrong_district = random.choice(wrong_districts)
            address_v2 = make_address(wrong_city, wrong_district, version=2)
            nodes["addresses"].append(address_v2)
            rels["delivered_to"].append((shipment_id, address_v2["address_id"]))

            t += timedelta(hours=random.randint(4, 10))
            new_event(shipment_id, "OUT_FOR_DELIVERY", t)
            t += timedelta(hours=random.randint(1, 6))
            attempt_evt = new_event(shipment_id, "DELIVERY_ATTEMPT", t)
            t += timedelta(hours=random.randint(1, 3))
            fail_evt = new_event(shipment_id, "FAILED", t)
            shipment["status"] = "FAILED"

            fr = new_failure_reason(
                "address_conflict", FAILURE_DESCRIPTIONS["address_conflict"],
                dest_city["name_ar"], dest_district["name_ar"], courier["name"], t, resolved,
            )
            rels["caused_by"].append((fail_evt["event_id"], fr["failure_id"]))
            if resolved:
                new_resolution_chain(fr["failure_id"], "address_conflict", t)

        elif category == "recipient_unavailable":
            t += timedelta(hours=random.randint(4, 10))
            new_event(shipment_id, "OUT_FOR_DELIVERY", t)
            t += timedelta(hours=random.randint(1, 6))
            attempt_evt = new_event(shipment_id, "DELIVERY_ATTEMPT", t)
            t += timedelta(hours=random.randint(1, 3))
            fail_evt = new_event(shipment_id, "FAILED", t)
            shipment["status"] = "FAILED"

            fr = new_failure_reason(
                "recipient_unavailable", FAILURE_DESCRIPTIONS["recipient_unavailable"],
                dest_city["name_ar"], dest_district["name_ar"], courier["name"], t, resolved,
            )
            rels["caused_by"].append((fail_evt["event_id"], fr["failure_id"]))
            if resolved:
                new_resolution_chain(fr["failure_id"], "recipient_unavailable", t)

        elif category == "failed_attempt":
            subtype = random.choice(FAILED_ATTEMPT_SUBTYPES)
            t += timedelta(hours=random.randint(4, 10))
            new_event(shipment_id, "OUT_FOR_DELIVERY", t)
            t += timedelta(hours=random.randint(1, 6))
            attempt_evt = new_event(shipment_id, "DELIVERY_ATTEMPT", t)
            t += timedelta(hours=random.randint(1, 3))
            fail_evt = new_event(shipment_id, "FAILED", t)
            shipment["status"] = "FAILED"

            fr = new_failure_reason(
                "failed_attempt", FAILURE_DESCRIPTIONS[subtype],
                dest_city["name_ar"], dest_district["name_ar"], courier["name"], t, resolved,
                category_detail=subtype,
            )
            rels["caused_by"].append((fail_evt["event_id"], fr["failure_id"]))
            if resolved:
                new_resolution_chain(fr["failure_id"], "failed_attempt", t)

        elif category == "hub_delay":
            t += timedelta(hours=random.randint(12, 36))
            delay_evt = new_event(shipment_id, "HUB_DELAY", t)
            t += timedelta(hours=random.randint(6, 18))
            new_event(shipment_id, "OUT_FOR_DELIVERY", t)
            t += timedelta(hours=random.randint(1, 6))
            fail_evt = new_event(shipment_id, "FAILED", t)
            shipment["status"] = "FAILED"

            fr = new_failure_reason(
                "hub_delay", FAILURE_DESCRIPTIONS["hub_delay"],
                dest_city["name_ar"], dest_district["name_ar"], courier["name"], t, resolved,
            )
            rels["caused_by"].append((fail_evt["event_id"], fr["failure_id"]))
            if resolved:
                new_resolution_chain(fr["failure_id"], "hub_delay", t)

        else:  # escalation: chain of 2-3 combined failure types
            sub_categories = random.sample(
                ["address_conflict", "recipient_unavailable", "failed_attempt", "hub_delay"], k=2
            )
            t += timedelta(hours=random.randint(4, 10))
            new_event(shipment_id, "OUT_FOR_DELIVERY", t)

            failure_ids = []
            for sub_cat in sub_categories:
                t += timedelta(hours=random.randint(1, 6))
                attempt_evt = new_event(shipment_id, "DELIVERY_ATTEMPT", t)
                t += timedelta(hours=random.randint(1, 3))
                sub_fail_evt = new_event(shipment_id, "FAILED", t)

                if sub_cat == "failed_attempt":
                    detail = random.choice(FAILED_ATTEMPT_SUBTYPES)
                    desc = FAILURE_DESCRIPTIONS[detail]
                else:
                    detail = None
                    desc = FAILURE_DESCRIPTIONS[sub_cat]

                fr = new_failure_reason(
                    "escalation", desc, dest_city["name_ar"], dest_district["name_ar"],
                    courier["name"], t, resolved, category_detail=f"escalation:{detail or sub_cat}",
                )
                rels["caused_by"].append((sub_fail_evt["event_id"], fr["failure_id"]))
                failure_ids.append(fr["failure_id"])

            t += timedelta(hours=random.randint(6, 24))
            final_evt = new_event(shipment_id, "FAILED", t)
            shipment["status"] = "FAILED"
            if resolved:
                for fid in failure_ids:
                    new_resolution_chain(fid, "escalation", t)

        nodes["shipments"].append(shipment)

    write_cypher(nodes, rels)
    print(f"Wrote {OUT_FILE}")
    print(f"Shipments: {len(nodes['shipments'])} | Events: {len(nodes['events'])} "
          f"| FailureReasons: {len(nodes['failure_reasons'])} | Resolutions: {len(nodes['resolutions'])} "
          f"| Outcomes: {len(nodes['outcomes'])}")


def write_cypher(nodes, rels):
    lines = []

    def section(title):
        lines.append("")
        lines.append("// " + "=" * 70)
        lines.append(f"// {title}")
        lines.append("// " + "=" * 70)

    section("NODES: Policy")
    for p in nodes["policies"]:
        lines.append(
            f"CREATE (:Policy {props({'policy_id': p['id'], 'name': p['name'], 'sla_days': p['sla_days'], 'retry_limit': p['retry_limit']})});"
        )

    section("NODES: Courier")
    for c in nodes["couriers"]:
        lines.append(f"CREATE (:Courier {props(c)});")

    section("NODES: Address")
    for a in nodes["addresses"]:
        lines.append(f"CREATE (:Address {props(a)});")

    section("NODES: Customer")
    for c in nodes["customers"]:
        lines.append(f"CREATE (:Customer {props(c)});")

    section("NODES: Order")
    for o in nodes["orders"]:
        lines.append(
            f"CREATE (:Order {props({'order_id': o['order_id'], 'origin_warehouse': o['origin_warehouse'], 'origin_warehouse_id': o['origin_warehouse_id'], 'destination_address': o['destination_address']})});"
        )

    section("NODES: Shipment")
    for s in nodes["shipments"]:
        lines.append(f"CREATE (:Shipment {props(s)});")

    section("NODES: Event")
    for e in nodes["events"]:
        e_props = {k: v for k, v in e.items() if k != "shipment_id"}
        lines.append(f"CREATE (:Event {props(e_props)});")

    section("NODES: FailureReason")
    for fr in nodes["failure_reasons"]:
        lines.append(f"CREATE (:FailureReason {props(fr)});")

    section("NODES: Resolution")
    for r in nodes["resolutions"]:
        lines.append(f"CREATE (:Resolution {props(r)});")

    section("NODES: Outcome")
    for o in nodes["outcomes"]:
        lines.append(f"CREATE (:Outcome {props(o)});")

    section("CONSTRAINTS / INDEXES (recommended for MATCH performance below)")
    index_specs = [
        ("Order", "order_id"), ("Shipment", "shipment_id"), ("Customer", "customer_id"),
        ("Address", "address_id"), ("Courier", "courier_id"), ("Policy", "policy_id"),
        ("Event", "event_id"), ("FailureReason", "failure_id"), ("Resolution", "resolution_id"),
        ("Outcome", "outcome_id"),
    ]
    for label, prop in index_specs:
        lines.append(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop});")

    section("RELATIONSHIPS: (Order)-[:HAS_SHIPMENT]->(Shipment)")
    for order_id, shipment_id in rels["has_shipment"]:
        lines.append(
            f"MATCH (a:Order {{order_id: {esc(order_id)}}}), (b:Shipment {{shipment_id: {esc(shipment_id)}}}) CREATE (a)-[:HAS_SHIPMENT]->(b);"
        )

    section("RELATIONSHIPS: (Shipment)-[:DELIVERED_TO]->(Address)")
    for shipment_id, address_id in rels["delivered_to"]:
        lines.append(
            f"MATCH (a:Shipment {{shipment_id: {esc(shipment_id)}}}), (b:Address {{address_id: {esc(address_id)}}}) CREATE (a)-[:DELIVERED_TO]->(b);"
        )

    section("RELATIONSHIPS: (Shipment)-[:HAS_EVENT]->(Event)")
    for shipment_id, event_id in rels["has_event"]:
        lines.append(
            f"MATCH (a:Shipment {{shipment_id: {esc(shipment_id)}}}), (b:Event {{event_id: {esc(event_id)}}}) CREATE (a)-[:HAS_EVENT]->(b);"
        )

    section("RELATIONSHIPS: (Shipment)-[:ASSIGNED_TO]->(Courier)")
    for shipment_id, courier_id in rels["assigned_to"]:
        lines.append(
            f"MATCH (a:Shipment {{shipment_id: {esc(shipment_id)}}}), (b:Courier {{courier_id: {esc(courier_id)}}}) CREATE (a)-[:ASSIGNED_TO]->(b);"
        )

    section("RELATIONSHIPS: (Order)-[:PLACED_BY]->(Customer)")
    for order_id, customer_id in rels["placed_by"]:
        lines.append(
            f"MATCH (a:Order {{order_id: {esc(order_id)}}}), (b:Customer {{customer_id: {esc(customer_id)}}}) CREATE (a)-[:PLACED_BY]->(b);"
        )

    section("RELATIONSHIPS: (Customer)-[:LIVES_AT]->(Address)")
    for customer_id, address_id in rels["lives_at"]:
        lines.append(
            f"MATCH (a:Customer {{customer_id: {esc(customer_id)}}}), (b:Address {{address_id: {esc(address_id)}}}) CREATE (a)-[:LIVES_AT]->(b);"
        )

    section("RELATIONSHIPS: (Shipment)-[:GOVERNED_BY]->(Policy)")
    for shipment_id, policy_id in rels["governed_by"]:
        lines.append(
            f"MATCH (a:Shipment {{shipment_id: {esc(shipment_id)}}}), (b:Policy {{policy_id: {esc(policy_id)}}}) CREATE (a)-[:GOVERNED_BY]->(b);"
        )

    section("RELATIONSHIPS: (Event)-[:CAUSED_BY]->(FailureReason)")
    for event_id, failure_id in rels["caused_by"]:
        lines.append(
            f"MATCH (a:Event {{event_id: {esc(event_id)}}}), (b:FailureReason {{failure_id: {esc(failure_id)}}}) CREATE (a)-[:CAUSED_BY]->(b);"
        )

    section("RELATIONSHIPS: (FailureReason)-[:RESOLVES_WITH]->(Resolution)")
    for failure_id, resolution_id in rels["resolves_with"]:
        lines.append(
            f"MATCH (a:FailureReason {{failure_id: {esc(failure_id)}}}), (b:Resolution {{resolution_id: {esc(resolution_id)}}}) CREATE (a)-[:RESOLVES_WITH]->(b);"
        )

    section("RELATIONSHIPS: (Resolution)-[:HAD_OUTCOME]->(Outcome)")
    for resolution_id, outcome_id in rels["had_outcome"]:
        lines.append(
            f"MATCH (a:Resolution {{resolution_id: {esc(resolution_id)}}}), (b:Outcome {{outcome_id: {esc(outcome_id)}}}) CREATE (a)-[:HAD_OUTCOME]->(b);"
        )

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
