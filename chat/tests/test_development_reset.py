"""L10: the development reset deletes the operations ledger only behind an explicit development flag
(environment variable, default off) and the current session's confirmation; every attempt is audited."""
import json
import os
import unittest
from unittest import mock

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations.lifecycle import OperationsConflict
from operations.store import DEV_RESET_ENV, OperationsStore
from tests.test_operations_store import Driver, Reader, development_reset


class DevelopmentResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = generate(Config(total=90))

    def setUp(self):
        self.driver = Driver(self.world)
        self.store = OperationsStore(self.driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world))
        self.store.initialize()
        development_reset(self.store)
        for _ in range(12):  # Some ledger to protect.
            self.store.tick(seconds=86400, manual=True, speed=60)
            while self.store.status()["session"]["monitor_pending"]:
                self.store.monitor_step()
        self.assertTrue(self.cases())

    def cases(self):
        return [v for k, v in self.driver.ledger.values() if k == "OpsCase"]

    def audit(self):
        control = next(v for k, v in self.driver.ledger.values() if k == "OpsControl")
        return json.loads(control.get("reset_audit_json") or "[]")

    def test_the_flag_is_off_by_default_and_a_reset_is_refused_and_audited(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DEV_RESET_ENV, None)
            status = self.store.status()["development_reset"]
            self.assertEqual((status["enabled"], status["confirmation"]), (False, None))
            before = len(self.cases())
            with self.assertRaises(OperationsConflict) as refused:
                self.store.reset_session("DEMO-OPERATOR-LOCAL", confirmation=self.store.reset_confirmation())
        self.assertIn(f"{DEV_RESET_ENV}=1", str(refused.exception))
        self.assertEqual(len(self.cases()), before)  # Nothing deleted.
        self.assertEqual((self.audit()[-1]["result"], self.audit()[-1]["reason"]), ("REFUSED", "development reset disabled"))
        for value in ("0", "true", "yes", ""):  # Only an explicit 1 enables it.
            with mock.patch.dict(os.environ, {DEV_RESET_ENV: value}):
                with self.assertRaises(OperationsConflict):
                    self.store.reset_session("DEMO-OPERATOR-LOCAL", confirmation=self.store.reset_confirmation())
        self.assertEqual(len(self.cases()), before)

    def test_with_the_flag_a_missing_or_stale_confirmation_is_refused_and_audited(self):
        before = len(self.cases())
        stale = self.store.reset_confirmation()
        with mock.patch.dict(os.environ, {DEV_RESET_ENV: "1"}):
            for confirmation in (None, "", "RESET-LEDGER-wrong", 7):
                with self.assertRaises(OperationsConflict) as refused:
                    self.store.reset_session("DEMO-OPERATOR-LOCAL", confirmation=confirmation)
                self.assertIn("confirmation", str(refused.exception))
            self.assertEqual(len(self.cases()), before)
            self.store.reset_session("DEMO-OPERATOR-LOCAL", confirmation=stale)
            self.assertEqual(self.cases(), [])
            # The confirmation named the session it reset: replaying it after the reset is refused.
            with self.assertRaises(OperationsConflict):
                self.store.reset_session("DEMO-OPERATOR-LOCAL", confirmation=stale)
        results = [entry["result"] for entry in self.audit()]
        self.assertEqual(results[-6:], ["REFUSED"] * 4 + ["PERFORMED", "REFUSED"])

    def test_a_confirmed_development_reset_is_audited_on_the_record_it_keeps(self):
        before_session = self.store.status()["session"]["session_id"]
        removed = sum(k != "OpsControl" for k, _ in self.driver.ledger.values())
        development_reset(self.store)
        entry = self.audit()[-1]
        self.assertEqual((entry["result"], entry["actor_id"], entry["deleted_records"]), ("PERFORMED", "DEMO-OPERATOR-LOCAL", removed))
        self.assertEqual(entry["session_before"], before_session)
        self.assertEqual(entry["session_after"], self.store.status()["session"]["session_id"])
        self.assertNotEqual(entry["session_after"], before_session)
        self.assertEqual(self.store.status()["development_reset"]["last"]["result"], "PERFORMED")
        with self.assertRaises(OperationsConflict):  # The operator authority check still applies.
            with mock.patch.dict(os.environ, {DEV_RESET_ENV: "1"}):
                self.store.reset_session("AI", confirmation=self.store.reset_confirmation())


if __name__ == "__main__":
    unittest.main()
