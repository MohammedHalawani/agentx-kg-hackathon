"""Carried review items before the redesigned UI is connected: L2, L3, L5, L6, L9, L11, L12.

(L7, a rules-only proposal never executable on approval, and L8, transitive truth isolation including
store.py, are tested in test_s5_safeguards; L10 in test_development_reset; L1 in the frontend.)
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations import investigator
from operations.agents import BLAME
from operations.graph import investigate as run_graph
from operations.lifecycle import HARNESS_ACTOR, OperationsConflict, operator_ids, require_actor
from operations.reasoning import public_evidence
from tests import test_investigator as ti
from tests import test_operations_store as _store

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PhysicalCheckRuleTests(ti.Base):
    """L2: the investigator asking for a physical check has its own rule and text, not the rule-conflict one."""
    def run_with(self, physical):
        sid = self.shipment("different_barcode")
        context = public_evidence(self.world, sid, self.world.config.as_of)
        fake = ti.FakeInvestigator(lambda tools: [("scans", {})], ["ACCEPT"])
        fake.cause, fake.action, fake.physical = "BARCODE_MISMATCH", "REQUEST_RESCAN", physical
        result, _ = run_graph(sid, context["as_of"], self.world.config, lambda *_: context, lambda *_: [], agents=fake,
                              live_session=True, symptoms=("BARCODE_READ_DIFFERS",), heartbeats=ti.heartbeats_from(self.world))
        return result["authority"]

    def test_physical_check_request_is_its_own_rule(self):
        authority = self.run_with(True)
        self.assertEqual((authority["risk_class"], authority["rule_id"]), ("HUMAN_REVIEW", "AUTH-23-physical-check-requested"))
        self.assertNotIn("Deterministic evidence rules", authority["reason"])
        self.assertTrue(authority["inputs"]["requires_physical_check"])
        self.assertFalse(authority["inputs"]["rule_conflict"])
        self.assertEqual(self.run_with(False)["risk_class"], "AUTO")  # The same case without the request.


class InvalidOutputLabelTests(ti.Base):
    """L3: output that never passes validation is labelled invalid model output, not an unavailable model."""
    def tools(self):
        return super().tools(self.shipment("different_barcode"), self.world.config.as_of, symptoms=("BARCODE_READ_DIFFERS",))

    def test_validation_failures_and_transport_failures_are_labelled_apart(self):
        bad = {"action": "conclude", "primary_cause": "NOT_A_CAUSE", "hypotheses": []}
        out = investigator.investigate(self.tools(), turn=ti.scripted(bad, bad))
        self.assertEqual((out["mode"], out["degraded"]), ("invalid_model_output", True))
        def boom(messages): raise TimeoutError("slow")
        out = investigator.investigate(self.tools(), turn=ti.scripted(boom, boom))
        self.assertEqual((out["mode"], out["degraded"]), ("model_unavailable", True))
        call = {"action": "call", "tool": "policy", "args": {}, "purpose": "Read thresholds."}
        out = investigator.investigate(self.tools(), turn=ti.scripted(*[call] * (investigator.MAX_TOOL_CALLS + 2)))
        self.assertEqual(out["mode"], "invalid_model_output")  # The model answered but never concluded validly.

    def test_reviewer_invalid_output_stays_unavailable_for_authority_but_says_why(self):
        def garbage(system, user, default): return {"verdict": "LOOKS_FINE", "feedback": "x"}
        def down(system, user, default): raise ConnectionError("down")
        invalid = investigator.review({"hypotheses": []}, {}, [], [], ask=garbage)
        unavailable = investigator.review({"hypotheses": []}, {}, [], [], ask=down)
        self.assertEqual((invalid["verdict"], invalid["mode"]), ("UNAVAILABLE", "invalid_model_output"))
        self.assertEqual((unavailable["verdict"], unavailable["mode"]), ("UNAVAILABLE", "model_unavailable"))


class _Store(unittest.TestCase):
    setUpClass = classmethod(lambda cls: setattr(cls, "world", generate(Config(total=90))))
    make = _store.StoreTests.make
    approvable = _store.StoreTests.approvable

    def kind(self, driver, kind):
        return [v for k, v in driver.ledger.values() if k == kind]


class InvalidOutputAuditTests(_Store):
    def test_the_audit_says_the_investigator_output_failed_validation(self):
        class Invalid(ti.FakeInvestigator):
            def investigate(self, tools, on_step=None, feedback=None):
                bad = {"action": "conclude", "primary_cause": "NOT_A_CAUSE", "hypotheses": []}
                return investigator.investigate(tools, turn=ti.scripted(bad, bad), on_step=on_step)
        store, driver = self.make()
        store.agents = Invalid(lambda tools: [], [])
        store.process_one(manual=True)
        [degraded] = [a for a in self.kind(driver, "OpsAudit") if a["event_type"] == "MODEL_DEGRADED"]
        self.assertIn("investigator returned output that failed validation", degraded["result"])
        self.assertNotIn("unavailable", degraded["result"])


class EscalatedNotApprovableTests(_Store):
    """L5: an escalated case is not served as approvable."""
    def test_escalated_case_is_not_approvable(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        self.assertTrue(case["recommendation"]["approvable"])
        store.decide(case["case_id"], "escalate", "DEMO-OPERATOR-LOCAL", case["state_version"], "escalate-l5")
        served = store.case_detail(case["case_id"])
        self.assertEqual(served["workflow_state"], "ESCALATED")
        self.assertEqual((served["recommendation"]["approvable"], served["recommendation"]["approval_rule"]),
                         (False, "LIFECYCLE-not-awaiting-decision"))
        with self.assertRaises(OperationsConflict):
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", served["state_version"], "approve-escalated")
        self.assertEqual(self.kind(driver, "OpsExecution"), [])


class BlameFilterTests(unittest.TestCase):
    """L6: accusatory statements are blocked; neutral custody statements are not."""
    ACCUSATORY = ("The driver kept the parcel.", "the driver probably kept it", "The courier took the package home.",
                  "The neighbour took the parcel.", "The contractor withheld the shipment.", "The driver may have kept the parcel.",
                  "Drivers kept the parcels.", "The driver lost the parcel.", "The recipient lied about the delivery.",
                  "The courier deliberately skipped the scan.", "Possible theft.", "The recipient is at fault.")
    NEUTRAL = ("The parcel remains with the driver.", "Last corroborated custody is the driver; no return scan was recorded.",
               "The driver's device stopped syncing at 11:00.", "The recipient was unavailable at the address.",
               "The driver took a photo at the door.", "The customer kept calling the hotline.",
               "The driver has not returned the parcel to the depot yet.", "The parcel was kept at the depot overnight.",
               "Custody is with the contractor vehicle; the parcel is not reconciled.")

    def test_accusations_are_blocked_and_neutral_custody_facts_are_not(self):
        self.assertEqual([s for s in self.ACCUSATORY if not BLAME.search(s)], [])
        self.assertEqual([s for s in self.NEUTRAL if BLAME.search(s)], [])

    def test_the_investigator_rejects_a_conclusion_that_blames_the_driver(self):
        out = {"hypotheses": [{"cause": "UNKNOWN", "status": "uncertain", "supporting_evidence_ids": [], "contradicting_evidence_ids": [],
                               "assessment": "No receipt scan."}], "primary_cause": "UNKNOWN", "confidence": "low",
               "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "missing_evidence": [], "summary": "The driver kept the parcel."}
        self.assertIn("blame", investigator.validate_conclusion(out, set()))
        out["summary"] = "The parcel remains with the driver; no return scan is recorded."
        self.assertIsNone(investigator.validate_conclusion(out, set()))


class SupersededReviewTests(_Store):
    """L9: while a newer investigation is queued or running, no review is served as current."""
    def test_no_review_is_current_during_reanalysis(self):
        store, driver, result = self.approvable()
        case = store.case_detail(result["case_id"])
        self.assertEqual(case["review"]["verdict"], "accept")
        store.request_reanalysis(case["case_id"], "DEMO-OPERATOR-LOCAL", case["state_version"], "reanalyze-l9")
        self.assertIsNone(store.case_detail(case["case_id"])["review"])  # Queued.
        seen = []
        original = store.reader.evidence
        def during(sid, as_of):
            seen.append(store.case_detail(case["case_id"])["review"])
            return original(sid, as_of)
        store.reader.evidence = during
        store.agents = _store.agent_investigator(verdicts=("HUMAN_REVIEW",))
        store.process_one(case_id=case["case_id"])
        store.reader.evidence = original
        self.assertIsNone(seen[0])  # Running.
        after = store.case_detail(case["case_id"])
        self.assertEqual((after["review"]["verdict"], after["review"]["run_id"]), ("human_review", after["last_run_id"]))


class OperatorIdentityTests(_Store):
    """L11: operators are configurable; the harness records under its own id with source "harness"."""
    def test_configured_operators_and_the_harness_identity(self):
        self.assertEqual(operator_ids(), ("DEMO-OPERATOR-LOCAL",))
        with mock.patch.dict(os.environ, {"SUHAIL_OPERATOR_IDS": "DEMO-OPERATOR-A, DEMO-OPERATOR-B"}):
            self.assertEqual(operator_ids(), ("DEMO-OPERATOR-A", "DEMO-OPERATOR-B"))
            self.assertEqual(require_actor("DEMO-OPERATOR-B"), "operator")
            with self.assertRaises(OperationsConflict):
                require_actor("DEMO-OPERATOR-LOCAL")  # No longer configured.
        for value in (HARNESS_ACTOR, "SYN-OPERATOR-X"):  # The harness id cannot be an operator; ids stay synthetic.
            with mock.patch.dict(os.environ, {"SUHAIL_OPERATOR_IDS": value}), self.assertRaises(OperationsConflict):
                operator_ids()
        self.assertEqual(require_actor(HARNESS_ACTOR, source="harness"), "harness")
        for actor, source in ((HARNESS_ACTOR, "operator"), ("DEMO-OPERATOR-LOCAL", "harness"), ("DEMO-OPERATOR-LOCAL", "model")):
            with self.assertRaises(OperationsConflict):
                require_actor(actor, source=source)

    def test_a_harness_finding_is_recorded_under_the_harness(self):
        store, driver = self.make()
        result = store.process_one(manual=True)
        def to_human(tx):
            tx.ledger[result["case_id"]][1]["workflow_state"] = "HUMAN_REVIEW"
        driver.execute_write(to_human)
        case = store.case_detail(result["case_id"])
        evidence = [n["id"] for n in store.reader.evidence(case["shipment_id"], store.status()["as_of"])["nodes"] if n["kind"] == "Package"]
        with self.assertRaises(OperationsConflict):  # The harness never acts as an operator.
            store.record_human_outcome(case["case_id"], HARNESS_ACTOR, "parcel_located", "Parcel found during the harness check.",
                                       evidence, case["state_version"], "harness-as-operator")
        store.record_human_outcome(case["case_id"], HARNESS_ACTOR, "parcel_located", "Parcel found during the harness check.",
                                   evidence, case["state_version"], "harness-finding", source="harness")
        [outcome] = self.kind(driver, "OpsOutcome")
        self.assertEqual((outcome["verifier_id"], outcome["source"]), (HARNESS_ACTOR, "harness"))
        audit = next(a for a in self.kind(driver, "OpsAudit") if a["event_type"] == "HUMAN_OUTCOME_RECORDED")
        self.assertEqual(audit["actor_id"], HARNESS_ACTOR)
        self.assertIn("(harness)", audit["result"])

    def test_the_local_session_uses_the_configured_operator(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from backend.local_authority import LocalOperationsAuthority
        with mock.patch.dict(os.environ, {"SUHAIL_OPERATOR_IDS": "DEMO-OPERATOR-NIGHT"}):
            self.assertEqual(LocalOperationsAuthority.operator_id(), "DEMO-OPERATOR-NIGHT")

    def test_the_s5_harness_records_findings_and_approvals_under_its_own_id(self):
        source = (ROOT / "scripts" / "s5_scenarios.py").read_text(encoding="utf-8")
        self.assertNotIn("DEMO-OPERATOR-LOCAL", source)
        self.assertEqual(source.count('source="harness"'), 3)  # The finding, the refusal attempt and the approval.


class DirtyTreeTests(unittest.TestCase):
    """L12: the S5 runner's dirty-tree check counts untracked files."""
    def test_untracked_files_make_the_tree_dirty(self):
        spec = importlib.util.spec_from_file_location("s5_scenarios_under_test", ROOT / "scripts" / "s5_scenarios.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args], cwd=tmp,
                               check=True, capture_output=True)
            git("init", "-q")
            pathlib.Path(tmp, "a.txt").write_text("a", encoding="utf-8")
            git("add", "a.txt")
            git("commit", "-q", "-m", "a")
            self.assertFalse(module.git_state(tmp)[1])
            pathlib.Path(tmp, "new_module.py").write_text("x = 1", encoding="utf-8")
            self.assertTrue(module.git_state(tmp)[1])


if __name__ == "__main__":
    unittest.main()
