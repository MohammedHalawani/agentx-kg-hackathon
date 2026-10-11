"""The case brief: one plain account of a case, composed by code from its stored records, that never says more than
the records do. Pure tests on case details."""
import unittest

from operations import brief
from operations.canopus import code_free
from tests.test_canopus import SID, detail

EXECUTION = {"entity_id": "E1", "action_type": "REQUEST_RESCAN", "authority": "AUTO_POLICY", "status": "ACKNOWLEDGED", "executed_at": "2026-09-15T12:05:00+00:00",
             "deadline_at": "2026-09-18T12:05:00+00:00", "expected_response_at": "2026-09-15T13:00:00+00:00", "target_device": "DEMO-DEV-SR-1"}
CLEARED = {"execution_id": "E1", "verification_status": "VERIFIED", "success": True, "outcome_type": "barcode_corrected", "exception_cleared": True,
           "reason": "A readable rescan after the request matches the manifest barcode.", "verified_at": "2026-09-16T03:00:00+00:00"}
FAILED = {**CLEARED, "success": False, "outcome_type": "barcode_still_differs", "exception_cleared": False, "reason": "The rescan still differs."}


def lines(b):
    return {line["key"]: line["text_en"] for line in b["lines"]}


class BriefTests(unittest.TestCase):
    def build(self, *args, **options):
        b = brief.build(detail(*args, **options))
        b.pop("_stage_outcome")
        return b

    def test_resolved_is_true_only_for_a_case_the_verifier_closed(self):
        self.assertTrue(self.build("RESOLVED", accepted=True, verdict="ACCEPT", executions=[EXECUTION], outcome=CLEARED)["resolved"])
        for state in ("OPEN", "INVESTIGATING", "AWAITING_APPROVAL", "HUMAN_REVIEW", "ESCALATED", "NEEDS_EVIDENCE", "AWAITING_OUTCOME", "ACTION_INITIATED", "REJECTED", "NEW"):
            b = self.build(state, executions=[EXECUTION], outcome=CLEARED)       # Even with a successful outcome on record.
            self.assertFalse(b["resolved"], state)
            self.assertNotEqual(b["verification"]["status"], "verified_resolved", state)
            self.assertNotIn("Resolved:", lines(b)["status"], state)

    def test_every_state_has_a_waiting_kind_and_an_unknown_one_is_with_a_person(self):
        kinds = {state: brief.waiting_kind(state) for state in ("OPEN", "REOPENED", "INVESTIGATING", "RECOMMENDATION_READY", "AWAITING_APPROVAL", "HUMAN_REVIEW",
                                                                "ESCALATED", "NEEDS_EVIDENCE", "ACTION_INITIATED", "AWAITING_OUTCOME", "RESOLVED", "REJECTED")}
        self.assertEqual(set(kinds.values()), set(brief.WAITING))
        self.assertEqual((kinds["AWAITING_OUTCOME"], kinds["INVESTIGATING"], kinds["ESCALATED"], kinds["RESOLVED"]),
                         ("awaiting_new_evidence", "investigating", "awaiting_operator_decision", "resolved"))
        self.assertEqual(brief.waiting_kind("SOMETHING_NEW"), "awaiting_operator_decision")

    def test_a_cause_is_a_hypothesis_until_the_review_accepts_it_and_a_challenge_is_always_stated(self):
        challenged = self.build()
        self.assertEqual((challenged["suspected_cause"]["status"], challenged["review"]["status"]), ("hypothesis_not_accepted", "challenged"))
        # The challenge is stated once, in the Review line; the Finding line does not repeat it. The structured field keeps both.
        self.assertEqual(lines(challenged)["finding"], "The investigation suggests a barcode-reading problem.")
        self.assertIn("This is a hypothesis", challenged["suspected_cause"]["text_en"])
        self.assertIn("did not accept", lines(challenged)["review"])
        self.assertEqual(challenged["review"]["reason_original"], "A transient read error was not ruled out.")
        accepted = self.build(accepted=True, verdict="ACCEPT")
        self.assertEqual((accepted["suspected_cause"]["status"], accepted["review"]["status"]), ("accepted", "accepted"))
        self.assertNotIn("review", lines(accepted))
        for verdict, status in (("HUMAN_REVIEW", "asked_for_person"), ("UNAVAILABLE", "unavailable"), ("INSUFFICIENT_EVIDENCE", "challenged")):
            b = self.build(verdict=verdict)
            self.assertEqual(b["review"]["status"], status)
            self.assertIn("review", lines(b), verdict)

    def test_a_stored_plain_summary_of_the_review_reason_is_folded_into_the_review_line(self):
        case = detail()
        case["narration"]["events"].append({"id": "N9", "kind": "canopus_summary", "phase": "review",
                                            "text_en": "The reviewer found that a one-off read error was not ruled out.", "text_ar": "وجد المراجع أن خطأ القراءة العابر لم يُستبعد."})
        folded = lines(brief.build(case))["review"]
        self.assertEqual(folded, "The independent review did not accept this conclusion: the reviewer found that a one-off read error was not ruled out.")
        case["narration"]["events"][-1]["text_en"] = "The reviewer cited DEMO-SHP-000001-SCAN-009 under AUTH-16."
        self.assertEqual(lines(brief.build(case))["review"], "The independent review did not accept this conclusion and asked for it to be revised.")

    def test_a_sent_request_says_who_what_is_awaited_the_deadline_and_that_it_is_simulated(self):
        b = self.build("AWAITING_OUTCOME", accepted=True, verdict="ACCEPT", executions=[EXECUTION])
        action, = b["actions"]
        self.assertEqual((action["status"], action["simulated"], action["authorized_by"], action["continues_automatically"]), ("sent", True, "automatic_policy", True))
        self.assertEqual((action["recipient"]["known"], action["recipient"]["id"]), (True, "DEMO-DEV-SR-1"))
        self.assertEqual(action["awaiting"]["text_en"], "a new barcode read of this parcel")
        self.assertEqual(action["deadline_at"], EXECUTION["deadline_at"])
        for part in ("(simulated)", "DEMO-DEV-SR-1", "a new barcode read of this parcel", "verifies the result automatically", "2026-09-18 12:05 UTC"):
            self.assertIn(part, action["text_en"])
        # No answer time is shown without evidence behind it: the simulator's own schedule is never exposed.
        self.assertIsNone(action["expected_response_at"])
        self.assertEqual((b["waiting_kind"], b["verification"]["status"]), ("awaiting_new_evidence", "awaiting_evidence"))
        self.assertIn("Nothing is verified yet", lines(b)["status"])

    def test_an_unknown_recipient_is_said_to_be_unknown_and_an_undelivered_request_is_not_a_sent_one(self):
        nameless = {k: v for k, v in EXECUTION.items() if k != "target_device"}
        action = self.build("AWAITING_OUTCOME", executions=[nameless])["actions"][0]
        self.assertEqual((action["recipient"]["known"], action["recipient"]["id"]), (False, None))
        self.assertIn("names no specific recipient", action["text_en"])
        undelivered = self.build("HUMAN_REVIEW", executions=[{**nameless, "status": "NOT_ACKNOWLEDGED"}])
        self.assertEqual((undelivered["actions"][0]["status"], undelivered["verification"]["status"]), ("not_delivered", "not_delivered"))
        self.assertIn("could not be delivered", undelivered["actions"][0]["text_en"])
        self.assertIsNone(undelivered["actions"][0]["awaiting"])

    def test_outcomes_are_told_apart(self):
        failed = self.build("HUMAN_REVIEW", accepted=True, verdict="ACCEPT", executions=[EXECUTION], outcome=FAILED)
        self.assertEqual(failed["verification"]["status"], "verified_not_fixed")
        self.assertIn("did not find evidence", failed["actions"][0]["text_en"])
        doubted = self.build("HUMAN_REVIEW", executions=[EXECUTION], outcome=CLEARED)          # Verified, reviewer never accepted.
        self.assertEqual((doubted["verification"]["status"], doubted["resolved"]), ("verified_not_closed", False))
        remains = self.build("HUMAN_REVIEW", executions=[EXECUTION], outcome={**CLEARED, "exception_cleared": False})
        self.assertEqual(remains["verification"]["status"], "verified_but_problem_remains")
        self.assertIn("not closed", doubted["verification"]["text_en"])
        reassessing = self.build("OPEN", executions=[EXECUTION], outcome=CLEARED)
        self.assertEqual(reassessing["verification"]["status"], "verified_awaiting_reassessment")
        self.assertEqual(self.build()["verification"]["status"], "not_applicable")
        other = self.build("HUMAN_REVIEW", executions=[EXECUTION], outcome={**CLEARED, "execution_id": "E0"})
        self.assertIsNone(other["actions"][0]["outcome"])                    # An outcome of another execution is not this one's.

    def test_sentences_carry_no_codes_and_the_codes_are_in_their_own_fields(self):
        for b in (self.build(), self.build("AWAITING_OUTCOME", accepted=True, verdict="ACCEPT", executions=[EXECUTION]),
                  self.build("RESOLVED", accepted=True, verdict="ACCEPT", executions=[EXECUTION], outcome=CLEARED), self.build("ESCALATED"), self.build("OPEN", action=None)):
            for line in b["lines"]:
                self.assertTrue(code_free(line["text_en"]), line["text_en"])
                self.assertTrue(line["text_ar"] and line["label_ar"], line["key"])
            for text in (b["what_happened"]["text_en"], b["suspected_cause"]["text_en"], b["review"]["text_en"], b["policy"]["text_en"], b["verification"]["text_en"]):
                self.assertTrue(code_free(text), text)
        b = self.build()
        self.assertEqual(b["technical"], {"workflow_state": "HUMAN_REVIEW", "state_version": 7, "run_id": "DEMO-OPS-RUN-1",
                                          "authority_rule_id": "AUTH-14-symptom-floor", "review_verdict": "REVISE", "closure": None})
        self.assertEqual((b["policy"]["rule_id"], b["suspected_cause"]["code"], b["what_happened"]["symptoms"][0]["code"]),
                         ("AUTH-14-symptom-floor", "BARCODE_MISMATCH", "BARCODE_READ_DIFFERS"))

    def test_evidence_is_labelled_for_a_person_with_the_id_kept_apart(self):
        b = self.build()
        item, = b["evidence"]
        self.assertEqual((item["id"], item["in_graph"], item["facility_id"]), (f"{SID}-SCAN-009", True, "DEMO-SORT-JED-01"))
        self.assertEqual(item["label_en"], "Scan (sorter read) at DEMO-SORT-JED-01, 2026-09-15 11:23 UTC")
        self.assertEqual(brief.evidence_label("DEMO-CMP-abc", {})["in_graph"], False)

    def test_the_brief_is_the_same_for_the_same_records(self):
        self.assertEqual(brief.build(detail()), brief.build(detail()))


class StageFactTests(unittest.TestCase):
    def test_each_completed_stage_says_what_happened(self):
        from tests.test_narration import run_events
        facts = brief.stage_facts(run_events(), {"status": "awaiting_evidence", "short_en": "Awaiting new evidence", "short_ar": "بانتظار أدلة جديدة"})
        by = {(f["stage"], f["iteration"]): f for f in facts}
        self.assertEqual([f["stage"] for f in facts], ["extract", "retrieve", "classify", "retrieve_context", "recommend", "review", "writeback", "outcome"])
        self.assertEqual(by[("extract", 0)]["fact_en"], "Case opened: a barcode read does not match the shipment's manifest")
        self.assertEqual(by[("retrieve", 0)]["fact_en"], "40 records and 90 connections read from the graph")
        self.assertEqual(by[("classify", 0)]["fact_en"], "Suspected cause: a barcode-reading problem (medium confidence), after 2 checks")
        self.assertEqual(by[("retrieve_context", 0)]["fact_en"], "3 verified similar cases found")
        self.assertEqual(by[("recommend", 0)]["fact_en"], "Proposed: rescan request")
        self.assertEqual((by[("review", 1)]["fact_en"], by[("review", 1)]["status"]), ("Independent review: accepted", "done"))
        self.assertEqual(by[("writeback", 1)]["fact_en"], "Request sent automatically under policy")
        self.assertEqual((facts[-1]["status"], facts[-1]["fact_en"]), ("running", "Awaiting new evidence"))
        for fact in facts:
            self.assertTrue(code_free(fact["fact_en"]), fact["fact_en"])

    def test_a_rejected_review_and_a_running_stage_are_shown_as_such(self):
        from tests.test_narration import event, run_events
        rejected = brief.stage_facts(run_events("REVISE"))
        review = next(f for f in rejected if f["stage"] == "review")
        self.assertEqual((review["status"], review["fact_en"]), ("rejected", "Independent review: asked for a revision"))
        running = brief.stage_facts([event(1, "extract", "RUNNING")])
        self.assertEqual([(f["stage"], f["status"], f["fact_en"]) for f in running], [("extract", "running", None)])
        self.assertEqual(brief.stage_facts([]), [])


if __name__ == "__main__":
    unittest.main()
