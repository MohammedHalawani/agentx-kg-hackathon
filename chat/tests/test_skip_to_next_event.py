"""Skip to the next event: the clock runs forward until a case awaiting evidence gets its verified outcome or a new case
opens, then goes back as it was. The same clock and the same steps as at any speed: outcomes are decided by the verifier
from the records of the simulated world; nothing about a future event is returned."""
import unittest

from dataset_v2.contracts import instant
from operations.lifecycle import OperationsConflict
from tests.test_world_simulation import Scenario, at
from tests.world_live import seed_case, symptoms_at

MISREAD = "DEMO-SHP-000064"          # A one-off sorter misread: a rescan reads the manifest barcode again.
WRONG_LABEL = "DEMO-SHP-000049"      # Carries the label of another order: every rescan returns that barcode.


class SkipTests(unittest.TestCase):
    def seeded(self, sid, when="17T03:30"):
        s = Scenario(at(when))
        case_id = seed_case(s.store, s.driver, sid, "REQUEST_RESCAN", ["BARCODE_MISMATCH"], symptoms=symptoms_at(s.live, sid, s.live.clock))
        s.store.execute_step()
        return s, case_id

    def test_it_stops_when_the_awaited_outcome_is_verified_and_restores_the_clock(self):
        s, case_id = self.seeded(MISREAD)
        before = s.store.status()
        self.assertEqual((before["simulator"]["state"], s.case(case_id)["workflow_state"]), ("paused", "AWAITING_OUTCOME"))
        result = s.store.skip_to_next_event(max_hours=24)
        self.assertEqual(result["reason"], "outcome_decided")
        self.assertIn({"case_id": case_id, "workflow_state": "RESOLVED"}, result["cases"])     # Other cases may have opened in the same step.
        detail = s.case(case_id)
        self.assertEqual((detail["workflow_state"], detail["outcome"]["verification_status"], detail["outcome"]["outcome_type"]),
                         ("RESOLVED", "VERIFIED", "barcode_corrected"))               # Decided by the verifier from the simulated record.
        after = s.store.status()
        self.assertEqual((after["simulator"]["state"], after["simulator"]["speed"]), ("paused", before["simulator"]["speed"]))
        self.assertEqual(result["status"]["simulator"]["state"], "paused")
        self.assertGreater(instant(result["to"]), instant(result["from"]))
        self.assertLessEqual(result["simulated_minutes"], 24 * 60)
        self.assertEqual(result["still_awaiting_evidence"], 0)
        self.assertEqual(sorted(result), ["cases", "from", "reason", "simulated_minutes", "status", "still_awaiting_evidence", "to"])

    def test_an_unsuccessful_action_is_reported_as_it_is_never_as_a_resolution(self):
        s, case_id = self.seeded(WRONG_LABEL)
        result = s.store.skip_to_next_event(max_hours=96)
        self.assertEqual(result["reason"], "outcome_decided")
        detail = s.case(case_id)
        self.assertEqual((detail["workflow_state"], detail["outcome"]["success"]), ("HUMAN_REVIEW", False))
        self.assertIn({"case_id": case_id, "workflow_state": "HUMAN_REVIEW"}, result["cases"])

    def test_with_nothing_to_wait_for_it_stops_at_its_limit_and_a_running_clock_is_left_paused(self):
        s = Scenario(at("17T03:30"))
        s.store.control("simulator", "start", speed=60)
        result = s.store.skip_to_next_event(max_hours=1)
        self.assertIn(result["reason"], ("limit_reached", "case_opened"))
        if result["reason"] == "limit_reached":
            self.assertGreaterEqual(result["simulated_minutes"], 59)
        after = s.store.status()["simulator"]
        self.assertEqual((after["state"], after["speed"]), ("paused", 60))      # Paused afterwards, at the speed it had.
        self.assertEqual(result["status"]["simulator"]["state"], "paused")

    def test_a_step_that_fails_still_leaves_the_clock_paused(self):
        from unittest import mock
        s = Scenario(at("17T03:30"))
        s.store.control("simulator", "start", speed=60)
        with mock.patch.object(s.store, "outcome_step", side_effect=RuntimeError("database hiccup")):
            with self.assertRaises(RuntimeError):
                s.store.skip_to_next_event(max_hours=1)
        after = s.store.status()["simulator"]
        self.assertEqual((after["state"], after["speed"]), ("paused", 60))

    def test_it_is_bounded_and_refused_while_an_investigation_runs(self):
        s, case_id = self.seeded(MISREAD)
        for hours in (0, 169, 1.5, "3", None):
            with self.assertRaises(OperationsConflict):
                s.store.skip_to_next_event(max_hours=hours)
        from operations.store import CONTROL_ID
        s.driver.ledger[CONTROL_ID][1]["worker_claim"] = case_id
        with self.assertRaises(OperationsConflict):
            s.store.skip_to_next_event()
        self.assertEqual(s.case(case_id)["workflow_state"], "AWAITING_OUTCOME")


if __name__ == "__main__":
    unittest.main()
