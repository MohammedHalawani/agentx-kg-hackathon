"""S5: end-to-end scenarios A-F and measured metrics, on an isolated Neo4j test database.

Phases (run in order; each recreates shipments-v2-demo-test from a fresh live bundle):
  pipeline   live split replayed hour by hour through the gateway, monitor, real GPT-OSS
             investigation (tool loop + reviewer), authority, execution adapter (synthetic
             operational simulator) and the independent verifier. Scenarios A, B, C, E + metrics.
  heldout    the held-out split replayed as the live split through the real gateway and monitor
             (no model): official detection false positives and recall.
  reviewer   scenario D: one case investigated with the reviewer pointed at an unreachable endpoint.
  concurrency scenario F: the separated workers run with the real model while the clock advances;
             ingestion and monitoring progress is sampled during each investigation.
  checks     on the database a pipeline run left: public evidence ids, authority bypass, case triggers.
  accounting on the same database: every wrong diagnosis's end state, whether each resolved case's
             exception was gone at closure, and what happened to shipments with two genuine causes.

Truth is read only to score after each phase (and by the simulator, which plays the field).
Usage (from chat/): uv run python ../scripts/s5_scenarios.py --phase pipeline --out ../docs/evals/2026-10-09_s5
"""
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chat"))

import config  # noqa: E402
from tests.test_live_runtime_neo4j import TEST_DATABASE, build_test_database, make_store  # noqa: E402

logging.getLogger("neo4j").setLevel(logging.ERROR)


ROOT = Path(__file__).resolve().parents[1]
# Every model call LiteLLM completes or fails during a phase, by the model name the provider reported.
MODEL_CALLS = {"succeeded": {}, "failed": {}, "total_tokens": 0}


def record_model_calls():
    import litellm

    def succeeded(kwargs, response, start, end):
        name = getattr(response, "model", None) or kwargs.get("model") or "unknown"
        MODEL_CALLS["succeeded"][name] = MODEL_CALLS["succeeded"].get(name, 0) + 1
        MODEL_CALLS["total_tokens"] += getattr(getattr(response, "usage", None), "total_tokens", 0) or 0

    def failed(kwargs, response, start, end):
        name = kwargs.get("model") or "unknown"
        MODEL_CALLS["failed"][name] = MODEL_CALLS["failed"].get(name, 0) + 1

    litellm.success_callback = [*litellm.success_callback, succeeded]
    litellm.failure_callback = [*litellm.failure_callback, failed]


def git_state():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip())
    return commit, dirty


def provenance(phase, started_at, *, bundle_dir=None, manifest_hash=None):
    """Written into every results file: the exact code, data and model a result came from."""
    from dataset_v2.contracts import digest
    from dataset_v2.network import NETWORK_VERSION
    from operations import investigator
    commit, dirty = git_state()
    record = {"phase": phase, "commit": commit, "dirty_tree": dirty, "started_at": started_at,
              "finished_at": datetime.now(timezone.utc).isoformat(), "configured_model": config.LLM_MODEL,
              "model_api_base": config.LLM_API_BASE, "database": TEST_DATABASE, "generator": NETWORK_VERSION,
              "investigator_prompt_sha256": digest(investigator.SYSTEM), "reviewer_prompt_sha256": digest(investigator.REVIEWER_SYSTEM),
              "model_calls": json.loads(json.dumps(MODEL_CALLS))}
    if bundle_dir is not None:
        manifest = json.loads((Path(bundle_dir) / "manifest.json").read_text(encoding="utf-8"))
        feed = json.loads((Path(bundle_dir) / "feed_manifest.json").read_text(encoding="utf-8"))
        record.update(dataset_id=manifest.get("dataset_id"), manifest_hash=digest(manifest), feed_hash=feed["hash"], truth_hash=feed["truth_hash"])
    if manifest_hash:
        record["manifest_hash"] = manifest_hash
    return record


def ledger(driver, kind):
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        return [dict(r["p"]) for r in session.run(f"MATCH (n:OpsEntity:{kind}) RETURN properties(n) AS p")]


def iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else (value.to_native().isoformat() if hasattr(value, "to_native") else value)


def attach(store, truth):
    from operations.simulation import OperationalSimulator
    store.adapter = OperationalSimulator(store.gateway, store.reader, truth, store.config)


def scoring_truth(total, manifest_hash):
    """The answer key, regenerated deterministically for scoring and checked against the imported dataset."""
    import tempfile
    from dataset_v2.contracts import digest
    from dataset_v2.live_bundle import export_live, read_live_bundle, read_truth
    from dataset_v2.network import live_config
    with tempfile.TemporaryDirectory() as tmp:
        export_live(Path(tmp) / "b", live_config(total=total, dataset_id="DEMO-SUHAIL-LIVE-TEST"), live_split="development")
        bundle, _ = read_live_bundle(Path(tmp) / "b")
        truth = read_truth(Path(tmp) / "b")
    assert digest(bundle.manifest) == manifest_hash, "regenerated truth does not match the imported dataset"
    return truth


def step_loop(store, *, investigate=True, max_hours=None):
    hours = 0
    while store.status()["as_of"] < store.status()["simulator"]["end_at"] and (max_hours is None or hours < max_hours):
        store.tick(seconds=3600, manual=True, speed=1)
        hours += 1
        while store.status()["session"]["monitor_pending"]:
            store.monitor_step(limit=25)
        if investigate:
            while True:
                result = store.process_one(manual=True)
                if not result.get("processed") and result.get("reason") != "snapshot_changed":
                    break
            store.execute_step(limit=25)
        store.outcome_step(limit=50)


def case_rows(driver, truth):
    cases = ledger(driver, "OpsCase")
    runs = {}
    for run in ledger(driver, "OpsRun"):
        runs.setdefault(run["case_id"], []).append(run)
    executions = {}
    for e in ledger(driver, "OpsExecution"):
        executions.setdefault(e["case_id"], []).append(e)
    outcomes = {}
    for o in ledger(driver, "OpsOutcome"):
        outcomes.setdefault(o["case_id"], []).append(o)
    decisions = {d["case_id"] for d in ledger(driver, "OpsDecision")}
    rows = []
    for case in cases:
        row = truth[case["shipment_id"]]
        last = sorted(runs.get(case["entity_id"], []), key=lambda r: iso(r["recorded_at"]))
        analysis = json.loads(last[-1]["result_json"]) if last and last[-1].get("result_json") else {}
        inv = analysis.get("investigation") or {}
        cited = {i for h in inv.get("hypotheses") or [] for i in h.get("supporting_evidence_ids", []) + h.get("contradicting_evidence_ids", [])}
        retrieved = set(inv.get("retrieved_evidence_ids") or [])
        execs = executions.get(case["entity_id"], [])
        outs = outcomes.get(case["entity_id"], [])
        rows.append({
            "case_id": case["entity_id"], "shipment_id": case["shipment_id"], "opened_at": iso(case["opened_at"]),
            "symptoms": case.get("symptom_codes"), "investigations": len(last), "tool_calls": len(inv.get("steps") or []),
            "tools": [s["tool"] for s in inv.get("steps") or []], "mode": inv.get("mode"),
            "primary_cause": inv.get("primary_cause"), "confidence": inv.get("confidence"),
            "hypotheses": [[h["cause"], h["status"]] for h in inv.get("hypotheses") or []],
            "recommended_action": inv.get("recommended_action"), "review": (analysis.get("review") or {}).get("model_verdict"),
            "review_rounds": len(analysis.get("trace") or []), "degraded": [d["role"] for d in analysis.get("degraded") or []],
            "fact_check_unsupported": (analysis.get("checks") or {}).get("unsupported"),
            "authority": (analysis.get("authority") or {}).get("risk_class"), "authority_reason": (analysis.get("authority") or {}).get("reason"),
            "executions": [{"action_type": e.get("action_type"), "authority": e.get("authority"), "status": e.get("status"),
                            "adapter": json.loads(e.get("adapter_result_json") or "{}").get("behaviour")} for e in execs],
            "outcomes": [{"type": o.get("outcome_type"), "success": o.get("success"), "verifier": o.get("verifier_id")} for o in outs],
            "final_state": case["workflow_state"], "human_decision": case["entity_id"] in decisions,
            "citations_within_retrieved": cited <= retrieved, "cited": len(cited),
            "key_evidence_cited": (bool(cited & set(row.get("key_evidence") or [])) if row.get("key_evidence") else None),
            # Scoring only:
            "truth_recipe": row["recipe"], "truth_healthy": row["healthy"], "truth_cause": row["root_cause"],
            "acceptable_causes": row["acceptable_causes"], "expected_resolution": row["expected_resolution"]})
    return rows


def metrics(rows, truth):
    live = {sid: r for sid, r in truth.items() if r["split"] == "development"}
    abnormal = {sid for sid, r in live.items() if not r["healthy"]}
    investigated = [r for r in rows if r["primary_cause"] is not None or r["degraded"]]
    scored = [r for r in investigated if not r["truth_healthy"]]
    correct = [r for r in scored if r["primary_cause"] in (r["acceptable_causes"] or [])]
    auto_exec = [r for r in rows if any(e["authority"] == "AUTO_POLICY" for e in r["executions"])]
    resolved = [r for r in rows if r["final_state"] == "RESOLVED"]
    false_resolutions = [r for r in resolved if r["truth_healthy"] or r["expected_resolution"] != "AUTO"
                         or r["primary_cause"] not in (r["acceptable_causes"] or [])]
    auto_eligible = [sid for sid in abnormal if live[sid]["expected_resolution"] == "AUTO"]
    auto_resolved_eligible = [r for r in resolved if r["shipment_id"] in auto_eligible and not r["human_decision"]]
    wrong_auto = [r for r in auto_exec if r["primary_cause"] not in (r["acceptable_causes"] or [])]
    wrong_routed_to_human = [r for r in scored if r not in correct and r["authority"] in ("HUMAN_REVIEW", "APPROVAL_REQUIRED")]
    return {
        "live_shipments": len(live), "abnormal_live_shipments": len(abnormal), "cases_opened": len(rows),
        "cases_on_healthy_shipments": sum(r["truth_healthy"] for r in rows),
        "abnormal_without_case": len(abnormal - {r["shipment_id"] for r in rows}),
        "investigations_completed": len(investigated), "degraded_investigations": sum(bool(r["degraded"]) for r in rows),
        "root_cause_accuracy": {"correct": len(correct), "scored": len(scored), "rate": round(len(correct) / len(scored), 3) if scored else None},
        "wrong_cause_but_routed_to_a_person": len(wrong_routed_to_human),
        "evidence_correctness": {"citations_within_retrieved": sum(r["citations_within_retrieved"] for r in investigated),
                                 "investigations": len(investigated),
                                 "key_evidence_cited": sum(bool(r["key_evidence_cited"]) for r in investigated if r["key_evidence_cited"] is not None),
                                 "with_key_evidence_defined": sum(r["key_evidence_cited"] is not None for r in investigated)},
        "automatic_actions_executed": len(auto_exec),
        "automatic_actions_with_wrong_cause": len(wrong_auto),
        "automatic_resolution_success": {"auto_executed_and_verified_resolved": sum(r["final_state"] == "RESOLVED" for r in auto_exec),
                                         "auto_executed": len(auto_exec),
                                         "rate": round(sum(r["final_state"] == "RESOLVED" for r in auto_exec) / len(auto_exec), 3) if auto_exec else None},
        "auto_eligible_scenarios_resolved_without_human": {"resolved": len(auto_resolved_eligible), "eligible": len(auto_eligible)},
        "false_resolution": {"count": len(false_resolutions), "resolved": len(resolved),
                             "rate": round(len(false_resolutions) / len(resolved), 3) if resolved else None,
                             "cases": [[r["case_id"], r["truth_recipe"], r["primary_cause"]] for r in false_resolutions]},
        "final_states": {s: sum(r["final_state"] == s for r in rows) for s in sorted({r["final_state"] for r in rows})},
        "verification_failures_left_unresolved": sum(any(o["success"] is False for o in r["outcomes"]) and r["final_state"] != "RESOLVED" for r in rows),
        "human_decisions_recorded": sum(r["human_decision"] for r in rows),
    }


def bundle_dir(tmp):
    return Path(tmp.name) / "bundle"


def phase_pipeline(out, total, started_at):
    from operations import investigator
    driver, bundle, truth, tmp = build_test_database(total=total)
    store = make_store(driver, bundle, agents=investigator)
    attach(store, truth)
    started = time.perf_counter()
    step_loop(store)
    rows = case_rows(driver, truth)
    result = {"phase": "pipeline", "model": config.LLM_MODEL, "wall_seconds": round(time.perf_counter() - started),
              "provenance": provenance("pipeline", started_at, bundle_dir=bundle_dir(tmp)),
              "metrics": metrics(rows, truth), "cases": rows}
    (out / "pipeline.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    tmp.cleanup()
    return result["metrics"]


def phase_heldout(out, total, started_at):
    driver, bundle, truth, tmp = build_test_database(total=total, live_split="held_out")
    store = make_store(driver, bundle)
    step_loop(store, investigate=False)
    cases = ledger(driver, "OpsCase")
    live = {sid: r for sid, r in truth.items() if r["split"] == "development"}
    with_case = {c["shipment_id"] for c in cases}
    healthy = [s for s, r in live.items() if r["healthy"]]
    abnormal = [s for s, r in live.items() if not r["healthy"]]
    result = {"phase": "heldout_detection", "replayed_split": "held_out (relabelled as the live split)", "shipments": len(live),
              "healthy": len(healthy), "abnormal": len(abnormal),
              "false_positive_cases": sorted([s, live[s]["recipe"]] for s in healthy if s in with_case),
              "missed_abnormal": sorted([s, live[s]["recipe"]] for s in abnormal if s not in with_case)}
    result["false_positive_rate"] = round(len(result["false_positive_cases"]) / len(healthy), 4) if healthy else None
    result["recall"] = round(1 - len(result["missed_abnormal"]) / len(abnormal), 4) if abnormal else None
    result["per_shipment"] = sorted([s, live[s]["recipe"], live[s]["healthy"], s in with_case] for s in live)
    result["provenance"] = provenance("heldout", started_at, bundle_dir=bundle_dir(tmp))
    (out / "heldout_detection.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    tmp.cleanup()
    return result


def phase_reviewer(out, total, started_at):
    """D: the real investigator runs; the reviewer's provider endpoint is unreachable."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_litellm import ChatLiteLLM
    from llm.pipeline import _llm
    from operations import investigator
    broken = ChatLiteLLM(model=config.LLM_MODEL, api_key=config.LLM_API_KEY, api_base="http://127.0.0.1:9/v1", temperature=0,
                         request_timeout=10, max_retries=0)
    def unreachable(system, user, default):
        return _llm.parse_json(_llm.message_text(broken.invoke([SystemMessage(system), HumanMessage(user)]).content)) or default
    module = types.SimpleNamespace(investigate=investigator.investigate,
                                   review=lambda c, r, k, s: investigator.review(c, r, k, s, ask=unreachable))
    driver, bundle, truth, tmp = build_test_database(total=total)
    store = make_store(driver, bundle, agents=module)
    attach(store, truth)
    processed = None
    while processed is None and store.status()["as_of"] < store.status()["simulator"]["end_at"]:
        store.tick(seconds=3600, manual=True, speed=1)
        while store.status()["session"]["monitor_pending"]:
            store.monitor_step(limit=25)
        target = next((c for c in ledger(driver, "OpsCase") if c["workflow_state"] == "OPEN"
                       and truth[c["shipment_id"]]["recipe"] in ("different_barcode", "different_weight")), None)
        if target:
            processed = store.process_one(case_id=target["entity_id"])
            store.execute_step(limit=10)
    case = next(c for c in ledger(driver, "OpsCase") if c["entity_id"] == processed["case_id"])
    audit = [a for a in ledger(driver, "OpsAudit") if a.get("case_id") == case["entity_id"]]
    run = json.loads(next(r for r in ledger(driver, "OpsRun") if r["case_id"] == case["entity_id"])["result_json"])
    result = {"phase": "reviewer_failure", "case_id": case["entity_id"], "truth_recipe": truth[case["shipment_id"]]["recipe"],
              "investigator_mode": (run.get("investigation") or {}).get("mode"), "primary_cause": (run.get("investigation") or {}).get("primary_cause"),
              "review": run.get("review"), "degraded": run.get("degraded"), "authority": run.get("authority"),
              "final_state": case["workflow_state"], "executions": [e for e in ledger(driver, "OpsExecution") if e["case_id"] == case["entity_id"]],
              "stored_reviews": [{k: r.get(k) for k in ("verdict", "model_verdict", "degraded", "mode", "summary_en", "summary_ar")}
                                 for r in ledger(driver, "OpsReview") if r["case_id"] == case["entity_id"]],
              "audit_events": sorted({a["event_type"] for a in audit}),
              "provenance": provenance("reviewer", started_at, bundle_dir=bundle_dir(tmp))}
    (out / "reviewer_failure.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    tmp.cleanup()
    return result


def phase_concurrency(out, total, seconds, started_at):
    from operations import investigator
    from operations.workers import WorkerPool
    import os
    os.environ["SUHAIL_WORKER_PACE_SECONDS"] = "0"
    driver, bundle, truth, tmp = build_test_database(total=total)
    store = make_store(driver, bundle, agents=investigator)
    attach(store, truth)
    store.control("simulator", "start", speed=600)
    # First: automatic investigation paused. Ingestion and monitoring must still progress.
    pool = WorkerPool(store).start()
    before = store.status()
    time.sleep(60)
    paused = store.status()
    paused_check = {"events_ingested": paused["simulator"]["event_count"] - before["simulator"]["event_count"],
                    "monitor_checks": paused["session"]["monitor_checked"] - before["session"]["monitor_checked"],
                    "cases_opened": paused["session"]["monitor_opened"] - before["session"]["monitor_opened"],
                    "investigations_run": paused["worker"]["processed_count"] - before["worker"]["processed_count"]}
    store.control("worker", "start")
    samples, stop = [], threading.Event()
    def sample():
        while not stop.wait(3):
            status = store.status()
            samples.append({"wall": time.time(), "as_of": status["as_of"], "events": status["simulator"]["event_count"],
                            "monitor_checked": status["session"]["monitor_checked"], "active_case": status["worker"]["active_case_id"],
                            "investigation_busy": pool.workers["investigation"].heartbeat["busy"]})
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    time.sleep(seconds)
    stop.set(); pool.stop()
    store.control("simulator", "pause"); store.control("worker", "pause")
    windows, current = [], None
    for s in samples:
        if s["active_case"] and (current is None or current["case"] != s["active_case"]):
            current = {"case": s["active_case"], "start": s, "end": s}
            windows.append(current)
        elif s["active_case"] and current:
            current["end"] = s
        else:
            current = None
    spans = [{"case_id": w["case"], "wall_seconds": round(w["end"]["wall"] - w["start"]["wall"]),
              "events_ingested_meanwhile": w["end"]["events"] - w["start"]["events"],
              "monitor_checks_meanwhile": w["end"]["monitor_checked"] - w["start"]["monitor_checked"],
              "simulated_clock": [w["start"]["as_of"], w["end"]["as_of"]]} for w in windows if w["end"]["wall"] > w["start"]["wall"]]
    result = {"phase": "concurrency", "model": config.LLM_MODEL, "run_seconds": seconds, "samples": len(samples),
              "investigation_paused_check": paused_check,
              "investigation_windows": spans, "worker_heartbeats": pool.status(),
              "total_events": samples[-1]["events"] if samples else 0,
              "provenance": provenance("concurrency", started_at, bundle_dir=bundle_dir(tmp))}
    (out / "concurrency.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    tmp.cleanup()
    return result


def phase_checks(out, total, started_at):
    """On the database the pipeline phase left behind: public ids, authority switch, trigger coverage, and a
    scan of every receipt, outcome, audit entry, review, recommendation and case API response for answer-key words."""
    from core.query_runner import get_driver
    from dataset_v2.contracts import Config
    from dataset_v2.live_bundle import truth_vocabulary
    from operations.identifiers import public_value
    from operations.read_model import OperationsReader
    driver = get_driver()
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        imported = session.run("MATCH (m:_V2Import) RETURN m.manifest_json AS m, m.manifest_hash AS h").single()
        manifest = json.loads(imported["m"])
        clock = iso(session.run("MATCH (c:OpsEntity:OpsControl) RETURN c.as_of AS a").single()["a"])
    cfg = Config(**manifest["config"])
    from operations.store import OperationsStore
    reader = OperationsReader(driver, TEST_DATABASE, cfg.dataset_id, cfg, clock=lambda: clock)
    # Read-only use of the ledger (no initialize, no reset): the case detail an operator would open.
    reader.store = OperationsStore(driver, TEST_DATABASE, cfg.dataset_id, cfg, reader=reader)
    cases = ledger(driver, "OpsCase")
    runs = {}
    for run in ledger(driver, "OpsRun"):
        runs.setdefault(run["case_id"], []).append(run)
    resolvable = cited_total = telemetry_cited = 0
    unresolved_ids = []
    api_details = []
    for case in cases:
        if not runs.get(case["entity_id"]):
            continue
        last = sorted(runs[case["entity_id"]], key=lambda r: iso(r["recorded_at"]))[-1]
        inv = (json.loads(last.get("result_json") or "{}").get("investigation") or {})
        detail = public_value(reader.case_detail(case["entity_id"]))
        api_details.append(json.dumps(detail, default=str, ensure_ascii=False))
        nodes = {n["id"] for n in detail["evidence"]["nodes"]}
        for h in inv.get("hypotheses") or []:
            for key in public_value(h.get("supporting_evidence_ids", []) + h.get("contradicting_evidence_ids", [])):
                cited_total += 1
                if key in nodes:
                    resolvable += 1
                elif key.startswith("SYN-DEV-"):
                    telemetry_cited += 1
                else:
                    unresolved_ids.append([case["entity_id"], key])
    audits = ledger(driver, "OpsAudit")
    decisions = {a["case_id"]: json.loads(a["result"]) for a in audits if a.get("event_type") == "AUTHORITY_DECISION" and a["result"].startswith("{")}
    approvals = {d["case_id"] for d in ledger(driver, "OpsDecision") if d.get("decision") == "approve"}
    bypass = []
    for e in ledger(driver, "OpsExecution"):
        if e.get("authority") == "AUTO_POLICY" and (decisions.get(e["case_id"]) or {}).get("risk_class") != "AUTO":
            bypass.append(e["entity_id"])
        if e.get("authority") != "AUTO_POLICY" and e["case_id"] not in approvals:
            bypass.append(e["entity_id"])
    triggers = {}
    for case in cases:
        for symptom in case.get("symptom_codes") or []:
            triggers[symptom] = triggers.get(symptom, 0) + 1
    for case in cases:  # Cases never investigated are served by the API too.
        if not runs.get(case["entity_id"]):
            api_details.append(json.dumps(public_value(reader.case_detail(case["entity_id"])), default=str, ensure_ascii=False))
    vocabulary = [t.lower() for t in truth_vocabulary(scoring_truth(total, imported["h"]))]
    sources = {"execution_receipts": [e.get("adapter_result_json") for e in ledger(driver, "OpsExecution")],
               "outcomes": [json.dumps({k: o.get(k) for k in ("outcome_type", "reason", "expected_effect", "rule_id")}) for o in ledger(driver, "OpsOutcome")],
               "audit": [a.get("result") for a in audits],
               "reviews": [json.dumps({k: r.get(k) for k in ("verdict", "feedback", "summary_en", "summary_ar")}, ensure_ascii=False) for r in ledger(driver, "OpsReview")],
               "recommendations": [json.dumps({k: r.get(k) for k in ("action", "action_en", "action_ar", "authority_reason")}, ensure_ascii=False)
                                   for r in ledger(driver, "OpsRecommendation")],
               "case_api_responses": api_details}
    leaks = []
    for source, texts in sources.items():
        for text in texts:
            lowered = (text or "").lower()
            for term in vocabulary:
                at = lowered.find(term)
                if at >= 0:
                    leaks.append({"source": source, "term": term, "excerpt": (text or "")[max(0, at - 60):at + len(term) + 60]})
    result = {"phase": "checks", "public_id_resolution": {"cited": cited_total, "resolve_to_case_evidence": resolvable,
              "device_telemetry_citations": telemetry_cited, "unresolved": cited_total - resolvable - telemetry_cited,
              "unresolved_ids": unresolved_ids[:50]},
              "authority_bypass_executions": bypass, "executions": len(ledger(driver, "OpsExecution")),
              "authority_decisions_recorded": len(decisions), "trigger_symptoms": triggers,
              "answer_key_scan": {"terms": len(vocabulary), "records_scanned": {k: len(v) for k, v in sources.items()},
                                  "leaks": leaks[:100], "leak_count": len(leaks)},
              "provenance": provenance("checks", started_at, manifest_hash=imported["h"])}
    (out / "checks.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return result


def end_state(row):
    """What happened to a case after its diagnosis, in the terms of the S5 accounting."""
    outcomes = row["outcomes"]
    if row["executions"]:
        if row["final_state"] == "RESOLVED":
            return "executed_and_verified_resolved"
        if any(o["success"] for o in outcomes):
            return "executed_and_verified_but_exception_remained_unresolved"
        if any(o["success"] is False for o in outcomes):
            return "executed_verification_failed_unresolved"
        return "executed_verification_pending"
    if row["final_state"] == "AWAITING_APPROVAL":
        return "approval_pending"
    return "routed_to_a_person_" + row["final_state"].lower()


def phase_accounting(out, total, source, started_at):
    """After a pipeline run, on the database it left: every wrong diagnosis's end state, whether each
    resolved case's exception was really gone at closure, and what happened to two-cause shipments."""
    from core.query_runner import get_driver
    from dataset_v2.contracts import Config
    from dataset_v2.derive import assess_shipment
    from operations.read_model import OperationsReader
    from operations.reasoning import evidence_world
    from operations.store import DETECTION_ALLOWANCE_SECONDS, STANDING_SYMPTOMS, monitor_finding
    pipeline = json.loads((out / source).read_text(encoding="utf-8"))
    rows = pipeline["cases"]
    driver = get_driver()
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        imported = session.run("MATCH (m:_V2Import) RETURN m.manifest_json AS m, m.manifest_hash AS h").single()
        clock = iso(session.run("MATCH (c:OpsEntity:OpsControl) RETURN c.as_of AS a").single()["a"])
    truth = scoring_truth(total, imported["h"])
    cfg = Config(**json.loads(imported["m"])["config"])
    reader = OperationsReader(driver, TEST_DATABASE, cfg.dataset_id, cfg, clock=lambda: clock)
    cases = {c["entity_id"]: c for c in ledger(driver, "OpsCase")}

    def standing(sid, at):
        world = evidence_world(reader.evidence(sid, at), cfg)
        found = monitor_finding(assess_shipment(world, sid, at, detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS))
        return sorted(set(found["symptoms"]) & STANDING_SYMPTOMS)

    wrong = [r for r in rows if not r["truth_healthy"] and r["primary_cause"] not in (r["acceptable_causes"] or [])]
    resolved = []
    for r in rows:
        if r["final_state"] != "RESOLVED":
            continue
        closed = iso(cases[r["case_id"]].get("closed_at"))
        later = [c["entity_id"] for c in cases.values() if c["shipment_id"] == r["shipment_id"] and iso(c["opened_at"]) > closed]
        resolved.append({"case_id": r["case_id"], "shipment_id": r["shipment_id"], "truth_recipe": r["truth_recipe"],
                         "primary_cause": r["primary_cause"], "closed_at": closed,
                         "standing_symptoms_at_closure": standing(r["shipment_id"], closed),
                         "standing_symptoms_at_end": standing(r["shipment_id"], clock), "later_cases": later})
    two_cause = []
    for sid, t in sorted(truth.items()):
        if t["split"] != "development" or not t.get("secondary_issue"):
            continue
        two_cause.append({"shipment_id": sid, "recipe": t["recipe"], "root_cause": t["root_cause"], "secondary_issue": t["secondary_issue"],
                          "second_cause_source": "truth generator: depot handheld outage window (propagate_outages)",
                          "outage_affected_event_ids": t.get("outage_affected_event_ids"),
                          "cases": [{"case_id": r["case_id"], "opened_at": r["opened_at"], "symptoms": r["symptoms"], "primary_cause": r["primary_cause"],
                                     "executions": r["executions"], "outcomes": r["outcomes"], "final_state": r["final_state"],
                                     "case_symptoms_now": cases[r["case_id"]].get("symptom_codes")}
                                    for r in sorted(rows, key=lambda x: x["opened_at"]) if r["shipment_id"] == sid],
                          "standing_symptoms_at_end": standing(sid, clock)})
    result = {"phase": "accounting", "source": source, "database": TEST_DATABASE, "clock": clock,
              "wrong_diagnoses": [{"case_id": r["case_id"], "shipment_id": r["shipment_id"], "truth_recipe": r["truth_recipe"],
                                   "acceptable_causes": r["acceptable_causes"], "primary_cause": r["primary_cause"],
                                   "authority": r["authority"], "executions": [e["action_type"] for e in r["executions"]],
                                   "end_state": end_state(r)} for r in wrong],
              "wrong_diagnosis_end_states": {s: sum(end_state(r) == s for r in wrong) for s in sorted({end_state(r) for r in wrong})},
              "false_resolutions_on_wrong_cause": [r["case_id"] for r in wrong if end_state(r) == "executed_and_verified_resolved"],
              "resolved_cases": resolved,
              "resolved_with_standing_symptom_at_closure": [x["case_id"] for x in resolved if x["standing_symptoms_at_closure"]],
              "two_cause_shipments": two_cause}
    (out / source.replace("pipeline", "accounting")).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=("pipeline", "checks", "accounting", "heldout", "reviewer", "concurrency", "human"))
    parser.add_argument("--source", default="pipeline.json", help="accounting: the pipeline result file in --out")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--total", type=int, default=600)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--allow-dirty", action="store_true", help="run on uncommitted tracked changes (results say so)")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    commit, dirty = git_state()
    if dirty and not args.allow_dirty:
        raise SystemExit(f"Tracked files differ from {commit[:12]}; commit first so results name the exact code (or pass --allow-dirty).")
    started_at = datetime.now(timezone.utc).isoformat()
    record_model_calls()
    result = {"pipeline": lambda: phase_pipeline(args.out, args.total, started_at),
              "checks": lambda: phase_checks(args.out, args.total, started_at),
              "accounting": lambda: phase_accounting(args.out, args.total, args.source, started_at),
              "heldout": lambda: phase_heldout(args.out, args.total, started_at),
              "reviewer": lambda: phase_reviewer(args.out, args.total, started_at),
              "concurrency": lambda: phase_concurrency(args.out, args.total, args.seconds, started_at),
              "human": lambda: phase_human(args.out, args.total, started_at)}[args.phase]()
    print(json.dumps(result, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
