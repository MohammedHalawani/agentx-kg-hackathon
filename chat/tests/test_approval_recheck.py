"""M2: an approval recomputes authority on the current case, and so does dispatch.

The product owner's decision (Option A, allow with recheck): at approval Suhail recomputes authority
against the latest evidence, symptoms, investigation run, reviewer decision and case state; a changed
context invalidates the approval and sends the case back for re-investigation and review; on a
human-investigation case only the evidence-gathering allowlist may be approved; a successful evidence
request never closes a case with another open dispute; the checks run again immediately before
execution, with audit records for both.
"""
import json
import unittest
from unittest import mock

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations.lifecycle import OperationsConflict
from tests import test_operations_store as _store
from tests.test_operations_store import Acknowledging, agent_investigator, approval_policy


class _Base(unittest.TestCase):
    setUpClass = classmethod(lambda cls: setattr(cls, "world", generate(Config(total=90))))
    make = _store.StoreTests.make
    approvable = _store.StoreTests.approvable

    def kind(self, driver, kind):
        return [v for k, v in driver.ledger.values() if k == kind]

    def audit(self, driver, case_id=None):
        return [v["event_type"] for v in sorted(self.kind(driver, "OpsAudit"), key=lambda a: str(a["wall_recorded_at"]))
                if case_id is None or v.get("case_id") == case_id]

    def audit_rows(self, driver, event_type):
        return [v for v in self.kind(driver, "OpsAudit") if v["event_type"] == event_type]

    def new_evidence(self, store):
        """A newly visible record for the shipment that does not bump the case version (for example a non-event
        record such as an address version, or one ingested between the version check and the approval)."""
        original = store.reader.evidence
        def evidence(sid, at):
            context = original(sid, at)
            extra = {"id": "DEMO-NEW-RECORD", "kind": "AddressVersion", "properties": {"recorded_at": str(at), "valid_from": str(at)}}
            return {**context, "nodes": [*context["nodes"], extra]}
        store.reader.evidence = evidence
        return original

    def add_symptom_through_monitor(self, store, driver, case, symptom):
        """The real monitor path: the shipment is re-checked and a newly observed symptom joins the open case."""
        def enqueue(tx):
            control = next(v for k, v in tx.ledger.values() if k == "OpsControl")
            control["monitor_queue"] = [case["shipment_id"]]
        driver.execute_write(enqueue)
        finding = {"open": True, "symptoms": sorted({*(case.get("symptom_codes") or []), symptom})}
        with mock.patch("operations.store.monitor_finding", return_value=finding):
            store.monitor_step()

    def adapter(self):
        calls = []
        class Adapter:
            def respond(self, execution, now):
                calls.append(execution["entity_id"])
                return {"acknowledged": True, "behaviour": "Request accepted."}
        return Adapter(), calls


class RecommendationToApprovalTests(_Base):
    def test_unchanged_context_is_approved_and_the_check_is_audited(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        self.assertTrue(case["recommendation"]["approvable"])
        self.assertFalse(case["recommendation"]["approval_context_stale"])
        approved = store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-ok")
        self.assertEqual(approved["workflow_state"], "AWAITING_OUTCOME")
        [checked] = self.audit_rows(driver, "APPROVAL_CONTEXT_CHECKED")
        detail = json.loads(checked["result"])
        self.assertEqual(detail["context"]["run_id"], case["last_run_id"])
        [execution] = self.kind(driver, "OpsExecution")
        context = json.loads(execution["approval_context_json"])
        self.assertEqual((context["run_id"], context["investigated_by"]), (case["last_run_id"], "agent"))

    def test_new_evidence_after_the_recommendation_refuses_approval_and_requeues(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        self.new_evidence(store)
        served = store.case_detail(result["case_id"])["recommendation"]
        self.assertEqual((served["approvable"], served["approval_rule"], served["approval_context_stale"]),
                         (False, "AUTH-20-approval-context-stale", True))
        with self.assertRaises(OperationsConflict) as refused:
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-stale")
        self.assertIn("AUTH-20-approval-context-stale", str(refused.exception))
        self.assertIn("evidence_count", str(refused.exception))
        after = store.case_detail(case["case_id"])
        self.assertEqual((after["workflow_state"], after["recommendation_id"]), ("OPEN", None))  # Requeued for re-investigation.
        self.assertEqual(self.kind(driver, "OpsExecution"), [])
        self.assertIn("APPROVAL_CONTEXT_STALE", self.audit(driver, case["case_id"]))
        with self.assertRaises(OperationsConflict):  # A retry with the same key replays the refusal.
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-stale")
        self.assertEqual(self.kind(driver, "OpsExecution"), [])

    def test_when_the_basis_keeps_changing_a_person_reviews_instead_of_another_automatic_run(self):
        from operations.store import MAX_SNAPSHOT_REFRESHES
        store, driver, result = self.approvable()
        def exhausted(tx):
            tx.ledger[result["case_id"]][1]["snapshot_refreshes"] = MAX_SNAPSHOT_REFRESHES
        driver.execute_write(exhausted)
        case = store.case_detail(result["case_id"])
        self.new_evidence(store)
        with self.assertRaises(OperationsConflict):
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-exhausted")
        after = store.case_detail(case["case_id"])
        self.assertEqual((after["workflow_state"], after["recommendation_id"]), ("HUMAN_REVIEW", None))
        self.assertEqual(self.kind(driver, "OpsExecution"), [])

    def test_a_symptom_added_after_the_recommendation_refuses_approval(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        stored = next(v for k, v in driver.ledger.values() if k == "OpsCase" and v["entity_id"] == case["case_id"])
        # A past-event symptom (not a standing or human-floor one): the monitor records it and leaves the case with the person.
        self.add_symptom_through_monitor(store, driver, stored, "WEIGHT_READ_DIFFERS")
        current = store.case_detail(case["case_id"])
        self.assertEqual(current["workflow_state"], "AWAITING_APPROVAL")
        # The operator reloads and approves at the new version: the version check passes, the context check does not.
        with self.assertRaises(OperationsConflict) as refused:
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", current["state_version"], "approve-new-symptom")
        self.assertIn("symptoms", str(refused.exception))
        self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "OPEN")
        self.assertEqual(self.kind(driver, "OpsExecution"), [])

    def test_a_standing_symptom_added_after_the_recommendation_requeues_the_case_before_any_approval(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        stored = next(v for k, v in driver.ledger.values() if k == "OpsCase" and v["entity_id"] == case["case_id"])
        self.add_symptom_through_monitor(store, driver, stored, "DELIVERY_PROOF_INCOMPLETE")
        current = store.case_detail(case["case_id"])
        # The monitor sent the investigated case back for re-investigation: there is nothing left to approve.
        self.assertEqual((current["workflow_state"], current["recommendation_id"]), ("OPEN", None))
        self.assertIn("REINVESTIGATION_QUEUED", self.audit(driver, case["case_id"]))
        with self.assertRaises(OperationsConflict):
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", current["state_version"], "approve-new-symptom")
        self.assertEqual(self.kind(driver, "OpsExecution"), [])

    def test_once_reinvestigations_are_used_up_the_approval_recheck_still_refuses_changed_symptoms(self):
        from operations.store import MAX_SYMPTOM_REINVESTIGATIONS
        store, driver, result = self.approvable()
        def used_up(tx):
            tx.ledger[result["case_id"]][1]["symptom_reinvestigations"] = MAX_SYMPTOM_REINVESTIGATIONS
        driver.execute_write(used_up)
        case = store.case_detail(result["case_id"])
        stored = next(v for k, v in driver.ledger.values() if k == "OpsCase" and v["entity_id"] == case["case_id"])
        self.add_symptom_through_monitor(store, driver, stored, "DELIVERY_PROOF_INCOMPLETE")
        current = store.case_detail(case["case_id"])
        self.assertEqual(current["workflow_state"], "AWAITING_APPROVAL")  # Not requeued again: bounded.
        self.assertIn("REINVESTIGATION_LIMIT", self.audit(driver, case["case_id"]))
        with self.assertRaises(OperationsConflict) as refused:
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", current["state_version"], "approve-after-limit")
        self.assertIn("symptoms", str(refused.exception))
        self.assertEqual(self.kind(driver, "OpsExecution"), [])


class ApprovalToExecutionTests(_Base):
    def approved(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-then-change")
        return store, driver, case

    def test_unchanged_context_is_dispatched_and_the_check_is_audited(self):
        store, driver, case = self.approved()
        store.adapter, calls = self.adapter()
        store.execute_step()
        self.assertEqual(len(calls), 1)
        self.assertIn("EXECUTION_CONTEXT_CHECKED", self.audit(driver, case["case_id"]))
        self.assertEqual(self.kind(driver, "OpsExecution")[0]["status"], "ACKNOWLEDGED")

    def test_new_evidence_between_approval_and_execution_refuses_dispatch(self):
        store, driver, case = self.approved()
        self.new_evidence(store)
        store.adapter, calls = self.adapter()
        store.execute_step()
        self.assertEqual(calls, [])  # Nothing dispatched.
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["status"], execution["permission_rule"]), ("REFUSED", "AUTH-20-approval-context-stale"))
        events = self.audit(driver, case["case_id"])
        self.assertIn("APPROVAL_CONTEXT_CHECKED", events)
        self.assertIn("EXECUTION_CONTEXT_STALE", events)
        self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "OPEN")  # Back for re-investigation.
        store.execute_step()
        self.assertEqual(calls, [])

    def test_a_symptom_added_between_approval_and_execution_refuses_dispatch(self):
        store, driver, case = self.approved()
        stored = next(v for k, v in driver.ledger.values() if k == "OpsCase" and v["entity_id"] == case["case_id"])
        self.add_symptom_through_monitor(store, driver, stored, "RECIPIENT_REPORTED_NOT_RECEIVED")
        store.adapter, calls = self.adapter()
        store.execute_step()
        self.assertEqual(calls, [])
        [stale] = self.audit_rows(driver, "EXECUTION_CONTEXT_STALE")
        self.assertIn("symptoms", stale["result"])
        self.assertEqual(self.kind(driver, "OpsExecution")[0]["status"], "REFUSED")


class HumanInvestigationApprovalTests(_Base):
    def human_case(self, action):
        """The independent reviewer asked for a person: the real policy routes the case to human review."""
        store, driver = self.make()
        store.agents = agent_investigator(verdicts=("HUMAN_REVIEW",), action=action)
        result = store.process_one(manual=True)
        case = store.case_detail(result["case_id"])
        self.assertEqual((case["workflow_state"], case["recommendation"]["risk_class"]), ("HUMAN_REVIEW", "HUMAN_REVIEW"))
        return store, driver, case

    def test_an_allowlisted_evidence_request_may_be_approved_but_only_a_person_closes(self):
        store, driver, case = self.human_case("REQUEST_RESCAN")
        self.assertTrue(case["recommendation"]["approvable"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-evidence")
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["decided_risk"], execution["closure"]), ("HUMAN_REVIEW", "HUMAN"))
        store.adapter, calls = self.adapter()
        store.execute_step()
        self.assertEqual(len(calls), 1)

    def test_consequential_actions_are_refused_before_a_human_finding(self):
        for action in ("REROUTE_TO_CONFIRMED_DESTINATION", "RETURN_TO_SENDER", "INITIATE_CUSTODY_RECONCILIATION",
                       "PRIORITIZE_NEXT_SESSION", "REQUEST_ADDRESS_CONFIRMATION"):
            store, driver, case = self.human_case(action)
            self.assertFalse(case["recommendation"]["approvable"], action)
            self.assertEqual(case["recommendation"]["approval_rule"], "AUTH-21-human-investigation-required", action)
            with self.assertRaises(OperationsConflict) as refused:
                store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-" + action[:16])
            self.assertIn("AUTH-21-human-investigation-required", str(refused.exception))
            self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "HUMAN_REVIEW")  # Not requeued: not stale.
            self.assertEqual(self.kind(driver, "OpsExecution"), [], action)
            self.assertIn("APPROVAL_REFUSED", self.audit(driver, case["case_id"]))

    def test_a_planted_consequential_execution_on_a_human_case_is_refused_at_dispatch(self):
        store, driver, case = self.human_case("REQUEST_RESCAN")
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-then-swap")
        def swap(tx):  # Whatever wrote it: a consequential action carried on an approval of an evidence request.
            for kind, e in tx.ledger.values():
                if kind == "OpsExecution":
                    e.update(action_type="REROUTE_TO_CONFIRMED_DESTINATION", decided_risk="APPROVAL_REQUIRED")
        driver.execute_write(swap)
        store.adapter, calls = self.adapter()
        store.execute_step()
        self.assertEqual(calls, [])
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["status"], execution["permission_rule"]), ("REFUSED", "AUTH-21-human-investigation-required"))


class EvidenceRequestClosureTests(_Base):
    def verified(self, exceptions, *, case_symptoms=("MILESTONE_OVERDUE",), other_case=None):
        """An approved evidence request, executed, then verified successful by the (mocked) verifier."""
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-closure")
        def setup(tx):
            for kind, e in tx.ledger.values():
                if kind == "OpsExecution":
                    e["closure"] = "AUTO"
                    e["approval_context_json"] = json.dumps({**json.loads(e["approval_context_json"]), "symptoms": sorted(case_symptoms),
                                                             "human_investigation": False})
                if kind == "OpsCase" and e["entity_id"] == case["case_id"]:
                    e["symptom_codes"] = sorted(case_symptoms)
            if other_case:
                tx.ledger["DEMO-OPS-CASE-OTHER"] = ("OpsCase", {**tx.ledger[case["case_id"]][1], "entity_id": "DEMO-OPS-CASE-OTHER",
                                                                "workflow_state": "HUMAN_REVIEW", "symptom_codes": list(other_case)})
        driver.execute_write(setup)
        store.adapter = Acknowledging()
        store.execute_step()
        current = store.case_detail(case["case_id"])
        self.assertEqual(current["workflow_state"], "AWAITING_OUTCOME")
        verdict = {"status": "success", "outcome_type": "barcode_corrected", "evidence_ids": [], "reason": "A readable rescan matches.",
                   "rule_id": "VERIFY-request-rescan-barcode-corrected", "expected_effect": "rescan"}
        with mock.patch("operations.outcome_engine.evaluate", return_value=verdict), \
             mock.patch("dataset_v2.derive.assess_shipment", return_value={"exceptions": exceptions, "delivery_assessment": []}):
            store.request_verification(case["case_id"], "DEMO-OPERATOR-LOCAL", current["state_version"], "verify-closure")
        outcome = next(v for k, v in driver.ledger.values() if k == "OpsOutcome")
        return store.case_detail(case["case_id"]), outcome, self.audit(driver, case["case_id"])

    def test_control_with_nothing_open_the_evidence_request_resolves(self):
        case, outcome, audit = self.verified([])
        self.assertEqual(case["workflow_state"], "RESOLVED")
        self.assertTrue(outcome["exception_cleared"])

    def test_a_visible_recipient_dispute_keeps_the_case_open(self):
        case, outcome, audit = self.verified([{"code": "DELIVERY_DISPUTE"}])
        self.assertEqual(case["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual((outcome["success"], outcome["exception_cleared"]), (True, False))
        self.assertIn("RECIPIENT_REPORTED_NOT_RECEIVED", outcome["remaining_symptoms"])
        self.assertNotIn("CASE_RESOLVED", audit)

    def test_a_recorded_failed_delivery_keeps_the_case_open(self):
        case, outcome, audit = self.verified([], case_symptoms=("BARCODE_READ_DIFFERS", "DELIVERY_ATTEMPT_FAILED"))
        self.assertEqual(case["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual(outcome["remaining_symptoms"], ["DELIVERY_ATTEMPT_FAILED"])
        self.assertIn("OUTCOME_VERIFIED_EXCEPTION_REMAINS", audit)

    def test_another_open_case_of_the_shipment_keeps_the_case_open(self):
        case, outcome, audit = self.verified([], other_case=("CUSTODY_REPORTS_CONFLICT",))
        self.assertEqual(case["workflow_state"], "HUMAN_REVIEW")
        self.assertIn("CUSTODY_REPORTS_CONFLICT", outcome["remaining_symptoms"])
        self.assertIn("OTHER_OPEN_CASES", audit)
        case, outcome, audit = self.verified([], other_case=("BARCODE_READ_DIFFERS",))
        self.assertEqual((case["workflow_state"], outcome["remaining_symptoms"]), ("HUMAN_REVIEW", ["OTHER_OPEN_CASE"]))


class Shipment000392SequenceTests(_Base):
    """The real failure: routed APPROVAL_REQUIRED on a wrong CUSTODY_GAP diagnosis; MANIFEST_CUSTODY_CONFLICT (a
    human-floor symptom) was then observed; a device sync was approved and executed anyway."""

    def test_the_000392_sequence_is_refused_and_the_floor_holds_afterwards(self):
        store, driver = self.make()
        store.agents = agent_investigator(cause="CUSTODY_GAP", action="REQUEST_DEVICE_SYNC")
        with approval_policy():  # The routing the wrong diagnosis received.
            result = store.process_one(manual=True)
        self.assertEqual(result["workflow_state"], "AWAITING_APPROVAL")
        stored = next(v for k, v in driver.ledger.values() if k == "OpsCase" and v["entity_id"] == result["case_id"])
        self.add_symptom_through_monitor(store, driver, stored, "MANIFEST_CUSTODY_CONFLICT")
        case = store.case_detail(result["case_id"])
        self.assertIn("MANIFEST_CUSTODY_CONFLICT", next(v for k, v in driver.ledger.values()
                                                       if k == "OpsCase" and v["entity_id"] == case["case_id"])["symptom_codes"])
        # The human-floor symptom arrived after the investigation: the monitor queued the case for re-investigation, so
        # the recommendation made without it is gone and cannot be approved.
        self.assertEqual((case["workflow_state"], case["recommendation"]), ("OPEN", None))
        with self.assertRaises(OperationsConflict):
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-000392")
        self.assertEqual(self.kind(driver, "OpsExecution"), [])
        self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "OPEN")
        self.assertIn("REINVESTIGATION_QUEUED", self.audit(driver, case["case_id"]))
        # Re-investigated with the same wrong diagnosis and the same routing: the floor symptom now makes it a
        # human-investigation case. A consequential action cannot be approved...
        store.agents = agent_investigator(cause="CUSTODY_GAP", action="REROUTE_TO_CONFIRMED_DESTINATION")
        with approval_policy():
            store.process_one(case_id=case["case_id"])
        case = store.case_detail(case["case_id"])
        self.assertEqual(case["recommendation"]["approval_rule"], "AUTH-21-human-investigation-required")
        with self.assertRaises(OperationsConflict):
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-000392-reroute")
        # ...and the device sync may run only as evidence gathering, which never closes the manifest conflict.
        store.request_reanalysis(case["case_id"], "DEMO-OPERATOR-LOCAL", case["state_version"], "reanalyze-000392")
        store.agents = agent_investigator(cause="CUSTODY_GAP", action="REQUEST_DEVICE_SYNC")
        with approval_policy():
            store.process_one(case_id=case["case_id"])
        case = store.case_detail(case["case_id"])
        self.assertTrue(case["recommendation"]["approvable"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-000392-sync")
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["decided_risk"], execution["closure"]), ("HUMAN_REVIEW", "HUMAN"))
        store.adapter = Acknowledging()
        store.execute_step()
        current = store.case_detail(case["case_id"])
        verdict = {"status": "success", "outcome_type": "delayed_upload_received", "evidence_ids": [], "reason": "Late uploads arrived.",
                   "rule_id": "VERIFY-request-device-sync-delayed-upload-received", "expected_effect": "sync"}
        with mock.patch("operations.outcome_engine.evaluate", return_value=verdict), \
             mock.patch("dataset_v2.derive.assess_shipment", return_value={"exceptions": [], "delivery_assessment": []}):
            store.request_verification(case["case_id"], "DEMO-OPERATOR-LOCAL", current["state_version"], "verify-000392")
        final = store.case_detail(case["case_id"])
        self.assertNotEqual(final["workflow_state"], "RESOLVED")
        self.assertIn("MANIFEST_CUSTODY_CONFLICT", final["outcome"]["remaining_symptoms"])


if __name__ == "__main__":
    unittest.main()
