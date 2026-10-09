"""S5 safeguards: truth isolation, exactly-once execution across restarts, human-verified closure."""
import ast
import json
import pathlib
import unittest

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations.lifecycle import OperationsConflict
from operations.store import OperationsStore
from tests import test_operations_store as _store
from tests.test_operations_store import Reader

ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENT_REACHABLE = ["chat/operations/tools.py", "chat/operations/investigator.py", "chat/operations/checks.py",
                   "chat/operations/graph.py", "chat/operations/read_model.py", "chat/operations/reasoning.py",
                   "chat/operations/agents.py", "chat/operations/worker.py", "backend/operations_api.py", "backend/main.py"]


def imported_names(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names |= {f"{node.module}.{a.name}" for a in node.names} | {node.module or ""}
    return names


class TruthIsolationTests(unittest.TestCase):
    def test_no_agent_or_operator_module_can_reach_truth_or_simulator_state(self):
        for path in AGENT_REACHABLE:
            names = imported_names(path)
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertFalse(any("simulation" in n for n in names if path != "backend/operations_api.py"), path)
            self.assertNotIn("truth.jsonl", source, path)
            self.assertFalse(any(n.endswith("read_truth") for n in names if path != "backend/operations_api.py"), path)

    def test_api_reads_truth_only_to_construct_the_simulator(self):
        source = (ROOT / "backend/operations_api.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        users = [f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and "read_truth" in ast.unparse(f)]
        self.assertEqual(users, ["attach_simulator"])
        routes = [ast.unparse(d) for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) for d in f.decorator_list]
        self.assertFalse([r for r in routes if "truth" in r.lower()])

    def test_static_frontend_mount_does_not_expose_artifacts(self):
        main = (ROOT / "backend/main.py").read_text(encoding="utf-8")
        self.assertNotIn("artifacts", main)

    def test_investigator_prompt_and_tool_results_name_no_truth(self):
        from operations import investigator
        for marker in ("truth", "recipe", "root_cause", "expected_resolution", "buffered_upload", "wrong_label", "offline_device"):
            self.assertNotIn(marker, investigator.SYSTEM.lower())


class _Store(unittest.TestCase):
    """Reuses the store test fixtures without re-running their tests."""
    setUpClass = classmethod(lambda cls: setattr(cls, "world", generate(Config(total=90))))
    make = _store.StoreTests.make
    processed = _store.StoreTests.processed


class ExecutionRecoveryTests(_Store):
    def test_claimed_but_unacknowledged_execution_is_redispatched_exactly_once(self):
        store, driver, result = self.processed()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-crash")
        calls = []
        class Adapter:
            def respond(self, execution, now):
                calls.append(execution["entity_id"]); return {"scheduled": 0, "behaviour": "test"}
        # Simulate a crash after the claim and before the receipt.
        def crash(tx):
            for kind, e in tx.ledger.values():
                if kind == "OpsExecution": e["status"] = "EXECUTING"
        driver.execute_write(crash)
        self.assertEqual(store.execute_step(), [])  # A claimed execution is not picked again by a live worker.
        restarted = OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world))
        restarted.adapter = Adapter()
        restarted.initialize()
        self.assertEqual(len(restarted.execute_step()), 1)
        self.assertEqual(restarted.execute_step(), [])
        self.assertEqual(len(calls), 1)
        audit = [v["event_type"] for k, v in driver.ledger.values() if k == "OpsAudit"]
        self.assertIn("EXECUTION_RECOVERED", audit)

    def test_simulator_messages_have_deterministic_ids(self):
        from dataset_v2.contracts import Node
        from operations.simulation import message
        node = Node("DEMO-X-SIM-1", "ScanEvent", {"shipment_id": "S", "occurred_at": "2026-09-01T00:00:00+00:00", "source_ref": "x"})
        self.assertEqual(message(node, "SPL_CORE", "2026-09-01T00:01:00+00:00")["feed_id"],
                         message(node, "SPL_CORE", "2026-09-01T00:05:00+00:00")["feed_id"])


class HumanClosureTests(_Store):
    def test_person_closes_with_evidence_as_human_verified_not_evidence_verified(self):
        store, driver, result = self.processed()
        def to_human(tx):
            tx.ledger[result["case_id"]][1]["workflow_state"] = "HUMAN_REVIEW"
        driver.execute_write(to_human)
        case = store.case_detail(result["case_id"])
        evidence = [n["id"] for n in store.reader.evidence(case["shipment_id"], store.status()["as_of"])["nodes"] if n["kind"] == "Package"]
        with self.assertRaises(OperationsConflict):
            store.record_human_outcome(case["case_id"], "DEMO-OPERATOR-LOCAL", "parcel_located", "found", evidence, case["state_version"], "short-1")
        with self.assertRaises(OperationsConflict):
            store.record_human_outcome(case["case_id"], "DEMO-OPERATOR-LOCAL", "parcel_located", "Parcel found on shelf B4 during the depot check.",
                                       ["DEMO-NOT-VISIBLE"], case["state_version"], "foreign-1")
        closed = store.record_human_outcome(case["case_id"], "DEMO-OPERATOR-LOCAL", "parcel_located",
                                            "Parcel found on shelf B4 during the depot check.", evidence, case["state_version"], "human-01")
        self.assertEqual((closed["workflow_state"], closed["verification_status"]), ("RESOLVED", "HUMAN_VERIFIED"))
        outcome = next(v for k, v in driver.ledger.values() if k == "OpsOutcome")
        self.assertEqual((outcome["verification_status"], outcome["verifier_id"]), ("HUMAN_VERIFIED", "DEMO-OPERATOR-LOCAL"))
        self.assertTrue(store.record_human_outcome(case["case_id"], "DEMO-OPERATOR-LOCAL", "parcel_located",
                                                   "Parcel found on shelf B4 during the depot check.", evidence, case["state_version"], "human-01")["idempotent"])


class ExceptionClearanceTests(_Store):
    """A verified action resolves the case only when the exception itself is gone."""
    def verify_with(self, exceptions):
        from unittest import mock
        store, driver, result = self.processed()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-clear")
        def no_human_closure(tx):
            for kind, e in tx.ledger.values():
                if kind == "OpsExecution": e["closure"] = "AUTO"
                if kind == "OpsCase": e["symptom_codes"] = ["MILESTONE_OVERDUE"]
        driver.execute_write(no_human_closure)
        store.execute_step()
        current = store.case_detail(case["case_id"])
        verdict = {"status": "success", "outcome_type": "delayed_upload_received", "evidence_ids": [], "reason": "Late upload arrived.",
                   "rule_id": "VERIFY-REQUEST_DEVICE_SYNC-success", "expected_effect": "late upload"}
        assessment = {"exceptions": exceptions}
        with mock.patch("operations.outcome_engine.evaluate", return_value=verdict),              mock.patch("dataset_v2.derive.assess_shipment", return_value=assessment):
            store.request_verification(case["case_id"], "DEMO-OPERATOR-LOCAL", current["state_version"], "verify-clear")
        outcome = next(v for k, v in driver.ledger.values() if k == "OpsOutcome")
        audit = [v["event_type"] for k, v in driver.ledger.values() if k == "OpsAudit"]
        return store.case_detail(case["case_id"]), outcome, audit

    def test_action_verified_but_standing_symptom_remains_is_not_resolved(self):
        case, outcome, audit = self.verify_with([{"code": "MANIFEST_CONFLICT"}])
        self.assertEqual(case["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual((outcome["success"], outcome["exception_cleared"], outcome["remaining_symptoms"]),
                         (True, False, ["MANIFEST_CUSTODY_CONFLICT"]))
        self.assertIn("OUTCOME_VERIFIED_EXCEPTION_REMAINS", audit)
        self.assertNotIn("CASE_RESOLVED", audit)

    def test_past_event_symptom_does_not_block_resolution_when_the_condition_is_gone(self):
        case, outcome, audit = self.verify_with([{"code": "JOURNEY_DELAY"}])
        self.assertEqual(case["workflow_state"], "RESOLVED")
        self.assertTrue(outcome["exception_cleared"])
        self.assertIn("CASE_RESOLVED", audit)


if __name__ == "__main__":
    unittest.main()
