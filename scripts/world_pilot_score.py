"""Score a pilot results file against the world's private truth labels. A separate process from the pilot.

  cd chat
  uv run python ../scripts/world_pilot_score.py ../docs/evals/<dir>/pilot.json --truth-dir <truth root>\\<dataset id>
        [--split development] [--database <as in the results>] [--out <results>.scored.json]

The pilot (world_pilot.py) never sees truth. This program reads its results file, the truth directory
(<truth-dir>/<split>/truth.jsonl, written outside the repository by the world export) and, read-only, the database
the pilot ran on, and adds to every case:

- knowable_causes: world.truth.labels_at(row, t, ingested) at the investigation's snapshot t, where `ingested` is taken
  from this run's own ingestion (a record counts when it was recorded and ingested at or before t);
- a verdict: correct, incorrect, appropriately uncertain, wrongly uncertain (or: no valid conclusion).

  correct                   the primary cause is a cause knowable at the snapshot, or a code the truth row lists as
                            acceptable for a mechanism identifiable at the snapshot
  incorrect                 a specific cause that is neither; this includes a cause that only becomes knowable later
                            (reported separately as primary_is_an_eventual_cause) and any cause on a healthy shipment
  appropriately uncertain   INSUFFICIENT_EVIDENCE when no cause is knowable at the snapshot
  wrongly uncertain         INSUFFICIENT_EVIDENCE when a cause is knowable at the snapshot
  no valid conclusion       the investigation was degraded (reported apart; not an answer)

It must be run before the database's live session is reset again: it refuses when the results' session or run records
are no longer in the database, because the ingestion times would not be this run's. It makes no model calls and
writes nothing to the database.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))

ABSTENTION = "INSUFFICIENT_EVIDENCE"
VERDICTS = ("correct", "incorrect", "appropriately uncertain", "wrongly uncertain", "no valid conclusion")
SCORE_SCHEMA = "world-pilot-score-1"


def read_truth(truth_dir, split):
    path = Path(truth_dir) / split / "truth.jsonl"
    if not path.exists():
        raise SystemExit(f"No truth labels at {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["shipment_id"]: row for row in rows}


def scored_mechanisms(row):
    return [m for m in row.get("mechanisms") or [] if m.get("cause_code") and m.get("resolution") != "NONE"]


def spec_records(row):
    """Every evidence id a discrimination spec of this shipment mentions (records, and records that cancel an absence)."""
    ids = set()
    for mechanism in row.get("mechanisms") or []:
        for group in (mechanism.get("discrimination") or {}).get("any_of") or []:
            for item in group.get("all_of") or []:
                if "record" in item:
                    ids.add(item["record"])
                else:
                    ids.update(item["absence"].get("cancelled_by") or [])
    return ids


def ingested_by(driver, database, ids, snapshot):
    """Which of `ids` Suhail held at `snapshot` in this run: recorded, and for a fed record ingested, at or before it."""
    from dataset_v2.contracts import instant
    ids = sorted(ids)
    found = set()
    with driver.session(database=database, default_access_mode="READ") as session:
        for offset in range(0, len(ids), 5000):
            rows = session.run("MATCH (n:V2Entity) WHERE n.entity_id IN $ids AND n.recorded_at <= $t "
                               "AND (n.ingested_at IS NULL OR datetime(n.ingested_at) <= $t) RETURN n.entity_id AS id",
                               ids=ids[offset:offset + 5000], t=instant(snapshot))
            found.update(r["id"] for r in rows)
    return found


def score_case(case, row, ingested):
    """The verdict for one investigated case. `ingested`: evidence ids held at the case's snapshot."""
    from dataset_v2.contracts import instant
    from world.truth import discriminated, labels_at
    snapshot = case["snapshot_as_of"]
    knowable = labels_at(row, snapshot, ingested)
    mechanisms = scored_mechanisms(row)
    identified = [m for m in mechanisms if discriminated(m["discrimination"], instant(snapshot), ingested)]
    acceptable = sorted({code for m in identified for code in (m.get("acceptable_causes") or [m["cause_code"]])})
    eventual = sorted({m["cause_code"] for m in mechanisms})
    nothing_knowable = knowable in ([], [ABSTENTION])
    primary = case.get("primary_cause")
    matched = None
    if primary is None:
        verdict = "no valid conclusion"
    elif primary == ABSTENTION:
        verdict = "appropriately uncertain" if nothing_knowable else "wrongly uncertain"
    elif primary in knowable and not nothing_knowable:
        verdict, matched = "correct", "knowable_cause"
    elif primary in acceptable:
        verdict, matched = "correct", "acceptable_code_of_an_identifiable_mechanism"
    else:
        verdict = "incorrect"
    named = {h.get("cause") for h in case.get("hypotheses") or [] if h.get("status") == "supported"} | ({primary} if primary else set())
    named.discard(ABSTENTION)
    known = set() if nothing_knowable else set(knowable)
    return {"verdict": verdict, "matched": matched, "snapshot_as_of": snapshot, "shipment_healthy": bool(row.get("healthy")),
            "knowable_causes": knowable, "acceptable_codes_at_snapshot": acceptable, "eventual_causes": eventual,
            "identifiable_mechanism_types": sorted({m.get("type") for m in identified if m.get("type")}),
            "primary_cause": primary,
            "primary_is_an_eventual_cause": bool(primary and primary != ABSTENTION and primary in eventual),
            "knowable_causes_named": sorted(named & known),
            "knowable_causes_not_named": sorted(known - named),
            "supported_causes_not_knowable": sorted(named - known - set(acceptable)),
            "spec_records_held_at_snapshot": len(ingested)}


def run_records(driver, database, results):
    """The session and the run ids of the results that are still in the database."""
    run_ids = [c["run_id"] for c in results["cases"] if c.get("run_id")]
    with driver.session(database=database, default_access_mode="READ") as session:
        marker = session.run("MATCH (m:_V2Import) RETURN m.manifest_hash AS hash").single()
        control = session.run("MATCH (c:OpsEntity:OpsControl) RETURN c.session_id AS session").single()
        runs = {r["id"] for r in session.run("MATCH (r:OpsEntity:OpsRun) WHERE r.entity_id IN $ids RETURN r.entity_id AS id", ids=run_ids)}
    return (marker["hash"] if marker else None), (control["session"] if control else None), runs


def score(results, truth, driver, database):
    """The results document with a `score` on every case and a summary. Raises ValueError when the database no longer
    holds the run the results describe."""
    manifest_hash, session_id, runs = run_records(driver, database, results)
    if manifest_hash != results.get("manifest_hash"):
        raise ValueError("The database holds a different import than the one the results name")
    if session_id != results.get("session_id"):
        raise ValueError("The database's live session was reset after the pilot; its ingestion times are not this run's")
    cases = []
    for case in results["cases"]:
        row = truth.get(case["shipment_id"])
        if row is None:
            cases.append({**case, "score": {"verdict": None, "error": "no truth row for this shipment"}})
            continue
        if not case.get("snapshot_as_of"):
            cases.append({**case, "score": {"verdict": "no valid conclusion", "error": "the case has no stored run record",
                                            "run_found_in_database": case.get("run_id") in runs}})
            continue
        ingested = ingested_by(driver, database, spec_records(row), case["snapshot_as_of"])
        cases.append({**case, "score": {**score_case(case, row, ingested), "run_found_in_database": case.get("run_id") in runs}})
    verdicts = {name: sum(1 for c in cases if c["score"].get("verdict") == name) for name in VERDICTS}
    answered = verdicts["correct"] + verdicts["incorrect"]
    identifiable = [c for c in cases if c["score"].get("knowable_causes") not in (None, [], [ABSTENTION])]
    summary = {"cases": len(cases), "verdicts": verdicts,
               "identifiable_at_snapshot": len(identifiable),
               "correct_on_identifiable": sum(1 for c in identifiable if c["score"]["verdict"] == "correct"),
               "not_identifiable_at_snapshot": sum(1 for c in cases if c["score"].get("knowable_causes") in ([], [ABSTENTION])),
               "confident_wrong_answers": verdicts["incorrect"],
               "accuracy_when_answering": round(verdicts["correct"] / answered, 3) if answered else None,
               "incorrect_but_an_eventual_cause": sum(1 for c in cases if c["score"].get("verdict") == "incorrect"
                                                      and c["score"].get("primary_is_an_eventual_cause")),
               "citations_all_valid": sum(1 for c in cases if c.get("citations_all_valid")),
               "automatic_actions_authorized": sum(1 for c in cases if (c.get("authority") or {}).get("risk_class") == "AUTO"),
               "automatic_actions_on_incorrect_answers": sum(1 for c in cases if (c.get("authority") or {}).get("risk_class") == "AUTO"
                                                             and c["score"].get("verdict") == "incorrect"),
               "note": "A pilot of a few cases chosen by opening symptom set: it shows whether real investigations work end to end, "
                       "not a measured accuracy."}
    return {**results, "cases": cases, "score_schema": SCORE_SCHEMA, "summary": summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path, help="the pilot's results file")
    parser.add_argument("--truth-dir", type=Path, required=True, help="the truth directory of the dataset (holds <split>/truth.jsonl)")
    parser.add_argument("--split", default="development")
    parser.add_argument("--database", help="default: the database named in the results")
    parser.add_argument("--out", type=Path, help="default: <results>.scored.json")
    args = parser.parse_args(argv)
    results = json.loads(args.results.read_text(encoding="utf-8"))
    out = args.out or args.results.with_suffix(".scored.json")
    if out.exists():
        raise SystemExit(f"{out} exists; choose a new file")
    truth = read_truth(args.truth_dir, args.split)
    database = args.database or results["database"]
    import logging
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    import config
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD))
    with driver:
        try:
            scored = score(results, truth, driver, database)
        except ValueError as error:
            raise SystemExit(str(error))
    scored["scoring"] = {"script": "scripts/world_pilot_score.py", "split": args.split, "truth_rows": len(truth),
                         "truth_schema": next(iter(truth.values()), {}).get("truth_schema"), "database": database}
    out.write_text(json.dumps(scored, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), **scored["summary"]}))


if __name__ == "__main__":
    main()
