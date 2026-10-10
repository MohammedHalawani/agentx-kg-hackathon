import sys
from collections import Counter
from datetime import timedelta
sys.path.insert(0, ".")
from dataset_v2.network import generate_live, live_config
from dataset_v2.feed import split_feed
from dataset_v2.contracts import instant
world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
imported, items = split_feed(world, truth)
start = instant(min(i["deliver_at"] for i in items if i["origin"] == "PROVIDER")) - timedelta(seconds=1)
buffered = {e for r in truth.values() for e in (r.get("outage_affected_event_ids") or [])}
lags = Counter(); n = 0; ge60 = 0; ge60_nonbuf = 0; nonbuf = 0
for i in items:
    if i["origin"] != "PROVIDER": continue
    node = world.nodes[i["source_event_id"]]
    if node.kind not in ("CustodyEvent", "ScanEvent", "DeliveryAttempt"): continue
    d = instant(i["deliver_at"]); k = -(-(d - start).total_seconds() // 3600); rec = start + timedelta(hours=k)
    lag = (rec - instant(node.properties["occurred_at"])).total_seconds() / 60
    n += 1; ge60 += lag >= 60
    if node.id not in buffered:
        nonbuf += 1; ge60_nonbuf += lag >= 60
        lags[min(int(lag // 10) * 10, 120)] += 1
print("records", n, "lag>=60min", ge60, "| not outage-buffered", nonbuf, "of which lag>=60min", ge60_nonbuf, round(ge60_nonbuf / nonbuf, 3))
print("lag histogram (10-min bins, non-buffered):", sorted(lags.items()))
