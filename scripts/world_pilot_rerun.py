"""Re-investigate named cases of an existing pilot session after a fix, without replaying the feed or resetting anything.

  cd chat
  uv run python ../scripts/world_pilot_rerun.py ../docs/evals/<pilot>/pilot.json --cases 1,3 --out ../docs/evals/<pilot>/rerun.json

Each named case (by its number in the pilot file) is put back in the queue through the product's own explicit
re-analysis and investigated once with process_one. The clock stays where the pilot left it, so the snapshot is later
than the first investigation's and may hold more evidence; the results say so. No truth is read here (same refusals as
world_pilot.py, at the start and again when the run ends: the results record truth_environment_set and
world_truth_imported, and nothing is written if either is set); scoring stays a separate process. The results name
this script, carry the re-run's own settings (the pilot's are kept apart as pilot_settings) and, per case, how many
executions the step dispatched. A hard model-call budget applies, and the run goes through the
campaign's model-call ledger exactly as world_pilot.py does (refused if spent + --max-calls would exceed the cap,
--max-calls reserved before the first call, the calls actually made written at the end).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))
sys.path.insert(0, str(ROOT / "scripts"))

import world_pilot as pilot  # noqa: E402

SCRIPT = "scripts/world_pilot_rerun.py"


def rerun_document(first, rows, *, results, numbers, max_calls, per_case_cap, provenance, isolation):
    """The re-run's results file. Identity (database, dataset, session) is the pilot's; the settings are the re-run's
    own, with the pilot's kept apart so a reader cannot take the pilot's budget for this run's."""
    return {**{k: first[k] for k in ("schema", "synthetic", "database", "dataset_id", "manifest_hash", "session_id")},
            "settings": {"script": SCRIPT, "max_calls": max_calls, "per_case_model_call_cap": per_case_cap, "pilot_cases": list(numbers),
                         "execution_adapter": (first.get("settings") or {}).get("execution_adapter"),
                         "disabled_tools": (first.get("settings") or {}).get("disabled_tools", [])},
            "pilot_settings": first.get("settings"),
            "rerun_of": str(results), "note": "Same cases re-investigated after a fix; the snapshot is the clock the pilot ended on, "
            "later than the first investigation's.", "provenance": provenance, "isolation": isolation,
            "cases": rows, "cases_not_investigated": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results")
    parser.add_argument("--cases", required=True, help="comma-separated case numbers from the pilot file (1-based)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-calls", type=int, default=72)
    parser.add_argument("--ledger", type=Path, help="campaign model-call ledger (default docs/evals/model_call_ledger.json)")
    args = parser.parse_args(argv)
    pilot.refuse_truth_access()
    ledger = pilot.campaign_ledger(args.ledger, args.max_calls)   # Refuses here if the campaign cap cannot cover --max-calls.
    first = json.loads(Path(args.results).read_text(encoding="utf-8"))
    numbers = [int(n) for n in args.cases.split(",")]
    chosen = [first["cases"][n - 1] for n in numbers]
    started_at = datetime.now(timezone.utc).isoformat()
    code_state = pilot.git_state()
    if code_state[1]:
        raise SystemExit("Uncommitted changes: commit first so the results name the code they came from")
    from core.query_runner import get_driver
    from operations import investigator
    from operations.investigator import model_call_cap
    driver = get_driver()
    pilot.record_model_calls()
    store, reader, manifest_hash = pilot.open_store(driver, first["database"], investigator)
    if store.status()["session"]["session_id"] != first["session_id"]:
        raise SystemExit("The database's live session is not the pilot's session; nothing to re-investigate")
    # Reserved at the run's own maximum before any call. If the run dies, the reservation stays counted at that maximum.
    run_name = f"world_pilot_rerun {Path(args.out).name} {started_at}"
    pilot.reserve_calls(ledger, run_name, args.max_calls, code_state[0],
                        f"scripts/world_pilot_rerun.py, cases {args.cases} of {Path(args.results).name}; own cap {args.max_calls}")
    cap = model_call_cap()
    in_code = {"calls": 0}   # The stored per-case counters, added up (a run without one counts at the cap).

    def spent():
        """The larger of LiteLLM's callback count (which can lag a call) and the per-case counters, as in the pilot."""
        return max(pilot.provider_calls(), in_code["calls"])
    rows = []
    for number, row in zip(numbers, chosen):
        case_id = row["case_id"]
        if args.max_calls - spent() < cap:
            rows.append({"pilot_case": number, "case_id": case_id, "processed": False, "error": "call budget exhausted"})
            continue
        detail = reader.case_detail(case_id)
        state = detail["workflow_state"]
        if state != "OPEN":
            store.request_reanalysis(case_id, "DEMO-OPERATOR-LOCAL", detail["state_version"], f"pilot-rerun-{case_id}-{started_at}")
        before, begun = spent(), time.time()
        result = store.process_one(case_id, manual=True)
        state_after = reader.case_detail(case_id)["workflow_state"]
        executed = store.execute_step(limit=5)
        record = pilot.case_record(store, reader, case_id, {"opened_at": row["opened_at"], "symptoms": row["opening_symptoms"],
                                                             "shipment_id": row["shipment_id"]},
                                   result, round(time.time() - begun, 1), before, spent(), state_after)
        record.update(pilot_case=number, first_primary_cause=row["primary_cause"], first_authority=row["authority"],
                      state_before_rerun=state, executions_dispatched=len(executed) if isinstance(executed, list) else None)
        in_code["calls"] += record["model_calls_used"] if isinstance(record.get("model_calls_used"), int) else cap
        rows.append(record)
        print(f"rerun: pilot case {number} {row['primary_cause']} -> {record.get('primary_cause')} "
              f"authority {(record.get('authority') or {}).get('risk_class')} calls {record.get('model_calls_used')}", flush=True)
    ledger.settle(run_name, spent(), tokens=pilot.MODEL_CALLS["total_tokens"])
    # As the pilot does at its end: the guard at the start cannot see a variable set, or a module loaded, during the run.
    isolation = {"truth_environment_set": pilot.truth_environment(), "world_truth_imported": pilot.truth_module_loaded()}
    if isolation["world_truth_imported"] or isolation["truth_environment_set"]:
        raise SystemExit("world.truth or a truth path reached the re-run process; no results were written")
    out = rerun_document(first, rows, results=args.results, numbers=numbers, max_calls=args.max_calls, per_case_cap=cap,
                         provenance=pilot.provenance(started_at, code_state, manifest_hash, first["database"], script=SCRIPT),
                         isolation=isolation)
    Path(args.out).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"out": args.out, "cases": len(rows), "model_calls": spent()}))


if __name__ == "__main__":
    main()
