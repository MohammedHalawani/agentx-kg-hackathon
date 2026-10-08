"""Regressions for accepted V1 output facts and the operator/persistence boundary."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from llm.pipeline import graph, operator_output, writeback


def fixture():
    return {"context": {"local_subgraph": {
        "shipment": {"shipment_id": "SHP-TEST"}, "events": [
            {"event_type": "CREATED", "timestamp": "2026-01-01T00:00:00"},
            {"event_type": "DELIVERY_ATTEMPT", "timestamp": "2026-01-02T00:00:00"},
            {"event_type": "DELIVERY_ATTEMPT", "timestamp": "2026-01-03T00:00:00"}],
        "policy": {"retry_limit": 3, "sla_days": 2}}},
        "classification": {"category": "address_conflict", "confidence": .9, "priority": "high",
                           "rationale": "Invented exhaustion after 2 of3 attempts."},
        "recommendation": {"action": "verify", "rationale": "five same-action cases succeeded",
                           "grounded_cases": [{"resolution_id": "RES-1", "action": "verify", "success": True},
                                              {"resolution_id": "RES-2", "action": "different", "success": True}]},
        "review": {"verdict": "accept", "score": .9, "reason": "2/3=80%; already delivered."}}


class OperatorOutputTests(unittest.TestCase):
    def test_attempt_budget_and_sla_equality_come_from_events(self):
        text = operator_output.classification_summary(fixture(), fixture()["classification"])
        self.assertIn("2 of 3 permitted (budget remains)", text)
        self.assertIn("2.0 days against 2-day policy SLA (within SLA)", text)
        self.assertIn("Model hypothesis", text)
        self.assertNotIn("Invented", text)

    def test_missing_attempt_data_remains_unknown(self):
        state = fixture()
        del state["context"]["local_subgraph"]["events"]
        self.assertEqual(operator_output.recorded_facts(state), "Recorded attempt history unavailable.")

    def test_action_statistics_count_only_unique_observed_matching_citations(self):
        state = fixture()
        rows = state["recommendation"]["grounded_cases"]
        rows.extend([dict(rows[0]), {"resolution_id": "RES-PENDING", "action": "verify", "success": None}])
        text = operator_output.recommendation_summary(state, state["recommendation"])
        self.assertIn("histories: 2; exact-action matches: 1", text)
        self.assertIn("1/1 succeeded (100.0%)", text)
        self.assertNotIn("five", text)
        self.assertIn("unconfirmed", text)

    def test_two_of_three_is_not_eighty_percent(self):
        state = fixture()
        state["recommendation"]["grounded_cases"] = [
            {"resolution_id": str(i), "action": "verify", "success": i < 2} for i in range(3)]
        text = operator_output.recommendation_summary(state, state["recommendation"])
        self.assertIn("2/3 succeeded (66.7%)", text)

    def test_acceptance_and_rejection_do_not_certify_facts_or_invent_authority(self):
        state = fixture()
        text = operator_output.review_summary(state, state["review"])
        self.assertNotIn("80%", text)
        self.assertNotIn("already delivered", text)
        self.assertIn("does not establish correctness", text)
        state["review"] = {"verdict": "reject", "reason": "Cancel and refund; all redirects illegal."}
        text = operator_output.review_summary(state, state["review"])
        self.assertNotIn("refund", text)
        self.assertIn("not an authoritative rule", text)

    def test_stream_stage_and_final_use_same_factual_boundary(self):
        state = fixture()
        fake = SimpleNamespace(stream=lambda initial, **kwargs: iter([
            {"retrieve": {"context": state["context"]}},
            {"classify": {"classification": state["classification"]}},
            {"recommend": {"recommendation": state["recommendation"]}},
            {"review": {"review": state["review"]}}]))
        with patch.object(graph, "build_pipeline", return_value=fake):
            events = list(graph.stream_complaint("reported discrepancy"))
        serialized = json.dumps(events)
        self.assertNotIn("80%", serialized)
        self.assertNotIn("five same-action", serialized)
        final = events[-1][1]
        for stage, field in (("classify", "classification"), ("recommend", "recommendation"), ("review", "review")):
            payload = next(value for kind, value in events if kind == "stage" and value["stage"] == stage)
            self.assertEqual(payload["detail"], final[field])

    def test_escalation_persistence_uses_factual_summary_not_model_rule(self):
        state = fixture()
        state["review"] = {"verdict": "reject", "reason": "cancel refund"}
        self.assertNotIn("refund", writeback._escalation_reason(state))


if __name__ == "__main__":
    unittest.main()
