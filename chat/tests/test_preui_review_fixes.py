"""Findings of the independent safety review of the pre-UI fixes, each with a regression test.

1. The queue (and Explore) never serves rule triage or an unaccepted investigation as the case's summary, category or
   cause; rule codes are kept apart and labelled.
3. An investigation the independent reviewer did not accept is not served as the diagnosis.
4. A refused approval never moves a case a person holds back into automatic re-investigation; an executed
   recommendation cannot be approved again.
5. While a re-analysis is queued, the earlier run's review rounds and stage events are not served as current.
6. An outcome or execution of an earlier cycle is marked as such.
7. Every successful action (not only evidence requests) is checked against open disputes and sibling cases.
8. A stored agent run never serves a rule-definition sentence as a hypothesis's Arabic summary.
10. The live development reset checks the investigation worker and resets ingestion under one lock, and audits refusal.
(2, the blame filter, is in test_carried_items.)
"""
import json
import os
import unittest
from unittest import mock

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations.lifecycle import OperationsConflict
from operations.store import DEV_RESET_ENV, MONITOR_SUMMARY, MONITOR_SUMMARY_PENDING, symptom_status
from tests import test_operations_store as _store
from tests.test_operations_store import Acknowledging, agent_investigator, approval_policy
from tests.test_operations_read_model import make_reader


class _Base(unittest.TestCase):
    setUpClass = classmethod(lambda cls: setattr(cls, "world", generate(Config(total=90))))
    make = _store.StoreTests.make
    approvable = _store.StoreTests.approvable
    processed = _store.StoreTests.processed

    def kind(self, driver, kind):
        return [v for k, v in driver.ledger.values() if k == kind]

    def stored(self, driver, case_id):
        return next(v for k, v in driver.ledger.values() if k == "OpsCase" and v["entity_id"] == case_id)

    def audit(self, driver, case_id):
        return [v["event_type"] for v in sorted(self.kind(driver, "OpsAudit"), key=lambda a: str(a["wall_recorded_at"]))
                if v.get("case_id") == case_id]

    def verify(self, store, case, *, exceptions=(), delivered=False, outcome_type="barcode_corrected", key="verify"):
        """The independent verifier finds the action's effect (mocked), with `exceptions` still visible."""
        current = store.case_detail(case["case_id"])
        verdict = {"status": "success", "outcome_type": outcome_type, "evidence_ids": [], "reason": "The action's effect was observed.",
                   "rule_id": "VERIFY-x", "expected_effect": "x"}
        assessment = {"exceptions": [{"code": c} for c in exceptions],
                      "delivery_assessment": [{"assessment": "CORROBORATED_DELIVERY"}] if delivered else []}
        with mock.patch("operations.outcome_engine.evaluate", return_value=verdict), \
             mock.patch("dataset_v2.derive.assess_shipment", return_value=assessment):
            store.request_verification(case["case_id"], "DEMO-OPERATOR-LOCAL", current["state_version"], key)
        return store.case_detail(case["case_id"])


class QueueSummaryTests(_Base):
    """Finding 1: what the case record (and so the queue) says about itself comes from an accepted diagnosis only."""

    def test_a_rules_only_run_leaves_the_monitor_summary_and_keeps_rule_codes_apart(self):
        store, driver, result = self.processed()  # No investigator: rule triage only.
        case = self.stored(driver, result["case_id"])
        run = json.loads(next(v for v in self.kind(driver, "OpsRun") if v["case_id"] == result["case_id"])["result_json"])
        labels = run["result"]["operational_labels"]
        self.assertTrue(labels)  # Rule triage did produce codes ...
        self.assertEqual(case["cause_codes"], [])  # ... and none of them is the case's cause,
        self.assertEqual(case["issue_summary"], MONITOR_SUMMARY)  # nor its summary,
        self.assertEqual(case["operational_status"], symptom_status(case["symptom_codes"]))  # nor its status.
        self.assertFalse(case["diagnosis_available"])
        self.assertEqual(case["rule_signal_codes"], labels)  # Kept apart, under a name that says what they are.
        self.assertNotIn(case["issue_summary"], [d.get("summary_en") for d in run["result"]["diagnoses"]])

    def test_an_accepted_agent_diagnosis_describes_the_case_until_it_is_queued_again(self):
        store, driver, result = self.approvable()
        case = self.stored(driver, result["case_id"])
        run = json.loads(next(v for v in self.kind(driver, "OpsRun") if v["case_id"] == result["case_id"])["result_json"])
        self.assertTrue(case["diagnosis_available"])
        self.assertEqual(case["cause_codes"], ["BARCODE_MISMATCH"])
        self.assertEqual(case["issue_summary"], run["investigation"]["hypotheses"][0]["assessment"])
        self.assertEqual(case["rule_signal_codes"], [])
        detail = store.case_detail(result["case_id"])
        store.request_reanalysis(result["case_id"], "DEMO-OPERATOR-LOCAL", detail["state_version"], "reanalyze-queue")
        queued = self.stored(driver, result["case_id"])
        self.assertEqual((queued["workflow_state"], queued["diagnosis_available"], queued["cause_codes"], queued["issue_summary"]),
                         ("OPEN", False, [], MONITOR_SUMMARY_PENDING))
        self.assertEqual(queued["operational_status"], symptom_status(queued["symptom_codes"]))

    def test_an_investigation_the_reviewer_did_not_accept_does_not_describe_the_case(self):
        for verdicts in (("HUMAN_REVIEW",), ("REVISE", "REVISE", "REVISE")):
            store, driver = self.make()
            store.agents = agent_investigator(verdicts=verdicts)
            result = store.process_one(manual=True)
            case = self.stored(driver, result["case_id"])
            self.assertEqual((case["diagnosis_available"], case["cause_codes"], case["issue_summary"], case["rule_signal_codes"]),
                             (False, [], MONITOR_SUMMARY, []), verdicts)

    def test_the_queue_serves_category_cause_and_summary_only_from_an_accepted_diagnosis(self):
        from operations.read_model import CASE_STATUS, QUEUE_BASE, QUEUE_PROJECTION, EXPLORE_BASE, EXPLORE_PROJECTION
        calls = []
        def handler(query, params):
            calls.append((query, params))
            return [{"total": 0}] if "count(*) AS total" in query else []
        reader, _ = make_reader(handler)
        reader.queue(limit=25, operational_status="SLA_RISK", cause="ADDRESS_CONFLICT")
        query, params = next((q, p) for q, p in calls if "AS item" in q)
        self.assertEqual(params["monitor_summary"], MONITOR_SUMMARY)
        diagnosed = "coalesce(c.diagnosis_available,false)"
        for served in (f"issue_summary:CASE WHEN {diagnosed} THEN coalesce(c.issue_summary,$monitor_summary) ELSE $monitor_summary END",
                       f"category:CASE WHEN {diagnosed} THEN head(c.cause_codes) ELSE null END",
                       f"cause_codes:(CASE WHEN {diagnosed} THEN coalesce(c.cause_codes,[]) ELSE [] END)",
                       f"summary_source:CASE WHEN {diagnosed} THEN 'agent_diagnosis' ELSE 'monitor' END",
                       "rule_signal_codes:coalesce(c.rule_signal_codes,[])", f"operational_status:{CASE_STATUS}"):
            self.assertIn(served, query)
        # Filters use the same served values, so a legacy record's rule-derived status or codes never match.
        self.assertIn(f"{CASE_STATUS}=$operational_status", QUEUE_BASE)
        self.assertIn(f"$cause IN (CASE WHEN {diagnosed}", QUEUE_BASE)
        self.assertNotIn("c.cause_codes,[]) AS codes", EXPLORE_BASE)
        self.assertIn("'MILESTONE_OVERDUE' IN symptoms", EXPLORE_BASE)
        self.assertIn("diagnosis_available:coalesce(c.diagnosis_available,false)", EXPLORE_PROJECTION)
        for query in (QUEUE_BASE, QUEUE_PROJECTION, EXPLORE_BASE, EXPLORE_PROJECTION):
            self.assertNotIn("__", query.replace("__CASE", "").replace("$", ""))  # Every placeholder substituted.
        # The served status follows the store's symptom policy, in order, for a case without an accepted diagnosis.
        from operations.store import SYMPTOM_STATUS
        positions = [CASE_STATUS.index(f"WHEN '{symptom}' IN coalesce(c.symptom_codes,[]) THEN '{status}'") for symptom, status in SYMPTOM_STATUS]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(CASE_STATUS.endswith("ELSE 'NEEDS_ATTENTION' END)"))


class UnacceptedInvestigationTests(_Base):
    """Finding 3: only an investigation the independent reviewer accepted is the diagnosis."""

    def test_a_rejected_or_human_review_investigation_is_served_apart_and_labelled(self):
        for verdicts, state, verdict, reason in ((("REVISE", "REVISE", "REVISE"), "ESCALATED", "reject", "MODEL_REVISE"),
                                                 (("HUMAN_REVIEW",), "HUMAN_REVIEW", "human_review", "MODEL_HUMAN_REVIEW"),
                                                 (("UNAVAILABLE",), "HUMAN_REVIEW", "review_unavailable", "REVIEWER_UNAVAILABLE")):
            store, driver = self.make()
            store.agents = agent_investigator(verdicts=verdicts)
            result = store.process_one(manual=True)
            detail = store.case_detail(result["case_id"])
            diagnosis = detail["diagnosis"]
            self.assertEqual(detail["workflow_state"], state, verdicts)
            self.assertEqual((diagnosis["available"], diagnosis["reason"], diagnosis["primary_cause"], diagnosis["hypotheses"]),
                             (False, "review_not_accepted", None, []), verdicts)
            self.assertEqual(diagnosis["review"], {"verdict": verdict, "model_verdict": detail["review"].get("model_verdict"),
                                                   "reason_code": reason, "accepted": False})
            unaccepted = diagnosis["unaccepted_investigation"]
            self.assertEqual((unaccepted["accepted"], unaccepted["primary_cause"], unaccepted["run_id"]),
                             (False, "BARCODE_MISMATCH", detail["last_run_id"]))
            self.assertEqual(unaccepted["review"]["verdict"], verdict)
            self.assertTrue(unaccepted["hypotheses"])

    def test_an_accepted_investigation_carries_its_review(self):
        store, driver, result = self.approvable()
        diagnosis = store.case_detail(result["case_id"])["diagnosis"]
        self.assertTrue(diagnosis["available"])
        self.assertEqual(diagnosis["review"], {"verdict": "accept", "model_verdict": "ACCEPT", "reason_code": "MODEL_ACCEPT", "accepted": True})
        self.assertIsNone(diagnosis["unaccepted_investigation"])


class ExecutedRecommendationTests(_Base):
    """Finding 4: a refused approval leaves a person's case where it is; an executed recommendation is not approvable."""

    def approved_and_verified(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-once")
        store.adapter = Acknowledging()
        store.execute_step()
        # The verifier observes the action's effect, but the exception is still there: the case goes to a person.
        after = self.verify(store, case, exceptions=["MISSED_MILESTONE"], key="verify-remains")
        self.assertEqual(after["workflow_state"], "HUMAN_REVIEW")
        return store, driver, after

    def test_approving_an_executed_recommendation_again_is_refused_and_the_case_stays_with_the_person(self):
        store, driver, case = self.approved_and_verified()
        recommendation = next(v for v in self.kind(driver, "OpsRecommendation") if v["entity_id"] == case["recommendation_id"])
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((recommendation["status"], recommendation["execution_id"]), ("AUTHORIZED", execution["entity_id"]))
        self.assertEqual((execution["recommendation_id"], execution["run_id"]), (recommendation["entity_id"], case["last_run_id"]))
        served = case["recommendation"]
        self.assertEqual((served["approvable"], served["approval_rule"], served["approval_context_stale"]),
                         (False, "AUTH-24-recommendation-already-executed", False))
        with self.assertRaises(OperationsConflict) as refused:
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-twice")
        self.assertIn("AUTH-24-recommendation-already-executed", str(refused.exception))
        after = store.case_detail(case["case_id"])
        self.assertEqual(after["workflow_state"], "HUMAN_REVIEW")  # Not moved back into automatic re-investigation.
        self.assertEqual(len(self.kind(driver, "OpsExecution")), 1)  # Nothing authorized again.
        events = self.audit(driver, case["case_id"])
        self.assertEqual(events[-1], "APPROVAL_REFUSED")
        self.assertNotIn("APPROVAL_CONTEXT_STALE", events)

    def test_a_record_written_before_the_marking_is_recognised_from_its_decision(self):
        store, driver, case = self.approved_and_verified()
        def legacy(tx):
            for kind, record in tx.ledger.values():
                if kind == "OpsRecommendation":
                    record["status"] = "PROPOSED"
                    record.pop("execution_id", None)
        driver.execute_write(legacy)
        current = store.case_detail(case["case_id"])
        self.assertEqual(current["recommendation"]["approval_rule"], "AUTH-24-recommendation-already-executed")
        with self.assertRaises(OperationsConflict):
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", current["state_version"], "approve-legacy")
        self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "HUMAN_REVIEW")

    def test_the_automatic_path_marks_its_recommendation_too(self):
        auto = ("AUTO", "Low-risk, reversible, evidence-bound action within the synthetic automation allowlist.")
        store, driver = self.make()
        store.agents = agent_investigator()
        with mock.patch("operations.authority.authorize", return_value=auto), \
             mock.patch("operations.authority.symptom_floor", side_effect=lambda r, why, a, s: (r, why, "AUTO")):
            result = store.process_one(manual=True)
        [execution] = self.kind(driver, "OpsExecution")
        [recommendation] = self.kind(driver, "OpsRecommendation")
        self.assertEqual((execution["authority"], execution["recommendation_id"], execution["run_id"]),
                         ("AUTO_POLICY", recommendation["entity_id"], result["run_id"]))
        self.assertEqual(recommendation["status"], "AUTHORIZED")
        self.assertTrue(json.loads(recommendation["approval_context_json"]))  # The context written afterwards is kept too.

    def test_a_never_executable_action_refused_on_a_changed_context_is_not_requeued(self):
        store, driver = self.make()
        store.agents = agent_investigator(verdicts=("HUMAN_REVIEW",), cause="CUSTODY_GAP", action="PHYSICAL_CUSTODY_CHECK")
        result = store.process_one(manual=True)
        case = store.case_detail(result["case_id"])
        original = store.reader.evidence
        def evidence(sid, at):  # New evidence since the recommendation.
            context = original(sid, at)
            return {**context, "nodes": [*context["nodes"], {"id": "DEMO-NEW", "kind": "AddressVersion", "properties": {"recorded_at": str(at)}}]}
        store.reader.evidence = evidence
        with self.assertRaises(OperationsConflict) as refused:
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-person-only")
        self.assertIn("AUTH-12-human-review-action", str(refused.exception))
        self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "HUMAN_REVIEW")  # Stays with the person.


class QueuedRunTests(_Base):
    """Finding 5: while a re-analysis is queued, the earlier run is served apart, marked superseded."""

    def test_the_earlier_run_is_previous_and_the_pipeline_is_queued(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        first = case["last_run_id"]
        store.request_reanalysis(case["case_id"], "DEMO-OPERATOR-LOCAL", case["state_version"], "reanalyze-queued")
        queued = store.case_detail(case["case_id"])
        self.assertIsNone(queued["run"])
        self.assertIsNone(queued["review"])
        self.assertEqual((queued["previous_run"]["entity_id"], queued["previous_run"]["superseded"]), (first, True))
        self.assertEqual(queued["previous_run"]["result"]["trace"][-1]["review"]["verdict"], "accept")  # Kept, but not current.
        pipeline = store.pipeline_state(case["case_id"])
        self.assertEqual((pipeline["status"], pipeline["events"], pipeline["run_id"], pipeline["previous_run_id"]),
                         ("QUEUED", [], None, first))
        # Through the read model the pipeline shown is queued, with no stage event of the earlier run.
        reader = _ReadModel(store)
        detail = reader.case_detail(case["case_id"])
        self.assertEqual((detail["pipeline"]["status"], detail["pipeline"]["events"]), ("QUEUED", []))
        self.assertEqual(detail["previous_run"]["entity_id"], first)
        store.process_one(case_id=case["case_id"])  # The new run becomes current.
        after = store.case_detail(case["case_id"])
        self.assertNotEqual(after["run"]["entity_id"], first)
        self.assertIsNone(after["previous_run"])


def _ReadModel(store):
    """The read model over the in-memory store: evidence and shipment views from the store's reader."""
    from operations.read_model import OperationsReader
    reader = OperationsReader.__new__(OperationsReader)
    reader.store, reader.config, reader.dataset_id = store, store.config, store.dataset_id
    reader.clock = store.clock
    reader._run = lambda query, **params: [{"shipment_id": store.case_detail(params["case_id"])["shipment_id"], "as_of": store.clock(),
                                            "workflow_state": None, "state_version": None, "priority": None, "operational_status": None,
                                            "last_run_id": None, "recommendation_id": None}]
    reader.shipment_detail = lambda sid, at: {"shipment_id": sid, "as_of": at, "evidence": {"nodes": [], "edges": []}}
    store.case_graph = lambda case_id, ids: {"nodes": [], "edges": []}
    return reader


class CycleTests(_Base):
    """Finding 6: an outcome or execution of an earlier investigation cycle is marked as such."""

    def test_an_earlier_cycles_outcome_and_execution_are_not_current_after_a_newer_run(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-cycle")
        store.adapter = Acknowledging()
        store.execute_step()
        after = self.verify(store, case, exceptions=["MISSED_MILESTONE"], key="verify-cycle")
        self.assertEqual(after["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual((after["outcome"]["run_id"], after["outcome"]["current_cycle"]), (case["last_run_id"], True))
        self.assertTrue(after["executions"][0]["current_cycle"])
        store.request_reanalysis(case["case_id"], "DEMO-OPERATOR-LOCAL", after["state_version"], "reanalyze-cycle")
        queued = store.case_detail(case["case_id"])
        self.assertFalse(queued["outcome"]["current_cycle"])  # A new cycle is queued; nothing belongs to it yet.
        store.agents = agent_investigator(verdicts=("HUMAN_REVIEW",))
        store.process_one(case_id=case["case_id"])
        final = store.case_detail(case["case_id"])
        self.assertEqual(final["workflow_state"], "HUMAN_REVIEW")
        self.assertFalse(final["outcome"]["current_cycle"])
        self.assertFalse(final["executions"][0]["current_cycle"])
        self.assertEqual(final["outcome"]["outcome_type"], "barcode_corrected")  # Still served, as history.

    def test_records_without_a_run_id_count_only_when_made_after_the_current_run(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-legacy-cycle")
        store.adapter = Acknowledging()
        store.execute_step()
        self.verify(store, case, exceptions=["MISSED_MILESTONE"], key="verify-legacy-cycle")
        def legacy(tx):
            for kind, record in tx.ledger.values():
                if kind in ("OpsOutcome", "OpsExecution"):
                    record.pop("run_id", None)
                    record["recorded_at"] = "2000-01-01T00:00:00+00:00"  # Before the current run.
        driver.execute_write(legacy)
        served = store.case_detail(case["case_id"])
        self.assertFalse(served["outcome"]["current_cycle"])
        self.assertFalse(served["executions"][0]["current_cycle"])


class ClosureOnEveryActionTests(_Base):
    """Finding 7: a successful action of any kind never closes a case with another open dispute or case."""

    def executed(self, action, cause, *, case_symptoms=("MILESTONE_OVERDUE",), other_case=None, late_symptoms=()):
        store, driver, result = self.approvable(action=action, cause=cause)
        case = store.case_detail(result["case_id"])
        # These tests are about closure after a verified outcome: the authority recheck at approval and dispatch is held
        # at "a person may authorize" (the scripted investigation's fact checks would otherwise route it to a person).
        authorized = mock.patch("operations.authority.recheck_authority",
                                return_value=("APPROVAL_REQUIRED", "Action changes destination or service; operator authorization required.", "AUTO"))
        authorized.start()
        self.addCleanup(authorized.stop)
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-" + action[:20])
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
        self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "AWAITING_OUTCOME")
        if late_symptoms:  # Observed after the action was dispatched.
            def late(tx):
                record = tx.ledger[case["case_id"]][1]
                record["symptom_codes"] = sorted({*record["symptom_codes"], *late_symptoms})
            driver.execute_write(late)
        return store, driver, case

    def outcome(self, driver):
        return next(v for k, v in driver.ledger.values() if k == "OpsOutcome")

    def test_a_reconciliation_with_a_sibling_case_open_stays_unresolved(self):
        store, driver, case = self.executed("INITIATE_CUSTODY_RECONCILIATION", "CUSTODY_GAP", other_case=("DELIVERY_ATTEMPT_FAILED",))
        final = self.verify(store, case, outcome_type="custody_reconciled")
        self.assertEqual(final["workflow_state"], "HUMAN_REVIEW")
        self.assertIn("DELIVERY_ATTEMPT_FAILED", self.outcome(driver)["remaining_symptoms"])
        self.assertIn("OTHER_OPEN_CASES", self.audit(driver, case["case_id"]))

    def test_a_reconciliation_with_a_recorded_failed_delivery_stays_unresolved(self):
        store, driver, case = self.executed("INITIATE_CUSTODY_RECONCILIATION", "CUSTODY_GAP",
                                            case_symptoms=("CUSTODY_TRANSFER_UNCONFIRMED", "DELIVERY_ATTEMPT_FAILED"))
        final = self.verify(store, case, outcome_type="custody_reconciled")
        self.assertEqual(final["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual(self.outcome(driver)["remaining_symptoms"], ["DELIVERY_ATTEMPT_FAILED"])

    def test_an_address_confirmation_does_not_close_a_failed_delivery(self):
        store, driver, case = self.executed("REQUEST_ADDRESS_CONFIRMATION", "ADDRESS_CONFLICT", case_symptoms=("DELIVERY_ATTEMPT_FAILED",))
        final = self.verify(store, case, outcome_type="address_confirmed")
        self.assertEqual(final["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual((self.outcome(driver)["success"], self.outcome(driver)["exception_cleared"]), (True, False))
        self.assertNotIn("CASE_RESOLVED", self.audit(driver, case["case_id"]))

    def test_corroborated_delivery_settles_a_failed_attempt(self):
        store, driver, case = self.executed("PRIORITIZE_NEXT_SESSION", "RECIPIENT_UNAVAILABLE", case_symptoms=("DELIVERY_ATTEMPT_FAILED",))
        final = self.verify(store, case, delivered=True, outcome_type="delivery_verified")
        self.assertEqual(final["workflow_state"], "RESOLVED")

    def test_a_reconciliation_settles_the_unreconciled_session_it_reconciled_but_closure_stays_with_a_person(self):
        # An unreconciled session end (a human-floor symptom) observed only after the reconciliation was dispatched.
        store, driver, case = self.executed("INITIATE_CUSTODY_RECONCILIATION", "CUSTODY_GAP", case_symptoms=("CUSTODY_TRANSFER_UNCONFIRMED",),
                                            late_symptoms=("SESSION_END_UNRECONCILED",))
        final = self.verify(store, case, outcome_type="custody_reconciled")
        self.assertEqual(final["workflow_state"], "HUMAN_REVIEW")  # A human-floor symptom was recorded.
        self.assertEqual(self.outcome(driver)["remaining_symptoms"], [])
        self.assertIn("OUTCOME_VERIFIED_HUMAN_CLOSURE", self.audit(driver, case["case_id"]))

    def test_control_a_reconciliation_with_nothing_else_open_resolves(self):
        store, driver, case = self.executed("INITIATE_CUSTODY_RECONCILIATION", "CUSTODY_GAP", case_symptoms=("CUSTODY_TRANSFER_UNCONFIRMED",))
        final = self.verify(store, case, outcome_type="custody_reconciled")
        self.assertEqual(final["workflow_state"], "RESOLVED")


class LegacyHypothesisTextTests(_Base):
    """Finding 8: a stored agent run's hypotheses never carry a rule-definition Arabic sentence when served."""

    def test_a_legacy_stored_run_is_served_without_the_rule_sentence(self):
        from operations.reasoning import ARABIC
        store, driver, result = self.approvable()
        sentence = ARABIC["BARCODE_MISMATCH"][0]
        def legacy(tx):  # As runs were stored before b426682.
            for kind, run in tx.ledger.values():
                if kind == "OpsRun":
                    stored = json.loads(run["result_json"])
                    for d in stored["result"]["diagnoses"]:
                        d["summary_ar"] = sentence
                    for e in stored.get("pipeline_events") or []:
                        for d in (e.get("output") or {}).get("diagnoses") or []:
                            d["summary_ar"] = sentence
                    run["result_json"] = json.dumps(stored)
        driver.execute_write(legacy)
        self.assertIn(sentence, json.dumps([json.loads(v["result_json"]) for v in self.kind(driver, "OpsRun")], ensure_ascii=False))
        detail = store.case_detail(result["case_id"])
        pipeline = store.pipeline_state(result["case_id"])
        self.assertTrue(detail["run"]["result"]["result"]["diagnoses"])
        self.assertTrue(any((e.get("output") or {}).get("diagnoses") for e in pipeline["events"]))
        self.assertNotIn(sentence, json.dumps(detail, ensure_ascii=False, default=str))
        self.assertNotIn(sentence, json.dumps(pipeline, ensure_ascii=False, default=str))


class LiveResetTests(_Base):
    """Finding 10: the live reset checks the worker claim and resets the ingestion ledger under the same lock."""

    class Gateway:
        def __init__(self, driver, fail=False):
            self.driver, self.fail, self.calls = driver, fail, []

        def reset(self):
            # Records what the claim was when the ingestion ledger was reset.
            control = next(v for k, v in self.driver.ledger.values() if k == "OpsControl")
            self.calls.append(control.get("worker_claim"))
            if self.fail:
                raise ConnectionError("down")

        def first_delivery(self):
            return "2026-09-01T00:00:00+00:00"

    def live_store(self, fail=False):
        store, driver = self.make()
        store.live, store.gateway = True, self.Gateway(driver, fail)
        return store, driver

    def reset(self, store):
        with mock.patch.dict(os.environ, {DEV_RESET_ENV: "1"}):
            return store.reset_session("DEMO-OPERATOR-LOCAL", confirmation=store.reset_confirmation())

    def control(self, driver):
        return next(v for k, v in driver.ledger.values() if k == "OpsControl")

    def test_an_active_worker_refuses_the_reset_before_ingestion_is_touched_and_is_audited(self):
        store, driver = self.live_store()
        def claim(tx):
            next(v for k, v in tx.ledger.values() if k == "OpsControl")["worker_claim"] = "DEMO-OPS-CASE-X"
        driver.execute_write(claim)
        cases = len(self.kind(driver, "OpsCase"))
        with self.assertRaises(OperationsConflict) as refused:
            self.reset(store)
        self.assertIn("Pause auto-triage", str(refused.exception))
        self.assertEqual(store.gateway.calls, [])  # The ingestion ledger was not reset.
        self.assertEqual(len(self.kind(driver, "OpsCase")), cases)
        last = json.loads(self.control(driver)["reset_audit_json"])[-1]
        self.assertEqual((last["result"], last["reason"], last["active_case_id"]), ("REFUSED", "investigation worker active", "DEMO-OPS-CASE-X"))

    def test_a_confirmed_live_reset_resets_ingestion_once_after_the_claim_check(self):
        store, driver = self.live_store()
        self.reset(store)
        self.assertEqual(store.gateway.calls, [None])
        self.assertEqual(self.kind(driver, "OpsCase"), [])
        self.assertEqual(json.loads(self.control(driver)["reset_audit_json"])[-1]["result"], "PERFORMED")
        self.assertEqual(str(self.control(driver)["as_of"]), "2026-08-31 23:59:59+00:00")  # From the first provider delivery.

    def test_a_failed_ingestion_reset_deletes_nothing_and_is_audited(self):
        store, driver = self.live_store(fail=True)
        cases = len(self.kind(driver, "OpsCase"))
        with self.assertRaises(OperationsConflict):
            self.reset(store)
        self.assertEqual(len(self.kind(driver, "OpsCase")), cases)
        last = json.loads(self.control(driver)["reset_audit_json"])[-1]
        self.assertEqual((last["result"], last["error"]), ("FAILED", "ConnectionError"))


if __name__ == "__main__":
    unittest.main()
