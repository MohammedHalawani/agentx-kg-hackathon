"""Write-boundary guards and stable replay keys; no database/model calls."""
import copy
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "test")
os.environ.setdefault("NEO4J_PASSWORD", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.pipeline import writeback


def accepted_state():
    return {
        "extracted": {"shipment_id": "SHP-9001", "tracking_id": "SPL100009001"},
        "context": {"live_failure_id": "FR-FIXTURE-1", "local_subgraph": {
            "shipment": {"shipment_id": "SHP-9001", "tracking_id": "SPL100009001"},
            "live_failure": {"failure_id": "FR-FIXTURE-1"},
        }},
        "recommendation": {"action": "Confirm address and redirect"},
        "review": {"verdict": "accept", "score": 0.9, "reason": "Address mismatch confirmed."},
        "classification": {"category": "address_conflict", "priority": "high", "confidence": 0.9},
        "complaint_text": "Fixture address mismatch", "loop_count": 0,
    }


class WriteBoundaryTests(unittest.TestCase):
    def test_invalid_acceptance_never_opens_driver(self):
        bad = []
        for verdict, score, action in [("reject", .9, "redirect"), ("accept", .5, "redirect"),
                                       ("accept", float("nan"), "redirect"), ("accept", True, "redirect"),
                                       ("accept", 1.1, "redirect"), ("accept", .9, "  "),
                                       ("accept", .9, {"text": "redirect"}),
                                       ("accept", .9, "<think>private</think>")]:
            state = accepted_state()
            state["review"].update(verdict=verdict, score=score)
            state["recommendation"]["action"] = action
            bad.append(state)
        with patch.object(writeback, "get_driver") as driver:
            for state in bad:
                with self.subTest(state=state["review"], action=state["recommendation"]):
                    self.assertIsNone(writeback.write_resolution(state))
            driver.assert_not_called()

    def test_identity_mismatch_or_missing_never_opens_driver(self):
        states = []
        for part, field, value in [("extracted", "shipment_id", "SHP-other"),
                                    ("extracted", "tracking_id", "SPL-other")]:
            state = accepted_state(); state[part][field] = value; states.append(state)
        for change in ("shipment", "live_failure", "failure_id"):
            state = accepted_state()
            if change == "failure_id":
                state["context"]["live_failure_id"] = "FR-other"
            else:
                state["context"]["local_subgraph"].pop(change)
            states.append(state)
        state = accepted_state(); state["extracted"] = {}; states.append(state)
        with patch.object(writeback, "get_driver") as driver:
            for state in states:
                self.assertIsNone(writeback.write_resolution(state))
            driver.assert_not_called()

    def test_repeat_state_has_same_keys_and_pending_provenance(self):
        state = accepted_state(); driver = Mock()
        def execute(query, **args):
            return [{"resolution_id": args["parameters_"]["resolution_id"]}], None, None
        driver.execute_query.side_effect = execute
        with patch.object(writeback, "get_driver", return_value=driver):
            first = writeback.write_resolution(state)
            repeated = writeback.write_resolution(copy.deepcopy(state))
        self.assertEqual(first, repeated)
        params = [c.kwargs["parameters_"] for c in driver.execute_query.call_args_list]
        self.assertEqual(params[0]["outcome_id"], params[1]["outcome_id"])
        self.assertIsNone(params[0]["success"])
        self.assertEqual(datetime.fromisoformat(params[0]["timestamp"]).utcoffset(), timezone.utc.utcoffset(None))
        self.assertEqual(driver.execute_query.call_args.kwargs["database_"], writeback.config.SHIPMENT_DATABASE)
        changed = accepted_state(); changed["recommendation"]["action"] = "Reschedule"
        with patch.object(writeback, "get_driver", return_value=driver):
            self.assertNotEqual(first, writeback.write_resolution(changed))
        # Deterministic key differs, while the DB guard refuses a competing existing action.

    def test_database_guard_refusal_is_not_reported_as_written(self):
        driver = Mock(); driver.execute_query.return_value = ([], None, None)
        with patch.object(writeback, "get_driver", return_value=driver):
            self.assertIsNone(writeback.write_resolution(accepted_state()))

    def test_tracking_only_identity_and_final_only_persisted_notes(self):
        state = accepted_state(); state["extracted"]["shipment_id"] = None
        state["review"]["reason"] = "<think>PRIVATE_SENTINEL</think>Address confirmed."
        driver = Mock(); driver.execute_query.return_value = ([{"resolution_id": "RES-fixture"}], None, None)
        with patch.object(writeback, "get_driver", return_value=driver):
            self.assertEqual(writeback.write_resolution(state), "RES-fixture")
        p = driver.execute_query.call_args.kwargs["parameters_"]
        self.assertEqual(p["shipment_id"], "SHP-9001")
        self.assertNotIn("PRIVATE_SENTINEL", p["notes"])
        self.assertIn("execution unconfirmed", p["notes"])

    def test_escalation_replay_key_and_invalid_identity(self):
        state = accepted_state(); state["review"]["verdict"] = "reject"
        driver = Mock()
        driver.execute_query.side_effect = lambda q, **kw: ([{"escalation_id": kw["parameters_"]["escalation_id"], "team": "fixture"}], None, None)
        with patch.object(writeback, "get_driver", return_value=driver):
            first = writeback.write_escalation(state)
            self.assertEqual(first, writeback.write_escalation(copy.deepcopy(state)))
        self.assertTrue(driver.execute_query.call_args.kwargs["parameters_"]["created_at"].endswith("+00:00"))
        state["extracted"]["shipment_id"] = "SHP-other"
        with patch.object(writeback, "get_driver") as uncalled:
            self.assertIsNone(writeback.write_escalation(state))
            uncalled.assert_not_called()


if __name__ == "__main__":
    unittest.main()
