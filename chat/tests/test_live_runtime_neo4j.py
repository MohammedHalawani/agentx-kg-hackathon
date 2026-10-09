"""Live runtime against a real Neo4j test database (S2b). Opt-in: SUHAIL_NEO4J_TESTS=1.

Replays the whole live timeline through the gateway and the monitor only (no investigation), then
compares the cases the monitor opened with the separately stored truth: healthy shipments must not
get cases, abnormal ones must, and each case must be opened from evidence ingested by then.
A second test runs the separated workers with a deliberately slow investigation and checks that
ingestion and monitoring keep making progress meanwhile.
"""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import os as _os
# A second isolated twin lets two evaluation phases run side by side.
TEST_DATABASE = _os.environ.get("SUHAIL_TEST_DATABASE", "shipments-v2-demo-test")
assert TEST_DATABASE in ("shipments-v2-demo-test", "shipments-v2-demo-test2")


def build_test_database(total=150, live_split="development"):
    import config
    from core.query_runner import get_driver
    from dataset_v2.live_bundle import export_live, load_feed, read_live_bundle, read_truth
    from dataset_v2.load import apply_bundle
    from dataset_v2.network import live_config
    driver = get_driver()
    tmp = tempfile.TemporaryDirectory()
    bundle_dir = Path(tmp.name) / "bundle"
    export_live(bundle_dir, live_config(total=total, dataset_id="DEMO-SUHAIL-LIVE-TEST"), live_split=live_split)
    with driver.session(database="system") as session:
        session.run(f"CREATE OR REPLACE DATABASE `{TEST_DATABASE}` WAIT 60 SECONDS").consume()
    bundle, items = read_live_bundle(bundle_dir)
    report = apply_bundle(driver, bundle, uri=config.NEO4J_URI, database=TEST_DATABASE,
                          protected=(config.SHIPMENT_DATABASE, config.NEO4J_DATABASE, config.CHAT_DATABASE))
    assert report["status"] == "imported", report
    load_feed(driver, TEST_DATABASE, bundle, items)
    return driver, bundle, read_truth(bundle_dir), tmp


def make_store(driver, bundle, agents=None):
    from dataset_v2.contracts import Config
    from operations.read_model import OperationsReader
    from operations.store import OperationsStore
    cfg = Config(**bundle.manifest["config"])
    reader = OperationsReader(driver, TEST_DATABASE, cfg.dataset_id, cfg, lambda: store.status()["as_of"])
    store = OperationsStore(driver, TEST_DATABASE, cfg.dataset_id, cfg, reader=reader, agents=agents)
    reader.store = store
    store.initialize()
    store.reset_session()
    return store


@unittest.skipUnless(os.environ.get("SUHAIL_NEO4J_TESTS") == "1", "set SUHAIL_NEO4J_TESTS=1 to run against local Neo4j")
class LiveRuntimeNeo4jTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver, cls.bundle, cls.truth, cls.tmp = build_test_database()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ledger(self, kind):
        with self.driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
            return [dict(r["p"]) for r in session.run(f"MATCH (n:OpsEntity:{kind}) RETURN properties(n) AS p")]

    def test_1_monitor_detection_against_truth(self):
        store = make_store(self.driver, self.bundle)
        while True:
            result = store.tick(seconds=3600, manual=True, speed=1)
            while store.status()["session"]["monitor_pending"]:
                store.monitor_step(limit=20)
            if store.status()["as_of"] >= store.status()["simulator"]["end_at"]:
                break
        cases = self.ledger("OpsCase")
        by_shipment = {}
        for case in cases:
            by_shipment.setdefault(case["shipment_id"], []).append(case)
        live = {sid: row for sid, row in self.truth.items() if row["split"] == "development"}
        false_positive = sorted(sid for sid, row in live.items() if row["healthy"] and sid in by_shipment)
        missed = sorted(sid for sid, row in live.items() if not row["healthy"] and sid not in by_shipment)
        report = {"live": len(live), "abnormal": sum(not r["healthy"] for r in live.values()), "cases": len(cases),
                  "false_positive": [(s, live[s]["recipe"], [c["symptom_codes"] for c in by_shipment[s]], [str(c["opened_at"]) for c in by_shipment[s]]) for s in false_positive], "missed": [(s, live[s]["recipe"]) for s in missed]}
        print("\nDETECTION", report)
        self.assertEqual(false_positive, [], report)
        self.assertEqual(missed, [], report)
        for case in cases:
            self.assertEqual(case["cause_codes"], [])
            self.assertTrue(case["symptom_codes"])
        # Scenario checks: the offline device is caught as an overdue milestone before its late upload.
        for sid, row in live.items():
            if row["recipe"] == "offline_device_sync":
                opened = min(c["opened_at"].to_native() for c in by_shipment[sid])
                self.assertIn("MILESTONE_OVERDUE", by_shipment[sid][0]["symptom_codes"])
                from dataset_v2.contracts import instant
                self.assertLess(opened, instant(row["physical"]["natural_reconnect_at"]))
            if row["recipe"] == "contractor_unreturned":
                self.assertIn("SESSION_END_UNRECONCILED", {s for c in by_shipment[sid] for s in c["symptom_codes"]})
            if row["recipe"] == "conflicting_manifest":
                self.assertIn("MANIFEST_CUSTODY_CONFLICT", {s for c in by_shipment[sid] for s in c["symptom_codes"]})

    def test_2_slow_investigation_does_not_block_ingestion_or_monitoring(self):
        from operations.workers import WorkerPool
        store = make_store(self.driver, self.bundle)
        gate = threading.Event()
        original = store.process_one
        def slow_process_one(*args, **kwargs):
            gate.wait(20)  # Stands in for a slow model call that holds the investigation worker.
            return original(*args, **kwargs)
        store.process_one = slow_process_one
        os.environ["SUHAIL_WORKER_PACE_SECONDS"] = "0"
        store.control("simulator", "start", speed=3600)
        store.control("worker", "start")
        pool = WorkerPool(store).start()
        try:
            started = store.status()
            time.sleep(12)
            during = store.status()
            workers = pool.status()
        finally:
            gate.set()
            pool.stop()
            store.control("simulator", "pause")
            store.control("worker", "pause")
        print("\nSEPARATION", {"events": [started["simulator"]["event_count"], during["simulator"]["event_count"]],
                               "monitor_checked": [started["session"]["monitor_checked"], during["session"]["monitor_checked"]],
                               "investigation_busy": workers["investigation"]["busy"]})
        self.assertTrue(workers["investigation"]["busy"])  # Still inside the slow investigation...
        self.assertGreater(during["simulator"]["event_count"], started["simulator"]["event_count"])  # ...while ingestion advanced
        self.assertGreater(during["session"]["monitor_checked"], started["session"]["monitor_checked"])  # ...and monitoring ran.


if __name__ == "__main__":
    unittest.main()
