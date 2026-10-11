"""SUHAIL_FORCED_CONCLUSION and the turn_budget_exhausted kind.

Scripted model, no provider. An investigation whose model keeps calling tools until its turn budget is gone ends
degraded with kind "turn_budget_exhausted" (not "invalid_model_output"), whatever the option says. With the option on
it first gets one final turn that says only "no more tool calls; conclude now or conclude INSUFFICIENT_EVIDENCE"; a
valid conclusion from that turn is validated, reviewed and authorised like any other and is marked forced_final_turn.
With the option off nothing else changes: same model inputs, same record, no extra call, no event.
"""
import json
import os
import unittest
from unittest import mock

from operations import investigator
from operations.diagnosis import case_diagnosis
from operations.graph import investigate as run_graph
from operations.investigator import CAUSE_CHOICES, FORCED_MESSAGE
from tests.test_invalid_output_repair import ACCEPT, Case, NO_HYPOTHESES, NOT_RETRIEVED, asker, cite_scan, same
from tests.test_investigator import heartbeats_from, scripted

KIND = "turn_budget_exhausted"
ERROR = "turn budget exhausted without a valid conclusion"
FORCED = "forced_final_turn"
TURNS = 3   # a short turn budget for these tests: two tool turns, then the last turn


def abstain(messages):
    return {"action": "conclude", "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low",
            "missing_evidence": ["A second scan of the parcel label."], "next_evidence_step": "Ask the hub for a rescan.",
            "recommended_action": "REQUEST_RESCAN", "requires_physical_check": False,
            "summary": "The retrieved records do not establish a cause.",
            "hypotheses": [{"cause": "BARCODE_MISMATCH", "status": "uncertain", "supporting_evidence_ids": [],
                            "contradicting_evidence_ids": [], "assessment": "One reading is not enough to tell."}]}


class Short(Case):
    def setUp(self):
        super().setUp()
        patch = mock.patch.dict(os.environ)
        patch.start(); self.addCleanup(patch.stop)
        os.environ.pop(investigator.FORCED_ENV, None)
        patch = mock.patch.object(investigator, "MAX_TURNS", TURNS)
        patch.start(); self.addCleanup(patch.stop)


class FailureKindTests(unittest.TestCase):
    def test_the_turn_budget_has_its_own_kind(self):
        self.assertEqual(investigator.failure_mode(ERROR), KIND)
        self.assertEqual(investigator.TURN_BUDGET_ERROR, ERROR)
        self.assertEqual(investigator.failure_mode("hypotheses must be a non-empty list"), "invalid_model_output")
        self.assertEqual(investigator.failure_mode("model call failed (TimeoutError)"), "model_unavailable")
        self.assertEqual(investigator.failure_mode("model-call cap reached before a valid conclusion"), "model_call_cap")


class ForcedMessageTests(unittest.TestCase):
    def test_the_message_names_no_cause_and_no_evidence(self):
        for code in CAUSE_CHOICES:
            if code not in ("INSUFFICIENT_EVIDENCE",):
                self.assertNotIn(code, FORCED_MESSAGE)
        for hint in ("SHP-", "SCAN", "likely", "probably", "consider", "barcode", "weight", "device", "hub"):
            self.assertNotIn(hint.lower(), FORCED_MESSAGE.lower())
        self.assertIn("INSUFFICIENT_EVIDENCE", FORCED_MESSAGE)
        self.assertIn("No more tool calls are possible", FORCED_MESSAGE)
        self.assertIn("Either is a valid answer", FORCED_MESSAGE)     # abstention is first class, not a fallback
        self.assertNotIn("{", FORCED_MESSAGE)                         # a fixed sentence: nothing about the case is formatted in


class InvestigatorTests(Short):
    def run_loop(self, *replies, cap=None, **options):
        belt = self.belt()
        call = self.call(belt)
        inner = scripted(call, call, call, *replies)      # three tool-call replies: the third is on the last turn and is refused
        def turn(messages):
            turn.sent.append(json.dumps(messages, sort_keys=True))
            return inner(messages)
        turn.seen, turn.sent = inner.seen, []
        announced = []
        out = investigator.investigate(belt, turn=turn, session=investigator.Session(cap), on_forced=announced.append,
                                       on_repair=lambda e: None, **options)
        return out, turn, announced

    def test_off_ends_degraded_with_the_new_kind_and_no_extra_turn(self):
        out, turn, announced = self.run_loop()
        self.assertEqual((out["degraded"], out["mode"], out["validation_error"]), (True, KIND, ERROR))
        self.assertEqual((len(turn.seen), announced), (TURNS, []))
        self.assertNotIn(FORCED, out)
        self.assertIsNone(out["primary_cause"])

    def test_off_is_the_same_whether_unset_zero_or_explicit(self):
        runs = []
        for setting in (None, "0", "explicit"):
            if setting == "0":
                os.environ[investigator.FORCED_ENV] = setting
            out, turn, announced = self.run_loop(**({"forced": False} if setting == "explicit" else {}))
            self.assertEqual(announced, [])
            runs.append(same([out, turn.sent]))
        self.assertEqual(len(set(runs)), 1)

    def test_on_changes_nothing_for_an_investigation_that_concludes_in_time(self):
        def run(**options):
            belt = self.belt()
            turn = scripted(self.call(belt), cite_scan)
            announced = []
            out = investigator.investigate(belt, turn=turn, session=investigator.Session(), on_forced=announced.append, **options)
            return same([out, turn.seen]), announced
        os.environ[investigator.FORCED_ENV] = "1"
        on = run()
        self.assertEqual(on, run(forced=False))
        self.assertEqual(on[1], [])

    def test_on_gives_one_final_turn_and_the_conclusion_is_marked(self):
        os.environ[investigator.FORCED_ENV] = "1"                    # read from the environment
        out, turn, announced = self.run_loop(cite_scan)
        self.assertEqual((out["degraded"], out["mode"], out["primary_cause"]), (False, "gpt-oss", "BARCODE_MISMATCH"))
        self.assertIs(out[FORCED], True)
        self.assertEqual(len(turn.seen), TURNS + 1)
        self.assertEqual(out["model_calls"]["model_calls_used"], TURNS + 1)     # the forced turn counts against the cap
        # The forced turn is the conversation so far plus the fixed message and nothing else (no earlier rejection repeated).
        final = json.loads(turn.sent[-1])
        self.assertEqual(final[-1], {"role": "user", "content": FORCED_MESSAGE})
        self.assertEqual(final[:-1], json.loads(turn.sent[-2])[:-1])
        self.assertEqual(len(announced), 1)
        self.assertEqual({k: announced[0][k] for k in ("kind", "role", "message")},
                         {"kind": FORCED, "role": "investigator", "message": investigator.FORCED_EVENT_MESSAGE})
        self.assertEqual(announced[0]["model_calls"]["model_calls_used"], TURNS)

    def test_insufficient_evidence_is_a_valid_forced_conclusion(self):
        out, turn, _ = self.run_loop(abstain, forced=True)
        self.assertEqual((out["degraded"], out["primary_cause"], out[FORCED]), (False, "INSUFFICIENT_EVIDENCE", True))
        self.assertEqual(out["missing_evidence"], ["A second scan of the parcel label."])

    def test_the_forced_conclusion_passes_the_normal_validator_and_gets_its_normal_retry(self):
        out, turn, _ = self.run_loop(NOT_RETRIEVED, cite_scan, forced=True)
        self.assertEqual((out["degraded"], out[FORCED], len(turn.seen)), (False, True, TURNS + 2))
        retry = turn.seen[-1][-1]["content"]
        self.assertTrue(retry.startswith("Your previous reply was rejected: cited evidence ids were not returned by your tools"))
        self.assertTrue(retry.endswith(FORCED_MESSAGE))

    def test_a_forced_turn_that_is_also_invalid_degrades_as_the_turn_budget(self):
        out, turn, announced = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, forced=True)
        self.assertEqual((out["degraded"], out["mode"], out["validation_error"]), (True, KIND, ERROR))
        self.assertIs(out[FORCED], True)                              # the turn was given; the record says so
        self.assertEqual((len(turn.seen), len(announced)), (TURNS + 2, 1))
        self.assertIsNone(out["primary_cause"]); self.assertEqual(out["hypotheses"], [])
        self.assertEqual([e["error"] for e in out["validation_errors"]][-2:], [
            "cited evidence ids were not returned by your tools: DEMO-SHP-000001-SCAN-01", "hypotheses must be a non-empty list"])

    def test_a_model_that_still_calls_tools_on_the_forced_turn_degrades(self):
        belt = self.belt()
        out, turn, announced = self.run_loop(self.call(belt), self.call(belt), forced=True)
        self.assertEqual((out["degraded"], out["mode"], out[FORCED], len(turn.seen)), (True, KIND, True, TURNS + 2))
        self.assertEqual(len(out["steps"]), 2)                        # no tool ran after the budget was exhausted
        self.assertEqual(len(announced), 1)                           # one forced turn per round, never a second

    def test_the_repair_option_applies_to_the_forced_turn(self):
        out, turn, _ = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, cite_scan, forced=True, repair=True)
        self.assertEqual((out["degraded"], out[FORCED], out["invalid_output_repairs"], len(turn.seen)), (False, True, 1, TURNS + 3))
        out, turn, _ = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, NO_HYPOTHESES, forced=True, repair=True)
        self.assertEqual((out["degraded"], out["mode"], out[FORCED], len(turn.seen)), (True, KIND, True, TURNS + 3))

    def test_no_forced_turn_when_the_call_cap_has_no_room(self):
        # Cap 4: three turns used, one call left and it is reserved for the review.
        out, turn, announced = self.run_loop(cite_scan, cap=TURNS + 1, forced=True)
        self.assertEqual((out["degraded"], out["mode"], out["validation_error"]), (True, KIND, ERROR))
        self.assertNotIn(FORCED, out)
        self.assertEqual((len(turn.seen), announced), (TURNS, []))
        self.assertEqual(out["model_calls"]["model_calls_used"], TURNS)

    def test_a_provider_failure_on_the_forced_turn_is_a_provider_failure(self):
        def boom(messages):
            raise TimeoutError("slow")
        out, turn, _ = self.run_loop(boom, boom, forced=True)
        self.assertEqual((out["degraded"], out["mode"], out[FORCED]), (True, "model_unavailable", True))


class LivePathTests(Short):
    """The graph as the store runs it: agents is the operations.investigator module, the option comes from the environment."""

    def run_case(self, turns, asks, forced):
        if forced is not None:
            os.environ[investigator.FORCED_ENV] = forced
        belt = self.belt()
        call = self.call(belt)
        turn, ask = scripted(call, call, call, *turns), asker(*asks)
        events = []
        with mock.patch.object(investigator, "model_turn", turn), mock.patch.object(investigator, "_review_call", ask):
            result, _ = run_graph(self.sid, self.context["as_of"], self.world.config, lambda *_: self.context, lambda *_: [],
                                  on_event=lambda e, _: events.append(e), agents=investigator, live_session=True,
                                  symptoms=("BARCODE_READ_DIFFERS",), heartbeats=heartbeats_from(self.world))
        return result, events, turn, ask

    def forced(self, events):
        return [e for e in events if e["output"].get("kind") == FORCED]

    def test_off_reports_the_new_kind_everywhere_and_routes_as_before(self):
        result, events, turn, ask = self.run_case([], [], None)
        self.assertEqual(result["degraded"], [{"role": "investigator", "error": ERROR, "kind": KIND}])
        self.assertEqual(result["investigation"]["mode"], KIND)
        self.assertEqual(result["investigation_log"]["rounds"][0]["investigator"]["mode"], KIND)
        closing = next(e for e in events if e["stage"] == "classify" and e["status"] not in ("RUNNING", "RETRYING"))
        self.assertEqual(closing["output"]["agent"], KIND)
        # AUTH-02 routing is unchanged: a failed model role goes to a person and nothing runs automatically.
        self.assertEqual((result["authority"]["risk_class"], result["authority"]["rule_id"]), ("HUMAN_REVIEW", "AUTH-02-model-degraded"))
        self.assertEqual(result["authority"]["inputs"]["degraded"], ["investigator"])
        self.assertEqual(result["result"]["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual((result["review"]["verdict"], result["review"]["reason_code"]), ("no_proposal", "INVESTIGATOR_UNAVAILABLE"))
        self.assertIsNone(result["proposal"])
        # No trace of the option in the record.
        self.assertEqual(self.forced(events), [])
        self.assertNotIn(FORCED, json.dumps(result, default=str))
        self.assertEqual((len(turn.seen), len(ask.seen)), (TURNS, 0))

    def test_on_the_forced_conclusion_is_reviewed_authorised_and_marked(self):
        result, events, turn, ask = self.run_case([cite_scan], [ACCEPT], "1")
        self.assertEqual(result["degraded"], [])
        self.assertEqual(result["investigation"]["primary_cause"], "BARCODE_MISMATCH")
        self.assertIs(result["investigation"][FORCED], True)
        log = result["investigation_log"]
        self.assertIs(log[FORCED], True)
        self.assertIs(log["rounds"][0]["investigator"][FORCED], True)
        self.assertEqual(log["model_calls_by_role"], {"investigator": TURNS + 1, "reviewer": 1})
        # The normal reviewer and the normal authority decided: an accepted review, and not the degraded rule.
        self.assertEqual(len(ask.seen), 1)
        self.assertEqual((result["review"]["verdict"], result["review"]["model_verdict"]), ("accept", "ACCEPT"))
        self.assertNotEqual(result["authority"]["rule_id"], "AUTH-02-model-degraded")
        self.assertEqual(result["authority"]["inputs"]["degraded"], [])
        shown = self.forced(events)
        self.assertEqual([(e["stage"], e["status"], e["output"]["kind"], e["output"]["message"]) for e in shown],
                         [("classify", "RUNNING", FORCED, investigator.FORCED_EVENT_MESSAGE)])
        self.assertEqual(self.forced(result["pipeline_events"]), shown)      # persisted with the run
        order = [(e["stage"], e["status"]) for e in events if e["stage"] == "classify" and e["output"].get("kind") != "tool_call"]
        self.assertEqual(order, [("classify", "RUNNING"), ("classify", "RUNNING"), ("classify", "COMPLETED")])

    def test_on_and_still_invalid_goes_to_a_person_exactly_as_off(self):
        off, _, _, _ = self.run_case([], [], None)
        on, events, turn, ask = self.run_case([NOT_RETRIEVED, NO_HYPOTHESES], [], "1")
        self.assertEqual(on["degraded"], off["degraded"])
        self.assertEqual(on["degraded"], [{"role": "investigator", "error": ERROR, "kind": KIND}])
        self.assertEqual(on["authority"], off["authority"]); self.assertEqual(on["review"], off["review"])
        self.assertIsNone(on["proposal"]); self.assertEqual(on["result"]["diagnoses"], [])
        self.assertIs(on["investigation"][FORCED], True); self.assertIs(on["investigation_log"][FORCED], True)
        self.assertEqual((len(self.forced(events)), len(ask.seen)), (1, 0))


class DiagnosisTests(unittest.TestCase):
    """case detail's diagnosis says when the investigation used the forced final turn; otherwise the field is absent."""

    def run_record(self, *, forced, degraded=False, accepted=True):
        investigation = {"degraded": degraded, "mode": KIND if degraded else "gpt-oss", "primary_cause": None if degraded else "BARCODE_MISMATCH",
                         "confidence": "medium", "summary": "s", "hypotheses": [], "missing_evidence": [], "requires_physical_check": False,
                         "steps": [], **({FORCED: True} if forced else {})}
        review = ({"verdict": "accept", "model_verdict": "ACCEPT", "reason_code": "MODEL_ACCEPT"} if accepted else
                  {"verdict": "reject", "model_verdict": "REVISE", "reason_code": "MODEL_REVISE"})
        result = {"mode": "gpt_oss_agents", "investigation": investigation, "review": review, "trace": [], "degraded": [],
                  "result": {"as_of": "2026-09-15T13:30:00+00:00"},
                  "investigation_log": {"rounds": [], **({FORCED: True} if forced else {})}}
        return {"entity_id": "RUN-1", "status": "REVIEWED", "recorded_at": "2026-09-15T13:31:00+00:00", "result": result}

    def diagnosis(self, **options):
        return case_diagnosis({"workflow_state": "AWAITING_APPROVAL", "last_run_id": "RUN-1"}, self.run_record(**options))

    def test_an_accepted_forced_conclusion_is_marked(self):
        d = self.diagnosis(forced=True)
        self.assertEqual((d["available"], d["primary_cause"], d[FORCED]), (True, "BARCODE_MISMATCH", True))

    def test_an_unaccepted_or_failed_forced_turn_is_marked_too(self):
        d = self.diagnosis(forced=True, accepted=False)
        self.assertEqual((d["available"], d["reason"], d[FORCED], d["unaccepted_investigation"][FORCED]),
                         (False, "review_not_accepted", True, True))
        d = self.diagnosis(forced=True, degraded=True)
        self.assertEqual((d["available"], d["reason"], d[FORCED]), (False, "investigation_unavailable", True))

    def test_the_field_is_absent_otherwise(self):
        for options in ({}, {"accepted": False}, {"degraded": True}):
            d = self.diagnosis(forced=False, **options)
            self.assertNotIn(FORCED, d)
            self.assertNotIn(FORCED, d.get("unaccepted_investigation") or {})


if __name__ == "__main__":
    unittest.main()
