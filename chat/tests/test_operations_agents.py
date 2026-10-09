"""Model-backed V2 roles: validation, retry/fallback, authority policy and the synthetic executor."""
import json
import types
import unittest

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations import agents
from operations.authority import authorize, default_action, ACTIONS
from tests.test_operations_store import Driver, Reader, LiveSessionTests
from operations.store import OperationsStore

PACKET = {"shipment_id": "S", "as_of": "2026-09-01T07:00:00+00:00", "visible_evidence_ids": ["S", "SCAN-1", "PKG-1"],
          "deterministic_signals": [{"code": "BARCODE_MISMATCH", "summary": "Readable scan differs from manifest", "evidence_ids": ["SCAN-1"], "requires_human_review": False}],
          "observations": [{"id": "SCAN-1", "kind": "ScanEvent", "observed_barcode": "ABC128"}], "evidence_counts": {"ScanEvent": 1}}
GOOD_INV = {"primary_hypothesis": "BARCODE_MISMATCH", "alternative_hypotheses": [], "supporting_evidence_ids": ["SCAN-1"],
            "conflicting_evidence_ids": [], "missing_evidence": [], "confidence": "high", "sensitivity": "low",
            "summary": "Readable scan ABC128 conflicts with the manifest barcode."}


def scripted(*outputs):
    queue = list(outputs)
    calls = []
    def call(system, user, default):
        calls.append(user)
        return {**default, **queue.pop(0)}
    call.calls = calls
    return call


class ValidationTests(unittest.TestCase):
    def test_valid_investigation_is_accepted_as_model_output(self):
        out = agents.investigate(PACKET, call=scripted(GOOD_INV))
        self.assertEqual(out["mode"], "gpt-oss"); self.assertEqual(out["primary_hypothesis"], "BARCODE_MISMATCH")

    def test_invented_evidence_id_is_retried_with_feedback_then_falls_back(self):
        bad = {**GOOD_INV, "supporting_evidence_ids": ["FUTURE-SCAN-9"]}
        call = scripted(bad, bad)
        out = agents.investigate(PACKET, call=call)
        self.assertEqual(out["mode"], "deterministic_fallback")
        self.assertIn("not visible", out["validation_error"])
        self.assertIn("previous output was rejected", call.calls[1])
        self.assertEqual(out["supporting_evidence_ids"], ["SCAN-1"])  # Fallback cites only deterministic evidence.

    def test_invented_numbers_blame_and_gps_delivery_are_rejected(self):
        for summary in ("There were 3 failed attempts.", "The driver lost the parcel.", "Vehicle GPS proves the package was delivered."):
            out = agents.investigate(PACKET, call=scripted({**GOOD_INV, "summary": summary}, {**GOOD_INV, "summary": summary}))
            self.assertEqual(out["mode"], "deterministic_fallback", summary)

    def test_hypothesis_must_be_supported_by_a_deterministic_signal(self):
        out = agents.investigate(PACKET, call=scripted({**GOOD_INV, "primary_hypothesis": "DELIVERY_DISPUTE"}, GOOD_INV))
        self.assertEqual(out["mode"], "gpt-oss")

    def test_planner_cannot_propose_prohibited_or_unknown_actions(self):
        good = {"action_type": "REQUEST_RESCAN", "evidence_basis": ["SCAN-1"], "expected_result": "A readable scan matches the manifest.",
                "risk_hypothesis": "low", "reason": "Barcode conflict.", "requires_authorization_hint": "no"}
        out = agents.plan(PACKET, GOOD_INV, call=scripted({**good, "action_type": "COMPENSATION"}, good))
        self.assertEqual(out["action_type"], "REQUEST_RESCAN"); self.assertEqual(out["mode"], "gpt-oss")

    def test_packet_contains_no_private_fields(self):
        text = json.dumps(PACKET)
        for word in ("chain_of_thought", "gold", "expected_cause", "reasoning"):
            self.assertNotIn(word, text)


class AuthorityTests(unittest.TestCase):
    def test_low_risk_is_auto_only_in_synthetic_live_session(self):
        self.assertEqual(authorize("REQUEST_RESCAN", ["BARCODE_MISMATCH"], review_verdict="ACCEPT", evidence_conflict=False, synthetic=True, live_session=True)[0], "AUTO")
        self.assertEqual(authorize("REQUEST_RESCAN", ["BARCODE_MISMATCH"], review_verdict="ACCEPT", evidence_conflict=False, synthetic=True, live_session=False)[0], "APPROVAL_REQUIRED")
        self.assertEqual(authorize("REQUEST_RESCAN", ["BARCODE_MISMATCH"], review_verdict="ACCEPT", evidence_conflict=False, synthetic=False, live_session=True)[0], "APPROVAL_REQUIRED")

    def test_disputes_conflicts_and_reviewer_escalations_go_to_humans(self):
        self.assertEqual(authorize("PRIORITIZE_NEXT_SESSION", ["DELIVERY_DISPUTE", "TRAFFIC_DELAY"], review_verdict="ACCEPT", evidence_conflict=False, synthetic=True, live_session=True)[0], "HUMAN_REVIEW")
        self.assertEqual(authorize("REQUEST_HUB_CHECK", ["HUB_DELAY"], review_verdict="ACCEPT", evidence_conflict=True, synthetic=True, live_session=True)[0], "HUMAN_REVIEW")
        self.assertEqual(authorize("REQUEST_HUB_CHECK", ["HUB_DELAY"], review_verdict="ESCALATE", evidence_conflict=False, synthetic=True, live_session=True)[0], "HUMAN_REVIEW")

    def test_sensitive_actions_need_approval_and_mismatched_actions_are_not_auto(self):
        self.assertEqual(authorize("RETURN_TO_SENDER", ["RECIPIENT_UNAVAILABLE"], review_verdict="ACCEPT", evidence_conflict=False, synthetic=True, live_session=True)[0], "APPROVAL_REQUIRED")
        self.assertEqual(authorize("REQUEST_RESCAN", ["TRAFFIC_DELAY"], review_verdict="ACCEPT", evidence_conflict=False, synthetic=True, live_session=True)[0], "APPROVAL_REQUIRED")
        self.assertEqual(authorize("COMPENSATION", ["TRAFFIC_DELAY"], review_verdict="ACCEPT", evidence_conflict=False, synthetic=True, live_session=True)[0], "PROHIBITED")
        self.assertEqual(default_action("DELIVERY_DISPUTE"), "DELIVERY_DISPUTE_REVIEW")


def fake_agents():
    """The real agents module with a deterministic stand-in for the model call."""
    def call(system, user, default):
        facts = json.loads(user.split("\n\nYour previous")[0])["facts"]
        top = facts["deterministic_signals"][0]
        if "investigator" in system:
            return {**default, "primary_hypothesis": top["code"], "supporting_evidence_ids": top["evidence_ids"][:5],
                    "confidence": "medium", "sensitivity": "high" if top["requires_human_review"] else "low", "summary": "Supported by cited evidence."}
        if "planner" in system:
            return {**default, "action_type": default_action(top["code"]), "evidence_basis": top["evidence_ids"][:5],
                    "expected_result": "Later evidence confirms recovery.", "reason": "Catalog action for the diagnosis."}
        return {**default, "verdict": "ACCEPT", "feedback": "Supported and within policy."}
    module = types.SimpleNamespace(facts=agents.facts, investigate=lambda p: agents.investigate(p, call=call),
                                   plan=lambda p, i, feedback=None: agents.plan(p, i, call=call, feedback=feedback),
                                   review=lambda p, i, pr: agents.review(p, i, pr, call=call))
    return module


class AgentPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.world = generate(Config(total=90))

    def live(self):
        d = Driver(self.world)
        s = OperationsStore(d, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world), agents=fake_agents())
        s.initialize(); s.reset_session(); return s, d

    def test_live_case_runs_agent_stages_and_low_risk_action_awaits_outcome_without_a_human(self):
        s, d = self.live(); LiveSessionTests.run_world(self, s, rounds=400)
        cases = [v for k, v in d.ledger.values() if k == "OpsCase"]
        self.assertTrue(cases)
        routed = {}
        while True:
            r = s.process_one(manual=True)
            if not r.get("processed"): break
            routed[r["case_id"]] = r["workflow_state"]
        self.assertIn("AWAITING_OUTCOME", routed.values())
        executions = [v for k, v in d.ledger.values() if k == "OpsExecution"]
        self.assertTrue(executions)
        for e in executions:
            self.assertEqual(e["authority"], "AUTO_POLICY"); self.assertIsNone(e.get("decision_id"))
            self.assertEqual(ACTIONS[e["action_type"]][0], "AUTO")
        audit = [v for k, v in d.ledger.values() if k == "OpsAudit"]
        self.assertTrue(any(a["event_type"] == "ACTION_AUTHORIZED" and a["actor_id"] == "SUHAIL-AUTHORITY-POLICY" for a in audit))
        runs = [json.loads(v["result_json"]) for k, v in d.ledger.values() if k == "OpsRun"]
        agent_modes = {e["output"].get("agent") for r in runs for e in r["pipeline_events"] if e["status"] == "COMPLETED"}
        self.assertIn("gpt-oss", agent_modes)
        for case in [v for k, v in d.ledger.values() if k == "OpsCase"]:
            self.assertNotEqual(case["workflow_state"], "RESOLVED")  # Nothing self-certifies success.
            if "DELIVERY_DISPUTE" in case["cause_codes"]:
                self.assertIn(case["workflow_state"], ("HUMAN_REVIEW", "OPEN", "ESCALATED"))


class OutcomeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.world = generate(Config(total=90))

    def test_rescan_success_requires_later_matching_scan_and_silence_fails_at_deadline(self):
        from operations.outcome_engine import evaluate
        from dataset_v2.contracts import Node
        from operations.reasoning import evidence_world, public_evidence
        sid = next(n.id for n in self.world.of_kind("Shipment") if n.properties["split"] == "development")
        ctx = public_evidence(self.world, sid, self.world.config.as_of)
        world = evidence_world(ctx, self.world.config)
        pkg = next(n for n in world.nodes.values() if n.kind == "Package")
        execution = {"action_type": "REQUEST_RESCAN", "occurred_at": "2026-10-20T00:00:00+00:00", "deadline_at": "2026-10-23T00:00:00+00:00"}
        self.assertEqual(evaluate(world, sid, execution, "2026-10-20T06:00:00+00:00")["status"], "pending")
        self.assertEqual(evaluate(world, sid, execution, "2026-10-23T00:00:00+00:00")["status"], "failure")
        scan = Node("LATER-SCAN", "ScanEvent", {"shipment_id": sid, "package_id": pkg.id, "readable": True,
                    "observed_barcode": pkg.properties.get("manifest_barcode"), "occurred_at": "2026-10-20T05:00:00+00:00"})
        world.nodes[scan.id] = scan
        self.assertEqual(evaluate(world, sid, execution, "2026-10-20T04:00:00+00:00")["status"], "pending")  # Not yet visible.
        verdict = evaluate(world, sid, execution, "2026-10-20T06:00:00+00:00")
        self.assertEqual((verdict["status"], verdict["outcome_type"]), ("success", "barcode_corrected"))
        report = Node("LATER-REPORT", "RecipientReport", {"shipment_id": sid, "report_code": "NOT_RECEIVED", "occurred_at": "2026-10-20T05:30:00+00:00"})
        world.nodes[report.id] = report
        self.assertEqual(evaluate(world, sid, execution, "2026-10-20T06:00:00+00:00")["outcome_type"], "dispute_unresolved")

    def test_live_world_resolves_only_from_later_verified_evidence_with_no_human(self):
        d = Driver(self.world)
        s = OperationsStore(d, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world), agents=fake_agents())
        s.initialize(); s.reset_session()
        for _ in range(600):
            r = s.tick(seconds=3600, manual=True, speed=60)
            while s.status()["session"]["monitor_pending"]: s.monitor_step()
            while s.process_one(manual=True).get("processed"): pass
            s.outcome_step(limit=50)
            if not r["events_replayed"] and s.status()["as_of"] >= s.status()["simulator"]["end_at"]: break
        cases = [v for k, v in d.ledger.values() if k == "OpsCase"]
        outcomes = {v["entity_id"]: v for k, v in d.ledger.values() if k == "OpsOutcome"}
        executions = {v["entity_id"]: v for k, v in d.ledger.values() if k == "OpsExecution"}
        resolved = [c for c in cases if c["workflow_state"] == "RESOLVED"]
        self.assertTrue(resolved, "at least one zero-human resolution")
        for c in resolved:
            o = outcomes[c["verified_outcome_id"]]
            self.assertTrue(c["is_terminal"]); self.assertTrue(o["success"]); self.assertEqual(o["verifier_id"], "SUHAIL-OUTCOME-VERIFIER")
            self.assertGreaterEqual(str(o["verified_at"]), str(executions[o["execution_id"]]["occurred_at"]))
        decisions = [v for k, v in d.ledger.values() if k == "OpsDecision"]
        self.assertEqual(decisions, [])  # No human clicked anything.
        failed = [o for o in outcomes.values() if not o["success"]]
        for o in failed:
            case = next(c for c in cases if c["entity_id"] == o["case_id"])
            self.assertNotEqual(case["workflow_state"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
