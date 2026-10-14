"""The per-call model timeout on the live investigator and reviewer path.

The HTTP client's timeout (LLM_TIMEOUT_SECONDS, 120 s) bounds each wait for bytes, not the call: a provider that keeps
the connection alive held one call for 210 s. llm.pipeline._llm.invoke(messages, deadline=...) is a wall-clock limit;
operations.investigator.model_turn and _review_call use it with SUHAIL_MODEL_CALL_TIMEOUT_SECONDS (default 60 s). A
call that exceeds it raises TimeoutError and is a provider failure exactly as before: one retry, then the role fails
closed. No provider, no database: the model is a fake that hangs.

V3 (operations.provider_gate): an abandoned call keeps its provider slot until the underlying call really ends, and a
retry cannot start beside it. With one slot (SUHAIL_PROVIDER_MAX_INFLIGHT=1, the default) the retry of a stalled call
therefore finds no slot: the provider is not called again and the role fails closed (CapOneTests). The earlier tests
below are about the retry rule itself, where a retry does reach the provider; they say so by asking for two slots.
Every test gets its own gate, and its hung calls are released and waited for before the next phase or test.
"""
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from llm.pipeline import _llm
from operations import investigator, provider_gate
from tests import test_investigator as ti

DEADLINE = 0.2        # seconds, for the tests
CONCLUSION = ('{"action":"conclude","hypotheses":[{"cause":"INSUFFICIENT_EVIDENCE","status":"uncertain","supporting_evidence_ids":[],'
              '"contradicting_evidence_ids":[],"assessment":"Nothing decides it."}],"primary_cause":"INSUFFICIENT_EVIDENCE","confidence":"low",'
              '"missing_evidence":["the hub scan log"],"next_evidence_step":"Ask the hub for its scan log.",'
              '"recommended_action":"REQUEST_ADDITIONAL_EVIDENCE","requires_physical_check":false,"summary":"Not enough to name a cause."}')


class Model:
    """A chat model whose calls behave as scripted: "hang" blocks until released (far longer than the deadline),
    an exception is raised, anything else is the reply's text. It records the timeout each call was given, and how
    many calls were inside it at the same moment (`peak`: the underlying calls live at once)."""

    def __init__(self, *script):
        self.script, self.calls, self.timeouts = list(script), 0, []
        self.release = threading.Event()
        self.lock, self.live, self.peak = threading.Lock(), 0, 0

    def invoke(self, messages, **kwargs):
        with self.lock:
            self.calls += 1
            self.timeouts.append(kwargs.get("timeout"))
            step = self.script.pop(0) if self.script else "hang"
            self.live += 1
            self.peak = max(self.peak, self.live)
        try:
            if step == "hang":
                self.release.wait(30)
                return SimpleNamespace(content="{}")
            if isinstance(step, Exception):
                raise step
            return SimpleNamespace(content=step)
        finally:
            with self.lock:
                self.live -= 1


class Patched(unittest.TestCase):
    def slots(self, cap):
        """This test's own provider gate with `cap` slots (the process's gate is put back afterwards)."""
        self.gate = provider_gate.ProviderGate(cap)
        self.addCleanup(provider_gate.use, provider_gate.use(self.gate))
        return self.gate

    def drain(self, *models):
        """Release these models' hung calls and wait until every underlying call has ended and given its slot back.
        Called between the phases of a test and after it, so no abandoned call of one phase holds a slot in the next."""
        for model in models:
            model.release.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (self.gate.snapshot()["inflight"] or any(m.live for m in models)):
            time.sleep(0.005)
        snapshot = self.gate.snapshot()
        self.assertEqual((snapshot["inflight"], [m.live for m in models]), (0, [0] * len(models)), "a fake provider call never ended")
        return snapshot

    def use(self, model, deadline=DEADLINE, cap=1):
        self.slots(cap)
        for patcher in (mock.patch.object(_llm, "model", return_value=model), mock.patch.object(_llm, "call_timeout", return_value=deadline)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.drain, model)          # let the abandoned calls end, and wait for them
        return model


class DeadlineTests(Patched):
    def test_a_call_that_hangs_is_abandoned_at_the_deadline_with_a_timeout_error(self):
        model = self.use(Model("hang"))
        started = time.monotonic()
        with self.assertRaises(TimeoutError) as raised:
            _llm.invoke(["m"], deadline=DEADLINE)
        waited = time.monotonic() - started
        self.assertIsInstance(raised.exception, _llm.ModelCallTimeout)
        self.assertGreaterEqual(waited, DEADLINE)
        self.assertLess(waited, DEADLINE + 2)                       # not the 30 s the provider would have taken
        self.assertEqual(model.calls,1)
        self.assertTrue(all(0<t<=DEADLINE for t in model.timeouts))  # admission consumes the same deadline

    def test_a_call_that_returns_in_time_is_returned_and_an_error_is_raised_as_itself(self):
        model = self.use(Model("answer", ConnectionError("refused")))
        self.assertEqual(_llm.invoke(["m"], deadline=DEADLINE).content, "answer")
        with self.assertRaises(ConnectionError):
            _llm.invoke(["m"], deadline=DEADLINE)
        self.assertEqual(model.calls, 2)

    def test_without_an_explicit_deadline_the_configured_limit_still_applies(self):
        plain = SimpleNamespace(invoke=lambda messages,**kwargs: SimpleNamespace(content="plain"))
        with mock.patch.object(_llm, "model", return_value=plain):
            self.assertEqual(_llm.invoke(["m"]).content, "plain")
            self.assertEqual(_llm.ask_json("s", "u", {"a": ""}), {"a": ""})

    def test_the_default_is_60_seconds_and_the_environment_variable_changes_it(self):
        self.assertEqual((_llm.CALL_TIMEOUT_ENV, _llm.DEFAULT_CALL_TIMEOUT_SECONDS), ("SUHAIL_MODEL_CALL_TIMEOUT_SECONDS", 60.0))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_llm.CALL_TIMEOUT_ENV, None)
            self.assertEqual(_llm.call_timeout(), 60.0)
            for text, expected in (("45", 45.0), ("90.5", 90.5), ("1", 5.0), ("99999", 1800.0), ("soon", 60.0), ("", 60.0), ("nan", 60.0)):
                os.environ[_llm.CALL_TIMEOUT_ENV] = text
                self.assertEqual(_llm.call_timeout(), expected, text)

    def test_the_transport_setting_alone_is_not_a_wall_clock_limit(self):
        """What was wrong: the 120 s reaches the provider client only as its timeout parameter (the wait for bytes)."""
        import config
        _llm.model.cache_clear()
        self.addCleanup(_llm.model.cache_clear)
        built = _llm.model()
        self.assertEqual(built.request_timeout, config.LLM_TIMEOUT_SECONDS)
        self.assertEqual(built._client_params["timeout"], config.LLM_TIMEOUT_SECONDS)
        self.assertEqual(built.max_retries, 0)


class InvestigatorTests(Patched, ti.Base):
    def tools(self):
        sid = sorted(sid for sid, row in self.truth.items() if row["split"] == "development")[0]
        return ti.Base.tools(self, sid, self.world.config.as_of)

    # The tests of this class are about the retry rule: the retry of a stalled call reaches the provider. That needs a
    # second provider slot while the stalled call is still open, so they ask for two (cap=2). CapOneTests has the
    # same situations with one slot.
    def test_model_turn_and_the_review_call_use_the_deadline(self):
        model = self.use(Model('{"action":"call","tool":"shipment_overview","args":{}}', "hang", '{"verdict":"ACCEPT"}', "hang"), cap=2)
        self.assertEqual(investigator.model_turn([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])["action"], "call")
        with self.assertRaises(TimeoutError):
            investigator.model_turn([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
        self.assertEqual(investigator._review_call("s", "u", {"verdict": ""}), {"verdict": "ACCEPT"})
        with self.assertRaises(TimeoutError):
            investigator._review_call("s", "u", {"verdict": ""})
        self.assertEqual(len(model.timeouts),4)
        self.assertTrue(all(0<t<=DEADLINE for t in model.timeouts))

    def test_a_stalled_investigator_call_is_a_provider_failure_retried_once_and_then_the_next_reply_is_used(self):
        model = self.use(Model("hang", CONCLUSION), cap=2)
        started = time.monotonic()
        result = investigator.investigate(self.tools(), session=investigator.Session(6))
        self.assertLess(time.monotonic() - started, DEADLINE + 5)
        self.assertFalse(result["degraded"])
        self.assertEqual(result["primary_cause"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(model.calls, 2)                                      # the stalled call and its one retry
        self.assertEqual(result["validation_errors"], [{"turn": 1, "error": "model call failed (ModelCallTimeout)"}])
        self.assertEqual(result["model_calls"]["model_calls_used"], 2)        # a stalled call is counted, as a failed one is
        self.assertEqual(model.peak, 2)                                       # the retry ran beside the stalled call: both slots

    def test_two_stalled_calls_in_a_row_fail_closed_as_model_unavailable_exactly_as_two_provider_errors_do(self):
        def run(*script):
            model = Model(*script)
            self.slots(2)                           # this phase's own two slots: the stalled call and its retry
            with mock.patch.object(_llm, "model", return_value=model), mock.patch.object(_llm, "call_timeout", return_value=DEADLINE):
                session = investigator.Session(6)
                try:
                    return model, session, investigator.investigate(self.tools(), session=session)
                finally:
                    self.drain(model)               # both hung calls have ended before the next phase starts
        model, session, stalled = run("hang", "hang", CONCLUSION)
        _other, _session, refused = run(ConnectionError("down"), ConnectionError("down"), CONCLUSION)
        self.assertEqual(model.calls, investigator.ATTEMPTS_PER_TURN)        # no third call: the retry rule is unchanged
        self.assertEqual((stalled["degraded"], stalled["mode"], stalled["primary_cause"]), (True, "model_unavailable", None))
        self.assertEqual(stalled["validation_error"], "model call failed (ModelCallTimeout)")
        self.assertEqual((refused["degraded"], refused["mode"]), (True, "model_unavailable"))
        self.assertEqual(stalled["model_calls"], refused["model_calls"])      # the same calls counted, the same way
        self.assertEqual([t["outcome"] for t in session.turns], ["provider_failure", "provider_failure"])

    def test_a_stalled_reviewer_call_is_retried_once_and_then_the_review_is_unavailable(self):
        conclusion = {"hypotheses": [], "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low", "missing_evidence": ["x"],
                      "next_evidence_step": "y", "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": "s"}
        first = self.use(Model("hang", '{"verdict":"ACCEPT","feedback":"Supported.","unsupported_claims":[],"unaddressed_contradictions":[],"alternatives_tested":"yes"}'), cap=2)
        review = investigator.review(conclusion, {}, {}, ["MILESTONE_OVERDUE"], session=investigator.Session(6), repair=False)
        self.assertEqual((review["verdict"], review["degraded"], first.calls), ("ACCEPT", False, 2))
        # The first phase's stalled call is released and has ended before the second phase: otherwise it would still hold
        # one of the two slots, and the second phase (two stalled calls) would need three.
        self.drain(first)
        model = Model("hang", "hang", '{"verdict":"ACCEPT","feedback":"late"}')
        self.slots(2)
        with mock.patch.object(_llm, "model", return_value=model):
            session = investigator.Session(6)
            review = investigator.review(conclusion, {}, {}, ["MILESTONE_OVERDUE"], session=session, repair=False)
        self.assertEqual(model.peak, 2)
        self.drain(model)
        self.assertEqual((review["verdict"], review["degraded"], review["mode"]), ("UNAVAILABLE", True, "model_unavailable"))   # fail closed, never ACCEPT
        self.assertEqual(review["validation_error"], "model call failed (ModelCallTimeout)")
        self.assertEqual((model.calls, session.budget.used), (2, 2))


class NoToolsArmTests(Patched):
    def test_the_no_tools_baseline_calls_the_model_under_the_same_deadline(self):
        from stage3_eval.arms import CaseRef, NoToolsArm
        model = self.use(Model("hang", "hang"), cap=2)      # the retry rule, with a slot for the retry
        result = NoToolsArm(c_cap=16).run(CaseRef(key="E1:S1", world="E1", shipment_id="S1", as_of="2026-09-14T09:00:00+00:00",
                                                  symptoms=("MILESTONE_OVERDUE",)))
        self.assertEqual((result.degraded, result.failure_mode, result.provider_failures, result.calls_used), (True, "model_unavailable", 2, 2))
        self.assertEqual(result.validation_error, "model call failed (ModelCallTimeout)")
        self.assertEqual(len(model.timeouts),2)
        self.assertTrue(all(0<t<=DEADLINE for t in model.timeouts))

    def test_with_one_slot_the_baseline_s_retry_is_refused_and_it_fails_closed_with_both_attempts_counted(self):
        from stage3_eval.arms import CaseRef, NoToolsArm
        model = self.use(Model("hang", '{"primary_cause":"HUB_DELAY"}'))
        result = NoToolsArm(c_cap=16).run(CaseRef(key="E1:S1", world="E1", shipment_id="S1", as_of="2026-09-14T09:00:00+00:00",
                                                  symptoms=("MILESTONE_OVERDUE",)))
        self.assertEqual((result.degraded, result.failure_mode, result.provider_failures, result.calls_used), (True, "model_unavailable", 2, 2))
        self.assertEqual(result.validation_error, "model call failed (ProviderCapacityTimeout)")
        self.assertEqual((model.calls,model.peak),(1,1))
        self.assertTrue(all(0<t<=DEADLINE for t in model.timeouts))


class CapOneTests(Patched, ti.Base):
    """One provider slot (the default): an abandoned call holds it until the underlying call really ends. Its retry does
    not reach the provider, at most one underlying call is live at any moment, and every role still fails closed with
    its attempts counted as before."""

    def tools(self):
        sid = sorted(sid for sid, row in self.truth.items() if row["split"] == "development")[0]
        return ti.Base.tools(self, sid, self.world.config.as_of)

    def test_an_abandoned_call_keeps_the_only_slot_until_it_really_ends_and_its_late_answer_is_discarded(self):
        model = self.use(Model("hang", "after"))
        with self.assertRaises(_llm.ModelCallTimeout) as abandoned:
            _llm.invoke(["m"], deadline=DEADLINE)
        self.assertNotIsInstance(abandoned.exception, _llm.ProviderCapacityTimeout)
        for _ in range(3):                                                      # however often it is retried
            with self.assertRaises(TimeoutError) as retry:
                _llm.invoke(["m"], deadline=DEADLINE)
            self.assertIsInstance(retry.exception, _llm.ProviderCapacityTimeout)
        held = self.gate.snapshot()
        self.assertEqual((model.calls, model.live, model.peak), (1, 1, 1))      # one underlying call, still open
        self.assertEqual((held["inflight"], held["granted"], held["released"], held["refused"]), (1, 1, 0, 3))     # not released by any timeout
        ended = self.drain(model)                                               # the underlying call ends: only now is the slot free
        self.assertEqual((ended["inflight"], ended["released"]), (0, 1))
        self.assertEqual(ended["calls"][0]["abandoned"], True)                  # its answer ("{}") went to nobody
        self.assertEqual(_llm.invoke(["m"], deadline=DEADLINE).content, "after")
        self.assertEqual((model.calls, model.peak), (2, 1))                     # never two underlying calls at once

    def test_a_stalled_investigator_turn_fails_closed_with_both_attempts_counted_and_one_provider_call(self):
        model = self.use(Model("hang", CONCLUSION))
        session = investigator.Session(6)
        started = time.monotonic()
        result = investigator.investigate(self.tools(), session=session)
        self.assertLess(time.monotonic() - started, 2 * DEADLINE + 5)           # the retry's wait is bounded by its own deadline
        self.assertEqual((result["degraded"], result["mode"], result["primary_cause"]), (True, "model_unavailable", None))    # never the late reply
        self.assertEqual(result["validation_error"], "model call failed (ProviderCapacityTimeout)")
        self.assertEqual((model.calls, model.peak), (1, 1))
        self.assertEqual(result["model_calls"]["model_calls_used"], investigator.ATTEMPTS_PER_TURN)     # the refused retry is counted
        self.assertEqual([t["outcome"] for t in session.turns], ["provider_failure", "provider_failure"])
        self.assertEqual(self.gate.snapshot()["inflight"], 1)                   # still held when the investigation has given up

    def test_a_stalled_review_is_unavailable_never_accept_with_one_provider_call(self):
        conclusion = {"hypotheses": [], "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low", "missing_evidence": ["x"],
                      "next_evidence_step": "y", "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": "s"}
        model = self.use(Model("hang", '{"verdict":"ACCEPT","feedback":"Supported.","unsupported_claims":[],"unaddressed_contradictions":[],"alternatives_tested":"yes"}'))
        session = investigator.Session(6)
        review = investigator.review(conclusion, {}, {}, ["MILESTONE_OVERDUE"], session=session, repair=False)
        self.assertEqual((review["verdict"], review["degraded"], review["mode"]), ("UNAVAILABLE", True, "model_unavailable"))   # the ACCEPT was never asked for
        self.assertEqual(review["validation_error"], "model call failed (ProviderCapacityTimeout)")
        self.assertEqual((model.calls, model.peak, session.budget.used), (1, 1, 2))


if __name__ == "__main__":
    unittest.main()
