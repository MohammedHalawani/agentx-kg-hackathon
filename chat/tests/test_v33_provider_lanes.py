"""V3.3: provider lanes. One lane per distinct provider key, one call in flight per lane (operations.provider_gate).

A provider plan that allows one request in flight per account must never see two on one key. These tests check the
gate's lane bookkeeping, how the shared gate's limit follows the keys, and, against an ephemeral loopback HTTP server
through the real LiteLLM/OpenAI transport, that two calls in flight carry two different keys and one key never carries
two. Offline only: no provider is called.
"""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import litellm
from langchain_core.messages import HumanMessage
from llm import translate
from llm.pipeline import _llm
from operations import provider_gate
from operations.inference_safety import InferenceLedger

KEY_A, KEY_B = "offline-lane-a", "offline-lane-b"


class LaneBookkeepingTests(unittest.TestCase):
    def test_two_slots_are_two_lanes_and_a_lane_is_reused_only_when_free(self):
        gate = provider_gate.ProviderGate(2)
        first, second = gate.acquire(1), gate.acquire(1)
        self.assertEqual({first.lane, second.lane}, {0, 1})
        with self.assertRaises(provider_gate.CapacityUnavailable):
            gate.acquire(0.1)
        first.release()
        third = gate.acquire(1)
        self.assertEqual(third.lane, first.lane)
        self.assertEqual([lane["busy"] for lane in gate.snapshot()["lanes"]], [True, True])

    def test_an_abandoned_call_keeps_its_lane_until_it_ends(self):
        gate = provider_gate.ProviderGate(2)
        stalled = gate.acquire(1)
        stalled.abandon()
        retry = gate.acquire(1)
        self.assertNotEqual(retry.lane, stalled.lane)
        retry.release()
        again = gate.acquire(1)
        self.assertNotEqual(again.lane, stalled.lane)       # the abandoned call still holds its lane and key
        stalled.release()
        self.assertEqual(gate.snapshot()["inflight"], 1)

    def test_a_lane_out_of_service_is_skipped_and_the_last_lane_is_never_taken_out(self):
        gate = provider_gate.ProviderGate(2)
        self.assertTrue(gate.disable(1, "RateLimitError"))
        self.assertFalse(gate.disable(0, "RateLimitError"))
        first = gate.acquire(1)
        self.assertEqual(first.lane, 0)
        with self.assertRaises(provider_gate.CapacityUnavailable):
            gate.acquire(0.1)                                   # one lane left: one call at a time
        with self.assertRaises(provider_gate.CapacityUnavailable) as refused:
            gate.acquire(1, lane=1)
        self.assertEqual(refused.exception.reason, "lane_disabled")
        self.assertEqual(gate.snapshot()["lanes"][1]["disabled"], "RateLimitError")

    def test_a_lane_can_be_asked_for(self):
        gate = provider_gate.ProviderGate(2)
        second = gate.acquire(1, lane=1)
        self.assertEqual(second.lane, 1)
        with self.assertRaises(provider_gate.CapacityUnavailable):
            gate.acquire(0.1, lane=1)                           # lane B is busy; lane A being free does not help
        self.assertEqual(gate.acquire(1).lane, 0)

    def test_waiters_are_served_in_order_across_lanes(self):
        gate = provider_gate.ProviderGate(2)
        held = [gate.acquire(1), gate.acquire(1)]
        order = []

        def wait(name):
            permit = gate.acquire(5)
            order.append(name)
            time.sleep(0.05)
            permit.release()

        threads = []
        for name in ("first", "second", "third"):
            threads.append(threading.Thread(target=wait, args=(name,)))
            threads[-1].start()
            time.sleep(0.1)
        for permit in held:
            permit.release()
        for thread in threads:
            thread.join(5)
        self.assertEqual(order, ["first", "second", "third"])

    def test_one_slot_is_always_lane_zero(self):
        gate = provider_gate.ProviderGate(1)
        for _ in range(3):
            permit = gate.acquire(1)
            self.assertEqual(permit.lane, 0)
            permit.release()


class SharedLimitTests(unittest.TestCase):
    def shared_limit(self, requested, first, second):
        with mock.patch.dict(os.environ, {provider_gate.MAX_INFLIGHT_ENV: requested}), \
                mock.patch.object(_llm.config, "LLM_API_KEY", first), mock.patch.object(_llm.config, "LLM_API_KEY2", second):
            previous = provider_gate.use(None)
            try:
                return provider_gate.shared().limit
            finally:
                provider_gate.use(previous)

    def test_limit_two_needs_two_distinct_keys(self):
        self.assertEqual(self.shared_limit("2", KEY_A, KEY_B), 2)
        self.assertEqual(self.shared_limit("2", KEY_A, None), 1)
        self.assertEqual(self.shared_limit("2", KEY_A, KEY_A), 1)      # the same account twice is still one lane
        self.assertEqual(self.shared_limit("2", None, None), 1)
        self.assertEqual(self.shared_limit("1", KEY_A, KEY_B), 1)      # a second key never raises the limit by itself
        self.assertEqual(self.shared_limit("3", KEY_A, KEY_B), 2)      # three asked for, two distinct keys: two (V3.4)
        with mock.patch.dict(os.environ, {provider_gate.LANE_B_ENV: "off"}):
            self.assertEqual(self.shared_limit("2", KEY_A, KEY_B), 1)  # lane B switched off: one lane, as before

    def test_lane_one_without_a_distinct_second_key_is_lane_zeros_key(self):
        with mock.patch.object(_llm.config, "LLM_API_KEY", KEY_A), mock.patch.object(_llm.config, "LLM_API_KEY2", KEY_A):
            self.assertEqual(_llm.lane_key(1), KEY_A)
        with mock.patch.object(_llm.config, "LLM_API_KEY", KEY_A), mock.patch.object(_llm.config, "LLM_API_KEY2", KEY_B):
            self.assertEqual((_llm.lane_key(0), _llm.lane_key(1)), (KEY_A, KEY_B))


class LoopbackLaneTests(unittest.TestCase):
    """Real HTTP through LiteLLM's OpenAI transport against a loopback server that records each request's key and how
    many requests per key were open at once."""

    STALL = 0.6

    def setUp(self):
        self.lock = threading.Lock()
        self.open_by_key, self.peak_by_key, self.seen = {}, {}, []
        self.open_total = self.peak_total = 0
        self.status_by_key = {}
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
                with test.lock:
                    test.open_by_key[key] -= 1
                    test.open_total -= 1
                status = test.status_by_key.get(key, 200)
                if status != 200:
                    payload = json.dumps({"error": {"message": "offline failure", "type": "server_error"}}).encode()
                    try:
                        self.send_response(status)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header("Retry-After", "0")
                        self.end_headers()
                        self.wfile.write(payload)
                    except OSError:
                        pass
                    return
                payload = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": "gpt-oss:120b",
                                      "choices": [{"index": 0, "finish_reason": "stop",
                                                   "message": {"role": "assistant", "content": "ok"}}],
                                      "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.ledger_path = os.path.join(folder.name, "ledger.json")
        for patcher in (
            mock.patch.dict(os.environ, {"SUHAIL_INFERENCE_LEDGER": self.ledger_path, "SUHAIL_INPUT_USD_PER_MILLION": "1",
                                         "SUHAIL_OUTPUT_USD_PER_MILLION": "1", "SUHAIL_INFERENCE_MAX_CALLS": "100",
                                         "SUHAIL_INFERENCE_MAX_TOKENS": "100000000", "SUHAIL_INFERENCE_MAX_USD": "100",
                                         provider_gate.MAX_INFLIGHT_ENV: "2"}),
            mock.patch.object(_llm.config, "LLM_API_BASE", f"http://127.0.0.1:{self.server.server_port}/v1"),
            mock.patch.object(_llm.config, "LLM_API_KEY", KEY_A),
            mock.patch.object(_llm.config, "LLM_API_KEY2", KEY_B),
            mock.patch.object(litellm, "telemetry", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        _llm.model.cache_clear()
        self.addCleanup(_llm.model.cache_clear)
        previous = provider_gate.use(None)              # the shared gate is rebuilt from the patched keys
        self.addCleanup(provider_gate.use, previous)

    def run_calls(self, count, threads, call):
        errors, queue, lock = [], list(range(count)), threading.Lock()

        def worker():
            while True:
                with lock:
                    if not queue:
                        return
                    queue.pop()
                try:
                    call()
                except Exception as error:   # surfaced below
                    errors.append(error)

        pool = [threading.Thread(target=worker) for _ in range(threads)]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join(30)
        self.assertEqual(errors, [])

    def test_two_calls_in_flight_carry_two_keys_and_no_key_carries_two(self):
        self.assertEqual(provider_gate.shared().limit, 2)
        with self.assertLogs("suhail.provider.transport", "INFO") as logs:
            self.run_calls(6, 3, lambda: _llm.invoke([HumanMessage("offline lane probe")], deadline=20))
        self.assertEqual(len(self.seen), 6)
        self.assertEqual(self.peak_total, 2)                               # two requests really open at once
        self.assertEqual(self.peak_by_key, {KEY_A: 1, KEY_B: 1})           # never two on one key
        snapshot = provider_gate.shared().snapshot()
        self.assertEqual((snapshot["peak_inflight"], snapshot["inflight"]), (2, 0))
        self.assertEqual(sum(1 for line in logs.output if "transport dispatch" in line), 6)
        self.assertEqual(sum(1 for line in logs.output if "transport return" in line and "outcome=ok" in line), 6)
        self.assertFalse(any(KEY_A in line or KEY_B in line for line in logs.output))
        rows = InferenceLedger().load()["entries"]
        self.assertEqual(sorted(row["lane"] for row in rows), ["A", "A", "A", "B", "B", "B"])
        self.assertTrue(all(row["status"] == "usage_confirmed" for row in rows))

    def test_one_key_keeps_one_request_open_even_when_two_are_asked_for(self):
        with mock.patch.object(_llm.config, "LLM_API_KEY2", None):
            provider_gate.use(None)
            self.assertEqual(provider_gate.shared().limit, 1)
            self.run_calls(3, 2, lambda: _llm.invoke([HumanMessage("offline lane probe")], deadline=20))
        self.assertEqual((self.peak_total, set(self.seen)), (1, {KEY_A}))

    def test_a_429_on_lane_b_takes_it_out_without_retry_or_resending_on_lane_a(self):
        self.status_by_key[KEY_B] = 429
        with self.assertRaises(litellm.RateLimitError):
            _llm.invoke([HumanMessage("offline lane probe")], deadline=20, lane=1)
        self.assertEqual(self.seen, [KEY_B])                               # one request, not retried, not re-sent on A
        self.assertEqual(provider_gate.shared().snapshot()["lanes"][1]["disabled"], "RateLimitError")
        self.run_calls(3, 2, lambda: _llm.invoke([HumanMessage("offline lane probe")], deadline=20))
        self.assertEqual(self.seen, [KEY_B, KEY_A, KEY_A, KEY_A])          # one lane from now on
        self.assertEqual(self.peak_total, 1)
        rows = InferenceLedger().load()["entries"]
        self.assertEqual([row["lane"] for row in rows], ["B", "A", "A", "A"])
        self.assertEqual(rows[0]["status"], "maximum_charged")             # no usage: the reservation stays charged

    def test_a_503_fails_one_call_and_keeps_the_lane(self):
        self.status_by_key[KEY_B] = 503
        with self.assertRaises(litellm.ServiceUnavailableError):
            _llm.invoke([HumanMessage("offline lane probe")], deadline=20, lane=1)
        self.assertEqual(self.seen, [KEY_B])
        self.assertIsNone(provider_gate.shared().snapshot()["lanes"][1]["disabled"])

    def test_one_key_429_keeps_the_only_lane(self):
        with mock.patch.object(_llm.config, "LLM_API_KEY2", None):
            provider_gate.use(None)
            self.status_by_key[KEY_A] = 429
            with self.assertRaises(litellm.RateLimitError):
                _llm.invoke([HumanMessage("offline lane probe")], deadline=20)
            self.assertIsNone(provider_gate.shared().snapshot()["lanes"][0]["disabled"])

    def test_an_abandoned_call_holds_its_lane_and_is_charged_until_it_ends(self):
        self.STALL = 1.5
        with self.assertRaises(_llm.ModelCallTimeout):
            _llm.invoke([HumanMessage("offline lane probe")], deadline=0.5, lane=1)
        snapshot = provider_gate.shared().snapshot()
        self.assertTrue(snapshot["lanes"][1]["busy"])                       # still open at the provider
        self.assertEqual(_llm.invoke([HumanMessage("offline lane probe")], deadline=20).content, "ok")
        self.assertEqual(self.seen, [KEY_B, KEY_A])                         # the next call took lane A, not B
        deadline = time.monotonic() + 5
        while provider_gate.shared().snapshot()["lanes"][1]["busy"] and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(provider_gate.shared().snapshot()["lanes"][1]["busy"])
        rows = {row["lane"]: row for row in InferenceLedger().load()["entries"]}
        self.assertEqual(rows["B"]["status"], "abandoned")

    def test_translation_passing_the_shared_client_still_uses_its_lane(self):
        self.run_calls(4, 2, lambda: _llm.invoke([HumanMessage("offline lane probe")], client=translate.model(),
                                                  deadline=20, entry="translate"))
        self.assertEqual(self.peak_by_key, {KEY_A: 1, KEY_B: 1})
        self.assertEqual(self.peak_total, 2)


if __name__ == "__main__":
    unittest.main()
