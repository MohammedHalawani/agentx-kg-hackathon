"""S1 gate: real GPT-OSS investigations over the isolated V2 graph, read-only (no ledger writes).

Runs the operations LangGraph with the real model roles for development shipments whose visible
evidence (at a mid-journey snapshot) shows a symptom, then repeats one run with the reviewer
pointed at an unreachable endpoint to prove the reviewer fails closed. Prints a JSON summary only:
no provider text, prompts or credentials.

Usage (from chat/):  uv run python ../scripts/s1_model_gate.py --cases 4
"""
import argparse
import json
import sys
import time
import types
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chat"))

import config  # noqa: E402
from core.query_runner import get_driver  # noqa: E402
from dataset_v2.contracts import Config, instant  # noqa: E402
from dataset_v2.derive import assess_shipment  # noqa: E402
from dataset_v2.load import DEFAULT_DATABASE  # noqa: E402
from operations import agents  # noqa: E402
from operations.graph import investigate  # noqa: E402
from operations.read_model import OperationsReader  # noqa: E402
from operations.reasoning import evidence_world  # noqa: E402


def reader():
    driver = get_driver()
    with driver.session(database=DEFAULT_DATABASE, default_access_mode="READ") as session:
        manifest = json.loads(session.run("MATCH (m:_V2Import) RETURN m.manifest_json AS m").single()["m"])
    cfg = Config(**manifest["config"])
    return OperationsReader(driver, DEFAULT_DATABASE, cfg.dataset_id, cfg, clock=lambda: cfg.as_of), cfg


def candidates(read, cfg, limit):
    rows = read._run("MATCH (s:V2Entity:Shipment {dataset_id:$dataset_id,split:'development'}) "
                     "RETURN s.entity_id AS sid, s.recorded_at AS start, s.as_of AS end ORDER BY s.entity_id")
    found = []
    for row in rows:
        start, end = instant(row["start"]), instant(row["end"])
        # Mid-journey snapshot: the case is investigated before its story has finished.
        snapshot = (start + (end - start) * 0.6).isoformat()
        context = read.evidence(row["sid"], snapshot)
        exceptions = assess_shipment(evidence_world(context, cfg), row["sid"], snapshot)["exceptions"]
        if exceptions:
            found.append((row["sid"], snapshot))
        if len(found) >= limit:
            break
    return found


def summarize(sid, snapshot, analysis, seconds):
    events = analysis["pipeline_events"]
    review = analysis["review"]
    investigation = analysis.get("investigation") or {}
    return {"shipment_id": sid, "as_of": snapshot, "seconds": round(seconds, 1),
            "mode": analysis["mode"], "investigator": investigation.get("mode"),
            "primary_hypothesis": investigation.get("primary_hypothesis"),
            "validation_errors": {role: (analysis.get("investigation") or {}).get("validation_error") if role == "investigator" else
                                  ((analysis.get("proposal") or {}).get("planner") or {}).get("validation_error") for role in ("investigator", "planner")},
            "cited_evidence": len(investigation.get("supporting_evidence_ids") or []),
            "planner": ((analysis.get("proposal") or {}).get("planner") or {}).get("mode"),
            "action_type": (analysis.get("proposal") or {}).get("action_type"),
            "review_verdict": review.get("verdict"), "model_review_verdict": review.get("model_verdict"),
            "iterations": len(analysis["trace"]), "degraded": [d["role"] for d in analysis.get("degraded", [])],
            "authority": (analysis.get("authority") or {}).get("risk_class"),
            "workflow_state": analysis["result"]["workflow_state"],
            "stages": " ".join(f"{e['stage']}:{e['status']}" for e in events if e["status"] != "RUNNING")}


def run(read, cfg, sid, snapshot, module):
    started = time.perf_counter()
    analysis, _ = investigate(sid, snapshot, cfg, read.evidence,
                              lambda s, codes: read.historical_precedents(s, codes, as_of=snapshot),
                              agents=module, live_session=True)
    return summarize(sid, snapshot, analysis, time.perf_counter() - started)


def unreachable_reviewer():
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_litellm import ChatLiteLLM
    from llm.pipeline import _llm
    broken = ChatLiteLLM(model=config.LLM_MODEL, api_key=config.LLM_API_KEY, api_base="http://127.0.0.1:9/v1",
                         temperature=0, request_timeout=10, max_retries=0)
    def call(system, user, default):
        response = broken.invoke([SystemMessage(system), HumanMessage(user)])
        return _llm.parse_json(_llm.message_text(response.content)) or default
    return types.SimpleNamespace(facts=agents.facts, investigate=agents.investigate, plan=agents.plan,
                                 review=lambda p, i, pr: agents.review(p, i, pr, call=call))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=4)
    args = parser.parse_args()
    read, cfg = reader()
    chosen = candidates(read, cfg, args.cases)
    results = [run(read, cfg, sid, snapshot, agents) for sid, snapshot in chosen]
    healthy = [(r["shipment_id"], r["as_of"]) for r in results if not r["degraded"] and r["model_review_verdict"]]
    failure = run(read, cfg, *healthy[0], unreachable_reviewer()) if healthy else None
    print(json.dumps({"model": config.LLM_MODEL, "database": DEFAULT_DATABASE, "writes": 0,
                      "investigations": results, "reviewer_unreachable": failure}, indent=1))


if __name__ == "__main__":
    main()
