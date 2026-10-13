"""Planning and per-node classification of the provider-overwrite repair. No database."""
import unittest
from types import SimpleNamespace

from scripts.repair_provider_overwrite import classify, other_digest, plan


def node(kind, **props):
    return SimpleNamespace(kind=kind, properties=props)


class RepairPlanTests(unittest.TestCase):
    def test_only_records_naming_a_different_provider_than_their_channel_are_planned(self):
        items = [{"source_event_id": "T1", "provider_id": "DEMO-PROV-SPL", "payload_hash": "h1", "feed_id": "F1"},
                 {"source_event_id": "T1", "provider_id": "DEMO-PROV-SPL", "payload_hash": "h1", "feed_id": "F1-retransmit"},
                 {"source_event_id": "M1", "provider_id": "DEMO-PROV-INDEP-01", "payload_hash": "h2", "feed_id": "F2"},
                 {"source_event_id": "S1", "provider_id": "DEMO-PROV-SPL", "payload_hash": "h3", "feed_id": "F3"}]
        nodes = {"T1": node("Trip", provider_id="DEMO-PROV-3PL-01"),
                 "M1": node("Manifest", provider_id="DEMO-PROV-INDEP-01"),   # same as channel: not affected
                 "S1": node("ScanEvent")}                                    # no own provider: not affected
        fixes = plan(items, nodes)
        self.assertEqual(fixes, [{"id": "T1", "kind": "Trip", "provider": "DEMO-PROV-3PL-01",
                                  "channel_provider": "DEMO-PROV-SPL", "payload_hash": "h1", "feed_id": "F1"}])

    def test_classification_is_guarded_and_idempotent(self):
        fix = {"id": "T1", "provider": "DEMO-PROV-3PL-01", "channel_provider": "DEMO-PROV-SPL", "payload_hash": "h1", "feed_id": "F1"}
        stored = {"raw_payload_hash": "h1", "feed_id": "F1"}
        row = lambda **p: {"found": True, "props": {**stored, **p}, "feed_payload_hash": "h1"}
        self.assertEqual(classify(fix, row(provider_id="DEMO-PROV-SPL")), "needs_repair")
        self.assertEqual(classify(fix, row(provider_id="DEMO-PROV-3PL-01")), "repaired")
        self.assertEqual(classify(fix, row(provider_id="DEMO-PROV-LMC-01")), "anomalous")
        self.assertEqual(classify(fix, row(provider_id="DEMO-PROV-SPL", raw_payload_hash="other")), "anomalous")
        self.assertEqual(classify(fix, {"found": False, "props": None, "feed_payload_hash": None}), "anomalous")
        self.assertEqual(classify(fix, {**row(provider_id="DEMO-PROV-SPL"), "feed_payload_hash": "other"}), "anomalous")

    def test_other_properties_digest_ignores_only_the_provider(self):
        a = {"entity_id": "T1", "recorded_at": "2026-09-14T09:00:00+00:00", "provider_id": "DEMO-PROV-SPL"}
        self.assertEqual(other_digest(a), other_digest({**a, "provider_id": "DEMO-PROV-3PL-01"}))
        self.assertNotEqual(other_digest(a), other_digest({**a, "recorded_at": "2026-09-14T09:00:01+00:00"}))


if __name__ == "__main__":
    unittest.main()
