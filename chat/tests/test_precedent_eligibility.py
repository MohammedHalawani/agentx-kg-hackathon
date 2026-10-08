"""Pending and malformed outcomes never become observed historical evidence."""
import unittest
from unittest.mock import patch

from llm.pipeline import recommender, retrieve, rules
from scripts import embed_backfill_shipments as backfill


def precedent(fid, success, score=0.9):
    return {"failure_id": fid, "resolution_id": "RES-" + fid, "action": "contact",
            "success": success, "score": score}


class PrecedentEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.rows = [precedent("observed-win", True), precedent("observed-fail", False),
                     precedent("pending", None), precedent("string", "false"),
                     precedent("integer", 1), precedent("low-score", True, 0.5)]

    def test_vector_requires_observed_boolean_outcome_and_similarity(self):
        with patch.object(retrieve, "_embed", return_value=[0.0]), \
             patch.object(retrieve, "_read", return_value=self.rows):
            rows = retrieve.vector_search("symptom complaint", exclude_failure_id="observed-win")
        self.assertEqual([r["failure_id"] for r in rows], ["observed-fail"])
        self.assertIn("o.success IN [true, false]", retrieve._VECTOR)

    def test_graph_keeps_failed_observations_and_excludes_pending(self):
        with patch.object(retrieve, "_read", return_value=self.rows):
            rows = retrieve.graph_traversal({"city": "test"}, exclude_failure_id="low-score")
        self.assertEqual([r["failure_id"] for r in rows], ["observed-win", "observed-fail"])
        self.assertIn("o.success IN [true, false]", retrieve._GRAPH)

    def test_success_rate_counts_only_observed_outcomes(self):
        stats = rules.action_success_rate(self.rows[:5])
        self.assertEqual(stats["contact"], {"tried": 2, "succeeded": 1, "rate": 0.5})
        self.assertIn("1/2", rules.precedent_strength(self.rows[:5])["detail"])
        self.assertIn("No comparable", rules.precedent_strength(self.rows[2:5])["detail"])

    def test_pending_only_second_retrieval_cannot_support_citation(self):
        state = {"complaint_text": "test", "context": {}, "classification": {}}
        # Malformed/private extra context cannot turn a pending row into a citation.
        with patch.object(recommender, "second_retrieval", return_value=[self.rows[2]]), \
             patch.object(recommender._llm, "ask_json", return_value={
                 "action": "contact", "grounded_in": ["RES-pending"], "rationale": "Summary"}):
            rec = recommender.recommend(state)
        self.assertEqual(rec["grounded_in"], [])
        self.assertEqual(rec["grounded_cases"], [])
        self.assertEqual(rec["candidates"], [])

    def test_backfill_selection_and_write_recheck_observed_outcome(self):
        class Driver:
            def __init__(self):
                self.calls = []
            def execute_query(self, query, **kwargs):
                self.calls.append((query, kwargs))
                return [], None, None
        driver = Driver()
        with patch.object(backfill, "get_driver", return_value=driver):
            backfill.fetch_pending(False)
            backfill.fetch_pending(True)
            backfill.write_embeddings(["observed-win"], [[0.0]])
        self.assertIn("AND f.embedding IS NULL", driver.calls[0][0])
        self.assertNotIn("AND f.embedding IS NULL", driver.calls[1][0])
        for query, kwargs in driver.calls:
            self.assertIn("o.success IN [true, false]", query)
            self.assertEqual(kwargs["database_"], backfill.config.SHIPMENT_DATABASE)


if __name__ == "__main__":
    unittest.main()
