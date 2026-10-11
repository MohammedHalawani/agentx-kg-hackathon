"""SUHAIL_INVALID_OUTPUT_REPAIR: one extra attempt after a model role's reply is still invalid after its retry.

Scripted model, no provider. With the option on, a third well-formed reply is accepted and a RETRYING pipeline event
(output.kind "invalid_output_repair") says so; a third invalid reply fails closed exactly as without the option and the
case goes to a person. With the option off nothing changes: same model inputs, same result, no extra call, no event.
"""
import json
import os
import unittest
from unittest import mock

from operations import investigator
from operations.graph import investigate as run_graph
from operations.reasoning import public_evidence
from tests.test_investigator import Base, heartbeats_from, scripted

KIND = "invalid_output_repair"


def conclusion(ids, summary="A readable scan differs from the manifest barcode."):
    return {"action": "conclude", "primary_cause": "BARCODE_MISMATCH", "confidence": "medium", "missing_evidence": [],
            "recommended_action": "REQUEST_RESCAN", "requires_physical_check": False, "summary": summary,
            "hypotheses": [{"cause": "BARCODE_MISMATCH", "status": "supported", "supporting_evidence_ids": ids,
                            "contradicting_evidence_ids": [], "assessment": "The scan reading differs from the manifest."},
                           {"cause": "WEIGHT_MISMATCH", "status": "refuted", "supporting_evidence_ids": [],
                            "contradicting_evidence_ids": [], "assessment": "Weights are within tolerance."}]}


def cite_scan(messages):
    result = next(m["content"] for m in reversed(messages) if m["content"].startswith("TOOL RESULT"))
    return conclusion([json.loads(result.split(": ", 1)[1].split(" CITABLE_EVIDENCE_IDS")[0])["scans"][0]["scan_id"]])


NOT_RETRIEVED = conclusion(["DEMO-SHP-000001-SCAN-01"])       # cites an id no tool returned: invalid
NO_HYPOTHESES = {"action": "conclude", "primary_cause": "BARCODE_MISMATCH"}
ACCEPT = {"verdict": "ACCEPT", "feedback": "Supported by the cited scan.", "unsupported_claims": [],
          "unaddressed_contradictions": [], "alternatives_tested": "yes"}
GARBAGE = {"verdict": "LOOKS_FINE", "feedback": 7}


def stable(value):
    """A record without its wall-clock fields (measurement only; they differ between any two runs)."""
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items()
                if k not in ("recorded_at", "elapsed_seconds", "latency", "seconds", "model_seconds", "tool_seconds", "query_seconds")}
    return [stable(v) for v in value] if isinstance(value, list) else value


def same(value):
    return json.dumps(stable(value), sort_keys=True, default=str)


def asker(*replies):
    queue, seen = list(replies), []
    def ask(system, user, default):
        seen.append((system, user))
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    ask.seen = seen
    return ask


class Case(Base):
    def setUp(self):
        self.sid = self.shipment("different_barcode")
        self.context = public_evidence(self.world, self.sid, self.world.config.as_of)
        for name in (investigator.REPAIR_ENV, investigator.BATCH_ENV, investigator.PREFETCH_ENV, investigator.MODEL_CALL_CAP_ENV):
            patch = mock.patch.dict(os.environ)
            patch.start(); self.addCleanup(patch.stop)
            os.environ.pop(name, None)

    def belt(self):
        return self.tools(self.sid, self.world.config.as_of, symptoms=("BARCODE_READ_DIFFERS",))

    def call(self, belt):
        package = next(n.id for n in belt.world.nodes.values() if n.kind == "Package")
        return {"action": "call", "tool": "scans", "args": {"package_id": package}, "purpose": "Compare barcode reads."}


class InvestigatorRepairTests(Case):
    def run_loop(self, *replies, cap=None, **options):
        belt = self.belt()
        inner = scripted(self.call(belt), *replies)
        def turn(messages):
            turn.sent.append(json.dumps(messages, sort_keys=True))     # as sent: the conversation list is extended later
            return inner(messages)
        turn.seen, turn.sent = inner.seen, []
        repairs = []
        out = investigator.investigate(belt, turn=turn, session=investigator.Session(cap), on_repair=repairs.append, **options)
        return out, turn, repairs

    def test_repaired_on_the_third_reply(self):
        out, turn, repairs = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, cite_scan, repair=True)
        self.assertFalse(out["degraded"]); self.assertEqual(out["mode"], "gpt-oss")
        self.assertEqual(out["primary_cause"], "BARCODE_MISMATCH")
        self.assertEqual(out["invalid_output_repairs"], 1)
        self.assertEqual(out["model_calls"]["model_calls_used"], 4)          # every attempt counts against the cap
        self.assertEqual([e["error"] for e in out["validation_errors"]], [
            "cited evidence ids were not returned by your tools: DEMO-SHP-000001-SCAN-01", "hypotheses must be a non-empty list"])
        self.assertEqual(len(repairs), 1)
        self.assertEqual({k: repairs[0][k] for k in ("kind", "role", "attempt", "message", "validation_error")},
                         {"kind": KIND, "role": "investigator", "attempt": 1, "message": "model reply invalid, retrying",
                          "validation_error": "hypotheses must be a non-empty list"})
        note = turn.seen[3][-1]["content"]                                  # the repair request names the error and the shape
        self.assertIn("Validation error: hypotheses must be a non-empty list", note)
        self.assertIn('{"action":"conclude","hypotheses"', note)

    def test_still_invalid_fails_closed_with_the_same_reason_as_without_the_option(self):
        off, _, none = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES)
        on, turn, repairs = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, {"action": "conclude", "hypotheses": "none"}, repair=True)
        self.assertEqual((none, len(repairs), len(turn.seen)), ([], 1, 4))
        self.assertTrue(on["degraded"]); self.assertEqual(on["mode"], "invalid_model_output")
        self.assertIsNone(on["primary_cause"]); self.assertEqual(on["hypotheses"], [])
        self.assertIsNone(on["recommended_action"]); self.assertTrue(on["requires_physical_check"])
        self.assertEqual(on["summary"], off["summary"])
        self.assertEqual((off["mode"], off["validation_error"]), ("invalid_model_output", "hypotheses must be a non-empty list"))
        # The reason is the validation error of the reply that was rejected last, as it is without the option.
        self.assertEqual(on["validation_error"], "hypotheses must be a non-empty list")

    def test_the_repair_stays_within_the_call_cap(self):
        # Cap 4 keeps one call for the review: after call, invalid, invalid there is no room, so no repair is attempted.
        off, turn_off, _ = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, cap=4)
        on, turn_on, repairs = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, cite_scan, cap=4, repair=True)
        self.assertEqual((repairs, len(turn_on.seen)), ([], 3))
        self.assertEqual(same(on), same(off))
        self.assertEqual(on["model_calls"]["calls_refused_by_cap"], 0)
        self.assertEqual(on["mode"], "invalid_model_output")

    def test_option_off_is_unchanged(self):
        # Unset, "0" and an explicit repair=False: the same model inputs, the same result, three calls, no repair.
        runs = []
        for setting in (None, "0", "explicit"):
            if setting in ("0",):
                os.environ[investigator.REPAIR_ENV] = setting
            out, turn, repairs = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, cite_scan,
                                               **({"repair": False} if setting == "explicit" else {}))
            self.assertEqual((repairs, len(turn.seen)), ([], 3))
            self.assertNotIn("invalid_output_repairs", out)
            runs.append((same(out), tuple(turn.sent)))
        self.assertEqual(len(set(runs)), 1)
        out = json.loads(runs[0][0])
        self.assertEqual(sorted(out), sorted([
            "mode", "degraded", "steps", "round_steps", "retrieved_evidence_ids", "validation_error", "validation_errors", "model_calls",
            "hypotheses", "primary_cause", "confidence", "missing_evidence", "next_evidence_step", "recommended_action",
            "requires_physical_check", "summary"]))
        self.assertEqual((out["mode"], out["degraded"], out["validation_error"]),
                         ("invalid_model_output", True, "hypotheses must be a non-empty list"))
        # And with the option on, the model sees exactly the same inputs up to the repair request.
        on, turn, _ = self.run_loop(NOT_RETRIEVED, NO_HYPOTHESES, cite_scan, repair=True)
        self.assertEqual(tuple(turn.sent[:3]), runs[0][1])

    def test_a_valid_run_is_the_same_with_the_option_on(self):
        off, turn_off, _ = self.run_loop(NOT_RETRIEVED, cite_scan)
        on, turn_on, repairs = self.run_loop(NOT_RETRIEVED, cite_scan, repair=True)
        self.assertEqual(repairs, [])
        self.assertEqual(same(on), same(off))
        self.assertEqual(turn_on.sent, turn_off.sent)


class ReviewerRepairTests(Case):
    def review(self, ask, session=None, **options):
        repairs = []
        out = investigator.review({"hypotheses": []}, {}, [], [], ask=ask, session=session, on_repair=repairs.append, **options)
        return out, repairs

    def test_repaired_on_the_third_reply(self):
        ask = asker(GARBAGE, ["ACCEPT"], ACCEPT)
        session = investigator.Session(12)
        out, repairs = self.review(ask, session, repair=True)
        self.assertEqual((out["verdict"], out["degraded"], out["mode"]), ("ACCEPT", False, "gpt-oss"))
        self.assertEqual(out["invalid_output_repairs"], 1)
        self.assertEqual(session.budget.by_role, {"reviewer": 3})
        self.assertEqual([(e["kind"], e["role"], e["validation_error"]) for e in repairs],
                         [(KIND, "reviewer", "output must be one JSON object")])
        self.assertIn("Validation error: output must be one JSON object", ask.seen[2][1])
        self.assertIn('"verdict":"ACCEPT|REVISE|INSUFFICIENT_EVIDENCE|HUMAN_REVIEW|ESCALATE"', ask.seen[2][1])

    def test_still_invalid_or_failing_is_unavailable_with_the_same_reason(self):
        off, _ = self.review(asker(GARBAGE, GARBAGE))
        for third in (GARBAGE, None, TimeoutError("slow")):
            on, repairs = self.review(asker(GARBAGE, GARBAGE, third), repair=True)
            self.assertEqual(len(repairs), 1)
            self.assertEqual((on["verdict"], on["degraded"], on["mode"]), ("UNAVAILABLE", True, "invalid_model_output"))
            self.assertEqual({k: v for k, v in on.items() if k != "invalid_output_repairs"}, off)

    def test_a_provider_failure_or_a_spent_cap_is_not_repaired(self):
        ask = asker(ConnectionError("down"), TimeoutError("slow"), ACCEPT)
        out, repairs = self.review(ask, repair=True)
        self.assertEqual((out["verdict"], out["mode"], repairs, len(ask.seen)), ("UNAVAILABLE", "model_unavailable", [], 2))
        session = investigator.Session(2)
        ask = asker(GARBAGE, GARBAGE, ACCEPT)
        out, repairs = self.review(ask, session, repair=True)
        self.assertEqual((out["verdict"], out["mode"], repairs, len(ask.seen)), ("UNAVAILABLE", "invalid_model_output", [], 2))
        self.assertEqual(session.budget.refused, 0)

    def test_option_off_is_unchanged(self):
        runs = []
        for setting in (None, "0", "explicit"):
            if setting == "0":
                os.environ[investigator.REPAIR_ENV] = setting
            ask = asker(GARBAGE, GARBAGE, ACCEPT)
            out, repairs = self.review(ask, **({"repair": False} if setting == "explicit" else {}))
            self.assertEqual((repairs, len(ask.seen)), ([], 2))
            runs.append(json.dumps([out, ask.seen], sort_keys=True))
        self.assertEqual(len(set(runs)), 1)
        self.assertEqual(json.loads(runs[0])[0], {
            "verdict": "UNAVAILABLE", "feedback": "Independent model review could not be completed.", "unsupported_claims": [],
            "unaddressed_contradictions": [], "alternatives_tested": "", "mode": "invalid_model_output", "degraded": True,
            "validation_error": "verdict must be ACCEPT|REVISE|INSUFFICIENT_EVIDENCE|HUMAN_REVIEW|ESCALATE"})


class LivePathTests(Case):
    """The graph as the store runs it: agents is the operations.investigator module, the option comes from the environment."""

    def run_case(self, turns, asks, repair):
        if repair is not None:
            os.environ[investigator.REPAIR_ENV] = repair
        belt = self.belt()
        turn, ask = scripted(self.call(belt), *turns), asker(*asks)
        events = []
        with mock.patch.object(investigator, "model_turn", turn), mock.patch.object(investigator, "_review_call", ask):
            result, _ = run_graph(self.sid, self.context["as_of"], self.world.config, lambda *_: self.context, lambda *_: [],
                                  on_event=lambda e, _: events.append(e), agents=investigator, live_session=True,
                                  symptoms=("BARCODE_READ_DIFFERS",), heartbeats=heartbeats_from(self.world))
        return result, events, turn, ask

    def repairs(self, events):
        return [e for e in events if e["output"].get("kind") == KIND]

    def test_both_roles_are_repaired_and_each_repair_is_a_pipeline_event(self):
        result, events, turn, ask = self.run_case([NOT_RETRIEVED, NO_HYPOTHESES, cite_scan], [GARBAGE, GARBAGE, ACCEPT], "1")
        self.assertEqual(result["degraded"], [])
        self.assertEqual(result["review"]["verdict"], "accept")
        self.assertEqual(result["investigation"]["primary_cause"], "BARCODE_MISMATCH")
        shown = self.repairs(events)
        self.assertEqual([(e["stage"], e["status"], e["output"]["role"], e["output"]["message"]) for e in shown],
                         [("classify", "RETRYING", "investigator", "model reply invalid, retrying"),
                          ("review", "RETRYING", "reviewer", "model reply invalid, retrying")])
        self.assertEqual(shown[0]["output"]["validation_error"], "hypotheses must be a non-empty list")
        # Persisted with the run (pipeline_events) in sequence, between the stage's start and its closing event.
        self.assertEqual(self.repairs(result["pipeline_events"]), shown)
        order = [(e["stage"], e["status"]) for e in events if e["stage"] == "classify" and e["output"].get("kind") != "tool_call"]
        self.assertEqual(order, [("classify", "RUNNING"), ("classify", "RETRYING"), ("classify", "COMPLETED")])
        self.assertEqual(result["investigation_log"]["model_calls_by_role"], {"investigator": 4, "reviewer": 3})
        self.assertGreater(result["latency"]["stages"]["classify"], 0)        # the stage's time still spans the repair

    def test_a_failed_repair_goes_to_a_person_with_no_conclusion(self):
        bad = {"action": "conclude", "hypotheses": "none"}
        off, off_events, _, _ = self.run_case([NOT_RETRIEVED, NO_HYPOTHESES], [], None)
        on, events, turn, _ = self.run_case([NOT_RETRIEVED, NO_HYPOTHESES, bad], [], "1")
        self.assertEqual(len(self.repairs(events)), 1); self.assertEqual(self.repairs(off_events), [])
        for result in (off, on):
            self.assertEqual(result["degraded"], [{"role": "investigator", "error": "hypotheses must be a non-empty list",
                                                   "kind": "invalid_model_output"}])
            self.assertIsNone(result["proposal"]); self.assertIsNone(result["investigation"]["primary_cause"])
            self.assertEqual(result["result"]["diagnoses"], [])
            self.assertEqual(result["result"]["workflow_state"], "HUMAN_REVIEW")
            self.assertEqual((result["authority"]["risk_class"], result["authority"]["rule_id"]), ("HUMAN_REVIEW", "AUTH-02-model-degraded"))
            self.assertEqual((result["review"]["verdict"], result["review"]["reason_code"]), ("no_proposal", "INVESTIGATOR_UNAVAILABLE"))
        self.assertEqual(on["authority"], off["authority"]); self.assertEqual(on["review"], off["review"])

    def test_a_failed_reviewer_repair_is_an_unavailable_review_for_a_person(self):
        off, _, _, _ = self.run_case([cite_scan], [GARBAGE, GARBAGE], None)
        on, events, _, _ = self.run_case([cite_scan], [GARBAGE, GARBAGE, GARBAGE], "1")
        self.assertEqual([(e["stage"], e["status"]) for e in self.repairs(events)], [("review", "RETRYING")])
        for result in (off, on):
            self.assertEqual(result["review"]["verdict"], "review_unavailable")
            self.assertEqual(result["degraded"], [{"role": "reviewer", "kind": "invalid_model_output",
                                                   "error": "verdict must be ACCEPT|REVISE|INSUFFICIENT_EVIDENCE|HUMAN_REVIEW|ESCALATE"}])
            self.assertEqual((result["authority"]["risk_class"], result["result"]["workflow_state"]), ("HUMAN_REVIEW", "HUMAN_REVIEW"))
        self.assertEqual(on["authority"], off["authority"])

    def test_option_off_records_what_it_recorded_before(self):
        # Unset and "0" give the same run: the same model inputs, events (timing fields aside) and record; no repair anywhere.
        runs = []
        for setting in (None, "0"):
            result, events, turn, ask = self.run_case([NOT_RETRIEVED, NO_HYPOTHESES, cite_scan], [ACCEPT], setting)
            self.assertEqual((len(turn.seen), len(ask.seen), self.repairs(events)), (3, 0, []))
            self.assertNotIn(KIND, json.dumps(result, default=str)); self.assertNotIn("invalid_output_repairs", json.dumps(result, default=str))
            runs.append(json.dumps([stable(result), stable(events), turn.seen], sort_keys=True, default=str))
        self.assertEqual(runs[0], runs[1])


if __name__ == "__main__":
    unittest.main()
