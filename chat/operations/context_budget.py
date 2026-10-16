"""Input-limit management for the investigator and the reviewer (V3.4.1).

Every model request is refused before dispatch when its conservative input bound (operations.inference_safety.input_bound)
exceeds SUHAIL_MAX_INPUT_BYTES. That bound stays as it is. This module lets the roles stay under it instead of running into
it: it measures a request exactly as the dispatcher will, and it shortens older tool results deterministically when the
conversation would otherwise not fit.

Measured on the 24 recorded V3.4 runs (artifacts/v341): the fixed part of every investigator request is about 23k
characters, each tool result adds a median 3.5k (largest 6.5k), and the bound counts each quote inside a tool result twice
(JSON escaping, about 9%). Four of the five refused requests were revision rounds, which re-send the whole conversation.

Compaction (no model is used to summarise): an older tool result becomes a digest that keeps every id it named, each
evidence id with its kind, scope and times as the run's evidence index holds them, every computed comparison with its
values, the tool and its arguments, and a label saying that it was shortened, why, and that calling the tool again shows
the full result. Nothing is dropped silently: every id found in the original text is in the digest, the run records
which results were shortened and which ids they carried, and the full records stay in the run's evidence index for the
reviewer and the UI. Results that hold evidence a review or the conclusion marked as contradicting are never shortened.
Results that the current hypotheses cite, and the latest tool turn's results, are shortened only when nothing else lets a
conclusion fit (the cited records reach the reviewer in full regardless).
"""
import json
import logging
import re
from datetime import datetime

from operations.inference_safety import SafetyRefused, input_bound, input_limit

log = logging.getLogger("suhail.context")

CONTEXT_EXHAUSTED = "context_exhausted"
CONTEXT_ERROR = "context limit reached before a valid conclusion"
# When compaction is needed at all, it frees about one more median tool result than strictly needed, so that the next turn
# does not compact again straight away (median result 3.5k characters; the bound counts about 9% more).
HEADROOM_BYTES = 4096
NOTE_RESERVE_BYTES = 1024      # the reviewer's corrective-retry text, sent with a retried review request
TOOL_PREFIX = "TOOL RESULT "
COMPACTED = "COMPACTED"
_ID = re.compile(r"DEMO-[A-Za-z0-9_.:-]*[A-Za-z0-9]")


def limit():
    """The input bound in force (SUHAIL_MAX_INPUT_BYTES), or None when it is not configured validly; the dispatcher then
    refuses every call anyway, and nothing here pretends otherwise."""
    try:
        return input_limit()
    except SafetyRefused:
        return None


def request_bytes(messages):
    """The bound the dispatcher computes for these {role, content} messages (llm.pipeline._llm.invoke on their contents)."""
    return input_bound([m["content"] for m in messages])


def text_bytes(*contents):
    """The bound of a request made of these plain strings (the reviewer's system and user message)."""
    return input_bound(list(contents))


def ids_in(text):
    return set(_ID.findall(text or ""))


def _time(value):
    """An index time without changing its meaning: a UTC offset written as Z."""
    return value[:-6] + "Z" if isinstance(value, str) and value.endswith("+00:00") else value


def _stamp(key, entry):
    """One evidence id with its times, losslessly: id@occurred_at+Ns (recorded N seconds later), id@=recorded_at when only
    the recording time is known, or the bare id for a record without times (a device, a facility)."""
    occurred, recorded = _time(entry.get("occurred_at")), _time(entry.get("recorded_at"))
    if occurred and recorded:
        try:
            lag = (datetime.fromisoformat(recorded.replace("Z", "+00:00")) - datetime.fromisoformat(occurred.replace("Z", "+00:00")))
            seconds = lag.total_seconds()
            if seconds == int(seconds):
                return f"{key}@{occurred}+{int(seconds)}s"
        except ValueError:
            pass
        return f"{key}@{occurred}|{recorded}"
    if occurred or recorded:
        return f"{key}@{occurred}" if occurred else f"{key}@={recorded}"
    return key


def digest(step, original, tools, *, reason="input limit"):
    """The compacted text of one tool result message. step: the call (tool, args, evidence_ids, computed_ids)."""
    index, computed_results = getattr(tools, "index", {}) or {}, getattr(tools, "computed", {}) or {}
    evidence = {}
    for key in step["evidence_ids"]:
        if key in computed_results:
            continue
        entry = index.get(key) or {}
        evidence.setdefault(f"{entry.get('kind') or 'record'}/{entry.get('scope') or 'unknown'}", []).append(_stamp(key, entry))
    computed = {}
    for key in step.get("computed_ids") or []:
        values = {k: v for k, v in (computed_results.get(key) or {}).items()
                  if k not in ("kind", "scope", "tool", "computed_as_of") and v not in (None, "", [], {})}
        if len(values.get("input_ids") or []) > 6:
            values["input_ids_count"] = len(values.pop("input_ids"))
        computed[key] = values
    body = {"args": step.get("args") or {}, "evidence": evidence, "computed": computed}
    head = (f"{TOOL_PREFIX}{step['tool']} ({COMPACTED} for the {reason}. Each evidence id is kept with its kind/scope and times as "
            f"id@occurred_at+Ns (recorded N seconds later); computed results keep their values; every id here stays citable. The "
            f"full result is in the run's evidence index: call {step['tool']} again to read it in full): ")
    text = head + json.dumps(body, default=str, ensure_ascii=False, separators=(",", ":"))
    missing = sorted(ids_in(original) - ids_in(text))
    if missing:   # ids the original text named inside its records (packages, devices, inputs): kept by name
        body["also_named"] = missing
        text = head + json.dumps(body, default=str, ensure_ascii=False, separators=(",", ":"))
    return text


class ContextLedger:
    """What one case investigation did about its input limit, kept with the session and recorded with the run."""

    def __init__(self, bound):
        self.bound = bound
        self.results = {}        # message index -> the tool call that produced it
        self.compactions = []    # one entry per shortened message
        self.conclude_only = None
        self.exhausted = None
        self.refused = []        # requests the dispatcher refused anyway (defence in depth): their sizes
        self.max_request = 0

    def note_result(self, index, step):
        self.results[index] = step

    def protected(self, session):
        """Ids whose results stay in full: what the current hypotheses cite and what any review or the conclusion marked
        as contradicting."""
        cited, contradicting = set(), set()
        for conclusion in session.conclusions[-1:]:
            for h in conclusion.get("hypotheses") or []:
                cited.update(x for x in h.get("supporting_evidence_ids") or [] if isinstance(x, str))
                contradicting.update(x for x in h.get("contradicting_evidence_ids") or [] if isinstance(x, str))
        for review in session.reviews:
            contradicting.update(x for x in review.get("unaddressed_contradictions") or [] if isinstance(x, str))
        return cited, contradicting

    def compact(self, session, tools, target, *, latest_too=False):
        """Shorten tool results, oldest first, until the conversation's bound is at most `target` or nothing more may be
        shortened. Normally only older results that hold no evidence the current hypotheses cite. latest_too (only to let a
        conclusion through): the latest tool turn's results and results the hypotheses cite may be shortened too; the
        cited records themselves reach the reviewer in full either way. Results holding evidence that a review or the
        conclusion marked as contradicting are never shortened. Returns the bytes saved."""
        messages = session.messages
        before = request_bytes(messages)
        if before <= target:
            return 0
        cited, contradicting = self.protected(session)
        keep = contradicting if latest_too else cited | contradicting
        last_assistant = max((i for i, m in enumerate(messages) if m["role"] == "assistant"), default=-1)
        for index in sorted(self.results):
            if request_bytes(messages) <= target:
                break
            step, content = self.results[index], messages[index]["content"]
            if COMPACTED in content[:len(TOOL_PREFIX) + 60] or (index > last_assistant and not latest_too):
                continue
            if set(step["evidence_ids"]) & keep:
                continue
            short = digest(step, content, tools)
            if len(short.encode("utf-8")) >= len(content.encode("utf-8")):
                continue
            messages[index] = {**messages[index], "content": short}
            self.compactions.append({"message": index, "round": step.get("round"), "at_round": session.rounds - 1, "tool": step["tool"],
                                     "evidence_ids": list(step["evidence_ids"]), "computed_ids": list(step.get("computed_ids") or []),
                                     "chars_before": len(content), "chars_after": len(short), "latest_turn": index > last_assistant,
                                     "cited_by_current_hypotheses": sorted(set(step["evidence_ids"]) & cited)})
        saved = before - request_bytes(messages)
        if saved:
            log.info("context compaction: %d tool results shortened, %d -> %d bytes (bound %d)",
                     len(self.compactions), before, before - saved, self.bound)
        return saved

    def record(self):
        """The run's record of what was done, or None when the investigation never came near its input limit."""
        if not (self.compactions or self.conclude_only or self.exhausted or self.refused):
            return None
        shortened = sorted({i for c in self.compactions for i in c["evidence_ids"]})
        return {"input_bound_bytes": self.bound, "max_request_bytes": self.max_request,
                "compacted_results": len(self.compactions), "compactions": self.compactions,
                "shortened_evidence_ids": shortened, "conclude_only": self.conclude_only, "exhausted": self.exhausted,
                "refused_by_dispatcher": self.refused,
                "note": "Shortened results keep every id with its kind, scope and times; full records are in the evidence index."}


def fit_review_packet(system, packet, bound, *, reserve=NOTE_RESERVE_BYTES):
    """The reviewer's packet within the input bound, or None when it cannot be made to fit without dropping what the
    review rests on. Returns (packet, trimmed): trimmed lists what was left out, and the packet says so itself.

    Only bounded, already-optional parts are reduced, in this order: the contents of retrieved-but-uncited records (lowest
    priority first; records a previous review flagged are never removed; every id stays in the inventory), then long
    input-id lists of computed results (replaced by their count). Cited records, citation validity, the deterministic
    checks, the conclusion and earlier reviews are never reduced."""
    def size(p):
        return text_bytes(system, json.dumps({"facts": p}, default=str, ensure_ascii=False)) + reserve
    if size(packet) <= bound:
        return packet, None
    packet = json.loads(json.dumps(packet, default=str, ensure_ascii=False))
    trimmed = {"uncited_records_removed": [], "computed_input_lists_shortened": []}
    flagged = {key for review in packet.get("previous_reviews") or [] for key in review.get("unaddressed_contradictions") or []}
    records = packet.get("retrieved_uncited_records") or {}
    for key in reversed(list(records)):
        if size(packet) <= bound:
            break
        if key in flagged:
            continue
        records.pop(key)
        trimmed["uncited_records_removed"].append(key)
    for key, values in (packet.get("computed_results_seen") or {}).items():
        if size(packet) <= bound:
            break
        if isinstance(values, dict) and len(values.get("input_ids") or []) > 12:
            values["input_ids_count"] = len(values.pop("input_ids"))
            trimmed["computed_input_lists_shortened"].append(key)
    coverage = packet.get("uncited_record_coverage")
    if isinstance(coverage, dict) and trimmed["uncited_records_removed"]:
        coverage["shown"] = len(records)
        coverage["not_shown"] = coverage.get("not_shown", 0) + len(trimmed["uncited_records_removed"])
        coverage["removed_for_input_limit"] = len(trimmed["uncited_records_removed"])
    if trimmed["computed_input_lists_shortened"]:
        packet["computed_input_lists_shortened_for_input_limit"] = list(trimmed["computed_input_lists_shortened"])
    if size(packet) > bound:
        return None, trimmed
    return packet, trimmed
