"""Deterministic AFL routing proof with real stage/rule code, offline I/O only.

This proves orchestration, not live model performance. Scripted final JSON simulates a bad
recommendation; rejection itself comes from the unmodified production reviewer hard rules.
"""
from contextlib import ExitStack
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from llm.pipeline import _llm, classifier, extract, graph, recommender, retrieve, reviewer, rules, writeback

COMPLAINT = "Shipment SHP-9001 had two failed attempts; the current recipient address differs from the order address."
RETRY = "إعادة جدولة التسليم في يوم آخر"
CORRECTED = "تأكيد العنوان الصحيح مع العميل وإعادة التوجيه"


def fixture_context():
    return {
        "live_failure_id": "FR-FIXTURE-1",
        "local_subgraph": {
            "shipment": {"shipment_id": "SHP-9001", "status": "DELIVERY_FAILED"},
            "live_failure": {"failure_id": "FR-FIXTURE-1", "category": "address_conflict"},
            "policy": {"policy_id": "POL-FIXTURE", "retry_limit": 2, "sla_days": 3},
            "addresses": [{"address_id": "ADDR-OLD", "version": 1}, {"address_id": "ADDR-CURRENT", "version": 2}],
            "events": [{"event_type": "CREATED", "timestamp": "2026-10-01T08:00:00"},
                       {"event_type": "DELIVERY_ATTEMPT", "timestamp": "2026-10-04T08:00:00"},
                       {"event_type": "DELIVERY_ATTEMPT", "timestamp": "2026-10-05T08:00:00"}],
        },
        "similar_cases": [
            {"failure_id": "FR-HISTORY-1", "resolution_id": "RES-HISTORY-1", "category": "recipient_unavailable", "action": RETRY, "success": True},
            {"failure_id": "FR-HISTORY-2", "resolution_id": "RES-HISTORY-2", "category": "address_conflict", "action": CORRECTED, "success": True},
        ],
    }


class ScriptedFinalModel:
    def __init__(self, mode="corrected"):
        self.mode = mode
        self.classifications = 0
        self.recommendations = 0
        self.review_calls = 0
        self.classifier_prompts = []

    def invoke(self, messages):
        system, prompt = messages[0].content, messages[1].content
        if system == extract._SYSTEM:
            response = {"city": None, "district": None, "courier": None, "category_hint": None}
        elif system == classifier._SYSTEM:
            self.classifications += 1
            self.classifier_prompts.append(prompt)
            category = "address_conflict" if self.mode == "corrected" and self.classifications > 1 else "recipient_unavailable"
            response = {"category": category, "confidence": 0.8, "priority": "high", "rationale": "Address versions and failed attempts require correction."}
        elif system == recommender._SYSTEM:
            self.recommendations += 1
            corrected = self.mode == "corrected" and self.recommendations > 1
            response = {"action": CORRECTED if corrected or self.mode in ("uncited", "mismatched") else RETRY,
                        "grounded_in": ([] if self.mode == "uncited" else
                                        ["RES-HISTORY-2" if corrected or self.mode == "mismatched" else "RES-HISTORY-1"]),
                        "rationale": "Change approach after exhausted attempts; cite a verified historical outcome."}
        elif system == reviewer._SYSTEM:
            self.review_calls += 1
            response = {"verdict": "accept", "score": 0.9, "reason": "Corrected action avoids another retry and cites matching precedent."}
        else:
            raise AssertionError("Unexpected stage prompt")
        # Real ask_json normalization stays in the path; deliberately irrelevant extra
        # private metadata verifies it cannot contaminate the state-machine artifact.
        response["reasoning"] = "PRIVATE FIXTURE METADATA"
        return SimpleNamespace(content=[{"type": "thinking", "text": "PRIVATE FIXTURE METADATA"},
                                        {"type": "text", "text": json.dumps(response, ensure_ascii=False)}])


def run_fixture(mode="corrected", missing_grounding=False, write_result="RES-FIXTURE-ACCEPTED"):
    context = fixture_context()
    if missing_grounding:
        context["similar_cases"] = []
    scripted = ScriptedFinalModel(mode)
    graph.build_pipeline.cache_clear()
    with ExitStack() as stack:
        stack.enter_context(patch.object(_llm, "model", return_value=scripted))
        stack.enter_context(patch.object(retrieve, "retrieve_context", return_value=context))
        stack.enter_context(patch.object(retrieve, "vector_search", return_value=context["similar_cases"]))
        stack.enter_context(patch.object(graph, "_case_file", return_value=None))
        resolution = stack.enter_context(patch.object(writeback, "write_resolution", return_value=write_result))
        escalation = stack.enter_context(patch.object(writeback, "write_escalation", return_value={"escalation_id": "ESC-FIXTURE", "team": "human_review"}))
        captured = []
        original_classify = classifier.classify
        def classify_with_capture(state):
            captured.append(deepcopy(state))
            return original_classify(state)
        stack.enter_context(patch.object(classifier, "classify", side_effect=classify_with_capture))
        events = list(graph.stream_complaint(COMPLAINT))
        result = {"events": events, "model": scripted, "classification_inputs": captured,
                  "resolution_calls": resolution.call_count, "escalation_calls": escalation.call_count}
    graph.build_pipeline.cache_clear()
    return result


def proof_artifact(result):
    events = result["events"]
    stages = [payload for kind, payload in events if kind == "stage"]
    classifications = [s["detail"] for s in stages if s["stage"] == "classify"]
    recommendations = [s["detail"] for s in stages if s["stage"] == "recommend"]
    reviews = [s["detail"] for s in stages if s["stage"] == "review"]
    feedback = result["classification_inputs"][1]["review_notes"] if len(classifications) > 1 else []
    return {
        "proof_type": "deterministic_fixture_real_compiled_langgraph_and_reviewer_rules",
        "external_io": "mocked final model JSON, read retrieval, case file, and writeback; no DB writes",
        "live_model_rejection": False,
        "complaint": COMPLAINT,
        "policy": fixture_context()["local_subgraph"]["policy"],
        "business_rule_findings": rules.evaluate(fixture_context()["local_subgraph"], fixture_context()["similar_cases"]),
        "initial_diagnosis": classifications[0] if classifications else None,
        "initial_recommendation": recommendations[0] if recommendations else None,
        "initial_review": reviews[0] if reviews else None,
        "feedback": feedback,
        "feedback_in_second_classifier_prompt": bool(feedback) and all(n in result["model"].classifier_prompts[1] for n in feedback),
        "second_diagnosis": classifications[1] if len(classifications) > 1 else None,
        "second_recommendation": recommendations[1] if len(recommendations) > 1 else None,
        "stages": stages,
        "final": events[-1][1],
        "resolution_write_mock_calls": result["resolution_calls"],
        "escalation_write_mock_calls": result["escalation_calls"],
        "observed_operational_success": None,
    }


class AFLStateMachineTests(unittest.TestCase):
    def test_hard_reject_feedback_reclassify_then_accept(self):
        result = run_fixture()
        proof = proof_artifact(result)
        self.assertEqual([s["stage"] for s in proof["stages"]],
                         ["extract", "retrieve", "classify", "recommend", "review", "classify", "recommend", "review", "writeback"])
        self.assertEqual(proof["initial_diagnosis"]["category"], "recipient_unavailable")
        self.assertEqual(proof["initial_recommendation"]["action"], RETRY)
        self.assertEqual(proof["initial_review"]["verdict"], "reject")
        self.assertIn("Retry budget exhausted", proof["initial_review"]["reason"])
        self.assertTrue(proof["feedback_in_second_classifier_prompt"])
        self.assertEqual(proof["second_diagnosis"]["category"], "address_conflict")
        self.assertEqual(proof["second_recommendation"]["action"], CORRECTED)
        self.assertEqual(proof["final"]["review"]["verdict"], "accept")
        self.assertEqual(proof["final"]["loops"], 1)
        self.assertEqual(result["model"].review_calls, 1)  # Initial hard reject never asked a model.
        self.assertEqual(result["resolution_calls"], 1)
        self.assertEqual(result["escalation_calls"], 0)
        self.assertEqual(result["classification_inputs"][1]["attempted_actions"], [RETRY])
        self.assertNotIn("PRIVATE", json.dumps(proof))
        self.assertIsNone(proof["observed_operational_success"])

    def test_persistent_retry_reject_is_bounded_and_escalates(self):
        result = run_fixture("perpetual_retry")
        final = result["events"][-1][1]
        self.assertEqual(final["loops"], graph.MAX_LOOPS)
        self.assertEqual(result["model"].classifications, graph.MAX_LOOPS)
        self.assertEqual(result["model"].recommendations, graph.MAX_LOOPS)
        self.assertEqual(result["model"].review_calls, 0)
        self.assertEqual(final["disposition"], "escalate")
        self.assertIsNone(final["resolution_id"])
        self.assertEqual(result["resolution_calls"], 0)
        self.assertEqual(result["escalation_calls"], 1)
        self.assertEqual(len(result["classification_inputs"][1]["review_notes"]), 1)

    def test_no_precedent_short_circuits_before_classification(self):
        result = run_fixture(missing_grounding=True)
        stages = [payload["stage"] for kind, payload in result["events"] if kind == "stage"]
        self.assertEqual(stages, ["extract", "retrieve", "escalate"])
        self.assertEqual(result["model"].classifications, 0)
        self.assertEqual(result["model"].recommendations, 0)
        self.assertEqual(result["resolution_calls"], 0)
        self.assertEqual(result["events"][-1][1]["disposition"], "escalate")

    def test_uncited_action_hard_rejects_without_reviewer_model(self):
        result = run_fixture("uncited")
        reviews = [p["detail"] for k, p in result["events"] if k == "stage" and p["stage"] == "review"]
        self.assertTrue(all(r["verdict"] == "reject" and "cites none" in r["reason"] for r in reviews))
        self.assertEqual(result["model"].review_calls, 0)
        self.assertEqual(result["resolution_calls"], 0)

    def test_all_citations_wrong_category_reject_without_reviewer_model(self):
        result = run_fixture("mismatched")
        reviews = [p["detail"] for k, p in result["events"] if k == "stage" and p["stage"] == "review"]
        self.assertTrue(all(r["verdict"] == "reject" and "every cited case" in r["reason"] for r in reviews))
        self.assertEqual(result["model"].review_calls, 0)
        self.assertEqual(result["resolution_calls"], 0)

    def test_accepted_but_write_unavailable_escalates_without_false_success(self):
        result = run_fixture(write_result=None)
        final = result["events"][-1][1]
        self.assertEqual(final["review"]["verdict"], "accept")
        self.assertEqual(final["disposition"], "escalate")
        self.assertIsNone(final["resolution_id"])
        self.assertEqual(result["escalation_calls"], 1)


if __name__ == "__main__":
    unittest.main()
