"""B1: review and action text is built from what actually happened, never from a scripted story.

The Arabic action text comes from the action catalogue; the Arabic review text is chosen from the
reason code of the check or reviewer decision that produced the verdict, so the vehicle-GPS sentence
appears only when the GPS check fired, and an investigator outage is never shown as a rejection.
"""
import json
import unittest

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations import investigator
from operations.authority import ACTIONS, ACTION_SUMMARY_AR
from operations.worker import REVIEW_SUMMARY_AR, review as guard, review_reason, with_review_reason
from tests import test_operations_store as _store
from tests import test_investigator as ti

GPS_AR = "موقع المركبة"


def no_gps_text(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    return GPS_AR not in text and "Vehicle GPS cannot establish" not in text


class CatalogueTextTests(unittest.TestCase):
    def test_every_catalogue_action_has_an_arabic_summary(self):
        self.assertEqual(set(ACTION_SUMMARY_AR), set(ACTIONS))
        self.assertTrue(all(text.strip() for text in ACTION_SUMMARY_AR.values()))

    def test_only_the_gps_reason_mentions_vehicle_position(self):
        for reason, text in REVIEW_SUMMARY_AR.items():
            self.assertEqual(GPS_AR in text, reason == "GPS_DELIVERY_CLAIM", reason)

    def test_guard_reports_the_check_that_fired(self):
        visible, kinds = {"GPS-1", "SCAN-1"}, {"GPS-1": "GPSObservation", "SCAN-1": "ScanEvent"}
        gps = guard({"action": "Vehicle GPS confirms the parcel was delivered.", "evidence_ids": ["SCAN-1"], "requires_approval": True}, visible, kinds)
        unbound = guard({"action": "Rescan the package.", "evidence_ids": ["ELSEWHERE"], "requires_approval": True}, visible, kinds)
        certifies = guard({"action": "Close.", "action_code": "CONFIRM_DELIVERY", "evidence_ids": ["SCAN-1"], "requires_approval": True}, visible, kinds)
        ok = guard({"action": "Rescan the package.", "evidence_ids": ["SCAN-1"], "requires_approval": True}, visible, kinds)
        self.assertEqual([r["reason_code"] for r in (gps, unbound, certifies, ok)],
                         ["GPS_DELIVERY_CLAIM", "EVIDENCE_NOT_BOUND", "CERTIFIES_OUTCOME", "EVIDENCE_BOUND"])

    def test_legacy_records_are_classified_from_their_own_feedback(self):
        old_gps_ar = "رفضت مراجعة السلامة المقترح. يجب استخدام أدلة الشحنة وطلب اعتماد المشغّل؛ موقع المركبة لا يثبت تسليم الطرد."
        revise = {"verdict": "reject", "model_verdict": "REVISE", "feedback": "Re-check the scan device.", "summary_ar": old_gps_ar}
        outage = {"verdict": "reject", "feedback": "No grounded investigation action at this snapshot.", "summary_ar": old_gps_ar}
        gps = {"verdict": "reject", "feedback": "Vehicle GPS cannot establish parcel delivery. Revise.", "summary_ar": old_gps_ar}
        self.assertEqual([review_reason(r) for r in (revise, outage, gps)], ["MODEL_REVISE", "NO_PROPOSAL", "GPS_DELIVERY_CLAIM"])
        self.assertTrue(no_gps_text(with_review_reason(revise)))
        self.assertTrue(no_gps_text(with_review_reason(outage)))
        self.assertIn(GPS_AR, with_review_reason(gps)["summary_ar"])


class _Store(unittest.TestCase):
    setUpClass = classmethod(lambda cls: setattr(cls, "world", generate(Config(total=90))))
    make = _store.StoreTests.make

    def ledger(self, driver, kind):
        return [v for k, v in driver.ledger.values() if k == kind]


class StoredReviewTextTests(_Store):
    def run_with(self, fake):
        store, driver = self.make()
        store.agents = fake
        result = store.process_one(manual=True)
        self.assertTrue(result["processed"])
        return store, driver, result

    def test_agent_proposal_carries_the_catalogue_arabic_action(self):
        fake = ti.FakeInvestigator(lambda tools: [("shipment_overview", {})], ["REVISE", "HUMAN_REVIEW"])
        fake.cause, fake.action = "BARCODE_MISMATCH", "REQUEST_RESCAN"
        store, driver, result = self.run_with(fake)
        [recommendation] = self.ledger(driver, "OpsRecommendation")
        self.assertEqual(recommendation["action_ar"], ACTION_SUMMARY_AR["REQUEST_RESCAN"])
        detail = store.case_detail(result["case_id"])
        for item in detail["run"]["result"]["trace"]:
            self.assertEqual(item["proposal"]["action_ar"], ACTION_SUMMARY_AR["REQUEST_RESCAN"])

    def test_agent_hypotheses_carry_no_rule_sentence_as_their_arabic_summary(self):
        fake = ti.FakeInvestigator(lambda tools: [("shipment_overview", {})], ["HUMAN_REVIEW"])
        fake.cause, fake.action = "CUSTODY_GAP", "REQUEST_DEVICE_SYNC"
        store, driver, result = self.run_with(fake)
        diagnoses = store.case_detail(result["case_id"])["run"]["result"]["result"]["diagnoses"]
        self.assertTrue(diagnoses)
        self.assertEqual({d["summary_ar"] for d in diagnoses}, {None})  # Not a rule definition passed off as the model's words.
        self.assertEqual(diagnoses[0]["summary_en"], "Consistent with the records.")

    def test_a_model_revision_is_not_told_as_a_gps_story(self):
        fake = ti.FakeInvestigator(lambda tools: [("shipment_overview", {})], ["REVISE", "REVISE"])
        fake.cause, fake.action = "BARCODE_MISMATCH", "REQUEST_RESCAN"
        store, driver, result = self.run_with(fake)
        reviews = self.ledger(driver, "OpsReview")
        self.assertTrue(reviews)
        self.assertEqual({r["reason_code"] for r in reviews}, {"MODEL_REVISE"})
        self.assertEqual({r["summary_ar"] for r in reviews}, {REVIEW_SUMMARY_AR["MODEL_REVISE"]})
        self.assertEqual({r["summary_en"] for r in reviews}, {"Re-check the scan device."})  # The reviewer's own words.
        self.assertTrue(no_gps_text(store.case_detail(result["case_id"])))

    def test_an_investigator_outage_is_not_served_as_a_rejection(self):
        class Outage(ti.FakeInvestigator):
            def investigate(self, tools, on_step=None, feedback=None):
                def boom(messages): raise TimeoutError("slow")
                return investigator.investigate(tools, turn=boom, on_step=on_step)
        store, driver, result = self.run_with(Outage(lambda tools: [], []))
        [review] = self.ledger(driver, "OpsReview")
        self.assertEqual((review["verdict"], review["reason_code"]), ("no_proposal", "INVESTIGATOR_UNAVAILABLE"))
        self.assertEqual(review["summary_ar"], REVIEW_SUMMARY_AR["INVESTIGATOR_UNAVAILABLE"])
        detail = store.case_detail(result["case_id"])
        self.assertEqual(detail["workflow_state"], "HUMAN_REVIEW")
        self.assertTrue(no_gps_text(detail))
        stage = [e for e in detail["run"]["result"]["pipeline_events"] if e["stage"] == "review" and e["status"] != "RUNNING"][-1]
        self.assertEqual((stage["status"], stage["output"]["verdict"]), ("DEGRADED", "no_proposal"))

    def test_rules_only_runs_store_no_scripted_review_text(self):
        store, driver = self.make()
        result = store.process_one(manual=True)
        reviews = self.ledger(driver, "OpsReview")
        self.assertTrue(reviews)
        for review in reviews:
            self.assertEqual(review["summary_ar"], REVIEW_SUMMARY_AR[review["reason_code"]])
            self.assertEqual(GPS_AR in review["summary_ar"], review["reason_code"] == "GPS_DELIVERY_CLAIM")
        self.assertTrue(no_gps_text(store.case_detail(result["case_id"])))

    def test_stored_legacy_text_is_replaced_when_served(self):
        fake = ti.FakeInvestigator(lambda tools: [("shipment_overview", {})], ["REVISE", "REVISE"])
        fake.cause, fake.action = "BARCODE_MISMATCH", "REQUEST_RESCAN"
        store, driver, result = self.run_with(fake)
        def legacy(tx):  # A record written before reason codes existed, with the old fixed sentence.
            for kind, review in tx.ledger.values():
                if kind == "OpsReview":
                    review.pop("reason_code", None)
                    review["summary_ar"] = "رفضت مراجعة السلامة المقترح. موقع المركبة لا يثبت تسليم الطرد."
        driver.execute_write(legacy)
        detail = store.case_detail(result["case_id"])
        self.assertEqual(detail["review"]["summary_ar"], REVIEW_SUMMARY_AR["MODEL_REVISE"])
        self.assertTrue(no_gps_text(detail))


if __name__ == "__main__":
    unittest.main()
