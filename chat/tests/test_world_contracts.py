"""World-1 contract additions are additive, and the live-network (S5) dataset regenerates byte-identical. No database."""
import json
import unittest

from dataset_v2.contracts import KINDS, RELATIONSHIPS, UTC_FIELDS, Node, digest
from dataset_v2.context import CATALOG, OBSERVATIONS
from dataset_v2.feed import (CHANNELS, CHANNEL_PROVIDER, DATED_SHARED, ENVELOPE, FEED_KINDS, INGESTIBLE_KINDS, SHARED_OBSERVATIONS,
                             WORLD_FEED_KINDS, Reference, decode, encode, feed_item, ingestible_kinds, split_feed)
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
        # The live-network gateway accepts exactly what it accepted before the mechanism world existed.
        self.assertEqual(INGESTIBLE_KINDS, (FEED_KINDS - {"CommunicationEvent"}) | {"AddressVersion"})
        # Exactly the kinds the gateway accepted before the mechanism world existed (commit 968b264).
        self.assertEqual(INGESTIBLE_KINDS, frozenset((
            "ScanEvent", "CustodyEvent", "DeliveryAttempt", "ContactAttempt", "GPSObservation", "TrafficObservation", "DeliveryProof",
            "AuthenticationEvidence", "SignatureEvidence", "PhotoEvidence", "HandoffEvidence", "RecipientReport", "DepotReconciliation",
            "StatusEvent", "LocationPin", "Manifest", "DeviceHeartbeat", "AddressVersion")))
        self.assertTrue(SHARED_OBSERVATIONS | DATED_SHARED <= WORLD_FEED_KINDS)
        self.assertEqual(CHANNEL_PROVIDER["MESSAGING"], "DEMO-PROV-MSG-01")

    def test_the_wider_kind_set_is_accepted_only_for_mechanism_world_datasets(self):
        for dataset in ("DEMO-SUHAIL-LIVE", "DEMO-SUHAIL-LIVE-TEST", "DEMO-SUHAIL", "DEMO-OTHER", None):
            self.assertEqual(ingestible_kinds(dataset), INGESTIBLE_KINDS, dataset)
        for dataset in ("DEMO-SUHAIL-WORLD-1", "DEMO-SUHAIL-WORLD-TEST"):
            self.assertEqual(ingestible_kinds(dataset), INGESTIBLE_KINDS | WORLD_FEED_KINDS, dataset)
        world_only = WORLD_FEED_KINDS - INGESTIBLE_KINDS
        self.assertTrue({"DeliverySession", "VehicleAssignment", "Customer", "FacilityThroughput", "TripEvent", "TrafficEvent", "Trip",
                         "Container", "RouteRun", "CommunicationEvent"} <= world_only)

    def test_the_live_network_gateway_rejects_mechanism_world_kinds(self):
        from operations.ingestion import Gateway

        class Result:
            def single(self):
                return None

            def consume(self):
                return None

            def __iter__(self):
                return iter(())

        class Tx:
            def __init__(self):
                self.created = 0

            def run(self, query, **params):
                self.created += query.startswith("CREATE")
                return Result()

        ref = Reference([], [])
        payload = {"type": "FacilityThroughput", "id": "DEMO-TP-X", "shipment": None, "at": "2026-09-14T09:00:00+00:00",
                   "fields": {"facility_id": "DEMO-SORT-RUH-01", "processed_count": 3, "source_ref": "wms:throughput"}}
        item = {"channel": "SPL_CORE", "message_type": "FACILITYTHROUGHPUT", "payload_json": json.dumps(payload), "payload_hash": "h",
                "feed_id": "DEMO-FEED-1", "provider_id": "DEMO-PROV-SPL", "origin": "PROVIDER"}
        from dataset_v2.contracts import instant
        clock = instant("2026-09-14T10:00:00+00:00")
        for dataset, status in (("DEMO-SUHAIL-LIVE", "REJECTED"), ("DEMO-SUHAIL-WORLD-1", "INGESTED")):
            gateway = Gateway(None, "unused", dataset)
            gateway._splits = {}
            tx = Tx()
            self.assertEqual(gateway._one(tx, ref, item, clock)[0], status, dataset)
            self.assertEqual(tx.created, 1 if status == "INGESTED" else 0)

    def test_new_ingestion_edge_rules_only_touch_ingestible_kinds(self):
        from operations.ingestion import EDGE_RULES
        accepted = ingestible_kinds("DEMO-SUHAIL-WORLD-1")
        for kind, prop, rel, outward in EDGE_RULES:
            self.assertIn(kind, accepted)
            self.assertIn(rel, RELATIONSHIPS)

    def test_a_dated_shared_record_round_trips_through_the_feed(self):
        from dataset_v2.contracts import World
        from world.config import WorldConfig
        world = World(WorldConfig(dataset_id="DEMO-SUHAIL-WORLD-TEST").v2_config({"history": 20, "development": 20}))
        world.node("Container", "DEMO-CTR-RUH-00001", occurred_at="2026-09-14T09:00:00+00:00", recorded_at="2026-09-14T09:00:05+00:00",
                   container_type="BAG", origin_facility_id="DEMO-SORT-RUH-01", destination_facility_id="DEMO-DEPOT-RUH-N", source_ref="wms:container")
        node = world.nodes["DEMO-CTR-RUH-00001"]
        item = feed_item(world, node, Reference([], []))
        kind, entity, sid, occurred, props = decode(item["channel"], item["message_type"], json.loads(item["payload_json"]), Reference([], []))
        self.assertEqual((kind, entity, sid, occurred), ("Container", node.id, None, node.properties["occurred_at"]))
        self.assertEqual(props, {k: v for k, v in node.properties.items() if k not in ENVELOPE})

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
