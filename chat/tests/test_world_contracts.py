"""World-1 contract additions are additive, and the live-network (S5) dataset regenerates byte-identical. No database."""
import json
import unittest

from dataset_v2.contracts import KINDS, RELATIONSHIPS, UTC_FIELDS, Node, digest
from dataset_v2.context import CATALOG, OBSERVATIONS
from dataset_v2.feed import (CHANNELS, CHANNEL_PROVIDER, ENVELOPE, FEED_KINDS, INGESTIBLE_KINDS, SHARED_OBSERVATIONS, WORLD_FEED_KINDS,
                             Reference, decode, encode, split_feed)
from dataset_v2.network import generate_live, live_config

# Provenance of the S5 dataset (scripts/s5_scenarios.py provenance(): digest of manifest.json, feed_manifest hash and truth_hash).
S5_TRUTH_PREFIX = "0775597"
S5_FEED = "650656eb92efb99f903c45234f882d31543071b5a9f931bb31d7cad111aa9f30"
S5_MANIFEST = "d8707c05f218937a87bac829922c8b61b5cb5e252d117a712aadf74dd04efddf"


class S5RegenerationTests(unittest.TestCase):
    def test_s5_dataset_regenerates_byte_identical(self):
        world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
        imported, items = split_feed(world, truth)
        self.assertTrue(digest([truth[k] for k in sorted(truth)]).startswith(S5_TRUTH_PREFIX))
        self.assertEqual(digest(items), S5_FEED)
        self.assertEqual(digest(imported.manifest()), S5_MANIFEST)
        self.assertNotIn("MESSAGING", {item["channel"] for item in items})


class AdditiveContractTests(unittest.TestCase):
    def test_new_kinds_relationships_and_fields_are_registered(self):
        for kind in ("Container", "Trip", "RouteRun", "Lane", "FacilityThroughput", "TripEvent", "TrafficEvent", "CommunicationEvent"):
            self.assertIn(kind, KINDS)
        for rel in ("IN_CONTAINER", "ON_TRIP", "ON_ROUTE_RUN", "ON_LANE", "HAS_COMMUNICATION", "HAS_THROUGHPUT", "HAS_TRIP_EVENT"):
            self.assertIn(rel, RELATIONSHIPS)
        self.assertTrue({"cutoff_at", "estimated_arrival_at"} <= UTC_FIELDS)
        self.assertIn("CommunicationEvent", OBSERVATIONS)
        self.assertTrue({"Container", "Trip", "RouteRun", "Lane"} <= CATALOG)

    def test_live_network_channels_and_feed_kinds_unchanged(self):
        self.assertEqual(CHANNELS, ("SPL_CORE", "DRIVER_APP", "CARRIER_EDI", "TELEMATICS", "RECIPIENT_PORTAL", "TRAFFIC", "MDM"))
        self.assertEqual(FEED_KINDS, frozenset(OBSERVATIONS | {"DeviceHeartbeat"}))
        self.assertTrue(FEED_KINDS | {"AddressVersion"} <= INGESTIBLE_KINDS)
        self.assertTrue(WORLD_FEED_KINDS <= INGESTIBLE_KINDS and SHARED_OBSERVATIONS <= WORLD_FEED_KINDS)
        self.assertEqual(CHANNEL_PROVIDER["MESSAGING"], "DEMO-PROV-MSG-01")

    def test_new_ingestion_edge_rules_only_touch_ingestible_kinds(self):
        from operations.ingestion import EDGE_RULES
        for kind, prop, rel, outward in EDGE_RULES:
            self.assertIn(kind, INGESTIBLE_KINDS)
            self.assertIn(rel, RELATIONSHIPS)

    def test_messaging_round_trip_is_exact(self):
        ref = Reference([{"entity_id": "DEMO-SHP-1-PKG-01", "manifest_barcode": "RB123456785SA"}],
                        [{"entity_id": "DEMO-SHP-1", "tracking_id": "SYN0000000001"}])
        props = {"entity_id": "DEMO-SHP-1-COMM-001", "dataset_id": "DEMO-X", "schema_version": "suhail-v2.1", "synthetic": True,
                 "provenance": "SYNTHETIC_DEMO_ASSUMPTION", "split": "development", "holdout_group": "DEMO-SHP-1", "shipment_id": "DEMO-SHP-1",
                 "occurred_at": "2026-09-14T09:10:00+00:00", "recorded_at": "2026-09-14T09:12:00+00:00", "package_id": "DEMO-SHP-1-PKG-01",
                 "direction": "OUTBOUND", "channel_type": "SMS", "purpose": "OTP", "delivery_status": "FAILED", "carrier_route": "OP-2",
                 "recipient_id": "DEMO-SHP-1-RECIPIENT", "template_ref": "tpl-otp-v1", "secret_value_stored": False, "source_ref": "messaging-gateway"}
        node = Node(props["entity_id"], "CommunicationEvent", props)
        message_type, payload = encode(node, "MESSAGING", ref)
        payload = json.loads(json.dumps(payload))
        kind, entity, sid, occurred, decoded = decode("MESSAGING", message_type, payload, ref)
        self.assertEqual((kind, entity, sid, occurred), ("CommunicationEvent", node.id, "DEMO-SHP-1", props["occurred_at"]))
        self.assertEqual(decoded, {k: v for k, v in props.items() if k not in ENVELOPE})
        self.assertFalse({"otp", "otp_value", "code", "pin", "secret", "token"} & set(payload["dlr"]))  # No code value is ever carried.
