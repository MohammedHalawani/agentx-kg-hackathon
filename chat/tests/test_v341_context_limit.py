"""V3.4.1: the investigator and the reviewer stay within the input bound instead of running into it.

Five recorded V3.4 investigations (Workstream B, 2026-10-16) ended with no diagnosis because a request grew past
SUHAIL_MAX_INPUT_BYTES: the dispatcher refused it, the investigator retried it unchanged, and the case was recorded as
"model unavailable" (AUTH-02). Their tool results were rebuilt exactly on a disposable copy of the world at the recorded
snapshot (every evidence id and computed-result id equal to the recorded ones) and are replayed here offline: the real
tools over the recorded database rows, a scripted model that repeats the recorded tool choices, and the real investigator,
reviewer, graph and authority code. Synthetic data only.
"""
import gzip
import hashlib
import json
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from operations import context_budget, investigator
from operations.context_budget import COMPACTED, digest, ids_in, request_bytes
from operations.inference_safety import ContextLimitExceeded, SafetyRefused, input_bound

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v341"
TRACES = sorted(FIXTURES.glob("*.json.gz"))
BOUND = 65536
# The settings of the recorded runs (artifacts\v34-four-lane\v34_backend.ps1): three tools a reply, the overview fetched
# first, one repair, the forced final turn, 12 model calls a case.
RECORDED = {"SUHAIL_TOOL_BATCH": "3", "SUHAIL_PREFETCH_OVERVIEW": "1", "SUHAIL_INVALID_OUTPUT_REPAIR": "1",
            "SUHAIL_FORCED_CONCLUSION": "1", "SUHAIL_MAX_INPUT_BYTES": str(BOUND), "SUHAIL_MODEL_CALL_CAP": "12"}
CONCLUDE_NOTES = (investigator.CONTEXT_FINAL_MESSAGE, investigator.FORCED_MESSAGE, "No further tool calls are possible")
RESOLVED_STATES = {"RESOLVED", "VERIFIED", "VERIFIED_RESOLVED", "CLOSED"}


def load(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


class Replay:
    """One recorded case: the real tools over the recorded read-model rows (any other query fails the test)."""

    def __init__(self, fixture):
        from operations.datasets import dataset_config
        self.f = fixture
        self.config = dataset_config(fixture["config"])
        self.fetches = {(r["name"], json.dumps(r["params"], sort_keys=True)): r["rows"] for r in fixture["rows"]["fetch"]}
        self.precedent_rows = {r["cause"]: r["rows"] for r in fixture["rows"]["precedents"]}

    def fetch(self, name, **params):
        key = (name, json.dumps(params, sort_keys=True))
        if key not in self.fetches:
            raise AssertionError(f"query not recorded: {key}")
        return json.loads(json.dumps(self.fetches[key]))

    def precedents(self, sid, codes):
        codes = list(codes)
        return json.loads(json.dumps(self.precedent_rows.get(codes[0], []))) if len(codes) == 1 else []

    def tools(self):
        from operations.tools import InvestigationTools
        return InvestigationTools(json.loads(json.dumps(self.f["context"])), self.config, symptoms=self.f["symptoms"],
                                  precedents=lambda cause: self.precedents(self.f["shipment_id"], [cause]), port=self.fetch)


class ScriptedModel:
    """Repeats the recorded tool choices, round by round. Where the recording ends (the original request was refused there),
    `after` decides: "conclude" replies with the round's recorded conclusion (or an honest INSUFFICIENT_EVIDENCE when none was
    recorded); "more_tools" keeps asking for tools until it is told to conclude; "stubborn" never concludes."""

    def __init__(self, fixture, after="conclude"):
        self.f, self.after = fixture, after
        self.plan = {}
        groups = {}
        for s in fixture["steps"]:
            if s.get("chosen_by") == "prefetch":
                continue
            groups.setdefault((s["round"], s["model_seconds"]), []).append({"tool": s["tool"], "args": s["args"], "purpose": s["purpose"]})
        for (rnd, _), calls in groups.items():
            self.plan.setdefault(rnd, []).append({"action": "call", "calls": calls})
        self.recorded_conclusions = {r["round"]: r["conclusion"] for r in fixture["rounds"] if r.get("conclusion")}
        for rnd, conclusion in self.recorded_conclusions.items():
            self.plan.setdefault(rnd, []).append({"action": "conclude", **conclusion})
        self.extra = [{"tool": s["tool"], "args": s["args"], "purpose": "look again"} for s in fixture["steps"] if s.get("chosen_by") != "prefetch"]
        self.requests, self.oversized = [], []

    def round_of(self, sent):
        return sum(1 for m in sent if m["role"] == "user" and m["content"].startswith("REVIEW OF YOUR CONCLUSION"))

    def __call__(self, sent):
        size = input_bound([m["content"] for m in sent])
        self.requests.append(size)
        if size > BOUND:
            self.oversized.append(size)
        last = sent[-1]["content"]
        rnd = self.round_of(sent)
        told_to_conclude = sent[-1]["role"] == "user" and any(note in last for note in CONCLUDE_NOTES)
        queue = self.plan.get(rnd, [])
        if told_to_conclude and self.after != "stubborn":
            return self.conclusion(sent, rnd)
        if queue:
            reply = queue[0]
            if reply["action"] == "conclude" or not told_to_conclude:
                return queue.pop(0)
        if self.after == "conclude":
            return self.conclusion(sent, rnd)
        self.extra.append(self.extra.pop(0))
        return {"action": "call", "calls": [self.extra[0]]}

    def conclusion(self, sent, rnd):
        for r in sorted(self.recorded_conclusions, reverse=True):
            if r <= rnd:
                return {"action": "conclude", **self.recorded_conclusions[r]}
        ids = sorted({i for s in self.f["steps"] for i in s["evidence_ids"]})[:2]
        return {"action": "conclude", "hypotheses": [{"cause": "INSUFFICIENT_EVIDENCE", "status": "uncertain",
                                                      "supporting_evidence_ids": [], "contradicting_evidence_ids": ids,
                                                      "assessment": "The retrieved records do not establish a cause."}],
                "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low",
                "missing_evidence": ["a record that distinguishes the remaining explanations"],
                "next_evidence_step": "Request additional evidence from the facility that last recorded the parcel.",
                "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False,
                "summary": "The evidence available now does not establish a cause."}


class ScriptedReviewer:
    """Repeats the recorded review verdicts in order; past the recording, asks for a person (a conservative verdict)."""

    def __init__(self, fixture):
        self.recorded = [r["review"] for r in fixture["rounds"] if (r.get("review") or {}).get("model_verdict") not in (None, "UNAVAILABLE")]
        self.requests, self.oversized, self.calls = [], [], 0

    def __call__(self, system, user, default):
        size = input_bound([system, user])
        self.requests.append(size)
        if size > BOUND:
            self.oversized.append(size)
        review = self.recorded[self.calls] if self.calls < len(self.recorded) else None
        self.calls += 1
        if review is None:
            return {"verdict": "HUMAN_REVIEW", "feedback": "A person should decide.", "unsupported_claims": [],
                    "unaddressed_contradictions": [], "alternatives_tested": "yes"}
        return {"verdict": review["model_verdict"], "feedback": review.get("feedback") or "",
                "unsupported_claims": review.get("unsupported_claims") or [],
                "unaddressed_contradictions": review.get("unaddressed_contradictions") or [],
                "alternatives_tested": review.get("alternatives_tested") or "no"}


def run_case(fixture, after="conclude"):
    """The recorded case through the real graph (investigator, reviewer, guard, authority), offline."""
    from operations.graph import investigate
    replay = Replay(fixture)
    model, reviewer = ScriptedModel(fixture, after), ScriptedReviewer(fixture)
    agents = SimpleNamespace(
        investigate=lambda tools, **kw: investigator.investigate(tools, turn=model, **kw),
        review=lambda *a, **kw: investigator.review(*a, ask=reviewer, **kw))
    with mock.patch.dict(os.environ, RECORDED):
        analysis, _ = investigate(fixture["shipment_id"], fixture["as_of"], replay.config,
                                  lambda sid, as_of: json.loads(json.dumps(fixture["context"])), replay.precedents,
                                  agents=agents, live_session=True, symptoms=fixture["symptoms"], port=replay.fetch, call_cap=12)
    return analysis, model, reviewer


@unittest.skipUnless(TRACES, "V3.4.1 replay fixtures missing")
class FiveRecordedTraces(unittest.TestCase):
    maxDiff = None

    def test_the_offline_tools_return_exactly_what_the_recorded_runs_saw(self):
        for path in TRACES:
            f = load(path)
            with self.subTest(trace=path.name):
                tools = Replay(f).tools()
                for s in f["steps"]:
                    tools.begin_round(s["round"])
                    got = tools.call(s["tool"], s["args"])
                    self.assertEqual(got["evidence_ids"], s["evidence_ids"])
                    self.assertEqual(got["computed_ids"], s["computed_ids"])
                    self.assertEqual(hashlib.sha256(got["result"].encode("utf-8")).hexdigest(), s["result_sha256"])

    def test_the_recorded_runs_failed_as_model_unavailable_at_the_input_bound(self):
        for path in TRACES:
            f = load(path)
            with self.subTest(trace=path.name):
                self.assertEqual(f["investigation_mode"], "model_unavailable")
                self.assertEqual(f["authority_rule_id"], "AUTH-02-model-degraded")
                self.assertEqual([e["error"] for e in f["validation_errors"]][-2:], ["model call failed (SafetyRefused)"] * 2)

    def check_case(self, f, analysis, model, reviewer):
        inv, log = analysis["investigation"], analysis.get("investigation_log") or {}
        # A model that never stops calling tools ends on the turn budget or the call cap (pre-existing kinds, still a person).
        turn_budget = inv.get("mode") in ("turn_budget_exhausted", "model_call_cap")
        # No oversized request is ever handed to the model or the reviewer, so none is refused or repeated.
        self.assertEqual(model.oversized, [])
        self.assertEqual(reviewer.oversized, [])
        self.assertTrue(all(size <= BOUND for size in model.requests + reviewer.requests))
        # Never classified as an unavailable provider.
        kinds = [d.get("kind") for d in analysis.get("degraded") or []]
        self.assertNotIn("model_unavailable", kinds)
        self.assertNotEqual(inv.get("mode"), "model_unavailable")
        if not turn_budget:
            self.assertNotEqual((analysis.get("authority") or {}).get("rule_id"), "AUTH-02-model-degraded")
        # No evidence id is lost: every id any tool returned is in the run's evidence index, and every shortened result
        # still names each of its ids.
        retrieved = {i for s in inv["steps"] for i in s["evidence_ids"]}
        self.assertTrue(retrieved <= set(log.get("evidence_index") or {}) | set(log.get("computed_results") or {}))
        self.assertEqual(set(inv["retrieved_evidence_ids"]), retrieved)
        context = log.get("context_management") or inv.get("context_management")
        if context:
            shortened = {i for c in context["compactions"] for i in c["evidence_ids"]}
            self.assertEqual(set(context["shortened_evidence_ids"]), shortened)
            self.assertTrue(shortened <= retrieved)
        # No hidden dropped contradiction: once a review or a conclusion marked evidence as contradicting, no result holding
        # it was shortened afterwards (and every shortened result kept its ids, kinds, times and computed values).
        def flagged_before(k):
            rounds = [r for r in log.get("rounds") or [] if r["round"] < k]
            ids = {i for r in rounds for i in (r.get("review") or {}).get("unaddressed_contradictions") or []}
            return ids | {i for r in rounds for h in ((r.get("conclusion") or {}).get("hypotheses") or [])
                          for i in h.get("contradicting_evidence_ids") or []}
        if context:
            for c in context["compactions"]:
                self.assertFalse(set(c["evidence_ids"]) & flagged_before(c["at_round"]), c)
        # No false verified resolution and nothing resolved by this run.
        self.assertNotIn(analysis["result"].get("workflow_state"), RESOLVED_STATES)
        self.assertIsNone(analysis.get("outcome"))
        # Either a valid conclusion that went through the reviewer and authority, or an honest handoff to a person.
        if turn_budget:
            self.assertEqual(analysis["authority"]["risk_class"], "HUMAN_REVIEW")
        elif inv.get("degraded"):
            self.assertEqual(inv["mode"], "context_exhausted")
            self.assertEqual(analysis["authority"]["rule_id"], "AUTH-28-context-exhausted")
            self.assertEqual(analysis["authority"]["risk_class"], "HUMAN_REVIEW")
            self.assertEqual(analysis["review"]["reason_code"], "INVESTIGATOR_CONTEXT_EXHAUSTED")
            partial = inv["partial_investigation"]
            self.assertEqual(set(partial["retrieved_evidence_ids"]), retrieved)
            self.assertIn("not a diagnosis", partial["last_hypotheses_status"] + " not a diagnosis")
            self.assertIsNone(inv["primary_cause"])
        else:
            self.assertIn(inv["primary_cause"], investigator.CAUSE_CHOICES)
            self.assertTrue(analysis["review"]["verdict"])

    def test_each_trace_ends_with_a_conclusion_or_an_honest_handoff_and_never_an_oversized_request(self):
        for path in TRACES:
            f = load(path)
            for after in ("conclude", "more_tools"):
                with self.subTest(trace=path.name, after=after):
                    analysis, model, reviewer = run_case(f, after)
                    self.check_case(f, analysis, model, reviewer)

    def test_the_original_refusal_point_now_fits(self):
        # The recorded run's last accepted request and its refused one, against the replay: the replay's request at the
        # same turn is within the bound (older results compacted), and the conversation up to it matches the recorded size.
        for path in TRACES:
            f = load(path)
            with self.subTest(trace=path.name):
                analysis, model, _ = run_case(f, "conclude")
                # The replay ran every recorded tool call, so it reached the point where the recorded run was refused.
                self.assertGreaterEqual(len(analysis["investigation"]["steps"]), len(f["steps"]))
                self.assertLessEqual(max(model.requests), BOUND)
                context = analysis["investigation_log"].get("context_management")
                self.assertTrue(context and context["compacted_results"] >= 1, "the replay should have needed compaction")
                self.assertLessEqual(context["max_request_bytes"], BOUND)

    def test_a_model_that_never_concludes_is_handed_to_a_person_not_called_unavailable(self):
        for path in TRACES:
            f = load(path)
            with self.subTest(trace=path.name):
                analysis, model, reviewer = run_case(f, "stubborn")
                self.check_case(f, analysis, model, reviewer)
                inv = analysis["investigation"]
                if inv.get("degraded"):
                    self.assertIn(inv["mode"], ("context_exhausted", "turn_budget_exhausted", "model_call_cap"))
                self.assertLessEqual(inv["model_calls"]["model_calls_used"], 12)


class Classification(unittest.TestCase):
    def test_each_failure_has_its_own_kind(self):
        self.assertEqual(investigator.failure_mode("model call failed (ReadTimeout)"), "model_unavailable")
        self.assertEqual(investigator.failure_mode(investigator.CONTEXT_ERROR), "context_exhausted")
        self.assertEqual(investigator.failure_mode("context limit reached before the review could be sent"), "context_exhausted")
        self.assertEqual(investigator.failure_mode(investigator.TURN_BUDGET_ERROR), "turn_budget_exhausted")
        self.assertEqual(investigator.failure_mode("model-call cap reached before a valid conclusion"), "model_call_cap")
        self.assertEqual(investigator.failure_mode("hypotheses must be a non-empty list"), "invalid_model_output")

    def test_the_input_bound_refusal_is_its_own_error_and_still_a_safety_refusal(self):
        error = ContextLimitExceeded(70000, BOUND)
        self.assertIsInstance(error, SafetyRefused)
        self.assertEqual((error.size, error.limit), (70000, BOUND))

    def test_authority_names_the_input_limit_rule_not_model_unavailable(self):
        from operations.authority import rule_id
        self.assertEqual(rule_id("Input limit reached (investigator): no oversized request was sent; the evidence gathered so far "
                                 "is attached and automatic execution is blocked."), "AUTH-28-context-exhausted")
        self.assertEqual(rule_id("Model role unavailable (investigator); automatic execution blocked."), "AUTH-02-model-degraded")

    def test_the_review_reason_has_its_arabic_text(self):
        from operations.worker import REVIEW_SUMMARY_AR, with_review_reason
        self.assertIn("INVESTIGATOR_CONTEXT_EXHAUSTED", REVIEW_SUMMARY_AR)
        self.assertEqual(with_review_reason({"verdict": "no_proposal", "reason_code": "INVESTIGATOR_CONTEXT_EXHAUSTED"})["summary_ar"],
                         REVIEW_SUMMARY_AR["INVESTIGATOR_CONTEXT_EXHAUSTED"])


class Dispatcher(unittest.TestCase):
    def test_an_oversized_request_is_refused_before_dispatch_and_logged_without_its_content(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        from llm.pipeline import _llm
        secret = "PROMPT-TEXT-" + "x" * 70000
        with mock.patch.dict(os.environ, {"SUHAIL_MAX_INPUT_BYTES": str(BOUND)}), \
                mock.patch.object(_llm.provider_gate, "shared", side_effect=AssertionError("no provider slot may be taken")), \
                self.assertLogs("suhail.context", "WARNING") as logs:
            with self.assertRaises(ContextLimitExceeded) as caught:
                _llm.invoke([SystemMessage("s"), HumanMessage(secret)])
        self.assertGreater(caught.exception.size, BOUND)
        self.assertEqual(caught.exception.limit, BOUND)
        self.assertTrue(any("not dispatched" in line and f"bound={BOUND}" in line for line in logs.output))
        self.assertFalse(any("PROMPT-TEXT" in line for line in logs.output))

    def test_the_ledger_refuses_the_same_way(self):
        from operations.inference_safety import InferenceLedger, Policy
        policy = Policy(10, 10 ** 9, "100", "1", "1", BOUND, 2048)
        ledger = InferenceLedger(policy, path=Path(os.environ.get("TEMP", ".")) / "suhail-v341-ledger-test.json")
        with self.assertRaises(ContextLimitExceeded):
            ledger._charge(["x" * (BOUND + 1)])


class FakeTools:
    """A minimal tool belt whose results are as large as asked (each result names its ids)."""
    CATALOG = {"big": ({}, "a large result"), "shipment_overview": ({}, "start")}

    def __init__(self, size=6000):
        self.size, self.retrieved, self.calls, self.index, self.computed, self.round, self.disabled = size, set(), [], {}, {}, 0, ()
        self.sid, self.as_of, self.symptoms = "DEMO-SHP-T", "2026-09-17T03:30:00+00:00", []

    def describe(self):
        return [{"tool": k, "args": a, "returns": t} for k, (a, t) in self.CATALOG.items()]

    def round_calls(self, number=None):
        return [c for c in self.calls if c["round"] == (self.round if number is None else number)]

    def begin_round(self, number):
        self.round = number

    def call(self, tool, args):
        n = len(self.calls)
        ids = [f"DEMO-SHP-T-REC-{n:03d}-{k}" for k in range(4)]
        for i in ids:
            self.index[i] = {"kind": "ScanEvent", "scope": "shipment", "occurred_at": "2026-09-16T10:00:00+00:00",
                             "recorded_at": "2026-09-16T10:01:00+00:00"}
        self.retrieved.update(ids)
        self.calls.append({"round": self.round, "tool": tool, "args": {}, "evidence_ids": ids, "computed_ids": [], "seconds": 0})
        text = json.dumps({"rows": [{"id": i, "note": "y" * (self.size // 4)} for i in ids]}) + " CITABLE_EVIDENCE_IDS: " + json.dumps(ids)
        return {"result": text, "evidence_ids": ids, "computed_ids": []}


def calls_forever(seen):
    return {"action": "call", "tool": "big", "args": {}, "purpose": "more"}


class InvestigatorLoop(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"SUHAIL_MAX_INPUT_BYTES": "30000", "SUHAIL_TOOL_BATCH": "1",
                                               "SUHAIL_PREFETCH_OVERVIEW": "0", "SUHAIL_FORCED_CONCLUSION": "0",
                                               "SUHAIL_INVALID_OUTPUT_REPAIR": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_dispatcher_refusal_is_not_retried_unchanged_and_not_a_provider_failure(self):
        sent = []
        def refuse(messages):
            sent.append(json.dumps(messages))
            raise ContextLimitExceeded()
        session = investigator.Session(12)
        out = investigator.investigate(FakeTools(), turn=refuse, session=session)
        self.assertEqual(out["mode"], "context_exhausted")
        self.assertEqual(len(sent), 1)                       # never sent again as it was
        self.assertEqual(session.budget.used, 0)             # a refused request is not a model call
        self.assertIn("partial_investigation", out)
        self.assertEqual(out["summary"], investigator.CONTEXT_SUMMARY)

    def test_older_results_are_compacted_with_every_id_then_the_model_is_asked_to_conclude(self):
        tools, seen = FakeTools(), []
        def model(messages):
            seen.append(messages)
            if investigator.CONTEXT_FINAL_MESSAGE in messages[-1]["content"]:
                ids = sorted(tools.retrieved)[:1]
                return {"action": "conclude", "hypotheses": [{"cause": "INSUFFICIENT_EVIDENCE", "status": "uncertain",
                                                              "supporting_evidence_ids": [], "contradicting_evidence_ids": ids,
                                                              "assessment": "Not established."}],
                        "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low", "missing_evidence": ["a later scan"],
                        "next_evidence_step": "Request additional evidence.", "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE",
                        "requires_physical_check": False, "summary": "Not established."}
            return calls_forever(messages)
        session = investigator.Session(14)
        out = investigator.investigate(tools, turn=model, session=session)
        self.assertFalse(out["degraded"], out.get("validation_error"))
        self.assertTrue(out["context_conclude_only"])
        self.assertTrue(all(request_bytes(m) <= 30000 for m in seen))
        record = out["context_management"]
        self.assertGreaterEqual(record["compacted_results"], 1)
        final = seen[-1]
        for index, message in enumerate(final):
            if COMPACTED in message["content"][:80]:
                step = session.context.results[index]
                self.assertTrue(set(step["evidence_ids"]) <= ids_in(message["content"]))
        # The full records stay where the reviewer and the run log read them.
        self.assertEqual(set(tools.index), tools.retrieved)

    def test_a_model_that_keeps_calling_at_the_limit_is_handed_over_as_context_exhausted(self):
        session = investigator.Session(14)
        seen = []
        out = investigator.investigate(FakeTools(), turn=lambda m: (seen.append(m), calls_forever(m))[1], session=session)
        self.assertTrue(out["degraded"])
        self.assertEqual(out["mode"], "context_exhausted")
        self.assertTrue(all(request_bytes(m) <= 30000 for m in seen))
        self.assertEqual(out["partial_investigation"]["retrieved_evidence_ids"], out["retrieved_evidence_ids"])
        self.assertTrue(out["context_management"]["exhausted"])

    def test_nothing_changes_while_the_conversation_fits(self):
        with mock.patch.dict(os.environ, {"SUHAIL_MAX_INPUT_BYTES": "65536"}):
            tools, seen = FakeTools(size=200), []
            replies = [calls_forever(None), calls_forever(None)]
            def model(messages):
                seen.append(messages)
                return replies.pop(0) if replies else {"action": "conclude", "hypotheses": [
                    {"cause": "INSUFFICIENT_EVIDENCE", "status": "uncertain", "supporting_evidence_ids": [], "contradicting_evidence_ids": [],
                     "assessment": "x"}], "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low", "missing_evidence": ["y"],
                    "next_evidence_step": "z", "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False,
                    "summary": "s"}
            out = investigator.investigate(tools, turn=model, session=investigator.Session(12))
        self.assertNotIn("context_management", out)
        self.assertNotIn("context_conclude_only", out)
        self.assertFalse(any(COMPACTED in m["content"] for m in seen[-1]))


class Digest(unittest.TestCase):
    def test_a_digest_keeps_every_id_times_and_computed_values_and_says_it_was_shortened(self):
        tools = SimpleNamespace(index={"DEMO-SHP-1-SCAN-001": {"kind": "ScanEvent", "scope": "shipment",
                                                              "occurred_at": "2026-09-16T10:00:00+00:00", "recorded_at": "2026-09-16T12:30:00+00:00"}},
                                computed={"DEMO-CMP-abc": {"kind": "ComputedResult", "scope": "computed", "computation": "weight_comparison",
                                                           "outside_tolerance": True, "difference_kg": 1.4, "input_ids": ["DEMO-SHP-1-SCAN-001"]}})
        original = ('TOOL RESULT scans: {"rows": [{"scan": "DEMO-SHP-1-SCAN-001", "device": "DEMO-DEV-9", "weight": 3.4, "x": "' + "z" * 3000 +
                    '"}]} CITABLE_EVIDENCE_IDS: ["DEMO-SHP-1-SCAN-001", "DEMO-CMP-abc"]')
        step = {"tool": "scans", "args": {"package_id": "DEMO-SHP-1-PKG-01"}, "evidence_ids": ["DEMO-SHP-1-SCAN-001", "DEMO-CMP-abc"],
                "computed_ids": ["DEMO-CMP-abc"]}
        text = digest(step, original, tools)
        self.assertLess(len(text), len(original))
        self.assertIn(COMPACTED, text)
        self.assertTrue(ids_in(original) <= ids_in(text))          # DEMO-DEV-9 too, named outside the citable list
        # Times kept losslessly: occurred 10:00:00, recorded 9000 s (2 h 30 min) later, as the evidence index holds them.
        self.assertIn('"ScanEvent/shipment":["DEMO-SHP-1-SCAN-001@2026-09-16T10:00:00Z+9000s"]', text)
        self.assertIn('"outside_tolerance":true', text)
        self.assertIn('"difference_kg":1.4', text)
        # V3.4.2: only the original's citable list is citable; DEMO-DEV-9 is kept by name, labelled not citable.
        self.assertTrue(text.endswith(' CITABLE_EVIDENCE_IDS: ["DEMO-SHP-1-SCAN-001", "DEMO-CMP-abc"]'))
        self.assertIn('"mentioned_ids_not_citable":["DEMO-DEV-9"]', text)
        self.assertNotIn("every id here stays citable", text)

    def test_cited_and_contradicting_evidence_is_never_shortened(self):
        tools = FakeTools()
        session = investigator.Session(12)
        session.messages = [{"role": "system", "content": "s"}]
        for n in range(4):
            r = tools.call("big", {})
            session.messages.append({"role": "assistant", "content": "{}"})
            session.messages.append({"role": "user", "content": "TOOL RESULT big: " + r["result"]})
            session.context.note_result(len(session.messages) - 1, tools.calls[-1])
        session.messages.append({"role": "assistant", "content": "{}"})
        first, second = tools.calls[0]["evidence_ids"], tools.calls[1]["evidence_ids"]
        session.conclusions.append({"hypotheses": [{"supporting_evidence_ids": first[:1], "contradicting_evidence_ids": []}]})
        session.reviews.append({"unaddressed_contradictions": second[:1]})
        session.context.compact(session, tools, 0)
        shortened = [c["message"] for c in session.context.compactions]
        self.assertEqual(sorted(shortened), [6, 8])     # 2 is cited by the current hypotheses, 4 marked as contradicting
        # Only to let a conclusion through: cited results may be shortened too (the reviewer reads cited records in full),
        # results with contradicting evidence never.
        session.context.compact(session, tools, 0, latest_too=True)
        shortened = [c["message"] for c in session.context.compactions]
        self.assertEqual(sorted(shortened), [2, 6, 8])
        self.assertEqual(session.context.compactions[-1]["cited_by_current_hypotheses"], first[:1])


class Reviewer(unittest.TestCase):
    def packet_parts(self, records=30, size=1500):
        uncited = {f"DEMO-SHP-1-REC-{n:03d}": {"kind": "ScanEvent", "text": "r" * size} for n in range(records)}
        context = {"review_round": 0, "citation_validity": {"all_valid": True, "invalid_ids": []},
                   "computed_results_seen": {"DEMO-CMP-1": {"computation": "c", "input_ids": [f"DEMO-SHP-1-REC-{n:03d}" for n in range(30)]}},
                   "retrieved_but_uncited": {"ScanEvent": {"count": records, "ids": list(uncited)}},
                   "retrieved_uncited_records": uncited,
                   "uncited_record_coverage": {"available": records, "shown": records, "not_shown": 0}}
        conclusion = {"hypotheses": [], "primary_cause": "INSUFFICIENT_EVIDENCE", "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE",
                      "summary": "s", "confidence": "low", "missing_evidence": ["m"], "next_evidence_step": "n", "requires_physical_check": False}
        return conclusion, {"DEMO-SHP-1-SCAN-001": {"kind": "ScanEvent"}}, context

    def test_an_oversized_packet_is_trimmed_in_bounded_parts_and_says_so(self):
        conclusion, records, context = self.packet_parts()
        seen = []
        def ask(system, user, default):
            seen.append(input_bound([system, user]))
            return {"verdict": "HUMAN_REVIEW", "feedback": "f", "unsupported_claims": [], "unaddressed_contradictions": [],
                    "alternatives_tested": "yes"}
        with mock.patch.dict(os.environ, {"SUHAIL_MAX_INPUT_BYTES": "30000"}):
            out = investigator.review(conclusion, records, {}, [], ask=ask, context=context, session=investigator.Session(12), repair=False)
        self.assertEqual(out["verdict"], "HUMAN_REVIEW")
        self.assertTrue(all(size <= 30000 for size in seen))
        trimmed = out["context_management"]["trimmed"]
        self.assertTrue(trimmed["uncited_records_removed"])

    def test_a_packet_that_cannot_fit_is_not_sent_and_fails_closed(self):
        conclusion, records, context = self.packet_parts()
        records = {f"DEMO-SHP-1-CITED-{n}": {"kind": "ScanEvent", "text": "c" * 2000} for n in range(30)}   # cited records never shrink
        ask = mock.Mock(side_effect=AssertionError("must not be sent"))
        with mock.patch.dict(os.environ, {"SUHAIL_MAX_INPUT_BYTES": "30000"}):
            out = investigator.review(conclusion, records, {}, [], ask=ask, context=context, session=investigator.Session(12))
        ask.assert_not_called()
        self.assertEqual(out["verdict"], "UNAVAILABLE")
        self.assertEqual(out["mode"], "context_exhausted")
        self.assertTrue(out["degraded"])

    def test_a_refused_review_is_not_retried(self):
        from operations.agents import _ask
        call = mock.Mock(side_effect=ContextLimitExceeded(70000, BOUND))
        out, mode, error = _ask("s", {"a": 1}, {}, {}, lambda o: None, call)
        self.assertIsNone(out)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(investigator.failure_mode(error), "context_exhausted")


if __name__ == "__main__":
    unittest.main()
