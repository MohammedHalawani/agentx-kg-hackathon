"""S3 gate: real GPT-OSS investigations inside the live runtime (isolated Neo4j test database).

Replays the live timeline hour by hour through the gateway and monitor; whenever the monitor has
opened a case, the investigation worker runs the real GPT-OSS agent (tool loop + independent
reviewer) at that moment's evidence snapshot. Afterwards, and only for scoring, each conclusion
is compared with the separately stored truth. Prints a JSON summary: no prompts, provider text
or credentials. The test database is created by tests/test_live_runtime_neo4j.build_test_database.

Usage (from chat/): uv run python ../scripts/s3_agent_gate.py [--rebuild] [--max-cases N]
"""
import argparse
import json
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chat"))

import config  # noqa: E402
from tests.test_live_runtime_neo4j import TEST_DATABASE, build_test_database, make_store  # noqa: E402


def ledger(driver, kind):
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        return [dict(r["p"]) for r in session.run(f"MATCH (n:OpsEntity:{kind}) RETURN properties(n) AS p")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cases", type=int, default=50)
    parser.add_argument("--total", type=int, default=150)
    args = parser.parse_args()
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    from operations import investigator
    driver, bundle, truth, tmp = build_test_database(total=args.total)
    store = make_store(driver, bundle, agents=investigator)
    runs = []
    while len(runs) < args.max_cases:
        store.tick(seconds=3600, manual=True, speed=1)
        while store.status()["session"]["monitor_pending"]:
            store.monitor_step(limit=20)
        while len(runs) < args.max_cases:
            started = time.perf_counter()
            result = store.process_one(manual=True)
            if not result.get("processed") and result.get("reason") != "snapshot_changed":
                break
            runs.append({"case_id": result["case_id"], "seconds": round(time.perf_counter() - started, 1), **{k: result.get(k) for k in ("workflow_state", "reason")}})
        if store.status()["as_of"] >= store.status()["simulator"]["end_at"]:
            break
    cases = {c["entity_id"]: c for c in ledger(driver, "OpsCase")}
    run_rows = {r["case_id"]: json.loads(r["result_json"]) for r in ledger(driver, "OpsRun") if r.get("result_json")}
    report = []
    for run in runs:
        case = cases[run["case_id"]]
        analysis = run_rows.get(run["case_id"], {})
        inv = analysis.get("investigation") or {}
        row = truth[case["shipment_id"]]
        cited = {i for h in inv.get("hypotheses") or [] for i in h.get("supporting_evidence_ids", [])}
        report.append({
            "case_id": case["entity_id"], "shipment_id": case["shipment_id"], "symptoms": case.get("symptom_codes"),
            "seconds": run["seconds"], "tool_calls": len(inv.get("steps") or []), "tools": [s["tool"] for s in inv.get("steps") or []],
            "mode": inv.get("mode"), "primary_cause": inv.get("primary_cause"), "confidence": inv.get("confidence"),
            "hypotheses": [(h["cause"], h["status"]) for h in inv.get("hypotheses") or []],
            "action": inv.get("recommended_action"), "review": (analysis.get("review") or {}).get("model_verdict"),
            "iterations": len(analysis.get("trace") or []), "degraded": [d["role"] for d in analysis.get("degraded") or []],
            "unsupported_by_rules": (analysis.get("checks") or {}).get("unsupported"),
            "authority": (analysis.get("authority") or {}).get("risk_class"), "workflow_state": case["workflow_state"],
            "cited_within_retrieved": cited <= set(inv.get("retrieved_evidence_ids") or []),
            # Scoring only (never available to the run): the scenario's expected cause.
            "truth_recipe": row["recipe"], "truth_cause": row["root_cause"], "acceptable": row["acceptable_causes"],
            "cause_correct": inv.get("primary_cause") in (row["acceptable_causes"] or []),
            "key_evidence_cited": bool(cited & set(row.get("key_evidence") or [])) if row.get("key_evidence") else None})
    scored = [r for r in report if r["truth_cause"]]
    summary = {"model": config.LLM_MODEL, "cases": len(report),
               "root_cause_correct": sum(r["cause_correct"] for r in scored), "scored": len(scored),
               "citations_valid": sum(r["cited_within_retrieved"] for r in report),
               "mean_tool_calls": round(sum(r["tool_calls"] for r in report) / len(report), 1) if report else None,
               "mean_seconds": round(sum(r["seconds"] for r in report) / len(report), 1) if report else None,
               "degraded": sum(bool(r["degraded"]) for r in report),
               "authority": {k: sum(r["authority"] == k for r in report) for k in ("AUTO", "APPROVAL_REQUIRED", "HUMAN_REVIEW", None)}}
    print(json.dumps({"summary": summary, "cases": report}, indent=1, default=str))
    tmp.cleanup()


if __name__ == "__main__":
    main()
