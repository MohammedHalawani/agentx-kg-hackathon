"""S4: execution adapter, operational simulator and action-specific verification on real Neo4j.

Opt-in: SUHAIL_NEO4J_TESTS=1. The investigator here is a transparent test double (rule of thumb
over the real tools: a silent facility handheld means delayed sync, a differing barcode read means
rescan) so the execution and verification mechanics are tested deterministically; the real
GPT-OSS agent is exercised in the S3 gate and the S5 scenarios. Truth is read only by the
simulator and, afterwards, by the assertions.
"""
import os
import types
import unittest

from tests.test_live_runtime_neo4j import TEST_DATABASE, build_test_database, make_store


def rule_of_thumb_investigator():
    from operations import investigator
    def investigate(tools, on_step=None, feedback=None):
        packages = [n.id for n in tools.world.nodes.values() if n.kind == "Package"]
        replies = [{"action": "call", "tool": "journey", "args": {}, "purpose": "Expected vs observed."},
                   {"action": "call", "tool": "scans", "args": {}, "purpose": "Barcode and weight reads."}]
        state = {}
        def decide(messages):
            missing = [r for r in tools._journey()["milestones"] if r["state"] == "missing_after_deadline" and r.get("facility_handheld")]
            if missing and "device" not in state:
                state["device"] = missing[0]["facility_handheld"]
                return {"action": "call", "tool": "device_status", "args": {"device_id": state["device"]}, "purpose": "Is the scanner reporting?"}
            scans = tools._scans()["scans"]
            wrong = [s for s in scans if s.get("barcode_matches") is False]
            silent = state.get("device") and tools.device_reports.get(state["device"], {}).get("reporting_state") == "SILENT"
            if silent:
                cause, action, ids = "DELAYED_SYNC", "REQUEST_DEVICE_SYNC", [state["device"], missing[0]["milestone_id"]]
            elif wrong:
                cause, action, ids = "BARCODE_MISMATCH", "REQUEST_RESCAN", [wrong[0]["scan_id"]]
            else:
                return {"action": "conclude", "primary_cause": "UNKNOWN", "confidence": "low", "missing_evidence": ["more"],
                        "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": "Unclear.",
                        "hypotheses": [{"cause": "UNKNOWN", "status": "uncertain", "supporting_evidence_ids": [], "contradicting_evidence_ids": [], "assessment": "Unclear."}]}
            return {"action": "conclude", "primary_cause": cause, "confidence": "medium", "missing_evidence": [], "recommended_action": action,
                    "requires_physical_check": False, "summary": "Supported by the retrieved records.",
                    "hypotheses": [{"cause": cause, "status": "supported", "supporting_evidence_ids": ids, "contradicting_evidence_ids": [], "assessment": "Consistent."}]}
        queue = replies + [decide, decide]
        def turn(messages):
            reply = queue.pop(0)
            return reply(messages) if callable(reply) else reply
        return investigator.investigate(tools, turn=turn, on_step=on_step)
    def review(conclusion, records, checks, symptoms):
        return investigator.review(conclusion, records, checks, symptoms, ask=lambda s, u, d: {**d, "verdict": "ACCEPT", "feedback": "Supported."})
    return types.SimpleNamespace(investigate=investigate, review=review)


@unittest.skipUnless(os.environ.get("SUHAIL_NEO4J_TESTS") == "1", "set SUHAIL_NEO4J_TESTS=1 to run against local Neo4j")
class ExecutionNeo4jTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver, cls.bundle, cls.truth, cls.tmp = build_test_database()
        from operations.simulation import OperationalSimulator
        cls.store = make_store(cls.driver, cls.bundle, agents=rule_of_thumb_investigator())
        cls.store.adapter = OperationalSimulator(cls.store.gateway, cls.store.reader, cls.truth, cls.store.config)
        store = cls.store
        while store.status()["as_of"] < store.status()["simulator"]["end_at"]:
            store.tick(seconds=3600, manual=True, speed=1)
            while store.status()["session"]["monitor_pending"]:
                store.monitor_step(limit=20)
            while store.process_one(manual=True).get("processed"):
                pass
            store.execute_step(limit=20)
            store.outcome_step(limit=50)
        with cls.driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
            cls.cases = {r["c"]["shipment_id"]: dict(r["c"]) for r in session.run("MATCH (c:OpsEntity:OpsCase) RETURN properties(c) AS c")}
            cls.outcomes = {r["o"]["case_id"]: dict(r["o"]) for r in session.run("MATCH (o:OpsEntity:OpsOutcome) RETURN properties(o) AS o")}
            cls.executions = {r["e"]["case_id"]: dict(r["e"]) for r in session.run("MATCH (e:OpsEntity:OpsExecution) RETURN properties(e) AS e")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def case_for(self, recipe):
        sid = next(s for s, r in self.truth.items() if r["recipe"] == recipe and r["split"] == "development")
        return self.cases[sid]

    def test_offline_device_sync_resolves_from_the_late_upload_without_a_human(self):
        case = self.case_for("offline_device_sync")
        execution, outcome = self.executions[case["entity_id"]], self.outcomes[case["entity_id"]]
        self.assertEqual((execution["action_type"], execution["authority"], execution["status"]), ("REQUEST_DEVICE_SYNC", "AUTO_POLICY", "ACKNOWLEDGED"))
        self.assertEqual((outcome["outcome_type"], outcome["success"], outcome["verifier_id"]), ("delayed_upload_received", True, "SUHAIL-OUTCOME-VERIFIER"))
        self.assertEqual(case["workflow_state"], "RESOLVED")
        self.assertFalse([e for e in self.decisions() if e["case_id"] == case["entity_id"]])

    def test_wrong_label_rescan_fails_verification_and_stays_unresolved(self):
        case = self.case_for("wrong_label_applied")
        outcome = self.outcomes[case["entity_id"]]
        self.assertEqual((outcome["outcome_type"], outcome["success"]), ("barcode_still_differs", False))
        self.assertEqual(case["workflow_state"], "HUMAN_REVIEW")

    def test_misread_label_rescan_succeeds(self):
        case = self.case_for("different_barcode")
        self.assertEqual(self.outcomes[case["entity_id"]]["outcome_type"], "barcode_corrected")
        self.assertEqual(case["workflow_state"], "RESOLVED")

    def decisions(self):
        with self.driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
            return [dict(r["d"]) for r in session.run("MATCH (d:OpsEntity:OpsDecision) RETURN properties(d) AS d")]


if __name__ == "__main__":
    unittest.main()
