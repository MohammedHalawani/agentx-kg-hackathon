"""Read-only: per-case detail on missing milestones, the device journey points to, upload lags, traffic, proof reasons."""
import json, sys
from collections import Counter
sys.path.insert(0, r"C:\Projects\demo\chat")
from dataset_v2.network import generate_live, live_config
from dataset_v2.contracts import instant
from operations.reasoning import public_evidence
from operations.tools import InvestigationTools
from operations.checks import fact_checks, cited_records

world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
beats = {}
for n in world.nodes.values():
    if n.kind == "DeviceHeartbeat":
        beats.setdefault(n.properties["device_id"], []).append(n)


def heartbeats(device_id, since, until):
    return sorted([{"entity_id": b.id, "occurred_at": b.properties["occurred_at"], "pending_uploads": b.properties.get("pending_uploads"),
                    "last_upload_at": b.properties.get("last_upload_at")} for b in beats.get(device_id, [])
                   if instant(b.properties["recorded_at"]) <= instant(until) and instant(since) <= instant(b.properties["occurred_at"]) <= instant(until)],
                  key=lambda r: r["occurred_at"], reverse=True)[:60]


pipe = json.load(open(r"C:\Projects\demo\docs\evals\2026-10-09_s5\final\pipeline.json"))
want = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else None
for c in pipe["cases"]:
    sid, as_of = c["shipment_id"], c["opened_at"]
    if want and sid[-6:] not in want:
        continue
    ctx = public_evidence(world, sid, as_of)
    tools = InvestigationTools(ctx, world.config, symptoms=c["opening_symptoms"], heartbeats=heartbeats)
    j = tools._journey()["milestones"]
    missing = [r for r in j if r["state"] == "missing_after_deadline"]
    print("==", sid[-6:], truth[sid]["recipe"], "acc", truth[sid]["acceptable_causes"], "model", c["primary_cause"], "open", c["opening_symptoms"])
    print("   milestones: %d total, states %s" % (len(j), dict(Counter(r["state"] for r in j))))
    for r in missing:
        d = tools._device_status(r["facility_handheld"], 24) if r["facility_handheld"] else None
        print("   MISSING", r["predicate"], r["location_kind"], r["location_id"], "->", r["facility_handheld"], d and (d["reporting_state"], d["hours_since_last_seen"], d["heartbeats"]))
    for p in [n.id for n in tools._packages()][:2]:
        ch = tools._custody_chain(p)["transfers"]
        print("   custody", p[-6:], [(t["event_type"], t["to_kind"], t["corroborated"], t["acknowledgments"], t["upload_lag_minutes"], (t["device_ref"] or "")[9:]) for t in ch])
    lag = [(n.kind, n.id[-20:], round((instant(n.properties["recorded_at"]) - instant(n.properties["occurred_at"])).total_seconds() / 60))
           for n in tools.nodes.values() if n.properties.get("occurred_at") and n.properties.get("recorded_at")
           and (instant(n.properties["recorded_at"]) - instant(n.properties["occurred_at"])).total_seconds() >= 3600]
    print("   records with upload lag >= 60 min:", lag[:6], "count", len(lag))
    traffic = [n for n in tools.nodes.values() if n.kind == "TrafficObservation"]
    if traffic:
        print("   TrafficObservation (no tool returns it):", [(t.id[-24:], t.properties.get("delay_seconds"), t.properties.get("confidence")) for t in traffic])
    da = tools._delivery_attempts()
    for a in da["attempts"]:
        print("   attempt", a["disposition"], a["failed_reason"], [x["result"] for x in a["contacts"]], [(p["corroborated"], p["reasons"]) for p in a["proofs"]])
    vm = tools._vehicle_and_manifest()
    print("   assignments", [(a["mode"], a["vehicle_ownership"], a["driver_employment"], a["session_end_at"]) for a in vm["assignments"]])
    print("   phys", truth[sid].get("physical"))
