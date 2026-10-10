import json, sys
sys.path.insert(0, r"C:\Projects\demo\chat")
from dataset_v2.network import generate_live, live_config
from operations.reasoning import public_evidence
from operations.tools import InvestigationTools, MAX_RESULT_CHARS
world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
pipe = json.load(open(r"C:\Projects\demo\docs\evals\2026-10-09_s5\final\pipeline.json"))
tot = {"journey_rows_gt30": 0, "journey_text_cut": 0, "missing_hidden": 0, "cases_with_missing": 0, "scans_text_cut": 0, "cust_text_cut": 0, "attempts_text_cut": 0}
for c in pipe["cases"]:
    sid, as_of = c["shipment_id"], c["opened_at"]
    ctx = public_evidence(world, sid, as_of)
    t = InvestigationTools(ctx, world.config, symptoms=c["opening_symptoms"])
    pkgs = [n.id for n in t._packages()]
    # full milestone list (no row cap): per-package calls
    full = [r for p in pkgs for r in t._journey(p)["milestones"]]
    missing = [r for r in full if r["state"] == "missing_after_deadline"]
    res = t.call("journey", {})["result"]
    cut = "TRUNCATED" in res
    body = res.split(" CITABLE_EVIDENCE_IDS")[0]; hidden = [r["milestone_id"] for r in missing if ("\"milestone_id\": \"" + r["milestone_id"] + "\"") not in body]
    tot["journey_rows_gt30"] += len(full) > 30
    tot["journey_text_cut"] += cut
    tot["cases_with_missing"] += bool(missing)
    tot["missing_hidden"] += bool(hidden)
    s = t.call("scans", {})["result"]; tot["scans_text_cut"] += "TRUNCATED" in s
    a = t.call("delivery_attempts", {})["result"]; tot["attempts_text_cut"] += "TRUNCATED" in a
    per = [len(t.call("journey", {"package_id": p})["result"]) for p in pkgs]
    if cut or hidden or len(full) > 30:
        print(sid[-6:], "pkgs", len(pkgs), "milestones", len(full), "journey chars(all)", len(res), "per-pkg chars", per,
              "missing", len(missing), "missing hidden in journey():", len(hidden), "| model journey calls:", c["tools"].count("journey"), "ok" if c["primary_cause"] in c["acceptable_causes"] else "WRONG")
print(tot, "cases", len(pipe["cases"]))
