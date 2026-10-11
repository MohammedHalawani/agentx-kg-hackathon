"""Case detail's next_step: what the case needs next and why it is not resolved, derived only from recorded fields."""
import unittest

from operations.next_step import STEPS, next_step, step_code


def case(state, *, approvable=None, action="REQUEST_RESCAN", executions=(), outcome=None, rule="AUTH-16-review-rejected", verdict="REVISE", **diagnosis):
    recommendation = None if approvable is None else {"action_type": action, "approvable": approvable, "approval_rule": "AUTH-19-operator-approved",
                                                      "approval_reason": "A person may authorize this."}
    return {"workflow_state": state, "recommendation": recommendation, "executions": list(executions), "outcome": outcome,
            "review": {"verdict": "reject", "model_verdict": verdict, "feedback": "Not supported."},
            "run": {"result": {"authority": {"rule_id": rule, "reason": "Recorded reason.", "risk_class": "HUMAN_REVIEW"}}},
            "diagnosis": {"available": False, **diagnosis}}


class NextStepTests(unittest.TestCase):
    def test_each_state_has_one_step_and_only_a_resolved_case_needs_nothing(self):
        expected = {"RESOLVED": "NONE", "OPEN": "START_INVESTIGATION", "REOPENED": "START_INVESTIGATION", "INVESTIGATING": "WAIT_INVESTIGATION",
                    "AWAITING_OUTCOME": "WAIT_VERIFICATION", "ACTION_INITIATED": "WAIT_VERIFICATION", "ESCALATED": "REVIEW_UNACCEPTED_INVESTIGATION",
                    "NEEDS_EVIDENCE": "PROVIDE_EVIDENCE_OR_REANALYSE", "HUMAN_REVIEW": "INVESTIGATE_AND_RECORD_FINDING"}
        for state, code in expected.items():
            self.assertEqual(step_code(case(state)), code, state)
            self.assertEqual(next_step(case(state))["resolved"], state == "RESOLVED", state)
        self.assertEqual(step_code(case("SOMETHING_NEW")), "INVESTIGATE_AND_RECORD_FINDING")     # Unknown: a person, never automatic.
        # The five states an operator sees are told apart.
        codes = [step_code(case("HUMAN_REVIEW")), step_code(case("ESCALATED")), step_code(case("AWAITING_APPROVAL", approvable=True)),
                 step_code(case("AWAITING_OUTCOME")), step_code(case("RESOLVED"))]
        self.assertEqual(len(set(codes)), 5)

    def test_a_case_waiting_to_be_investigated_says_so_and_does_not_claim_one_is_running(self):
        for state in ("OPEN", "REOPENED"):
            step = next_step(case(state))
            self.assertEqual((step["code"], step["actor"]), ("START_INVESTIGATION", "operator"), state)
            self.assertIn("Click Investigate now", step["text_en"])
            self.assertNotIn("to finish", step["text_en"])
        self.assertIn("to finish", next_step(case("INVESTIGATING"))["text_en"])

    def test_approval_is_offered_only_when_the_recorded_approval_check_allows_it(self):
        self.assertEqual(step_code(case("AWAITING_APPROVAL", approvable=True)), "APPROVE_OR_REJECT")
        self.assertEqual(step_code(case("AWAITING_APPROVAL", approvable=False)), "INVESTIGATE_AND_RECORD_FINDING")
        self.assertEqual(step_code(case("HUMAN_REVIEW", approvable=True)), "APPROVE_EVIDENCE_REQUEST_OR_INVESTIGATE")
        self.assertEqual(step_code(case("HUMAN_REVIEW", approvable=False)), "INVESTIGATE_AND_RECORD_FINDING")
        self.assertEqual(step_code(case("ESCALATED", approvable=True)), "REVIEW_UNACCEPTED_INVESTIGATION")   # Never an approval prompt.

    def test_an_already_verified_request_is_not_offered_again_as_the_next_step(self):
        executions = [{"entity_id": "E1", "action_type": "REQUEST_REWEIGH", "authority": "AUTO_POLICY", "status": "ACKNOWLEDGED"}]
        verified = {"execution_id": "E1", "verification_status": "VERIFIED", "success": True, "outcome_type": "weight_remeasured", "exception_cleared": True}
        step = next_step(case("HUMAN_REVIEW", approvable=True, action="REQUEST_REWEIGH", executions=executions, outcome=verified))
        self.assertEqual((step["code"], step["actor"], step["resolved"]), ("REVIEW_VERIFIED_RESULT_AND_RECORD_FINDING", "operator", False))
        self.assertIn("already carried out and independently verified", step["text_en"])
        self.assertIn("not closed", step["text_en"])
        # A failed result, another action, or no result yet leaves the approval offer as it was.
        for outcome, action in (({**verified, "success": False}, "REQUEST_REWEIGH"), (verified, "REQUEST_RESCAN"), (None, "REQUEST_REWEIGH")):
            self.assertEqual(step_code(case("HUMAN_REVIEW", approvable=True, action=action, executions=executions, outcome=outcome)),
                             "APPROVE_EVIDENCE_REQUEST_OR_INVESTIGATE")

    def test_the_step_names_who_acts_and_carries_both_languages_and_the_action(self):
        step = next_step(case("HUMAN_REVIEW", approvable=True, action="REQUEST_DEVICE_SYNC"))
        self.assertEqual(step["actor"], "operator")
        self.assertIn("the device sync request", step["text_en"])
        self.assertTrue(step["text_ar"])
        self.assertIn("will not close the case", step["text_en"])
        waiting = next_step(case("AWAITING_OUTCOME", approvable=False, action="REQUEST_RESCAN", executions=[{"entity_id": "E1", "action_type": "REQUEST_HUB_CHECK"}]))
        self.assertEqual(waiting["actor"], "system")
        self.assertIn("The facility check request was sent", waiting["text_en"])       # The action that was sent, not the recommendation's name.
        for code, (actor, english, arabic) in STEPS.items():
            self.assertIn(actor, ("none", "system", "operator"), code)
            self.assertTrue(english and arabic, code)

    def test_the_blocker_and_missing_evidence_are_the_recorded_ones(self):
        step = next_step(case("ESCALATED", approvable=False, unaccepted_investigation={"missing_evidence": ["a second read of the label"]}))
        self.assertEqual((step["blocked_by"]["rule_id"], step["blocked_by"]["review_verdict"], step["blocked_by"]["review_feedback"]),
                         ("AUTH-16-review-rejected", "REVISE", "Not supported."))
        self.assertEqual(step["blocked_by"]["approval_rule"], "AUTH-19-operator-approved")
        self.assertEqual(step["missing_evidence"], ["a second read of the label"])
        self.assertEqual(next_step(case("HUMAN_REVIEW", missing_evidence=["the depot scan"]))["missing_evidence"], ["the depot scan"])
        self.assertIsNone(next_step(case("RESOLVED"))["blocked_by"])

    def test_attempted_actions_carry_only_the_outcome_recorded_for_them(self):
        executions = [{"entity_id": "E2", "action_type": "REQUEST_DEVICE_SYNC", "authority": "OPERATOR_APPROVAL", "status": "ACKNOWLEDGED"},
                      {"entity_id": "E1", "action_type": "INITIATE_CUSTODY_RECONCILIATION", "authority": "AUTO_POLICY", "status": "ACKNOWLEDGED"}]
        outcome = {"execution_id": "E1", "verification_status": "VERIFIED", "success": False, "outcome_type": "parcel_not_found",
                   "exception_cleared": False, "reason": "Not found."}
        rows = next_step(case("HUMAN_REVIEW", approvable=False, executions=executions, outcome=outcome))["attempted"]
        self.assertEqual([(r["action_type"], r["status"], r["success"], r["outcome_type"]) for r in rows],
                         [("REQUEST_DEVICE_SYNC", "ACKNOWLEDGED", None, None), ("INITIATE_CUSTODY_RECONCILIATION", "ACKNOWLEDGED", False, "parcel_not_found")])
        self.assertEqual(next_step(case("ESCALATED"))["attempted"], [])
        # A failed action never reads as resolved.
        self.assertFalse(next_step(case("HUMAN_REVIEW", approvable=False, executions=executions, outcome=outcome))["resolved"])


if __name__ == "__main__":
    unittest.main()
