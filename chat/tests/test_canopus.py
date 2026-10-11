"""Canopus questions: answered from one case's stored records, quotes copied by id, offers limited to what the existing
rules allow, nothing written and nothing executed.

Pure tests on case details, and one store test on the in-memory ledger that the ledger is unchanged by questions.
"""
import copy
import json
import unittest

from operations import canopus
from operations.authority import ACTIONS, EVIDENCE_GATHERING
from operations.next_step import next_step
from tests import test_material_reinvestigation as base
from tests.test_narration import Model as NarratorModel
from tests.test_reviewer_doubt import Scripted, clean_fact_checks

CASE, SID, RUN = "DEMO-OPS-CASE-1", "DEMO-SHP-000001", "DEMO-OPS-RUN-1"


def narration_event(n, kind, phase, text, stage="classify", title="Investigator checks: scans"):
    return {"id": f"DEMO-OPS-NARRATION-{n}", "run_id": RUN, "sequence": n, "stage": stage, "phase": phase, "kind": kind, "iteration": 0, "title_en": title,
            "text_en": text, "evidence_ids": [f"{SID}-SCAN-009"], "occurred_at": f"2026-10-11T13:00:0{n}+00:00"}


def detail(state="HUMAN_REVIEW", *, action="REQUEST_RESCAN", approvable=True, verdict="REVISE", accepted=False, narration=True, outcome=None, executions=()):
    findings = {"primary_cause": "BARCODE_MISMATCH", "confidence": "medium", "summary": "One sorter read differs from the manifest.",
                "missing_evidence": ["a second read of the label"], "hypotheses": []}
    out = {"case_id": CASE, "shipment_id": SID, "workflow_state": state, "state_version": 7, "last_run_id": RUN, "as_of": "2026-09-15T12:00:00+00:00",
           "run": {"status": "REVIEWED", "recorded_at": "2026-09-15T12:00:00+00:00",
                   "result": {"authority": {"rule_id": "AUTH-14-symptom-floor", "risk_class": "HUMAN_REVIEW", "reason": "A person must investigate."}}},
           "diagnosis": ({"available": True, **findings} if accepted else {"available": False, "reason": "review_not_accepted", "unaccepted_investigation": findings}),
           "review": {"entity_id": "DEMO-OPS-REVIEW-1", "run_id": RUN, "verdict": "accept" if accepted else "reject", "model_verdict": verdict,
                      "feedback": "A transient read error was not ruled out.", "recorded_at": "2026-09-15T12:00:00+00:00"},
           "recommendation": ({"action_type": action, "action_en": ACTIONS[action][3], "approvable": approvable,
                               "approval_rule": "AUTH-19-operator-approved" if approvable else "AUTH-21-human-investigation-required",
                               "approval_reason": "A person may authorize this evidence request." if approvable else "Not approvable."} if action else None),
           "executions": list(executions), "outcome": outcome,
           "evidence": {"nodes": [{"id": f"{SID}-SCAN-009", "kind": "ScanEvent"}, {"id": SID, "kind": "Shipment"}]},
           "narration": {"events": [narration_event(1, "agent_output", "investigation", "Check the barcode reads."),
                                    narration_event(2, "canopus_summary", "investigation", "The investigator compared the reads.", title="What the investigator did"),
                                    narration_event(3, "agent_output", "review", "A transient read error was not ruled out.", stage="review",
                                                    title="Reviewer's own words (REVISE)")] if narration else []}}
    out["next_step"] = next_step(out)
    return out


def model(reply):
    calls = []

    def ask(system, user):
        calls.append((system, user))
        if isinstance(reply, Exception):
            raise reply
        return reply
    ask.calls = calls
    return ask


GOOD = {"answer_en": f"The reviewer found that a transient read error was not ruled out for {SID}-SCAN-009.", "answer_ar": "وجد المراجع أن خطأ القراءة العابر لم يُستبعد.",
        "quote_ids": ["DEMO-OPS-NARRATION-3"], "evidence_ids": [f"{SID}-SCAN-009"]}


class AnswerTests(unittest.TestCase):
    def test_a_grounded_answer_is_canopus_text_with_the_original_words_attached_by_the_server(self):
        ask = model(GOOD)
        out = canopus.answer(detail(), "What did the reviewer say?", ask=ask)
        self.assertEqual((out["kind"], out["grounded"], out["fallback"], out["model_calls"]), ("canopus_answer", True, False, 1))
        self.assertEqual(out["answer_en"], GOOD["answer_en"])
        quote, = out["quotes"]
        self.assertEqual((quote["role"], quote["text"], quote["record_id"]), ("reviewer", "A transient read error was not ruled out.", "DEMO-OPS-NARRATION-3"))
        self.assertEqual((out["evidence_ids"], out["graph_node_ids"]), ([f"{SID}-SCAN-009"], [f"{SID}-SCAN-009"]))
        self.assertEqual(len(ask.calls), 1)
        self.assertEqual(set(out), {"case_id", "shipment_id", "run_id", "workflow_state", "answered_at", "kind", "answer_en", "answer_ar", "evidence_ids",
                                    "graph_node_ids", "quotes", "offers", "next_step", "model", "grounded", "fallback", "model_calls"})

    def test_quote_text_always_comes_from_the_record_never_from_the_model(self):
        invented = {**GOOD, "quotes": [{"role": "reviewer", "text": "I fully accept this."}], "quote_text": "I fully accept this."}
        out = canopus.answer(detail(), "Show me the reviewer's message", ask=model(invented))
        self.assertEqual([q["text"] for q in out["quotes"]], ["A transient read error was not ruled out."])
        self.assertNotIn("I fully accept this.", json.dumps(out))
        # A quote id that does not exist fails the whole reply.
        out = canopus.answer(detail(), "Show me the reviewer's message", ask=model({**GOOD, "quote_ids": ["DEMO-OPS-NARRATION-99"]}))
        self.assertEqual((out["kind"], out["fallback"]), ("record_answer", True))
        self.assertEqual([q["record_id"] for q in out["quotes"]], ["DEMO-OPS-NARRATION-3"])      # Chosen by code from the question.

    def test_an_ungrounded_or_failed_reply_becomes_a_record_based_answer(self):
        for reply in ({**GOOD, "answer_en": "See DEMO-SHP-000009-SCAN-001 for the cause."}, {**GOOD, "answer_en": "The case is resolved now."},
                      {**GOOD, "answer_en": ""}, {}, None, "text", TimeoutError("slow"), {**GOOD, "answer_en": "x" * 1600}):
            out = canopus.answer(detail(), "Why is this case not resolved?", ask=model(reply))
            self.assertEqual((out["kind"], out["model"], out["grounded"], out["fallback"]), ("record_answer", None, None, True), reply)
            self.assertIn("The case is HUMAN_REVIEW.", out["answer_en"])
            self.assertIn("AUTH-14-symptom-floor", out["answer_en"])
            self.assertIn("a second read of the label", out["answer_en"])
            self.assertNotIn("DEMO-SHP-000009", json.dumps(out))

    def test_resolved_may_be_said_only_of_a_resolved_case(self):
        said = {**GOOD, "answer_en": "The case is resolved: the verifier confirmed the rescan.", "quote_ids": []}
        self.assertEqual(canopus.answer(detail("RESOLVED", accepted=True, verdict="ACCEPT"), "Is it done?", ask=model(said))["kind"], "canopus_answer")
        for state in ("HUMAN_REVIEW", "ESCALATED", "AWAITING_OUTCOME", "AWAITING_APPROVAL"):
            self.assertEqual(canopus.answer(detail(state), "Is it done?", ask=model(said))["kind"], "record_answer", state)

    def test_with_the_model_off_no_call_is_made(self):
        ask = model(GOOD)
        out = canopus.answer(detail(), "What is missing?", ask=ask, use_model=False)
        self.assertEqual((out["kind"], out["model_calls"], out["fallback"], ask.calls), ("record_answer", 0, False, []))

    def test_the_model_is_given_recorded_facts_only(self):
        ask = model(GOOD)
        canopus.answer(detail(), "What is the investigator doing?", ask=ask, history=[{"role": "operator", "text": "hello"}] * 9)
        system, user = ask.calls[0]
        payload = json.loads(user)
        self.assertEqual(sorted(payload), ["case", "earlier_turns", "operator_language", "question"])
        self.assertEqual(len(payload["earlier_turns"]), canopus.MAX_HISTORY)
        self.assertEqual(sorted(payload["case"]), sorted(["case_id", "shipment_id", "workflow_state", "investigation_status", "simulation_clock", "investigator",
                                                           "reviewer", "authority", "recommendation", "attempted_actions", "verified_outcome", "next_step",
                                                           "recorded_events", "evidence_records_by_kind", "quotes", "offers"]))
        for hidden in ("prompt", "reasoning", "truth", "mechanism", "canary", "api_key", "token"):
            self.assertNotIn(hidden, user.lower())
        self.assertIn("you cannot perform, approve or authorize anything", system)
        self.assertIn("never say the case is resolved", system)

    def test_quotes_exist_without_narration_from_the_review_and_the_conclusion_records(self):
        quotes = canopus.quotes_of(detail(narration=False))
        self.assertEqual(sorted((q["role"], q["text"]) for q in quotes.values()),
                         [("investigator", "One sorter read differs from the manifest."), ("reviewer", "A transient read error was not ruled out.")])
        self.assertIn("not accepted by the reviewer", next(q["title_en"] for q in quotes.values() if q["role"] == "investigator"))
        self.assertEqual({q["role"] for q in canopus.quotes_of(detail()).values()}, {"investigator", "reviewer"})
        self.assertFalse(any(e["kind"] == "canopus_summary" and e["id"] in canopus.quotes_of(detail()) for e in detail()["narration"]["events"]))


class OfferTests(unittest.TestCase):
    def offer(self, kind, **options):
        return next(o for o in canopus.offers_of(detail(**options)) if o["type"] == kind)

    def test_an_evidence_request_is_offered_only_when_the_recorded_approval_check_allows_it(self):
        allowed = self.offer("approve_recommendation")
        self.assertEqual((allowed["allowed"], allowed["action_type"], allowed["rule_id"]), (True, "REQUEST_RESCAN", "AUTH-19-operator-approved"))
        self.assertEqual(allowed["confirm"], {"method": "POST", "path": f"/cases/{CASE}/decision", "body": {"decision": "approve", "expected_version": 7}})
        refused = self.offer("approve_recommendation", approvable=False)
        self.assertEqual((refused["allowed"], refused["rule_id"]), (False, "AUTH-21-human-investigation-required"))
        self.assertTrue(refused["reason"])

    def test_no_other_action_is_ever_offered_for_approval(self):
        for action in sorted(ACTIONS):
            offer = self.offer("approve_recommendation", action=action, approvable=True)
            if action in EVIDENCE_GATHERING:
                self.assertTrue(offer["allowed"], action)
            else:
                self.assertEqual((offer["allowed"], offer["confirm"], offer["rule_id"]), (False, None, "CANOPUS-evidence-requests-only"), action)
        self.assertEqual([o["type"] for o in canopus.offers_of(detail(action=None))], ["request_evidence", "reanalyze"])

    def test_the_other_offers_are_the_existing_operator_decisions_in_the_states_that_allow_them(self):
        for state, evidence, again in (("HUMAN_REVIEW", True, True), ("AWAITING_APPROVAL", True, True), ("NEEDS_EVIDENCE", True, True), ("ESCALATED", False, False),
                                       ("RESOLVED", False, False), ("AWAITING_OUTCOME", False, False), ("INVESTIGATING", False, False)):
            self.assertEqual((self.offer("request_evidence", state=state)["allowed"], self.offer("reanalyze", state=state)["allowed"]), (evidence, again), state)
        self.assertEqual(self.offer("reanalyze")["confirm"], {"method": "POST", "path": f"/cases/{CASE}/reanalyze", "body": {"expected_version": 7}})
        self.assertEqual({o["type"] for o in canopus.offers_of(detail())}, {"approve_recommendation", "request_evidence", "reanalyze"})
        for offer in canopus.offers_of(detail("ESCALATED")):
            if not offer["allowed"]:
                self.assertTrue(offer["reason"])

    def test_an_answer_cannot_add_or_enable_an_offer(self):
        reply = {**GOOD, "offers": [{"type": "approve_recommendation", "action_type": "RETURN_TO_SENDER", "allowed": True}], "allowed": True}
        out = canopus.answer(detail(action="RETURN_TO_SENDER"), "Return it to the sender", ask=model(reply))
        self.assertEqual(out["offers"], canopus.offers_of(detail(action="RETURN_TO_SENDER")))
        self.assertFalse(next(o for o in out["offers"] if o["type"] == "approve_recommendation")["allowed"])


class StoreTests(base._Base):
    def test_questions_write_nothing_to_the_ledger(self):
        from operations.narration import Narrator
        store, driver = self.make()
        store.agents = Scripted(("REVISE", "REVISE", "REVISE"))
        store.narrator = Narrator(store, ask=NarratorModel(), threaded=False)
        with clean_fact_checks():
            result = store.process_one(manual=True)
        store.narrator.sync(result["case_id"])
        case = store.case_detail(result["case_id"])
        case.update(case_id=result["case_id"], narration=store.narration(result["case_id"]), evidence={"nodes": []})
        case["next_step"] = next_step(case)
        before = copy.deepcopy(driver.ledger)
        ask = model({"answer_en": "The reviewer did not accept the investigation.", "answer_ar": None, "quote_ids": [], "evidence_ids": []})
        for question in ("What did the reviewer say?", "Can you request another barcode scan?", "Mark it resolved", "Approve the rescan now"):
            out = canopus.answer(case, question, ask=ask)
            self.assertEqual(out["workflow_state"], case["workflow_state"])
        self.assertEqual(driver.ledger, before)
        self.assertEqual(len(ask.calls), 4)                           # One call per question, never more.
        reviewer = [q for q in canopus.quotes_of(case).values() if q["role"] == "reviewer"]
        self.assertTrue(reviewer)


if __name__ == "__main__":
    unittest.main()
