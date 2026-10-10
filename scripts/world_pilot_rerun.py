"""Re-investigate named cases of an existing pilot session after a fix, without replaying the feed or resetting anything.

  cd chat
  uv run python ../scripts/world_pilot_rerun.py ../docs/evals/<pilot>/pilot.json --cases 1,3 --out ../docs/evals/<pilot>/rerun.json

Each named case (by its number in the pilot file) is put back in the queue through the product's own explicit
re-analysis and investigated once with process_one. The clock stays where the pilot left it, so the snapshot is later
than the first investigation's and may hold more evidence; the results say so. No truth is read here (same refusals as
world_pilot.py); scoring stays a separate process. A hard model-call budget applies.
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results")
    parser.add_argument("--cases", required=True, help="comma-separated case numbers from the pilot file (1-based)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-calls", type=int, default=72)
    args = parser.parse_args(argv)
    pilot.refuse_truth_access()
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
    cap = model_call_cap()
    spent = pilot.provider_calls
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
        store.execute_step(limit=5)
        record = pilot.case_record(store, reader, case_id, {"opened_at": row["opened_at"], "symptoms": row["opening_symptoms"],
                                                             "shipment_id": row["shipment_id"]},
                                   result, round(time.time() - begun, 1), before, spent(), state_after)
        record.update(pilot_case=number, first_primary_cause=row["primary_cause"], first_authority=row["authority"],
                      state_before_rerun=state)
        rows.append(record)
        print(f"rerun: pilot case {number} {row['primary_cause']} -> {record.get('primary_cause')} "
              f"authority {(record.get('authority') or {}).get('risk_class')} calls {record.get('model_calls_used')}", flush=True)
    out = {**{k: first[k] for k in ("schema", "synthetic", "database", "dataset_id", "manifest_hash", "session_id", "settings")},
           "rerun_of": str(args.results), "note": "Same cases re-investigated after a fix; the snapshot is the clock the pilot ended on, "
           "later than the first investigation's.", "provenance": pilot.provenance(started_at, code_state, manifest_hash, first["database"]),
           "cases": rows, "cases_not_investigated": []}
    Path(args.out).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"out": args.out, "cases": len(rows), "model_calls": spent()}))


if __name__ == "__main__":
    main()
