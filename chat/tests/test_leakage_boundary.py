"""Answer-leakage regressions. Each test fails on the pre-S1 code (fhd 1a67e22).

V1: the open FailureReason's recorded category/description reached the classifier and reviewer
prompts, and intake complaint wording was chosen per recorded category.
V2: OpsCases were seeded from dataset Case nodes derived from each shipment's whole evidence
window, carried those cause codes, and the evidence packet exposed the story's end time.
"""
import unittest
from unittest.mock import patch

from dataset_v2.contracts import Config, canonical
from dataset_v2.generate import generate
from llm.pipeline import cases, classifier, retrieve, reviewer
from operations.reasoning import public_evidence
from operations import store as store_module
from operations.store import OperationsStore
from tests.test_operations_store import Driver, Reader

SENTINEL_CATEGORY = "failed_attempt_wrong_gate"
SENTINEL_DESCRIPTION = "ANSWER-LABEL-SENTINEL wrong gate recorded by courier"


def local_with_label():
    return {"shipment": {"shipment_id": "SHP-1"}, "courier": None, "policy": {"retry_limit": 2, "sla_days": 3},
            "addresses": [], "events": [{"event_id": "E1", "event_type": "FAILED", "timestamp": "2026-01-01"}],
            "live_failure": {"failure_id": "F-1", "category": SENTINEL_CATEGORY, "description": SENTINEL_DESCRIPTION}}


class V1PromptBoundaryTests(unittest.TestCase):
    def test_local_query_projects_the_open_failure_as_an_identifier_only(self):
        live = retrieve._LOCAL.split("AS events,")[1]
        self.assertIn(".failure_id", live)
        for field in (".category", ".description"):
            self.assertNotIn(field, live)

    def test_classifier_prompt_never_contains_the_recorded_failure_label(self):
        state = {"complaint_text": "Shipment SHP-1 has a problem", "context": {"local_subgraph": local_with_label(), "similar_cases": []}}
        prompt = classifier._prompt(state)
        self.assertIn("F-1", prompt)
        self.assertNotIn(SENTINEL_CATEGORY, prompt)
        self.assertNotIn("ANSWER-LABEL-SENTINEL", prompt)

    def test_reviewer_prompt_never_contains_the_recorded_failure_label(self):
        state = {"complaint_text": "Shipment SHP-1 has a problem", "classification": {"category": "hub_delay"},
                 "recommendation": {"action": "x"}, "context": {"local_subgraph": local_with_label(), "similar_cases": []}}
        prompt = reviewer._prompt(state, [])
        self.assertNotIn(SENTINEL_CATEGORY, prompt)
        self.assertNotIn("ANSWER-LABEL-SENTINEL", prompt)

    def test_intake_worklist_wording_is_neutral_and_carries_no_category(self):
        rows = [{"failure_id": f"F-{i}", "shipment_id": f"SHP-{i}", "category": category, "city": "Riyadh", "courier": "C"}
                for i, category in enumerate(("address_conflict", "hub_delay", "failed_attempt_barcode_mismatch"))]
        with patch.object(cases, "queue", return_value=rows):
            items = cases.worklist()
        self.assertEqual(len({item["text"].replace(item["shipment_id"], "") for item in items}), 1)
        for item in items:
            self.assertNotIn("category", item)
        self.assertNotIn("الباركود", canonical(items))  # The old barcode template named the cause.


class V2CaseBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = generate(Config(total=90))

    def store(self):
        driver = Driver(self.world)
        return OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world)), driver

    def test_initialize_never_loads_offline_dataset_cases(self):
        self.assertTrue([n for n in self.world.of_kind("Case") if n.properties["split"] == "development"])
        store, driver = self.store()
        store.initialize()
        for _ in range(5):
            store.tick(seconds=86400, manual=True, speed=60)
        self.assertEqual([v for kind, v in driver.ledger.values() if kind == "OpsCase"], [])
        self.assertFalse(any("V2Entity:Case" in query for query in driver.queries))

    def test_monitor_opens_cases_with_symptoms_and_no_cause_codes(self):
        store, driver = self.store()
        store.initialize(); store.reset_session()
        for _ in range(40):
            store.tick(seconds=86400, manual=True, speed=60)
            while store.status()["session"]["monitor_pending"]:
                store.monitor_step()
        opened = [v for kind, v in driver.ledger.values() if kind == "OpsCase"]
        self.assertTrue(opened)
        for case in opened:
            self.assertEqual(case["cause_codes"], [])
            self.assertTrue(case.get("symptom_codes"))
            self.assertTrue(set(case["symptom_codes"]) <= set(getattr(store_module, "SYMPTOMS", {}).values()))

    def test_evidence_packet_hides_the_end_of_the_shipment_story(self):
        shipment = next(n for n in self.world.of_kind("Shipment") if n.properties["split"] == "development")
        self.assertIn("as_of", shipment.properties)  # The generator records it; the packet must not expose it.
        context = public_evidence(self.world, shipment.id, shipment.properties["recorded_at"])
        for node in context["nodes"]:
            if node["kind"] in ("Shipment", "JourneyPlan"):
                self.assertNotIn("as_of", node["properties"])


if __name__ == "__main__":
    unittest.main()
