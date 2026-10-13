"""V3: the limit on provider calls in flight (operations.provider_gate, SUHAIL_PROVIDER_MAX_INFLIGHT).

Every call made through llm.pipeline._llm.invoke holds a slot from before the provider is called until the underlying
call has really ended. What is shown here:

  - the calls inside the provider never exceed the limit, with or without a deadline, whoever makes them (an
    investigator turn, a review, a translation, narration, Canopus);
  - a caller that gives up at its deadline does not free its slot, and its retry cannot start beside the abandoned
    call: it waits, and fails as a provider failure when no slot comes free;
  - waiting is bounded in time and in number, creates no thread, ends when the caller's claim is cancelled, and leaves
    no permit behind;
  - a call keeps its caller's context and its own inputs, and the shared model is built once;
  - the log names each call (request, role, case, run, worker, times) and never its prompt or reply.

The provider is a double (MockProvider); nothing here reaches a network. `run_mock_overlap` is the small instrumented
harness: two investigations' worth of calls against the double, measured by the gate's own records. Running this file
with the argument `harness` prints its measurement at both limits. It measures this process's gate only: it says nothing
about a provider account's limits or about what a provider does with two open requests.
"""
import contextvars
import json
import logging
import os
import sys
import threading
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from llm import translate
from llm.pipeline import _llm
from operations import canopus, investigator, narration, provider_gate
from operations.provider_gate import CapacityUnavailable, ProviderGate
from tests import test_investigator as ti
from tests.test_model_call_timeout import CONCLUSION

DEADLINE = 0.2      # seconds, for the tests
probe = contextvars.ContextVar("test_probe", default=None)


class MockProvider:
    """A chat model double. Each call follows the next step of the script: "hang" blocks until released, a number
    sleeps that long, an exception is raised, a threading.Barrier is waited on (so two calls prove they overlap),
    anything else (or nothing) answers at once. It counts how many calls are inside it at the same moment."""

    def __init__(self, *script, default=None):
        self.script, self.default, self.lock = list(script), default, threading.Lock()
        self.calls, self.inside, self.peak = [], 0, 0
        self.release = threading.Event()

    def invoke(self, messages, **kwargs):
        with self.lock:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
            step = self.script.pop(0) if self.script else self.default
            self.calls.append({"messages": messages, "timeout": kwargs.get("timeout"), "thread": threading.current_thread().name,
                               "probe": probe.get(), "scope": provider_gate.current()[0]})
        try:
            if step == "hang":
                self.release.wait(30)
            elif isinstance(step, threading.Barrier):
                step.wait(10)
            elif isinstance(step, (int, float)) and not isinstance(step, bool):
                time.sleep(step)
            elif isinstance(step, Exception):
                raise step
            elif isinstance(step, str):
                return SimpleNamespace(content=step)
            return SimpleNamespace(content="echo:" + str(messages[-1]))
        finally:
            with self.lock:
                self.inside -= 1


class Gated(unittest.TestCase):
    """Each test gets its own gate and its own provider double in place of the shared model."""

    def use(self, provider, limit=1, deadline=DEADLINE, **gate):
        self.gate = ProviderGate(limit, **gate)
        previous = provider_gate.use(self.gate)
        self.addCleanup(provider_gate.use, previous)
        for patcher in (mock.patch.object(_llm, "model", return_value=provider), mock.patch.object(_llm, "call_timeout", return_value=deadline)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.drained, provider)
        self.provider = provider
        return provider

    def drained(self, provider=None, seconds=5):
        """Let every call still in flight end, and wait until the gate is empty again."""
        (provider or self.provider).release.set()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and self.gate.snapshot()["inflight"]:
            time.sleep(0.005)
        return self.gate.snapshot()

    def background(self, call):
        box = {}

        def work():
            try:
                box["result"] = call()
            except BaseException as error:
                box["error"] = error
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        box["thread"] = thread
        return box

    def until(self, condition, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not condition():
            time.sleep(0.005)
        self.assertTrue(condition(), "the expected state was never reached")


class SettingTests(unittest.TestCase):
    def test_the_limit_is_one_by_default_and_only_one_or_two_are_allowed(self):
        self.assertEqual((provider_gate.MAX_INFLIGHT_ENV, provider_gate.DEFAULT_LIMIT), ("SUHAIL_PROVIDER_MAX_INFLIGHT", 1))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(provider_gate.MAX_INFLIGHT_ENV, None)
            self.assertEqual(ProviderGate().limit, 1)
            for text, expected in (("1", 1), ("2", 2), ("3", 1), ("0", 1), ("-1", 1), ("many", 1), ("", 1), ("1.5", 1), ("inf", 1)):
                os.environ[provider_gate.MAX_INFLIGHT_ENV] = text
                self.assertEqual((provider_gate.max_inflight(), ProviderGate().limit), (expected, expected), text)
        self.assertEqual((ProviderGate(2).limit, ProviderGate(9).limit), (2, 1))


class LimitTests(Gated):
    def test_calls_in_flight_never_exceed_the_limit_and_at_two_they_do_overlap(self):
        for limit in (1, 2):
            with self.subTest(limit=limit):
                together = threading.Barrier(2)
                provider = self.use(MockProvider(*([together, together] if limit == 2 else []), default=0.02), limit=limit, deadline=10)
                boxes = [self.background(lambda i=i: _llm.invoke([f"m{i}"], deadline=10)) for i in range(6)]
                for box in boxes:
                    box["thread"].join(30)
                self.assertEqual([b.get("error") for b in boxes], [None] * 6)
                self.assertEqual(len(provider.calls), 6)
                self.assertEqual(provider.peak, limit)          # reached, and never passed: at 2 the barrier needed both inside
                snapshot = self.drained()
                self.assertEqual((snapshot["peak_inflight"], snapshot["granted"], snapshot["released"], snapshot["refused"], snapshot["inflight"]),
                                 (limit, 6, 6, 0, 0))

    def test_a_caller_timeout_keeps_the_slot_until_the_call_ends_and_a_retry_cannot_start_beside_it(self):
        provider = self.use(MockProvider("hang", "second call"))
        started = time.monotonic()
        with self.assertRaises(_llm.ModelCallTimeout) as first:
            _llm.invoke(["m"], deadline=DEADLINE)
        self.assertNotIsInstance(first.exception, _llm.ProviderCapacityTimeout)
        self.assertEqual(self.gate.snapshot()["inflight"], 1)                  # the abandoned call still holds the only slot
        with self.assertRaises(_llm.ProviderCapacityTimeout) as retry:          # the retry: the provider is not called again
            _llm.invoke(["m"], deadline=DEADLINE)
        self.assertIsInstance(retry.exception, TimeoutError)
        self.assertIsInstance(retry.exception, _llm.ModelCallTimeout)           # the failure every caller already handles
        self.assertLess(time.monotonic() - started, 2 * DEADLINE + 3)           # its wait was bounded by its own deadline
        self.assertEqual((len(provider.calls), provider.peak), (1, 1))
        snapshot = self.gate.snapshot()
        self.assertEqual((snapshot["inflight"], snapshot["granted"], snapshot["released"], snapshot["refused"]), (1, 1, 0, 1))
        snapshot = self.drained()                                               # the provider call ends at last
        self.assertEqual((snapshot["inflight"], snapshot["released"]), (0, 1))
        [call] = snapshot["calls"]
        self.assertEqual((call["abandoned"], call["outcome"]), (True, "ok"))    # it answered; the answer went nowhere
        self.assertEqual(_llm.invoke(["m"], deadline=DEADLINE).content, "second call")   # now a call gets through again
        self.assertEqual(provider.peak, 1)

    def test_at_two_a_retry_runs_beside_one_abandoned_call_and_a_third_call_waits(self):
        provider = self.use(MockProvider("hang", "hang", "third"), limit=2)
        for _ in range(2):
            with self.assertRaises(_llm.ModelCallTimeout) as raised:
                _llm.invoke(["m"], deadline=DEADLINE)
            self.assertNotIsInstance(raised.exception, _llm.ProviderCapacityTimeout)
        self.assertEqual((len(provider.calls), self.gate.snapshot()["inflight"]), (2, 2))
        with self.assertRaises(_llm.ProviderCapacityTimeout):
            _llm.invoke(["m"], deadline=DEADLINE)
        self.assertEqual((len(provider.calls), provider.peak), (2, 2))
        self.drained()
        self.assertEqual(_llm.invoke(["m"], deadline=DEADLINE).content, "third")

    def test_calls_without_a_deadline_are_limited_too(self):
        provider = self.use(MockProvider("hang", "second"))
        held = self.background(lambda: _llm.invoke(["plain"]))                 # no deadline: runs on the caller's own thread
        self.until(lambda: self.gate.snapshot()["inflight"] == 1)
        with self.assertRaises(_llm.ProviderCapacityTimeout):
            _llm.invoke(["other"])                                              # waits the default call timeout at most
        with self.assertRaises(_llm.ProviderCapacityTimeout):
            _llm.ask_json("s", "u", {"a": ""})
        self.assertEqual(len(provider.calls), 1)
        provider.release.set()
        held["thread"].join(5)
        self.assertEqual(held["result"].content, "echo:plain")
        self.assertEqual(self.drained()["inflight"], 0)
        self.assertEqual(_llm.invoke(["other"]).content, "second")
        self.assertEqual(provider.peak, 1)

    def test_a_call_that_raises_gives_its_slot_back_and_a_permit_is_released_exactly_once(self):
        provider = self.use(MockProvider(ConnectionError("refused"), ValueError("bad"), "fine"))
        with self.assertRaises(ConnectionError):
            _llm.invoke(["m"], deadline=DEADLINE)
        with self.assertRaises(ValueError):
            _llm.invoke(["m"])
        self.assertEqual(_llm.invoke(["m"], deadline=DEADLINE).content, "fine")
        snapshot = self.drained()
        self.assertEqual((snapshot["inflight"], snapshot["granted"], snapshot["released"]), (0, 3, 3))
        self.assertEqual([c["outcome"] for c in snapshot["calls"]], ["ConnectionError", "ValueError", "ok"])
        permit = self.gate.acquire(1)
        self.assertEqual((permit.release(), permit.release(), permit.release("again")), (True, False, False))
        self.assertEqual((self.gate.snapshot()["inflight"], self.gate.snapshot()["released"]), (0, 4))


class WaitingTests(Gated):
    def test_cancelling_a_claim_ends_its_wait_at_once_and_leaks_no_permit(self):
        provider = self.use(MockProvider("hang", "after"))
        held = self.background(lambda: _llm.invoke(["holder"], deadline=30))
        self.until(lambda: self.gate.snapshot()["inflight"] == 1)
        cancelled = threading.Event()

        def waiting_call():
            with provider_gate.scope(cancel=cancelled, case_id="CASE-B", run_id="RUN-B", worker_id="investigation-2"):
                return _llm.invoke(["waiter"], deadline=30)
        waiter = self.background(waiting_call)
        self.until(lambda: self.gate.snapshot()["waiting"] == 1)
        started = time.monotonic()
        cancelled.set()
        waiter["thread"].join(5)
        self.assertLess(time.monotonic() - started, 2)                          # not the 30 s it could have waited
        self.assertIsInstance(waiter["error"], _llm.ProviderCapacityTimeout)
        self.assertIn("cancelled", str(waiter["error"]))
        snapshot = self.gate.snapshot()
        self.assertEqual((snapshot["waiting"], snapshot["inflight"], snapshot["granted"], snapshot["refused"]), (0, 1, 1, 1))
        # A claim that is already gone starts no new call, even with a slot free.
        self.drained()
        with provider_gate.scope(cancel=cancelled, run_id="RUN-B"), self.assertRaises(_llm.ProviderCapacityTimeout):
            _llm.invoke(["never sent"], deadline=DEADLINE)
        self.assertEqual([c["messages"] for c in provider.calls], [["holder"]])
        snapshot = self.gate.snapshot()
        self.assertEqual((snapshot["inflight"], snapshot["granted"], snapshot["released"]), (0, 1, 1))
        self.assertEqual(_llm.invoke(["m"], deadline=DEADLINE).content, "after")         # the gate still works

    def test_waiting_is_bounded_in_number_and_creates_no_threads(self):
        provider = self.use(MockProvider("hang", default="done"), max_waiters=2)
        held = self.background(lambda: _llm.invoke(["holder"], deadline=30))
        self.until(lambda: self.gate.snapshot()["inflight"] == 1)
        waiters = [self.background(lambda i=i: _llm.invoke([f"w{i}"], deadline=30)) for i in range(2)]
        self.until(lambda: self.gate.snapshot()["waiting"] == 2)
        self.assertEqual(sum(t.name == "model-call" for t in threading.enumerate()), 1)     # only the call in flight has a thread
        started = time.monotonic()
        with self.assertRaises(_llm.ProviderCapacityTimeout) as refused:        # a third caller is not queued behind them
            _llm.invoke(["w3"], deadline=30)
        self.assertLess(time.monotonic() - started, 1)
        self.assertIn("queue_full", str(refused.exception))
        self.assertEqual(len(provider.calls), 1)
        provider.release.set()
        for box in (held, *waiters):
            box["thread"].join(10)
        self.assertEqual(sorted(b["result"].content for b in waiters), ["done", "done"])
        snapshot = self.drained()
        self.assertEqual((provider.peak, snapshot["peak_inflight"], snapshot["waiting"], snapshot["inflight"]), (1, 1, 0, 0))
        self.assertEqual((snapshot["granted"], snapshot["released"], snapshot["refused"]), (3, 3, 1))

    def test_waiting_callers_are_served_in_the_order_they_asked(self):
        provider = self.use(MockProvider("hang", default=0.01), deadline=30)
        held = self.background(lambda: _llm.invoke(["holder"], deadline=30))
        self.until(lambda: self.gate.snapshot()["inflight"] == 1)
        waiters = []
        for index in range(4):
            waiters.append(self.background(lambda index=index: _llm.invoke([f"w{index}"], deadline=30)))
            self.until(lambda: self.gate.snapshot()["waiting"] == index + 1)        # each is in line before the next one asks
        provider.release.set()
        for box in (held, *waiters):
            box["thread"].join(15)
        self.assertEqual([b.get("error") for b in waiters], [None] * 4)
        self.assertEqual([c["messages"][0] for c in provider.calls], ["holder", "w0", "w1", "w2", "w3"])     # nobody jumped the line
        self.assertEqual(provider.peak, 1)
        # A caller that arrives when a slot is free but others are still in line waits its turn too.
        gate = ProviderGate(1)
        first = gate.acquire(1)
        order = []

        def queued(name):
            permit = gate.acquire(5)
            order.append(name)
            time.sleep(0.02)
            permit.release()
        earlier = threading.Thread(target=queued, args=("earlier",))
        earlier.start()
        self.until(lambda: gate.waiting == 1)
        later = threading.Thread(target=queued, args=("later",))
        later.start()
        self.until(lambda: gate.waiting == 2)
        first.release()
        earlier.join(5)
        later.join(5)
        self.assertEqual(order, ["earlier", "later"])

    def test_a_wait_that_runs_out_is_a_timeout_and_the_gate_itself_refuses_by_reason(self):
        gate = ProviderGate(1)
        first = gate.acquire(1)
        started = time.monotonic()
        with self.assertRaises(CapacityUnavailable) as timed_out:
            gate.acquire(0.1)
        self.assertEqual(timed_out.exception.reason, "timeout")
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsInstance(timed_out.exception, TimeoutError)
        first.release()
        self.assertTrue(gate.acquire(0).release())                              # free: no wait is needed at all


class IsolationTests(Gated):
    def test_a_call_keeps_its_callers_context_and_two_calls_keep_their_own_inputs(self):
        together = threading.Barrier(2)
        provider = self.use(MockProvider(together, together), limit=2, deadline=10)

        def caller(name):
            probe.set(name)
            messages = [f"system for {name}", f"question from {name}"]
            with provider_gate.scope(case_id="CASE-" + name, run_id="RUN-" + name, worker_id=name):
                response = _llm.invoke(messages, deadline=10)
            return messages, response
        boxes = {name: self.background(lambda name=name: caller(name)) for name in ("investigation-1", "investigation-2")}
        for box in boxes.values():
            box["thread"].join(15)
        for name, box in boxes.items():
            messages, response = box["result"]
            self.assertEqual(messages, [f"system for {name}", f"question from {name}"])        # not touched
            self.assertEqual(response.content, f"echo:question from {name}")                   # its own answer
            call = next(c for c in provider.calls if c["messages"] is messages)                # the very list it passed
            self.assertEqual((call["probe"], call["thread"]), (name, "model-call"))            # its context, on the call's thread
            self.assertEqual(call["scope"], {"case_id": "CASE-" + name, "run_id": "RUN-" + name, "worker_id": name})
        self.assertEqual(provider.peak, 2)
        self.assertIsNone(probe.get())
        self.assertEqual(provider_gate.current(), ({}, None))                   # a scope ends with its block

    def test_the_shared_model_is_built_once_when_several_threads_ask_together(self):
        _llm.model.cache_clear()
        self.addCleanup(_llm.model.cache_clear)
        built, start = [], threading.Barrier(8)

        def slow_constructor(**kwargs):
            time.sleep(0.05)
            built.append(kwargs)
            return SimpleNamespace(name=f"client-{len(built)}")

        def ask():
            start.wait(10)
            return _llm.model()
        with mock.patch.object(_llm, "ChatLiteLLM", side_effect=slow_constructor):
            boxes = [self.background(ask) for _ in range(8)]
            for box in boxes:
                box["thread"].join(10)
            self.assertEqual(len(built), 1)
            self.assertEqual(len({id(b["result"]) for b in boxes}), 1)
            self.assertIs(_llm.model(), boxes[0]["result"])
        self.assertEqual((built[0]["temperature"], built[0]["max_retries"]), (0, 0))        # the same construction as before


class EveryCallerTests(Gated):
    def test_translation_narration_and_canopus_take_a_slot_like_every_other_call(self):
        provider = self.use(MockProvider("hang", "شحنة SHP-0227 متأخرة", '{"title_en":"T","text_en":"Narrated.","text_ar":null}', '{"answer":"x"}'))
        translate.to_arabic.cache_clear()
        self.addCleanup(translate.to_arabic.cache_clear)
        patches = [mock.patch.object(translate, "model", return_value=provider), mock.patch.object(narration, "CALL_DEADLINE_SECONDS", DEADLINE),
                   mock.patch.object(canopus, "CALL_DEADLINE_SECONDS", DEADLINE)]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        held = self.background(lambda: _llm.invoke(["an investigator turn"], deadline=30))
        self.until(lambda: self.gate.snapshot()["inflight"] == 1)
        # While the only slot is taken, none of them reaches the provider.
        self.assertEqual(translate.to_arabic("Shipment SHP-0227 is delayed"), "Shipment SHP-0227 is delayed")     # kept, untranslated
        for ask in (narration.provider_ask, canopus.provider_ask):
            with self.assertRaises(_llm.ProviderCapacityTimeout):
                ask("system", "user")
        self.assertEqual((len(provider.calls), provider.peak, self.gate.snapshot()["refused"]), (1, 1, 3))
        self.drained()
        translate.to_arabic.cache_clear()
        self.assertEqual(translate.to_arabic("Shipment SHP-0227 is delayed"), "شحنة SHP-0227 متأخرة")
        self.assertEqual(narration.provider_ask("system", "user")["text_en"], "Narrated.")
        canopus.provider_ask("system", "user")
        snapshot = self.drained()
        self.assertEqual([c["role"] for c in snapshot["calls"]], ["invoke", "translation", "ask_json", "ask_json"])
        self.assertEqual((provider.peak, snapshot["peak_inflight"], snapshot["granted"], snapshot["released"]), (1, 1, 4, 4))
        self.assertEqual([c["timeout"] for c in provider.calls], [30, None, DEADLINE, DEADLINE])      # translation still has no deadline

    def test_the_log_names_each_call_and_never_its_prompt_or_reply(self):
        self.use(MockProvider("PRIVATE REPLY TEXT", "hang"))
        with self.assertLogs(provider_gate.log, level=logging.INFO) as captured:
            with provider_gate.scope(case_id="DEMO-OPS-CASE-A", run_id="DEMO-OPS-RUN-A", worker_id="investigation-1"):
                _llm.invoke(["PRIVATE PROMPT TEXT"], deadline=DEADLINE)
                with self.assertRaises(_llm.ModelCallTimeout):
                    _llm.ask_json("PRIVATE SYSTEM", "PRIVATE USER", {"a": ""}, deadline=DEADLINE)
                with self.assertRaises(_llm.ProviderCapacityTimeout):
                    _llm.invoke(["PRIVATE RETRY"], deadline=DEADLINE)
        snapshot = self.drained()
        text = "\n".join(captured.output) + json.dumps(snapshot)
        self.assertNotIn("PRIVATE", text)
        first, second = snapshot["calls"]
        self.assertEqual((first["role"], second["role"]), ("investigator", "reviewer"))     # by entry point, inside a run's scope
        for call in snapshot["calls"]:
            self.assertEqual((call["case_id"], call["run_id"], call["worker_id"]), ("DEMO-OPS-CASE-A", "DEMO-OPS-RUN-A", "investigation-1"))
            self.assertRegex(call["request_id"], r"^call-\d{6}$")
            self.assertLessEqual(datetime.fromisoformat(call["started_at"]), datetime.fromisoformat(call["finished_at"]))
        self.assertEqual(second["abandoned"], True)
        starts = [line for line in captured.output if "provider call start" in line]
        self.assertEqual(len(starts), 2)
        for line in starts:
            for part in ("request=call-", "case=DEMO-OPS-CASE-A", "run=DEMO-OPS-RUN-A", "worker=investigation-1", "role=", "at="):
                self.assertIn(part, line)
        self.assertTrue(any("provider call refused reason=timeout" in line and "run=DEMO-OPS-RUN-A" in line for line in captured.output))


class InvestigatorTests(Gated, ti.Base):
    """The investigator's own retry rule, unchanged, on top of the limit: one call and one retry per turn."""

    def tools(self):
        sid = sorted(sid for sid, row in self.truth.items() if row["split"] == "development")[0]
        return ti.Base.tools(self, sid, self.world.config.as_of)

    def test_at_one_a_stalled_turn_s_retry_finds_no_slot_and_the_role_fails_closed(self):
        provider = self.use(MockProvider("hang", CONCLUSION))
        session = investigator.Session(6)
        result = investigator.investigate(self.tools(), session=session)
        self.assertEqual((result["degraded"], result["mode"], result["primary_cause"]), (True, "model_unavailable", None))
        self.assertEqual(result["validation_error"], "model call failed (ProviderCapacityTimeout)")
        self.assertEqual((len(provider.calls), provider.peak), (1, 1))          # the retry never reached the provider
        self.assertEqual(session.budget.used, investigator.ATTEMPTS_PER_TURN)   # both attempts are counted, as before
        self.assertEqual([t["outcome"] for t in session.turns], ["provider_failure", "provider_failure"])

    def test_at_two_the_retry_goes_out_and_its_reply_is_used(self):
        provider = self.use(MockProvider("hang", CONCLUSION), limit=2)
        session = investigator.Session(6)
        result = investigator.investigate(self.tools(), session=session)
        self.assertFalse(result["degraded"])
        self.assertEqual(result["primary_cause"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual((len(provider.calls), provider.peak, session.budget.used), (2, 2, 2))
        self.assertEqual(result["validation_errors"], [{"turn": 1, "error": "model call failed (ModelCallTimeout)"}])


def run_mock_overlap(limit, latency=0.03, turns=2):
    """The harness: two investigations at once, each making `turns` investigator calls and one review call through the
    real invoke and ask_json, against a provider double that takes `latency` seconds. Returns the gate's measurement:
    its counters, every call's record, and whether calls of different runs were open at the same time."""
    # At two, each investigation's first call waits for the other's: the overlap is then certain, not a matter of timing.
    together = threading.Barrier(2)
    gate, provider = ProviderGate(limit), MockProvider(*([together, together] if limit >= 2 else []), default=latency)
    previous = provider_gate.use(gate)
    try:
        with mock.patch.object(_llm, "model", return_value=provider):
            def investigation(name):
                with provider_gate.scope(case_id="DEMO-OPS-CASE-" + name, run_id="DEMO-OPS-RUN-" + name, worker_id="investigation-" + name):
                    for turn in range(turns):
                        _llm.invoke([f"turn {turn}"], deadline=10)
                    _llm.ask_json("review", "conclusion", {"verdict": ""}, deadline=10)
            threads = [threading.Thread(target=investigation, args=(name,)) for name in ("1", "2")]
            started = time.monotonic()
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
            seconds = time.monotonic() - started
    finally:
        provider_gate.use(previous)
    snapshot = gate.snapshot()
    spans = [(c["run_id"], datetime.fromisoformat(c["started_at"]), datetime.fromisoformat(c["finished_at"])) for c in snapshot["calls"]]
    overlapping = sum(1 for i, a in enumerate(spans) for b in spans[i + 1:] if a[0] != b[0] and a[1] < b[2] and b[1] < a[2])
    return {**snapshot, "provider_peak": provider.peak, "provider_calls": len(provider.calls), "wall_seconds": round(seconds, 3),
            "overlapping_pairs_across_runs": overlapping, "mock_only": True}


class HarnessTests(unittest.TestCase):
    def test_two_investigations_overlap_at_two_and_run_one_call_at_a_time_at_one(self):
        one, two = run_mock_overlap(1), run_mock_overlap(2)
        for measured in (one, two):
            self.assertEqual((measured["provider_calls"], measured["granted"], measured["released"], measured["refused"], measured["inflight"]),
                             (6, 6, 6, 0, 0))
            self.assertEqual({c["run_id"] for c in measured["calls"]}, {"DEMO-OPS-RUN-1", "DEMO-OPS-RUN-2"})
            self.assertEqual(sorted(c["role"] for c in measured["calls"]), ["investigator"] * 4 + ["reviewer"] * 2)
            self.assertTrue(all(c["case_id"] and c["worker_id"] and c["request_id"] for c in measured["calls"]))
            self.assertTrue(measured["mock_only"])
        self.assertEqual((one["provider_peak"], one["peak_inflight"], one["overlapping_pairs_across_runs"]), (1, 1, 0))
        self.assertEqual((two["provider_peak"], two["peak_inflight"]), (2, 2))
        self.assertGreater(two["overlapping_pairs_across_runs"], 0)


if __name__ == "__main__":
    if sys.argv[1:] == ["harness"]:
        print(json.dumps({f"limit_{limit}": run_mock_overlap(limit) for limit in (1, 2)}, indent=2))
    else:
        unittest.main()
