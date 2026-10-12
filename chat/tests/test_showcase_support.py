"""What a verified resolution is called, and the image attached to a photo record: both read only the case's records.

The status line of a resolved case names what the verifier confirmed from the evidence the outcome itself cites
(custody at a facility, or a delivery whose proof carries the recipient's passed authentication). A photo is never
what makes a delivery "verified". An image file is served only for a photo record that has one, by its public id.
"""
import tempfile
import unittest
from pathlib import Path

from operations import brief, media

DEPOT = {"id": "DEMO-DEPOT-KHB-01", "kind": "DeliveryDepot", "properties": {"display_name": "Synthetic depot KHB-01"}}
DEVICE = {"id": "DEMO-DEV-HH-DEPOT-KHB-01", "kind": "Device", "properties": {"facility_id": "DEMO-DEPOT-KHB-01"}}
RECONCILE = {"id": "C1", "kind": "CustodyEvent", "properties": {"event_type": "RECEIVED", "to_id": "DEMO-DEPOT-KHB-01", "facility_id": "DEMO-DEPOT-KHB-01"}}
DELIVERED = {"id": "C2", "kind": "CustodyEvent", "properties": {"event_type": "DELIVERED", "proof_id": "P1"}}
PROOF = {"id": "P1", "kind": "DeliveryProof", "properties": {"authentication_id": "A1", "photo_id": "DEMO-SHP-000001-PHOTO-001"}}
PASSED = {"id": "A1", "kind": "AuthenticationEvidence", "properties": {"result": "PASS"}}
PHOTO = {"id": "DEMO-SHP-000001-PHOTO-001", "kind": "PhotoEvidence", "properties": {"media_ref": "synthetic://x/photo-1", "no_image_generated": True}}


def index(*nodes):
    return {n["id"]: n for n in nodes}


class ResolutionTests(unittest.TestCase):
    def test_reconciled_custody_names_the_facility_that_recorded_the_parcel(self):
        r = brief.resolution({"outcome_type": "custody_reconciled", "evidence_ids": ["C1"]}, index(DEPOT, RECONCILE))
        self.assertEqual((r["kind"], r["facility_id"]), ("custody_confirmed", "DEMO-DEPOT-KHB-01"))
        self.assertTrue(r["text_en"].startswith("Resolved: warehouse custody confirmed."))
        self.assertIn("Synthetic depot KHB-01 (DEMO-DEPOT-KHB-01) recorded the parcel in its custody after the request", r["text_en"])
        self.assertTrue(r["text_ar"] and r["short_ar"])
        self.assertNotIn("deliver", r["text_en"].lower())                       # Custody is confirmed; nothing is said about delivery.

    def test_a_located_parcel_names_the_facility_that_scanned_it_and_claims_no_custody_or_delivery(self):
        scan = {"id": "S1", "kind": "ScanEvent", "properties": {"facility_id": "DEMO-DEPOT-KHB-01", "observation_type": "FACILITY_CHECK_SCAN"}}
        r = brief.resolution({"outcome_type": "parcel_located", "evidence_ids": ["S1"]}, index(DEPOT, scan))
        self.assertEqual((r["kind"], r["facility_id"]), ("parcel_located", "DEMO-DEPOT-KHB-01"))
        self.assertIn("Resolved: parcel located at the warehouse. Synthetic depot KHB-01 (DEMO-DEPOT-KHB-01) scanned the parcel after the request", r["text_en"])
        self.assertNotIn("custody confirmed", r["text_en"])
        self.assertNotIn("deliver", r["text_en"].lower())

    def test_a_delivery_is_called_verified_only_with_the_recipients_passed_authentication(self):
        outcome = {"outcome_type": "delayed_upload_received", "evidence_ids": ["C2"]}
        verified = brief.resolution(outcome, index(DELIVERED, PROOF, PASSED, PHOTO))
        self.assertEqual(verified["kind"], "delivery_verified")
        self.assertTrue(verified["text_en"].startswith("Resolved: delivery status verified."))
        self.assertIn("confirmed by the recipient's code", verified["text_en"])
        failed = {**PASSED, "properties": {"result": "FAIL"}}
        for nodes in (index(DELIVERED, PROOF, PHOTO), index(DELIVERED, PROOF, failed, PHOTO), index(DELIVERED, PHOTO), index(PROOF, PASSED, PHOTO)):
            self.assertEqual(brief.resolution(outcome, nodes)["kind"], "problem_cleared")      # A photo or a proof record alone is not enough.
        self.assertEqual(brief.resolution({"outcome_type": "delayed_upload_received", "evidence_ids": []}, index(DELIVERED, PROOF, PASSED))["kind"],
                         "problem_cleared")                                         # Only evidence the outcome cites counts.

    def test_any_other_verified_outcome_keeps_the_general_sentence(self):
        r = brief.resolution({"outcome_type": "barcode_corrected", "evidence_ids": ["S1"]}, {})
        self.assertEqual((r["kind"], r["text_en"]), ("problem_cleared", "Resolved: the verifier confirmed from later evidence that the problem is cleared."))

    def test_a_request_to_a_facilitys_device_names_the_facility(self):
        execution = {"entity_id": "E1", "action_type": "INITIATE_CUSTODY_RECONCILIATION", "authority": "AUTO_POLICY", "status": "ACKNOWLEDGED",
                     "target_device": "DEMO-DEV-HH-DEPOT-KHB-01", "deadline_at": "2026-09-19T08:00:00+00:00"}
        action = brief.action_explanation(execution, None, index(DEPOT, DEVICE))
        self.assertEqual((action["recipient"]["facility_id"], action["recipient"]["facility_name"]), ("DEMO-DEPOT-KHB-01", "Synthetic depot KHB-01"))
        self.assertIn("sent to Synthetic depot KHB-01 (DEMO-DEPOT-KHB-01), through its device DEMO-DEV-HH-DEPOT-KHB-01 (simulated)", action["text_en"])
        self.assertNotIn("driver", action["text_en"].lower())                    # The recorded recipient is the depot, nobody else.


class HumanFindingTests(unittest.TestCase):
    OUTCOME = {"verification_status": "HUMAN_FINDING", "success": False, "outcome_type": "delivered_confirmed_by_person", "execution_id": None,
               "exception_cleared": False, "remaining_symptoms": ["MANIFEST_CUSTODY_CONFLICT", "SESSION_END_UNRECONCILED"], "reason": "Proof checked."}

    def test_a_recorded_finding_that_leaves_something_standing_is_never_called_resolved(self):
        from tests.test_canopus import detail
        case = detail("ESCALATED", outcome=dict(self.OUTCOME))
        b = brief.build(case)
        status = next(line["text_en"] for line in b["lines"] if line["key"] == "status")
        self.assertFalse(b["resolved"])
        self.assertEqual(b["verification"]["status"], "human_finding_not_resolved")
        self.assertEqual(status, "Delivery confirmed by a person from the recorded proof. Manifest discrepancy remains. Delivery session not reconciled. "
                                 "Human review required.")
        self.assertNotIn("Resolved", status)
        self.assertNotIn("verified", status.lower())                               # A person confirmed it; the verifier did not.
        problem = next(line["text_en"] for line in b["lines"] if line["key"] == "problem")
        self.assertTrue(problem)                                                    # The problems stay stated in full in the assessment.
        unknown = brief.human_finding({**self.OUTCOME, "remaining_symptoms": ["OVERDUE_AT_FACILITY"]})
        self.assertIn("Still stands: The parcel has stayed at a facility longer than planned.", unknown["text_en"])
        self.assertEqual(b["_stage_outcome"]["short_en"], "Finding recorded, not resolved")
        self.assertTrue(next(line["text_ar"] for line in b["lines"] if line["key"] == "status"))

    def test_other_outcomes_are_not_a_persons_finding(self):
        self.assertIsNone(brief.human_finding({"verification_status": "VERIFIED", "outcome_type": "barcode_corrected"}))
        self.assertIsNone(brief.human_finding({"verification_status": "HUMAN_VERIFIED", "outcome_type": "delivered_confirmed_by_person"}))
        self.assertIsNone(brief.human_finding({}))


class DeliveryEvidenceStatusTests(unittest.TestCase):
    ATTEMPT = {"id": "T1", "kind": "DeliveryAttempt", "properties": {"disposition": "DELIVERED"}}
    HANDOVER = {"id": "H1", "kind": "HandoffEvidence", "properties": {}}
    LATE = {"id": "P1", "kind": "DeliveryProof", "properties": {"attempt_id": "T1", "authentication_id": "A1", "handoff_id": "H1",
                                                              "occurred_at": "2026-09-19T05:50:00+00:00", "recorded_at": "2026-09-20T05:31:00+00:00"}}

    def case(self, state, nodes, symptoms=("MANIFEST_CUSTODY_CONFLICT", "SESSION_END_UNRECONCILED")):
        from tests.test_canopus import detail
        case = detail(state)
        case.update(opened_at="2026-09-19T08:45:00+00:00", symptom_codes=list(symptoms))
        case["evidence"] = {"nodes": list(nodes)}
        b = brief.build(case)
        return b, next(line["text_en"] for line in b["lines"] if line["key"] == "status")

    def test_a_case_with_a_person_says_what_arrived_what_it_supports_and_what_still_stands(self):
        b, status = self.case("ESCALATED", [self.LATE, self.ATTEMPT, PASSED, self.HANDOVER, PHOTO])
        self.assertEqual(status, "Delivery evidence and the recipient's code received. The recorded proof supports delivery. Manifest discrepancy remains. "
                                 "Delivery session not reconciled. Human review required.")
        self.assertFalse(b["resolved"])
        for word in ("resolved", "verified", "confirmed", "closed"):
            self.assertNotIn(word, status.lower())
        self.assertTrue(next(line["text_ar"] for line in b["lines"] if line["key"] == "status"))
        self.assertIn("Human review required.", self.case("HUMAN_REVIEW", [self.LATE, self.ATTEMPT, PASSED, self.HANDOVER])[1])

    def test_incomplete_or_earlier_evidence_leaves_the_usual_status(self):
        failed = {**PASSED, "properties": {"result": "FAIL"}}
        attempted = {**self.ATTEMPT, "properties": {"disposition": "FAILED"}}
        early = {**self.LATE, "properties": {**self.LATE["properties"], "recorded_at": "2026-09-19T05:51:00+00:00"}}
        for nodes in ([self.LATE, self.ATTEMPT, failed, self.HANDOVER], [self.LATE, attempted, PASSED, self.HANDOVER], [self.LATE, self.ATTEMPT, PASSED],
                      [early, self.ATTEMPT, PASSED, self.HANDOVER], [PHOTO, PASSED, self.ATTEMPT, self.HANDOVER]):
            self.assertNotIn("supports delivery", self.case("ESCALATED", nodes)[1])
        # Only for a case that is with a person: no other state takes this line.
        for state in ("OPEN", "INVESTIGATING", "AWAITING_OUTCOME", "NEEDS_EVIDENCE"):
            self.assertNotIn("supports delivery", self.case(state, [self.LATE, self.ATTEMPT, PASSED, self.HANDOVER])[1], state)


class CanopusFactsTests(unittest.TestCase):
    def test_delivery_evidence_is_described_from_the_records_and_never_called_verified(self):
        from operations import canopus
        handover = {"id": "H1", "kind": "HandoffEvidence", "properties": {}}
        proof = {"id": "P1", "kind": "DeliveryProof", "after_investigation": True,
                 "properties": {"authentication_id": "A1", "handoff_id": "H1", "occurred_at": "2026-09-19T05:50:00+00:00", "recorded_at": "2026-09-20T05:31:00+00:00"}}
        text = canopus.delivery_evidence({"evidence": {"nodes": [proof, PASSED, handover, PHOTO]}})
        self.assertEqual(text, "On record: a delivery proof made at 2026-09-19 05:50 UTC, the recipient's code passed, a handover record, "
                               "a delivery photo record. These records reached Suhail late, after the case was opened.")
        self.assertNotIn("verified", text)
        self.assertIsNone(canopus.delivery_evidence({"evidence": {"nodes": [PHOTO, PASSED]}}))       # No proof record, nothing to describe.


class MediaTests(unittest.TestCase):
    def test_a_photo_record_gets_an_image_only_when_a_file_is_named_after_its_public_id(self):
        with tempfile.TemporaryDirectory() as folder:
            nodes = [dict(PHOTO), dict(PROOF)]
            self.assertNotIn("media", media.attach(nodes, folder)[0])
            (Path(folder) / "SYN-SHP-000001-PHOTO-001.jpg").write_bytes(b"\xff\xd8\xff")
            (Path(folder) / "P1.jpg").write_bytes(b"\xff\xd8\xff")
            nodes = media.attach([dict(PHOTO), dict(PROOF)], folder)
            self.assertEqual(nodes[0]["media"]["url"], "/media/evidence/SYN-SHP-000001-PHOTO-001")
            self.assertEqual((nodes[0]["media"]["content_type"], nodes[0]["media"]["illustration"]), ("image/jpeg", True))
            self.assertNotIn("media", nodes[1])                                    # Only photo records carry an image.
            self.assertTrue(nodes[0]["properties"]["no_image_generated"])          # The stored record is not changed.
            self.assertEqual(media.media_file("SYN-SHP-000001-PHOTO-001", folder).name, "SYN-SHP-000001-PHOTO-001.jpg")

    def test_nothing_outside_the_media_folder_can_be_asked_for(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "SECRET.jpg").write_bytes(b"x")
            inner = Path(folder) / "media"
            inner.mkdir()
            for name in ("../SECRET", "..\\SECRET", "SECRET.jpg", "secret", "", None, "A/B", "A" * 161):
                self.assertIsNone(media.media_file(name, inner), name)


if __name__ == "__main__":
    unittest.main()
