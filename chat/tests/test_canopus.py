"""Canopus questions: answered in operator language from one case's stored records, the agents' words copied by id and
only when asked for, offers limited to what the existing rules allow now, nothing written and nothing executed.

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
            "text_en": text, "evidence_ids": [f"{SID}-SCAN-009"], "graph_node_ids": [f"{SID}-SCAN-009"], "occurred_at": f"2026-10-11T13:00:0{n}+00:00"}


def detail(state="HUMAN_REVIEW", *, action="REQUEST_RESCAN", approvable=True, verdict="REVISE", accepted=False, narration=True, outcome=None, executions=(),
           approval_rule=None):
    findings = {"primary_cause": "BARCODE_MISMATCH", "confidence": "medium", "summary": "One sorter read differs from the manifest.",
                "missing_evidence": ["a second read of the label"],
                "hypotheses": [{"cause": "BARCODE_MISMATCH", "status": "supported", "supporting_evidence_ids": [f"{SID}-SCAN-009"]}]}
    out = {"case_id": CASE, "shipment_id": SID, "workflow_state": state, "state_version": 7, "last_run_id": RUN, "as_of": "2026-09-15T12:00:00+00:00",
           "symptom_codes": ["BARCODE_READ_DIFFERS"],
           "run": {"status": "REVIEWED", "recorded_at": "2026-09-15T12:00:00+00:00",
                   "result": {"authority": {"rule_id": "AUTH-14-symptom-floor", "risk_class": "HUMAN_REVIEW", "reason": "A person must investigate."}}},
           "diagnosis": ({"available": True, **findings} if accepted else {"available": False, "reason": "review_not_accepted", "unaccepted_investigation": findings}),
           "review": {"entity_id": "DEMO-OPS-REVIEW-1", "run_id": RUN, "verdict": "accept" if accepted else "reject", "model_verdict": verdict,
                      "feedback": "A transient read error was not ruled out.", "recorded_at": "2026-09-15T12:00:00+00:00"},
           "recommendation": ({"action_type": action, "action_en": ACTIONS[action][3], "approvable": approvable,
                               "approval_rule": approval_rule or ("AUTH-19-operator-approved" if approvable else "AUTH-21-human-investigation-required"),
                               "approval_reason": "A person may authorize this evidence request." if approvable else "Not approvable."} if action else None),
           "executions": list(executions), "outcome": outcome,
           "evidence": {"nodes": [{"id": f"{SID}-SCAN-009", "kind": "ScanEvent", "properties": {"facility_id": "DEMO-SORT-JED-01", "observation_type": "SORTER_READ",
                                                                                                "occurred_at": "2026-09-15T11:23:00+00:00"}},
                                  {"id": SID, "kind": "Shipment", "properties": {}}]},
           "pipeline": {"events": []},
           "narration": {"events": [narration_event(1, "agent_output", "investigation", "Check the barcode reads."),
                                    narration_event(2, "canopus_summary", "investigation", "The investigator compared the reads.", title="What the investigator did"),
                                    narration_event(4, "agent_output", "investigation", "One sorter read differs from the manifest.", title="Investigator's conclusion (not yet reviewed)"),
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


GOOD = {"answer_en": "The investigation suggests a barcode-reading problem, but the independent review did not accept it: a transient read error was not ruled out.",
        "answer_ar": "يرجّح التحقيق مشكلة في قراءة الباركود، لكن المراجعة المستقلة لم تقبل ذلك.", "quote_ids": [], "evidence_ids": [f"{SID}-SCAN-009"]}
FIELDS = {"case_id", "shipment_id", "run_id", "workflow_state", "answered_at", "kind", "answer_en", "answer_ar", "evidence_ids", "graph_node_ids", "quotes",
          "offers", "unavailable_offers", "next_step", "technical", "model", "grounded", "fallback", "model_calls"}


class AnswerTests(unittest.TestCase):
    def test_a_usable_answer_is_plain_text_with_the_codes_in_separate_fields(self):
        ask = model(GOOD)
        out = canopus.answer(detail(), "Why is this case not resolved?", ask=ask)
        self.assertEqual((out["kind"], out["grounded"], out["fallback"], out["model_calls"]), ("canopus_answer", True, False, 1))
        self.assertEqual(out["answer_en"], GOOD["answer_en"])
        self.assertEqual(set(out), FIELDS)
        self.assertEqual(out["quotes"], [])                                    # Nobody asked for an agent's words.
        self.assertEqual(out["technical"], {"workflow_state": "HUMAN_REVIEW", "rule_id": "AUTH-14-symptom-floor", "review_verdict": "REVISE",
                                            "evidence_ids": [f"{SID}-SCAN-009"]})
        self.assertEqual((out["evidence_ids"], out["graph_node_ids"]), ([f"{SID}-SCAN-009"], [f"{SID}-SCAN-009"]))
        self.assertTrue(canopus.code_free(out["answer_en"]))
        self.assertEqual(len(ask.calls), 1)

    def test_an_answer_with_internal_codes_or_record_ids_is_replaced(self):
        for text in ("Under AUTH-27 the rescan may run.", "The case is HUMAN_REVIEW for now.", "It was ESCALATED by the review.",
                     "The cause is BARCODE_MISMATCH.", f"See {SID}-SCAN-009 for the read.", "Blocked by LIFECYCLE-not-awaiting-decision.",
                     "The run DEMO-OPS-RUN-1 ended.", "The reviewer said REVISE."):
            out = canopus.answer(detail(), "What is going on?", ask=model({**GOOD, "answer_en": text}))
            self.assertEqual((out["kind"], out["fallback"]), ("record_answer", True), text)
            self.assertTrue(canopus.code_free(out["answer_en"]), out["answer_en"])
        for text in (f"The rescan for {SID} goes to device DEMO-DEV-SR-SORT-JED-01 at the facility DEMO-SORT-JED-01.",
                     "The parcel is with DHL and uses a USB scanner."):      # Shipment, facility and device ids are operator vocabulary.
            self.assertTrue(canopus.code_free(text), text)

    def test_the_record_based_answer_is_the_case_brief_in_order(self):
        for reply in ({**GOOD, "answer_en": "The case is resolved now."}, {**GOOD, "answer_en": ""}, {}, None, "text", TimeoutError("slow"),
                      {**GOOD, "answer_en": "x" * 1600}, {**GOOD, "answer_en": "See DEMO-SHP-000009 instead."}):
            out = canopus.answer(detail(), "Why is this case not resolved?", ask=model(reply))
            self.assertEqual((out["kind"], out["model"], out["grounded"], out["fallback"]), ("record_answer", None, None, True), reply)
            text = out["answer_en"]
            self.assertIn("A barcode read does not match the shipment's manifest", text)
            self.assertIn("This is a hypothesis", text)
            self.assertIn("did not accept this conclusion", text)               # The reviewer's challenge is never smoothed over.
            self.assertLess(text.index("barcode read does not match"), text.index("did not accept"))
            self.assertNotIn("resolved", text.lower().replace("not resolved", ""))
            self.assertTrue(canopus.code_free(text), text)
            self.assertTrue(out["answer_ar"])

    def test_resolved_may_be_said_only_of_a_resolved_case(self):
        said = {**GOOD, "answer_en": "Yes, the case is resolved: the verifier confirmed the rescan."}
        self.assertEqual(canopus.answer(detail("RESOLVED", accepted=True, verdict="ACCEPT"), "Is it done?", ask=model(said))["kind"], "canopus_answer")
        for state in ("HUMAN_REVIEW", "ESCALATED", "AWAITING_OUTCOME", "AWAITING_APPROVAL"):
            self.assertEqual(canopus.answer(detail(state), "Is it done?", ask=model(said))["kind"], "record_answer", state)

    def test_the_agents_words_are_shown_only_when_asked_for_and_always_from_the_record(self):
        picks = {**GOOD, "quote_ids": ["DEMO-OPS-NARRATION-3"], "quotes": [{"role": "reviewer", "text": "I fully accept this."}]}
        asked = canopus.answer(detail(), "What did the reviewer say? Show me the original message.", ask=model(picks))
        self.assertEqual([(q["role"], q["text"], q["record_id"]) for q in asked["quotes"]],
                         [("reviewer", "A transient read error was not ruled out.", "DEMO-OPS-NARRATION-3")])
        self.assertNotIn("I fully accept this.", json.dumps(asked))
        not_asked = canopus.answer(detail(), "What is Suhail waiting for?", ask=model(picks))
        self.assertEqual(not_asked["quotes"], [])
        # A quote id that does not exist fails the reply; the record-based answer then chooses by the question.
        missing = canopus.answer(detail(), "Show me the reviewer's original message", ask=model({**GOOD, "quote_ids": ["DEMO-OPS-NARRATION-99"]}))
        self.assertEqual((missing["kind"], [q["record_id"] for q in missing["quotes"]]), ("record_answer", ["DEMO-OPS-NARRATION-3"]))
        investigator = canopus.answer(detail(), "Show the investigator's own words", ask=model(None))
        self.assertEqual([q["text"] for q in investigator["quotes"]], ["One sorter read differs from the manifest."])     # The conclusion, not a tool-call purpose.

    def test_with_the_model_off_no_call_is_made(self):
        ask = model(GOOD)
        out = canopus.answer(detail(), "What is missing?", ask=ask, use_model=False)
        self.assertEqual((out["kind"], out["model_calls"], out["fallback"], ask.calls), ("record_answer", 0, False, []))

    def test_the_model_is_given_the_case_brief_in_plain_language_and_nothing_else(self):
        ask = model(GOOD)
        canopus.answer(detail(), "What is the investigator doing?", ask=ask, history=[{"role": "operator", "text": "hello"}] * 9)
        system, user = ask.calls[0]
        payload = json.loads(user)
        self.assertEqual(sorted(payload), ["case", "earlier_turns", "operator_language", "question"])
        self.assertEqual(len(payload["earlier_turns"]), canopus.MAX_HISTORY)
        case = payload["case"]
        self.assertEqual(sorted(case), sorted(["shipment_id", "resolved", "what_the_case_is_waiting_for", "assessment", "what_happened", "suspected_cause",
                                               "review", "what_policy_permits", "requests_sent", "verification", "next_step", "who_acts_next",
                                               "missing_evidence", "evidence", "quotes", "what_the_operator_can_do_now", "what_is_not_possible_now"]))
        self.assertEqual(sorted(case["assessment"]), sorted(["Problem", "Finding", "Review", "Action taken", "Current status"]))
        self.assertEqual((case["resolved"], case["suspected_cause"]["status"], case["review"]["status"]), (False, "hypothesis_not_accepted", "challenged"))
        self.assertEqual(case["review"]["reason_original"], "A transient read error was not ruled out.")
        for hidden in ("prompt", "reasoning", "truth", "mechanism", "canary", "api_key", "token", "auth-", "lifecycle-"):
            self.assertNotIn(hidden, user.lower())
        for rule in ("Never write internal codes", "Never say the case is resolved", "You cannot perform, approve or authorize anything", "Requests are simulated"):
            self.assertIn(rule, system)

    def test_graph_highlights_are_real_graph_nodes_even_when_the_answer_cites_none(self):
        out = canopus.answer(detail(), "What did the reviewer say? Quote it.", ask=model({**GOOD, "quote_ids": ["DEMO-OPS-NARRATION-3"], "evidence_ids": []}))
        self.assertEqual(out["graph_node_ids"], [f"{SID}-SCAN-009"])            # From the shown quote's own record.
        plain = canopus.answer(detail(), "Why?", ask=model({**GOOD, "evidence_ids": []}))
        self.assertEqual(plain["graph_node_ids"], [f"{SID}-SCAN-009"])          # Else the leading hypothesis's records, only graph nodes.
        nothing = detail(narration=False)
        nothing["diagnosis"]["unaccepted_investigation"]["hypotheses"] = []
        self.assertEqual(canopus.answer(nothing, "Hello", ask=model({**GOOD, "evidence_ids": []}))["graph_node_ids"], [])

    def test_quotes_exist_without_narration_from_the_review_and_the_conclusion_records(self):
        quotes = canopus.quotes_of(detail(narration=False))
        self.assertEqual(sorted((q["role"], q["text"]) for q in quotes.values()),
                         [("investigator", "One sorter read differs from the manifest."), ("reviewer", "A transient read error was not ruled out.")])
        self.assertFalse(any(e["kind"] == "canopus_summary" and e["id"] in canopus.quotes_of(detail()) for e in detail()["narration"]["events"]))


class OfferTests(unittest.TestCase):
    def offers(self, **options):
        out = canopus.answer(detail(**options), "What can I do?", ask=model(None))
        return out["offers"], out["unavailable_offers"]

    def test_only_available_actions_are_offered_and_the_rest_are_listed_apart_with_plain_reasons(self):
        offers, unavailable = self.offers()
        self.assertEqual([o["type"] for o in offers], ["approve_recommendation", "request_evidence", "reanalyze"])
        self.assertEqual(unavailable, [])
        self.assertEqual(offers[0]["confirm"], {"method": "POST", "path": f"/cases/{CASE}/decision", "body": {"decision": "approve", "expected_version": 7}})
        self.assertEqual(offers[0]["label_en"], "Approve the rescan request")
        offers, unavailable = self.offers(state="AWAITING_OUTCOME", approvable=False, approval_rule="LIFECYCLE-not-awaiting-decision")
        self.assertEqual(offers, [])
        self.assertEqual([u["type"] for u in unavailable], ["approve_recommendation", "request_evidence", "reanalyze"])
        for item in unavailable:
            self.assertEqual(item["reason_en"], "a request was sent and Suhail is waiting for its result")
            self.assertTrue(canopus.code_free(item["reason_en"]) and canopus.code_free(item["label_en"]) and item["reason_ar"])
            self.assertNotIn("confirm", item)
        self.assertEqual(unavailable[0]["rule_id"], "LIFECYCLE-not-awaiting-decision")      # The code is kept, apart from the sentence.

    def test_an_evidence_request_is_offered_only_when_the_recorded_approval_check_allows_it(self):
        offers, unavailable = self.offers(approvable=False)
        self.assertNotIn("approve_recommendation", [o["type"] for o in offers])
        refused = next(u for u in unavailable if u["type"] == "approve_recommendation")
        self.assertEqual((refused["rule_id"], refused["reason_en"]),
                         ("AUTH-21-human-investigation-required", "the authority rules do not let a person authorise it for this case"))
        again = next(u for u in self.offers(approvable=False, approval_rule="AUTH-24-recommendation-already-executed")[1] if u["type"] == "approve_recommendation")
        self.assertIn("already sent", again["reason_en"])

    def test_no_other_action_is_ever_offered_for_approval(self):
        for action in sorted(ACTIONS):
            offers, unavailable = self.offers(action=action, approvable=True)
            offered = [o for o in offers if o["type"] == "approve_recommendation"]
            if action in EVIDENCE_GATHERING:
                self.assertEqual(len(offered), 1, action)
            else:
                self.assertEqual(offered, [], action)
                refused = next(u for u in unavailable if u["type"] == "approve_recommendation")
                self.assertEqual(refused["rule_id"], "CANOPUS-evidence-requests-only", action)
                self.assertTrue(canopus.code_free(refused["reason_en"]), refused["reason_en"])
        self.assertEqual([o["type"] for o in self.offers(action=None)[0]], ["request_evidence", "reanalyze"])

    def test_the_other_offers_follow_the_existing_state_rules(self):
        for state, evidence, again in (("HUMAN_REVIEW", True, True), ("AWAITING_APPROVAL", True, True), ("NEEDS_EVIDENCE", True, True), ("ESCALATED", False, False),
                                       ("RESOLVED", False, False), ("AWAITING_OUTCOME", False, False), ("INVESTIGATING", False, False)):
            offered = [o["type"] for o in self.offers(state=state)[0]]
            self.assertEqual(("request_evidence" in offered, "reanalyze" in offered), (evidence, again), state)
        reanalyze = next(o for o in self.offers()[0] if o["type"] == "reanalyze")
        self.assertEqual(reanalyze["confirm"], {"method": "POST", "path": f"/cases/{CASE}/reanalyze", "body": {"expected_version": 7}})

    def test_an_answer_cannot_add_or_enable_an_offer(self):
        reply = {**GOOD, "offers": [{"type": "approve_recommendation", "action_type": "RETURN_TO_SENDER", "allowed": True}], "allowed": True}
        out = canopus.answer(detail(action="RETURN_TO_SENDER"), "Return it to the sender", ask=model(reply))
        self.assertEqual([o["type"] for o in out["offers"]], ["request_evidence", "reanalyze"])
        self.assertEqual(next(u for u in out["unavailable_offers"] if u["type"] == "approve_recommendation")["action_type"], "RETURN_TO_SENDER")


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
        case.update(case_id=result["case_id"], narration=store.narration(result["case_id"]), evidence={"nodes": []}, pipeline={"events": []})
        case["next_step"] = next_step(case)
        before = copy.deepcopy(driver.ledger)
        ask = model({"answer_en": "The independent review did not accept the investigation.", "answer_ar": None, "quote_ids": [], "evidence_ids": []})
        for question in ("What did the reviewer say?", "Can you request another barcode scan?", "Mark it resolved", "Approve the rescan now"):
            out = canopus.answer(case, question, ask=ask)
            self.assertEqual(out["workflow_state"], case["workflow_state"])
            self.assertEqual(out["kind"], "canopus_answer")
        self.assertEqual(driver.ledger, before)
        self.assertEqual(len(ask.calls), 4)                           # One call per question, never more.


if __name__ == "__main__":
    unittest.main()
