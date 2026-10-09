"""Provider gateway against a real Neo4j (isolated test database). Opt-in: SUHAIL_NEO4J_TESTS=1.

Builds a small live bundle, imports it into shipments-v2-demo-test (recreated for the run), and
checks ingestion timing, de-duplication, provenance, late-upload visibility, idempotence and reset.
The foundation (shipments-v2-demo) and live (shipments-v2-demo-live) databases are never written.
"""
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from dataset_v2.contracts import instant, iso

TEST_DATABASE = "shipments-v2-demo-test"


@unittest.skipUnless(os.environ.get("SUHAIL_NEO4J_TESTS") == "1", "set SUHAIL_NEO4J_TESTS=1 to run against local Neo4j")
class LiveIngestionNeo4jTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config
        from core.query_runner import get_driver
        from dataset_v2.live_bundle import export_live, load_feed, read_live_bundle, read_truth
        from dataset_v2.load import apply_bundle
        from dataset_v2.network import live_config
        cls.driver = get_driver()
        cls.counts_before = cls.database_counts()
        cls.tmp = tempfile.TemporaryDirectory()
        bundle_dir = Path(cls.tmp.name) / "bundle"
        export_live(bundle_dir, live_config(total=150, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
        with cls.driver.session(database="system") as session:
            session.run(f"CREATE OR REPLACE DATABASE `{TEST_DATABASE}` WAIT 60 SECONDS").consume()
        cls.bundle, cls.items = read_live_bundle(bundle_dir)
        cls.truth = read_truth(bundle_dir)
        protected = (config.SHIPMENT_DATABASE, config.NEO4J_DATABASE, config.CHAT_DATABASE)
        report = apply_bundle(cls.driver, cls.bundle, uri=config.NEO4J_URI, database=TEST_DATABASE, protected=protected)
        assert report["status"] == "imported", report
        load_feed(cls.driver, TEST_DATABASE, cls.bundle, cls.items)
        from operations.ingestion import Gateway
        cls.gateway = Gateway(cls.driver, TEST_DATABASE, cls.bundle.manifest["dataset_id"])

    @classmethod
    def tearDownClass(cls):
        assert cls.database_counts() == cls.counts_before, "foundation/live databases must be untouched"
        cls.tmp.cleanup()

    @classmethod
    def database_counts(cls):
        out = {}
        with cls.driver.session(database="system", default_access_mode="READ") as session:
            names = {r["name"] for r in session.run("SHOW DATABASES YIELD name RETURN name")}
        for name in ("shipments-v2-demo",):
            if name in names:
                with cls.driver.session(database=name, default_access_mode="READ") as session:
                    out[name] = session.run("MATCH (n:V2Entity) RETURN count(n) AS n").single()["n"]
        return out

    def query(self, cypher, **params):
        with self.driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
            return [dict(r) for r in session.run(cypher, **params)]

    def test_1_only_delivered_messages_are_ingested_with_provenance(self):
        self.gateway.reset()
        first = min(instant(i["deliver_at"]) for i in self.items)
        clock = first + timedelta(hours=30)
        due = sum(instant(i["deliver_at"]) <= clock for i in self.items)
        total = {"ingested": 0, "duplicate": 0}
        while True:
            batch = self.gateway.ingest_due(clock.isoformat(), limit=500)
            for key in total: total[key] += batch[key]
            if batch["messages"] < 500: break
        self.assertEqual(batch["rejected"], 0)
        self.assertEqual(total["ingested"] + total["duplicate"], due)
        rows = self.query("MATCH (n:LiveIngested) RETURN n.recorded_at AS rec, n.occurred_at AS occ, n.channel AS channel, "
                          "n.provider_id AS provider, n.feed_id AS feed, n.raw_payload_hash AS hash")
        self.assertEqual(len(rows), total["ingested"])
        for row in rows:
            self.assertLessEqual(row["rec"].to_native(), clock)
            self.assertLessEqual(row["occ"].to_native(), row["rec"].to_native())
            self.assertTrue(row["channel"] and row["provider"] and row["feed"] and row["hash"])
        pending = self.query("MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.deliver_at <= $c RETURN count(f) AS n", c=clock)
        self.assertEqual(pending[0]["n"], 0)

    def test_2_retransmissions_are_duplicates_and_reingest_is_idempotent(self):
        clock = max(instant(i["deliver_at"]) for i in self.items) + timedelta(minutes=1)
        while self.gateway.ingest_due(clock.isoformat(), limit=500)["messages"] == 500:
            pass
        before = self.query("MATCH (n:LiveIngested) RETURN count(n) AS n")[0]["n"]
        self.assertEqual(self.gateway.ingest_due(clock.isoformat())["messages"], 0)
        self.assertEqual(self.query("MATCH (n:LiveIngested) RETURN count(n) AS n")[0]["n"], before)
        duplicates = self.query("MATCH (f:ProviderFeedItem {status:'DUPLICATE'}) RETURN f.source_event_id AS id")
        self.assertTrue(duplicates)
        for row in duplicates:
            self.assertEqual(self.query("MATCH (n:LiveIngested {entity_id:$id}) RETURN count(n) AS n", id=row["id"])[0]["n"], 1)
        self.assertEqual(before, len({i["source_event_id"] for i in self.items}))

    def test_3_late_upload_is_invisible_until_ingested_then_visible_as_late(self):
        from operations.read_model import OperationsReader
        from dataset_v2.contracts import Config
        row = next(r for r in self.truth.values() if r["recipe"] == "offline_device_sync" and r["split"] == "development")
        late = row["physical"]["buffered_event_ids"][0]
        node = self.query("MATCH (n:LiveIngested {entity_id:$id}) RETURN n.occurred_at AS occ, n.recorded_at AS rec", id=late)[0]
        occurred, recorded = node["occ"].to_native(), node["rec"].to_native()
        self.assertGreaterEqual(recorded - occurred, timedelta(hours=19))
        cfg = Config(**self.bundle.manifest["config"])
        reader = OperationsReader(self.driver, TEST_DATABASE, cfg.dataset_id, cfg, clock=lambda: iso(recorded + timedelta(minutes=1)))
        between = iso(occurred + timedelta(hours=2))
        self.assertNotIn(late, {n["id"] for n in reader.evidence(row["shipment_id"], between)["nodes"]})
        self.assertIn(late, {n["id"] for n in reader.evidence(row["shipment_id"], iso(recorded))["nodes"]})

    def test_4_conflicting_retransmission_is_kept_apart_and_unknown_payload_rejected(self):
        clock = max(instant(i["deliver_at"]) for i in self.items) + timedelta(minutes=5)
        original = next(i for i in self.items if i["channel"] == "SPL_CORE" and i["message_type"] == "SCANEVENT")
        tampered = {**original, "feed_id": "DEMO-FEED-TAMPERED-1", "payload_hash": "different", "deliver_at": iso(clock - timedelta(minutes=1)),
                    "origin": "TEST"}
        broken = {**original, "feed_id": "DEMO-FEED-BROKEN-1", "payload_json": "{\"type\":\"Unknown\"}", "deliver_at": iso(clock - timedelta(minutes=1)),
                  "origin": "TEST"}
        self.gateway.enqueue([tampered, broken])
        result = self.gateway.ingest_due(clock.isoformat())
        self.assertEqual((result["conflicting_duplicate"], result["rejected"]), (1, 1))
        statuses = {r["id"]: r["status"] for r in self.query("MATCH (f:ProviderFeedItem) WHERE f.origin='TEST' RETURN f.feed_id AS id, f.status AS status")}
        self.assertEqual(statuses, {"DEMO-FEED-TAMPERED-1": "CONFLICTING_DUPLICATE", "DEMO-FEED-BROKEN-1": "REJECTED"})

    def test_5_reset_returns_every_provider_message_to_pending(self):
        self.gateway.reset()
        self.assertEqual(self.query("MATCH (n:LiveIngested) RETURN count(n) AS n")[0]["n"], 0)
        self.assertEqual(self.query("MATCH (f:ProviderFeedItem) WHERE f.origin <> 'PROVIDER' RETURN count(f) AS n")[0]["n"], 0)
        self.assertEqual(self.query("MATCH (f:ProviderFeedItem {status:'PENDING'}) RETURN count(f) AS n")[0]["n"], len(self.items))
        self.assertGreater(self.query("MATCH (n:V2Entity) RETURN count(n) AS n")[0]["n"], 0)  # Imports untouched.


if __name__ == "__main__":
    unittest.main()
