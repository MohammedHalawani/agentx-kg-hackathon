"""How long GPT-OSS investigations take, from run records or from the operations ledger. Read-only.

    python scripts/investigation_latency.py records docs/evals/2026-10-10_world1_pilot/pilot.json [more files] [--json out.json]
    python scripts/investigation_latency.py ledger --database shipments-v2-world-1-small [--json out.json]

records  reads run-record files as they are committed: the pilot's results files ({"cases": [...]}), and the Stage 3
         harness's agent results (results/<phase>/agent.jsonl, one ArmResult per line). It needs nothing else.
         Records written before the latency fields existed carry only the run's wall time and call counts; for those the
         time to the first conclusion is ESTIMATED by sharing the wall time equally among the run's model calls (said so
         in the output). Records with a `latency` object (operations.latency) are measured, never estimated.
ledger   reads the operations ledger in Neo4j (read-only session): each run's pipeline events carry wall-clock
         timestamps (recorded_at), and the case's CASE_OPENED and CASE_CLAIMED audits carry wall_recorded_at. From them:
         queue time (opened to claimed), time to the first conclusion, to the first review and to the final decision,
         and the gap between consecutive tool calls (one model turn plus one tool call plus one event write each). This
         works on every run already in the ledger, including the pilot's and Stage 3's.

The online clock starts when the monitor opens a case (CASE_OPENED). In a replay or an evaluation run, cases are
opened by the replay and claimed when the harness asks; their queue time describes the harness, not online operation,
and is reported apart. Ordinary: the reviewer decided on the first round. Complex: a revision round followed.
Percentiles are nearest-rank; with few runs, p95 is the worst run or close to it.
"""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]


def nearest_rank(values, q):
    values = sorted(values)
    return values[max(1, math.ceil(q * len(values))) - 1]


def describe(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"n": len(values), "median": round(statistics.median(values), 1), "p95": round(nearest_rank(values, .95), 1),
            "worst": round(max(values), 1), "best": round(min(values), 1)}


# ---------------------------------------------------------------------- records
def load_records(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, dict) and "cases" in data:
        return data["cases"]
    return data if isinstance(data, list) else [data]


def from_record(record):
    """One run's timing from a pilot case record or a Stage 3 ArmResult."""
    latency = record.get("latency") or {}
    rounds = record.get("rounds")
    calls = record.get("model_calls_used", record.get("calls_used"))
    wall = latency.get("total_seconds", record.get("wall_seconds"))
    n_rounds = len(rounds) if isinstance(rounds, list) else (record.get("review_rounds") or None)
    tools = (sum(len(r.get("tool_calls") or []) for r in rounds) if isinstance(rounds, list) else len(record.get("steps") or []))
    first, first_how = latency.get("first_conclusion_seconds"), "measured" if latency.get("first_conclusion_seconds") is not None else None
    if first is None and isinstance(rounds, list) and rounds and calls and wall:
        # The investigator's calls of round 0: the counter after round 0 minus round 0's one review call.
        round0 = (rounds[0].get("model_calls_used_after_round") or 0) - 1
        if round0 > 0:
            first, first_how = wall * round0 / calls, "estimated"
    elif first is None and n_rounds == 1 and calls and wall:
        first, first_how = wall * (calls - 1) / calls, "estimated"
    model = latency.get("model") or {}
    tool = latency.get("tools") or {}
    return {"shipment_id": record.get("shipment_id"), "wall_seconds": wall, "calls": calls, "rounds": n_rounds, "tool_calls": tools,
            "kind": None if not n_rounds else ("ordinary" if n_rounds == 1 else "complex"),
            "first_conclusion_seconds": first, "first_conclusion": first_how,
            "final_seconds": latency.get("final_seconds"),
            "model_seconds": model.get("seconds"), "tool_seconds": tool.get("seconds"), "queries": tool.get("queries"),
            "query_seconds": tool.get("query_seconds"), "event_write_seconds": (latency.get("event_writes") or {}).get("seconds"),
            "seconds_per_model_call": round(wall / calls, 2) if wall and calls else None,
            "degraded": bool(record.get("degraded"))}


def summarize(runs):
    out = {}
    for name, chosen in (("all", runs), ("ordinary", [r for r in runs if r["kind"] == "ordinary"]),
                         ("complex", [r for r in runs if r["kind"] == "complex"])):
        if not chosen:
            continue
        out[name] = {key: describe([r[key] for r in chosen]) for key in
                     ("wall_seconds", "first_conclusion_seconds", "final_seconds", "calls", "tool_calls", "seconds_per_model_call",
                      "model_seconds", "tool_seconds", "queries", "query_seconds", "event_write_seconds")}
        out[name] = {k: v for k, v in out[name].items() if v}
        how = {r["first_conclusion"] for r in chosen if r["first_conclusion"]}
        out[name]["first_conclusion_is"] = "measured" if how == {"measured"} else "estimated" if how == {"estimated"} else sorted(how)
    return out


# ---------------------------------------------------------------------- ledger
def _wall(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None


def from_run(case_id, shipment_id, analysis, audits):
    events = analysis.get("pipeline_events") or []
    stamped = [(e, _wall(e.get("recorded_at"))) for e in events if e.get("recorded_at")]
    if not stamped:
        return None
    start = stamped[0][1]

    def at(stage, statuses, iteration=None):
        return next(((t - start).total_seconds() for e, t in stamped if e["stage"] == stage and e["status"] in statuses
                     and (iteration is None or e.get("iteration") == iteration)), None)
    tool_times = [t for e, t in stamped if e["stage"] == "classify" and (e.get("output") or {}).get("kind") == "tool_call"]
    classify_starts = [t for e, t in stamped if e["stage"] == "classify" and e["status"] in ("RUNNING", "RETRYING")
                       and (e.get("output") or {}).get("kind") != "tool_call"]
    gaps = []
    for t in tool_times:
        before = max([x for x in [*classify_starts, *tool_times] if x < t], default=None)
        if before is not None:
            gaps.append((t - before).total_seconds())
    opened = min((a for a in audits if a["event_type"] == "CASE_OPENED"), key=lambda a: a["wall"], default=None)
    claimed = max((a for a in audits if a["event_type"] == "CASE_CLAIMED" and a["wall"] <= start), key=lambda a: a["wall"], default=None)
    trace = analysis.get("trace") or []
    log = analysis.get("investigation_log") or {}
    final = at("writeback", ("COMPLETED", "DEGRADED")) or at("escalate", ("COMPLETED", "DEGRADED"))
    run = {"case_id": case_id, "shipment_id": shipment_id, "mode": analysis.get("mode"),
           "queue_seconds": (claimed["wall"] - opened["wall"]).total_seconds() if opened and claimed else None,
           "claim_to_start_seconds": (start - claimed["wall"]).total_seconds() if claimed else None,
           "first_conclusion_seconds": at("classify", ("COMPLETED", "DEGRADED"), 0), "first_conclusion": "measured",
           "first_review_seconds": at("review", ("COMPLETED", "REJECTED", "HUMAN_REVIEW", "DEGRADED", "SKIPPED")),
           "final_seconds": final, "wall_seconds": final, "retrieve_seconds": at("retrieve", ("COMPLETED",)),
           "rounds": len(trace) or None, "kind": None if not trace else ("ordinary" if len(trace) == 1 else "complex"),
           "calls": log.get("model_calls_used"), "tool_calls": len(tool_times),
           "seconds_per_tool_turn": round(statistics.median(gaps), 2) if gaps else None,
           "seconds_per_model_call": round(final / log["model_calls_used"], 2) if final and log.get("model_calls_used") else None}
    latency = analysis.get("latency") or {}
    run.update({"model_seconds": (latency.get("model") or {}).get("seconds"), "tool_seconds": (latency.get("tools") or {}).get("seconds"),
                "queries": (latency.get("tools") or {}).get("queries"), "query_seconds": (latency.get("tools") or {}).get("query_seconds"),
                "event_write_seconds": (latency.get("event_writes") or {}).get("seconds")})
    return run


LEDGER_QUERY = """
MATCH (c:OpsEntity:OpsCase {dataset_id: $dataset})-[:OPS_HAS_RUN]->(r:OpsEntity:OpsRun)
OPTIONAL MATCH (c)-[:OPS_HAS_AUDIT]->(a:OpsEntity:OpsAudit) WHERE a.event_type IN ['CASE_OPENED', 'CASE_CLAIMED']
WITH c, r, collect({event_type: a.event_type, wall: a.wall_recorded_at}) AS audits
RETURN c.entity_id AS case_id, c.shipment_id AS shipment_id, r.entity_id AS run_id, r.result_json AS result_json, audits
ORDER BY c.entity_id, r.entity_id
"""


def read_ledger(database, dataset=None, uri=None, user=None, password=None):
    sys.path.insert(0, str(ROOT / "chat"))
    import config
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(uri or config.NEO4J_URI, auth=(user or config.NEO4J_USERNAME, password or config.NEO4J_PASSWORD))
    try:
        with driver.session(database=database, default_access_mode="READ") as session:
            if dataset is None:
                row = session.run("MATCH (m:_V2Import) RETURN m.manifest_json AS manifest").single()
                dataset = json.loads(row["manifest"])["dataset_id"] if row else None
            rows = list(session.run(LEDGER_QUERY, dataset=dataset))
    finally:
        driver.close()
    runs = []
    for row in rows:
        audits = [{"event_type": a["event_type"], "wall": _wall(a["wall"])} for a in row["audits"] if a.get("wall")]
        analysis = json.loads(row["result_json"] or "{}")
        if analysis.get("mode") != "gpt_oss_agents":
            continue
        run = from_run(row["case_id"], row["shipment_id"], analysis, audits)
        if run:
            runs.append(run)
    return dataset, runs


def table(summary):
    lines = ["| Runs | Measure | n | Median | p95 | Worst |", "|---|---|---|---|---|---|"]
    for group, measures in summary.items():
        for key, d in measures.items():
            if isinstance(d, dict):
                lines.append(f"| {group} | {key} | {d['n']} | {d['median']} | {d['p95']} | {d['worst']} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("records")
    rec.add_argument("files", nargs="+")
    led = sub.add_parser("ledger")
    led.add_argument("--database", required=True)
    led.add_argument("--dataset")
    for p in (rec, led):
        p.add_argument("--json")
    args = parser.parse_args(argv)
    if args.command == "records":
        runs = [from_record(r) for f in args.files for r in load_records(f)]
        source = {"files": args.files}
    else:
        dataset, runs = read_ledger(args.database, args.dataset)
        source = {"database": args.database, "dataset_id": dataset}
        queued = [r["queue_seconds"] for r in runs if r["queue_seconds"] is not None]
        source["queue_seconds"] = describe(queued)
        source["note"] = "queue_seconds in a replay or evaluation describes the harness, not online operation"
    summary = summarize(runs)
    print(table(summary))
    if args.command == "ledger" and source.get("queue_seconds"):
        print(f"\nqueue (CASE_OPENED to CASE_CLAIMED, harness): {source['queue_seconds']}")
    if args.json:
        Path(args.json).write_text(json.dumps({"source": source, "summary": summary, "runs": runs}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
