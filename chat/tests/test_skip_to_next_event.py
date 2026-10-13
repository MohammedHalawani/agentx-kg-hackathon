"""Skip to the next event: the clock runs forward until a case awaiting evidence gets its verified outcome or a new case
opens, then goes back as it was. The same clock and the same steps as at any speed: outcomes are decided by the verifier
from the records of the simulated world; nothing about a future event is returned."""
import unittest

from dataset_v2.contracts import instant
from operations.lifecycle import OperationsConflict
from operations.schema import public_value
from tests.test_operations_store import WallClock, live_claim
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
        # An investigation in progress is a live claim: the store's own grant on an OPEN peer case, with its run, worker,
        # epoch and unexpired lease (operations.claims). The case awaiting its outcome is not touched by any of it.
        peer = self.peer(s)
        with live_claim(s.store, peer) as claimed:
            case = next(public_value(c) for c in s.kind("OpsCase") if c["entity_id"] == peer)
            run = next(public_value(r) for r in s.kind("OpsRun") if r["entity_id"] == claimed["last_run_id"])
            self.assertEqual((case["workflow_state"], run["status"]), ("INVESTIGATING", "RUNNING"))
            self.assertEqual([case[k] for k in ("claim_id", "claim_epoch", "worker_id", "last_run_id")],
                             [claimed["claim_id"], 1, "investigation-1", run["entity_id"]])
            self.assertEqual([run[k] for k in ("claim_id", "claim_epoch", "worker_id")], [claimed["claim_id"], 1, "investigation-1"])
            self.assertGreater(instant(case["lease_expires_at"]), s.store.wall())
            with self.assertRaises(OperationsConflict) as refused:
                s.store.skip_to_next_event()
            self.assertIn("investigation is running", str(refused.exception))
            self.assertEqual([a["case_id"] for a in s.store.status()["worker"]["active_cases"]], [peer])     # the claim is untouched
        self.assertEqual(s.case(case_id)["workflow_state"], "AWAITING_OUTCOME")

    def peer(self, s, sid=WRONG_LABEL):
        """An OPEN case on another shipment, opened as the monitor opens one: what an investigation can be claiming
        while the first case awaits its outcome."""
        def write(tx):
            control = s.store._control(tx, lock=True)
            symptoms = sorted(symptoms_at(s.live, sid, s.live.clock)) or ["BARCODE_READ_DIFFERS"]
            return s.store._open_monitored_case(tx, sid, symptoms, control["as_of"], control.get("session_id"))
        return s.store._execute(write, write=True)

    def test_a_leftover_flag_of_the_earlier_ledger_format_does_not_refuse_a_skip(self):
        """The single flag on the control record is not a claim: nothing is being investigated, so time may be skipped."""
        from operations.store import CONTROL_ID
        s, case_id = self.seeded(MISREAD)
        s.driver.ledger[CONTROL_ID][1]["worker_claim"] = case_id
        result = s.store.skip_to_next_event(max_hours=1)
        self.assertIn(result["reason"], ("outcome_decided", "case_opened", "limit_reached", "end_of_timeline"))
        self.assertIsNone(s.driver.ledger[CONTROL_ID][1].get("worker_claim"))     # and the stale flag is cleared
        self.assertEqual(s.store.status()["worker"]["active_count"], 0)

    def test_an_expired_claim_does_not_refuse_a_skip_and_is_recovered_first(self):
        """A claim whose lease ran out is not a running investigation: it is requeued, then the skip goes ahead."""
        s, case_id = self.seeded(MISREAD)
        peer = self.peer(s)
        clock = s.store.wall = WallClock()
        with live_claim(s.store, peer) as claimed:
            clock.advance(181)                                      # past the 180 s lease, with no renewal
            result = s.store.skip_to_next_event(max_hours=1)
            self.assertIn(result["reason"], ("outcome_decided", "case_opened", "limit_reached", "end_of_timeline"))
            self.assertIn("CLAIM_EXPIRED", s.audits(peer))
            run = next(public_value(r) for r in s.kind("OpsRun") if r["entity_id"] == claimed["last_run_id"])
            self.assertEqual((run["status"], run["end_reason"]), ("ABORTED", "LEASE_EXPIRED"))
        self.assertNotEqual(s.case(peer)["workflow_state"], "INVESTIGATING")
        self.assertEqual(s.store.status()["worker"]["active_count"], 0)


if __name__ == "__main__":
    unittest.main()
