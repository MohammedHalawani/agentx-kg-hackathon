"""V3.4 monitor detection evidence, alert state and the Operations overview. In memory; no database, no model.

  - A case records why the monitor opened it (rules, evidence ids, the milestone with its deadline, grace and expected
    location, the last corroborated custody event), from the evidence visible at the monitor's clock only.
  - A buffered upload that arrives later is judged on its event time: the monitored custody gap of the offline-device
    shipment no longer stands, the case records its alert as cleared, and nothing is resolved or verified by that.
  - Healthy shipments the monitor checked have no case; the overview counts only what the monitor and the ledger hold.
  - Pure rules of operations.detection.
"""
import json
import unittest

from dataset_v2.contracts import instant
from operations.detection import (ALERT_ACTIVE, ALERT_CLEARED, ALERT_PARTLY_CLEARED, alert_state, detection_summary,
                                  detection_text, merge_detection)
from operations.store import SYMPTOMS


def symptom(code):
    return SYMPTOMS.get(code, "EVIDENCE_MISSING")


class Node:
    def __init__(self, kind, **properties):
        self.kind, self.properties = kind, properties


class World:
    def __init__(self, nodes):
        self.nodes = nodes


class DetectionRules(unittest.TestCase):
    def assessment(self):
        return {"as_of": "2026-09-15T15:15:00+00:00",
                "exceptions": [{"code": "MISSED_MILESTONE", "evidence_ids": ["M1", "CUST-1"], "reasons": ["Expected observation absent"], "requires_human_review": False}],
                "expected_vs_actual": [
                    {"predicate": "RECEIVED", "package_id": "P1", "milestone_id": "M1", "location_id": "HUB", "earliest_at": "2026-09-15T12:00:00+00:00",
                     "latest_at": "2026-09-15T14:00:00+00:00", "actual_at": None, "due": True, "late": False, "missing_due": True},
                    {"predicate": "DELIVERED", "package_id": "P1", "milestone_id": "M2", "location_id": "R", "latest_at": "2026-09-16T17:00:00+00:00",
                     "actual_at": None, "due": False, "late": False, "missing_due": False},
                    {"predicate": "WEIGHT_KG", "package_id": "P1", "evidence_id": "S1", "expected": 2.0, "actual": 2.1, "tolerance_kg": .5, "matches": True}],
                "custody": [{"package_id": "P1", "last_corroborated_holder_id": "VAN", "last_corroborated_event_id": "CUST-1", "gap_event_ids": [],
                             "conflicting": False, "parcel_location_from_gps": None}]}

    def world(self):
        return World({"M1": Node("ExpectedMilestone", grace_seconds=1800), "HUB": Node("Hub", name="Hub one"), "VAN": Node("Vehicle")})

    def test_a_missed_milestone_records_deadline_grace_location_and_last_custody(self):
        d = detection_summary(self.assessment(), self.world(), symptom)
        [rule] = d["rules"]
        self.assertEqual((rule["code"], rule["symptom"]), ("MISSED_MILESTONE", "MILESTONE_OVERDUE"))
        [m] = d["milestones"]     # The not-yet-due delivery milestone is not part of the detection.
        self.assertEqual((m["state"], m["grace_seconds"], m["deadline_at"], m["observed_at"], m["delivery_promise"]),
                         ("missing_after_deadline", 1800, "2026-09-15T14:30:00+00:00", None, False))
        self.assertEqual(m["expected_location"]["kind"], "Hub")
        self.assertEqual(d["comparisons"], [])   # A weight inside tolerance is not a detection.
        self.assertEqual(d["custody"][0]["last_corroborated_event_id"], "CUST-1")
        self.assertIsNone(d["custody"][0]["parcel_location_from_gps"])
        self.assertEqual(d["model_calls"], 0)
        text = detection_text(d)
        self.assertIn("2026-09-15T14:30:00+00:00", text)
        self.assertIn("HUB", text)
        self.assertIn("CUST-1", text)

    def test_the_summary_names_no_cause(self):
        text = json.dumps(detection_summary(self.assessment(), self.world(), symptom))
        for word in ("cause", "root", "diagnos", "recommend", "mechanism", "truth"):
            self.assertNotIn(word, text.lower())

    def test_merging_keeps_every_rule_and_the_first_detection_time(self):
        first = detection_summary(self.assessment(), self.world(), symptom)
        later = {**first, "as_of": "2026-09-16T00:00:00+00:00",
                 "rules": [{"code": "UNRECONCILED_CUSTODY", "symptom": "SESSION_END_UNRECONCILED", "reasons": [], "evidence_ids": [], "requires_human_review": True}]}
        merged = merge_detection(json.dumps(merge_detection(None, first)), later)
        self.assertEqual([r["code"] for r in merged["rules"]], ["MISSED_MILESTONE", "UNRECONCILED_CUSTODY"])
        self.assertEqual((merged["first_as_of"], merged["as_of"]), ("2026-09-15T15:15:00+00:00", "2026-09-16T00:00:00+00:00"))

    def test_alert_state(self):
        self.assertEqual(alert_state(["MILESTONE_OVERDUE"], ["MILESTONE_OVERDUE"]), (ALERT_ACTIVE, []))
        self.assertEqual(alert_state(["MILESTONE_OVERDUE", "MILESTONE_LATE"], ["MILESTONE_LATE"]), (ALERT_PARTLY_CLEARED, ["MILESTONE_OVERDUE"]))
        self.assertEqual(alert_state(["CUSTODY_TRANSFER_UNCONFIRMED"], []), (ALERT_CLEARED, ["CUSTODY_TRANSFER_UNCONFIRMED"]))
        # A past-event symptom stays found, so its alert never clears on silence.
        self.assertEqual(alert_state(["BARCODE_READ_DIFFERS"], ["BARCODE_READ_DIFFERS"])[0], ALERT_ACTIVE)


class LiveMonitor(unittest.TestCase):
    """The real store over the in-memory ledger, the V3 test world replayed hour by hour with the monitor draining."""

    @classmethod
    def setUpClass(cls):
        from tests.test_world_simulation import OUTAGE_SHIPMENT, at
        from tests.world_live import LiveWorld, advance, ledger_store
        cls.sid = OUTAGE_SHIPMENT
        cls.live = LiveWorld(at("15T12:00"))
        cls.store, cls.driver = ledger_store(cls.live, None)
        cls.history = []

        def run_until(text):
            while instant(cls.live.clock) < instant(at(text)):
                advance(cls.store, cls.live, 1)
                while cls.store.status()["session"]["monitor_pending"]:
                    cls.store.monitor_step(limit=10)
                cls.history.append((cls.live.clock, cls.case_of(cls.sid)))
        cls.run_until = staticmethod(run_until)
        run_until("16T00:00")
        cls.before = cls.case_of(cls.sid)
        cls.overview_before = cls.store.monitor_overview()
        run_until("16T06:00")
        cls.after = cls.case_of(cls.sid)

    @classmethod
    def case_of(cls, sid):
        cases = [v for k, v in cls.driver.ledger.values() if k == "OpsCase" and v["shipment_id"] == sid]
        return dict(cases[0]) if cases else None

    def kind(self, name):
        return [v for k, v in self.driver.ledger.values() if k == name]

    def test_the_offline_device_case_records_why_it_was_opened(self):
        self.assertIsNotNone(self.before)
        self.assertIn("CUSTODY_TRANSFER_UNCONFIRMED", self.before["symptom_codes"])
        detail = self.store.case_detail(self.before["entity_id"])
        detection = detail["detection"]
        self.assertEqual(detection["source"], "deterministic_monitor_rules")
        gap = next(r for r in detection["rules"] if r["code"] == "CUSTODY_GAP")
        self.assertTrue(gap["evidence_ids"])
        # Every cited record was visible at the detection clock: nothing from the future.
        for key in gap["evidence_ids"]:
            node = self.live.world.nodes[key]
            if node.properties.get("recorded_at"):
                self.assertLessEqual(instant(node.properties["recorded_at"]), instant(detection["as_of"]))
        opened = next(a for a in self.kind("OpsAudit") if a.get("case_id") == self.before["entity_id"] and a["event_type"] == "CASE_OPENED")
        self.assertIn("Detected on evidence visible at", opened["result"])

    def test_the_late_upload_clears_the_alert_without_resolving_anything(self):
        self.assertEqual(self.before["monitor_alert_state"], ALERT_ACTIVE)
        self.assertEqual(self.after["monitor_alert_state"], ALERT_CLEARED)
        self.assertEqual(self.after["monitor_alert_cleared"], ["CUSTODY_TRANSFER_UNCONFIRMED"])
        self.assertEqual(self.after["workflow_state"], "OPEN")          # Still investigated; no workflow move.
        self.assertFalse(self.after.get("is_terminal"))
        self.assertIsNone(self.after.get("verified_outcome_id"))
        self.assertFalse([o for o in self.kind("OpsOutcome") if o.get("case_id") == self.after["entity_id"]])
        events = [a["event_type"] for a in self.kind("OpsAudit") if a.get("case_id") == self.after["entity_id"]]
        self.assertIn("MONITOR_ALERT_CLEARED", events)
        self.assertNotIn("CASE_RESOLVED", events)
        alert = self.store.case_detail(self.after["entity_id"])["monitor_alert"]
        self.assertEqual((alert["state"], alert["is_resolution"]), (ALERT_CLEARED, False))
        # The upload arrived after the opening and carries an earlier event time: judged on event time once ingested.
        uploads = [n for n in self.live.owned[self.sid] if n.kind == "CustodyEvent" and n.properties.get("recorded_at")
                   and instant(n.properties["recorded_at"]) > instant(self.before["opened_at"] if isinstance(self.before["opened_at"], str) else self.before["opened_at"].isoformat())
                   and instant(n.properties["occurred_at"]) < instant(self.before["opened_at"] if isinstance(self.before["opened_at"], str) else self.before["opened_at"].isoformat())]
        self.assertTrue(uploads)

    def test_checked_shipments_without_findings_have_no_case_and_the_overview_counts_the_ledger(self):
        watches = self.kind("OpsMonitorWatch")
        cases = {v["shipment_id"] for v in self.kind("OpsCase")}
        healthy = [w for w in watches if w["status"] == "NO_ACTIVE_EXCEPTION"]
        self.assertTrue(healthy)
        overview = self.store.monitor_overview()
        self.assertEqual(overview["shipments_monitored"], len(watches))
        self.assertEqual(overview["no_active_exception"], len([w for w in healthy if w["shipment_id"] not in cases]))
        self.assertEqual(overview["cases_total"], len(self.kind("OpsCase")))
        self.assertEqual(overview["verified_resolved"], 0)
        self.assertGreaterEqual(overview["alerts_cleared_by_later_evidence"], 1)
        self.assertLessEqual(overview["shipments_monitored"], overview["shipments_booked"])
        self.assertEqual(self.overview_before["alerts_cleared_by_later_evidence"], 0)   # Before the upload nothing had cleared.
        # A shipment with an active watch finding has a case, unless the case was opened under an earlier symptom set.
        for watch in watches:
            if watch["status"] == "ACTIVE_EXCEPTION":
                self.assertIn(watch["shipment_id"], cases)

    def test_no_case_was_opened_from_anything_but_the_monitor(self):
        for case in self.kind("OpsCase"):
            self.assertEqual(case["opened_by"], "MONITOR")
            self.assertTrue(case.get("detection_json"))


if __name__ == "__main__":
    unittest.main()


class BriefDetection(unittest.TestCase):
    """The case brief restates the monitor's evidence in plain words, without record codes, and never calls a cleared
    alert a resolution."""
    DETECTION = {"version": "monitor-detection-1", "as_of": "2026-09-15T15:15:00+00:00", "rules": [
        {"code": "MISSED_MILESTONE", "symptom": "MILESTONE_OVERDUE", "reasons": ["absent"], "evidence_ids": ["DEMO-SHP-000005-EM-01-02"], "requires_human_review": False}],
        "milestones": [{"package_id": "DEMO-SHP-000005-PKG-01", "milestone_id": "DEMO-SHP-000005-EM-01-02", "predicate": "RECEIVED", "delivery_promise": False,
                        "expected_location": {"id": "DEMO-HUB-RUH-01", "kind": "Hub", "name": None}, "latest_at": "2026-09-15T14:00:00+00:00",
                        "grace_seconds": 1800, "deadline_at": "2026-09-15T14:30:00+00:00", "observed_at": None, "state": "missing_after_deadline"}],
        "comparisons": [], "custody": [{"package_id": "DEMO-SHP-000005-PKG-01", "last_corroborated_event_id": "DEMO-SHP-000005-CUST-004",
                                        "last_corroborated_holder": {"id": "DEMO-VEH-LH-RUH-002", "kind": "Vehicle", "name": None},
                                        "unconfirmed_event_ids": [], "conflicting": False, "parcel_location_from_gps": None}]}

    def test_the_brief_says_which_step_was_due_where_and_when(self):
        from operations import brief
        from operations.canopus import code_free
        en, ar = brief.detection_sentences({"detection": self.DETECTION, "monitor_alert": {"state": "ACTIVE", "cleared_symptoms": []}})
        self.assertIn("arrival at the hub DEMO-HUB-RUH-01 was due by 2026-09-15 14:30 UTC (including 30 min grace)", en)
        self.assertIn("last confirmed custody is with a vehicle", en)
        self.assertNotIn("CUST-004", en)          # A record id is not operator vocabulary.
        self.assertTrue(code_free(en), en)
        self.assertTrue(ar)

    def test_a_cleared_alert_is_said_not_to_be_a_resolution(self):
        from operations import brief
        from operations.canopus import code_free
        en, _ = brief.detection_sentences({"detection": self.DETECTION,
                                           "monitor_alert": {"state": "CLEARED", "cleared_symptoms": ["CUSTODY_TRANSFER_UNCONFIRMED"]}})
        self.assertIn("the alert no longer stands, which is not a resolution", en)
        self.assertTrue(code_free(en), en)
        self.assertEqual(brief.detection_sentences({}), ("", ""))
