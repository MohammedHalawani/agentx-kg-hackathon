"""B2: the case diagnosis is the current run's agent investigation or explicitly absent; rule triage is
served separately, labelled as rule signals with its own as-of time, and never fills the diagnosis."""
import json
import unittest

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations import investigator
from operations.diagnosis import absent_diagnosis, case_diagnosis
from operations.read_model import OperationsReader
from tests import test_operations_store as _store
from tests import test_investigator as ti
from tests.test_operations_read_model import make_reader


class _Store(unittest.TestCase):
    setUpClass = classmethod(lambda cls: setattr(cls, "world", generate(Config(total=90))))
    make = _store.StoreTests.make

    def agent(self, verdicts=("REVISE", "HUMAN_REVIEW")):
        fake = ti.FakeInvestigator(lambda tools: [("shipment_overview", {}), ("policy", {})], list(verdicts))
        fake.cause, fake.action = "BARCODE_MISMATCH", "REQUEST_RESCAN"
        return fake


class StoreDiagnosisTests(_Store):
    def test_agent_investigation_is_the_diagnosis_with_run_and_as_of(self):
        store, driver = self.make()
        store.agents = self.agent()
        result = store.process_one(manual=True)
        detail = store.case_detail(result["case_id"])
        diagnosis = detail["diagnosis"]
        investigation = detail["run"]["result"]["investigation"]
        self.assertTrue(diagnosis["available"])
        self.assertEqual(diagnosis["source"], "agent_investigation")
        self.assertEqual(diagnosis["run_id"], detail["last_run_id"])
        self.assertEqual(diagnosis["primary_cause"], investigation["primary_cause"])
        self.assertEqual(diagnosis["confidence"], investigation["confidence"])
        self.assertEqual([h["cause"] for h in diagnosis["hypotheses"]], [h["cause"] for h in investigation["hypotheses"]])
        snapshot = next(e["evidence_as_of"] for e in detail["run"]["result"]["pipeline_events"])
        self.assertEqual(str(diagnosis["as_of"]), str(snapshot))  # The investigation's evidence snapshot, not the live clock.
        self.assertEqual(diagnosis["tool_calls"], 2)

    def test_rules_only_run_leaves_the_diagnosis_absent(self):
        store, driver = self.make()
        result = store.process_one(manual=True)  # No investigator: deterministic rules only.
        detail = store.case_detail(result["case_id"])
        self.assertEqual((detail["diagnosis"]["available"], detail["diagnosis"]["reason"]), (False, "no_agent_investigation"))
        self.assertIsNone(detail["diagnosis"]["primary_cause"])
        self.assertEqual(detail["diagnosis"]["hypotheses"], [])

    def test_investigator_outage_leaves_the_diagnosis_absent(self):
        class Outage(ti.FakeInvestigator):
            def investigate(self, tools, on_step=None, feedback=None):
                def boom(messages): raise TimeoutError("slow")
                return investigator.investigate(tools, turn=boom, on_step=on_step)
        store, driver = self.make()
        store.agents = Outage(lambda tools: [], [])
        result = store.process_one(manual=True)
        diagnosis = store.case_detail(result["case_id"])["diagnosis"]
        self.assertEqual((diagnosis["available"], diagnosis["reason"]), (False, "investigation_unavailable"))

    def test_a_queued_or_running_reinvestigation_supersedes_the_earlier_diagnosis(self):
        store, driver = self.make()
        store.agents = self.agent()
        result = store.process_one(manual=True)
        detail = store.case_detail(result["case_id"])
        first_run = detail["last_run_id"]
        store.request_reanalysis(result["case_id"], "DEMO-OPERATOR-LOCAL", detail["state_version"], "reanalyze-diagnosis")
        queued = store.case_detail(result["case_id"])["diagnosis"]
        self.assertEqual((queued["available"], queued["reason"], queued["superseded_run_id"]), (False, "reinvestigation_pending", first_run))
        seen = []
        original = store.reader.evidence
        def during(sid, as_of):  # Read the served diagnosis while the new investigation is running.
            seen.append(store.case_detail(result["case_id"])["diagnosis"])
            return original(sid, as_of)
        store.reader.evidence = during
        store.agents = self.agent()
        store.process_one(case_id=result["case_id"])
        store.reader.evidence = original
        self.assertEqual((seen[0]["available"], seen[0]["reason"]), (False, "investigation_in_progress"))
        self.assertNotEqual(seen[0]["run_id"], first_run)
        self.assertTrue(store.case_detail(result["case_id"])["diagnosis"]["available"])

    def test_case_diagnosis_rejects_unknown_absent_reasons(self):
        with self.assertRaises(ValueError):
            absent_diagnosis("filled_from_rules")
        self.assertEqual(case_diagnosis({"workflow_state": "HUMAN_REVIEW"}, None)["reason"], "not_investigated")


class ReadModelDiagnosisTests(unittest.TestCase):
    def reader(self, ledger_diagnosis):
        reader, _ = make_reader(lambda q, p: [{"shipment_id": "DEMO-SHP-18", "as_of": "2026-09-01T02:00:00+00:00",
                                               "workflow_state": "HUMAN_REVIEW", "state_version": 1}])
        signals = {"kind": "rule_signals", "is_diagnosis": False, "as_of": "2026-09-01T02:00:00+00:00",
                   "signals": [{"code": "UNRECONCILED_CUSTODY", "evidence_ids": ["DEMO-X"]}], "expected_vs_actual": []}
        reader.shipment_detail = lambda sid, asof: {"shipment_id": sid, "as_of": asof, "evidence": {"nodes": [], "edges": []},
                                                    "diagnosis": absent_diagnosis("not_a_case"), "rule_signals": signals}
        class Store:
            def case_detail(self, case_id):
                return {"workflow_state": "HUMAN_REVIEW", "state_version": 1, "run": None, "diagnosis": ledger_diagnosis}
        reader.store = Store()
        return reader

    def test_rule_signals_never_fill_an_absent_diagnosis(self):
        detail = self.reader(absent_diagnosis("not_investigated")).case_detail("DEMO-OPS-CASE-X")
        self.assertNotIn("reasoning", detail)
        self.assertEqual((detail["diagnosis"]["available"], detail["diagnosis"]["reason"]), (False, "not_investigated"))
        self.assertIsNone(detail["diagnosis"]["primary_cause"])
        self.assertEqual(detail["rule_signals"]["signals"][0]["code"], "UNRECONCILED_CUSTODY")
        self.assertFalse(detail["rule_signals"]["is_diagnosis"])
        self.assertNotIn("UNRECONCILED_CUSTODY", json.dumps(detail["diagnosis"]))

    def test_the_ledger_diagnosis_is_served_as_recorded(self):
        recorded = {**absent_diagnosis("not_investigated"), "available": True, "reason": None, "source": "agent_investigation",
                    "run_id": "DEMO-OPS-RUN-1", "primary_cause": "DELAYED_SYNC", "confidence": "medium"}
        detail = self.reader(recorded).case_detail("DEMO-OPS-CASE-X")
        self.assertEqual(detail["diagnosis"], recorded)

    def test_without_a_ledger_the_diagnosis_is_absent(self):
        reader = self.reader(None)
        reader.store = None
        detail = reader.case_detail("DEMO-OPS-CASE-X")
        self.assertEqual(detail["diagnosis"]["reason"], "no_operations_ledger")


if __name__ == "__main__":
    unittest.main()
