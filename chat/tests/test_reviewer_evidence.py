"""Offline regressions against visible saved evidence, never expected diagnoses."""
import copy
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import unittest

from dataset_v2.contracts import instant
from operations import investigator
from operations.checks import citation_validity, review_context
from operations.graph import analysis
from operations.identifiers import public_value, storage_value

SAVED = json.loads((Path(__file__).parent / "fixtures/v31_saved_evidence.json").read_text(encoding="utf-8"))["cases"]


def tools_for(case):
    case = storage_value(case)
    nodes = {n["id"]: SimpleNamespace(id=n["id"], kind=n["kind"], properties=n["properties"]) for n in case["nodes"]}
    computed = case["computed_results"]
    return SimpleNamespace(nodes=nodes, external={k: {"kind": "ComputedResult", **v} for k, v in computed.items()},
                           computed=computed, index=case["evidence_index"], retrieved=set(case["evidence_index"]), calls=[],
                           sid=case["shipment_id"], as_of=case["as_of"], cutoff=instant(case["as_of"]))


def verdict(**extra):
    return {"verdict": "ACCEPT", "feedback": "Checked the source records.", "unsupported_claims": [],
            "unaddressed_contradictions": [], "alternatives_tested": "yes", **extra}


class ReviewerEvidenceTests(unittest.TestCase):
    def context(self, tools, **kwargs):
        return review_context({}, tools, citation_validity({}, tools), **kwargs)

    def test_saved_barcode_packet_contains_actual_matching_and_differing_observations(self):
        tools = tools_for(SAVED[0])
        packet = self.context(tools)
        records = packet["retrieved_uncited_records"]
        sid = tools.sid
        manifest = records[sid + "-PKG-01"]["manifest_barcode"]
        self.assertEqual(records[sid + "-SCAN-001"]["observed_barcode"], manifest)
        self.assertNotEqual(records[sid + "-SCAN-005"]["observed_barcode"], manifest)
        self.assertIn("recorded_at", records[sid + "-SCAN-005"])
        self.assertEqual(records[sid + "-SCAN-005"]["recorded_at"], tools.nodes[sid + "-SCAN-005"].properties["recorded_at"])
        self.assertTrue(packet["computed_results_seen"])
        # A scripted reviewer reads the same contents; no preferred diagnosis is supplied.
        def ask(system, user, default):
            supplied = json.loads(user)["facts"]["retrieved_uncited_records"]
            self.assertEqual(supplied, records)
            return verdict(verdict="HUMAN_REVIEW", feedback="Compare the distinct source observations before acting.")
        result = investigator.review({}, {}, {}, [], ask=ask, context=packet, repair=False)
        self.assertEqual(result["verdict"], "HUMAN_REVIEW")

    def test_saved_custody_packet_exposes_real_endpoints_and_acknowledgments(self):
        tools = tools_for(SAVED[1])
        packet = self.context(tools)
        records = packet["retrieved_uncited_records"]
        first, third = [records[tools.sid + suffix] for suffix in ("-CUST-001", "-CUST-003")]
        self.assertEqual(first["from_id"], "DEMO-ORG-KHB-M1")
        self.assertEqual(first["to_id"], "DEMO-ORGWH-KHB-01")
        self.assertEqual(third["from_id"], "DEMO-VEH-FM-KHB-005")
        self.assertEqual(third["to_id"], "DEMO-SORT-DMM-01")
        for source, record in (("-CUST-001", first), ("-CUST-003", third)):
            self.assertEqual(record["event_type"], "RECEIVED")
            self.assertEqual(record["recorded_at"], tools.nodes[tools.sid + source].properties["recorded_at"])
            self.assertTrue(any("ack" in field for field in record))
        self.assertNotEqual(first["to_id"], third["from_id"])

    def test_contents_are_bounded_prioritize_previous_refs_and_preserve_provenance(self):
        tools = tools_for(SAVED[0])
        key = tools.sid + "-SCAN-009"
        tools.nodes[key].properties.update(source_ref="source/scan-009", raw_payload_hash="source-hash")
        packet = self.context(tools, previous_reviews=[{"unaddressed_contradictions": [key]}], record_limit=1, record_chars=2000)
        self.assertEqual(list(packet["retrieved_uncited_records"]), [key])
        self.assertEqual(packet["retrieved_uncited_records"][key]["source_ref"], "source/scan-009")
        self.assertEqual(packet["retrieved_uncited_records"][key]["raw_payload_hash"], "source-hash")
        self.assertLessEqual(len(json.dumps(packet["retrieved_uncited_records"])), 2000)
        self.assertGreater(packet["uncited_record_coverage"]["not_shown"], 0)
        too_small = self.context(tools, record_chars=2)
        self.assertEqual(too_small["retrieved_uncited_records"], {})

    def test_future_unretrieved_and_unresolved_sources_are_not_disclosed(self):
        tools = tools_for(SAVED[1])
        future = tools.sid + "-CUST-003"
        tools.nodes[future].properties["recorded_at"] = "2099-01-01T00:00:00Z"
        unretrieved = tools.sid + "-SCAN-001"
        tools.retrieved.remove(unretrieved)
        tools.retrieved.add("DEMO-MISSING")
        packet = self.context(tools)
        for key in (future, unretrieved, "DEMO-MISSING"):
            self.assertNotIn(key, packet["retrieved_uncited_records"])
        self.assertEqual(packet["uncited_record_coverage"]["excluded_invalid_or_unresolved"], 2)

    def test_unknown_inventory_only_and_invalid_contradiction_ids_fail_closed(self):
        for key, context in (("DEMO-INVENTED", {}),
                             ("DEMO-ONLY-ID", {"retrieved_but_uncited": {"ScanEvent": {"ids": ["DEMO-ONLY-ID"]}}}),
                             ("DEMO-CITED", {"citation_validity": {"invalid_ids": ["DEMO-CITED"]}})):
            with self.subTest(key=key):
                result = investigator.review({}, {"DEMO-CITED": {"kind": "ScanEvent"}}, {}, [],
                                             ask=lambda *args: verdict(verdict="REVISE", unaddressed_contradictions=[key]),
                                             context=context, repair=False)
                self.assertEqual(result["verdict"], "UNAVAILABLE")
                self.assertIn("contradiction ids", result["validation_error"])

    def test_readable_contradictions_remain_valid_independent_rejections(self):
        tools = tools_for(SAVED[1])
        packet = self.context(tools)
        key = tools.sid + "-CUST-001"
        result = investigator.review({}, {}, {}, [], ask=lambda *args: verdict(verdict="REVISE", unaddressed_contradictions=[key]),
                                     context=packet, repair=False)
        self.assertEqual(result["verdict"], "REVISE")
        self.assertEqual(result["unaddressed_contradictions"], [key])

    def test_accept_cannot_claim_unresolved_objections_or_untested_alternatives(self):
        for extra in ({"unsupported_claims": ["Unsupported assertion"]},
                      {"unaddressed_contradictions": ["DEMO-CITED"]}, {"alternatives_tested": "no"}):
            with self.subTest(extra=extra):
                result = investigator.review({"primary_cause": "BARCODE_MISMATCH"}, {"DEMO-CITED": {"kind": "ScanEvent"}}, {}, [],
                                             ask=lambda *args: verdict(**extra), repair=False)
                self.assertEqual(result["verdict"], "UNAVAILABLE")
        result = investigator.review({}, {}, {}, [], ask=lambda *args: verdict(),
                                     context={"citation_validity": {"all_valid": False}}, repair=False)
        self.assertEqual(result["verdict"], "UNAVAILABLE")

    def test_invalid_review_retry_consumes_shared_budget_and_can_be_corrected(self):
        session = investigator.Session(cap=2)
        replies = iter([verdict(unsupported_claims=["Needs correction"]), verdict(verdict="HUMAN_REVIEW")])
        result = investigator.review({}, {}, {}, [], ask=lambda *args: next(replies), session=session, repair=False)
        self.assertEqual(result["verdict"], "HUMAN_REVIEW")
        self.assertEqual(session.budget.by_role, {"reviewer": 2})
        self.assertEqual(session.budget.used, 2)


class SavedAccountingTests(unittest.TestCase):
    def test_final_counters_match_saved_actual_turns_without_mutating_round_snapshots(self):
        for case in SAVED:
            with self.subTest(case=case["shipment_id"]):
                before = copy.deepcopy(case)
                state = {"result": {}, "review": {}, "trace": [], "context": {},
                         "investigation": {"model_calls": case["conclusion_counters"]}, "log": case["final_counters"]}
                result = analysis(state, [])
                self.assertEqual(result["investigation"]["model_calls"], case["final_counters"])
                self.assertEqual(result["investigation"]["model_calls"]["model_calls_used"], len(case["actual_call_roles"]))
                self.assertEqual(result["investigation"]["model_calls"]["model_calls_by_role"], dict(Counter(case["actual_call_roles"])))
                self.assertEqual(case, before)
                self.assertNotEqual(case["conclusion_counters"]["model_calls_used"], case["final_counters"]["model_calls_used"])

    def test_saved_evidence_maps_resolve_after_public_boundary_conversion(self):
        for case in SAVED:
            fixed = public_value(case)
            for node in fixed["nodes"]:
                if node["id"] in fixed["evidence_index"]:
                    self.assertEqual(fixed["evidence_index"][node["id"]]["kind"], node["kind"])
            self.assertTrue(all(key.startswith("SYN-") for key in fixed["evidence_index"]))
            for key in fixed["computed_results"]:
                self.assertIn(key, fixed["evidence_index"])


if __name__ == "__main__":
    unittest.main()
