"""The per-call model timeout on the live investigator and reviewer path.

The HTTP client's timeout (LLM_TIMEOUT_SECONDS, 120 s) bounds each wait for bytes, not the call: a provider that keeps
the connection alive held one call for 210 s. llm.pipeline._llm.invoke(messages, deadline=...) is a wall-clock limit;
operations.investigator.model_turn and _review_call use it with SUHAIL_MODEL_CALL_TIMEOUT_SECONDS (default 60 s). A
call that exceeds it raises TimeoutError and is a provider failure exactly as before: one retry, then the role fails
closed. No provider, no database: the model is a fake that hangs.
"""
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from llm.pipeline import _llm
from operations import investigator
from tests import test_investigator as ti

DEADLINE = 0.2        # seconds, for the tests
CONCLUSION = ('{"action":"conclude","hypotheses":[{"cause":"INSUFFICIENT_EVIDENCE","status":"uncertain","supporting_evidence_ids":[],'
              '"contradicting_evidence_ids":[],"assessment":"Nothing decides it."}],"primary_cause":"INSUFFICIENT_EVIDENCE","confidence":"low",'
              '"missing_evidence":["the hub scan log"],"next_evidence_step":"Ask the hub for its scan log.",'
              '"recommended_action":"REQUEST_ADDITIONAL_EVIDENCE","requires_physical_check":false,"summary":"Not enough to name a cause."}')


class Model:
    """A chat model whose calls behave as scripted: "hang" blocks until released (far longer than the deadline),
    an exception is raised, anything else is the reply's text. It records the timeout each call was given."""

    def __init__(self, *script):
        self.script, self.calls, self.timeouts = list(script), 0, []
        self.release = threading.Event()

    def invoke(self, messages, **kwargs):
        self.calls += 1
        self.timeouts.append(kwargs.get("timeout"))
        step = self.script.pop(0) if self.script else "hang"
        if step == "hang":
            self.release.wait(30)
            return SimpleNamespace(content="{}")
        if isinstance(step, Exception):
            raise step
        return SimpleNamespace(content=step)


class Patched(unittest.TestCase):
    def use(self, model, deadline=DEADLINE):
        for patcher in (mock.patch.object(_llm, "model", return_value=model), mock.patch.object(_llm, "call_timeout", return_value=deadline)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(model.release.set)          # let the abandoned calls end
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
        self.assertEqual((model.calls, model.timeouts), (1, [DEADLINE]))     # the HTTP client is given the same limit

    def test_a_call_that_returns_in_time_is_returned_and_an_error_is_raised_as_itself(self):
        model = self.use(Model("answer", ConnectionError("refused")))
        self.assertEqual(_llm.invoke(["m"], deadline=DEADLINE).content, "answer")
        with self.assertRaises(ConnectionError):
            _llm.invoke(["m"], deadline=DEADLINE)
        self.assertEqual(model.calls, 2)

    def test_without_a_deadline_the_call_is_the_plain_one(self):
        plain = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="plain"))      # takes no timeout argument
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

    def test_model_turn_and_the_review_call_use_the_deadline(self):
        model = self.use(Model('{"action":"call","tool":"shipment_overview","args":{}}', "hang", '{"verdict":"ACCEPT"}', "hang"))
        self.assertEqual(investigator.model_turn([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])["action"], "call")
        with self.assertRaises(TimeoutError):
            investigator.model_turn([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
        self.assertEqual(investigator._review_call("s", "u", {"verdict": ""}), {"verdict": "ACCEPT"})
        with self.assertRaises(TimeoutError):
            investigator._review_call("s", "u", {"verdict": ""})
        self.assertEqual(model.timeouts, [DEADLINE] * 4)

    def test_a_stalled_investigator_call_is_a_provider_failure_retried_once_and_then_the_next_reply_is_used(self):
        model = self.use(Model("hang", CONCLUSION))
        started = time.monotonic()
        result = investigator.investigate(self.tools(), session=investigator.Session(6))
        self.assertLess(time.monotonic() - started, DEADLINE + 5)
        self.assertFalse(result["degraded"])
        self.assertEqual(result["primary_cause"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(model.calls, 2)                                      # the stalled call and its one retry
        self.assertEqual(result["validation_errors"], [{"turn": 1, "error": "model call failed (ModelCallTimeout)"}])
        self.assertEqual(result["model_calls"]["model_calls_used"], 2)        # a stalled call is counted, as a failed one is

    def test_two_stalled_calls_in_a_row_fail_closed_as_model_unavailable_exactly_as_two_provider_errors_do(self):
        def run(*script):
            model = Model(*script)
            with mock.patch.object(_llm, "model", return_value=model), mock.patch.object(_llm, "call_timeout", return_value=DEADLINE):
                session = investigator.Session(6)
                try:
                    return model, session, investigator.investigate(self.tools(), session=session)
                finally:
                    model.release.set()
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
        model = self.use(Model("hang", '{"verdict":"ACCEPT","feedback":"Supported.","unsupported_claims":[],"unaddressed_contradictions":[],"alternatives_tested":"yes"}'))
        review = investigator.review(conclusion, {}, {}, ["MILESTONE_OVERDUE"], session=investigator.Session(6), repair=False)
        self.assertEqual((review["verdict"], review["degraded"], model.calls), ("ACCEPT", False, 2))
        model = Model("hang", "hang", '{"verdict":"ACCEPT","feedback":"late"}')
        with mock.patch.object(_llm, "model", return_value=model):
            session = investigator.Session(6)
            review = investigator.review(conclusion, {}, {}, ["MILESTONE_OVERDUE"], session=session, repair=False)
        model.release.set()
        self.assertEqual((review["verdict"], review["degraded"], review["mode"]), ("UNAVAILABLE", True, "model_unavailable"))   # fail closed, never ACCEPT
        self.assertEqual(review["validation_error"], "model call failed (ModelCallTimeout)")
        self.assertEqual((model.calls, session.budget.used), (2, 2))


class NoToolsArmTests(Patched):
    def test_the_no_tools_baseline_calls_the_model_under_the_same_deadline(self):
        from stage3_eval.arms import CaseRef, NoToolsArm
        model = self.use(Model("hang", "hang"))
        result = NoToolsArm(c_cap=16).run(CaseRef(key="E1:S1", world="E1", shipment_id="S1", as_of="2026-09-14T09:00:00+00:00",
                                                  symptoms=("MILESTONE_OVERDUE",)))
        self.assertEqual((result.degraded, result.failure_mode, result.provider_failures, result.calls_used), (True, "model_unavailable", 2, 2))
        self.assertEqual(result.validation_error, "model call failed (ModelCallTimeout)")
        self.assertEqual(model.timeouts, [DEADLINE, DEADLINE])


if __name__ == "__main__":
    unittest.main()
