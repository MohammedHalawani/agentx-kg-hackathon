"""A finished or running investigation is superseded only by a material change.

Routine new records for the shipment (during a run or after it) leave the investigation standing as of its snapshot.
A changed symptom set, or a record that replaces or contradicts what the conclusion rests on (a late upload from
before the snapshot, a new version of a cited record), requeues the case. After a run a quiet interval on the
simulation clock holds back the next automatic investigation, and a case awaiting an executed action's outcome is left
to the outcome verifier. The approval and dispatch rechecks (AUTH-20) decide "the context changed" with the same
module: a routine record no longer refuses an approved or automatic action, and every material change, a changed
symptom set, a changed reviewer decision, a new run and a case version that ingestion does not account for still do
(ApprovalAndDispatchMaterialityTests; the recheck's other rules are in tests/test_approval_recheck.py).

In-memory ledger, scripted investigator and reviewer: no database, no model.
"""
import copy
import os
import unittest
from datetime import timedelta
from unittest import mock

from dataset_v2.contracts import Config, Node, instant
from dataset_v2.generate import generate
from operations import materiality
from operations.lifecycle import OperationsConflict
from operations.reasoning import public_evidence
from operations.schema import public_value
from operations.store import (CONTROL_ID, MAX_EVIDENCE_REINVESTIGATIONS, MAX_SNAPSHOT_REFRESHES, REINVESTIGATION_QUIET_SECONDS,
                              reinvestigation_quiet_seconds)
from tests import test_investigator as ti
from tests import test_operations_store as _store
from tests.test_operations_store import Acknowledging, approval_policy

WORLD = None


def world():
    global WORLD
    if WORLD is None:
        WORLD = generate(Config(total=90))
    return WORLD


class Scripted(ti.FakeInvestigator):
    """The scripted investigator; `during` runs once, while the first investigation is in progress."""
    cause, action, during = "BARCODE_MISMATCH", "REQUEST_RESCAN", None

    def __init__(self, during=None, verdicts=("ACCEPT",), missing=()):
        super().__init__(lambda tools: [("shipment_overview", {})], verdicts)
        self.during, self.missing = during, list(missing)

    def investigate(self, tools, on_step=None, feedback=None):
        hook, self.during = self.during, None
        if hook:
            hook()
        conclusion = super().investigate(tools, on_step=on_step, feedback=feedback)
        return {**conclusion, "missing_evidence": list(self.missing)} if self.missing else conclusion


class _Base(unittest.TestCase):
    make = _store.StoreTests.make
    approvable = _store.StoreTests.approvable

    def setUp(self):
        self.world = copy.deepcopy(world())   # Each test adds its own records.

    def kind(self, driver, kind):
        return [v for k, v in driver.ledger.values() if k == kind]

    def stored(self, driver, case_id=None):
        return public_value(copy.deepcopy(next(v for v in self.kind(driver, "OpsCase") if case_id is None or v["entity_id"] == case_id)))

    def audit(self, driver, event_type):
        return [v for v in self.kind(driver, "OpsAudit") if v["event_type"] == event_type]

    def clock(self, driver):
        return public_value(driver.ledger[CONTROL_ID][1]["as_of"])

    def advance(self, driver, seconds):
        def move(tx):
            control = tx.ledger[CONTROL_ID][1]
            control["as_of"] = control["as_of"] + timedelta(seconds=seconds)
        driver.execute_write(move)
        return self.clock(driver)

    def ingest(self, store, driver, case, *, occurred_before=None, kind="ScanEvent", **props):
        """One new record for the case's shipment becomes visible a second later on the clock, through the store's own
        ingestion step (the case advances exactly as it does for a fed record). occurred_before: seconds before the
        clock the observation happened (a late upload); otherwise it happened now (a routine record)."""
        now = self.advance(driver, 1)
        sid = case["shipment_id"]
        source = next(n for n in self.world.owned(sid) if n.kind == kind)
        identifier = f"DEMO-TEST-{kind.upper()}-{len(self.world.nodes)}"
        occurred = (instant(now) - timedelta(seconds=occurred_before)).isoformat() if occurred_before else now
        self.world.nodes[identifier] = Node(identifier, kind, {**source.properties, "entity_id": identifier, "occurred_at": occurred,
                                                               "recorded_at": now, **props})
        driver.execute_write(lambda tx: store._live_case_event(tx, sid, kind, identifier, now))
        return identifier

    def monitor(self, store, driver, case, symptom=None):
        """The real monitor step over the case's shipment; `symptom` is one it newly observes."""
        def enqueue(tx):
            tx.ledger[CONTROL_ID][1]["monitor_queue"] = [case["shipment_id"]]
        driver.execute_write(enqueue)
        if symptom is None:
            return store.monitor_step()
        finding = {"open": True, "symptoms": sorted({*(case.get("symptom_codes") or []), symptom})}
        with mock.patch("operations.store.monitor_finding", return_value=finding):
            return store.monitor_step()

    def investigating(self, driver):
        return public_value(copy.deepcopy(next(v for v in self.kind(driver, "OpsCase") if v["workflow_state"] == "INVESTIGATING")))

    def run_with(self, during, verdicts=("ACCEPT",), prepare=None):
        """One investigation of the first case; `during(store, driver, case)` happens while it runs."""
        store, driver = self.make()
        store.agents = Scripted(lambda: during(store, driver, self.investigating(driver)), verdicts)
        if prepare:
            prepare(store, driver)
        with approval_policy():
            result = store.process_one(manual=True)
        return store, driver, result


class DuringARunTests(_Base):
    def test_routine_new_records_during_a_run_do_not_supersede_it(self):
        store, driver, result = self.run_with(lambda s, d, case: [self.ingest(s, d, case), self.ingest(s, d, case)])
        self.assertTrue(result["processed"])
        case = self.stored(driver, result["case_id"])
        self.assertEqual(case["workflow_state"], "AWAITING_APPROVAL")
        self.assertEqual([r["status"] for r in self.kind(driver, "OpsRun")], ["REVIEWED"])
        self.assertEqual(case.get("snapshot_refreshes") or 0, 0)
        kept = self.audit(driver, "SNAPSHOT_KEPT")
        self.assertEqual(len(kept), 1)
        self.assertIn("2 new record(s)", kept[0]["result"])
        self.assertEqual(self.audit(driver, "CLAIM_RELEASED"), [])
        # The record states its snapshot: two seconds (two records) before the run was written.
        self.assertEqual(instant(case["investigated_as_of"]), instant(self.clock(driver)) - timedelta(seconds=2))
        self.assertIn(case["investigated_as_of"], kept[0]["result"])
        run = store.case_detail(result["case_id"])["run"]["result"]
        self.assertFalse(any(d.get("role") == "snapshot" for d in run.get("degraded") or []))

    def test_a_new_symptom_during_a_run_supersedes_it(self):
        store, driver, result = self.run_with(lambda s, d, case: self.monitor(s, d, case, "DELIVERY_PROOF_INCOMPLETE"))
        self.assertEqual((result["processed"], result["reason"]), (False, "snapshot_changed"))
        self.assertEqual(result["material"], [{"reason": "symptoms_changed", "added": ["DELIVERY_PROOF_INCOMPLETE"], "cleared": []}])
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], case["snapshot_refreshes"]), ("OPEN", 1))
        self.assertEqual([r["status"] for r in self.kind(driver, "OpsRun")], ["ABORTED"])
        self.assertIn("symptoms_changed (DELIVERY_PROOF_INCOMPLETE)", self.audit(driver, "CLAIM_RELEASED")[0]["result"])

    def test_a_late_upload_from_before_the_snapshot_supersedes_the_run(self):
        """The conclusion names a scan as missing; the scan made two hours before the snapshot is uploaded during the run."""
        uploaded = []
        store, driver, result = self.run_with(lambda s, d, case: uploaded.append(self.ingest(s, d, case, occurred_before=7200)))
        self.assertEqual((result["processed"], result["reason"]), (False, "snapshot_changed"))
        late = [m for m in result["material"] if m["reason"] == "late_upload"]
        self.assertEqual([(m["entity_id"], m["kind"]) for m in late], [(uploaded[0], "ScanEvent")])
        self.assertEqual(self.stored(driver, result["case_id"])["workflow_state"], "OPEN")

    def test_a_record_within_normal_upload_lag_is_not_a_late_upload(self):
        store, driver, result = self.run_with(lambda s, d, case: self.ingest(s, d, case, occurred_before=300))
        self.assertTrue(result["processed"])
        self.assertEqual(len(self.audit(driver, "SNAPSHOT_KEPT")), 1)

    def test_a_change_ingestion_does_not_account_for_is_material(self):
        def touch(store, driver, case):
            def bump(tx):
                tx.ledger[case["entity_id"]][1]["state_version"] += 1
            driver.execute_write(bump)
        store, driver, result = self.run_with(touch)
        self.assertEqual((result["processed"], result["material"]), (False, [{"reason": "case_record_changed"}]))

    def test_a_material_change_that_keeps_recurring_goes_to_a_person_with_the_snapshot_kind(self):
        def exhausted(store, driver):
            def write(tx):
                next(v for k, v in tx.ledger.values() if k == "OpsCase")["snapshot_refreshes"] = MAX_SNAPSHOT_REFRESHES
            driver.execute_write(write)
        store, driver, result = self.run_with(lambda s, d, case: self.ingest(s, d, case, occurred_before=7200), prepare=exhausted)
        self.assertTrue(result["processed"])
        detail = store.case_detail(result["case_id"])
        self.assertEqual(detail["workflow_state"], "HUMAN_REVIEW")
        run = detail["run"]["result"]
        self.assertEqual(run["authority"]["rule_id"], "AUTH-15-superseded-snapshot")
        self.assertEqual([d for d in run["degraded"] if d["role"] == "snapshot"],
                         [{"role": "snapshot", "error": "evidence changed during investigation", "kind": "snapshot_superseded"}])
        self.assertEqual(len(self.audit(driver, "SNAPSHOT_SUPERSEDED")), 1)
        self.assertEqual(self.kind(driver, "OpsExecution"), [])

    def test_a_routine_record_with_refreshes_used_up_is_still_kept(self):
        def exhausted(store, driver):
            def write(tx):
                next(v for k, v in tx.ledger.values() if k == "OpsCase")["snapshot_refreshes"] = MAX_SNAPSHOT_REFRESHES
            driver.execute_write(write)
        store, driver, result = self.run_with(lambda s, d, case: self.ingest(s, d, case), prepare=exhausted)
        detail = store.case_detail(result["case_id"])
        self.assertEqual(detail["workflow_state"], "AWAITING_APPROVAL")
        self.assertNotEqual((detail["run"]["result"].get("authority") or {}).get("rule_id"), "AUTH-15-superseded-snapshot")


class AfterARunTests(_Base):
    def runs(self, driver):
        return len(self.kind(driver, "OpsRun"))

    def test_routine_new_records_after_a_run_do_not_requeue_it(self):
        store, driver, result = self.approvable()
        for _ in range(3):
            self.ingest(store, driver, self.stored(driver, result["case_id"]))
            self.monitor(store, driver, self.stored(driver, result["case_id"]))
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], self.runs(driver)), ("AWAITING_APPROVAL", 1))
        self.assertEqual(self.audit(driver, "REINVESTIGATION_QUEUED"), [])
        self.assertEqual(case["evidence_checked_as_of"], self.clock(driver))     # Checked once, up to the clock.
        self.assertEqual(case.get("evidence_reinvestigations") or 0, 0)
        store.control("worker", "start")
        self.assertFalse(store.process_one()["processed"])                       # Nothing was queued.
        store.control("worker", "pause")

    def test_a_new_standing_symptom_after_a_run_requeues_it(self):
        store, driver, result = self.approvable()
        self.monitor(store, driver, self.stored(driver, result["case_id"]), "DELIVERY_PROOF_INCOMPLETE")
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], case["symptom_reinvestigations"]), ("OPEN", 1))
        queued = self.audit(driver, "REINVESTIGATION_QUEUED")
        self.assertEqual(len(queued), 1)
        self.assertIn("DELIVERY_PROOF_INCOMPLETE", queued[0]["result"])

    def test_a_late_upload_of_an_observation_cited_as_missing_requeues_the_finished_case(self):
        store, driver = self.make()
        store.agents = Scripted(missing=["The depot scan of the package before dispatch is missing."])
        with approval_policy():
            result = store.process_one(manual=True)
        self.assertTrue(result["processed"])
        self.assertEqual(store.case_detail(result["case_id"])["run"]["result"]["investigation"]["missing_evidence"],
                         ["The depot scan of the package before dispatch is missing."])
        before = self.stored(driver, result["case_id"])
        late = self.ingest(store, driver, before, occurred_before=7200)
        self.monitor(store, driver, self.stored(driver, result["case_id"]))
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], case["evidence_reinvestigations"], case.get("recommendation_id")), ("OPEN", 1, None))
        queued = self.audit(driver, "REINVESTIGATION_QUEUED")
        self.assertEqual(len(queued), 1)
        self.assertIn(f"late_upload ({late})", queued[0]["result"])
        self.assertEqual(store.case_detail(result["case_id"])["diagnosis"]["reason"], "reinvestigation_pending")

    def test_a_new_version_of_a_cited_record_is_material_and_an_uncited_one_is_not(self):
        sid = next(n.id for n in self.world.of_kind("Shipment") if n.properties.get("split") == "development")
        at = self.world.config.as_of
        before = public_evidence(self.world, sid, at)
        address = next(n for n in before["nodes"] if n["kind"] == "AddressVersion")
        newer = {"id": "DEMO-TEST-ADDRESS-V2", "kind": "AddressVersion",
                 "properties": {**address["properties"], "entity_id": "DEMO-TEST-ADDRESS-V2", "version": 2, "supersedes_id": address["id"], "recorded_at": at}}
        after = {**before, "nodes": [*before["nodes"], newer]}
        check = lambda cited: [m["reason"] for m in materiality.material_evidence(before, after, snapshot_at=at, cited=cited,
                                                                                 config=self.world.config, allowance=900)]
        self.assertEqual(check({address["id"]}), ["cited_record_superseded"])
        self.assertEqual(check(set()), [])
        del newer["properties"]["supersedes_id"]
        self.assertEqual(check({address["id"]}), ["cited_record_new_version"])
        self.assertEqual(materiality.cited_evidence_ids({"investigation": {"hypotheses": [{"supporting_evidence_ids": ["SYN-A"]}]},
                                                         "proposal": {"evidence_ids": ["DEMO-B"]}, "result": {"diagnoses": [{"evidence_ids": ["DEMO-C"]}]}}),
                         {"DEMO-A", "DEMO-B", "DEMO-C"})

    def test_material_evidence_requeues_are_bounded(self):
        store, driver, result = self.approvable()
        def used_up(tx):
            tx.ledger[result["case_id"]][1]["evidence_reinvestigations"] = MAX_EVIDENCE_REINVESTIGATIONS
        driver.execute_write(used_up)
        self.ingest(store, driver, self.stored(driver, result["case_id"]), occurred_before=7200)
        self.monitor(store, driver, self.stored(driver, result["case_id"]))
        self.monitor(store, driver, self.stored(driver, result["case_id"]))      # Checked once: no second audit.
        self.assertEqual(self.stored(driver, result["case_id"])["workflow_state"], "AWAITING_APPROVAL")
        self.assertEqual(len(self.audit(driver, "REINVESTIGATION_LIMIT")), 1)
        self.assertEqual(self.audit(driver, "REINVESTIGATION_QUEUED"), [])

    def test_nothing_is_reinvestigated_while_an_execution_awaits_its_outcome(self):
        store, driver, result = self.approvable()
        store.adapter = Acknowledging()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-then-wait")
        store.execute_step()
        self.assertEqual(self.stored(driver, result["case_id"])["workflow_state"], "AWAITING_OUTCOME")
        self.ingest(store, driver, self.stored(driver, result["case_id"]))                           # a routine record
        self.ingest(store, driver, self.stored(driver, result["case_id"]), occurred_before=7200)     # a late upload
        self.monitor(store, driver, self.stored(driver, result["case_id"]), "DELIVERY_PROOF_INCOMPLETE")  # a standing symptom
        case = self.stored(driver, result["case_id"])
        self.assertEqual((case["workflow_state"], self.runs(driver)), ("AWAITING_OUTCOME", 1))
        self.assertEqual(self.audit(driver, "REINVESTIGATION_QUEUED"), [])
        self.assertEqual((case.get("evidence_reinvestigations") or 0, case.get("symptom_reinvestigations") or 0), (0, 0))
        store.control("worker", "start")
        self.advance(driver, REINVESTIGATION_QUIET_SECONDS + 1)
        self.assertFalse(store.process_one()["processed"])
        store.control("worker", "pause")
        self.assertEqual(len([e for e in self.kind(driver, "OpsExecution") if e["status"] == "ACKNOWLEDGED"]), 1)


class ApprovalAndDispatchMaterialityTests(_Base):
    """AUTH-20 at approval and immediately before dispatch: the recheck and the authority recomputation are as they
    were; what counts as "the context changed" is decided by operations.materiality."""

    STALE = "AUTH-20-approval-context-stale"

    def awaiting(self):
        store, driver, result = self.approvable()
        return store, driver, result["case_id"]

    def approved(self):
        """Approved by a person and waiting for the execution adapter."""
        store, driver, case_id = self.awaiting()
        case = store.case_detail(case_id)
        store.decide(case_id, "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-first")
        store.adapter = Recording()
        return store, driver, case_id

    def approve(self, store, case_id, key="approve-now"):
        current = store.case_detail(case_id)          # the operator reloads: the version check passes
        return store.decide(case_id, "approve", "DEMO-OPERATOR-LOCAL", current["state_version"], key)

    def cited(self, driver):
        """(id, kind) of a record the run's conclusion cites, as the world holds it."""
        import json
        [run] = self.kind(driver, "OpsRun")
        ids = materiality.cited_evidence_ids(json.loads(run["result_json"]))
        return next((key, self.world.nodes[key].kind) for key in sorted(ids) if key in self.world.nodes)

    def changes(self):
        """Every change that must still block: name -> (apply(store, driver, case_id), what the refusal names)."""
        def symptom(store, driver, case_id):
            self.monitor(store, driver, self.stored(driver, case_id), "WEIGHT_READ_DIFFERS")      # recorded, not requeued

        def late_upload(store, driver, case_id):
            self.ingest(store, driver, self.stored(driver, case_id), occurred_before=7200)

        def superseded(store, driver, case_id):
            key, kind = self.cited(driver)
            self.ingest(store, driver, self.stored(driver, case_id), kind=kind, supersedes_id=key, version=2)

        def new_version(store, driver, case_id):
            _key, kind = self.cited(driver)
            self.ingest(store, driver, self.stored(driver, case_id), kind=kind, version=2)

        def finding(store, driver, case_id):
            new = self.ingest(store, driver, self.stored(driver, case_id))
            codes = lambda context, config, at, allowance: {"MANIFEST_CONFLICT"} if any(n["id"] == new for n in context["nodes"]) else set()
            patcher = mock.patch.object(materiality, "finding_codes", codes)
            patcher.start()
            self.addCleanup(patcher.stop)

        def reviewer(store, driver, case_id):
            def edit(tx):
                review = next(v for k, v in tx.ledger.values() if k == "OpsReview")
                review.update(verdict="human_review", model_verdict="HUMAN_REVIEW")
            driver.execute_write(edit)

        def version(store, driver, case_id):
            def edit(tx):
                tx.ledger[case_id][1]["state_version"] += 1          # the case moved, and no record was ingested
            driver.execute_write(edit)
        return {"a symptom change": (symptom, "symptoms"),
                "a late upload": (late_upload, "late_upload"),
                "a record that supersedes cited evidence": (superseded, "cited_record_superseded"),
                "a new version of a cited record": (new_version, "cited_record_new_version"),
                "a new finding": (finding, "finding_added (MANIFEST_CONFLICT)"),
                "a changed reviewer decision": (reviewer, "review_verdict"),
                "a case version ingestion does not account for": (version, "state_version")}

    # ---------------------------------------------------------------- a routine record alone
    def test_a_routine_record_alone_no_longer_refuses_an_approval(self):
        store, driver, case_id = self.awaiting()
        for _ in range(2):
            self.ingest(store, driver, self.stored(driver, case_id))
        served = store.case_detail(case_id)["recommendation"]
        self.assertEqual((served["approvable"], served["approval_context_stale"]), (True, False))
        approved = self.approve(store, case_id)
        self.assertEqual(approved["workflow_state"], "AWAITING_OUTCOME")
        self.assertEqual(self.audit(driver, "APPROVAL_CONTEXT_STALE"), [])
        self.assertEqual(self.audit(driver, "APPROVAL_REFUSED"), [])
        # The recheck ran, on the current evidence, and says what it passed over.
        import json
        [checked] = self.audit(driver, "APPROVAL_CONTEXT_CHECKED")
        detail = json.loads(checked["result"])
        self.assertEqual(detail["routine_new_records"], 2)
        [execution] = self.kind(driver, "OpsExecution")
        context = json.loads(execution["approval_context_json"])
        self.assertEqual(context["evidence_count"], detail["context"]["evidence_count"])      # the evidence visible at approval
        [recommendation] = self.kind(driver, "OpsRecommendation")
        self.assertEqual(context["evidence_count"], json.loads(recommendation["approval_context_json"])["evidence_count"] + 2)
        self.assertEqual(self.stored(driver, case_id).get("snapshot_refreshes") or 0, 0)        # not sent back, not counted

    def test_a_routine_record_alone_no_longer_refuses_the_dispatch_of_an_approved_action(self):
        store, driver, case_id = self.approved()
        self.ingest(store, driver, self.stored(driver, case_id))
        store.execute_step()
        self.assertEqual(len(store.adapter.calls), 1)
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual(execution["status"], "ACKNOWLEDGED")
        self.assertEqual(self.audit(driver, "EXECUTION_CONTEXT_STALE"), [])
        import json
        [checked] = self.audit(driver, "EXECUTION_CONTEXT_CHECKED")
        self.assertEqual(json.loads(checked["result"])["routine_new_records"], 1)
        self.assertEqual(self.stored(driver, case_id)["workflow_state"], "AWAITING_OUTCOME")

    def test_a_routine_record_alone_no_longer_refuses_an_automatic_action(self):
        store, driver = self.make()
        store.agents = Scripted(lambda: self.ingest(store, driver, self.investigating(driver)))     # one during the run (kept)
        with approval_policy(("AUTO", "An evidence request within policy; automatic.")):
            result = store.process_one(manual=True)                                                 # the automatic path
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["authority"], execution["status"]), ("AUTO_POLICY", "AUTHORIZED"))
        self.ingest(store, driver, self.stored(driver, result["case_id"]))                           # and one after it
        store.adapter = Recording()
        # The scripted case is decided AUTO by the same stand-in at dispatch (the real policy would not decide this
        # scripted conclusion AUTO, and refuses it with AUTH-18 whatever arrived): what is under test is AUTH-20.
        with approval_policy(("AUTO", "An evidence request within policy; automatic.")):
            store.execute_step()
        self.assertEqual(len(store.adapter.calls), 1)
        self.assertEqual(self.kind(driver, "OpsExecution")[0]["status"], "ACKNOWLEDGED")
        self.assertEqual(self.audit(driver, "EXECUTION_CONTEXT_STALE"), [])
        import json
        [checked] = self.audit(driver, "EXECUTION_CONTEXT_CHECKED")
        self.assertEqual(json.loads(checked["result"])["routine_new_records"], 2)                   # the one during the run and the one after
        self.assertEqual(self.runs(driver), 1)                                                       # no re-investigation

    def runs(self, driver):
        return len(self.kind(driver, "OpsRun"))

    # ---------------------------------------------------------------- what still blocks, exactly as before
    def test_each_material_change_still_refuses_the_approval_and_requeues_the_case(self):
        for name, (apply, named) in self.changes().items():
            with self.subTest(name):
                self.setUp()
                store, driver, case_id = self.awaiting()
                self.ingest(store, driver, self.stored(driver, case_id))          # a routine record beside it changes nothing
                apply(store, driver, case_id)
                served = store.case_detail(case_id)["recommendation"]
                self.assertEqual((served["approvable"], served["approval_rule"], served["approval_context_stale"]), (False, self.STALE, True))
                with self.assertRaises(OperationsConflict) as refused:
                    self.approve(store, case_id)
                self.assertIn(self.STALE, str(refused.exception))
                self.assertIn(named, str(refused.exception))
                case = self.stored(driver, case_id)
                self.assertEqual((case["workflow_state"], case.get("recommendation_id"), case["snapshot_refreshes"]), ("OPEN", None, 1))
                self.assertEqual(self.kind(driver, "OpsExecution"), [])
                [stale] = self.audit(driver, "APPROVAL_CONTEXT_STALE")
                self.assertIn(named, stale["result"])
                self.assertIn("requeued for re-investigation", stale["result"])
                self.assertEqual(self.audit(driver, "APPROVAL_CONTEXT_CHECKED"), [])
                self.doCleanups()

    def test_each_material_change_still_refuses_the_dispatch_and_requeues_the_case(self):
        for name, (apply, named) in self.changes().items():
            with self.subTest(name):
                self.setUp()
                store, driver, case_id = self.approved()
                self.ingest(store, driver, self.stored(driver, case_id))
                apply(store, driver, case_id)
                store.execute_step()
                self.assertEqual(store.adapter.calls, [])                          # nothing dispatched
                [execution] = self.kind(driver, "OpsExecution")
                self.assertEqual((execution["status"], execution["permission_rule"]), ("REFUSED", self.STALE))
                case = self.stored(driver, case_id)
                self.assertEqual((case["workflow_state"], case.get("recommendation_id")), ("OPEN", None))
                [stale] = self.audit(driver, "EXECUTION_CONTEXT_STALE")
                self.assertIn(named, stale["result"])
                self.assertEqual(self.audit(driver, "EXECUTION_CONTEXT_CHECKED"), [])
                store.execute_step()
                self.assertEqual(store.adapter.calls, [])
                self.doCleanups()

    def test_a_new_investigation_run_still_blocks_both(self):
        def newer_run(driver, case_id):
            def edit(tx):
                tx.ledger[case_id][1]["last_run_id"] = "DEMO-OPS-RUN-NEWER"
            driver.execute_write(edit)
        # Approval: the recommendation is no longer the current investigation's. Refused, and (as before) not requeued:
        # the case stays where the newer investigation left it.
        store, driver, case_id = self.awaiting()
        newer_run(driver, case_id)
        with self.assertRaises(OperationsConflict) as refused:
            self.approve(store, case_id)
        self.assertIn(self.STALE, str(refused.exception))
        self.assertIn("run_id", str(refused.exception))
        self.assertEqual(self.stored(driver, case_id)["workflow_state"], "AWAITING_APPROVAL")
        self.assertEqual((len(self.audit(driver, "APPROVAL_REFUSED")), self.audit(driver, "APPROVAL_CONTEXT_STALE")), (1, []))
        self.assertEqual(self.kind(driver, "OpsExecution"), [])
        # Dispatch: refused and requeued.
        self.setUp()
        store, driver, case_id = self.approved()
        newer_run(driver, case_id)
        store.execute_step()
        self.assertEqual(store.adapter.calls, [])
        [stale] = self.audit(driver, "EXECUTION_CONTEXT_STALE")
        self.assertIn("run_id", stale["result"])
        self.assertEqual(self.kind(driver, "OpsExecution")[0]["status"], "REFUSED")

    def test_the_other_rules_of_the_recheck_are_as_they_were(self):
        """A routine record does not open anything else: an executed recommendation cannot be approved again (AUTH-24),
        and a human-floor symptom still reserves the action for the allowlist and closure for a person."""
        store, driver, case_id = self.approved()
        self.ingest(store, driver, self.stored(driver, case_id))
        store.execute_step()
        self.assertEqual(len(store.adapter.calls), 1)
        [recommendation] = self.kind(driver, "OpsRecommendation")
        check = driver.execute_write(lambda tx: store._approval_check(tx, self.stored(driver, case_id), public_value(copy.deepcopy(recommendation)),
                                                                      self.clock(driver)))
        self.assertEqual((check["allowed"], check["rule"]), (False, "AUTH-24-recommendation-already-executed"))

    def test_the_decision_itself(self):
        """context_changes: what is compared, and how the evidence and the version are judged."""
        from operations.store import CONTEXT_KEYS, context_changes
        recorded = {"symptoms": ["A"], "evidence_count": 10, "latest_evidence_recorded_at": "t1", "run_id": "R1", "review_id": "V1",
                    "review_verdict": "accept", "model_verdict": "ACCEPT", "state_version": 7, "evidence_events": 3}
        routine = {**recorded, "evidence_count": 12, "latest_evidence_recorded_at": "t2", "state_version": 9, "evidence_events": 5}
        self.assertEqual(context_changes(recorded, dict(recorded), material=[]), [])
        self.assertEqual(context_changes(recorded, routine, material=[]), [])                       # two routine records
        self.assertEqual(context_changes(recorded, routine, material=[{"reason": "late_upload"}]), ["evidence_count", "latest_evidence_recorded_at"])
        self.assertEqual(context_changes(recorded, {**routine, "state_version": 10}, material=[]), ["state_version"])
        # Not assessed (None): any difference counts, as it did before materiality was used.
        self.assertEqual(context_changes(recorded, routine), ["evidence_count", "latest_evidence_recorded_at", "state_version"])
        self.assertEqual(context_changes({k: v for k, v in recorded.items() if k != "evidence_events"}, routine, material=[]), ["state_version"])
        for key, value in (("symptoms", ["A", "B"]), ("run_id", "R2"), ("review_id", "V2"), ("review_verdict", "human_review"), ("model_verdict", "REVISE")):
            self.assertEqual(context_changes(recorded, {**recorded, key: value}, material=[]), [key])
        self.assertEqual(context_changes(None, recorded, material=[]), ["approval_context_missing"])
        self.assertEqual(set(CONTEXT_KEYS), set(recorded) - {"evidence_events"})

    def test_a_context_recorded_without_its_evidence_time_is_judged_as_before(self):
        """A recommendation recorded before this change carries no evidence time to compare from: any new record refuses."""
        import json
        store, driver, case_id = self.awaiting()
        def strip(tx):
            recommendation = next(v for k, v in tx.ledger.values() if k == "OpsRecommendation")
            context = json.loads(recommendation["approval_context_json"])
            for key in ("evidence_at", "snapshot_at", "evidence_events"):
                context.pop(key, None)
            recommendation["approval_context_json"] = json.dumps(context)
        driver.execute_write(strip)
        self.ingest(store, driver, self.stored(driver, case_id))
        with self.assertRaises(OperationsConflict) as refused:
            self.approve(store, case_id)
        self.assertIn("evidence_count", str(refused.exception))


class Recording:
    """A field system that accepts every request, and remembers which."""

    def __init__(self):
        self.calls = []

    def respond(self, execution, now):
        self.calls.append(execution["entity_id"])
        return {"acknowledged": True, "behaviour": "Request accepted."}


class QuietIntervalTests(_Base):
    def requeued(self):
        store, driver, result = self.approvable()
        self.monitor(store, driver, self.stored(driver, result["case_id"]), "DELIVERY_PROOF_INCOMPLETE")
        self.assertEqual(self.stored(driver, result["case_id"])["workflow_state"], "OPEN")
        self.running(store)
        return store, driver, result["case_id"]

    def running(self, store):
        """The automatic worker, with the simulation clock running (the tests move the clock themselves)."""
        store.control("simulator", "start")
        store.control("worker", "start")
        self.addCleanup(lambda: [store.control("worker", "pause"), store.control("simulator", "pause")])

    def test_the_worker_waits_two_simulated_hours_after_a_run_before_investigating_the_case_again(self):
        store, driver, case_id = self.requeued()
        case = self.stored(driver, case_id)
        self.assertEqual(instant(case["quiet_until"]) - instant(self.clock(driver)), timedelta(hours=2))
        self.assertFalse(store.process_one()["processed"])
        self.advance(driver, 7199)
        self.assertFalse(store.process_one()["processed"])
        self.assertEqual(len(self.kind(driver, "OpsRun")), 1)
        self.advance(driver, 1)
        with approval_policy():
            again = store.process_one()
        self.assertEqual((again["processed"], again["case_id"]), (True, case_id))
        self.assertEqual(len(self.kind(driver, "OpsRun")), 2)

    def test_the_interval_also_follows_a_run_released_for_a_material_change(self):
        store, driver, result = self.run_with(lambda s, d, case: self.monitor(s, d, case, "DELIVERY_PROOF_INCOMPLETE"))
        self.assertFalse(result["processed"])
        self.running(store)
        self.assertFalse(store.process_one()["processed"])
        self.advance(driver, 7200)
        with approval_policy():
            self.assertTrue(store.process_one()["processed"])

    def test_an_operator_is_not_delayed(self):
        store, driver, case_id = self.requeued()
        with approval_policy():
            self.assertTrue(store.process_one(case_id=case_id)["processed"])           # a named case
        detail = store.case_detail(case_id)
        store.request_reanalysis(case_id, "DEMO-OPERATOR-LOCAL", detail["state_version"], "reanalyse-now")
        self.assertIsNone(self.stored(driver, case_id).get("quiet_until"))               # explicit re-analysis
        with approval_policy():
            self.assertTrue(store.process_one()["processed"])
        self.assertEqual(len(self.kind(driver, "OpsRun")), 3)

    def test_a_paused_simulation_does_not_hold_a_waiting_case(self):
        """The interval is simulated time: with the clock paused it could never pass, so it does not apply."""
        store, driver, case_id = self.requeued()
        self.assertFalse(store.process_one()["processed"])
        store.control("simulator", "pause")
        with approval_policy():
            self.assertEqual(store.process_one()["case_id"], case_id)

    def test_the_interval_is_configurable_and_zero_disables_it(self):
        self.assertEqual(reinvestigation_quiet_seconds(), 7200)
        with mock.patch.dict(os.environ, {"SUHAIL_REINVESTIGATION_QUIET_SECONDS": "600"}):
            self.assertEqual(reinvestigation_quiet_seconds(), 600)
        with mock.patch.dict(os.environ, {"SUHAIL_REINVESTIGATION_QUIET_SECONDS": "soon"}):
            self.assertEqual(reinvestigation_quiet_seconds(), 7200)
        self.assertEqual(reinvestigation_quiet_seconds(0), 0)
        store, driver = self.make()
        store.reinvestigation_quiet_seconds = 0
        store.agents = Scripted()
        with approval_policy():
            result = store.process_one(manual=True)
        self.assertIsNone(self.stored(driver, result["case_id"]).get("quiet_until"))
        self.monitor(store, driver, self.stored(driver, result["case_id"]), "DELIVERY_PROOF_INCOMPLETE")
        self.running(store)
        with approval_policy():
            self.assertTrue(store.process_one()["processed"])


if __name__ == "__main__":
    unittest.main()
