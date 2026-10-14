"""Production safeguards, with temporary ledgers and scripted/loopback providers only."""
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from operations.inference_safety import InferenceLedger, Policy, SafetyRefused
from operations import provider_gate
from llm.pipeline import _llm


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.json"
        self.policy = Policy(10, 100000, "100", "10", "20", 8192, 128)
        self.ledger = InferenceLedger(self.policy, self.path)

    def reserve(self, ledger=None):
        return (ledger or self.ledger).reserve(["source evidence"], {"role": "reviewer"}, time.monotonic() + 2)

    def test_missing_usage_errors_and_crash_keep_durable_maximum(self):
        key = self.reserve()
        before = self.ledger.load()["entries"][0]
        self.ledger.finish(key)
        after = InferenceLedger(self.policy, self.path).load()["entries"][0]
        self.assertEqual((after["tokens"], after["usd"], after["calls"]), (before["tokens"], before["usd"], 1))
        self.assertEqual(after["status"], "maximum_charged")
        crashed = self.reserve()
        self.assertEqual(InferenceLedger(self.policy, self.path).load()["entries"][-1]["id"], crashed)

    def test_confirmed_usage_settles_but_abandonment_never_frees_uncertain_spend(self):
        key = self.reserve()
        self.ledger.finish(key, response=SimpleNamespace(usage_metadata={"input_tokens": 10, "output_tokens": 20}))
        row = self.ledger.load()["entries"][0]
        self.assertEqual(row["tokens"], 30)
        self.assertEqual(Decimal(row["usd"]), self.policy.cost(10, 20))
        self.ledger.finish(key, abandoned=True)
        self.ledger.finish(key, response=SimpleNamespace(usage_metadata={"input_tokens": 1, "output_tokens": 1}))
        self.assertEqual(self.ledger.load()["entries"][0]["status"], "abandoned")
        self.assertGreater(self.ledger.load()["entries"][0]["tokens"], 30)

    def test_atomic_aggregate_reservation_across_separate_ledger_clients(self):
        policy = Policy(1, 100000, "100", "10", "20", 8192, 128)
        barrier, results = threading.Barrier(3), []
        def reserve():
            barrier.wait()
            try:
                self.reserve(InferenceLedger(policy, self.path)); results.append("reserved")
            except SafetyRefused:
                results.append("refused")
        threads = [threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join(3)
        self.assertEqual(sorted(results), ["refused", "reserved"])

    def test_call_token_and_cost_caps_and_missing_rates_fail_closed(self):
        for policy in (Policy(10, 1, "100", "10", "20", 8192, 128), Policy(10, 100000, ".000001", "10", "20", 8192, 128)):
            with self.subTest(policy=policy), self.assertRaises(SafetyRefused):
                self.reserve(InferenceLedger(policy, self.path))
        with patch.dict(os.environ, {"SUHAIL_INPUT_USD_PER_MILLION": ""}), self.assertRaises(SafetyRefused):
            Policy.configured()
        self.assertFalse(self.path.exists())

    def test_policy_change_corruption_and_usage_breach_block_further_requests(self):
        key = self.reserve()
        with self.assertRaises(SafetyRefused):
            self.ledger.finish(key, response=SimpleNamespace(usage_metadata={"input_tokens": 1, "output_tokens": 129}))
        with self.assertRaises(SafetyRefused): self.reserve()
        self.path.write_text("{}")
        with self.assertRaises(SafetyRefused): self.reserve()

    def test_shared_deadline_spends_admission_time_once_and_keeps_provider_permit(self):
        gate = provider_gate.ProviderGate(1)
        old = provider_gate.use(gate)
        self.addCleanup(provider_gate.use, old)
        permit = gate.acquire(1)
        released, finish = threading.Event(), threading.Event()
        seen = []
        def release():
            time.sleep(.08); permit.release(); released.set()
        thread = threading.Thread(target=release); thread.start()
        def invoke(messages, **kwargs):
            seen.append(kwargs); finish.wait(2)
            return SimpleNamespace(content="late")
        started = time.monotonic()
        with patch("operations.inference_safety.InferenceLedger", return_value=self.ledger):
            with self.assertRaises(_llm.ModelCallTimeout):
                _llm.invoke(["m"], deadline=.20, client=SimpleNamespace(invoke=invoke))
        elapsed = time.monotonic() - started
        self.assertTrue(released.is_set())
        self.assertLess(elapsed, .27)
        self.assertGreater(elapsed, .17)
        self.assertLess(seen[0]["timeout"], .15)
        self.assertEqual(seen[0]["max_tokens"], 128)
        self.assertEqual(gate.snapshot()["inflight"], 1)
        finish.set(); thread.join(2)
        until = time.monotonic() + 2
        while gate.snapshot()["inflight"] and time.monotonic() < until: time.sleep(.01)
        self.assertEqual(self.ledger.load()["entries"][0]["status"], "abandoned")


if __name__ == "__main__": unittest.main()
