"""Stage 2, section 1: operations on a mechanism-world database, with no simulator, and delivery-time ingestion.

No database: the store runs on the transactional in-memory port, the gateway on a recording transaction.
"""
from dataclasses import asdict
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # The backend package lives at the repository root.

from dataset_v2.contracts import Config, canonical, digest, instant, iso
from dataset_v2.generate import generate
from operations import datasets
from operations.ingestion import Gateway
from operations.lifecycle import OperationsConflict
from operations.read_model import OperationsReader
from operations.store import OperationsStore
from tests import test_operations_store as _store
from tests.test_operations_store import Acknowledging, Driver, Reader, agent_investigator, approval_policy, development_reset

WORLD_CONFIG = {"dataset_id": "DEMO-SUHAIL-WORLD-1", "development": 254, "held_out": 0, "history": 274, "normal_fraction": 0.7,
                "reconciliation_grace_minutes": 60, "seed": 20261010, "session_end": "20:00", "session_start": "08:00",
                "simulation_days": 12, "start_at": "2026-09-09T21:00:00+00:00", "total": 528}


class DatabasePolicyTests(unittest.TestCase):
    def test_world_databases_are_accepted_by_pattern_and_nothing_else_is_loosened(self):
        for name in ("shipments-v2-world-1-small", "shipments-v2-world-e1", "shipments-v2-world-1-small-heldout"):
            self.assertTrue(datasets.operations_database_allowed(name), name)
            self.assertTrue(datasets.read_database_allowed(name), name)
        for name in ("shipments-v2-world-", "shipments-v2-world", "shipments-v2-World-1", "shipments-v2-world-1_small", "shipments-v2-worlds-1",
                     "shipments-v2-demo-other", "shipments-v2-demo-world-1", "shipments", "neo4j", "system", "shipments-v2-world-1;drop", None, 7):
            self.assertFalse(datasets.operations_database_allowed(name), name)
        # The fixed list is exactly what it was.
        self.assertEqual(datasets.OPERATIONS_DATABASES, ("shipments-v2-demo", "shipments-v2-demo-live", "shipments-v2-demo-test",
                                                         "shipments-v2-demo-test2", "shipments-v2-demo-ci-test"))
        from operations import store
        self.assertIs(store.OPERATIONS_DATABASES, datasets.OPERATIONS_DATABASES)

    def test_world_data_and_world_databases_go_together(self):
        self.assertIsNone(datasets.pairing_error("shipments-v2-world-1-small", "DEMO-SUHAIL-WORLD-1"))
        self.assertIsNone(datasets.pairing_error("shipments-v2-demo-ci-test", "DEMO-SUHAIL-WORLD-TEST"))   # scratch database for tests
        self.assertIsNone(datasets.pairing_error("shipments-v2-demo-live", "DEMO-SUHAIL-LIVE-1"))
        self.assertIsNone(datasets.pairing_error("shipments-v2-demo", "DEMO-SUHAIL-V2-FOUNDATION"))
        for database, dataset in (("shipments-v2-world-1-small", "DEMO-SUHAIL-LIVE-1"), ("shipments-v2-world-1-small", "DEMO-SUHAIL-V2-FOUNDATION"),
                                  ("shipments-v2-demo-live", "DEMO-SUHAIL-WORLD-1"), ("shipments-v2-demo", "DEMO-SUHAIL-WORLD-1")):
            self.assertIsNotNone(datasets.pairing_error(database, dataset), (database, dataset))

    def test_the_store_and_the_reader_enforce_the_policy(self):
        world = generate(Config(total=90))
        driver = Driver(world)
        with self.assertRaises(OperationsConflict):
            OperationsStore(driver, "shipments-v2-world-1-small", world.config.dataset_id, world.config, Reader(world))
        with self.assertRaises(OperationsConflict):
            OperationsStore(driver, "shipments-v2-demo-other", world.config.dataset_id, world.config, Reader(world))
        with self.assertRaises(OperationsConflict):
            OperationsStore(driver, "shipments-v2-demo-live", "DEMO-SUHAIL-WORLD-1", datasets.dataset_config(WORLD_CONFIG), Reader(world))
        with self.assertRaises(ValueError):
            OperationsReader(driver, "shipments-v2-world-1-small", world.config.dataset_id, world.config)
        with self.assertRaises(ValueError):
            OperationsReader(driver, "shipments-v2-other", "DEMO-SUHAIL-WORLD-1", datasets.dataset_config(WORLD_CONFIG))
        reader = OperationsReader(driver, "shipments-v2-world-1-small", "DEMO-SUHAIL-WORLD-1", datasets.dataset_config(WORLD_CONFIG))
        self.assertEqual(reader.database, "shipments-v2-world-1-small")
        # Protected targets are still refused by the target guard, whatever the name pattern says.
        with self.assertRaises(ValueError):
            OperationsStore(driver, "shipments-v2-world-1-small", "DEMO-SUHAIL-WORLD-1", datasets.dataset_config(WORLD_CONFIG), Reader(world),
                            protected=("shipments-v2-world-1-small",))

    def test_a_world_export_configuration_is_read_and_the_foundation_one_is_unchanged(self):
        config = datasets.dataset_config(WORLD_CONFIG)
        self.assertIsInstance(config, Config)
        self.assertEqual(asdict(config), WORLD_CONFIG)          # What the store compares with the imported manifest.
        self.assertEqual(config.split_counts, {"history": 274, "development": 254})
        self.assertEqual(config.as_of, "2026-10-01T21:00:00+00:00")
        with self.assertRaises(ValueError):                      # The foundation Config still refuses an empty split...
            Config(**WORLD_CONFIG)
        with self.assertRaises(ValueError):                      # ...and only a world dataset may have one.
            datasets.dataset_config({**WORLD_CONFIG, "dataset_id": "DEMO-SUHAIL-LIVE-1"})
        for bad in ({**WORLD_CONFIG, "development": 0, "history": 528}, {**WORLD_CONFIG, "total": 527}, {**WORLD_CONFIG, "session_end": "07:00"},
                    {**WORLD_CONFIG, "start_at": "2026-09-09T21:00:00"}):
            with self.assertRaises(ValueError):
                datasets.dataset_config(bad)
        foundation = asdict(Config(total=90))
        self.assertEqual(type(datasets.dataset_config(foundation)), Config)
        self.assertEqual(asdict(datasets.dataset_config(foundation)), foundation)

    def test_operations_never_import_the_world_generator(self):
        import operations.datasets as module
        source = open(module.__file__, encoding="utf-8").read()
        self.assertNotIn("import world", source)
        self.assertNotIn("from world", source)


class BackendSelectionTests(unittest.TestCase):
    def test_an_explicit_world_database_is_accepted_and_others_are_refused(self):
        from backend import operations_api
        with mock.patch.dict(os.environ, {"SUHAIL_OPERATIONS_DATABASE": "shipments-v2-world-1-small"}):
            self.assertEqual(operations_api.operations_database(driver=None), "shipments-v2-world-1-small")
        with mock.patch.dict(os.environ, {"SUHAIL_OPERATIONS_DATABASE": "shipments-v2-demo-live"}):
            self.assertEqual(operations_api.operations_database(driver=None), "shipments-v2-demo-live")
        for name in ("shipments", "neo4j", "shipments-v2-world-", "shipments-v2-other"):
            with mock.patch.dict(os.environ, {"SUHAIL_OPERATIONS_DATABASE": name}):
                with self.assertRaises(RuntimeError):
                    operations_api.operations_database(driver=None)

    def test_no_simulator_is_attached_to_world_data_and_no_truth_file_is_opened(self):
        from backend import operations_api
        store = mock.Mock(live=True, adapter="unset")
        with mock.patch("dataset_v2.live_bundle.read_truth", side_effect=AssertionError("a truth file was opened for world data")), \
             mock.patch("pathlib.Path.read_text", side_effect=AssertionError("a bundle file was opened for world data")):
            self.assertIsNone(operations_api.attach_simulator(store, reader=None, manifest={"dataset_id": "DEMO-SUHAIL-WORLD-1"}))
        self.assertIsNone(store.adapter)


class WorldStoreWithoutSimulatorTests(unittest.TestCase):
    """A store on a mechanism-world dataset has no execution adapter: an authorized action gets no field response,
    nothing is verified and nothing resolves."""

    @classmethod
    def setUpClass(cls):
        cls.world = generate(Config(total=90))

    def test_the_store_runs_as_a_feed_dataset_and_reports_no_adapter(self):
        config = datasets.dataset_config(WORLD_CONFIG)
        driver = Driver(self.world)
        driver.marker = {"state": "COMPLETE", "manifest_json": canonical({"synthetic": True, "dataset_id": config.dataset_id, "config": asdict(config)}),
                         "manifest_hash": digest({"synthetic": True, "dataset_id": config.dataset_id, "config": asdict(config)})}
        store = OperationsStore(driver, "shipments-v2-world-1-small", config.dataset_id, config, Reader(self.world))
        self.assertTrue(store.live)                      # Observations arrive only through the provider gateway.
        self.assertIsInstance(store.gateway, Gateway)
        self.assertIsNone(store.adapter)
        store.initialize()
        status = store.status()
        self.assertEqual(status["execution"], {"adapter": "none", "dataset_kind": "mechanism_world"})
        self.assertEqual(status["as_of"], config.start_at)

    def test_without_an_adapter_an_authorized_action_is_not_acknowledged_and_nothing_resolves(self):
        driver = Driver(self.world)
        store = OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world))
        store.initialize(); development_reset(store)
        for _ in range(12):
            store.tick(seconds=86400, manual=True, speed=60)
            while store.status()["session"]["monitor_pending"]:
                store.monitor_step()
            if any(kind == "OpsCase" for kind, _ in driver.ledger.values()):
                break
        store.agents = agent_investigator()
        with approval_policy():
            result = store.process_one(manual=True)
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-no-adapter")
        self.assertIsNone(store.adapter)
        store.execute_step()
        execution = next(v for k, v in driver.ledger.values() if k == "OpsExecution")
        self.assertEqual((execution["status"], execution["mode"]), ("NOT_ACKNOWLEDGED", "no_adapter"))
        self.assertIn("nothing was sent", json.loads(execution["adapter_result_json"])["behaviour"])
        self.assertEqual(store.outcome_step(limit=10), [])       # Nothing to verify.
        final = store.case_detail(case["case_id"])
        self.assertEqual(final["workflow_state"], "HUMAN_REVIEW")
        self.assertFalse(any(v.get("workflow_state") == "RESOLVED" for k, v in driver.ledger.values() if k == "OpsCase"))
        self.assertEqual([v for k, v in driver.ledger.values() if k == "OpsOutcome"], [])


class Item(dict):
    pass


class RecordingTx:
    """What Gateway._ingest reads and writes, for a list of pending feed items."""

    def __init__(self, items):
        self.items, self.created, self.updated = items, [], []

    def run(self, query, **params):
        tx = self

        class Result(list):
            def single(self_inner):
                return self_inner[0] if self_inner else None

            def consume(self_inner):
                return None
        if query.startswith("MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.deliver_at <= $clock"):
            due = [i for i in tx.items if i["status"] == "PENDING" and instant(i["deliver_at"]) <= params["clock"]]
            return Result([{"f": i} for i in sorted(due, key=lambda i: (i["deliver_at"], i["feed_id"]))[:params["limit"]]])
        if query.startswith("MATCH (n:V2Entity {entity_id:$id}) RETURN n.raw_payload_hash"):
            return Result()
        if query.startswith("CREATE (n:"):
            tx.created.append(params["props"])
            return Result()
        if query.startswith("MATCH (f:ProviderFeedItem {feed_id:$id}) SET"):
            next(i for i in tx.items if i["feed_id"] == params["id"])["status"] = params["status"]
            return Result()
        return Result()   # Relationship merges and back-links: nothing to return.


class DeliveryTimeIngestionTests(unittest.TestCase):
    """A record's recorded_at is the provider's delivery time, not the tick that ingested it; never back-dated."""

    def item(self, key, occurred, deliver):
        payload = {"type": "StatusEvent", "id": f"DEMO-SHP-000001-STATUS-{key}", "shipment": "DEMO-SHP-000001", "at": occurred,
                   "fields": {"status": "IN_TRANSIT"}}
        return {"feed_id": f"DEMO-FEED-{key}", "channel": "SPL_CORE", "provider_id": "DEMO-PROV-SPL", "message_type": "STATUSEVENT",
                "source_event_id": payload["id"], "deliver_at": deliver, "origin": "PROVIDER", "payload_json": json.dumps(payload),
                "payload_hash": digest(payload), "status": "PENDING"}

    def gateway(self):
        from dataset_v2.feed import Reference
        gateway = Gateway(driver=None, database="shipments-v2-demo-ci-test", dataset_id="DEMO-SUHAIL-LIVE-TEST")
        gateway._reference = Reference([], [{"entity_id": "DEMO-SHP-000001", "tracking_id": "SYN1"}])
        gateway._splits = {"DEMO-SHP-000001": "development"}
        return gateway

    def test_recorded_time_rule(self):
        at = instant
        clock = at("2026-09-10T11:00:00+00:00")
        occurred, delivered = at("2026-09-10T10:05:00+00:00"), at("2026-09-10T10:05:40+00:00")
        self.assertEqual(Gateway.recorded_time(delivered, occurred, clock), delivered)             # the provider's delivery time
        self.assertEqual(Gateway.recorded_time(delivered, occurred, clock, floor=at("2026-09-10T10:00:00+00:00")), delivered)
        # A message delivered at or before a clock that was already drained was enqueued late: stamped at this tick.
        self.assertEqual(Gateway.recorded_time(delivered, occurred, clock, floor=at("2026-09-10T10:30:00+00:00")), clock)
        self.assertEqual(Gateway.recorded_time(delivered, occurred, clock, floor=delivered), clock)
        # Never before the event, never after the tick.
        self.assertEqual(Gateway.recorded_time(at("2026-09-10T10:00:00+00:00"), occurred, clock), occurred)
        self.assertEqual(Gateway.recorded_time(None, occurred, clock), clock)
        late = at("2026-09-10T10:59:59+00:00")
        self.assertEqual(Gateway.recorded_time(late, at("2026-09-09T14:00:00+00:00"), clock), late)  # A late upload stays late.

    def test_an_hourly_tick_does_not_make_ordinary_records_look_an_hour_late(self):
        gateway = self.gateway()
        items = [self.item("A", "2026-09-10T10:05:00+00:00", "2026-09-10T10:05:40+00:00"),
                 self.item("B", "2026-09-09T14:00:00+00:00", "2026-09-10T10:40:00+00:00")]   # buffered for 20 hours, then uploaded
        tx = RecordingTx(items)
        clock = instant("2026-09-10T11:00:00+00:00")
        result = gateway._ingest(tx, gateway._reference, clock, 500, None)
        self.assertEqual((result["ingested"], result["rejected"]), (2, 0))
        by_id = {p["entity_id"]: p for p in tx.created}
        ordinary, late = by_id["DEMO-SHP-000001-STATUS-A"], by_id["DEMO-SHP-000001-STATUS-B"]
        self.assertEqual(iso(ordinary["recorded_at"]), "2026-09-10T10:05:40+00:00")
        self.assertEqual(ordinary["ingest_lag_seconds"], 40)
        self.assertEqual(ordinary["ingested_at"], clock.isoformat())                             # The tick is kept, apart.
        self.assertEqual(iso(late["recorded_at"]), "2026-09-10T10:40:00+00:00")
        self.assertGreaterEqual(late["ingest_lag_seconds"], 20 * 3600)                           # Visible as late, never back-dated.
        for props in tx.created:
            self.assertLessEqual(instant(iso(props["occurred_at"])), instant(iso(props["recorded_at"])))
            self.assertLessEqual(instant(iso(props["recorded_at"])), clock)

    def test_a_message_enqueued_late_is_never_recorded_before_a_clock_already_drained(self):
        gateway = self.gateway()
        late = self.item("C", "2026-09-10T10:10:00+00:00", "2026-09-10T10:20:00+00:00")
        tx = RecordingTx([late])
        # The store passes its previous clock: everything delivered by 11:00 had been ingested before this message existed.
        gateway._ingest(tx, gateway._reference, instant("2026-09-10T12:00:00+00:00"), 500, instant("2026-09-10T11:00:00+00:00"))
        self.assertEqual(iso(tx.created[0]["recorded_at"]), "2026-09-10T12:00:00+00:00")
        # A snapshot taken at 11:00 does not gain this record afterwards.
        self.assertGreater(instant(iso(tx.created[0]["recorded_at"])), instant("2026-09-10T11:00:00+00:00"))

    def test_an_event_dated_after_its_receipt_is_still_rejected(self):
        gateway = self.gateway()
        tx = RecordingTx([self.item("D", "2026-09-10T12:30:00+00:00", "2026-09-10T10:20:00+00:00")])
        result = gateway._ingest(tx, gateway._reference, instant("2026-09-10T11:00:00+00:00"), 500, None)
        self.assertEqual((result["ingested"], result["rejected"]), (0, 1))
        self.assertEqual(tx.created, [])

    def test_the_gateway_remembers_the_clocks_it_drained(self):
        gateway = self.gateway()

        class Session:
            def __init__(self, tx): self.tx = tx
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute_write(self, fn): return fn(self.tx)

        tx = RecordingTx([self.item("E", "2026-09-10T10:05:00+00:00", "2026-09-10T10:05:40+00:00")])
        gateway.driver = mock.Mock(session=lambda **kw: Session(tx))
        gateway.ingest_due("2026-09-10T11:00:00+00:00", limit=500)
        self.assertEqual(gateway._drained, instant("2026-09-10T11:00:00+00:00"))
        tx.items.append(self.item("F", "2026-09-10T10:30:00+00:00", "2026-09-10T10:45:00+00:00"))   # enqueued after that drain
        gateway.ingest_due("2026-09-10T12:00:00+00:00", limit=500)
        self.assertEqual(iso(tx.created[-1]["recorded_at"]), "2026-09-10T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
