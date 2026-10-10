"""Pilot: real investigations of cases the monitor opens while a mechanism world's feed is replayed.

  cd chat
  uv run python ../scripts/world_pilot.py --out ../docs/evals/<dir>/pilot.json [--database shipments-v2-world-1-small]
        [--per-alert 2] [--max-cases 12] [--max-calls 144] [--call-cap N] [--check-after-hours 24] [--max-hours N]
        [--disable-tools a,b] [--allow-dirty]

What it does, in order:
1. Opens OperationsStore on a mechanism-world database (a shipments-v2-world-<name> database, or a scratch test
   database holding a world dataset) with agents = operations.investigator and NO execution adapter (no simulator).
2. Resets that database's operations ledger and live-ingested records only: the store's development reset, with its
   flag set for that one call. Provider feed items return to PENDING; imported records are never touched.
3. Starts the clock at the live start and advances it hour by hour: tick, then monitor_step until nothing is pending,
   so cases open from ingested evidence only.
4. When a case opens it is investigated at once with process_one(case_id, manual=True) if fewer than --per-alert
   cases with the same opening symptom set have been investigated and fewer than --max-cases in total. A case is not
   started when the model calls left in the total budget (--max-calls) are fewer than the per-case cap.
5. At a mid-feed instant (--check-after-hours after the live start) it runs the time-correct Neo4j check: the world's
   cross-shipment traversals (world.export.traversals, with no private state) and the investigation tools' fixed
   queries, all as of that instant. When ticking has stopped they run again as of the same instant: the rows must be
   the same and none may be recorded after it.
6. Ticking stops when --max-cases is reached, the budget cannot cover another case, or the feed ends. If the check
   instant has not been passed by then, the clock is advanced to one hour past it without investigating anything
   (no model calls), so the check compares against later ingestion.
7. Writes a JSON results file: provenance (commit, dirty flag, database, manifest hash, prompt hashes, model, exact
   model calls and tokens as LiteLLM reported them) and, per case, public fields only.

It never reads truth: it refuses to start when a truth or simulator-state path variable is set, never imports
world.truth and never opens a file outside the results path. Scoring is a separate process (world_pilot_score.py).
With no simulator an authorized action gets no field response: it is recorded as not acknowledged and the case goes
to a person; nothing resolves. This script makes model calls only through process_one.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))

TRUTH_ENVIRONMENT = ("SUHAIL_EVAL_TRUTH_ROOT", "SUHAIL_SIM_STATE_ROOT")
ACTOR = "DEMO-OPERATOR-LOCAL"
RESULT_SCHEMA = "world-pilot-1"
# Every model call LiteLLM completes or fails, by the model name the provider reported (as scripts/s5_scenarios.py).
MODEL_CALLS = {"succeeded": {}, "failed": {}, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def truth_environment():
    """Names of set environment variables that point at truth labels or the simulator's private state."""
    return sorted(name for name, value in os.environ.items() if value and (name in TRUTH_ENVIRONMENT or "TRUTH" in name.upper()))


def refuse_truth_access():
    names = truth_environment()
    if names:
        raise SystemExit("Refusing to run: unset " + ", ".join(names) + ". The pilot never reads truth; scoring is a separate process.")


def truth_module_loaded():
    """Whether world.truth is loaded in this process (it never is when the script runs as a command)."""
    return any(name == "world.truth" or name.startswith("world.truth.") for name in sys.modules)


def record_model_calls():
    import litellm

    def succeeded(kwargs, response, start, end):
        name = getattr(response, "model", None) or kwargs.get("model") or "unknown"
        MODEL_CALLS["succeeded"][name] = MODEL_CALLS["succeeded"].get(name, 0) + 1
        usage = getattr(response, "usage", None)
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            MODEL_CALLS[field] += getattr(usage, field, 0) or 0

    def failed(kwargs, response, start, end):
        name = kwargs.get("model") or "unknown"
        MODEL_CALLS["failed"][name] = MODEL_CALLS["failed"].get(name, 0) + 1

    litellm.success_callback = [*litellm.success_callback, succeeded]
    litellm.failure_callback = [*litellm.failure_callback, failed]


def provider_calls():
    """Every provider call so far, completed or failed."""
    return sum(MODEL_CALLS["succeeded"].values()) + sum(MODEL_CALLS["failed"].values())


def git_state(root=ROOT):
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True).strip())
    return commit, dirty


def _iso(value):
    if hasattr(value, "to_native"):
        value = value.to_native()
    return value.isoformat() if hasattr(value, "isoformat") else value


# ---------------------------------------------------------------------- the store
def open_store(driver, database, agents, *, uri=None):
    """(store, reader, manifest hash). A mechanism-world dataset in a world database or a scratch test database only."""
    import config
    from dataset_v2.contracts import SCHEMA_VERSION, digest
    from operations.datasets import SCRATCH_DATABASES, dataset_config, is_world_database, is_world_dataset
    from operations.read_model import OperationsReader
    from operations.store import OperationsStore
    if not (is_world_database(database) or database in SCRATCH_DATABASES):
        raise SystemExit(f"{database} is not a mechanism-world database (shipments-v2-world-<name>) or a scratch test database")
    with driver.session(database=database, default_access_mode="READ") as session:
        row = session.run("MATCH (m:_V2Import) RETURN m.state AS state, m.manifest_json AS manifest, m.manifest_hash AS hash").single()
    if row is None or row["state"] != "COMPLETE":
        raise SystemExit(f"{database} holds no complete V2 import")
    manifest = json.loads(row["manifest"])
    if manifest.get("synthetic") is not True or manifest.get("schema_version") != SCHEMA_VERSION or digest(manifest) != row["hash"]:
        raise SystemExit("Invalid frozen V2 manifest")
    if not is_world_dataset(manifest.get("dataset_id")):
        raise SystemExit(f"{database} does not hold a mechanism-world dataset")
    cfg = dataset_config(manifest["config"])
    reader = OperationsReader(driver, database, cfg.dataset_id, cfg, lambda: store.status()["as_of"])
    store = OperationsStore(driver, database, cfg.dataset_id, cfg, reader=reader, uri=uri or config.NEO4J_URI,
                            protected=(config.SHIPMENT_DATABASE, config.NEO4J_DATABASE, config.CHAT_DATABASE), agents=agents)
    reader.store = store
    if store.adapter is not None or not store.live:
        raise SystemExit("The pilot runs a feed dataset with no execution adapter")
    store.initialize()
    return store, reader, row["hash"]


def reset_ledger(store):
    """The store's development reset (operations ledger and live-ingested records of this dataset only), with its flag
    set for this call alone."""
    from operations.store import DEV_RESET_ENV
    with mock.patch.dict(os.environ, {DEV_RESET_ENV: "1"}):
        return store.reset_session(ACTOR, confirmation=store.reset_confirmation())


def feed_end(driver, database):
    with driver.session(database=database, default_access_mode="READ") as session:
        row = session.run("MATCH (f:ProviderFeedItem {origin:'PROVIDER'}) RETURN max(f.deliver_at) AS t, count(f) AS n").single()
    return (row["t"].to_native() if row and row["t"] else None), (row["n"] if row else 0)


def ledger_cases(driver, database, dataset_id, case_ids):
    with driver.session(database=database, default_access_mode="READ") as session:
        return {r["id"]: {"shipment_id": r["sid"], "opened_at": _iso(r["opened_at"]), "symptoms": sorted(r["symptoms"] or [])}
                for r in session.run("MATCH (c:OpsEntity:OpsCase {dataset_id:$d}) WHERE c.entity_id IN $ids "
                                     "RETURN c.entity_id AS id, c.shipment_id AS sid, c.opened_at AS opened_at, c.symptom_codes AS symptoms",
                                     d=dataset_id, ids=list(case_ids))}


# ---------------------------------------------------------------------- the time-correct check
EMPTY_PHYSICAL = {"devices": [], "messaging_outages": []}   # The pilot holds no private physical state.


def _rows_digest(rows):
    from dataset_v2.contracts import canonical, digest
    return digest(sorted(canonical(json.loads(json.dumps(r, default=_iso))) for r in rows))


def _latest(rows):
    stamps = []
    for row in rows:
        for record in (row, row.get("props") or {}):
            for field in ("recorded_at", "occurred_at", "latest_recorded_at"):
                if record.get(field):
                    stamps.append(str(_iso(record[field])))
    from dataset_v2.contracts import instant
    return max(stamps, key=instant) if stamps else None


def check_targets(driver, database, dataset_id, as_of):
    """Shared references to ask about, chosen from what is visible at as_of (the busiest of each kind; ties by id)."""
    from operations.cross_shipment import in_scope, visible
    picks = {
        "device": f"MATCH (n:V2Entity:ScanEvent) WHERE n.device_ref IS NOT NULL AND {in_scope('n')} AND {visible('n')} "
                  "RETURN n.device_ref AS id, count(*) AS c ORDER BY c DESC, id LIMIT 1",
        "route_run": f"MATCH (n:V2Entity:VehicleAssignment) WHERE n.route_run_id IS NOT NULL AND {in_scope('n')} AND {visible('n')} "
                     "RETURN n.route_run_id AS id, count(*) AS c ORDER BY c DESC, id LIMIT 1",
        "trip": f"MATCH (n:V2Entity:CustodyEvent) WHERE n.trip_id IS NOT NULL AND {in_scope('n')} AND {visible('n')} "
                "RETURN n.trip_id AS id, count(*) AS c ORDER BY c DESC, id LIMIT 1",
        "container": f"MATCH (n:V2Entity:ScanEvent) WHERE n.container_id IS NOT NULL AND {in_scope('n')} AND {visible('n')} "
                     "RETURN n.container_id AS id, count(*) AS c ORDER BY c DESC, id LIMIT 1",
        "facility": f"MATCH (n:V2Entity:CustodyEvent) WHERE n.facility_id IS NOT NULL AND {in_scope('n')} AND {visible('n')} "
                    "RETURN n.facility_id AS id, count(*) AS c ORDER BY c DESC, id LIMIT 1",
        "carrier_route": f"MATCH (n:V2Entity:CommunicationEvent) WHERE n.carrier_route IS NOT NULL AND {in_scope('n')} AND {visible('n')} "
                         "RETURN n.carrier_route AS id, count(*) AS c ORDER BY c DESC, id LIMIT 1",
        "city": f"MATCH (n:V2Entity:City) WHERE {in_scope('n')} AND {visible('n')} RETURN n.entity_id AS id, 0 AS c ORDER BY id LIMIT 1",
    }
    out = {}
    with driver.session(database=database, default_access_mode="READ") as session:
        for name, query in picks.items():
            row = session.run(query, dataset_id=dataset_id, as_of=as_of).single()
            out[name] = row["id"] if row else None
    return out


def catalogue_calls(targets, as_of):
    """The investigation tools' fixed queries to run as of `as_of`, over the two days before it."""
    start = (as_of - timedelta(hours=48)).isoformat()
    window = {"from_at": start, "to_at": as_of.isoformat()}
    calls = []
    if targets.get("device"):
        ref = targets["device"]
        calls += [("device_heartbeats", {"ref": ref, **window}), ("device_scan_counts", {"ref": ref, **window, "late_seconds": 3600}),
                  ("device_scans", {"ref": ref, **window}), ("device_late_scans", {"ref": ref, **window, "late_seconds": 3600}),
                  ("device_measurements", {"ref": ref, **window}), ("device_route_runs", {"ref": ref, **window})]
    if targets.get("facility"):
        ref = targets["facility"]
        calls += [("facility_devices", {"ref": ref}), ("facility_throughput", {"ref": ref, **window}), ("facility_custody_counts", {"ref": ref, **window}),
                  ("overdue_at_facility", {"ref": ref, "shipment_id": "DEMO-SHP-NONE", "from_at": start, "allowance": 900}),
                  ("overdue_at_facility_counts", {"ref": ref, "shipment_id": "DEMO-SHP-NONE", "from_at": start, "allowance": 900})]
    if targets.get("route_run"):
        ref = targets["route_run"]
        calls += [("shared_record", {"ref": ref})] + [(name, {"ref": ref}) for name in (
            "route_run_assignments", "route_run_custody", "route_run_attempts", "route_run_scans", "route_run_reconciliations", "route_run_manifests")]
    if targets.get("container"):
        calls.append(("container_scans", {"ref": targets["container"]}))
    if targets.get("trip"):
        calls += [(name, {"ref": targets["trip"]}) for name in ("trip_events", "trip_positions", "trip_custody", "trip_containers")]
    if targets.get("carrier_route"):
        calls += [("sms_route_counts", {"text": targets["carrier_route"], **window}), ("sms_route_failures", {"text": targets["carrier_route"], **window})]
    if targets.get("city"):
        calls.append(("traffic_events", {"ref": targets["city"], "from_at": start}))
    return calls


def time_check_pass(driver, database, reader, as_of, calls):
    """Every check query as of `as_of`: a digest of its rows and the latest timestamp among them."""
    from world.export import _stable, traversals
    with driver.session(database=database, default_access_mode="READ") as session:
        world_rows = traversals(session, EMPTY_PHYSICAL, as_of)
    out = {"world_traversals": {name: {"rows": _stable(row), "latest_recorded_at": row.get("latest_recorded_at")} for name, row in world_rows.items()},
           "tool_queries": {}}
    for name, params in calls:
        rows = reader.fetch(name, as_of=as_of.isoformat(), **params)
        out["tool_queries"][name] = {"rows": len(rows), "digest": _rows_digest(rows), "latest_timestamp": _latest(rows)}
    return out


def compare_time_check(as_of, first, again, *, clock_at_first, clock_at_second, targets):
    from dataset_v2.contracts import instant
    same_world = first["world_traversals"] == again["world_traversals"]
    same_tools = first["tool_queries"] == again["tool_queries"]
    late = {}
    for group in ("world_traversals", "tool_queries"):
        for name, row in again[group].items():
            stamp = row.get("latest_recorded_at") or row.get("latest_timestamp")
            if stamp and instant(str(stamp)) > as_of:
                late[f"{group}.{name}"] = str(stamp)
    returned = sum(1 for row in again["tool_queries"].values() if row["rows"]) + len(again["world_traversals"])
    differing = sorted([f"world_traversals.{k}" for k in first["world_traversals"] if first["world_traversals"][k] != again["world_traversals"].get(k)]
                       + [f"tool_queries.{k}" for k in first["tool_queries"] if first["tool_queries"][k] != again["tool_queries"].get(k)])
    return {"as_of": as_of.isoformat(), "clock_at_first_pass": clock_at_first, "clock_at_second_pass": clock_at_second,
            "pass": bool(same_world and same_tools and not late and returned and instant(clock_at_second) > as_of),
            "same_rows_with_the_clock_there_and_after_later_ingestion": bool(same_world and same_tools),
            "queries_whose_rows_differ": differing, "queries_returning_a_record_from_after_as_of": late,
            "queries_run": len(again["tool_queries"]) + len(again["world_traversals"]), "queries_returning_rows": returned,
            "targets": targets, "with_the_clock_at_as_of": first, "as_of_after_later_ingestion": again,
            "note": "World traversals run without the simulator's private state, so its device-outage and messaging-outage windows are "
                    "not sampled; the tool queries cover a device and a carrier route chosen from visible records."}


# ---------------------------------------------------------------------- one case, public fields only
def case_record(store, reader, case_id, opened, result, wall_seconds, calls_before, calls_after, state_after):
    """What the pilot reports for one investigated case, from the stored run record. No truth is involved."""
    served = {"diagnosis": False, "review": False, "run": False, "investigation_log": False, "error": None}
    detail, run = {}, {}
    try:
        detail = reader.case_detail(case_id)
        run = ((detail.get("run") or detail.get("previous_run") or {}).get("result")) or {}
        served.update(diagnosis=isinstance(detail.get("diagnosis"), dict), review=bool(detail.get("review") or run.get("review")),
                      run=bool(run), investigation_log=bool((run.get("investigation_log") or {}).get("rounds")))
    except Exception as error:  # Reported, never hidden: the run record must be readable for the UI and for scoring.
        served["error"] = type(error).__name__
    log = run.get("investigation_log") or {}
    rounds = []
    for entry in log.get("rounds") or []:
        conclusion = entry.get("conclusion") or {}
        review = entry.get("review") or {}
        rounds.append({
            "round": entry.get("round"),
            "tool_calls": [{"tool": c.get("tool"), "args": c.get("args"), "evidence_ids": c.get("evidence_ids"), "computed_ids": c.get("computed_ids"),
                            "omitted_rows": c.get("omitted_rows"), "failure": c.get("failure")} for c in entry.get("tool_calls") or []],
            "primary_cause": conclusion.get("primary_cause"), "confidence": conclusion.get("confidence"),
            "hypotheses": [{"cause": h.get("cause"), "status": h.get("status"), "supporting_evidence_ids": h.get("supporting_evidence_ids"),
                            "contradicting_evidence_ids": h.get("contradicting_evidence_ids"), "assessment": h.get("assessment")}
                           for h in conclusion.get("hypotheses") or []],
            "missing_evidence": conclusion.get("missing_evidence"), "next_evidence_step": conclusion.get("next_evidence_step"),
            "recommended_action": conclusion.get("recommended_action"), "requires_physical_check": conclusion.get("requires_physical_check"),
            "summary": conclusion.get("summary"),
            "investigator": entry.get("investigator"),
            "citations": [{"id": c.get("id"), "kind": c.get("kind"), "scope": c.get("scope"), "exists": c.get("resolves"),
                           "retrieved_in_this_run": c.get("retrieved_in_this_investigation"),
                           "recorded_at_or_before_snapshot": c.get("recorded_at_or_before_snapshot"), "valid": c.get("valid")}
                          for c in (entry.get("citation_validity") or {}).get("citations") or []],
            "citations_all_valid": (entry.get("citation_validity") or {}).get("all_valid"),
            "fact_checks": entry.get("fact_checks"),
            "review": {k: review.get(k) for k in ("verdict", "model_verdict", "reason_code", "feedback", "unsupported_claims",
                                                  "unaddressed_contradictions", "alternatives_tested", "mode", "degraded", "validation_error")},
            "model_calls_used_after_round": entry.get("model_calls_used")})
    last = rounds[-1] if rounds else {}
    authority = run.get("authority") or {}
    final_review = run.get("review") or {}
    try:
        final_state = store.case_detail(case_id)["workflow_state"]
    except Exception:
        final_state = None
    return {"case_id": case_id, "shipment_id": opened["shipment_id"], "opened_at": opened["opened_at"], "opening_symptoms": opened["symptoms"],
            "processed": bool(result.get("processed")), "run_id": result.get("run_id"), "snapshot_as_of": log.get("snapshot_as_of"),
            "rounds": rounds,
            "primary_cause": last.get("primary_cause"), "confidence": last.get("confidence"), "hypotheses": last.get("hypotheses") or [],
            "insufficient_evidence": last.get("primary_cause") == "INSUFFICIENT_EVIDENCE",
            "missing_evidence": last.get("missing_evidence") or [], "next_evidence_step": last.get("next_evidence_step") or "",
            "recommended_action": last.get("recommended_action"),
            "citations": last.get("citations") or [], "citations_all_valid": last.get("citations_all_valid"),
            "review": {"verdict": final_review.get("verdict"), "model_verdict": final_review.get("model_verdict"),
                       "reason_code": final_review.get("reason_code"), "reasons": final_review.get("feedback"),
                       "unsupported_claims": (last.get("review") or {}).get("unsupported_claims") or []},
            "authority": {"risk_class": authority.get("risk_class"), "rule_id": authority.get("rule_id"), "action_type": authority.get("action_type"),
                          "closure": authority.get("closure"), "reason": authority.get("reason")},
            "degraded": run.get("degraded") or [],
            "model_calls_used": log.get("model_calls_used"), "model_call_cap": log.get("model_call_cap"),
            "model_calls_by_role": log.get("model_calls_by_role"), "cap_reached": log.get("cap_reached"),
            "provider_calls": calls_after - calls_before, "disabled_tools": log.get("disabled_tools"),
            "wall_seconds": round(wall_seconds, 1),
            "workflow_state_after_investigation": state_after, "final_workflow_state": final_state,
            # The diagnosis block as the UI gets it: available only for an investigation the reviewer accepted.
            "diagnosis_served": {k: (detail.get("diagnosis") or {}).get(k) for k in ("available", "reason", "primary_cause")},
            "case_detail_returns": served}


# ---------------------------------------------------------------------- the replay
def run_pilot(driver, database, *, agents=None, per_alert=2, max_cases=12, max_calls=144, call_cap=None, check_after_hours=24,
              max_hours=None, disabled_tools=(), calls_used=provider_calls, log=print):
    """Replay the feed and investigate opening cases. Returns the results document (without provenance)."""
    from dataset_v2.contracts import instant
    from operations import investigator
    agents = agents or investigator
    store, reader, manifest_hash = open_store(driver, database, agents)
    if call_cap is not None:
        store.model_call_cap = int(call_cap)
    store.disabled_tools = tuple(disabled_tools)
    per_case_cap = investigator.CallBudget(store.model_call_cap).cap
    reset_ledger(store)
    status = store.status()
    start_clock = status["as_of"]
    session_id = status["session"]["session_id"]
    last_delivery, feed_items = feed_end(driver, database)
    if last_delivery is None:
        raise SystemExit("The database holds no provider feed")
    end = min(last_delivery, instant(status["simulator"]["end_at"]))
    check_at = instant(start_clock) + timedelta(hours=check_after_hours)
    log(f"pilot: {database} session {session_id} clock {start_clock} feed ends {end.isoformat()} per-case cap {per_case_cap}")

    counts = {"hours": 0, "ingested": 0, "duplicate": 0, "conflicting_duplicate": 0, "rejected": 0, "monitor_checked": 0}
    opened_order, investigated, by_symptoms, skipped, cases = [], [], {}, {}, []
    check, stop_reason, budget_refused = None, None, False

    def skip(case_id, reason):
        skipped[case_id] = reason

    def investigate(case_id):
        nonlocal budget_refused
        opened = ledger_cases(driver, database, store.dataset_id, [case_id]).get(case_id)
        if opened is None:
            return skip(case_id, "case_not_found")
        key = "+".join(opened["symptoms"])
        if len(investigated) >= max_cases:
            return skip(case_id, "max_cases_reached")
        if by_symptoms.get(key, 0) >= per_alert:
            return skip(case_id, "per_alert_limit")
        if max_calls - calls_used() < per_case_cap:
            budget_refused = True
            return skip(case_id, "model_call_budget")
        before, started = calls_used(), time.perf_counter()
        result, error = {"processed": False}, None
        for _ in range(3):  # A snapshot that changed mid-run requeues the case (the clock stands still here, so rarely).
            try:
                result = store.process_one(case_id, manual=True)
            except Exception as failure:  # The store paused its worker and released the claim; the case is reported as failed.
                error = type(failure).__name__
                break
            if result.get("processed") or result.get("reason") != "snapshot_changed" or max_calls - calls_used() < per_case_cap:
                break
        wall = time.perf_counter() - started
        by_symptoms[key] = by_symptoms.get(key, 0) + 1
        investigated.append(case_id)
        try:
            state_after = store.case_detail(case_id)["workflow_state"]
        except Exception:
            state_after = None
        # No simulator: an automatically authorized action is recorded as not acknowledged and the case goes to a person.
        executed = store.execute_step(limit=25) if error is None else []
        record = case_record(store, reader, case_id, opened, result, wall, before, calls_used(), state_after)
        record.update(error=error, executions_dispatched=len(executed) if isinstance(executed, list) else None)
        cases.append(record)
        log(f"pilot: case {len(cases)} {case_id} {key} -> {record['primary_cause']} review {record['review']['model_verdict']} "
            f"authority {record['authority']['risk_class']} calls {record['model_calls_used']} ({record['wall_seconds']} s)")

    def advance(investigating):
        tick = store.tick(seconds=3600, manual=True, speed=1)
        counts["hours"] += 1
        for field in ("duplicate", "conflicting_duplicate", "rejected"):
            counts[field] += tick.get(field, 0)
        counts["ingested"] += tick.get("events_replayed", 0)
        while store.status()["session"]["monitor_pending"]:
            step = store.monitor_step(limit=25)
            counts["monitor_checked"] += step["checked"]
            for case_id in step["opened"]:
                opened_order.append(case_id)
                if investigating:
                    investigate(case_id)
                else:
                    skip(case_id, "opened_after_investigations_stopped")
        return tick["as_of"]

    def first_check_pass(clock):
        targets = check_targets(driver, database, store.dataset_id, instant(clock))
        calls = catalogue_calls(targets, instant(clock))
        return {"as_of": instant(clock), "clock": clock, "targets": targets, "calls": calls,
                "first": time_check_pass(driver, database, reader, instant(clock), calls)}

    clock = start_clock
    while True:
        if instant(clock) >= end:
            stop_reason = "feed_ended"
        elif len(investigated) >= max_cases:
            stop_reason = "max_cases_reached"
        elif budget_refused:
            stop_reason = "model_call_budget"
        elif max_hours is not None and counts["hours"] >= max_hours:
            stop_reason = "max_hours_reached"
        if stop_reason:
            break
        clock = advance(True)
        if check is None and instant(clock) >= check_at:
            check = first_check_pass(clock)
    # The check instant, then at least one more hour of ingestion, without investigating anything.
    extra_hours = 0
    while (check is None or instant(clock) <= check["as_of"]) and instant(clock) < instant(status["simulator"]["end_at"]) and extra_hours < check_after_hours + 2:
        clock = advance(False)
        extra_hours += 1
        if check is None and instant(clock) >= check_at:
            check = first_check_pass(clock)
    if check is None:
        time_check = {"pass": False, "reason": "the check instant was not reached"}
    else:
        again = time_check_pass(driver, database, reader, check["as_of"], check["calls"])
        time_check = compare_time_check(check["as_of"], check["first"], again, clock_at_first=check["clock"], clock_at_second=clock,
                                        targets=check["targets"])
    final = store.status()
    opened_all = ledger_cases(driver, database, store.dataset_id, opened_order)
    by_set = {}
    for case_id in opened_order:
        key = "+".join((opened_all.get(case_id) or {}).get("symptoms") or [])
        by_set[key] = by_set.get(key, 0) + 1
    return {"schema": RESULT_SCHEMA, "synthetic": True, "database": database, "dataset_id": store.dataset_id, "manifest_hash": manifest_hash,
            "session_id": session_id,
            "settings": {"per_alert": per_alert, "max_cases": max_cases, "max_calls": max_calls, "per_case_model_call_cap": per_case_cap,
                         "check_after_hours": check_after_hours, "max_hours": max_hours, "disabled_tools": sorted(disabled_tools),
                         "tick_seconds": 3600, "execution_adapter": final["execution"]["adapter"]},
            "replay": {"clock_at_start": start_clock, "clock_at_end": clock, "feed_end": end.isoformat(), "feed_items": feed_items,
                       "stop_reason": stop_reason, "hours_after_investigations_stopped": extra_hours, **counts,
                       "cases_opened": len(opened_order), "cases_opened_by_symptom_set": dict(sorted(by_set.items())),
                       "cases_investigated": len(investigated), "cases_not_investigated": dict(sorted(
                           (reason, sum(1 for r in skipped.values() if r == reason)) for reason in set(skipped.values()))),
                       "model_calls_counted": calls_used(), "truth_environment_set": truth_environment(), "world_truth_imported": truth_module_loaded()},
            "time_correct_check": time_check,
            "cases": cases,
            "cases_not_investigated": [{"case_id": case_id, "reason": skipped[case_id], **(opened_all.get(case_id) or {})}
                                       for case_id in opened_order if case_id in skipped]}


def provenance(started_at, code_state, manifest_hash, database):
    import config
    from dataset_v2.contracts import digest
    from operations import investigator
    commit, dirty = code_state
    now = git_state()
    return {"script": "scripts/world_pilot.py", "commit": commit, "dirty_tree": dirty, "tree_changed_during_run": now != (commit, dirty),
            "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(), "database": database, "manifest_hash": manifest_hash,
            "configured_model": config.LLM_MODEL, "model_api_base": config.LLM_API_BASE,
            "investigator_prompt_sha256": digest(investigator.SYSTEM), "reviewer_prompt_sha256": digest(investigator.REVIEWER_SYSTEM),
            "cause_catalogue_sha256": digest(investigator.cause_catalogue()),
            "model_calls": json.loads(json.dumps(MODEL_CALLS)), "model_calls_total": provider_calls()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default="shipments-v2-world-1-small")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-alert", type=int, default=2, help="cases investigated per opening symptom set")
    parser.add_argument("--max-cases", type=int, default=12)
    parser.add_argument("--max-calls", type=int, default=144, help="hard total model-call budget")
    parser.add_argument("--call-cap", type=int, help="per-case model-call cap (default SUHAIL_MODEL_CALL_CAP, else 12)")
    parser.add_argument("--check-after-hours", type=int, default=24, help="hours after the live start at which the time-correct check runs")
    parser.add_argument("--max-hours", type=int, help="stop after this many simulated hours")
    parser.add_argument("--disable-tools", default="", help="comma-separated tool names withheld from the investigator")
    parser.add_argument("--allow-dirty", action="store_true", help="run on uncommitted changes (the results say so)")
    args = parser.parse_args(argv)
    refuse_truth_access()
    if min(args.per_alert, args.max_cases, args.max_calls, args.check_after_hours) < 1:
        raise SystemExit("--per-alert, --max-cases, --max-calls and --check-after-hours must be at least 1")
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; choose a new results file")
    code_state = git_state()
    if code_state[1] and not args.allow_dirty:
        raise SystemExit(f"The working tree differs from {code_state[0][:12]}; commit first so results name the exact code (or pass --allow-dirty).")
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    started_at = datetime.now(timezone.utc).isoformat()
    record_model_calls()
    import config
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD))
    started = time.perf_counter()
    with driver:
        result = run_pilot(driver, args.database, per_alert=args.per_alert, max_cases=args.max_cases, max_calls=args.max_calls,
                           call_cap=args.call_cap, check_after_hours=args.check_after_hours, max_hours=args.max_hours,
                           disabled_tools=tuple(t for t in args.disable_tools.replace(" ", "").split(",") if t))
    if result["replay"]["world_truth_imported"] or result["replay"]["truth_environment_set"]:
        raise SystemExit("world.truth or a truth path reached the pilot process; no results were written")
    result = {"provenance": provenance(started_at, code_state, result["manifest_hash"], args.database),
              "wall_seconds": round(time.perf_counter() - started, 1), **result}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=_iso) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "cases_investigated": len(result["cases"]), "stop_reason": result["replay"]["stop_reason"],
                      "model_calls": result["provenance"]["model_calls_total"], "time_correct_check": result["time_correct_check"].get("pass")}))


if __name__ == "__main__":
    main()
