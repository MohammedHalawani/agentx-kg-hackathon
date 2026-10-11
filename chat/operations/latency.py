"""Where one case investigation spends its time: model calls, evidence tools, their Neo4j queries and stage-event writes.

Measurement only. Nothing here changes what the investigator is sent, what it may call or what is decided; it adds
timing fields beside the records the run already keeps. Wall times are time.perf_counter() differences in seconds.

  Meter                one per case investigation (operations.graph.investigate): the session's model turns, the tool
                       belt's calls and queries, and the time spent persisting each pipeline event
  note_usage/take_usage   the token counts of the last provider response on this thread (None for a scripted model)

The summary is stored with the run as analysis["latency"] (schema "latency-1"). Its clock starts when the graph starts
(the worker has already claimed the case); the time a case waited in the queue before that is read from the ledger's
CASE_OPENED and CASE_CLAIMED audits (scripts/investigation_latency.py), never estimated here.
"""
import threading
import time

SCHEMA = "latency-1"
_last = threading.local()


def now():
    return time.perf_counter()


def note_usage(response):
    """Keep the token counts of a provider response for the caller that timed it (this thread only)."""
    usage = getattr(response, "usage_metadata", None) or {}
    if not usage:
        meta = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
        usage = {"input_tokens": meta.get("prompt_tokens"), "output_tokens": meta.get("completion_tokens")}
    _last.usage = {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}


def take_usage():
    usage, _last.usage = getattr(_last, "usage", None), None
    return usage


def turn_record(role, round_number, seconds, outcome, usage=None, prompt_chars=None):
    record = {"role": role, "round": round_number, "seconds": round(seconds, 3), "outcome": outcome}
    if prompt_chars is not None:
        record["prompt_chars"] = prompt_chars
    for key in ("input_tokens", "output_tokens"):
        if usage and isinstance(usage.get(key), int):
            record[key] = usage[key]
    return record


class Meter:
    """The timing of one case investigation. The graph registers its session and tool belt; events are timed as
    they are emitted (elapsed since start) and the on_event callback (the store's per-event write) is timed apart."""

    def __init__(self):
        self.started = now()
        self.session = None
        self.tools = None
        self.event_writes = 0
        self.event_write_seconds = 0.0

    def elapsed(self):
        return round(now() - self.started, 3)

    def timed_write(self, callback, *args):
        t0 = now()
        try:
            return callback(*args)
        finally:
            self.event_writes += 1
            self.event_write_seconds += now() - t0

    def summary(self, events):
        total = self.elapsed()
        turns = list(getattr(self.session, "turns", None) or [])
        calls = list(getattr(self.tools, "calls", None) or [])
        model_seconds = sum(t["seconds"] for t in turns)
        tool_seconds = sum(c.get("seconds") or 0 for c in calls)
        by_role = {}
        for t in turns:
            entry = by_role.setdefault(t["role"], {"calls": 0, "seconds": 0.0})
            entry["calls"] += 1
            entry["seconds"] = round(entry["seconds"] + t["seconds"], 3)
        seen, duplicates = set(), 0
        for c in calls:
            key = (c.get("tool"), repr(sorted((c.get("args") or {}).items())))
            duplicates += key in seen
            seen.add(key)

        def first(stage, statuses, iteration=None):
            return next((e.get("elapsed_seconds") for e in events if e["stage"] == stage and e["status"] in statuses
                         and (iteration is None or e.get("iteration") == iteration)), None)
        stages = {}
        opened = {}
        for e in events:
            if e.get("elapsed_seconds") is None:
                continue
            key = e["stage"]     # a stage's closing event can carry the next iteration number (review), so pair by stage
            if e["status"] in ("RUNNING", "RETRYING") and key not in opened:
                opened[key] = e["elapsed_seconds"]
            elif e["status"] not in ("RUNNING", "RETRYING") and key in opened:
                stages[e["stage"]] = round(stages.get(e["stage"], 0) + e["elapsed_seconds"] - opened.pop(key), 3)
        tokens = {k: sum(t.get(k) or 0 for t in turns) for k in ("input_tokens", "output_tokens")}
        return {"schema": SCHEMA, "clock": "graph start (case already claimed) to the end of the graph",
                "total_seconds": total,
                # The first model conclusion with hypotheses (round 0), the first independent review, the final decision.
                "first_conclusion_seconds": first("classify", ("COMPLETED", "DEGRADED"), 0),
                "first_review_seconds": first("review", ("COMPLETED", "REJECTED", "HUMAN_REVIEW", "DEGRADED", "SKIPPED")),
                "final_seconds": first("writeback", ("COMPLETED", "DEGRADED")) or first("escalate", ("COMPLETED", "DEGRADED")),
                "stages": stages,
                "model": {"calls": len(turns), "seconds": round(model_seconds, 3), "by_role": by_role,
                          **({k: v for k, v in tokens.items() if v} if any(tokens.values()) else {}), "turns": turns},
                "tools": {"calls": len(calls), "seconds": round(tool_seconds, 3), "duplicate_calls": duplicates,
                          "queries": sum(c.get("queries") or 0 for c in calls),
                          "query_seconds": round(sum(c.get("query_seconds") or 0 for c in calls), 3),
                          "cached_queries": sum(c.get("cached_queries") or 0 for c in calls)},
                "event_writes": {"count": self.event_writes, "seconds": round(self.event_write_seconds, 3)},
                "other_seconds": round(max(total - model_seconds - tool_seconds - self.event_write_seconds, 0), 3)}
