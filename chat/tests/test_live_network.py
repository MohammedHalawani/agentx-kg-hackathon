"""Live network dataset (S2a): providers, contractors, devices, provider feeds and truth isolation. No database."""
import json
import unittest
from collections import Counter
from datetime import timedelta

from dataset_v2.contracts import canonical, instant
from dataset_v2.feed import CHANNELS, ENVELOPE, Reference, decode, split_feed, validate_live_bundle
from dataset_v2.network import LIVE_NORMAL, PHYSICAL, REQUIRED_LIVE, generate_live, live_config
from dataset_v2.validate import validate_world


class LiveNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world, cls.truth = generate_live(live_config(total=150))
        cls.imported, cls.items = split_feed(cls.world, cls.truth)

    def dev(self):
        return {sid: row for sid, row in self.truth.items() if row["split"] == "development"}

    def test_full_world_is_domain_valid_and_every_required_scenario_is_live(self):
        self.assertTrue(validate_world(self.world)["pass"])
        recipes = {row["recipe"] for row in self.dev().values()}
        self.assertTrue(set(REQUIRED_LIVE) <= recipes, set(REQUIRED_LIVE) - recipes)

    def test_truth_never_appears_in_world_records(self):
        text = canonical([n.record() for n in self.world.nodes.values()] + [e.record() for e in self.world.edges.values()])
        for marker in ("offline_device_sync", "contractor_unreturned", "wrong_label", "declared_weight_wrong", "misread",
                       "buffered_upload", "retained_by_contractor", "root_cause", "expected_resolution", "live_recipe"):
            self.assertNotIn(marker, text)
        self.assertNotIn("truth", canonical(self.items))

    def test_contractors_private_cars_providers_and_devices(self):
        private = [v for v in self.world.of_kind("Vehicle") if v.properties.get("ownership") == "PRIVATE"]
        self.assertTrue(private)
        for vehicle in private:
            driver = self.world.nodes[vehicle.properties["driver_id"]].properties
            self.assertEqual((driver["employment"], driver["provider_id"]), ("INDEPENDENT", "DEMO-PROV-INDEP-01"))
            self.assertEqual(vehicle.properties["vehicle_class"], "PRIVATE_CAR")
        self.assertEqual({v.properties["provider_id"] for v in self.world.of_kind("Vehicle")},
                         {"DEMO-PROV-SPL", "DEMO-PROV-3PL-01", "DEMO-PROV-INDEP-01"})
        devices = {d.id for d in self.world.of_kind("Device")}
        for scan in self.world.of_kind("ScanEvent"):
            self.assertIn(scan.properties["device_ref"], devices)
        # Assignment, manifest inclusion and physical confirmation are distinct records.
        for assignment in self.world.of_kind("VehicleAssignment"):
            if assignment.properties["mode"] == "last_mile" and not assignment.id.endswith("FOLLOWUP-ASSIGN"):
                manifests = [m for m in self.world.of_kind("Manifest") if m.properties["assignment_id"] == assignment.id]
                self.assertTrue(manifests)
        confirmations = [s for s in self.world.of_kind("ScanEvent") if s.properties.get("observation_type") == "CUSTODY_CONFIRMATION"]
        self.assertTrue(confirmations)
        self.assertTrue(all(s.properties["device_ref"].startswith("DEMO-DEV-APP-") for s in confirmations))

    def test_offline_device_uploads_late_and_its_heartbeats_stop(self):
        rows = [r for r in self.truth.values() if r["recipe"] == "offline_device_sync"]
        self.assertTrue(rows)
        for row in rows:
            phys = row["physical"]
            for key in phys["buffered_event_ids"]:
                p = self.world.nodes[key].properties
                self.assertGreaterEqual(instant(p["recorded_at"]) - instant(p["occurred_at"]), timedelta(hours=19))
            beats = [h for h in self.world.of_kind("DeviceHeartbeat") if h.properties["device_id"] == phys["device_id"]]
            start, end = instant(phys["offline_from"]), instant(phys["natural_reconnect_at"])
            self.assertFalse([h for h in beats if start <= instant(h.properties["occurred_at"]) < end])
            reconnect = [h for h in beats if instant(h.properties["occurred_at"]) == end]
            self.assertTrue(reconnect and reconnect[0].properties["pending_uploads"] > 0)

    def test_scenario_overlays(self):
        for sid, row in self.dev().items():
            owned = self.world.owned(sid)
            if row["recipe"] == "contractor_unreturned":
                self.assertEqual(row["last_mile_vehicle_ownership"], "PRIVATE")
                self.assertFalse([n for n in owned if n.kind == "CustodyEvent" and n.properties["event_type"] == "RETURNED"])
                self.assertFalse([n for n in owned if n.kind == "DepotReconciliation"])
            if row["recipe"] == "conflicting_manifest":
                versions = sorted((n for n in owned if n.kind == "Manifest"), key=lambda n: n.properties["version"])
                self.assertEqual([v.properties["version"] for v in versions], [1, 2])
                self.assertNotIn(row["physical"]["dropped_package_id"], versions[1].properties["package_ids"])
            if row["recipe"] == "contractor_unconfirmed_pickup":
                load = self.world.nodes[row["key_evidence"][0]].properties
                self.assertLess(load["received_acknowledgments"], load["required_acknowledgments"])

    def test_feed_round_trip_is_exact_for_every_channel(self):
        ref = Reference.from_world(self.imported)
        seen = Counter()
        for item in self.items:
            kind, entity_id, sid, occurred, props = decode(item["channel"], item["message_type"], json.loads(item["payload_json"]), ref)
            original = self.world.nodes[entity_id]
            self.assertEqual(kind, original.kind)
            self.assertEqual(occurred, original.properties["occurred_at"])
            self.assertEqual(sid, original.properties.get("shipment_id"))
            self.assertEqual(props, {k: v for k, v in original.properties.items() if k not in ENVELOPE})
            seen[item["channel"]] += 1
        self.assertEqual(set(seen), set(CHANNELS) - ({"TRAFFIC"} if "TRAFFIC" not in seen else set()))

    def test_driver_app_speaks_barcodes_and_local_time(self):
        app = [json.loads(i["payload_json"]) for i in self.items if i["channel"] == "DRIVER_APP"]
        self.assertTrue(app)
        for payload in app:
            self.assertTrue(payload["local_time"].endswith("+0300"))
            self.assertNotIn("package_id", payload["attrs"])

    def test_feed_carries_delivery_lag_late_uploads_and_retransmissions(self):
        for item in self.items:
            node = self.world.nodes[item["source_event_id"]].properties
            self.assertGreaterEqual(instant(item["deliver_at"]), instant(node["recorded_at"]))
        by_source = Counter(i["source_event_id"] for i in self.items)
        retransmitted = [k for k, n in by_source.items() if n > 1]
        self.assertTrue(retransmitted)
        for key in retransmitted:
            copies = [i for i in self.items if i["source_event_id"] == key]
            self.assertEqual(len({c["payload_hash"] for c in copies}), 1)
            self.assertEqual(self.truth[self.world.nodes[key].properties["shipment_id"]]["recipe"], "duplicate_provider_events")

    def test_import_holds_no_live_observations_derived_cases_or_story_end(self):
        live = set(self.dev())
        for node in self.imported.nodes.values():
            if node.properties.get("holdout_group") in live:
                self.assertNotIn(node.kind, ("ScanEvent", "CustodyEvent", "DeliveryAttempt", "DeliveryProof", "Case", "Exception",
                                             "RecipientReport", "Manifest", "StatusEvent"))
                self.assertNotIn("as_of", node.properties)
                if node.kind == "Shipment":
                    self.assertEqual(node.properties["status"], "CREATED")
        self.assertFalse([n for n in self.imported.nodes.values() if n.kind == "DeviceHeartbeat"])
        self.assertFalse([e for e in self.imported.edges.values() if e.kind == "LOADED_ON" and e.properties["holdout_group"] in live])

    def test_bundle_reconstitutes_into_a_valid_world(self):
        result = validate_live_bundle(self.imported, self.items)
        self.assertTrue(result["pass"], Counter(e["code"] for e in result["errors"]))
        self.assertGreater(result["feed"]["retransmissions"], 0)

    def test_healthy_recipes_have_no_expected_cause(self):
        for row in self.truth.values():
            if row["recipe"] in LIVE_NORMAL and not row.get("secondary_effect_of"):
                self.assertTrue(row["healthy"]); self.assertIsNone(row["root_cause"])
            if row["recipe"] in PHYSICAL:
                self.assertTrue(row["physical"])


if __name__ == "__main__":
    unittest.main()
