"""Offline replica of the live monitor's opening symptoms (read-only, in-memory)."""
import json, pickle, sys
from collections import defaultdict
from datetime import timedelta
sys.path.insert(0, ".")
from dataset_v2.network import generate_live, live_config
from dataset_v2.feed import split_feed, feed_item, Reference, FEED_KINDS
from dataset_v2.derive import assess_shipment, EvidenceIndex
from dataset_v2.contracts import instant, iso
from operations.store import monitor_finding, DETECTION_ALLOWANCE_SECONDS

OUT = sys.argv[1]
world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
imported, items = split_feed(world, truth)
start = instant(min(i["deliver_at"] for i in items if i["origin"] == "PROVIDER")) - timedelta(seconds=1)
print("clock start", start.isoformat())
ref = Reference.from_world(world)
deliver = {}
for i in items:
    deliver.setdefault(i["source_event_id"], i["deliver_at"])
for n in world.nodes.values():
    if n.kind in FEED_KINDS and n.id not in deliver and n.properties.get("recorded_at"):
        try:
            deliver[n.id] = feed_item(world, n, ref)["deliver_at"]
        except Exception:
            deliver[n.id] = n.properties["recorded_at"]

def tick_ceil(t):
    k = -(-(t - start).total_seconds() // 3600)
    return start + timedelta(hours=k)

orig_recorded = {}
for nid, d in deliver.items():
    n = world.nodes[nid]
    orig_recorded[nid] = n.properties["recorded_at"]
    n.properties["recorded_at"] = iso(tick_ceil(instant(d)))
index = EvidenceIndex(world)
result = {"start": start.isoformat(), "shipments": {}}
for sid, row in sorted(truth.items()):
    if row["healthy"]:
        continue
    owned = index.groups[sid]
    times = [instant(n.properties["recorded_at"]) for kind, nodes in owned.items() for n in nodes if n.properties.get("recorded_at")]
    times += [instant(n.properties["occurred_at"]) for kind, nodes in owned.items() for n in nodes if n.properties.get("occurred_at")]
    t0, t1 = tick_ceil(min(times)), tick_ceil(max(times)) + timedelta(hours=48)
    t = t0
    timeline = []
    first = None
    prev_codes = None
    while t <= t1:
        a = assess_shipment(world, sid, t.isoformat(), _index=index, detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)
        codes = tuple(sorted(e["code"] for e in a["exceptions"]))
        if codes != prev_codes:
            timeline.append((t.isoformat(), list(codes), monitor_finding(a)["symptoms"]))
            prev_codes = codes
        t += timedelta(hours=1)
    result["shipments"][sid] = {"recipe": row["recipe"], "split": row["split"], "root_cause": row["root_cause"],
                                "acceptable": row["acceptable_causes"], "secondary": row.get("secondary_issue"),
                                "timeline": timeline}
json.dump(result, open(OUT, "w"), indent=0)
print("abnormal", len(result["shipments"]))
