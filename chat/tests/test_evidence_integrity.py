"""Narrow recorded attempt-count fidelity guard, including observed live failures."""
import json
import unittest
from unittest.mock import patch

from llm.pipeline import _llm, classifier, reviewer
from test_afl_state_machine import fixture_context, CORRECTED, ScriptedFinalModel, run_fixture


def state_for(rationale):
    return {"complaint_text": "Repeated unsuccessful delivery attempts.",
            "context": fixture_context(), "review_notes": [],
            "classification": {"category": "address_conflict", "confidence": 0.8,
                               "priority": "high", "rationale": rationale},
            "recommendation": {"action": CORRECTED, "grounded_in": ["RES-HISTORY-2"],
                               "grounded_cases": [{"category": "address_conflict", "resolution_id": "RES-HISTORY-2"}]}}


class EvidenceIntegrityTests(unittest.TestCase):
    def test_authoritative_prompt_counts_come_from_local_events_and_policy(self):
        state = state_for("Address conflict")
        prompt = classifier._prompt(state)
        facts = json.loads(prompt.split("AUTHORITATIVE RECORDED EVENT FACTS:\n")[1].split("\n\n")[0])
        self.assertEqual(facts["delivery_attempts"], 2)
        self.assertEqual(facts["recorded_event_count"], 3)
        self.assertEqual(facts["policy_retry_limit"], 2)
        self.assertEqual(facts["recorded_timeline_span_days"], 4.0)
        self.assertIn("Event.event_type", facts["recorded_sources"]["delivery_attempts"])
        self.assertIn("Never invent", classifier._SYSTEM)

    def test_observed_invented_four_and_three_attempts_reject_before_model(self):
        for rationale in (
            "Multiple failed attempts (four) confirm the issue persists.",
            "The event history shows three consecutive failed attempts exceeding the retry limit.",
            "The shipment had four failed attempts.",
            "The shipment has 4 delivery attempts.",
            "The shipment has ٤ delivery attempts.",
            "سجلت الشحنة ٣ محاولات تسليم فاشلة.",
            "محاولات التسليم (٤) في سجل الشحنة.",
        ):
            with self.subTest(rationale=rationale), patch.object(_llm, "ask_json") as model:
                result = reviewer.review(state_for(rationale))
                self.assertEqual(result["verdict"], "reject")
                self.assertIn("2 recorded DELIVERY_ATTEMPT", result["reason"])
                model.assert_not_called()

    def test_truthful_uncertain_or_proposed_counts_do_not_hard_reject(self):
        for rationale in (
            "There are two recorded delivery attempts.",
            "The shipment had two failed attempts.",
            "There was one failed attempt and another attempt with an unknown outcome.",
            "There may have been four failed attempts.",
            "At least two delivery attempts are recorded.",
            "The policy allows three delivery attempts.",
            "Recommend three delivery attempts next week.",
            "Three delivery attempts should be scheduled after customer confirmation.",
            "The customer reports four failed attempts, which needs verification.",
            "Three or four delivery attempts were mentioned.",
            "3–4 delivery attempts were mentioned.",
            "Historical cases had four failed attempts.",
            "الشحنة لها ٢ محاولات تسليم.",
            "ربما كانت هناك ٣ محاولات تسليم.",
            "Repeated unsuccessful delivery attempts require address confirmation.",
        ):
            with self.subTest(rationale=rationale):
                self.assertIsNone(reviewer._attempt_count_contradiction(state_for(rationale)))

    def test_proposed_action_count_is_not_treated_as_past_evidence(self):
        state = state_for("Two recorded delivery attempts require customer address confirmation.")
        state["recommendation"]["rationale"] = "Prepare three delivery attempts in a future plan."
        self.assertIsNone(reviewer._attempt_count_contradiction(state))

    def test_missing_operational_events_does_not_invent_zero(self):
        state = state_for("Four failed attempts.")
        del state["context"]["local_subgraph"]["events"]
        self.assertIsNone(reviewer._attempt_count_contradiction(state))

    def test_exact_feedback_reaches_reconsideration_prompt(self):
        state = state_for("Three consecutive failed attempts.")
        result = reviewer.review(state)
        state["review_notes"] = [result["reason"]]
        self.assertIn(result["reason"], classifier._prompt(state))

    def test_truthful_final_summary_still_reaches_model_review(self):
        with patch.object(_llm, "ask_json", return_value={"verdict": "accept", "score": 0.9, "reason": "Supported by evidence."}) as model:
            result = reviewer.review(state_for("Two recorded delivery attempts require address correction."))
        self.assertEqual(result["verdict"], "accept")
        model.assert_called_once()

    def test_exhausted_retry_guard_handles_english_capitalization_and_hyphen(self):
        for action in ("Retry delivery", "Redeliver the shipment", "Reschedule delivery", "Re-deliver the parcel"):
            with self.subTest(action=action), patch.object(_llm, "ask_json") as model:
                state = state_for("Two recorded delivery attempts require a changed approach.")
                state["recommendation"]["action"] = action
                result = reviewer.review(state)
                self.assertEqual(result["verdict"], "reject")
                self.assertIn("Retry budget exhausted", result["reason"])
                model.assert_not_called()

    def test_redirect_is_not_mistaken_for_redelivery(self):
        state = state_for("Two recorded delivery attempts require address correction.")
        self.assertEqual(reviewer._hard_rejects(state, []), [])

    def test_contradicted_count_retries_through_real_compiled_graph(self):
        original = ScriptedFinalModel.invoke
        def responses(model, messages):
            response = original(model, messages)
            payload = json.loads(response.content[-1]["text"])
            if messages[0].content == classifier._SYSTEM:
                payload["category"] = "address_conflict"
                payload["rationale"] = ("Three recorded delivery attempts." if model.classifications == 1
                                        else "Two recorded delivery attempts require address correction.")
            elif "resolution planner" in messages[0].content:
                payload["action"] = CORRECTED
                payload["grounded_in"] = ["RES-HISTORY-2"]
            response.content[-1]["text"] = json.dumps(payload)
            return response
        with patch.object(ScriptedFinalModel, "invoke", responses):
            result = run_fixture()
        reviews = [p["detail"] for k, p in result["events"] if k == "stage" and p["stage"] == "review"]
        self.assertEqual(reviews[0]["verdict"], "reject")
        self.assertIn("claims 3", reviews[0]["reason"])
        self.assertIn(reviews[0]["reason"], result["model"].classifier_prompts[1])
        self.assertEqual(reviews[1]["verdict"], "accept")
        self.assertEqual(result["model"].review_calls, 1)
        self.assertEqual(result["resolution_calls"], 1)


if __name__ == "__main__":
    unittest.main()
