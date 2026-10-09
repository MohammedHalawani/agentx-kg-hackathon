"""Detection quality on a split the monitor was not tuned on (default: held_out).

Replays the chosen split as if it were live: every observation becomes visible at the delivery
time the provider feed would give it (same lag rules as the live feed), and the monitor's own
decision function (assess_shipment with the live detection allowance, then monitor_finding) is
applied every simulated hour. Truth is read only afterwards, to score. No database, no model.

Usage (from chat/):  uv run python ../scripts/detection_eval.py --split held_out
"""
import argparse
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chat"))

from dataset_v2.contracts import World, instant, iso  # noqa: E402
from dataset_v2.derive import assess_shipment  # noqa: E402
from dataset_v2.feed import split_feed, reconstitute  # noqa: E402
from dataset_v2.network import generate_live, live_config  # noqa: E402
from operations.store import DETECTION_ALLOWANCE_SECONDS, monitor_finding  # noqa: E402


def mini_world(full, owned, cutoff):
    """The shipment's evidence visible at `cutoff` (occurred and recorded by then) plus shared catalogs."""
    world = World(full.config)
    for node in owned:
        p = node.properties
        if p.get("recorded_at") and instant(p["recorded_at"]) > cutoff:
            continue
        if p.get("occurred_at") and instant(p["occurred_at"]) > cutoff:
            continue
        world.nodes[node.id] = node
    for key in full.shared:
        world.nodes[key] = full.nodes[key]
    return world


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="held_out", choices=("held_out", "development", "history"))
    parser.add_argument("--total", type=int, default=600)
    args = parser.parse_args()
    world, truth = generate_live(live_config(total=args.total))
    as_live = {sid: {**row, "split": "development" if row["split"] == args.split else "other"} for sid, row in truth.items()}
    imported, items = split_feed(world, as_live)
    full = reconstitute(imported, items)
    full.shared = [k for k, n in full.nodes.items() if not n.properties.get("holdout_group") and n.kind != "DeviceHeartbeat"]
    end = instant(full.config.as_of)
    by_owner = {}
    for node in full.nodes.values():
        by_owner.setdefault(node.properties.get("holdout_group"), []).append(node)
    rows = []
    for sid, row in sorted(truth.items()):
        if row["split"] != args.split:
            continue
        start = instant(full.nodes[sid].properties["recorded_at"])
        opened, symptoms, t = None, [], start
        while t <= end:
            world = mini_world(full, by_owner[sid], t)
            if sid in world.nodes:
                finding = monitor_finding(assess_shipment(world, sid, iso(t), detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS))
                if finding["open"]:
                    opened, symptoms = iso(t), finding["symptoms"]
                    break
            t += timedelta(hours=1)
        rows.append({"shipment_id": sid, "recipe": row["recipe"], "healthy": row["healthy"], "opened_at": opened, "symptoms": symptoms})
    healthy = [r for r in rows if r["healthy"]]
    abnormal = [r for r in rows if not r["healthy"]]
    fp = [r for r in healthy if r["opened_at"]]
    missed = [r for r in abnormal if not r["opened_at"]]
    report = {"split": args.split, "shipments": len(rows), "healthy": len(healthy), "abnormal": len(abnormal),
              "false_positive_cases": len(fp), "false_positive_rate": round(len(fp) / len(healthy), 4) if healthy else None,
              "missed_abnormal": len(missed), "recall": round(1 - len(missed) / len(abnormal), 4) if abnormal else None,
              "false_positive_by_recipe": dict(Counter(r["recipe"] for r in fp)),
              "missed_by_recipe": dict(Counter(r["recipe"] for r in missed)),
              "false_positive_examples": [{k: r[k] for k in ("shipment_id", "recipe", "opened_at", "symptoms")} for r in fp[:10]]}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
