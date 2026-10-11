"""The demonstration script's lifecycle, in memory: detection by the monitor, a scripted investigator and reviewer over
the real tools (no model), the real authority policy, the world simulator as execution adapter, the real verifier.

scripts/world_demo.py itself opens Neo4j and the real model; here its stage functions run on the in-memory ledger.
"""
import importlib.util
import os
import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

from operations.store import CONTROL_ID
from operations.world_simulation import PhysicalState, WorldOperationalSimulator
from tests.test_operations_store import agent_investigator
from tests.world_live import LiveWorld, ledger_store, physical

ROOT = pathlib.Path(__file__).resolve().parents[2]
MISREAD = "DEMO-SHP-000064"   # Misread once by a sorter reader; on the Jeddah depot shelf from 03:11 on 17 September.


def demo_module():
    spec = importlib.util.spec_from_file_location("world_demo", ROOT / "scripts" / "world_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DemoTests(unittest.TestCase):
    def test_evaluation_and_other_databases_are_refused(self):
        demo = demo_module()
        for name in ("shipments-v2-world-eval-1", "shipments-v2-world-eval-e2-heldout", "shipments-v2-demo-live", "neo4j", ""):
            with self.assertRaises(SystemExit):
                demo.check_database(name)
        self.assertEqual(demo.check_database("shipments-v2-world-1-small"), "shipments-v2-world-1-small")
        with mock.patch.dict(os.environ, {"SUHAIL_EVAL_TRUTH_ROOT": r"C:\somewhere"}):
            self.assertEqual(demo.label_environment(), ["SUHAIL_EVAL_TRUTH_ROOT"])
        source = (ROOT / "scripts" / "world_demo.py").read_text(encoding="utf-8")
        for forbidden in ("world.truth", "truth_io", "read_truth", "suhail-eval-truth", "model_call_ledger.json\")"):
            self.assertNotIn(forbidden, source)

    def test_one_case_runs_from_detection_to_a_verified_resolution(self):
        demo = demo_module()
        live = LiveWorld("2026-09-17T03:30:00+00:00")
        sim = WorldOperationalSimulator(live.gateway, live, PhysicalState(physical()), live.world.config)
        store, driver = ledger_store(live, sim)
        store.agents = agent_investigator(cause="BARCODE_MISMATCH", action="REQUEST_RESCAN")
        driver.ledger[CONTROL_ID][1]["monitor_queue"] = [MISREAD]
        opened = store.monitor_step()["opened"]          # The monitor opens the case from visible evidence.
        self.assertEqual(len(opened), 1)
        record = {"case_id": opened[0], "shipment_id": MISREAD, "stages": [], "verified": False}
        demo.stage(record, "detection", store, opened[0])
        demo.investigate(store, record, SimpleNamespace(rules_only=False, approve=False), 60)
        stages = {row["stage"]: row for row in record["stages"]}
        self.assertEqual(stages["detection"]["workflow_state"], "OPEN")
        investigation = stages["investigation"]
        self.assertEqual((investigation["review"]["model_verdict"], investigation["authority"]["risk_class"], investigation["authority"]["action_type"]),
                         ("ACCEPT", "AUTO", "REQUEST_RESCAN"))
        self.assertEqual(stages["approval"]["needed"], False)
        [execution] = stages["execution"]["executions"]
        self.assertEqual((execution["authority"], execution["status"], execution["mode"]), ("AUTO_POLICY", "ACKNOWLEDGED", "world_operational_simulator"))
        self.assertEqual(execution["receipt"]["acknowledged"], True)
        self.assertEqual(stages["execution"]["workflow_state"], "AWAITING_OUTCOME")   # A receipt is not an outcome.
        self.assertIsNone(stages["execution"]["outcome"])
        for _ in range(2):
            demo.hour(store, verify=True)
        final = demo.stage(record, "final", store, opened[0])
        self.assertEqual(final["workflow_state"], "RESOLVED")
        self.assertEqual((final["outcome"]["verification_status"], final["outcome"]["outcome_type"], final["outcome"]["exception_cleared"],
                          final["outcome"]["verifier_id"]), ("VERIFIED", "barcode_corrected", True, "SUHAIL-OUTCOME-VERIFIER"))
        self.assertEqual(demo.calls_made(), 0)

    def test_without_a_reviewed_agent_investigation_nothing_executes(self):
        demo = demo_module()
        live = LiveWorld("2026-09-17T03:30:00+00:00")
        sim = WorldOperationalSimulator(live.gateway, live, PhysicalState(physical()), live.world.config)
        store, driver = ledger_store(live, sim)        # No agents: rules only.
        driver.ledger[CONTROL_ID][1]["monitor_queue"] = [MISREAD]
        [case_id] = store.monitor_step()["opened"]
        record = {"case_id": case_id, "shipment_id": MISREAD, "stages": [], "verified": False}
        demo.investigate(store, record, SimpleNamespace(rules_only=True, approve=True), 60)
        stages = {row["stage"]: row for row in record["stages"]}
        self.assertEqual(stages["execution"]["executions"], [])
        self.assertFalse(stages["approval"].get("approved"))
        self.assertEqual([i for i in live.gateway.items.values() if i["origin"] == "SIMULATOR"], [])


if __name__ == "__main__":
    unittest.main()
