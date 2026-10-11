"""Canopus narration: built only from recorded events, labelled by kind, bounded in model calls, never on the
investigation's path, and unable to change anything but its own records.

Pure tests for the builders and the grounding check; store tests on the in-memory ledger with a scripted investigator,
reviewer and narrator model (no database, no provider).
"""
import copy
import unittest
from unittest import mock

from operations import authority as policy
from operations.narration import (AUDIT_EVENTS, KINDS, PHASES, STAGES, Narrator, audit_drafts, graph_ids, grounded, pipeline_drafts, summarize,
                                  wrap_up_draft)
from tests import test_material_reinvestigation as base
from tests.test_operations_store import Acknowledging
from tests.test_reviewer_doubt import FAILURE, SUCCESS, Scripted, clean_fact_checks

SID = "DEMO-SHP-000001"


def event(seq, stage, status, iteration=0, **output):
    return {"sequence": seq, "stage": stage, "status": status, "iteration": iteration, "output": output,
            "recorded_at": f"2026-10-11T13:00:{seq:02d}+00:00", "evidence_as_of": "2026-09-15T12:00:00+00:00"}


def run_events(verdict="ACCEPT"):
    return [
        event(1, "extract", "RUNNING"),
        event(2, "extract", "COMPLETED", shipment_id=SID, symptoms=["BARCODE_READ_DIFFERS"], as_of="2026-09-15T12:00:00+00:00", evidence_ids=[SID]),
        event(3, "retrieve", "COMPLETED", nodes=40, relationships=90, categories={"ScanEvent": 9, "Device": 2}, evidence_ids=[f"{SID}-SCAN-009", "DEMO-DEV-SR-1"]),
        event(4, "classify", "RUNNING"),
        event(5, "classify", "RUNNING", kind="tool_call", tool="scans", args={"package_id": f"{SID}-PKG-01"}, purpose="Check the barcode reads.",
              evidence_ids=[f"{SID}-SCAN-009", "DEMO-CMP-aaaa"]),
        event(6, "classify", "RUNNING", kind="tool_call", tool="device_status", args={"device_id": "DEMO-DEV-SR-1"}, purpose="See whether the sorter misreads.",
              evidence_ids=["DEMO-DEV-SR-1", "DEMO-DEV-SR-1-HB-1"]),
        event(7, "classify", "COMPLETED", tool_calls=2, evidence_ids=[f"{SID}-SCAN-009", "DEMO-CMP-aaaa"],
              investigation={"primary_cause": "BARCODE_MISMATCH", "confidence": "medium", "summary": "One sorter read differs from the manifest.",
                             "hypotheses": [{"cause": "BARCODE_MISMATCH", "status": "supported", "assessment": "A single differing read.",
                                             "supporting_evidence_ids": [f"{SID}-SCAN-009"]}], "recommended_action": "REQUEST_RESCAN"}),
        event(8, "retrieve_context", "COMPLETED", verified_precedents=3, evidence_ids=["DEMO-POLICY-1"]),
        event(9, "recommend", "COMPLETED", proposal={"action_type": "REQUEST_RESCAN", "action_en": "Request a rescan.", "action_ar": "طلب إعادة المسح."},
              evidence_ids=[f"{SID}-SCAN-009"]),
        event(10, "review", "RUNNING"),
        event(11, "review", "COMPLETED" if verdict == "ACCEPT" else "REJECTED", 1, verdict="accept" if verdict == "ACCEPT" else "reject", model_verdict=verdict,
              feedback="Citations are valid." if verdict == "ACCEPT" else "A transient read error was not ruled out.",
              citation_validity={"cited": 1, "valid": 1, "invalid_ids": []}, model_review={"unsupported_claims": []}, evidence_ids=[f"{SID}-SCAN-009"]),
        event(12, "writeback", "COMPLETED", 1, workflow_state="AWAITING_OUTCOME",
              authority={"action_type": "REQUEST_RESCAN", "risk_class": "AUTO", "rule_id": "AUTH-10-auto-allowlist", "reason": "Low-risk request."}),
    ]


class BuilderTests(unittest.TestCase):
    def test_every_draft_has_a_known_stage_phase_and_kind_and_follows_the_source_order(self):
        drafts = pipeline_drafts(run_events())
        for d in drafts:
            self.assertIn(d["stage"], STAGES)
            self.assertIn(d["phase"], PHASES)
            self.assertIn(d["kind"], KINDS)
            self.assertTrue(d["text_en"] and d["title_en"])
        last = [max(d["source"]["pipeline_sequences"]) for d in drafts]
        self.assertEqual(last, sorted(last))
        self.assertEqual(len({d["key"] for d in drafts}), len(drafts))
        self.assertEqual([d["stage"] for d in drafts if d["kind"] == "system_event"],
                         ["extract", "retrieve", "retrieve_context", "recommend", "writeback"])

    def test_the_agents_own_words_are_quoted_and_only_rounds_ask_for_a_summary(self):
        drafts = pipeline_drafts(run_events("REVISE"))
        quoted = [d["text_en"] for d in drafts if d["kind"] == "agent_output"]
        self.assertEqual(quoted, ["Check the barcode reads.", "See whether the sorter misreads.", "One sorter read differs from the manifest.",
                                  "A transient read error was not ruled out."])
        jobs = [d["job"]["task"] for d in drafts if d["job"]]
        self.assertEqual(jobs, ["investigation_round", "review_round"])            # One per round, never one per tool call.
        self.assertTrue(all(d["kind"] == "canopus_summary" for d in drafts if d["job"]))
        review = next(d for d in drafts if d["job"] and d["job"]["task"] == "review_round")
        self.assertEqual((review["job"]["verdict"], review["job"]["accepted"]), ("REVISE", False))
        self.assertIn("not an acceptance", review["text_en"])                      # The record-based text, should the model be unavailable.

    def test_a_summary_job_carries_recorded_events_only(self):
        job = next(d["job"] for d in pipeline_drafts(run_events()) if d["job"])
        self.assertEqual(sorted(job), ["conclusion", "degraded", "round", "task", "tool_calls"])
        self.assertEqual(sorted(job["tool_calls"][0]), ["arguments", "evidence_ids", "purpose", "records_returned", "tool"])
        text = str(job).lower()
        for hidden in ("prompt", "system", "reasoning", "truth", "mechanism", "canary"):
            self.assertNotIn(hidden, text)

    def test_running_and_incomplete_stages_are_not_narrated(self):
        self.assertEqual(pipeline_drafts([event(1, "extract", "RUNNING"), event(4, "classify", "RUNNING"), event(10, "review", "RUNNING")]), [])

    def test_audit_entries_are_narrated_from_their_own_text_and_never_overstate_the_outcome(self):
        audits = [{"entity_id": f"A{i}", "event_type": kind, "result": f"recorded text {i}", "wall_recorded_at": f"2026-10-11T13:10:{i:02d}+00:00",
                   "occurred_at": "2026-09-15T14:00:00+00:00"} for i, kind in enumerate(AUDIT_EVENTS)]
        drafts = audit_drafts(audits + [{"entity_id": "X", "event_type": "CASE_CLAIMED", "result": "ignored"}])
        self.assertEqual(len(drafts), len(AUDIT_EVENTS))
        for d, a in zip(drafts, audits):
            self.assertEqual((d["kind"], d["text_en"], d["source"]["record_ids"]), ("system_event", a["result"], [a["entity_id"]]))
            self.assertTrue(d["text_ar"] and d["title_ar"])
        resolved = {kind for kind, spec in AUDIT_EVENTS.items() if spec[4] == "RESOLVED"}
        self.assertEqual(resolved, {"OUTCOME_VERIFIED", "CASE_RESOLVED", "REASSESSMENT_ACCEPTED"})

    def test_the_wrap_up_exists_only_after_a_verification_and_states_the_recorded_state(self):
        self.assertIsNone(wrap_up_draft([{"entity_id": "A", "event_type": "ACTION_EXECUTED", "result": "sent"}], {}, {}, "AWAITING_OUTCOME"))
        failed = wrap_up_draft([{"entity_id": "A", "event_type": "OUTCOME_FAILED", "result": "not confirmed"}], {"primary_cause": "X"}, {"model_verdict": "ACCEPT"}, "HUMAN_REVIEW")
        self.assertEqual((failed["outcome_state"], failed["job"]["case_state"]), ("HUMAN_REVIEW", "HUMAN_REVIEW"))
        self.assertIn("not resolved", failed["text_en"])

    def test_graph_ids_are_the_shipments_own_and_retrieved_records_only(self):
        ids = [f"{SID}-SCAN-009", "DEMO-CMP-aaaa", "DEMO-DEV-SR-1", "DEMO-DEV-SR-1-HB-1", SID]
        self.assertEqual(graph_ids(ids, SID, ["DEMO-DEV-SR-1"]), [f"{SID}-SCAN-009", "DEMO-DEV-SR-1", SID])


class GroundingTests(unittest.TestCase):
    ALLOWED = {f"{SID}-SCAN-009", "DEMO-DEV-SR-1"}

    def test_a_summary_may_name_only_ids_it_was_given(self):
        self.assertTrue(grounded(f"The investigator read {SID}-SCAN-009 on DEMO-DEV-SR-1.", self.ALLOWED, False))
        self.assertTrue(grounded("The investigator read SYN-SHP-000001-SCAN-009.", self.ALLOWED, False))      # The public spelling of a given id.
        self.assertFalse(grounded("The investigator read DEMO-SHP-000001-SCAN-010.", self.ALLOWED, False))
        self.assertFalse(grounded("", self.ALLOWED, False))
        self.assertFalse(grounded(None, self.ALLOWED, False))

    def test_a_summary_may_not_claim_a_resolution_the_record_does_not_show(self):
        for text in ("The case is resolved.", "This resolves the problem.", "The case was closed."):
            self.assertFalse(grounded(text, self.ALLOWED, False), text)
            self.assertTrue(grounded(text, self.ALLOWED, True), text)
        self.assertTrue(grounded("The case is not resolved and stays with a person.", self.ALLOWED, False))
        self.assertTrue(grounded("The problem is unresolved.", self.ALLOWED, False))

    def test_an_unusable_model_reply_is_dropped(self):
        draft = next(d for d in pipeline_drafts(run_events()) if d["job"])
        good = {"title_en": "Barcode check", "text_en": f"The investigator checked the reads and found {SID}-SCAN-009 differs.", "text_ar": "تحقق المحقق من القراءات."}
        self.assertEqual(summarize(draft, lambda s, u: good)["text_en"], good["text_en"])
        for bad in ({}, None, "text", {"text_en": ""}, {"text_en": "It read DEMO-SHP-000009-SCAN-001."}, {"text_en": "The case is resolved."},
                    {"text_en": "x" * 1300}):
            self.assertIsNone(summarize(draft, lambda s, u, bad=bad: bad), bad)
        # Typographic hyphens in an id are put back before the check: a given id passes, an invented one is still caught.
        typographic = summarize(draft, lambda s, u: {**good, "text_en": f"The investigator read {SID}-SCAN-009.".replace("-", "‑")})
        self.assertEqual(typographic["text_en"], f"The investigator read {SID}-SCAN-009.")
        self.assertIsNone(summarize(draft, lambda s, u: {**good, "text_en": "It read DEMO‑SHP‑000009‑SCAN‑001."}))
        # In an investigation round only the investigator has acted.
        self.assertIsNone(summarize(draft, lambda s, u: {**good, "text_en": "The reviewer concluded a custody gap."}))
        kept = summarize(draft, lambda s, u: {**good, "text_ar": "قرأ DEMO-SHP-000009-SCAN-001", "title_en": "DEMO-OTHER-1 check"})
        self.assertEqual((kept["text_ar"], kept["title_en"]), (None, draft["title_en"]))      # Ungrounded parts fall away; the rest stands.

    def test_the_narrator_is_given_the_recorded_job_and_nothing_else(self):
        seen = []
        draft = next(d for d in pipeline_drafts(run_events()) if d["job"])
        summarize(draft, lambda system, user: seen.append((system, user)) or {})
        system, user = seen[0]
        self.assertIn("RECORDED events", system)
        self.assertIn("never say the case is resolved", system)
        self.assertIn('"task": "investigation_round"', user)


class Model:
    """A scripted narrator model that counts its calls."""
    def __init__(self, reply=None, error=None):
        self.calls, self.reply, self.error = [], reply, error

    def __call__(self, system, user):
        self.calls.append(user)
        if self.error:
            raise self.error
        return self.reply if self.reply is not None else {"title_en": "Summary", "text_en": "The recorded step was summarised for the operator.", "text_ar": "ملخص الخطوة المسجلة."}


class StoreTests(base._Base):
    def investigate(self, verdicts=("ACCEPT",), model=None, limit=None):
        store, driver = self.make()
        store.agents = Scripted(verdicts)
        self.model = model or Model()
        store.narrator = Narrator(store, ask=self.model, limit=limit, threaded=False)
        with clean_fact_checks():
            result = store.process_one(manual=True)
        return store, driver, result

    def narrate(self, store, case_id):
        store.narrator.sync(case_id)
        return store.narration(case_id)

    def verified(self, store, driver, verdict=SUCCESS):
        store.adapter = Acknowledging()
        store.execute_step()
        self.advance(driver, 3600)
        with mock.patch("operations.outcome_engine.evaluate", return_value=verdict), \
                mock.patch("operations.store.monitor_finding", return_value={"open": False, "symptoms": []}), \
                mock.patch("operations.store.remaining_symptoms", return_value=[]):
            return store.outcome_step(limit=5, force=True)

    def test_an_investigation_never_calls_the_narrator_model_and_is_not_changed_by_narration(self):
        store, driver, result = self.investigate()
        self.assertEqual(self.model.calls, [])                       # Requested, not run: narration is off the investigation's path.
        before = copy.deepcopy({k: v for k, v in driver.ledger.items() if v[0] != "OpsNarration"})
        narration = self.narrate(store, result["case_id"])
        self.assertTrue(narration["events"])
        after = {k: v for k, v in driver.ledger.items() if v[0] != "OpsNarration"}
        self.assertEqual(before, after)                              # Narration wrote nothing but its own records.
        self.assertEqual(self.stored(driver, result["case_id"])["state_version"], result["state_version"])

    def test_the_stored_narration_follows_the_contract(self):
        store, driver, result = self.investigate()
        narration = self.narrate(store, result["case_id"])
        self.assertEqual((narration["run_id"], narration["status"]), (result["run_id"], "complete"))
        events = narration["events"]
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
        fields = {"id", "case_id", "shipment_id", "run_id", "sequence", "stage", "phase", "kind", "iteration", "title_en", "title_ar", "text_en", "text_ar",
                  "evidence_ids", "graph_node_ids", "source", "occurred_at", "scenario_time", "created_at", "model", "grounded", "fallback", "outcome_state"}
        for e in events:
            self.assertEqual(set(e), fields)
            self.assertIn(e["stage"], STAGES)
            self.assertIn(e["kind"], KINDS)
            self.assertTrue(set(e["graph_node_ids"]) <= set(e["evidence_ids"]))
            self.assertEqual(bool(e["model"]), e["kind"] == "canopus_summary")
            self.assertEqual(sorted(e["source"]), ["audit_event_types", "pipeline_sequences", "record_ids"])
        self.assertEqual({e["kind"] for e in events}, set(KINDS))
        summaries = [e for e in events if e["kind"] == "canopus_summary"]
        self.assertEqual(len(summaries), len(self.model.calls))
        self.assertEqual(narration["model_calls"], len(self.model.calls))
        self.assertTrue(all(e["grounded"] is True and e["text_ar"] for e in summaries))
        stages = [e["stage"] for e in events]
        self.assertLess(stages.index("extract"), stages.index("classify"))
        self.assertLess(stages.index("classify"), stages.index("review"))
        # The same list is served with the case detail and replays unchanged.
        self.assertEqual(store.narration(result["case_id"]), narration)
        self.assertEqual(self.narrate(store, result["case_id"]), narration)
        self.assertEqual(len(self.model.calls), len(summaries))      # A replay generates nothing.

    def test_model_calls_are_bounded_per_run_and_the_record_based_text_takes_over(self):
        store, driver, result = self.investigate(("REVISE", "REVISE", "REVISE"), limit=2)
        narration = self.narrate(store, result["case_id"])
        self.assertEqual(len(self.model.calls), 2)
        fallbacks = [e for e in narration["events"] if e["fallback"]]
        self.assertTrue(fallbacks)
        self.assertTrue(all(e["kind"] == "system_event" and e["model"] is None for e in fallbacks))
        store, driver, result = self.investigate(limit=0)
        narration = self.narrate(store, result["case_id"])
        self.assertEqual(self.model.calls, [])
        self.assertNotIn("canopus_summary", {e["kind"] for e in narration["events"]})

    def test_a_failing_or_ungrounded_narrator_never_affects_the_case(self):
        for model in (Model(error=TimeoutError("slow")), Model(reply={"text_en": "The case is resolved thanks to DEMO-INVENTED-1."})):
            store, driver, result = self.investigate(model=model)
            narration = self.narrate(store, result["case_id"])
            self.assertTrue(model.calls)
            self.assertNotIn("canopus_summary", {e["kind"] for e in narration["events"]})
            self.assertTrue(any(e["fallback"] for e in narration["events"]))
            self.assertFalse(any("DEMO-INVENTED-1" in e["text_en"] or "SYN-INVENTED-1" in e["text_en"] for e in narration["events"]))
            self.assertEqual(self.stored(driver, result["case_id"])["workflow_state"], result["workflow_state"])

    def test_a_reviewers_doubt_is_narrated_as_not_accepted(self):
        store, driver, result = self.investigate(("REVISE", "REVISE", "REVISE"))
        events = self.narrate(store, result["case_id"])["events"]
        self.assertIn("REVIEWER_DOUBT_RECORDED", [t for e in events for t in e["source"]["audit_event_types"]])
        quoted = [e for e in events if e["kind"] == "agent_output" and e["stage"] == "review"]
        self.assertTrue(quoted and all("REVISE" in e["title_en"] for e in quoted))
        self.assertFalse(any(e["outcome_state"] == "RESOLVED" for e in events))

    def test_execution_and_verification_are_narrated_from_the_records_and_an_unresolved_case_is_never_called_resolved(self):
        store, driver, result = self.investigate()
        self.narrate(store, result["case_id"])
        self.verified(store, driver, verdict=FAILURE)
        events = self.narrate(store, result["case_id"])["events"]
        tail = [t for e in events for t in e["source"]["audit_event_types"]]
        self.assertIn("ACTION_EXECUTED", tail)
        self.assertIn("OUTCOME_FAILED", tail)
        self.assertEqual(self.stored(driver, result["case_id"])["workflow_state"], "HUMAN_REVIEW")
        self.assertFalse(any(e["outcome_state"] == "RESOLVED" for e in events))
        wrap = events[-1]
        self.assertEqual((wrap["phase"], wrap["outcome_state"]), ("verification", "HUMAN_REVIEW"))
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))

    def test_a_verified_resolution_is_narrated_as_resolved_only_after_the_verifier(self):
        store, driver, result = self.investigate()
        before = self.narrate(store, result["case_id"])["events"]
        self.assertFalse(any(e["outcome_state"] == "RESOLVED" for e in before))
        self.verified(store, driver)
        events = self.narrate(store, result["case_id"])["events"]
        self.assertEqual(self.stored(driver, result["case_id"])["workflow_state"], "RESOLVED")
        self.assertEqual(events[:len(before)], before)                # Append-only: earlier events are unchanged.
        self.assertIn("RESOLVED", [e["outcome_state"] for e in events[len(before):]])

    def test_the_store_only_requests_narration_when_a_narrator_is_attached(self):
        store, driver = self.make()
        store.agents = Scripted(("ACCEPT",))
        with clean_fact_checks():
            result = store.process_one(manual=True)                   # No narrator: nothing is requested or stored.
        self.assertEqual(self.kind(driver, "OpsNarration"), [])
        self.assertEqual(store.narration(result["case_id"])["events"], [])
        self.assertEqual(store.narration(result["case_id"])["status"], "idle")


if __name__ == "__main__":
    unittest.main()
