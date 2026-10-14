"""Model-backed V2 roles: validation, retry/fallback, authority policy and the synthetic executor."""
import copy
import json
import types
import unittest

from dataset_v2.contracts import Config, instant
from dataset_v2.generate import generate
from operations import agents
from operations.authority import authorize, default_action, ACTIONS
from tests.test_operations_store import Driver, Reader, LiveSessionTests, development_reset
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


def receipt_alternative(primary, records):
    """Test the delayed-receipt explanation on actual retrieved event/receipt pairs.

    Prompt receipts weaken it for those records, but cannot rule out unseen buffered
    events. Keep that uncertainty instead of treating missing telemetry as a refutation.
    This fixture does not claim a second alternative when sync is already primary.
    """
    from operations.tools import LATE_UPLOAD_SECONDS
    if primary in (None, "UNKNOWN", "INSUFFICIENT_EVIDENCE", "DELAYED_SYNC"):
        return None
    observations = []
    for key, record in sorted(records.items()):
        if record.get("kind") not in ("ScanEvent", "CustodyEvent", "DeliveryAttempt"):
            continue
        if not record.get("occurred_at") or not record.get("recorded_at"):
            continue
        lag = (instant(str(record["recorded_at"])) - instant(str(record["occurred_at"]))).total_seconds()
        if lag >= 0:
            observations.append((key, lag))
        if len(observations) == 3:
            break
    if not observations:
        return None
    late = [key for key, lag in observations if lag >= LATE_UPLOAD_SECONDS]
    return {"cause": "DELAYED_SYNC", "status": "uncertain", "supporting_evidence_ids": late,
            "contradicting_evidence_ids": [] if late else [key for key, _ in observations],
            "assessment": ("The cited source records have delayed receipts; telemetry is needed to identify the mechanism."
                           if late else "The cited source records arrived promptly; buffering of unseen records remains unconfirmed.")}


def fake_agents(review_call=None, *, test_alternative=True):
    """Test double for the GPT-OSS investigator: it really calls the tools, then concludes with the
    cause the evidence rules support among the evidence it retrieved. Its reviewer independently
    recomputes the receipt-time alternative from the packet, without the investigator's tools/world.
    No model quality is measured by this deterministic double."""
    from operations import investigator
    from operations.checks import cited_records
    from dataset_v2.derive import assess_shipment
    review_packets, investigation_sessions, review_sessions = [], [], []

    def investigate(tools, *, turn=None, on_step=None, feedback=None, session=None, review=None, on_repair=None):
        investigation_sessions.append(session)
        packages = [n.id for n in tools.world.nodes.values() if n.kind == "Package"]
        plan = [("scans", {}), ("delivery_attempts", {}), ("vehicle_and_manifest", {})] + [("custody_chain", {"package_id": p}) for p in packages]
        plan += [("journey", {"package_id": p}) for p in packages]
        replies = [{"action": "call", "tool": t, "args": a, "purpose": "Inspect."} for t, a in plan[:investigator.MAX_TOOL_CALLS]]
        def conclude(messages):
            exceptions = assess_shipment(tools.world, tools.sid, tools.as_of)["exceptions"]
            top = next((e for e in exceptions if set(e["evidence_ids"]) & tools.retrieved), None)
            if top is None:
                return {"action": "conclude", "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low", "missing_evidence": ["more evidence"],
                        "next_evidence_step": "Obtain the missing package-bound source records.",
                        "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": "Not enough evidence.",
                        "hypotheses": [{"cause": "INSUFFICIENT_EVIDENCE", "status": "uncertain", "supporting_evidence_ids": [], "contradicting_evidence_ids": [], "assessment": "Unclear."}]}
            ids = sorted(set(top["evidence_ids"]) & tools.retrieved)
            hypotheses = [{"cause": top["code"], "status": "supported", "supporting_evidence_ids": ids,
                           "contradicting_evidence_ids": [], "assessment": "Consistent with the records."}]
            if test_alternative:
                retrieved = cited_records({"hypotheses": [{"supporting_evidence_ids": sorted(tools.retrieved)}]}, tools,
                                          limit=len(tools.retrieved))
                alternative = receipt_alternative(top["code"], retrieved)
                if alternative is not None:
                    hypotheses.append(alternative)
            return {"action": "conclude", "primary_cause": top["code"], "confidence": "medium", "missing_evidence": [],
                    "recommended_action": default_action(top["code"]), "requires_physical_check": top["requires_human_review"],
                    "summary": "Supported by cited evidence.", "hypotheses": hypotheses}
        def scripted_turn(messages, queue=list(replies) + [conclude]):
            reply = queue.pop(0)
            return reply(messages) if callable(reply) else reply
        return investigator.investigate(tools, turn=turn or scripted_turn, on_step=on_step, feedback=feedback, session=session,
                                       review=review, on_repair=on_repair)

    def review(conclusion, records, checks, symptoms, *, ask=None, context=None, session=None, on_repair=None):
        review_sessions.append(session)

        def scripted_review(system, user, default):
            packet = json.loads(user.split("\n\n", 1)[0])["facts"]
            review_packets.append(packet)
            if ask is not None or review_call is not None:
                return (ask or review_call)(system, user, default)
            finding = packet["investigator_conclusion"]
            actual = receipt_alternative(finding.get("primary_cause"), packet["cited_records"])
            checked = actual is not None and actual in finding.get("hypotheses", [])
            return {**default, "verdict": "ACCEPT" if checked else "HUMAN_REVIEW",
                    "feedback": "Source event and receipt times support the recorded alternative check." if checked else
                                "The alternative explanation lacks a source-backed check; human review is required.",
                    "alternatives_tested": "yes" if checked else "no"}

        return investigator.review(conclusion, records, checks, symptoms, ask=scripted_review, context=context,
                                   session=session, on_repair=on_repair)
    return types.SimpleNamespace(investigate=investigate, review=review, review_packets=review_packets,
                                 investigation_sessions=investigation_sessions, review_sessions=review_sessions)


class FixtureReviewTests(unittest.TestCase):
    def setUp(self):
        self.records = {"DEMO-SOURCE-TIMING": {"kind": "ScanEvent", "occurred_at": "2026-09-01T08:00:00+00:00",
                                               "recorded_at": "2026-09-01T08:02:00+00:00"}}
        self.alternative = receipt_alternative("CUSTODY_GAP", self.records)
        self.conclusion = {"primary_cause": "CUSTODY_GAP", "hypotheses": [self.alternative]}

    def test_reviewer_recomputes_source_times_and_uses_the_shared_session_and_context(self):
        from operations.investigator import Session
        module, session = fake_agents(), Session(4)
        context = {"review_round": 1, "citation_validity": {"all_valid": True}, "retrieved_uncited_records": {}}
        accepted = module.review(self.conclusion, self.records, [], [], context=context, session=session)
        self.assertEqual(accepted["verdict"], "ACCEPT")
        self.assertEqual(accepted["alternatives_tested"], "yes")
        self.assertEqual(self.alternative["contradicting_evidence_ids"], list(self.records))
        self.assertIs(module.review_sessions[0], session)
        self.assertEqual(session.budget.by_role, {"reviewer": 1})
        self.assertEqual(module.review_packets[0]["review_round"], 1)
        self.assertEqual(module.review_packets[0]["cited_records"], self.records)
        # An older event arriving at the same receipt time changes the evidence,
        # while the investigator's original claim is unchanged. It cannot pass.
        delayed = copy.deepcopy(self.records)
        delayed["DEMO-SOURCE-TIMING"]["occurred_at"] = "2026-09-01T06:00:00+00:00"
        self.assertEqual(receipt_alternative("CUSTODY_GAP", delayed)["supporting_evidence_ids"], list(delayed))
        reviewed = module.review(self.conclusion, delayed, [], [], context=context, session=session)
        self.assertEqual(reviewed["verdict"], "HUMAN_REVIEW")
        self.assertEqual(reviewed["alternatives_tested"], "no")
        self.assertEqual(session.budget.by_role, {"reviewer": 2})

    def test_missing_source_times_or_alternative_cannot_gain_default_acceptance(self):
        module = fake_agents()
        missing_time = copy.deepcopy(self.records)
        missing_time["DEMO-SOURCE-TIMING"].pop("recorded_at")
        for conclusion, records in ((self.conclusion, missing_time), ({**self.conclusion, "hypotheses": []}, self.records)):
            with self.subTest(conclusion=conclusion, records=records):
                result = module.review(conclusion, records, [], [])
                self.assertEqual(result["verdict"], "HUMAN_REVIEW")
                self.assertEqual(result["alternatives_tested"], "no")


class AgentPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.world = generate(Config(total=90))

    def live(self):
        d = Driver(self.world)
        s = OperationsStore(d, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world), agents=fake_agents())
        s.initialize(); development_reset(s); return s, d

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
        self.assertTrue(s.agents.review_packets)
        for packet in s.agents.review_packets:
            self.assertIn("citation_validity", packet)
            self.assertIn("retrieved_uncited_records", packet)
            conclusion = packet["investigator_conclusion"]
            actual = receipt_alternative(conclusion.get("primary_cause"), packet["cited_records"])
            if actual is not None:
                self.assertIn(actual, conclusion["hypotheses"])
        self.assertTrue(all(any(reviewed is investigated for investigated in s.agents.investigation_sessions)
                            for reviewed in s.agents.review_sessions))
        for run in runs:
            counters = run["investigation"]["model_calls"]
            self.assertGreater(counters["model_calls_used"], 0)
            self.assertEqual(counters, {key: run["investigation_log"][key] for key in counters})
            self.assertEqual(counters["model_calls_used"], run["latency"]["model"]["calls"])
        self.assertFalse(any(kind == "OpsOutcome" for kind, _ in d.ledger.values()))
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
        s.initialize(); development_reset(s); LiveSessionTests.run_world(self, s, rounds=400)
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

    def test_untested_alternative_cannot_authorize_an_action_or_falsely_resolve(self):
        def inconsistent_accept(system, user, default):
            return {**default, "verdict": "ACCEPT", "feedback": "No alternative was tested.", "alternatives_tested": "no"}

        for forged in (False, True):
            with self.subTest(inconsistent_accept=forged):
                module = fake_agents(review_call=inconsistent_accept if forged else None, test_alternative=False)
                driver = Driver(self.world)
                store = OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config,
                                        Reader(self.world), agents=module)
                store.initialize(); development_reset(store)
                LiveSessionTests.run_world(self, store, rounds=400)
                while store.process_one(manual=True).get("processed"):
                    pass
                store.execute_step(limit=50)
                store.outcome_step(limit=50)
                self.assertTrue(module.review_packets)
                runs = [json.loads(v["result_json"]) for k, v in driver.ledger.values() if k == "OpsRun"]
                reviewed = [run for run in runs if run["review"].get("model_verdict") is not None]
                self.assertTrue(reviewed)
                self.assertTrue(all(run["review"]["model_verdict"] == ("UNAVAILABLE" if forged else "HUMAN_REVIEW")
                                    for run in reviewed))
                if forged:
                    self.assertTrue(any("tested alternative" in (run["investigation_log"]["rounds"][-1]["review"].get("validation_error") or "")
                                        for run in reviewed))
                self.assertFalse(any(k in ("OpsExecution", "OpsOutcome") for k, _ in driver.ledger.values()))
                self.assertTrue(all(v["workflow_state"] not in ("AWAITING_OUTCOME", "ACTION_INITIATED", "RESOLVED")
                                    for k, v in driver.ledger.values() if k == "OpsCase"))


class OutcomeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.world = generate(Config(total=90))

    def test_live_world_resolves_only_from_later_verified_evidence_with_no_human(self):
        d = Driver(self.world)
        s = OperationsStore(d, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world), agents=fake_agents())
        s.initialize(); development_reset(s)
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
        self.assertEqual(outcomes, {})  # An unacknowledged request cannot create a verified outcome.
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
