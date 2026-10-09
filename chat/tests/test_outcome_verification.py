"""S4: action-specific outcome verification and the operational simulator's field responses."""
import unittest
from datetime import timedelta

from dataset_v2.contracts import Node, instant, iso
from dataset_v2.feed import reconstitute, split_feed
from dataset_v2.network import generate_live, live_config
from operations.outcome_engine import evaluate
from operations.reasoning import evidence_world, public_evidence


class Fixture:
    _cache = None

    @classmethod
    def get(cls):
        if cls._cache is None:
            world, truth = generate_live(live_config(total=150))
            imported, items = split_feed(world, truth)
            cls._cache = (reconstitute(imported, items), truth)
        return cls._cache


class VerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world, cls.truth = Fixture.get()

    def snapshot(self, sid, at):
        return evidence_world(public_evidence(self.world, sid, at), self.world.config)

    def sid(self, recipe):
        return next(s for s, r in self.truth.items() if r["recipe"] == recipe and r["split"] == "development")

    def add(self, world, kind, key, recorded, **props):
        node = Node(key, kind, {"shipment_id": props.pop("shipment_id"), "occurred_at": props.pop("occurred_at", recorded),
                                "recorded_at": recorded, **props})
        world.nodes[key] = node
        return node

    def test_unrelated_later_delivery_does_not_verify_a_rescan(self):
        sid = self.sid("different_barcode")
        at = self.world.config.as_of
        world = self.snapshot(sid, at)
        start = instant(at) - timedelta(days=1)
        execution = {"action_type": "REQUEST_RESCAN", "occurred_at": iso(start), "deadline_at": iso(start + timedelta(hours=72))}
        # Every package has later corroborated delivery evidence in the world, but no rescan after the request.
        self.assertEqual(evaluate(world, sid, execution, at)["status"], "pending")
        self.assertEqual(evaluate(world, sid, execution, iso(start + timedelta(hours=72)))["status"], "failure")

    def test_rescan_needs_a_matching_read_and_a_wrong_label_fails(self):
        sid = self.sid("different_barcode")
        at = instant(self.world.config.as_of)
        world = self.snapshot(sid, iso(at))
        start = at - timedelta(hours=2)
        execution = {"action_type": "REQUEST_RESCAN", "occurred_at": iso(start), "deadline_at": iso(start + timedelta(hours=72))}
        packages = [n for n in world.nodes.values() if n.kind == "Package"]
        for i, package in enumerate(packages):
            self.add(world, "ScanEvent", f"RESCAN-{i}", iso(start + timedelta(minutes=30)), shipment_id=sid, package_id=package.id,
                     readable=True, confidence=.99, observed_barcode=package.properties["manifest_barcode"])
        self.assertEqual(evaluate(world, sid, execution, iso(at))["outcome_type"], "barcode_corrected")
        self.add(world, "ScanEvent", "RESCAN-WRONG", iso(start + timedelta(minutes=40)), shipment_id=sid, package_id=packages[0].id,
                 readable=True, confidence=.99, observed_barcode="WRONG")
        self.assertEqual(evaluate(world, sid, execution, iso(at))["status"], "failure")

    def test_device_sync_needs_the_late_source_event_from_the_target_device(self):
        sid = self.sid("offline_device_sync")
        row = self.truth[sid]
        late = [self.world.nodes[k] for k in row["physical"]["buffered_event_ids"] if self.world.nodes[k].kind == "CustodyEvent"]
        occurred = min(instant(n.properties["occurred_at"]) for n in late)
        request = occurred + timedelta(hours=2)
        expected = [{"package_id": n.properties["package_id"], "predicate": "RECEIVED", "location_id": n.properties["to_id"]} for n in late]
        execution = {"action_type": "REQUEST_DEVICE_SYNC", "occurred_at": iso(request), "deadline_at": iso(request + timedelta(hours=24)),
                     "expected_evidence": expected, "target_device": row["physical"]["device_id"]}
        # Before the buffered upload arrives: pending; at the natural reconnect (after the request): success.
        self.assertEqual(evaluate(self.snapshot(sid, iso(request + timedelta(hours=1))), sid, execution, iso(request + timedelta(hours=1)))["status"], "pending")
        reconnect = row["physical"]["natural_reconnect_at"]
        after = iso(instant(reconnect) + timedelta(minutes=5))
        verdict = evaluate(self.snapshot(sid, after), sid, execution, after)
        self.assertEqual((verdict["status"], verdict["outcome_type"]), ("success", "delayed_upload_received"))
        # A different device's upload does not count.
        verdict = evaluate(self.snapshot(sid, after), sid, {**execution, "target_device": "DEMO-DEV-HH-OTHER"}, after)
        self.assertNotEqual(verdict["status"], "success")

    def test_non_receipt_report_after_action_is_failure(self):
        sid = self.sid("different_weight")
        at = instant(self.world.config.as_of)
        world = self.snapshot(sid, iso(at))
        start = at - timedelta(hours=2)
        self.add(world, "RecipientReport", "LATE-REPORT", iso(start + timedelta(minutes=5)), shipment_id=sid, report_code="NOT_RECEIVED")
        execution = {"action_type": "REQUEST_REWEIGH", "occurred_at": iso(start), "deadline_at": iso(start + timedelta(hours=72))}
        self.assertEqual(evaluate(world, sid, execution, iso(at))["outcome_type"], "dispute_unresolved")


if __name__ == "__main__":
    unittest.main()
