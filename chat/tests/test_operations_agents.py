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

    def test_invented_evidence_id_is_retried_with_feedback_then_degrades_without_a_substitute(self):
        bad = {**GOOD_INV, "supporting_evidence_ids": ["FUTURE-SCAN-9"]}
        call = scripted(bad, bad)
        out = agents.investigate(PACKET, call=call)
        self.assertEqual(out["mode"], "model_unavailable"); self.assertTrue(out["degraded"])
        self.assertIn("not visible", out["validation_error"])
        self.assertIn("previous output was rejected", call.calls[1])
        # No canned diagnosis is substituted for the missing model conclusion.
        self.assertIsNone(out["primary_hypothesis"]); self.assertEqual(out["supporting_evidence_ids"], [])

    def test_invented_numbers_blame_and_gps_delivery_are_rejected(self):
        for summary in ("There were 3 failed attempts.", "The driver lost the parcel.", "Vehicle GPS proves the package was delivered."):
            out = agents.investigate(PACKET, call=scripted({**GOOD_INV, "summary": summary}, {**GOOD_INV, "summary": summary}))
            self.assertEqual(out["mode"], "model_unavailable", summary)

    def test_reviewer_failure_fails_closed_and_is_never_acceptance(self):
        proposal = {"action_type": "REQUEST_RESCAN", "evidence_basis": ["SCAN-1"], "expected_result": "", "risk_hypothesis": "",
                    "reason": "", "requires_authorization_hint": ""}
        def timeout(system, user, default): raise TimeoutError("provider timed out")
        def invalid(system, user, default): return {**default, "verdict": "MAYBE"}
        for call in (timeout, invalid):
            out = agents.review(PACKET, GOOD_INV, proposal, call=call)
            self.assertEqual(out["verdict"], "UNAVAILABLE"); self.assertTrue(out["degraded"])
            self.assertNotIn("provider timed out", json.dumps(out))  # Error type only, never provider text.
        self.assertEqual(authorize("REQUEST_RESCAN", ["BARCODE_MISMATCH"], review_verdict="UNAVAILABLE", evidence_conflict=False,
                                   synthetic=True, live_session=True)[0], "HUMAN_REVIEW")
        self.assertEqual(authorize("REQUEST_RESCAN", ["BARCODE_MISMATCH"], review_verdict=None, evidence_conflict=False,
                                   synthetic=True, live_session=True)[0], "APPROVAL_REQUIRED")
        self.assertEqual(authorize("REQUEST_RESCAN", ["BARCODE_MISMATCH"], review_verdict="ACCEPT", evidence_conflict=False,
                                   synthetic=True, live_session=True, degraded=True)[0], "HUMAN_REVIEW")

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


def fake_agents(review_call=None):
    """Test double for the GPT-OSS investigator: it really calls the tools, then concludes with the
    cause the evidence rules support among the evidence it retrieved. Reviewer accepts unless replaced."""
    from operations import investigator
    from dataset_v2.derive import assess_shipment
    def investigate(tools, on_step=None, feedback=None):
        packages = [n.id for n in tools.world.nodes.values() if n.kind == "Package"]
        plan = [("scans", {}), ("delivery_attempts", {}), ("vehicle_and_manifest", {})] + [("custody_chain", {"package_id": p}) for p in packages]
        plan += [("journey", {"package_id": p}) for p in packages]
        replies = [{"action": "call", "tool": t, "args": a, "purpose": "Inspect."} for t, a in plan[:investigator.MAX_TOOL_CALLS]]
        def conclude(messages):
            exceptions = assess_shipment(tools.world, tools.sid, tools.as_of)["exceptions"]
            top = next((e for e in exceptions if set(e["evidence_ids"]) & tools.retrieved), None)
            if top is None:
                return {"action": "conclude", "primary_cause": "UNKNOWN", "confidence": "low", "missing_evidence": ["more evidence"],
                        "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": "Not enough evidence.",
                        "hypotheses": [{"cause": "UNKNOWN", "status": "uncertain", "supporting_evidence_ids": [], "contradicting_evidence_ids": [], "assessment": "Unclear."}]}
            ids = sorted(set(top["evidence_ids"]) & tools.retrieved)
            return {"action": "conclude", "primary_cause": top["code"], "confidence": "medium", "missing_evidence": [],
                    "recommended_action": default_action(top["code"]), "requires_physical_check": top["requires_human_review"],
                    "summary": "Supported by cited evidence.", "hypotheses": [{"cause": top["code"], "status": "supported",
                    "supporting_evidence_ids": ids, "contradicting_evidence_ids": [], "assessment": "Consistent with the records."}]}
        def turn(messages, queue=list(replies) + [conclude]):
            reply = queue.pop(0)
            return reply(messages) if callable(reply) else reply
        return investigator.investigate(tools, turn=turn, on_step=on_step, feedback=feedback)
    def review(conclusion, records, checks, symptoms):
        ask = review_call or (lambda system, user, default: {**default, "verdict": "ACCEPT", "feedback": "Supported and within policy."})
        return investigator.review(conclusion, records, checks, symptoms, ask=ask)
    return types.SimpleNamespace(investigate=investigate, review=review)


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


class ReviewerFailureTests(unittest.TestCase):
    """Scenario D at unit level: a failed reviewer blocks the automatic action and is recorded."""
    @classmethod
    def setUpClass(cls): cls.world = generate(Config(total=90))

    def test_unavailable_reviewer_blocks_auto_execution_and_records_degraded_review(self):
        def unreachable(system, user, default): raise ConnectionError("unreachable")
        module = fake_agents(review_call=unreachable)
        d = Driver(self.world)
        s = OperationsStore(d, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world), agents=module)
        s.initialize(); s.reset_session(); LiveSessionTests.run_world(self, s, rounds=400)
        routed = []
        while True:
            r = s.process_one(manual=True)
            if not r.get("processed"): break
            routed.append(r)
        self.assertTrue(routed)
        self.assertEqual([v for k, v in d.ledger.values() if k == "OpsExecution"], [])  # Nothing executed automatically.
        audit = [v for k, v in d.ledger.values() if k == "OpsAudit"]
        degraded = [a for a in audit if a["event_type"] == "MODEL_DEGRADED" and a["actor_id"] == "SUHAIL-REVIEWER"]
        self.assertTrue(degraded)
        for case in [v for k, v in d.ledger.values() if k == "OpsCase" and v.get("last_run_id")]:
            self.assertNotIn(case["workflow_state"], ("AWAITING_OUTCOME", "ACTION_INITIATED", "RESOLVED"))
        runs = [json.loads(v["result_json"]) for k, v in d.ledger.values() if k == "OpsRun"]
        self.assertTrue(any(e["stage"] == "review" and e["status"] == "DEGRADED" for r in runs for e in r["pipeline_events"]))


class OutcomeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.world = generate(Config(total=90))

    def test_live_world_resolves_only_from_later_verified_evidence_with_no_human(self):
        d = Driver(self.world)
        s = OperationsStore(d, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world), agents=fake_agents())
        s.initialize(); s.reset_session()
        for _ in range(600):
            r = s.tick(seconds=3600, manual=True, speed=60)
            while s.status()["session"]["monitor_pending"]: s.monitor_step()
            while s.process_one(manual=True).get("processed"): pass
            s.execute_step(limit=50)
            s.outcome_step(limit=50)
            if not r["events_replayed"] and s.status()["as_of"] >= s.status()["simulator"]["end_at"]: break
        cases = [v for k, v in d.ledger.values() if k == "OpsCase"]
        outcomes = {v["entity_id"]: v for k, v in d.ledger.values() if k == "OpsOutcome"}
        executions = {v["entity_id"]: v for k, v in d.ledger.values() if k == "OpsExecution"}
        resolved = [c for c in cases if c["workflow_state"] == "RESOLVED"]
        # No execution adapter here, so nothing is sent and nothing is acknowledged: later evidence must not
        # resolve anything, and each case goes to a person.
        self.assertTrue(executions)
        self.assertTrue(all(e["status"] == "NOT_ACKNOWLEDGED" and e["mode"] == "no_adapter" for e in executions.values()))
        self.assertEqual(resolved, [])
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
