"""AUTH-27: a reviewer's doubt (REVISE or INSUFFICIENT_EVIDENCE) lets only a safe, reversible evidence-gathering request
proceed, under every other authority rule, and never counts as acceptance.

The boundaries tested here: every other reviewer verdict, every action outside the evidence-gathering allowlist, every
human-investigation rule, approval-required and prohibited actions are decided exactly as before; the doubt is recorded;
a verified success of an action that ran under a doubt does not resolve the case, which is investigated and reviewed
again, and resolves only when that review accepts and the exception is still cleared. Nothing is executed from the
reassessment run.

Policy tests are pure. Store tests use the in-memory ledger with a scripted investigator and reviewer: no database, no
model. Where a store test needs an automatic decision, the deterministic fact checks are held clean for the scripted
conclusion, and where it needs "the exception is cleared", the verifier's verdict and the monitor's finding are scripted;
the store's own closure test (remaining_symptoms) and the real authority policy run unpatched unless a test says so.
"""
import unittest
from unittest import mock

from operations import authority as policy
from operations.authority import (ACTIONS, EVIDENCE_GATHERING, REVIEWER_DOUBT_VERDICTS, authorize, execution_permission, recheck_authority,
                                  reviewer_doubt_allows, rule_id)
from tests import test_material_reinvestigation as base
from tests.test_operations_store import Acknowledging

RULE = "AUTH-27-reviewer-doubt-evidence-gathering"
# A diagnosis each action addresses (an established cause, not an abstention: that has its own floor, tested below).
ADDRESSES = {a: sorted(ACTIONS[a][1] - policy.ABSTENTION_CODES)[0] for a in ACTIONS if ACTIONS[a][1]}


def decide(action, verdict, **flags):
    options = {"evidence_conflict": False, "synthetic": True, "live_session": True, **flags}
    return authorize(action, [ADDRESSES.get(action, "UNKNOWN")], review_verdict=verdict, **options)


def recheck(action, verdict, symptoms=(), **inputs):
    return recheck_authority(action, {"diagnosis_codes": [ADDRESSES.get(action, "UNKNOWN")], "review_verdict": verdict, **inputs}, list(symptoms))


class PolicyTests(unittest.TestCase):
    def test_the_allowlist_is_the_existing_evidence_gathering_set(self):
        self.assertEqual(EVIDENCE_GATHERING, frozenset(("REQUEST_RESCAN", "REQUEST_REWEIGH", "REQUEST_DEVICE_SYNC",
                                                        "REQUEST_ADDITIONAL_EVIDENCE", "REQUEST_HUB_CHECK")))
        self.assertEqual(REVIEWER_DOUBT_VERDICTS, frozenset(("REVISE", "INSUFFICIENT_EVIDENCE")))
        for action in EVIDENCE_GATHERING:
            self.assertEqual(ACTIONS[action][0], "AUTO", action)   # Each was already an automatic-class action.

    def test_a_doubt_lets_an_evidence_request_run_and_reserves_resolution_for_a_reassessment(self):
        for verdict in sorted(REVIEWER_DOUBT_VERDICTS):
            for action in sorted(EVIDENCE_GATHERING):
                risk, reason = decide(action, verdict)
                self.assertEqual((risk, rule_id(reason)), ("AUTO", RULE), (action, verdict))
                self.assertEqual(recheck(action, verdict)[::2], ("AUTO", "REASSESS"), (action, verdict))
                self.assertEqual(execution_permission(action, "AUTO_POLICY", risk)[:2], (True, "AUTH-10-auto-allowlist"))

    def test_an_accepted_review_is_decided_as_before(self):
        for action in sorted(EVIDENCE_GATHERING):
            risk, reason = decide(action, "ACCEPT")
            self.assertEqual((risk, rule_id(reason)), ("AUTO", "AUTH-10-auto-allowlist"))
            self.assertEqual(recheck(action, "ACCEPT")[2], "AUTO")

    def test_every_other_reviewer_verdict_still_blocks_an_evidence_request(self):
        for verdict, rule in (("HUMAN_REVIEW", "AUTH-03-reviewer-human"), ("ESCALATE", "AUTH-03-reviewer-human"),
                              ("UNAVAILABLE", "AUTH-02-model-degraded")):
            for action in sorted(EVIDENCE_GATHERING):
                risk, reason = decide(action, verdict)
                self.assertEqual((risk, rule_id(reason)), ("HUMAN_REVIEW", rule), (action, verdict))
        for verdict in (None, "REJECT", "reject", ""):      # No acceptance and no recognised doubt: never automatic.
            self.assertFalse(reviewer_doubt_allows("REQUEST_RESCAN", verdict))
            self.assertEqual(decide("REQUEST_RESCAN", verdict)[0], "APPROVAL_REQUIRED", verdict)
        self.assertEqual(decide("REQUEST_RESCAN", "REVISE", degraded=True)[0], "HUMAN_REVIEW")

    def test_an_action_outside_the_allowlist_is_never_made_automatic_by_a_doubt(self):
        for action, (risk_class, _, _, _) in sorted(ACTIONS.items()):
            if action in EVIDENCE_GATHERING:
                continue
            for verdict in sorted(REVIEWER_DOUBT_VERDICTS):
                self.assertFalse(reviewer_doubt_allows(action, verdict), action)
                risk, reason = decide(action, verdict)
                self.assertNotEqual(risk, "AUTO", (action, verdict))
                self.assertNotEqual(rule_id(reason), RULE, (action, verdict))
                if risk_class == "PROHIBITED":
                    self.assertEqual(risk, "PROHIBITED", action)
                if risk_class == "APPROVAL_REQUIRED":
                    self.assertIn(risk, ("APPROVAL_REQUIRED", "HUMAN_REVIEW"), action)
        # A reviewer's insufficient-evidence verdict on any other action still goes to a person.
        self.assertEqual(rule_id(decide("INITIATE_CUSTODY_RECONCILIATION", "INSUFFICIENT_EVIDENCE")[1]), "AUTH-25-reviewer-insufficient-evidence")
        for action in ("COMPENSATION", "LIABILITY_DETERMINATION"):
            for path in ("AUTO_POLICY", "OPERATOR_APPROVAL"):
                self.assertEqual(execution_permission(action, path, "AUTO")[:2], (False, "AUTH-13-prohibited"))

    def test_every_human_investigation_rule_still_wins_over_a_doubt(self):
        for flag, rule in (({"contractor_custody": True}, "AUTH-04-contractor-custody"), ({"physical_check": True}, "AUTH-23-physical-check-requested"),
                           ({"evidence_conflict": True}, "AUTH-06-evidence-conflict")):
            for verdict in sorted(REVIEWER_DOUBT_VERDICTS):
                risk, reason = decide("REQUEST_RESCAN", verdict, **flag)
                self.assertEqual((risk, rule_id(reason)), ("HUMAN_REVIEW", rule), (flag, verdict))
        for code in sorted(policy.SENSITIVE_CODES):
            risk, reason = authorize("REQUEST_ADDITIONAL_EVIDENCE", [code, "PROOF_INSUFFICIENT"], review_verdict="REVISE", evidence_conflict=False,
                                     synthetic=True, live_session=True)
            self.assertEqual((risk, rule_id(reason)), ("HUMAN_REVIEW", "AUTH-05-sensitive"), code)

    def test_the_other_automatic_conditions_still_apply_under_a_doubt(self):
        risk, reason = authorize("REQUEST_RESCAN", ["HUB_DELAY"], review_verdict="REVISE", evidence_conflict=False, synthetic=True, live_session=True)
        self.assertEqual((risk, rule_id(reason)), ("APPROVAL_REQUIRED", "AUTH-07-action-mismatch"))
        self.assertEqual(rule_id(decide("REQUEST_RESCAN", "REVISE", live_session=False)[1]), "AUTH-08-not-live-synthetic")
        self.assertEqual(rule_id(decide("REQUEST_RESCAN", "REVISE", synthetic=False)[1]), "AUTH-08-not-live-synthetic")

    def test_a_closure_already_reserved_for_a_person_stays_reserved(self):
        for symptom in sorted(policy.HUMAN_FLOOR_SYMPTOMS):
            risk, _, closure = recheck("REQUEST_RESCAN", "REVISE", [symptom])
            self.assertEqual((risk, closure), ("AUTO", "HUMAN"), symptom)
        risk, _, closure = recheck_authority("REQUEST_ADDITIONAL_EVIDENCE", {"diagnosis_codes": ["INSUFFICIENT_EVIDENCE"], "review_verdict": "REVISE"}, [])
        self.assertEqual((risk, closure), ("AUTO", "HUMAN"))


class Scripted(base.Scripted):
    def __init__(self, verdicts, cause="BARCODE_MISMATCH", action="REQUEST_RESCAN"):
        super().__init__(None, verdicts)
        self.cause, self.action = cause, action


def clean_fact_checks():
    """The deterministic fact checks held clean for the scripted conclusion (which cites nothing specific): the authority
    decision under test is then the policy's own."""
    from operations import checks
    real = checks.fact_checks
    return mock.patch("operations.checks.fact_checks",
                      side_effect=lambda inv, tools: {**real(inv, tools), "unsupported": False, "sensitive": False, "contractor_custody": False})


SUCCESS = {"status": "success", "outcome_type": "barcode_corrected", "evidence_ids": [], "reason": "The requested rescan read the manifest barcode."}
FAILURE = {"status": "failure", "outcome_type": "barcode_still_differs", "evidence_ids": [], "reason": "The requested rescan read another barcode."}


class StoreTests(base._Base):
    def investigate(self, verdicts=("REVISE", "REVISE", "REVISE"), clean=True, **script):
        store, driver = self.make()
        store.agents = Scripted(verdicts, **script)
        if clean:
            with clean_fact_checks():
                result = store.process_one(manual=True)
        else:
            result = store.process_one(manual=True)
        return store, driver, result

    def decision(self, driver):
        import json
        return json.loads(self.audit(driver, "AUTHORITY_DECISION")[-1]["result"])

    def events(self, driver):
        return [a["event_type"] for a in self.kind(driver, "OpsAudit") if a["event_type"] != "PIPELINE_STAGE"]

    def verified(self, store, driver, verdict=SUCCESS, cleared=True):
        """The execution adapter accepts the request and the verifier returns `verdict` an hour later."""
        store.adapter = Acknowledging()
        self.assertEqual(len(store.execute_step()), 1)
        self.advance(driver, 3600)
        with mock.patch("operations.outcome_engine.evaluate", return_value=verdict), \
                mock.patch("operations.store.monitor_finding", return_value={"open": False, "symptoms": []}), \
                (mock.patch("operations.store.remaining_symptoms", return_value=[]) if cleared else mock.patch("operations.store.STANDING_SYMPTOMS", policy.HUMAN_FLOOR_SYMPTOMS | {"MILESTONE_OVERDUE"})):
            return store.outcome_step(limit=5, force=True)

    def reassess(self, store, verdicts, cleared=True, symptoms=()):
        store.agents = Scripted(verdicts)
        with clean_fact_checks(), mock.patch("operations.store.monitor_finding", return_value={"open": bool(symptoms), "symptoms": list(symptoms)}), \
                (mock.patch("operations.store.remaining_symptoms", return_value=[]) if cleared else mock.patch("operations.store.remaining_symptoms", return_value=["MILESTONE_OVERDUE"])):
            return store.process_one(manual=True)

    # The decision and what is recorded.

    def test_a_revise_lets_the_rescan_run_and_records_the_doubt_without_accepting_the_investigation(self):
        store, driver, result = self.investigate()
        self.assertEqual(result["workflow_state"], "AWAITING_OUTCOME")
        decision = self.decision(driver)
        self.assertEqual((decision["rule_id"], decision["risk_class"], decision["closure"], decision["inputs"]["review_verdict"]),
                         (RULE, "AUTO", "REASSESS", "REVISE"))
        execution, = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["action_type"], execution["authority"], execution["closure"]), ("REQUEST_RESCAN", "AUTO_POLICY", "REASSESS"))
        doubt, = self.audit(driver, "REVIEWER_DOUBT_RECORDED")
        self.assertIn("REVISE", doubt["result"])
        self.assertIn("not an acceptance", doubt["result"])
        # Not an acceptance anywhere: the reviews say REVISE, the case has no accepted diagnosis, the detail labels it.
        self.assertEqual({r["model_verdict"] for r in self.kind(driver, "OpsReview")}, {"REVISE"})
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["diagnosis_available"], case["cause_codes"]), (False, []))
        detail = store.case_detail(result["case_id"])
        self.assertEqual((detail["diagnosis"]["available"], detail["diagnosis"]["reason"]), (False, "review_not_accepted"))
        self.assertFalse(detail["diagnosis"]["review"]["accepted"])
        self.assertEqual(self.audit(driver, "RECOMMENDATION_READY"), [])

    def test_the_deterministic_fact_checks_still_send_a_doubted_request_to_a_person(self):
        store, driver, result = self.investigate(clean=False)     # The scripted conclusion fails the real fact checks.
        # Another rule holds the request back, so the reviewer's rejection stands as before: escalated, not approvable.
        self.assertEqual(result["workflow_state"], "ESCALATED")
        self.assertEqual(self.decision(driver)["rule_id"], "AUTH-16-review-rejected")
        self.assertEqual(self.kind(driver, "OpsExecution"), [])
        self.assertFalse(store.case_detail(result["case_id"])["recommendation"]["approvable"])
        self.assertEqual(self.audit(driver, "REVIEWER_DOUBT_RECORDED"), [])

    def test_a_reviewer_who_asks_for_a_person_or_is_unavailable_still_stops_everything(self):
        for verdicts, rule in ((("HUMAN_REVIEW",), "AUTH-03-reviewer-human"), (("ESCALATE",), "AUTH-03-reviewer-human"),
                               (("UNAVAILABLE",), "AUTH-02-model-degraded")):
            store, driver, result = self.investigate(verdicts)
            self.assertEqual(result["workflow_state"], "HUMAN_REVIEW", verdicts)
            self.assertEqual(self.decision(driver)["rule_id"], rule, verdicts)
            self.assertEqual(self.kind(driver, "OpsExecution"), [], verdicts)

    def test_a_doubt_on_an_action_outside_the_allowlist_is_rejected_as_before(self):
        for cause, action in (("CUSTODY_GAP", "INITIATE_CUSTODY_RECONCILIATION"), ("ADDRESS_CONFLICT", "REROUTE_TO_CONFIRMED_DESTINATION"),
                              ("RECIPIENT_UNAVAILABLE", "RETURN_TO_SENDER"), ("DELIVERY_DISPUTE", "DELIVERY_DISPUTE_REVIEW")):
            store, driver, result = self.investigate(cause=cause, action=action)
            self.assertEqual(result["workflow_state"], "ESCALATED", action)
            self.assertEqual(self.decision(driver)["rule_id"], "AUTH-16-review-rejected", action)
            self.assertEqual(self.kind(driver, "OpsExecution"), [], action)
            self.assertFalse(store.case_detail(result["case_id"])["recommendation"]["approvable"], action)

    def test_an_approval_required_action_is_still_held_for_a_person_when_the_reviewer_accepts(self):
        store, driver, result = self.investigate(("ACCEPT",), cause="ADDRESS_CONFLICT", action="REROUTE_TO_CONFIRMED_DESTINATION")
        self.assertEqual(result["workflow_state"], "AWAITING_APPROVAL")
        self.assertEqual(self.kind(driver, "OpsExecution"), [])

    def test_a_guard_rejection_is_not_a_doubt(self):
        rejected = {"verdict": "reject", "reason_code": "EVIDENCE_NOT_BOUND", "feedback": "Evidence is not bound to this shipment."}
        with mock.patch("operations.worker.review", return_value=rejected):      # The deterministic guard, before any model review.
            store, driver, result = self.investigate()
        self.assertEqual(result["workflow_state"], "ESCALATED")
        self.assertEqual(self.kind(driver, "OpsExecution"), [])
        self.assertEqual(self.audit(driver, "REVIEWER_DOUBT_RECORDED"), [])

    # After the action: verification, reassessment, resolution.

    def test_a_verified_success_under_a_doubt_does_not_resolve_and_queues_the_reassessment(self):
        store, driver, result = self.investigate()
        self.verified(store, driver)
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], case.get("is_terminal"), case.get("verified_outcome_id")), ("OPEN", None, None))
        outcome, = self.kind(driver, "OpsOutcome")
        self.assertEqual(case["reassess_outcome_id"], outcome["entity_id"])
        self.assertEqual((outcome["success"], outcome["verification_status"]), (True, "VERIFIED"))
        self.assertEqual(len(self.audit(driver, "OUTCOME_VERIFIED_REASSESSMENT")), 1)
        self.assertEqual(self.audit(driver, "CASE_RESOLVED"), [])

    def test_the_case_resolves_only_when_the_reassessment_is_accepted_and_the_exception_is_cleared(self):
        store, driver, result = self.investigate()
        self.verified(store, driver)
        again = self.reassess(store, ("ACCEPT",))
        self.assertEqual(again["workflow_state"], "RESOLVED")
        case = self.stored(driver, result["case_id"])
        outcome, = self.kind(driver, "OpsOutcome")
        self.assertEqual((case["workflow_state"], case["is_terminal"], case["verified_outcome_id"], case["operational_status"], case.get("reassess_outcome_id")),
                         ("RESOLVED", True, outcome["entity_id"], "RESOLVED", None))
        events = self.events(driver)
        self.assertLess(events.index("OUTCOME_VERIFIED_REASSESSMENT"), events.index("REASSESSMENT_ACCEPTED"))
        self.assertEqual(events.count("CASE_RESOLVED"), 1)
        self.assertEqual(len(self.kind(driver, "OpsExecution")), 1)      # The reassessment executed nothing.
        self.assertEqual(len(self.audit(driver, "REVIEWER_DOUBT_RECORDED")), 1)   # The first doubt is still on record.
        self.assertEqual(len(self.kind(driver, "OpsRun")), 2)

    def test_a_reassessment_the_reviewer_does_not_accept_goes_to_a_person_and_executes_nothing(self):
        for verdicts in (("REVISE", "REVISE", "REVISE"), ("HUMAN_REVIEW",), ("UNAVAILABLE",)):
            store, driver, result = self.investigate()
            self.verified(store, driver)
            again = self.reassess(store, verdicts)
            self.assertEqual(again["workflow_state"], "HUMAN_REVIEW", verdicts)
            case = self.stored(driver, result["case_id"])
            self.assertEqual((case["workflow_state"], case.get("is_terminal"), case.get("reassess_outcome_id")), ("HUMAN_REVIEW", None, None), verdicts)
            self.assertEqual(len(self.kind(driver, "OpsExecution")), 1, verdicts)      # No second automatic action, no loop.
            self.assertEqual(len(self.audit(driver, "REASSESSMENT_NOT_ACCEPTED")), 1, verdicts)
            self.assertEqual(self.audit(driver, "CASE_RESOLVED"), [], verdicts)
            self.assertFalse(store.process_one()["processed"], verdicts)

    def test_an_accepted_reassessment_does_not_resolve_while_the_exception_remains(self):
        store, driver, result = self.investigate()
        self.verified(store, driver)
        again = self.reassess(store, ("ACCEPT",), cleared=False)
        self.assertEqual(again["workflow_state"], "HUMAN_REVIEW")
        self.assertIn("the exception remains", self.audit(driver, "REASSESSMENT_NOT_ACCEPTED")[0]["result"])
        self.assertEqual(self.audit(driver, "CASE_RESOLVED"), [])

    def test_a_verified_success_that_leaves_the_exception_goes_to_a_person_without_a_reassessment(self):
        store, driver, result = self.investigate()
        store.adapter = Acknowledging()
        store.execute_step()
        self.advance(driver, 3600)
        with mock.patch("operations.outcome_engine.evaluate", return_value=SUCCESS), \
                mock.patch("operations.store.monitor_finding", return_value={"open": True, "symptoms": ["MILESTONE_OVERDUE"]}):
            store.outcome_step(limit=5, force=True)       # The store's own closure test, unpatched.
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], case.get("reassess_outcome_id")), ("HUMAN_REVIEW", None))
        self.assertEqual(len(self.audit(driver, "OUTCOME_VERIFIED_EXCEPTION_REMAINS")), 1)
        self.assertEqual(self.audit(driver, "OUTCOME_VERIFIED_REASSESSMENT"), [])

    def test_a_failed_action_under_a_doubt_stays_unresolved(self):
        store, driver, result = self.investigate()
        self.verified(store, driver, verdict=FAILURE)
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], case.get("is_terminal"), case.get("reassess_outcome_id")), ("HUMAN_REVIEW", None, None))
        self.assertEqual(len(self.audit(driver, "OUTCOME_FAILED")), 1)
        self.assertEqual(self.audit(driver, "CASE_RESOLVED"), [])

    def test_an_accepted_first_review_still_resolves_directly_on_a_verified_success(self):
        store, driver, result = self.investigate(("ACCEPT",))
        self.assertEqual(self.kind(driver, "OpsExecution")[0]["closure"], "AUTO")
        self.verified(store, driver)
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], case.get("reassess_outcome_id")), ("RESOLVED", None))
        self.assertEqual(self.audit(driver, "REVIEWER_DOUBT_RECORDED"), [])


if __name__ == "__main__":
    unittest.main()
