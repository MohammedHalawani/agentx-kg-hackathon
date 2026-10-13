"""A record's own provider is never replaced by the delivering channel's. No database."""
import json
import unittest

from dataset_v2.contracts import instant
from dataset_v2.feed import Reference
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
        self.created, self.linked = [], []

    def run(self, query, **params):
        if query.startswith("CREATE"):
            self.created.append(params["props"])
        elif "MERGE" in query:
            self.linked.append((params["a"], params["b"]))
        return Result()


def ingest(kind, entity_id, fields, *, channel="SPL_CORE", channel_provider="DEMO-PROV-SPL"):
    payload = {"type": kind, "id": entity_id, "shipment": None, "at": "2026-09-14T09:00:00+00:00", "fields": fields}
    item = {"channel": channel, "message_type": kind.upper(), "payload_json": json.dumps(payload), "payload_hash": "h",
            "feed_id": "DEMO-FEED-1", "provider_id": channel_provider, "origin": "PROVIDER"}
    gateway = Gateway(None, "unused", "DEMO-SUHAIL-WORLD-TEST")
    gateway._splits = {}
    tx = Tx()
    status = gateway._one(tx, Reference([], []), item, instant("2026-09-14T10:00:00+00:00"))[0]
    return status, tx


class ProviderPrecedenceTests(unittest.TestCase):
    def test_payload_provider_survives_a_different_delivering_channel(self):
        status, tx = ingest("Trip", "DEMO-TRIP-PROVIDER-X",
                            {"lane_id": "DEMO-LANE-X", "provider_id": "DEMO-PROV-3PL-01", "source_ref": "tms:trip"})
        self.assertEqual(status, "INGESTED")
        node = tx.created[0]
        self.assertEqual(node["provider_id"], "DEMO-PROV-3PL-01")
        # The delivery envelope is otherwise unchanged and still identifies the channel that delivered it.
        self.assertEqual((node["channel"], node["feed_id"], node["raw_payload_hash"]), ("SPL_CORE", "DEMO-FEED-1", "h"))
        # The relationship is built from the same payload value, so property and relationship agree.
        self.assertIn(("DEMO-TRIP-PROVIDER-X", "DEMO-PROV-3PL-01"), tx.linked)
        self.assertNotIn(("DEMO-TRIP-PROVIDER-X", "DEMO-PROV-SPL"), tx.linked)

    def test_envelope_provider_still_fills_a_payload_without_one(self):
        status, tx = ingest("FacilityThroughput", "DEMO-TP-PROVIDER-X",
                            {"facility_id": "DEMO-SORT-RUH-01", "processed_count": 3, "source_ref": "wms:throughput"})
        self.assertEqual(status, "INGESTED")
        self.assertEqual(tx.created[0]["provider_id"], "DEMO-PROV-SPL")


if __name__ == "__main__":
    unittest.main()
