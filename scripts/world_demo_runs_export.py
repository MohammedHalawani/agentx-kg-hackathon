"""Archive every investigation run of the demo ledger's current session, in full, beside the session export.

  cd chat && uv run python ../scripts/world_demo_runs_export.py [--database shipments-v2-world-demo] [--out DIR]

world_demo_session.py exports each case's current detail (its latest run) and its whole audit trail. A case that was
investigated more than once has earlier runs whose full result is not in that file; this writes all of them: each
run's stored record with its result (pipeline events, investigation, review trace, authority decision), plus the
reviews, recommendations, executions, outcomes, decisions and narration events of the session. It only reads, with a
read-only session, and writes one JSON file. Ids are in their public spelling.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))

KINDS = ("OpsCase", "OpsRun", "OpsReview", "OpsRecommendation", "OpsDecision", "OpsExecution", "OpsOutcome", "OpsNarration")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default="shipments-v2-world-demo")
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "demo" / "sessions"))
    args = parser.parse_args()
    from core.query_runner import get_driver
    from operations.identifiers import public_value
    from operations.schema import public_value as plain
    driver = get_driver()
    records = {}
    with driver.session(database=args.database, default_access_mode="READ") as session:
        control = session.run("MATCH (c:OpsEntity:OpsControl) RETURN c.session_id AS session_id, c.as_of AS as_of").single()
        for kind in KINDS:
            rows = session.run(f"MATCH (n:OpsEntity:{kind}) WHERE n.split='development' RETURN properties(n) AS props ORDER BY n.recorded_at, n.entity_id")
            records[kind] = [public_value(plain(row["props"])) for row in rows]
    driver.close()
    for run in records["OpsRun"]:
        # The stored result is canonical JSON text; kept parsed so the archive is readable as it is.
        if isinstance(run.get("result_json"), str):
            run["result"] = json.loads(run.pop("result_json"))
    for kind in ("OpsRecommendation", "OpsExecution"):
        for record in records[kind]:
            record.pop("approval_context_json", None)       # Internal recheck context; the audit trail carries its decisions.
    session_id = public_value(str(control["session_id"])) if control and control["session_id"] else "no-session"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"runs_{session_id}_{stamp}.json"
    body = {"schema": "suhail-demo-runs-export-1", "synthetic": True, "session_id": session_id, "exported_at": stamp, "database": args.database,
            "simulation_clock": str(plain(control["as_of"])) if control else None, "counts": {kind: len(rows) for kind, rows in records.items()},
            "records": records}
    target.write_text(json.dumps(body, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"path": str(target), "bytes": target.stat().st_size, "counts": body["counts"]}))


if __name__ == "__main__":
    main()
