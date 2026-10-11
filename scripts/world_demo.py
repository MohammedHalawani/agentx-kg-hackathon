"""Demonstration: one full case lifecycle on a mechanism-world database, from detection to a verified outcome.

  cd chat
  uv run python ../scripts/world_demo.py --database shipments-v2-world-<name> --shipments DEMO-SHP-000133,DEMO-SHP-000049
        --state-root <physical state root> [--approve] [--max-hours 240] [--settle-hours 96] [--call-cap N] [--max-calls 60]
        [--rules-only] [--out FILE]

What it does, in order, for the shipments named by --shipments:
1. Opens OperationsStore on the world database with the real investigator (GPT-OSS tool loop and reviewer) and attaches
   the world operational simulator as the execution adapter. The simulator reads the export's private PHYSICAL state
   from --state-root (or SUHAIL_SIM_STATE_ROOT): where parcels are, what devices hold, where recipients live. It never
   reads truth labels, and this script refuses to start while a truth-label path variable is set.
2. Resets that database's operations ledger and live-ingested records only (the store's development reset, with its
   flag set for that one call). Provider feed items return to PENDING; imported records are never touched.
3. Advances the clock hour by hour (tick, then monitor_step until nothing is pending) until the monitor has opened a
   case for every named shipment, or --max-hours pass. Cases of other shipments open too and are left alone.
4. Investigates each named case as soon as it opens: process_one(case_id). Then, with --approve, approves an
   approval-required recommendation through the store's decide path as the demo operator (the store rechecks the
   approval context and refuses a stale one).
5. Runs execute_step (the simulator answers through the provider feed) and keeps advancing the clock with ingestion,
   monitoring and outcome_step until every named case has left AWAITING_OUTCOME, or --settle-hours pass.
6. Prints, and writes to --out, for each case: its id and its state after each stage (detection, investigation, review,
   authority, approval, execution, verification, final state).

Refused databases: the evaluation databases (shipments-v2-world-eval-*) and anything that is not a mechanism-world
database. The reset deletes that database's operations ledger: never point this at a database whose ledger matters.

Model calls: made only by process_one, at most --call-cap per case (default: the store's, 12) and --max-calls in total
(default 60; a case is not started when fewer than the per-case cap remain). They are counted and printed. They are NOT
written to the evaluation campaign's model-call ledger (docs/evals/model_call_ledger.json): this is a demonstration,
not an evaluation run. --rules-only makes no model call at all (a rules-only proposal is informational and never
executable, so that mode shows detection and routing to a person only).
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))

ACTOR = "DEMO-OPERATOR-LOCAL"
EVALUATION_DATABASE = re.compile(r"shipments-v2-world-eval-.*")
WAITING = ("ACTION_INITIATED", "AWAITING_OUTCOME")
MODEL_CALLS = {"succeeded": 0, "failed": 0}


def refuse(message):
    raise SystemExit("Refusing to run: " + message)


def check_database(name):
    from operations.datasets import is_world_database
    if EVALUATION_DATABASE.fullmatch(name or ""):
        refuse(f"{name} is an evaluation database; the demonstration never opens or resets one")
    if not is_world_database(name):
        refuse(f"{name} is not a mechanism-world database (shipments-v2-world-<name>)")
    return name


def label_environment():
    """Set environment variables that point at truth labels (the physical-state root is allowed: the simulator needs it)."""
    return sorted(name for name, value in os.environ.items() if value and "TRUTH" in name.upper())


def count_model_calls():
    import litellm

    def succeeded(kwargs, response, start, end):
        MODEL_CALLS["succeeded"] += 1

    def failed(kwargs, response, start, end):
        MODEL_CALLS["failed"] += 1

    litellm.success_callback = [*litellm.success_callback, succeeded]
    litellm.failure_callback = [*litellm.failure_callback, failed]


def calls_made():
    return MODEL_CALLS["succeeded"] + MODEL_CALLS["failed"]


def open_store(driver, database, agents, state_root):
    """(store, reader, manifest). The world simulator must attach: without it nothing can be verified."""
    import config
    from dataset_v2.contracts import SCHEMA_VERSION, digest
    from operations import world_simulation
    from operations.datasets import dataset_config, is_world_dataset
    from operations.read_model import OperationsReader
    from operations.store import OperationsStore
    with driver.session(database=database, default_access_mode="READ") as session:
        row = session.run("MATCH (m:_V2Import) RETURN m.state AS state, m.manifest_json AS manifest, m.manifest_hash AS hash").single()
    if row is None or row["state"] != "COMPLETE":
        refuse(f"{database} holds no complete V2 import")
    manifest = json.loads(row["manifest"])
    if manifest.get("synthetic") is not True or manifest.get("schema_version") != SCHEMA_VERSION or digest(manifest) != row["hash"]:
        refuse("invalid frozen V2 manifest")
    if not is_world_dataset(manifest.get("dataset_id")):
        refuse(f"{database} does not hold a mechanism-world dataset")
    cfg = dataset_config(manifest["config"])
    reader = OperationsReader(driver, database, cfg.dataset_id, cfg, lambda: store.status()["as_of"])
    store = OperationsStore(driver, database, cfg.dataset_id, cfg, reader=reader, uri=config.NEO4J_URI,
                            protected=(config.SHIPMENT_DATABASE, config.NEO4J_DATABASE, config.CHAT_DATABASE), agents=agents)
    reader.store = store
    store.initialize()
    try:
        adapter = world_simulation.attach(store, reader, manifest, state_root=state_root)
    except (OSError, ValueError) as error:
        refuse(f"the physical state could not be loaded ({error})")
    if adapter is None:
        refuse("no physical-state root: pass --state-root or set the simulator's state-root variable")
    return store, reader, manifest


def reset_ledger(store):
    from operations.store import DEV_RESET_ENV
    with mock.patch.dict(os.environ, {DEV_RESET_ENV: "1"}):
        return store.reset_session(ACTOR, confirmation=store.reset_confirmation())


def _iso(value):
    if hasattr(value, "to_native"):
        value = value.to_native()
    return value.isoformat() if hasattr(value, "isoformat") else value


def cases_of(driver, database, dataset_id, shipment_ids):
    """Every case of the named shipments, oldest first: [{case_id, shipment_id, workflow_state, opened_at, symptoms}]."""
    with driver.session(database=database, default_access_mode="READ") as session:
        return [{"case_id": r["id"], "shipment_id": r["sid"], "workflow_state": r["state"], "opened_at": _iso(r["opened_at"]),
                 "symptoms": sorted(r["symptoms"] or [])}
                for r in session.run("MATCH (c:OpsEntity:OpsCase {dataset_id:$d}) WHERE c.shipment_id IN $sids "
                                     "RETURN c.entity_id AS id, c.shipment_id AS sid, c.workflow_state AS state, c.opened_at AS opened_at, "
                                     "c.symptom_codes AS symptoms ORDER BY c.opened_at, c.entity_id", d=dataset_id, sids=list(shipment_ids))]


def feed_end(driver, database):
    with driver.session(database=database, default_access_mode="READ") as session:
        row = session.run("MATCH (f:ProviderFeedItem {origin:'PROVIDER'}) RETURN max(f.deliver_at) AS t").single()
    return row["t"].to_native() if row and row["t"] else None


def snapshot(store, case_id):
    """The public facts of a case now, as the API's case detail serves them (no truth exists in the ledger)."""
    detail = store.case_detail(case_id)
    run = (detail.get("run") or {}).get("result") or {}
    review, recommendation, outcome = detail.get("review") or {}, detail.get("recommendation") or {}, detail.get("outcome") or {}
    authority = run.get("authority") or {}
    return {
        "clock": store.status()["as_of"], "workflow_state": detail["workflow_state"], "state_version": detail["state_version"],
        "operational_status": detail["operational_status"],
        "investigation": {"mode": run.get("mode"), "diagnosis": detail.get("diagnosis"), "degraded": run.get("degraded") or []},
        "review": {"verdict": review.get("verdict"), "model_verdict": review.get("model_verdict"), "reason_code": review.get("reason_code")},
        "authority": {k: authority.get(k) for k in ("rule_id", "risk_class", "action_type", "closure", "reason")},
        "recommendation": {k: recommendation.get(k) for k in ("action_type", "risk_class", "status", "approvable", "approval_rule", "approval_reason")},
        "executions": [{k: e.get(k) for k in ("action_type", "authority", "status", "mode", "executed_at", "deadline_at", "permission_rule")}
                       | {"receipt": json.loads(e["adapter_result_json"]) if e.get("adapter_result_json") else None}
                       for e in detail.get("executions") or []],
        "outcome": {k: outcome.get(k) for k in ("verification_status", "success", "outcome_type", "exception_cleared", "remaining_symptoms",
                                                 "reason", "verifier_id", "evidence_ids")} if outcome else None,
    }


def stage(record, name, store, case_id, **extra):
    row = {"stage": name, **snapshot(store, case_id), **extra}
    record["stages"].append(row)
    outcome = row["outcome"] or {}
    print(f"[{row['clock']}] {record['shipment_id']} {case_id} · {name}: {row['workflow_state']}"
          + (f" · review {row['review']['model_verdict']}" if name == "investigation" and row["review"]["model_verdict"] else "")
          + (f" · authority {row['authority']['risk_class']} ({row['authority']['rule_id']}) for {row['authority']['action_type']}"
             if name == "investigation" and row["authority"]["risk_class"] else "")
          + (f" · {outcome.get('verification_status')} {outcome.get('outcome_type')} success={outcome.get('success')} "
             f"cleared={outcome.get('exception_cleared')} remaining={outcome.get('remaining_symptoms')}" if name in ("verification", "final") and outcome else "")
          + ("".join(f" · {k}={v}" for k, v in extra.items())), flush=True)
    return row


def hour(store, *, verify):
    """One hour of the world: actions dispatched, the feed ingested, the monitor run, and (when asked) the verifier."""
    store.execute_step(limit=10)
    store.tick(seconds=3600, manual=True)
    while store.status()["session"]["monitor_pending"]:
        if not store.monitor_step(limit=10)["checked"]:
            break
    return store.outcome_step(limit=10) if verify else []


def investigate(store, record, args, budget):
    case_id = record["case_id"]
    cap = store.model_call_cap or int(os.environ.get("SUHAIL_MODEL_CALL_CAP", "12"))
    if not args.rules_only and budget - calls_made() < cap:
        stage(record, "investigation", store, case_id, skipped="model-call budget exhausted")
        return
    before = calls_made()
    for attempt in range(3):   # New evidence during a run requeues the case (at most twice by the store itself).
        result = store.process_one(case_id=case_id, manual=True)
        if result.get("processed") or result.get("reason") != "snapshot_changed":
            break
    stage(record, "investigation", store, case_id, processed=bool(result.get("processed")), model_calls=calls_made() - before)
    detail = store.case_detail(case_id)
    recommendation = detail.get("recommendation") or {}
    needs = detail["workflow_state"] in ("AWAITING_APPROVAL", "RECOMMENDATION_READY", "HUMAN_REVIEW") and bool(recommendation)
    if not needs:
        stage(record, "approval", store, case_id, needed=False)
    elif not args.approve:
        stage(record, "approval", store, case_id, needed=True, approved=False, note="run with --approve to approve as the demo operator")
    elif not recommendation.get("approvable"):
        stage(record, "approval", store, case_id, needed=True, approved=False, refused=recommendation.get("approval_rule"),
              note=recommendation.get("approval_reason"))
    else:
        from operations.lifecycle import OperationsConflict
        try:
            store.decide(case_id, "approve", ACTOR, detail["state_version"], f"demo-approve-{detail['state_version']}")
            stage(record, "approval", store, case_id, needed=True, approved=True, actor=ACTOR)
        except OperationsConflict as refusal:   # The store rechecked the approval context and refused.
            stage(record, "approval", store, case_id, needed=True, approved=False, refused=str(refusal)[:300])
    store.execute_step(limit=10)
    stage(record, "execution", store, case_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True)
    parser.add_argument("--shipments", required=True, help="comma-separated shipment ids")
    parser.add_argument("--state-root", type=Path, help="the physical-state root of this export (never the truth-label root)")
    parser.add_argument("--approve", action="store_true", help="approve an approval-required recommendation as the demo operator")
    parser.add_argument("--max-hours", type=int, default=240, help="simulated hours to wait for the cases to open")
    parser.add_argument("--settle-hours", type=int, default=96, help="simulated hours to wait for outcomes after the last execution")
    parser.add_argument("--call-cap", type=int, help="model calls per case (default: the store's, 12)")
    parser.add_argument("--max-calls", type=int, default=60, help="model calls in total")
    parser.add_argument("--rules-only", action="store_true", help="no model: detection and routing only")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    check_database(args.database)
    if label_environment():
        refuse("unset " + ", ".join(label_environment()) + ". The demonstration never reads truth labels.")
    wanted = [s.strip() for s in args.shipments.split(",") if s.strip()]
    if not wanted:
        refuse("name at least one shipment")
    from core.query_runner import get_driver
    agents = None
    if not args.rules_only:
        from operations import investigator as agents
        count_model_calls()
    driver = get_driver()
    store, reader, manifest = open_store(driver, args.database, agents, args.state_root)
    if args.call_cap:
        store.model_call_cap = args.call_cap
    reset_ledger(store)
    status = store.status()
    print(f"database {args.database} · dataset {manifest['dataset_id']} · adapter {status['execution']['adapter']} · clock {status['as_of']}", flush=True)
    end = feed_end(driver, args.database)
    records, last_execution_hour = {}, 0
    for elapsed in range(1, args.max_hours + args.settle_hours + 1):
        opening = len(records) < len(wanted) and elapsed <= args.max_hours
        hour(store, verify=True)
        for case in cases_of(driver, args.database, manifest["dataset_id"], wanted):
            if case["shipment_id"] in {r["shipment_id"] for r in records.values()} and case["case_id"] not in records:
                continue   # A later case of the same shipment: the demonstration follows the first.
            if case["case_id"] not in records:
                record = records[case["case_id"]] = {"case_id": case["case_id"], "shipment_id": case["shipment_id"], "opened_at": case["opened_at"],
                                                     "symptoms": case["symptoms"], "stages": [], "verified": False}
                stage(record, "detection", store, case["case_id"], symptoms=case["symptoms"])
                investigate(store, record, args, args.max_calls)
                last_execution_hour = elapsed
        for record in records.values():
            state = store.case_detail(record["case_id"])
            if not record["verified"] and state.get("outcome") and state["workflow_state"] not in WAITING:
                record["verified"] = True
                stage(record, "verification", store, record["case_id"])
        waiting = [r for r in records.values() if store.case_detail(r["case_id"])["workflow_state"] in WAITING]
        clock = datetime.fromisoformat(store.status()["as_of"])
        if not opening and not waiting:
            break
        if not opening and elapsed - last_execution_hour >= args.settle_hours:
            break
        if end is not None and clock >= end.astimezone(timezone.utc) + timedelta(hours=args.settle_hours):
            break
    for record in records.values():
        record["final"] = stage(record, "final", store, record["case_id"])
    missing = [sid for sid in wanted if sid not in {r["shipment_id"] for r in records.values()}]
    for sid in missing:
        print(f"{sid}: the monitor opened no case within {args.max_hours} simulated hours", flush=True)
    result = {"schema": "world-demo-1", "database": args.database, "dataset_id": manifest["dataset_id"], "adapter": status["execution"]["adapter"],
              "shipments": wanted, "no_case_opened": missing, "approve": args.approve, "rules_only": args.rules_only,
              "model_calls": dict(MODEL_CALLS), "campaign_ledger_written": False, "final_clock": store.status()["as_of"],
              "cases": list(records.values())}
    print(f"model calls: {calls_made()} (not recorded in the evaluation campaign's ledger)", flush=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_iso) + "\n", encoding="utf-8")
        print(f"wrote {args.out}", flush=True)
    return result


if __name__ == "__main__":
    main()
