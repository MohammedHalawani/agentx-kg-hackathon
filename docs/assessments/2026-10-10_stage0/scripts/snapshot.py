"""What was visible at each final case's investigation snapshot (opened_at), in-memory, read-only."""
import json, sys
from collections import Counter
from datetime import timedelta
sys.path.insert(0, ".")
from dataset_v2.network import generate_live, live_config
from dataset_v2.feed import split_feed, feed_item, Reference, FEED_KINDS
from dataset_v2.derive import assess_shipment, EvidenceIndex
from dataset_v2.contracts import instant, iso

S = sys.argv[1]
world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
imported, items = split_feed(world, truth)
start = instant(min(i["deliver_at"] for i in items if i["origin"] == "PROVIDER")) - timedelta(seconds=1)
deliver = {}
for i in items:
    deliver.setdefault(i["source_event_id"], i["deliver_at"])
def tick_ceil(t):
    k = -(-(t - start).total_seconds() // 3600)
    return start + timedelta(hours=k)
for nid, d in deliver.items():
    world.nodes[nid].properties["recorded_at"] = iso(tick_ceil(instant(d)))
index = EvidenceIndex(world)
cases = json.load(open("C:/Projects/demo/docs/evals/2026-10-09_s5/final/pipeline.json"))["cases"]
rep = json.load(open(S + "/replica.json"))["shipments"]

def visible(sid, t):
    cutoff = instant(t)
    out = []
    for kind, nodes in index.groups[sid].items():
        for n in nodes:
            p = n.properties
            if kind in ("ScanEvent", "CustodyEvent", "DeliveryAttempt", "ContactAttempt", "DeliveryProof", "RecipientReport",
                        "DepotReconciliation", "TrafficObservation", "GPSObservation", "StatusEvent", "Manifest", "HandoffEvidence",
                        "AuthenticationEvidence", "PhotoEvidence"):
                if p.get("recorded_at") and instant(p["recorded_at"]) <= cutoff and instant(p.get("occurred_at") or p["recorded_at"]) <= cutoff:
                    out.append(n)
    return out

def beats(device, t):
    cutoff = instant(t)
    hb = sorted(instant(n.properties["occurred_at"]) for n in world.of_kind("DeviceHeartbeat")
                if n.properties.get("device_id") == device and instant(n.properties["recorded_at"]) <= cutoff
                and instant(n.properties["occurred_at"]) > cutoff - timedelta(hours=24))
    return hb

report = {}
for c in sorted(cases, key=lambda c: (c["shipment_id"], c["opened_at"])):
    sid, t = c["shipment_id"], c["opened_at"][:19] + "+00:00"
    row = truth[sid]
    vis = visible(sid, t)
    kinds = Counter(n.kind for n in vis)
    a = assess_shipment(world, sid, t, _index=index, detection_allowance_seconds=900)
    a0 = assess_shipment(world, sid, t, _index=index, detection_allowance_seconds=0)
    acc = set(row["acceptable_causes"])
    first_acc_code = next((tt for tt, codes, _ in rep[sid]["timeline"] if set(codes) & acc), None)
    info = {"recipe": row["recipe"], "acceptable": sorted(acc), "agent": c["primary_cause"], "snapshot": t,
            "rule_codes_monitor": a["supported_codes"], "rule_codes_factcheck": a0["supported_codes"],
            "first_time_acceptable_rule_code": first_acc_code,
            "hours_until_acceptable_rule_code": (round((instant(first_acc_code) - instant(t)).total_seconds() / 3600, 1) if first_acc_code else None),
            "visible_kinds": dict(kinds)}
    phys = row["physical"]
    dev = phys.get("device_id")
    if dev:
        hb = beats(dev, t)
        last = hb[-1] if hb else None
        info["outage_device"] = dev
        info["offline_from"] = phys.get("offline_from")
        info["reconnect"] = phys.get("natural_reconnect_at")
        info["device_hours_since_last_beat_at_snapshot"] = round((instant(t) - last).total_seconds() / 3600, 2) if last else None
        info["device_silent_at_snapshot(>=1.5h)"] = bool(last and (instant(t) - last) >= timedelta(minutes=90))
        info["snapshot_before_reconnect"] = instant(t) < instant(phys["natural_reconnect_at"])
    # last-mile vehicle ownership and attempts
    va = [n for n in index.groups[sid].get("VehicleAssignment", []) if n.properties.get("mode") == "last_mile"]
    if va:
        v = world.nodes[va[0].properties["vehicle_id"]].properties
        info["last_mile_vehicle"] = {"ownership": v.get("ownership"), "class": v.get("vehicle_class")}
    info["attempts_visible"] = [(n.properties.get("disposition"), n.properties.get("failed_reason")) for n in vis if n.kind == "DeliveryAttempt"]
    info["contacts_visible"] = [n.properties.get("result") for n in vis if n.kind == "ContactAttempt"]
    info["custody_visible"] = [(n.properties.get("event_type"), world.nodes[n.properties["to_id"]].kind if n.properties.get("to_id") in world.nodes else n.properties.get("to_id"),
                                n.properties.get("source_quality"), n.properties.get("occurred_at", "")[5:16]) for n in sorted(
                                    (x for x in vis if x.kind == "CustodyEvent"), key=lambda x: x.properties["occurred_at"])]
    info["traffic_visible"] = [(n.properties.get("delay_seconds"), n.properties.get("confidence")) for n in vis if n.kind == "TrafficObservation"]
    sessions = [n for n in index.groups[sid].get("DeliverySession", [])]
    info["sessions"] = [(n.id[-20:], n.properties.get("end_at", "")[5:16], n.properties.get("grace_seconds")) for n in sessions]
    report[c["case_id"]] = info
json.dump(report, open(S + "/snapshot.json", "w"), indent=1, default=str)
for k, v in report.items():
    if v["agent"] not in v["acceptable"] or v["recipe"] in ("unanswered_contact", "later_hub_departure", "traffic_safe_return", "offline_device_sync", "contractor_on_time"):
        print(json.dumps(v, default=str))
