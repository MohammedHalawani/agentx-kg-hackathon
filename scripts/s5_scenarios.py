"""S5: end-to-end scenarios A-F and measured metrics, on an isolated Neo4j test database.

Order. On the pipeline database: pipeline, then accounting, human and checks (checks last, so its
answer-key scan sees everything the other phases wrote). heldout, reviewer and concurrency each recreate
their database, so run them on the twin (SUHAIL_TEST_DATABASE=shipments-v2-demo-test2). accounting, human
and checks refuse to run on a ledger that is not the one pipeline.json in --out describes.

Phases:
  pipeline   live split replayed hour by hour through the gateway, monitor, real GPT-OSS
             investigation (tool loop + reviewer), authority, execution adapter (synthetic
             operational simulator) and the independent verifier. Scenarios A, B, C, E + metrics.
  heldout    the held-out split replayed as the live split through the real gateway and monitor
             (no model): official detection false positives and recall.
  reviewer   scenario D: one case investigated with the reviewer pointed at an unreachable endpoint.
  concurrency scenario F: the separated workers run with the real model while the clock advances;
             ingestion and monitoring progress is sampled during each investigation.
  checks     on the database a pipeline run left: public evidence ids, authority bypass, case triggers, answer-key scan.
  accounting on the same database: every wrong diagnosis's end state, whether each resolved case's
             exception was gone at closure, what happened to shipments with two genuine causes, and how much
             symptom naming and the second-cause credit contribute to the score.
  human      on the same database: scenario C's human path (a person's verified finding) and both approval
             outcomes (a person-only action refused, an approvable action executed).
Every results file carries a provenance block (commit and dirty flag at start, and whether the tree
changed during the run; bundle hashes, model, prompt hashes, model calls by the model name the provider
reported). Phases that run product code (pipeline, heldout, reviewer, concurrency, human) refuse to run on
uncommitted tracked changes; checks and accounting only read, and record the flag.

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
CODE_STATE = {}  # Commit and dirty flag captured in main() before any phase imports product code.


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
    commit, dirty = CODE_STATE.get("commit"), CODE_STATE.get("dirty")
    now_commit, now_dirty = git_state()
    record = {"phase": phase, "commit": commit, "dirty_tree": dirty,
              "tree_changed_during_run": (now_commit, now_dirty) != (commit, dirty), "started_at": started_at,
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
    from dataset_v2.contracts import instant
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
    opening = {a["case_id"]: sorted(x.strip() for x in a["result"].split(":", 1)[1].split(","))
               for a in ledger(driver, "OpsAudit") if a.get("event_type") == "CASE_OPENED" and ":" in (a.get("result") or "")}
    key_ids = sorted({k for c in cases for k in truth[c["shipment_id"]].get("key_evidence") or []})
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        ingested = {r["id"]: iso(r["at"]) for r in session.run(
            "MATCH (n:V2Entity) WHERE n.entity_id IN $ids RETURN n.entity_id AS id, n.recorded_at AS at", ids=key_ids)}
    rows = []
    for case in cases:
        row = truth[case["shipment_id"]]
        last = sorted(runs.get(case["entity_id"], []), key=lambda r: iso(r["recorded_at"]))
        analysis = json.loads(last[-1]["result_json"]) if last and last[-1].get("result_json") else {}
        inv = analysis.get("investigation") or {}
        cited = {i for h in inv.get("hypotheses") or [] for i in h.get("supporting_evidence_ids", []) + h.get("contradicting_evidence_ids", [])}
        snapshot = next((e.get("evidence_as_of") for e in analysis.get("pipeline_events") or [] if e.get("evidence_as_of")), None)
        # Key evidence the investigation could have seen: ingested by the time of its evidence snapshot.
        key_visible = {k for k in row.get("key_evidence") or [] if snapshot and ingested.get(k) and instant(ingested[k]) <= instant(iso(snapshot))}
        retrieved = set(inv.get("retrieved_evidence_ids") or [])
        execs = executions.get(case["entity_id"], [])
        outs = outcomes.get(case["entity_id"], [])
        rows.append({
            "case_id": case["entity_id"], "shipment_id": case["shipment_id"], "opened_at": iso(case["opened_at"]),
            "symptoms": case.get("symptom_codes"), "opening_symptoms": opening.get(case["entity_id"]),
            "investigations": len(last), "tool_calls": len(inv.get("steps") or []),
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
            "key_evidence_cited": (bool(cited & key_visible) if key_visible else None),
            "key_evidence_not_yet_ingested": bool(row.get("key_evidence")) and not key_visible,
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
    from operations.authority import HUMAN_FLOOR_SYMPTOMS
    auto_eligible = {sid for sid in abnormal if live[sid]["expected_resolution"] == "AUTO"}
    by_shipment = {}
    for r in rows:
        by_shipment.setdefault(r["shipment_id"], []).append(r)
    # A shipment counts only when every one of its cases ended resolved with no human decision.
    clean = {sid for sid in auto_eligible if by_shipment.get(sid)
             and all(r["final_state"] == "RESOLVED" and not r["human_decision"] for r in by_shipment[sid])}
    floored = {sid for sid in auto_eligible if any(set(r.get("opening_symptoms") or r["symptoms"] or []) & HUMAN_FLOOR_SYMPTOMS
                                                   for r in by_shipment.get(sid, []))}
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
                                 "with_key_evidence_visible_at_investigation": sum(r["key_evidence_cited"] is not None for r in investigated),
                                 "key_evidence_not_yet_ingested_at_investigation": sum(bool(r.get("key_evidence_not_yet_ingested")) for r in investigated)},
        "automatic_actions_executed": len(auto_exec),
        "automatic_actions_with_wrong_cause": len(wrong_auto),
        "automatic_resolution_success": {"auto_executed_and_verified_resolved": sum(r["final_state"] == "RESOLVED" for r in auto_exec),
                                         "auto_executed": len(auto_exec),
                                         "rate": round(sum(r["final_state"] == "RESOLVED" for r in auto_exec) / len(auto_exec), 3) if auto_exec else None},
        "auto_eligible_shipments_resolved_without_human": {
            "resolved": len(clean), "eligible": len(auto_eligible),
            "eligible_without_a_human_floor_symptom": len(auto_eligible - floored), "resolved_among_those": len(clean - floored),
            "note": "per shipment: every case of the shipment ended RESOLVED with no human decision; a human-floor symptom "
                    "(session end unreconciled, conflicting reports, manifest conflict, recipient report) never closes automatically"},
        "false_resolution": {"count": len(false_resolutions), "resolved": len(resolved),
                             "rate": round(len(false_resolutions) / len(resolved), 3) if resolved else None,
                             "cases": [[r["case_id"], r["truth_recipe"], r["primary_cause"]] for r in false_resolutions]},
        "final_states": {s: sum(r["final_state"] == s for r in rows) for s in sorted({r["final_state"] for r in rows})},
        "verification_failures_left_unresolved": sum(any(o["success"] is False for o in r["outcomes"]) and r["final_state"] != "RESOLVED" for r in rows),
        "human_decisions_recorded": sum(r["human_decision"] for r in rows),
    }


def bundle_dir(tmp):
    return Path(tmp.name) / "bundle"


def ledger_identity(driver):
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        session_id = session.run("MATCH (c:OpsEntity:OpsControl) RETURN c.session_id AS s").single()["s"]
    return {"session_id": session_id, "cases": len(ledger(driver, "OpsCase")), "runs": len(ledger(driver, "OpsRun"))}


def require_pipeline_ledger(out, driver):
    """accounting, human and checks read the ledger a pipeline run left; refuse any other ledger."""
    source = out / "pipeline.json"
    if not source.exists():
        raise SystemExit(f"{source} is missing: run --phase pipeline into this --out first.")
    expected = json.loads(source.read_text(encoding="utf-8")).get("ledger")
    found = ledger_identity(driver)
    if not expected or any(found[k] != expected[k] for k in ("session_id", "cases", "runs")):
        raise SystemExit(f"{TEST_DATABASE} holds a different ledger ({found}) from {source} ({expected}).")
    return found


def phase_pipeline(out, total, started_at):
    from operations import investigator
    driver, bundle, truth, tmp = build_test_database(total=total)
    store = make_store(driver, bundle, agents=investigator)
    attach(store, truth)
    started = time.perf_counter()
    step_loop(store)
    rows = case_rows(driver, truth)
    result = {"phase": "pipeline", "model": config.LLM_MODEL, "wall_seconds": round(time.perf_counter() - started),
              "provenance": provenance("pipeline", started_at, bundle_dir=bundle_dir(tmp)), "ledger": ledger_identity(driver),
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
    waited = 0
    # Keep investigation paused until the monitor has opened at least two cases (bounded), so the check
    # shows cases waiting while nothing investigates them.
    while waited < 60 or (store.status()["session"]["monitor_opened"] - before["session"]["monitor_opened"] < 2 and waited < 300):
        time.sleep(5)
        waited += 5
    paused = store.status()
    open_cases = [c for c in ledger(driver, "OpsCase") if c["workflow_state"] == "OPEN"]
    paused_check = {"paused_seconds": waited, "events_ingested": paused["simulator"]["event_count"] - before["simulator"]["event_count"],
                    "monitor_checks": paused["session"]["monitor_checked"] - before["session"]["monitor_checked"],
                    "cases_opened": paused["session"]["monitor_opened"] - before["session"]["monitor_opened"],
                    "cases_waiting_open": len(open_cases),
                    "investigations_run": paused["worker"]["processed_count"] - before["worker"]["processed_count"],
                    "runs_recorded": len(ledger(driver, "OpsRun"))}
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


def phase_checks(out, _total, started_at):
    """On the database the pipeline phase left behind: public ids, authority switch, trigger coverage, and a
    scan of every receipt, outcome, audit entry, review, recommendation and case API response for answer-key words."""
    from core.query_runner import get_driver
    from dataset_v2.contracts import Config
    from dataset_v2.live_bundle import truth_state_words, truth_vocabulary
    from operations.identifiers import public_value
    from operations.read_model import OperationsReader
    driver = get_driver()
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        imported = session.run("MATCH (m:_V2Import) RETURN m.manifest_json AS m, m.manifest_hash AS h").single()
        manifest = json.loads(imported["m"])
        clock = iso(session.run("MATCH (c:OpsEntity:OpsControl) RETURN c.as_of AS a").single()["a"])
    cfg = Config(**manifest["config"])
    total = cfg.total  # The imported dataset's own size, not a command-line guess.
    identity = require_pipeline_ledger(out, driver)
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
    decisions = [a for a in audits if a.get("event_type") == "AUTHORITY_DECISION"]
    # Each execution is matched to what authorized it: an automatic one to the authority decision of the run
    # whose recommendation initiated it, an operator one to its own approve decision.
    from operations.authority import ACTIONS
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        initiated = {r["e"]: r["s"] for r in session.run(
            "MATCH (s:OpsEntity)-[:OPS_INITIATES]->(e:OpsEntity:OpsExecution) RETURN s.entity_id AS s, e.entity_id AS e")}
    recommendations = {r["entity_id"]: r for r in ledger(driver, "OpsRecommendation")}
    run_authority = {r["entity_id"]: (json.loads(r.get("result_json") or "{}").get("authority") or {}) for r in ledger(driver, "OpsRun")}
    approve_decisions = {d["entity_id"]: d for d in ledger(driver, "OpsDecision") if d.get("decision") == "approve"}
    bypass, checked = [], []
    for e in ledger(driver, "OpsExecution"):
        base = (ACTIONS.get(e.get("action_type")) or ("?",))[0]
        if e.get("authority") == "AUTO_POLICY":
            recommendation = recommendations.get(initiated.get(e["entity_id"]) or "") or {}
            decided = run_authority.get(recommendation.get("run_id") or "", {})
            ok = base == "AUTO" and decided.get("risk_class") == "AUTO" and e.get("decided_risk") == "AUTO"
        else:
            decision = approve_decisions.get(e.get("decision_id") or "")
            ok = bool(decision) and decision["case_id"] == e["case_id"] and base in ("AUTO", "APPROVAL_REQUIRED")
        checked.append({"execution": e["entity_id"], "authority": e.get("authority"), "action_type": e.get("action_type"),
                        "status": e.get("status"), "permission_rule": e.get("permission_rule"), "authorized_by_its_own_decision": ok})
        if not ok:
            bypass.append(e["entity_id"])
    opening = {}
    for a in audits:  # What opened each case (the final symptom set grows after opening).
        if a.get("event_type") == "CASE_OPENED" and ":" in (a.get("result") or ""):
            for symptom in a["result"].split(":", 1)[1].split(","):
                opening[symptom.strip()] = opening.get(symptom.strip(), 0) + 1
    final_sets = {}
    for case in cases:
        for symptom in case.get("symptom_codes") or []:
            final_sets[symptom] = final_sets.get(symptom, 0) + 1
    for case in cases:  # Cases never investigated are served by the API too.
        if not runs.get(case["entity_id"]):
            api_details.append(json.dumps(public_value(reader.case_detail(case["entity_id"])), default=str, ensure_ascii=False))
    truth = scoring_truth(total, imported["h"])
    vocabulary = [t.lower() for t in truth_vocabulary(truth)]
    state_words = truth_state_words(truth)
    sources = {"execution_receipts": [e.get("adapter_result_json") for e in ledger(driver, "OpsExecution")],
               "outcomes": [json.dumps({k: o.get(k) for k in ("outcome_type", "reason", "expected_effect", "rule_id")}) for o in ledger(driver, "OpsOutcome")],
               "audit": [a.get("result") for a in audits],
               "reviews": [json.dumps({k: r.get(k) for k in ("verdict", "feedback", "summary_en", "summary_ar")}, ensure_ascii=False) for r in ledger(driver, "OpsReview")],
               "recommendations": [json.dumps({k: r.get(k) for k in ("action", "action_en", "action_ar", "authority_reason")}, ensure_ascii=False)
                                   for r in ledger(driver, "OpsRecommendation")],
               "case_api_responses": api_details}
    sources["commands"] = [c.get("result_json") for c in ledger(driver, "OpsCommand")]
    leaks = []
    for source, texts in sources.items():
        for text in texts:
            lowered = (text or "").lower()
            for term in vocabulary:
                at = lowered.find(term)
                if at >= 0:
                    leaks.append({"source": source, "term": term, "excerpt": (text or "")[max(0, at - 60):at + len(term) + 60]})
    # Single-word field states and truth field names, as whole words, in text that no model wrote (receipts,
    # outcomes, commands and non-model audit entries): models may use ordinary words like "misread".
    import re
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in state_words) + r")\b", re.I) if state_words else None
    machine = {"execution_receipts": sources["execution_receipts"], "outcomes": sources["outcomes"], "commands": sources["commands"],
               "audit": [a.get("result") for a in audits if a.get("event_type") not in ("PIPELINE_STAGE", "AUTHORITY_DECISION", "RECOMMENDATION_READY")]}
    for source, texts in machine.items():
        for text in texts:
            for match in (pattern.finditer(text or "") if pattern else []):
                leaks.append({"source": source, "term": match.group(0), "excerpt": (text or "")[max(0, match.start() - 60):match.end() + 60]})
    result = {"phase": "checks", "public_id_resolution": {"cited": cited_total, "resolve_to_case_evidence": resolvable,
              "device_telemetry_citations": telemetry_cited, "unresolved": cited_total - resolvable - telemetry_cited,
              "unresolved_ids": unresolved_ids[:50]},
              "authority_bypass_executions": bypass, "executions": len(ledger(driver, "OpsExecution")), "executions_checked": checked,
              "authority_decisions_recorded": len(decisions), "opening_trigger_symptoms": opening, "final_symptom_sets": final_sets,
              "answer_key_scan": {"terms": len(vocabulary), "state_words": state_words,
                                  "records_scanned": {k: len(v) for k, v in sources.items()},
                                  "leaks": leaks[:100], "leak_count": len(leaks)},
              "ledger": identity, "provenance": provenance("checks", started_at, manifest_hash=imported["h"])}
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


def scoring_transparency(rows, truth):
    """How much the opening symptom names give away, and how much the second-cause credit adds.

    The monitor maps deterministic rule codes to symptoms (operations.store.SYMPTOMS); ten of the twelve
    symptoms come from exactly one rule code. The diagnosis labels are wider than the rule codes (delayed
    sync, hub delay, route delay, SLA risk and possible misdelivery have no rule code), so a symptom's
    single rule code is not necessarily the answer. What is reported: accuracy when an opening symptom's
    single rule code is an acceptable cause vs not, and how often the diagnosis equals that rule code.
    Scoring is per shipment: any acceptable cause of the shipment counts on every case of that shipment."""
    from operations.store import SYMPTOMS
    inverse = {}
    for cause, symptom in SYMPTOMS.items():
        inverse.setdefault(symptom, set()).add(cause)
    scored = [r for r in rows if not r["truth_healthy"] and (r["primary_cause"] is not None or r["degraded"])]

    def opening(r):
        return r.get("opening_symptoms") or r["symptoms"] or []

    def acceptable(r, with_second=True):
        second = truth[r["shipment_id"]].get("secondary_issue")
        causes = set(r["acceptable_causes"] or [])
        return causes if with_second or not second else causes - {second}

    def rate(group, with_second=True):
        good = sum(r["primary_cause"] in acceptable(r, with_second) for r in group)
        return {"correct": good, "cases": len(group), "rate": round(good / len(group), 3) if group else None}

    one_code = [r for r in scored if opening(r) and all(len(inverse.get(x, ())) == 1 for x in opening(r))]
    named = [r for r in scored if any(len(inverse.get(x, ())) == 1 and inverse[x] & acceptable(r) for x in opening(r))]
    strict = [r for r in scored if any(len(inverse.get(x, ())) == 1 and r["primary_cause"] in inverse[x] for x in opening(r))]
    inclusive = [r for r in scored if any(r["primary_cause"] in inverse.get(x, ()) for x in opening(r))]
    correct = [r for r in scored if r["primary_cause"] in acceptable(r)]
    only_sync = [r for r in scored if set(r["acceptable_causes"] or []) == {"DELAYED_SYNC"}]
    resolved = [r for r in rows if r["final_state"] == "RESOLVED"]
    triggers = {}
    for r in rows:
        for x in opening(r):
            triggers[x] = triggers.get(x, 0) + 1
    return {
        "symptoms_from_one_rule_code": sorted(x for x, causes in inverse.items() if len(causes) == 1),
        "symptoms_from_several_rule_codes": {x: sorted(c) for x, c in inverse.items() if len(c) > 1},
        "accuracy_all": rate(scored),
        "accuracy_by_opening_symptom_rule_codes": {
            "one_label_every_opening_symptom_from_one_rule_code": rate(one_code),
            "multi_label_an_opening_symptom_from_several_rule_codes": rate([r for r in scored if r not in one_code]),
            "caveat": ("a symptom from one rule code is not one diagnosis: delayed sync, hub delay, route delay, SLA risk and "
                       "possible misdelivery have no rule code, so an overdue milestone (one rule code) has several possible "
                       "causes; the named and not-named split below measures what the symptom name gives away")},
        "accuracy_when_an_opening_symptom_names_an_acceptable_cause": rate(named),
        "accuracy_when_no_opening_symptom_names_an_acceptable_cause": rate([r for r in scored if r not in named]),
        "diagnosis_equals_the_label_of_an_opening_symptom": {
            "strict_one_to_one": {"correct": sum(r in correct for r in strict), "wrong": sum(r not in correct for r in strict)},
            "inclusive": {"correct": sum(r in correct for r in inclusive), "wrong": sum(r not in correct for r in inclusive)},
            "correct_total": len(correct), "wrong_total": len(scored) - len(correct)},
        "second_cause_credit": {
            "source": "network.propagate_outages adds DELAYED_SYNC to acceptable_causes of abnormal shipments caught in another "
                      "shipment's handheld outage window (secondary_issue); introduced in e4207f9 together with the run that used it",
            "accuracy_with": rate(scored), "accuracy_without": rate(scored, with_second=False),
            "resolved_on_a_wrong_cause_with": sum(r["primary_cause"] not in acceptable(r) for r in resolved),
            "resolved_on_a_wrong_cause_without": sum(r["primary_cause"] not in acceptable(r, False) for r in resolved),
            "cases_credited_only_by_it": [r["case_id"] for r in scored if r["primary_cause"] in acceptable(r) and r["primary_cause"] not in acceptable(r, False)]},
        "delayed_sync_only_cases": rate(only_sync),
        "opening_trigger_symptoms": triggers,
        "scoring_unit": "per shipment: every case of a shipment is scored against all of that shipment's acceptable causes"}


def phase_accounting(out, _total, source, started_at):
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
    cfg = Config(**json.loads(imported["m"])["config"])
    truth = scoring_truth(cfg.total, imported["h"])
    identity = require_pipeline_ledger(out, driver)
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
              "two_cause_shipments": two_cause,
              "scoring_transparency": scoring_transparency(rows, truth), "ledger": identity,
              "provenance": provenance("accounting", started_at, manifest_hash=imported["h"]),
              "source_provenance": pipeline.get("provenance")}
    (out / source.replace("pipeline", "accounting")).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return result


def phase_human(out, _total, started_at):
    """On the database the pipeline left: the human path of scenario C and both approval outcomes.

    The harness plays the depot supervisor. Like the simulator, it reads the simulated field state to
    choose what a physical check would find, then records it through the same store call the dashboard
    uses (HUMAN_VERIFIED, kept apart from evidence-verified outcomes). It also tries to approve a
    person-only action (must be refused) and approves an action waiting for approval (must execute)."""
    from core.query_runner import get_driver
    from dataset_v2.contracts import Config
    from operations.lifecycle import OperationsConflict
    from operations.read_model import OperationsReader
    from operations.store import OperationsStore
    driver = get_driver()
    with driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
        imported = session.run("MATCH (m:_V2Import) RETURN m.manifest_json AS m, m.manifest_hash AS h").single()
        clock = iso(session.run("MATCH (c:OpsEntity:OpsControl) RETURN c.as_of AS a").single()["a"])
    cfg = Config(**json.loads(imported["m"])["config"])
    truth = scoring_truth(cfg.total, imported["h"])
    identity = require_pipeline_ledger(out, driver)
    reader = OperationsReader(driver, TEST_DATABASE, cfg.dataset_id, cfg, clock=lambda: clock)
    store = OperationsStore(driver, TEST_DATABASE, cfg.dataset_id, cfg, reader=reader)
    reader.store = store
    attach(store, truth)
    finds = {"retained_by_contractor": ("parcel_not_found", "Physical check at the depot: the parcel is not on site; the independent driver "
                                         "did not return it and does not answer."),
             "returned_unscanned": ("returned_to_depot", "Physical check at the depot: the parcel is on the returns shelf; it came back after "
                                    "the session without a receipt scan."),
             "left_at_depot": ("parcel_located", "Physical check at the depot: the parcel is on site and was never loaded.")}
    findings, used = [], set()
    # Re-runnable: a case this phase (or anyone) already closed by a person's finding is left alone.
    handled = {o["case_id"] for o in ledger(driver, "OpsOutcome") if o.get("verification_status") == "HUMAN_VERIFIED"}
    handled |= {c["case_id"] for c in ledger(driver, "OpsCommand") if str(c.get("idempotency_key") or "").startswith("s5-")}
    for case in sorted(ledger(driver, "OpsCase"), key=lambda c: iso(c["opened_at"])):
        physical = truth[case["shipment_id"]].get("physical") or {}
        kind = physical.get("parcel")
        if case["workflow_state"] not in ("HUMAN_REVIEW", "ESCALATED") or kind not in finds or kind in used or case["entity_id"] in handled:
            continue
        used.add(kind)
        outcome_type, text = finds[kind]
        nodes = reader.evidence(case["shipment_id"], clock)["nodes"]
        custody = sorted((n for n in nodes if n["kind"] == "CustodyEvent"), key=lambda n: str(n["properties"].get("occurred_at")))
        evidence = [n["id"] for n in custody[-2:]] + [n["id"] for n in nodes if n["kind"] == "DeliverySession"][:1]
        recorded = store.record_human_outcome(case["entity_id"], "DEMO-OPERATOR-LOCAL", outcome_type,
                                              text + " (S5 harness acting as the depot supervisor.)", evidence, case["state_version"],
                                              "s5-human-" + case["entity_id"][-16:])
        outcome = next(o for o in ledger(driver, "OpsOutcome") if o.get("entity_id") == recorded["outcome_id"])
        findings.append({"case_id": case["entity_id"], "truth_recipe": truth[case["shipment_id"]]["recipe"], "state_before": case["workflow_state"],
                         "outcome_type": outcome_type, "evidence_ids": evidence, "state_after": recorded["workflow_state"],
                         "verification_status": outcome["verification_status"], "verifier_id": outcome["verifier_id"],
                         "exception_cleared": outcome.get("exception_cleared"), "rule_id": outcome.get("rule_id")})
    from operations.authority import ACTIONS
    refusals, approvals = [], []
    recommendations = {r["entity_id"]: r for r in ledger(driver, "OpsRecommendation")}
    def executions_of(case_id):
        return sum(e["case_id"] == case_id for e in ledger(driver, "OpsExecution"))

    for case in ledger(driver, "OpsCase"):
        recommendation = recommendations.get(case.get("recommendation_id") or "")
        if not recommendation or case["workflow_state"] not in ("HUMAN_REVIEW", "AWAITING_APPROVAL") or case["entity_id"] in handled:
            continue
        base = (ACTIONS.get(recommendation.get("action_type")) or ("?",))[0]
        if base == "HUMAN_REVIEW" and len(refusals) < 2:
            before = executions_of(case["entity_id"])
            try:
                store.decide(case["entity_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "s5-refuse-" + case["entity_id"][-16:])
                refusals.append({"case_id": case["entity_id"], "action_type": recommendation.get("action_type"), "refused": False})
            except OperationsConflict as error:
                rule = str(error).split(":", 1)[0]
                refusals.append({"case_id": case["entity_id"], "action_type": recommendation.get("action_type"),
                                 "refused_by_rule": rule if rule.startswith("AUTH-") else None, "reason": str(error),
                                 "executions_before": before, "executions_after": executions_of(case["entity_id"]),
                                 "state_after": next(c for c in ledger(driver, "OpsCase") if c["entity_id"] == case["entity_id"])["workflow_state"]})
        elif case["workflow_state"] == "AWAITING_APPROVAL" and base in ("AUTO", "APPROVAL_REQUIRED") and not approvals:
            decided = store.decide(case["entity_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "s5-approve-" + case["entity_id"][-16:])
            store.execute_step(limit=5)
            execution = next(e for e in ledger(driver, "OpsExecution") if e["entity_id"] == decided["execution_id"])
            approvals.append({"case_id": case["entity_id"], "action_type": recommendation.get("action_type"), "risk_class": recommendation.get("risk_class"),
                              "state_after_approval": decided["workflow_state"], "execution_status": execution["status"],
                              "authority": execution["authority"], "permission_rule": execution.get("permission_rule"),
                              "receipt": json.loads(execution.get("adapter_result_json") or "{}")})
    result = {"phase": "human", "database": TEST_DATABASE, "clock": clock, "human_findings": findings,
              "approval_refusals": refusals, "approvals": approvals, "ledger": identity,
              "provenance": provenance("human", started_at, manifest_hash=imported["h"])}
    (out / "human.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
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
    CODE_STATE.update(commit=commit, dirty=dirty)
    if dirty and args.phase not in ("checks", "accounting") and not args.allow_dirty:
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
