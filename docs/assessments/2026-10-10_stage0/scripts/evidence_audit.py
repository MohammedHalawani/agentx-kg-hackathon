"""Stage 0: offline evidence-availability audit of the final S5 run (f36736b), no model calls.

For each investigated case, rebuild what Suhail had ingested at the investigation snapshot (the case's opening
time), replay the investigator's read-only tools deterministically, and record which discriminating signals
were visible to it, which existed in the world but no tool exposes (cross-shipment), and which did not exist yet.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, r"C:\Projects\demo\chat")
from dataset_v2.contracts import instant  # noqa: E402
from dataset_v2.feed import reconstitute, split_feed  # noqa: E402
from dataset_v2.network import generate_live, live_config  # noqa: E402
from operations.reasoning import public_evidence  # noqa: E402
from operations.tools import InvestigationTools  # noqa: E402

FINAL = Path(r"C:\Projects\demo\docs\evals\2026-10-09_s5\final\pipeline.json")
rows = json.loads(FINAL.read_text(encoding="utf-8"))["cases"]
world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
imported, items = split_feed(world, truth)
live = reconstitute(imported, items)


def heartbeats(device_id, since, until):
    return [{"entity_id": n.id, **n.properties} for n in live.of_kind("DeviceHeartbeat")
            if n.properties["device_id"] == device_id and instant(since) <= instant(n.properties["occurred_at"]) <= instant(until)
            and instant(n.properties["recorded_at"]) <= instant(until)]


# Raw scan/custody records by device (from the provider payload's device_ref), for cross-shipment facts.
by_device = defaultdict(list)
for n in live.nodes.values():
    if n.kind in ("ScanEvent", "RawScanEvent") or n.properties.get("device_ref"):
        dev = n.properties.get("device_ref")
        if dev:
            by_device[dev].append(n)

out = []
for r in rows:
    if r["truth_healthy"]:
        continue
    sid, at = r["shipment_id"], r["opened_at"]
    try:
        context = public_evidence(live, sid, at)
    except LookupError:
        out.append({"case": r["case_id"], "error": "not visible"}); continue
    tools = InvestigationTools(context, live.config, symptoms=r.get("opening_symptoms") or [], heartbeats=heartbeats,
                               precedents=lambda cause: [])
    journey = tools._journey()
    missing = [m for m in journey["milestones"] if m["state"] == "missing_after_deadline"]
    handhelds = sorted({m.get("facility_handheld") for m in missing if m.get("facility_handheld")})
    device_reports = {}
    for d in handhelds:
        rep = tools._device_status(d)
        device_reports[d] = {k: rep.get(k) for k in ("reporting_state", "last_seen_at", "expected_beats_missed_since_last_seen",
                                                     "last_pending_uploads")}
    # Cross-shipment (not exposed by any tool): other shipments whose records from the same handheld were held back at this time.
    held_back_others = {}
    for d in handhelds:
        others = {n.properties.get("shipment_id") for n in by_device.get(d, [])
                  if n.properties.get("shipment_id") != sid and instant(n.properties["occurred_at"]) <= instant(at) < instant(n.properties["recorded_at"])}
        held_back_others[d] = len({o for o in others if o})
    t = truth[sid]
    out.append({
        "case": r["case_id"][-8:], "shipment": sid[-6:], "recipe": t["recipe"], "acceptable": t["acceptable_causes"],
        "physical": {k: v for k, v in (t.get("physical") or {}).items() if k in ("device", "parcel", "label", "scale", "recipient", "contractor")},
        "secondary": t.get("secondary_issue"),
        "opening": r.get("opening_symptoms"), "diagnosis": r["primary_cause"], "correct": r["primary_cause"] in (t["acceptable_causes"] or []),
        "tools_called": r["tools"], "final_state": r["final_state"], "review": r["review"], "authority": (r["authority_reason"] or "")[:60],
        "missing_milestones": [(m["predicate"], (m.get("location_id") or "")[-14:]) for m in missing],
        "expected_handhelds": handhelds, "device_status_at_snapshot": device_reports,
        "called_device_status": "device_status" in r["tools"],
        "other_shipments_held_back_on_same_handheld": held_back_others,
    })

Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(len(out))
