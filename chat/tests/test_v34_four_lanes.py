"""V3.4: up to four investigation workers and four provider lanes (one per DISTINCT provider key).

What is shown here, offline (no provider, no database):

  - lanes come from distinct keys only (a duplicate never adds capacity), the shared limit never exceeds them, and a lane
    keeps its key wherever it sits in the pool;
  - through the real LiteLLM/OpenAI transport against a loopback server: four calls in flight carry four different keys
    and no key ever carries two; four workers on two keys stay at two;
  - a lane that answers a rate limit cools down and comes back, a refused key is disabled and visible, the failed call is
    never re-sent on another lane, and the remaining lanes carry on mid-run;
  - per-lane call/token/cost caps hold, every reservation carries its lane before dispatch, and a ledger written without
    lane caps stays valid;
  - three and four workers on the real store (in-memory ledger): distinct cases at once, one grant per case, capacity
    held, and the worker pool stops Auto from inside the server when its budget or run limit says so.

Mock or loopback only: overlapping requests here are not live model inference.
"""
import json
import os
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import litellm
from langchain_core.messages import HumanMessage
from llm.pipeline import _llm
from operations import claims, provider_gate
from operations.inference_safety import InferenceLedger, Policy, SafetyRefused
from tests.test_v3_concurrency import Base, Hooked

KEYS = ("offline-lane-a", "offline-lane-b", "offline-lane-c", "offline-lane-d")
WORKERS4 = tuple(f"investigation-{n}" for n in range(1, 5))


def keys(*values):
    """Patch config's four provider keys (None for unset)."""
    values = (list(values) + [None] * 4)[:4]
    return [mock.patch.object(_llm.config, name, value) for name, value in zip(provider_gate.KEY_SETTINGS, values)]


class Patches:
    def patch(self, *patchers):
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)


class LanePlanTests(Patches, unittest.TestCase):
    def lanes(self, *values, env=None):
        with mock.patch.dict(os.environ, env or {}):
            patchers = keys(*values)
            for p in patchers:
                p.start()
            try:
                return provider_gate.provider_lanes()
            finally:
                for p in patchers:
                    p.stop()

    def test_one_lane_per_distinct_key_named_after_its_first_setting(self):
        a, b, c, d = KEYS
        self.assertEqual(self.lanes(a, b, c, d), ["A", "B", "C", "D"])
        self.assertEqual(self.lanes(a, b, a, d), ["A", "B", "D"])          # key 3 repeats key 1: not a lane
        self.assertEqual(self.lanes(a, a, a, a), ["A"])
        self.assertEqual(self.lanes(a, None, c, None), ["A", "C"])
        self.assertEqual(self.lanes(None, None, None, None), ["A"])
        self.assertEqual(self.lanes(a, b, c, d, env={"SUHAIL_PROVIDER_LANE_C": "off"}), ["A", "B", "D"])
        # A lane switched off keeps its key: the same key under a later setting does not come back as another lane.
        self.assertEqual(self.lanes(a, b, b, d, env={"SUHAIL_PROVIDER_LANE_B": "off"}), ["A", "D"])
        self.assertEqual(self.lanes(a, b, c, d, env={"SUHAIL_PROVIDER_LANE_A": "off"}), ["A", "B", "C", "D"])   # A stays

    def shared(self, requested, *values, env=None):
        with mock.patch.dict(os.environ, {provider_gate.MAX_INFLIGHT_ENV: requested, **(env or {})}):
            patchers = keys(*values)
            for p in patchers:
                p.start()
            previous = provider_gate.use(None)
            try:
                gate = provider_gate.shared()
                return gate.limit, gate.names
            finally:
                provider_gate.use(previous)
                for p in patchers:
                    p.stop()

    def test_the_shared_limit_never_exceeds_the_distinct_enabled_keys(self):
        a, b, c, d = KEYS
        self.assertEqual(self.shared("4", a, b, c, d), (4, ("A", "B", "C", "D")))
        self.assertEqual(self.shared("4", a, b, c, None), (3, ("A", "B", "C")))
        self.assertEqual(self.shared("4", a, b, b, a), (2, ("A", "B")))       # duplicates are never capacity
        self.assertEqual(self.shared("4", a, None, None, None), (1, ("A",)))
        self.assertEqual(self.shared("3", a, b, c, d), (3, ("A", "B", "C")))
        self.assertEqual(self.shared("2", a, b, c, d), (2, ("A", "B")))
        self.assertEqual(self.shared("1", a, b, c, d), (1, ("A",)))           # more keys never raise the limit by themselves
        self.assertEqual(self.shared("5", a, b, c, d), (1, ("A",)))           # only 1 to 4 exist
        self.assertEqual(self.shared("4", a, b, c, d, env={"SUHAIL_PROVIDER_LANE_D": "off"}), (3, ("A", "B", "C")))
        self.assertEqual(self.shared("4", a, a, c, d), (3, ("A", "C", "D")))

    def test_a_lane_uses_its_own_key_wherever_it_sits_in_the_pool(self):
        a, b, c, d = KEYS
        self.patch(*keys(a, a, c, d))
        self.assertEqual([provider_gate.lane_key(n) for n in "ACD"], [a, c, d])
        self.assertEqual([_llm.lane_key(i) for i in range(3)], [a, c, d])    # by place among the configured lanes
        self.assertEqual(_llm.lane_key(3), a)                                # no fourth distinct key: lane A's


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class LaneHealthTests(unittest.TestCase):
    def test_a_rate_limited_lane_cools_down_is_skipped_and_comes_back(self):
        clock = Clock()
        gate = provider_gate.ProviderGate(4, clock=clock, cooldown=60)
        self.assertEqual(gate.fault(2, "RateLimitError"), "cooling")
        states = {lane["lane"]: lane for lane in gate.lanes_snapshot()}
        self.assertEqual((states["C"]["state"], states["C"]["disabled"], states["C"]["cooling_seconds_left"]),
                         ("cooling", "RateLimitError", 60.0))
        held = [gate.acquire(1) for _ in range(3)]
        self.assertEqual(sorted(p.name for p in held), ["A", "B", "D"])      # C is skipped while it cools down
        with self.assertRaises(provider_gate.CapacityUnavailable):
            gate.acquire(0)
        with self.assertRaises(provider_gate.CapacityUnavailable) as asked:
            gate.acquire(1, lane=2)
        self.assertEqual(asked.exception.reason, "lane_disabled")
        clock.now += 61
        back = gate.acquire(0)
        self.assertEqual(back.name, "C")                                     # the cooldown ran out: C takes calls again
        back.release("ok")
        self.assertEqual(gate.lanes_snapshot()[2]["rate_limits_in_a_row"], 0)  # a successful call clears the strikes
        for permit in held:
            permit.release()

    def test_cooldowns_double_and_repeated_rate_limits_disable_the_lane_until_an_operator_enables_it(self):
        clock = Clock()
        gate = provider_gate.ProviderGate(2, clock=clock, cooldown=60)
        self.assertEqual(gate.fault(1, "RateLimitError"), "cooling")
        self.assertEqual(gate.lanes_snapshot()[1]["cooling_seconds_left"], 60.0)
        clock.now += 61
        self.assertEqual(gate.fault(1, "RateLimitError"), "cooling")
        self.assertEqual(gate.lanes_snapshot()[1]["cooling_seconds_left"], 120.0)
        clock.now += 121
        self.assertEqual(gate.fault(1, "RateLimitError"), "disabled")      # three in a row without a success
        lane = gate.lanes_snapshot()[1]
        self.assertEqual((lane["state"], lane["disabled"], lane["last_fault"]["action"]), ("disabled", "RateLimitError x3", "disabled"))
        clock.now += 10_000
        self.assertEqual(gate.lanes_snapshot()[1]["state"], "disabled")     # time alone never brings a disabled lane back
        self.assertTrue(gate.enable(1))
        self.assertEqual((gate.lanes_snapshot()[1]["state"], gate.lanes_snapshot()[1]["rate_limits_in_a_row"]), ("ready", 0))
        self.assertFalse(gate.enable(1))

    def test_a_refused_key_disables_its_lane_and_the_last_lane_in_service_is_kept(self):
        gate = provider_gate.ProviderGate(3, cooldown=60)
        self.assertEqual(gate.fault(0, "AuthenticationError"), "disabled")
        self.assertEqual(gate.fault(1, "RateLimitError"), "cooling")
        self.assertEqual(gate.fault(2, "PermissionDeniedError"), "kept")    # the only lane left in service stays
        self.assertEqual(gate.fault(2, "RateLimitError"), "kept")
        self.assertEqual([lane["state"] for lane in gate.lanes_snapshot()], ["disabled", "cooling", "ready"])
        self.assertEqual(gate.fault(2, "ServiceUnavailableError"), "ignored")
        self.assertEqual(gate.acquire(1).name, "C")

    def test_a_caller_limited_to_some_lanes_waits_for_those_and_refuses_when_all_are_disabled(self):
        gate = provider_gate.ProviderGate(4)
        self.assertEqual(gate.acquire(1, lanes=[3]).name, "D")
        with self.assertRaises(provider_gate.CapacityUnavailable) as waited:
            gate.acquire(0.1, lanes=[3])
        self.assertEqual(waited.exception.reason, "timeout")                 # A, B and C are free but not allowed
        self.assertEqual(gate.acquire(1, lanes=[1, 3]).name, "B")
        gate.disable(2, "AuthenticationError")
        with self.assertRaises(provider_gate.CapacityUnavailable) as refused:
            gate.acquire(1, lanes=[2])
        self.assertEqual(refused.exception.reason, "lane_disabled")

    def test_activity_names_who_is_in_a_call_on_which_lane_and_who_waits(self):
        gate = provider_gate.ProviderGate(1)
        held = gate.acquire(1, labels={"worker_id": "investigation-1", "case_id": "DEMO-OPS-CASE-1", "role": "investigator"})
        waiter = threading.Thread(target=lambda: gate.acquire(2, labels={"worker_id": "investigation-2", "case_id": "DEMO-OPS-CASE-2"}).release())
        waiter.start()
        deadline = time.monotonic() + 2
        while not gate.waiting and time.monotonic() < deadline:
            time.sleep(0.01)
        activity = gate.activity()
        self.assertEqual([(c["worker_id"], c["lane"], c["role"]) for c in activity["in_flight"]], [("investigation-1", "A", "investigator")])
        self.assertEqual([(c["worker_id"], c["case_id"]) for c in activity["waiting"]], [("investigation-2", "DEMO-OPS-CASE-2")])
        held.release()
        waiter.join(3)
        self.assertEqual(gate.activity(), {"in_flight": [], "waiting": []})

    def test_waiters_are_served_in_order_across_four_lanes(self):
        gate = provider_gate.ProviderGate(4)
        held = [gate.acquire(1) for _ in range(4)]
        order = []

        def wait(name):
            permit = gate.acquire(5)
            order.append(name)
            time.sleep(0.05)
            permit.release()
        threads = []
        for name in ("first", "second", "third", "fourth", "fifth"):
            threads.append(threading.Thread(target=wait, args=(name,)))
            threads[-1].start()
            time.sleep(0.08)
        for permit in held:
            permit.release()
        for thread in threads:
            thread.join(5)
        self.assertEqual(order, ["first", "second", "third", "fourth", "fifth"])


class Loopback(Patches, unittest.TestCase):
    """Real HTTP through LiteLLM's OpenAI transport against a loopback server that records each request's key and how many
    requests per key were open at once. Keys are offline strings."""

    STALL = 0.5
    LIMIT = "4"
    ENV = {}

    def setUp(self):
        self.lock = threading.Lock()
        self.open_by_key, self.peak_by_key, self.seen, self.status_by_key = {}, {}, [], {}
        self.open_total = self.peak_total = 0
        self.release = threading.Event()
        self.release.set()
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                key = self.headers.get("Authorization", "").removeprefix("Bearer ")
                self.rfile.read(int(self.headers["Content-Length"]))
                with test.lock:
                    test.seen.append(key)
                    test.open_by_key[key] = test.open_by_key.get(key, 0) + 1
                    test.open_total += 1
                    test.peak_by_key[key] = max(test.peak_by_key.get(key, 0), test.open_by_key[key])
                    test.peak_total = max(test.peak_total, test.open_total)
                time.sleep(test.STALL)
                test.release.wait(10)
                with test.lock:
                    test.open_by_key[key] -= 1
                    test.open_total -= 1
                status = test.status_by_key.get(key, 200)
                if status == 200:
                    payload = {"id": "x", "object": "chat.completion", "created": 0, "model": "gpt-oss:120b",
                               "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}
                else:
                    payload = {"error": {"message": "offline failure", "type": "server_error"}}
                body = json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.release.set)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.ledger_path = os.path.join(folder.name, "ledger.json")
        self.patch(mock.patch.dict(os.environ, {"SUHAIL_INFERENCE_LEDGER": self.ledger_path, "SUHAIL_INPUT_USD_PER_MILLION": "1",
                                                "SUHAIL_OUTPUT_USD_PER_MILLION": "1", "SUHAIL_INFERENCE_MAX_CALLS": "100",
                                                "SUHAIL_INFERENCE_MAX_TOKENS": "100000000", "SUHAIL_INFERENCE_MAX_USD": "100",
                                                provider_gate.MAX_INFLIGHT_ENV: self.LIMIT, **self.ENV}),
                   mock.patch.object(_llm.config, "LLM_API_BASE", f"http://127.0.0.1:{self.server.server_port}/v1"),
                   mock.patch.object(litellm, "telemetry", False), *keys(*KEYS))
        _llm.model.cache_clear()
        self.addCleanup(_llm.model.cache_clear)
        self.addCleanup(provider_gate.use, provider_gate.use(None))         # rebuilt from the patched keys

    def call(self, **options):
        return _llm.invoke([HumanMessage("offline lane probe")], deadline=20, **options)

    def run_calls(self, count, threads, call=None):
        call = call or self.call
        errors, queue, lock = [], list(range(count)), threading.Lock()

        def worker():
            while True:
                with lock:
                    if not queue:
                        return
                    queue.pop()
                try:
                    call()
                except Exception as error:
                    errors.append(type(error).__name__)
        pool = [threading.Thread(target=worker) for _ in range(threads)]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join(60)
        return errors

    def rows(self):
        return InferenceLedger().load()["entries"]


class FourLaneTransportTests(Loopback):
    def test_four_calls_in_flight_carry_four_keys_and_no_key_carries_two(self):
        self.assertEqual((provider_gate.shared().limit, provider_gate.shared().names), (4, ("A", "B", "C", "D")))
        with self.assertLogs("suhail.provider.transport", "INFO") as logs:
            self.assertEqual(self.run_calls(12, 6), [])
        self.assertEqual(len(self.seen), 12)                                  # one HTTP request per call, nothing retried
        self.assertEqual(self.peak_total, 4)                                  # four requests really open at once
        self.assertEqual(self.peak_by_key, {key: 1 for key in KEYS})          # never two on one key
        self.assertFalse(any(key in line for key in KEYS for line in logs.output))
        rows = self.rows()
        self.assertEqual(sorted({row["lane"] for row in rows}), ["A", "B", "C", "D"])
        self.assertTrue(all(row["status"] == "usage_confirmed" for row in rows))
        snapshot = provider_gate.shared().snapshot()
        self.assertEqual((snapshot["peak_inflight"], snapshot["inflight"]), (4, 0))
        self.assertEqual(sum(lane["granted"] for lane in snapshot["lanes"]), 12)

    def test_four_callers_on_two_distinct_keys_stay_at_two(self):
        self.patch(*keys(KEYS[0], KEYS[1], KEYS[0], KEYS[1]))
        provider_gate.use(None)
        self.assertEqual(provider_gate.shared().limit, 2)
        self.assertEqual(self.run_calls(8, 4), [])
        self.assertEqual((self.peak_total, self.peak_by_key), (2, {KEYS[0]: 1, KEYS[1]: 1}))

    def test_lanes_failing_mid_run_are_taken_out_without_resending_and_the_others_carry_on(self):
        a, b, c, d = KEYS
        self.status_by_key = {c: 429, d: 401}
        errors = self.run_calls(12, 4)
        self.assertEqual(sorted(errors), ["AuthenticationError", "RateLimitError"])   # exactly the two calls those lanes got
        self.assertEqual((self.seen.count(c), self.seen.count(d)), (1, 1))            # each failed once; never sent again
        self.assertEqual(len(self.seen), 12)                                           # one request per call: no hidden retry
        lanes = {lane["lane"]: lane for lane in provider_gate.shared().lanes_snapshot()}
        self.assertEqual((lanes["C"]["state"], lanes["C"]["disabled"]), ("cooling", "RateLimitError"))
        self.assertEqual((lanes["D"]["state"], lanes["D"]["disabled"]), ("disabled", "AuthenticationError"))
        self.assertEqual((lanes["A"]["state"], lanes["B"]["state"]), ("ready", "ready"))
        rows = self.rows()
        self.assertEqual(len(rows), 12)
        failed = [row for row in rows if row["lane"] in ("C", "D")]
        self.assertEqual([row["status"] for row in failed], ["maximum_charged", "maximum_charged"])   # no usage: charged at most
        # An operator puts D back after the key was fixed; it carries calls again.
        self.status_by_key.pop(d)
        self.assertTrue(provider_gate.shared().enable(3))
        self.assertEqual(self.call(lane=3).content, "ok")
        self.assertEqual(self.seen[-1], d)

    def test_a_reservation_names_its_lane_before_the_call_is_sent(self):
        self.release.clear()                                                   # hold the request open at the "provider"
        thread = threading.Thread(target=lambda: self.call(lane=2))
        thread.start()
        deadline = time.monotonic() + 10
        while not self.seen and time.monotonic() < deadline:
            time.sleep(0.02)
        [row] = self.rows()                                                    # what a crash at this moment leaves behind
        self.assertEqual((row["status"], row["lane"], row["calls"]), ("reserved", "C", 1))
        self.release.set()
        thread.join(10)
        self.assertEqual(self.rows()[0]["status"], "usage_confirmed")


class LaneCapTests(Loopback):
    LIMIT = "2"
    ENV = {"SUHAIL_INFERENCE_LANE_MAX_CALLS": "2"}

    def setUp(self):
        super().setUp()
        self.patch(*keys(KEYS[0], KEYS[1]))
        provider_gate.use(None)

    def test_each_lane_stops_at_its_own_cap_and_the_call_after_that_is_refused_before_any_request(self):
        for _ in range(4):
            self.assertEqual(self.call().content, "ok")
        self.assertEqual(sorted(row["lane"] for row in self.rows()), ["A", "A", "B", "B"])
        with self.assertRaises(SafetyRefused):
            self.call()
        self.assertEqual(len(self.seen), 4)
        self.assertEqual(provider_gate.shared().snapshot()["inflight"], 0)
        summary = InferenceLedger().summary(lanes=("A", "B"))
        self.assertEqual(summary["lane_caps"]["calls"], 2)
        self.assertEqual({name: totals["calls"] for name, totals in summary["lanes"].items()}, {"A": 2, "B": 2})

    def test_when_one_lane_is_spent_calls_go_to_the_other(self):
        self.assertEqual(self.call(lane=0).content, "ok")
        self.assertEqual(self.call(lane=0).content, "ok")
        with self.assertRaises(SafetyRefused):
            self.call(lane=0)                                                  # A has spent its two
        self.assertEqual(self.run_calls(2, 2), [])
        self.assertEqual(self.seen, [KEYS[0], KEYS[0], KEYS[1], KEYS[1]])     # the pool sent them to B, one at a time


class LedgerPolicyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "ledger.json")

    def test_a_ledger_without_lane_caps_stays_valid_and_turning_caps_on_needs_a_new_ledger(self):
        plain = Policy(10, 100000, "100", "10", "20", 8192, 128)
        self.assertEqual(set(plain.document()), {"calls", "tokens", "usd", "input_rate", "output_rate", "max_input_bytes",
                                                 "max_output_tokens"})                       # the V3.3 frozen form, unchanged
        InferenceLedger(plain, self.path).reserve(["m"], {}, time.monotonic() + 1)
        self.assertEqual(len(InferenceLedger(plain, self.path).load()["entries"]), 1)
        capped = Policy(10, 100000, "100", "10", "20", 8192, 128, 5, 50000, "50")
        with self.assertRaises(SafetyRefused):
            InferenceLedger(capped, self.path).load()

    def test_lane_caps_come_from_the_environment_and_default_to_the_aggregate(self):
        base = {"SUHAIL_INPUT_USD_PER_MILLION": "1", "SUHAIL_OUTPUT_USD_PER_MILLION": "1", "SUHAIL_INFERENCE_MAX_CALLS": "40",
                "SUHAIL_INFERENCE_MAX_TOKENS": "900", "SUHAIL_INFERENCE_MAX_USD": "2"}
        with mock.patch.dict(os.environ, base):
            for name in ("SUHAIL_INFERENCE_LANE_MAX_CALLS", "SUHAIL_INFERENCE_LANE_MAX_TOKENS", "SUHAIL_INFERENCE_LANE_MAX_USD"):
                os.environ.pop(name, None)
            self.assertFalse(Policy.configured().lane_capped)
            os.environ["SUHAIL_INFERENCE_LANE_MAX_CALLS"] = "10"
            policy = Policy.configured()
            self.assertEqual((policy.lane_calls, policy.lane_tokens, policy.lane_usd), (10, 900, "2"))
            os.environ["SUHAIL_INFERENCE_LANE_MAX_USD"] = "-1"
            with self.assertRaises(SafetyRefused):
                Policy.configured()

    def test_unattributed_rows_count_against_every_lane(self):
        policy = Policy(10, 10**7, "100", "1", "1", 8192, 128, 2, 10**7, "100")
        ledger = InferenceLedger(policy, self.path)
        ledger.reserve(["m"], {}, time.monotonic() + 1)                       # no lane: an older row
        ledger.reserve(["m"], {}, time.monotonic() + 1, lane="A")
        self.assertEqual(ledger.affordable(["m"], ["A", "B"], time.monotonic() + 1), ["B"])
        with self.assertRaises(SafetyRefused):
            ledger.reserve(["m"], {}, time.monotonic() + 1, lane="A")

    def test_headroom_is_for_a_whole_investigation_at_its_maximum(self):
        policy = Policy(30, 10**8, "100", "1", "1", 1000, 100, 8, 10**8, "100")
        ledger = InferenceLedger(policy, self.path)
        self.assertTrue(ledger.headroom(12, lanes=("A", "B")))                # 8 + 8 lane calls cover 12
        self.assertFalse(ledger.headroom(12, lanes=("A",)))                   # one lane's 8 do not
        for _ in range(20):
            ledger.reserve(["m"], {}, time.monotonic() + 1, lane="A" if _ < 8 else ("B" if _ < 16 else "C"))
        self.assertFalse(ledger.headroom(12, lanes=("A", "B", "C", "D")))     # 10 aggregate calls left
        self.assertTrue(ledger.headroom(10, lanes=("C", "D")))
        self.assertEqual(Decimal(ledger.summary(lanes=("A",))["spent"]["usd"]) > 0, True)


class SettingsTests(unittest.TestCase):
    def test_one_to_four_workers_are_allowed_and_anything_else_is_one(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(claims.WORKERS_ENV, None)
            self.assertEqual(claims.investigation_workers(), 1)
            for text, expected in (("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 1), ("0", 1), ("8", 1), ("3.5", 1), ("four", 1)):
                os.environ[claims.WORKERS_ENV] = text
                self.assertEqual(claims.investigation_workers(), expected, text)


class FourWorkerStoreTests(Base):
    def test_four_cases_are_investigated_at_the_same_time_each_by_its_own_worker(self):
        store, driver = self.make(cases=4, capacity=4)
        barrier, during = threading.Barrier(4), []

        def inside(tools):
            barrier.wait(20)            # passes only when all four investigations are in progress at once
            during.append(store.status()["worker"])
        store.agents = Hooked(always=inside)
        results = self.together(store, {name: (lambda name=name: store.process_one(manual=True, worker_id=name)) for name in WORKERS4})
        self.assertTrue(all(isinstance(r, dict) and r["processed"] for r in results.values()), results)
        self.assertEqual(len({r["case_id"] for r in results.values()}), 4)
        self.assertEqual({r["case_id"] for r in results.values()}, set(self.queue(driver)[:4]))   # the four oldest
        self.assertEqual({s["thread"] for s in store.agents.seen}, set(WORKERS4))
        self.assertEqual(len({s["shipment"] for s in store.agents.seen}), 4)
        for worker in during:
            self.assertEqual((worker["concurrency"], worker["active_count"]), (4, 4))
            self.assertEqual({a["worker_id"] for a in worker["active_cases"]}, set(WORKERS4))
        for name, result in results.items():
            run = self.run_of(driver, result["run_id"])
            self.assertEqual((run["status"], run["worker_id"], run["case_id"]), ("REVIEWED", name, result["case_id"]))
        self.assertEqual(store.status()["worker"]["processed_count"], 4)

    def test_four_workers_asking_for_one_case_together_get_it_once(self):
        store, driver = self.make(cases=1, capacity=4)
        store.agents = Hooked()
        case_id, start = self.queue(driver)[0], threading.Barrier(4)

        def ask(name):
            start.wait(15)
            return store.process_one(case_id=case_id, worker_id=name)
        results = self.together(store, {name: (lambda name=name: ask(name)) for name in WORKERS4})
        won = [name for name, r in results.items() if r.get("processed")]
        self.assertEqual(len(won), 1, results)
        self.assertEqual([r["reason"] for r in results.values() if not r.get("processed")], ["none_eligible"] * 3)
        self.assertEqual(len(self.audits(driver, "CASE_CLAIMED", case_id)), 1)

    def test_with_three_places_a_fourth_worker_is_turned_away_for_capacity_whoever_asks(self):
        store, driver = self.make(cases=5, capacity=3)
        barrier, seen, barrier_free = threading.Barrier(3), {}, threading.Event()

        def fourth():
            time.sleep(0.5)                          # while the three are inside their investigations
            seen["fourth"] = store.process_one(manual=True, worker_id=WORKERS4[3])
            seen["count"] = store.status()["worker"]["active_count"]
            barrier_free.set()
        store.agents = Hooked(always=lambda tools: (barrier.wait(20), barrier_free.wait(20)))
        results = self.together(store, {**{name: (lambda name=name: store.process_one(manual=True, worker_id=name)) for name in WORKERS4[:3]},
                                        "fourth": fourth})
        self.assertEqual(seen["fourth"], {"processed": False, "outcome": None, "reason": "capacity"})
        self.assertEqual(seen["count"], 3)
        self.assertEqual(len({results[name]["case_id"] for name in WORKERS4[:3]}), 3)
        self.assertEqual(len(self.kind(driver, "OpsRun")), 3)

    def test_a_fixed_mock_batch_with_four_workers_spreads_over_all_four_and_completes_it(self):
        def batch(workers, latency=0.4):
            store, driver = self.make(cases=6, capacity=workers)
            store.control("worker", "start")
            inside, peak, lock, errors = [0], [0], threading.Lock(), []

            def model_time(tools):
                with lock:
                    inside[0] += 1
                    peak[0] = max(peak[0], inside[0])
                time.sleep(latency)
                with lock:
                    inside[0] -= 1
            store.agents = Hooked(always=model_time)
            queued = len(self.kind(driver, "OpsCase"))

            def loop(name):
                while True:
                    try:
                        result = store.process_one(worker_id=name)
                    except Exception as error:
                        errors.append(type(error).__name__)
                        return
                    if not result.get("processed") and result.get("reason") == "none_eligible":
                        return
            threads = [threading.Thread(target=loop, args=(name,)) for name in WORKERS4[:workers]]
            started = time.monotonic()
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(180)
            runs = self.kind(driver, "OpsRun")
            return {"workers": workers, "queued": queued, "completed": store.status()["worker"]["processed_count"],
                    "errors": errors, "peak": peak[0], "seconds": round(time.monotonic() - started, 3),
                    "by_worker": {name: sum(r["worker_id"] == name for r in runs) for name in WORKERS4[:workers]},
                    "cases_run_twice": len(runs) - len({r["case_id"] for r in runs}), "mock_only": True}
        two, four = batch(2), batch(4)
        print("\nMOCK BATCH (not a model measurement)", json.dumps([two, four]))
        self.assertEqual((two["errors"], four["errors"]), ([], []))
        self.assertEqual((two["completed"], four["completed"]), (two["queued"], four["queued"]))
        self.assertEqual((two["peak"], four["peak"]), (2, 4))
        self.assertTrue(all(count > 0 for count in four["by_worker"].values()), four)
        self.assertEqual((two["cases_run_twice"], four["cases_run_twice"]), (0, 0))
        self.assertLess(four["seconds"], two["seconds"])


class AutoStopTests(Base):
    def pool(self, store, env=None):
        from operations.workers import WorkerPool
        with mock.patch.dict(os.environ, {"SUHAIL_WORKER_PACE_SECONDS": "0", **(env or {})}):
            return WorkerPool(store)

    def test_the_pool_has_four_investigation_loops_for_four_places(self):
        store, driver = self.make(capacity=4)
        pool = self.pool(store)
        self.assertEqual(pool.investigators, list(WORKERS4))
        self.assertEqual(len(pool._threads()), 8)

    def test_auto_stops_after_its_run_limit_once_no_claim_is_live(self):
        store, driver = self.make(cases=3, capacity=2)
        store.control("worker", "start")
        store.agents = None                                                    # rules only: the limit, not the budget
        pool = self.pool(store, {"SUHAIL_AUTO_MAX_RUNS": "2"})
        self.assertTrue(pool.investigate(WORKERS4[0])["processed"])
        self.assertTrue(pool.investigate(WORKERS4[1])["processed"])
        self.assertEqual(pool.investigate(WORKERS4[0]), {"processed": False, "reason": "auto_max_runs"})
        self.assertEqual(store.status()["worker"]["state"], "paused")
        stop = pool.auto_stop()
        self.assertEqual((stop["reason"], stop["paused"], stop["runs_started"], stop["max_runs"]), ("auto_max_runs", True, 2, 2))
        self.assertEqual(len(self.kind(driver, "OpsRun")), 2)

    def test_a_budget_that_cannot_pay_for_another_investigation_stops_auto_before_a_claim(self):
        store, driver = self.make(cases=2, capacity=2)
        store.control("worker", "start")
        store.agents = Hooked()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = {"SUHAIL_INFERENCE_LEDGER": os.path.join(folder.name, "l.json"), "SUHAIL_INFERENCE_MAX_CALLS": "5",
               "SUHAIL_INPUT_USD_PER_MILLION": "1", "SUHAIL_OUTPUT_USD_PER_MILLION": "1"}
        with mock.patch.dict(os.environ, env):
            pool = self.pool(store)
            self.assertEqual(pool.investigate(WORKERS4[0]), {"processed": False, "reason": "inference_budget_exhausted"})
            self.assertEqual(store.status()["worker"]["state"], "paused")
            self.assertEqual(self.kind(driver, "OpsRun"), [])                 # nothing claimed only to fail for want of budget
            store.control("worker", "start")                                   # an operator starts Auto again: stopped again
            self.assertEqual(pool.investigate(WORKERS4[1])["reason"], "inference_budget_exhausted")
            self.assertEqual(store.status()["worker"]["state"], "paused")
        with mock.patch.dict(os.environ, {**env, "SUHAIL_INPUT_USD_PER_MILLION": ""}):
            store.control("worker", "start")
            self.assertEqual(pool.investigate(WORKERS4[0])["reason"], "inference_budget_unavailable")

    def test_the_server_never_pauses_auto_while_a_claim_is_live(self):
        store, driver = self.make(cases=2, capacity=2)
        store.control("worker", "start")
        seen = {}
        store.agents = Hooked(lambda tools: seen.update(halted=store.halt_auto("test"), state=store.status()["worker"]["state"]))
        self.assertTrue(store.process_one(worker_id=WORKERS4[0])["processed"])
        self.assertEqual((seen["halted"], seen["state"]), (False, "running"))
        self.assertTrue(store.halt_auto("test"))
        self.assertEqual(store.status()["worker"]["state"], "paused")

    def test_provider_status_reports_lanes_and_budget_and_never_a_key(self):
        store, driver = self.make(capacity=4)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patchers = keys(*KEYS)
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(provider_gate.use, provider_gate.use(None))
        with mock.patch.dict(os.environ, {"SUHAIL_INFERENCE_LEDGER": os.path.join(folder.name, "l.json"), provider_gate.MAX_INFLIGHT_ENV: "4",
                                          "SUHAIL_INPUT_USD_PER_MILLION": "1", "SUHAIL_OUTPUT_USD_PER_MILLION": "1"}):
            provider_gate.shared().fault(2, "RateLimitError")
            status = self.pool(store).provider_status()
        self.assertEqual((status["lanes_configured"], status["limit"], status["workers"]), (4, 4, 4))
        self.assertEqual([lane["lane"] for lane in status["lanes"]], ["A", "B", "C", "D"])
        self.assertEqual([lane["state"] for lane in status["lanes"]], ["ready", "ready", "cooling", "ready"])
        self.assertTrue(status["budget"]["available"])
        self.assertEqual(status["budget"]["spent"]["calls"], 0)
        text = json.dumps(status)
        self.assertFalse(any(key in text for key in KEYS))


if __name__ == "__main__":
    unittest.main()
