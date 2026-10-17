"""V3.4.2: what a compacted tool result lets the investigator cite, and the input measurement the pre-check shares with the
dispatcher. Offline: no provider call, no database."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from operations import investigator
from operations.context_budget import COMPACTED, digest, ids_in, request_bytes, text_bytes
from operations.inference_safety import input_bound


def evidence_tools(retrieved=()):
    return SimpleNamespace(
        index={"DEMO-SHP-7-SCAN-001": {"kind": "ScanEvent", "scope": "shipment", "occurred_at": "2026-09-16T10:00:00+00:00",
                                       "recorded_at": "2026-09-16T10:00:30+00:00"},
               "DEMO-SHP-7-CUST-002": {"kind": "CustodyEvent", "scope": "shipment", "occurred_at": "2026-09-16T11:00:00+00:00",
                                       "recorded_at": "2026-09-16T11:00:00+00:00"}},
        computed={"DEMO-CMP-77": {"kind": "ComputedResult", "scope": "computed", "computation": "scan_gap",
                                  "gap_minutes": 95, "input_ids": ["DEMO-SHP-7-SCAN-001", "DEMO-SHP-7-CUST-002"]}},
        retrieved=set(retrieved))


ORIGINAL = ('TOOL RESULT scans: {"scans": [{"scan_id": "DEMO-SHP-7-SCAN-001", "device_id": "DEMO-DEV-HH-SORT-DMM-01", '
            '"facility_id": "DEMO-HUB-DMM-01", "note": "' + "n" * 2500 + '"}, {"custody_id": "DEMO-SHP-7-CUST-002", '
            '"holder": "DEMO-DRV-0042"}]} CITABLE_EVIDENCE_IDS: ["DEMO-SHP-7-SCAN-001", "DEMO-SHP-7-CUST-002", "DEMO-CMP-77"]')
STEP = {"tool": "scans", "args": {"package_id": "DEMO-SHP-7-PKG-01"},
        "evidence_ids": ["DEMO-SHP-7-SCAN-001", "DEMO-SHP-7-CUST-002", "DEMO-CMP-77"], "computed_ids": ["DEMO-CMP-77"]}


def body_of(text):
    return json.loads(text[text.index("): ") + 3:text.rindex(" CITABLE_EVIDENCE_IDS: ")])


class CompactedCitations(unittest.TestCase):
    def test_the_digest_separates_citable_evidence_computed_results_and_mentioned_names(self):
        # The driver DEMO-DRV-0042 was returned as evidence by another tool; the device and the hub never were.
        text = digest(STEP, ORIGINAL, evidence_tools(retrieved=[*STEP["evidence_ids"], "DEMO-DRV-0042"]))
        self.assertIn(COMPACTED, text)
        self.assertLess(len(text), len(ORIGINAL))
        # Exactly the original's citable list, under the same marker the investigator is told to cite from.
        self.assertEqual(json.loads(text.rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[1]), STEP["evidence_ids"])
        body = body_of(text)
        self.assertEqual(body["evidence"], {"ScanEvent/shipment": ["DEMO-SHP-7-SCAN-001@2026-09-16T10:00:00Z+30s"],
                                            "CustodyEvent/shipment": ["DEMO-SHP-7-CUST-002@2026-09-16T11:00:00Z+0s"]})
        self.assertEqual(body["computed"]["DEMO-CMP-77"]["gap_minutes"], 95)
        self.assertEqual(body["mentioned_ids_not_citable"], ["DEMO-DEV-HH-SORT-DMM-01", "DEMO-HUB-DMM-01"])
        self.assertEqual(body["mentioned_ids_citable_from_other_results"], ["DEMO-DRV-0042"])
        self.assertNotIn("also_named", body)
        # Nothing the original named is lost, and the instruction says which ids may be cited.
        self.assertTrue(ids_in(ORIGINAL) <= ids_in(text))
        self.assertIn("Cite only the ids under CITABLE_EVIDENCE_IDS", text)
        self.assertIn("not evidence: never cite them", text)
        self.assertNotIn("every id here stays citable", text)

    def test_mentioned_names_are_not_made_citable(self):
        tools = evidence_tools(retrieved=STEP["evidence_ids"])
        digest(STEP, ORIGINAL, tools)
        self.assertNotIn("DEMO-DEV-HH-SORT-DMM-01", tools.retrieved)
        self.assertNotIn("DEMO-DEV-HH-SORT-DMM-01", tools.index)
        # The validator still refuses a conclusion that cites a mentioned name as evidence.
        conclusion = {"hypotheses": [{"cause": "DELAYED_SYNC", "status": "supported", "assessment": "a",
                                      "supporting_evidence_ids": ["DEMO-DEV-HH-SORT-DMM-01"], "contradicting_evidence_ids": []}],
                      "primary_cause": "DELAYED_SYNC", "confidence": "low", "missing_evidence": ["x"], "next_evidence_step": "y",
                      "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": "s"}
        problem = investigator.validate_conclusion(conclusion, tools.retrieved)
        self.assertTrue(problem and "not returned by your tools" in problem, problem)
        conclusion["hypotheses"][0]["supporting_evidence_ids"] = ["DEMO-SHP-7-SCAN-001"]
        self.assertIsNone(investigator.validate_conclusion(conclusion, tools.retrieved))


SAMPLES = [
    "شحنة DEMO-SHP-000207 لم تصل إلى المستلم؛ آخر مسح في مركز الفرز بالدمام",
    'quoted "scan" and \'single\' quotes, a JSON fragment {"a": "b\\"c"}',
    "back\\slash \\\\ and C:\\Projects\\path, tab\tand newline\nand CR\r",
    "unicode ✓ ⚠ 🚚 emoji, combining é, CJK 配送, zero-width\u200b",
    ORIGINAL,
]


class MeasurementEquality(unittest.TestCase):
    """The investigator's pre-check and the reviewer's pre-check measure exactly what the dispatcher measures."""

    def capture(self):
        from llm.pipeline import _llm
        seen = []

        def invoke(messages, **_):
            seen.append(input_bound(messages))      # what _llm.invoke compares with SUHAIL_MAX_INPUT_BYTES
            raise RuntimeError("stop: no provider call")
        return mock.patch.object(_llm, "invoke", side_effect=invoke), seen

    def test_the_investigator_turn_is_measured_as_the_dispatcher_measures_it(self):
        conversations = [
            [{"role": "system", "content": SAMPLES[0]}, {"role": "user", "content": SAMPLES[1]}],
            [{"role": "system", "content": "s"}] + [{"role": ("assistant" if i % 2 else "user"), "content": text}
                                                    for i, text in enumerate(SAMPLES * 3)],
            [{"role": "system", "content": SAMPLES[2]}, {"role": "user", "content": digest(STEP, ORIGINAL, evidence_tools())}],
        ]
        patch, seen = self.capture()
        with patch:
            for messages in conversations:
                with self.assertRaises(RuntimeError):
                    investigator.model_turn(messages)
        self.assertEqual(seen, [request_bytes(m) for m in conversations])

    def test_the_review_request_is_measured_as_the_dispatcher_measures_it(self):
        pairs = [(investigator.REVIEWER_SYSTEM, json.dumps({"facts": {"note": text}}, ensure_ascii=False)) for text in SAMPLES]
        patch, seen = self.capture()
        with patch:
            for system, user in pairs:
                with self.assertRaises(RuntimeError):
                    investigator._review_call(system, user, {})
        self.assertEqual(seen, [text_bytes(s, u) for s, u in pairs])

    def test_the_bound_is_unchanged(self):
        from operations.inference_safety import input_limit
        with mock.patch.dict(os.environ, {"SUHAIL_MAX_INPUT_BYTES": "65536"}):
            self.assertEqual(input_limit(), 65536)


if __name__ == "__main__":
    unittest.main()
