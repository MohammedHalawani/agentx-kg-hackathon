"""Read-only: regenerate the S5 world in memory and replay the investigator's tools per case."""
import json, sys, time, pickle
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"C:\Projects\demo\chat")
from dataset_v2.network import generate_live, live_config
from dataset_v2.contracts import instant
from dataset_v2.derive import assess_shipment
from operations.reasoning import public_evidence
from operations.tools import InvestigationTools
from operations.store import monitor_finding

OUT = Path(sys.argv[1])
t0 = time.time()
world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
print("generated", round(time.time() - t0), "s", len(world.nodes), "nodes", file=sys.stderr)

beats_by_device = {}
for n in world.nodes.values():
    if n.kind == "DeviceHeartbeat":
        beats_by_device.setdefault(n.properties["device_id"], []).append(n)


def heartbeats(device_id, since, until):
    rows = []
    for b in beats_by_device.get(device_id, []):
        p = b.properties
        if instant(p["recorded_at"]) <= instant(until) and instant(since) <= instant(p["occurred_at"]) <= instant(until):
            rows.append({"entity_id": b.id, "occurred_at": p["occurred_at"], "pending_uploads": p.get("pending_uploads"),
                         "last_upload_at": p.get("last_upload_at")})
    return sorted(rows, key=lambda r: r["occurred_at"], reverse=True)[:60]


EXPOSED = {"Shipment", "Package", "JourneyPlan", "StatusEvent(latest only)", "ExpectedMilestone", "CustodyEvent", "ScanEvent",
           "DeliveryAttempt", "ContactAttempt", "RecipientReport", "DepotReconciliation", "VehicleAssignment", "DeliverySession",
           "Manifest", "GPSObservation", "AddressVersion", "DeliveryInstruction", "LocationPin", "Policy", "ServiceLevel"}

pipe = json.load(open(r"C:\Projects\demo\docs\evals\2026-10-09_s5\final\pipeline.json"))
rows = []
for c in pipe["cases"]:
    sid, as_of = c["shipment_id"], c["opened_at"]
    ctx = public_evidence(world, sid, as_of)
    kinds = Counter(n["kind"] for n in ctx["nodes"])
    tools = InvestigationTools(ctx, world.config, symptoms=c["symptoms"], heartbeats=heartbeats)
    reachable = set()
    calls = {}
    calls["shipment_overview"] = tools.call("shipment_overview", {})
    pkgs = [n.id for n in tools._packages()]
    calls["journey"] = tools.call("journey", {})
    for p in pkgs:
        calls["custody_chain:" + p] = tools.call("custody_chain", {"package_id": p})
    calls["scans"] = tools.call("scans", {})
    calls["delivery_attempts"] = tools.call("delivery_attempts", {})
    calls["vehicle_and_manifest"] = tools.call("vehicle_and_manifest", {})
    calls["address_and_instructions"] = tools.call("address_and_instructions", {})
    calls["policy"] = tools.call("policy", {})
    reachable = set(tools.retrieved)
    # device candidates the investigator could learn from tool output
    jr = tools._journey()["milestones"]
    hh = sorted({r["facility_handheld"] for r in jr if r.get("facility_handheld")})
    vm = tools._vehicle_and_manifest()
    apps = sorted({a["driver_app_device"] for a in vm["assignments"] if a.get("driver_app_device")})
    cust_devs = sorted({t["device_ref"] for p in pkgs for t in tools._custody_chain(p)["transfers"] if t.get("device_ref")})
    dev = {}
    for d in sorted(set(hh) | set(apps) | set(cust_devs)):
        if not d.startswith("DEMO-DEV-"):
            continue
        r = tools._device_status(d, 72)
        dev[d] = (r["reporting_state"], r["heartbeats"], r["hours_since_last_seen"], r["last_pending_uploads"], r["largest_gap_hours"])
    unreachable = {n["id"]: n["kind"] for n in ctx["nodes"] if n["id"] not in reachable}
    rule = assess_shipment(tools.world, sid, as_of)
    t = truth[sid]
    sizes = {k: len(v["result"]) for k, v in calls.items()}
    rows.append({"sid": sid[-6:], "as_of": as_of, "recipe": t["recipe"], "acceptable": t["acceptable_causes"],
                 "primary": c["primary_cause"], "ok": c["primary_cause"] in t["acceptable_causes"], "symptoms": c["symptoms"],
                 "tools_used": c["tools"], "context_kinds": dict(kinds), "unreachable_kinds": dict(Counter(unreachable.values())),
                 "rule_codes": rule["supported_codes"], "devices": dev, "facility_handhelds": hh, "driver_apps": apps,
                 "custody_devices": cust_devs, "key_evidence": t.get("key_evidence"),
                 "key_visible": [k for k in t.get("key_evidence") or [] if k in tools.nodes],
                 "key_reachable": [k for k in t.get("key_evidence") or [] if k in reachable],
                 "physical": t.get("physical"), "secondary": t.get("secondary_issue"), "result_chars": sizes,
                 "n_packages": len(pkgs)})
OUT.write_text(json.dumps(rows, indent=1, default=str))
print("done", round(time.time() - t0), "s", file=sys.stderr)
