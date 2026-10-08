"""Offline fairness, I/O fences, failure accounting and resume contract tests."""
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage, SystemMessage
from neo4j import RoutingControl

from scripts import evaluate_gpt_oss_v1 as bench
from llm.pipeline import classifier, graph, retrieve, writeback
from test_afl_state_machine import fixture_context, ScriptedFinalModel


def corpus_fixture():
    corpus = []
    for index, category in enumerate(bench.CATEGORIES):
        for number in range(7):
            sid = f"SHP-{1000 + index * 10 + number}"
            corpus.append({"shipment_id": sid, "failure_id": f"FR-{sid}",
                           "category": ("escalation:" if number == 0 else "") + category,
                           "city": "الرياض", "district": "حي الاختبار", "resolution_id": f"RES-{sid}",
                           "action": "SEEDED GOLD ACTION", "success": True})
        # A second observed history on the same escalation shipment, sharing its action.
        corpus.append({**corpus[-7], "failure_id": f"FR-SIBLING-{index}"})
    return corpus


def prepare_fixture(directory):
    corpus = corpus_fixture()
    membership = [{"shipment_id": r["shipment_id"], "failure_id": r["failure_id"]} for r in corpus]
    driver = SimpleNamespace(execute_query=lambda query, **kwargs: (
        corpus if query == bench._CORPUS_QUERY else membership, None, None))
    all_history = [{**r, "score": 0.85, "description": "Synthetic precedent"} for r in corpus]
    def local(extracted):
        context = fixture_context()["local_subgraph"]
        context["shipment"]["shipment_id"] = extracted["shipment_id"]
        context["shipment"]["status"] = "DELIVERED"
        context["live_failure"] = {"category": "OWN_GOLD_SENTINEL", "description": "OWN_GOLD_SENTINEL"}
        context["resolution"] = {"action": "OWN_GOLD_SENTINEL"}
        return context
    with patch.object(bench.config, "NEO4J_URI", "bolt://localhost:7687"), \
         patch.object(bench.config, "SHIPMENT_DATABASE", "shipments"), \
         patch.object(bench, "get_driver", return_value=driver), \
         patch.object(retrieve, "vector_search", return_value=all_history), \
         patch.object(retrieve, "graph_traversal", return_value=all_history), \
         patch.object(retrieve, "local_subgraph", side_effect=local), redirect_stdout(io.StringIO()):
        return bench.prepare(directory)


def execution_case():
    context = fixture_context()
    context["local_subgraph"] = bench.clean_local(context["local_subgraph"])
    context["live_failure_id"] = None
    return {"case_id": "case-01", "shipment_id": "SHP-9001", "language": "ar",
            "complaint": "Shipment SHP-9001 has repeated delivery difficulty.", "context": context,
            "second_pass": {cat: deepcopy(context["similar_cases"]) for cat in bench.CATEGORIES}}


class EvaluatorHarnessTests(unittest.TestCase):
    def test_balanced_unique_selection_and_language_schedule(self):
        rows = bench.select_cases(corpus_fixture())
        self.assertEqual(len({r["shipment_id"] for r in rows}), 30)
        self.assertEqual(Counter(bench.base(r["category"]) for r in rows), {cat: 5 for cat in bench.CATEGORIES})
        for cat in bench.CATEGORIES:
            subset = [(row, slot // 6) for slot, row in enumerate(rows) if bench.base(row["category"]) == cat]
            self.assertEqual(sum(row["category"].startswith("escalation:") for row, _ in subset), 1)
            self.assertEqual(Counter(bench.complaint_for(row, slot)[1] for row, slot in subset), {"ar": 3, "en": 2})

    def test_prepare_excludes_all_siblings_from_first_second_and_plausibility(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            manifest = prepare_fixture(directory)
            runtime, gold = bench.load_json(directory / "runtime_inputs.json"), bench.load_json(directory / "gold.json")
            self.assertEqual(manifest["escalation_seed_cases"], 6)
            self.assertNotIn("OWN_GOLD_SENTINEL", bench.encode(runtime))
            for case in runtime["cases"]:
                forbidden = set(gold[case["case_id"]]["holdout_failure_ids"])
                banks = [case["context"]["similar_cases"], *case["second_pass"].values()]
                self.assertFalse(any(r["failure_id"] in forbidden for bank in banks for r in bank))
                self.assertFalse(any(r["failure_id"] in forbidden for r in gold[case["case_id"]]["plausibility_history"]))
                self.assertNotIn("status", case["context"]["local_subgraph"]["shipment"])
                self.assertEqual(len(case["context"]["local_subgraph"]["events"]), 3)

    def test_validator_rejects_missing_sibling_exclusion_and_wrong_language_group(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            prepare_fixture(directory)
            runtime, gold = bench.load_json(directory / "runtime_inputs.json"), bench.load_json(directory / "gold.json")
            membership = bench.load_json(directory / "membership_snapshot.json")
            first = runtime["cases"][0]
            self.assertEqual(len(gold[first["case_id"]]["holdout_failure_ids"]), 2)
            gold[first["case_id"]]["holdout_failure_ids"].pop()
            with self.assertRaises(ValueError):
                bench.validate_runtime(runtime, gold, membership)
            gold = bench.load_json(directory / "gold.json")
            runtime["cases"][0]["language"], runtime["cases"][19]["language"] = "en", "ar"
            with self.assertRaises(ValueError):
                bench.validate_runtime(runtime, gold, membership)

    def test_read_preparation_queries_use_read_routing_only(self):
        corpus = corpus_fixture()
        membership = [{"shipment_id": r["shipment_id"], "failure_id": r["failure_id"]} for r in corpus]
        def execute(query, **kwargs):
            self.assertEqual(kwargs["routing_"], RoutingControl.READ)
            self.assertEqual(kwargs["database_"], "shipments")
            self.assertFalse(any(word in query.upper().split() for word in ("CREATE", "MERGE", "DELETE", "SET", "REMOVE")))
            return corpus if query == bench._CORPUS_QUERY else membership, None, None
        with TemporaryDirectory() as temp, patch.object(bench.config, "NEO4J_URI", "bolt://localhost:7687"), \
             patch.object(bench.config, "SHIPMENT_DATABASE", "shipments"), \
             patch.object(bench, "get_driver", return_value=SimpleNamespace(execute_query=execute)), \
             patch.object(retrieve, "vector_search", return_value=[]), patch.object(retrieve, "graph_traversal", return_value=[]), \
             patch.object(retrieve, "local_subgraph", return_value={}), redirect_stdout(io.StringIO()):
            bench.prepare(Path(temp))

    def test_seeded_eligibility_requires_seeded_resolution_not_only_failure(self):
        rows = [{"failure_id": "FR-1", "resolution_id": "RES-SEED", "success": True},
                {"failure_id": "FR-1", "resolution_id": "RES-AGENT", "success": True},
                {"failure_id": "FR-2", "resolution_id": "RES-2", "success": None}]
        filtered = bench.filter_precedent(rows, set(), {("FR-1", "RES-SEED")})
        self.assertEqual(filtered, [rows[0]])

    def test_real_graph_dry_writeback_and_private_output_suppression(self):
        graph.build_pipeline.cache_clear()
        with patch.object(bench, "get_driver", side_effect=AssertionError("No live driver")) as driver:
            result = bench.evaluate_case(execution_case(), ScriptedFinalModel())
        self.assertEqual(result["dry_disposition"], "accepted_recommendation")
        self.assertFalse(result["writeback_executed"])
        self.assertIsNone(result["observed_success"])
        self.assertEqual(result["final"]["resolution_id"], "DRY-RECOMMENDATION-NOT-PERSISTED")
        self.assertNotIn("PRIVATE", bench.encode(result))
        driver.assert_not_called()
        graph.build_pipeline.cache_clear()

    def test_frozen_second_pass_uses_predicted_category_not_gold_or_rationale(self):
        case = execution_case()
        bank = {cat: [{"failure_id": f"OTHER-{cat}", "resolution_id": f"BANK-{cat}",
                       "category": cat, "action": "تأكيد العنوان الصحيح", "success": True}] for cat in bench.CATEGORIES}
        case["second_pass"] = bank
        seen = []
        original = bench.recommender.recommend
        def recommend(state):
            actual = bench.recommender.second_retrieval(state)
            seen.append((state["classification"]["category"], actual[0]["category"]))
            return original(state)
        with patch.object(bench.recommender, "recommend", side_effect=recommend):
            bench.evaluate_case(case, ScriptedFinalModel())
        self.assertTrue(seen)
        self.assertTrue(all(predicted == bank_category for predicted, bank_category in seen))

    def test_extraction_does_not_control_frozen_evidence_or_hide_its_error(self):
        model = ScriptedFinalModel()
        original = model.invoke
        def invoke(messages):
            result = original(messages)
            if messages[0].content == bench.extract._SYSTEM:
                result.content = "invalid JSON"
            return result
        case = execution_case()
        result = bench.evaluate_case(case, SimpleNamespace(invoke=invoke))
        self.assertTrue(result["calls"][0]["malformed_json"])
        self.assertIn("classify", [c["stage"] for c in result["calls"]])
        self.assertEqual(result["dry_disposition"], "accepted_recommendation")

    def test_type_only_provider_errors_have_no_raw_exception_payload(self):
        def invoke(messages):
            raise ValueError("PRIVATE PROVIDER SECRET TEXT")
        result = bench.evaluate_case(execution_case(), SimpleNamespace(invoke=invoke))
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual(result["calls"][0]["error_type"], "ValueError")
        self.assertNotIn("PRIVATE", bench.encode(result))

    def test_wrong_shape_json_metrics_and_numeric_usage_are_safe(self):
        provider = SimpleNamespace(invoke=lambda messages: SimpleNamespace(
            content=[{"type": "thinking", "text": "PRIVATE"}, {"type": "text", "text": '{"category": [], "confidence": "bad", "priority": "high", "rationale": "Summary"}'}],
            usage_metadata={"input_tokens": 12, "total_tokens": 20, "private": "SECRET"}))
        measured = bench.MeasuredModel(provider)
        measured.invoke([SystemMessage(classifier._SYSTEM), HumanMessage("Complaint")])
        self.assertFalse(measured.calls[0]["malformed_json"])
        self.assertEqual(set(measured.calls[0]["invalid_declared_fields"]), {"category", "confidence"})
        self.assertEqual(measured.calls[0]["usage"], {"input_tokens": 12, "total_tokens": 20})
        self.assertNotIn("PRIVATE", bench.encode(measured.calls))

    def test_default_category_agreement_does_not_count_as_valid_model_inference(self):
        case = execution_case()
        provider = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="invalid final JSON"))
        with redirect_stdout(io.StringIO()):
            result = bench.evaluate_case(case, provider)
        answer = {"category": "recipient_unavailable", "action": "none", "plausibility_history": [],
                  "shipment_base_causes": ["recipient_unavailable"]}
        metrics = bench.score_result(result, case, answer)
        self.assertTrue(metrics["base_cause_agreement"])
        self.assertFalse(metrics["base_cause_valid_model_agreement"])
        self.assertFalse(metrics["final_classifier_model_output_valid"])

    def test_bounded_scores_and_category_hint_normalization_are_counted(self):
        for module, payload, expected in (
            (classifier, {"category": "address_conflict", "confidence": 10, "priority": "high", "rationale": "Evidence"}, "confidence"),
            (bench.reviewer, {"verdict": "accept", "score": -2, "reason": "Evidence"}, "score"),
            (bench.extract, {"city": None, "district": None, "courier": None, "category_hint": "unsupported"}, "category_hint"),
        ):
            measured = bench.MeasuredModel(SimpleNamespace(invoke=lambda messages: SimpleNamespace(content=json.dumps(payload))))
            measured.invoke([SystemMessage(module._SYSTEM), HumanMessage("Complaint")])
            self.assertIn(expected, measured.calls[0]["invalid_declared_fields"])
            self.assertFalse(measured.calls[0]["malformed_json"])

    def test_afl_improvement_proxy_separates_first_and_final_seed_agreement(self):
        case = execution_case()
        result = bench.evaluate_case(case, ScriptedFinalModel())
        answer = {"category": "address_conflict", "action": "none", "plausibility_history": [],
                  "shipment_base_causes": ["address_conflict"]}
        metrics = bench.score_result(result, case, answer)
        self.assertFalse(metrics["first_base_cause_agreement"])
        self.assertTrue(metrics["base_cause_agreement"])
        self.assertTrue(metrics["afl_corrected_seeded_cause_miss_proxy"])
        self.assertFalse(metrics["afl_changed_seeded_cause_hit_to_miss_proxy"])

    def test_immutable_bundle_and_resume_identity_reject_changes(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            manifest = prepare_fixture(directory)
            current, runtime = bench.verify_bundle(directory)
            case = runtime["cases"][0]
            result = {"runtime_hash": manifest["runtime_hash"], "gold_hash": manifest["gold_hash"],
                      "source_hashes": manifest["source_hashes"], "provider_identity": manifest["provider_identity"],
                      "version": bench.VERSION, "model": bench.MODELS[0], "case_id": case["case_id"], "language": case["language"]}
            bench.validate_result_identity(result, manifest, case, bench.MODELS[0])
            for key in result:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    bench.validate_result_identity({**result, key: "CHANGED"}, manifest, case, bench.MODELS[0])
            with patch.object(bench, "source_hashes", return_value={}), self.assertRaises(ValueError):
                bench.verify_bundle(directory)
            with patch.object(bench.config, "LLM_API_BASE", "https://changed.invalid/v1"), self.assertRaises(ValueError):
                bench.verify_bundle(directory)
            runtime["cases"][0]["complaint"] += " changed"
            bench.save_json(directory / "runtime_inputs.json", runtime)
            with self.assertRaises(ValueError):
                bench.verify_bundle(directory)

    def test_report_includes_errors_in_planned_denominator_and_ignores_extra_files(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            prepare_fixture(directory)
            provider = SimpleNamespace(invoke=lambda messages: (_ for _ in ()).throw(ValueError("PRIVATE")))
            with patch.object(bench, "ChatLiteLLM", return_value=provider), redirect_stdout(io.StringIO()):
                bench.run(directory, maximum=2)
            bench.save_json(directory / "results" / "20b" / "case-999.json", {"unexpected": True})
            payload = bench.report(directory)
            for model in bench.MODELS:
                row = payload["models"][model]
                self.assertEqual(row["completed_cases"], 1)
                self.assertEqual(row["case_exceptions"], 1)
                self.assertEqual(row["case_diagnostics"]["exception_rate_per_planned"], 1 / 30)
                self.assertEqual(row["metrics"]["base_cause_agreement"]["planned_denominator"], 30)
                self.assertEqual(sum(sum(counts.values()) for counts in row["confusion_counts"].values()), 30)
                self.assertIsNone(row["false_acceptance_rate"])
            with patch.object(bench, "ChatLiteLLM", return_value=provider), patch.object(bench, "evaluate_case") as execute, redirect_stdout(io.StringIO()):
                bench.run(directory, maximum=0)
                execute.assert_not_called()
            stale = bench.load_json(directory / "results" / "20b" / "case-01.json")
            stale["model"] = bench.MODELS[1]
            bench.save_json(directory / "results" / "20b" / "case-01.json", stale)
            with self.assertRaises(ValueError):
                bench.report(directory)


if __name__ == "__main__":
    unittest.main()
