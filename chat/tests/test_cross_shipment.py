"""The fixed cross-shipment evidence queries: read-only, bounded, scoped, time-correct, and never model-supplied.

No database. The catalogue's Cypher is checked as text and through the read model with a recording driver; its
semantics are exercised through the in-memory reference port (tests/world_fixture.MemoryPort), which the Neo4j
integration tests compare the real queries against.
"""
import re
import unittest

from dataset_v2.contracts import instant
from operations import cross_shipment
from operations.cross_shipment import QUERIES, clean_params, in_scope, visible
from operations.datasets import dataset_config
from operations.read_model import OperationsReader
from tests.test_operations_read_model import Driver
from tests.test_stage2_datasets import WORLD_CONFIG
from tests.world_fixture import MemoryPort, small_world

AS_OF = "2026-09-20T12:00:00+00:00"
SAMPLE = {"ref": "DEMO-DEV-HH-DEPOT-RUH-N", "shipment_id": "DEMO-SHP-000001", "text": "OP-1", "from_at": "2026-09-19T12:00:00+00:00",
          "to_at": "2026-09-20T12:00:00+00:00", "late_seconds": 3600, "allowance": 900, "shipment_ids": ["DEMO-SHP-000001", "DEMO-SHP-000002"]}


def params_for(name, **override):
    spec = QUERIES[name]
    keys = (*spec.ids, *spec.times, *spec.numbers, *spec.texts, *spec.id_lists)
    return {"as_of": AS_OF, **{k: SAMPLE[k] for k in keys}, **override}


class CatalogueTests(unittest.TestCase):
    def test_the_time_correct_predicate_is_the_world_packages(self):
        from world.export import visible as world_visible
        for alias in ("n", "e", "m"):
            self.assertEqual(visible(alias), world_visible(alias))

    def test_every_query_is_read_only_scoped_time_correct_and_bounded(self):
        banned = re.compile(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|LOAD|CALL|FOREACH|DETACH)\b", re.I)
        for name, spec in QUERIES.items():
            cypher = spec.cypher
            self.assertIsNone(banned.search(cypher), name)
            self.assertTrue(cypher.startswith("MATCH ("), name)
            # Every node the query matches is filtered by scope and by the snapshot.
            aliases = re.findall(r"\((\w+):V2Entity", cypher)
            self.assertTrue(aliases, name)
            for alias in set(aliases):
                self.assertIn(in_scope(alias), cypher, (name, alias))
                recorded = f"{alias}.recorded_at <= $as_of"
                self.assertIn(recorded, cypher, (name, alias))
                if alias != "p" and name not in ("overdue_at_facility", "overdue_at_facility_counts") or alias == "e":
                    self.assertIn(visible(alias), cypher, (name, alias))
            self.assertNotIn("held_out", cypher, name)
            self.assertTrue(cypher.rstrip().endswith("LIMIT $limit"), name)
            self.assertLessEqual(spec.limit, cross_shipment.MAX_LIMIT, name)
            # Parameters only: no string formatting of caller values is possible, and every $name is declared.
            used = set(re.findall(r"\$(\w+)", cypher))
            declared = {"as_of", "dataset_id", "limit", "kinds", *spec.ids, *spec.times, *spec.numbers, *spec.texts, *spec.id_lists}
            self.assertLessEqual(used, declared, name)

    def test_parameters_are_validated_and_limits_clamped(self):
        clock = "2026-09-21T00:00:00+00:00"
        cleaned = clean_params("device_heartbeats", params_for("device_heartbeats", limit=10_000), clock)
        self.assertEqual(cleaned["limit"], QUERIES["device_heartbeats"].limit)
        self.assertEqual(clean_params("shared_record", params_for("shared_record"), clock)["kinds"], list(cross_shipment.SHARED_KINDS))
        bad = [("nope", {"as_of": AS_OF}), ("shared_record", {"as_of": AS_OF}), ("shared_record", params_for("shared_record", ref="SHP-1")),
               ("shared_record", params_for("shared_record", ref="DEMO-" + "x" * 200)), ("shared_record", params_for("shared_record", extra=1)),
               ("shared_record", params_for("shared_record", limit=0)), ("shared_record", {"as_of": "2026-09-22T00:00:00+00:00", "ref": "DEMO-X"}),
               ("device_heartbeats", params_for("device_heartbeats", to_at="2026-09-20T13:00:00+00:00")),      # a window ahead of the snapshot
               ("device_heartbeats", params_for("device_heartbeats", from_at="yesterday")),
               ("device_scan_counts", params_for("device_scan_counts", late_seconds=-1)),
               ("device_scan_counts", params_for("device_scan_counts", late_seconds="3600")),
               ("package_by_barcode", params_for("package_by_barcode", text="")),
               ("package_by_barcode", params_for("package_by_barcode", text="x" * 200)),
               ("last_custody", params_for("last_custody", shipment_ids=[])),
               ("last_custody", params_for("last_custody", shipment_ids=["DEMO-A"] * 61)),
               ("last_custody", params_for("last_custody", shipment_ids=["MATCH (n) DETACH DELETE n"]))]
        for name, params in bad:
            with self.assertRaises(ValueError, msg=(name, params)):
                clean_params(name, params, clock)

    def test_the_reader_runs_only_catalogue_queries_with_cleaned_parameters_in_a_read_session(self):
        driver = Driver(lambda query, params: [])
        reader = OperationsReader(driver, "shipments-v2-world-1-small", "DEMO-SUHAIL-WORLD-1", dataset_config(WORLD_CONFIG),
                                  clock=lambda: "2026-09-21T00:00:00+00:00")
        for name in QUERIES:
            self.assertEqual(reader.fetch(name, **params_for(name)), [])
        self.assertEqual(len(driver.calls), len(QUERIES))
        for (query, params), name in zip(driver.calls, QUERIES):
            self.assertEqual(query, QUERIES[name].cypher)
            self.assertEqual(params["dataset_id"], "DEMO-SUHAIL-WORLD-1")
            self.assertEqual(params["as_of"], instant(AS_OF))                 # Typed for Neo4j temporal comparison.
            self.assertLessEqual(params["limit"], QUERIES[name].limit)
        self.assertTrue(all(o == {"database": "shipments-v2-world-1-small", "default_access_mode": "READ"} for o in driver.sessions))
        with self.assertRaises(ValueError):                                   # A snapshot ahead of the logical clock.
            reader.fetch("shared_record", ref="DEMO-X", as_of="2026-09-22T00:00:00+00:00")
        with self.assertRaises(ValueError):                                   # No free-form Cypher.
            reader.fetch("MATCH (n) RETURN n", as_of=AS_OF)

    def test_the_in_memory_reference_implements_every_query(self):
        self.assertEqual({name for name in QUERIES}, {name[1:] for name in vars(MemoryPort) if name.startswith("_") and name[1:] in QUERIES})


class ReferencePortTests(unittest.TestCase):
    """Semantics of the queries on real world records (through the in-memory reference)."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = small_world()
        cls.world = cls.fixture.world
        cls.port = MemoryPort(cls.world)
        cls.end = cls.world.config.as_of

    def scan(self, **match):
        return next(n for n in sorted(self.world.of_kind("ScanEvent"), key=lambda n: n.id)
                    if all(n.properties.get(k) is not None if v is True else n.properties.get(k) == v for k, v in match.items()))

    def test_no_query_returns_a_record_from_after_the_snapshot_or_a_held_out_split(self):
        middle = "2026-09-15T12:00:00+00:00"
        route = self.scan(route_run_id=True).properties["route_run_id"]
        trip = self.scan(trip_id=True).properties["trip_id"]
        container = self.scan(container_id=True).properties["container_id"]
        device = self.scan(observation_type="HANDHELD_RECEIPT").properties["device_ref"]
        facility = self.world.nodes[device].properties["facility_id"]
        window = {"from_at": "2026-09-13T12:00:00+00:00", "to_at": middle}
        calls = [("shared_record", {"ref": route}), ("shared_record", {"ref": trip}), ("facility_devices", {"ref": facility}),
                 ("device_heartbeats", {"ref": device, **window}), ("device_scans", {"ref": device, **window}),
                 ("device_scan_counts", {"ref": device, **window, "late_seconds": 3600}),
                 ("device_late_scans", {"ref": device, **window, "late_seconds": 60}),
                 ("device_measurements", {"ref": device, **window}),
                 ("overdue_at_facility", {"ref": facility, "shipment_id": "DEMO-SHP-NONE", "from_at": window["from_at"], "allowance": 900}),
                 ("facility_throughput", {"ref": facility, **window}), ("facility_custody_counts", {"ref": facility, **window}),
                 ("route_run_assignments", {"ref": route}), ("route_run_custody", {"ref": route}), ("route_run_attempts", {"ref": route}),
                 ("route_run_scans", {"ref": route}), ("route_run_reconciliations", {"ref": route}), ("route_run_manifests", {"ref": route}),
                 ("container_scans", {"ref": container}), ("trip_events", {"ref": trip}), ("trip_positions", {"ref": trip}),
                 ("trip_custody", {"ref": trip}), ("trip_containers", {"ref": trip})]
        cutoff = instant(middle)
        seen = 0
        for name, params in calls:
            for row in self.port.fetch(name, as_of=middle, **params):
                props = row.get("props", row)
                seen += 1
                for field in ("recorded_at", "occurred_at", "latest_recorded_at"):
                    if props.get(field):
                        self.assertLessEqual(instant(props[field]), cutoff, (name, field, props.get("entity_id")))
                if props.get("split"):
                    self.assertIn(props["split"], ("development", "history", "shared"), name)
        self.assertGreater(seen, 20)
        # The same questions asked later return at least as much; nothing visible at the snapshot disappears.
        for name, params in calls[11:17]:
            earlier = {r["props"]["entity_id"] for r in self.port.fetch(name, as_of=middle, **params)}
            later = {r["props"]["entity_id"] for r in self.port.fetch(name, as_of=self.end, **params)}
            self.assertLessEqual(earlier, later, name)

    def test_a_route_run_query_returns_other_shipments_parcels(self):
        route = self.scan(route_run_id=True).properties["route_run_id"]
        rows = self.port.fetch("route_run_assignments", ref=route, as_of=self.end)
        self.assertGreater(len({r["props"]["shipment_id"] for r in rows}), 1)
        self.assertTrue(all(r["props"]["route_run_id"] == route for r in rows))

    def test_overdue_at_a_facility_counts_only_steps_with_no_custody_record_by_the_snapshot(self):
        device = self.scan(observation_type="HANDHELD_RECEIPT", trip_id=True).properties["device_ref"]
        facility = self.world.nodes[device].properties["facility_id"]
        as_of = "2026-09-16T12:00:00+00:00"
        params = {"ref": facility, "shipment_id": "DEMO-SHP-NONE", "from_at": "2026-09-10T00:00:00+00:00", "allowance": 900, "as_of": as_of}
        rows = self.port.fetch("overdue_at_facility", limit=20, **params)
        counts = self.port.fetch("overdue_at_facility_counts", **params)
        self.assertEqual(sum(c["milestones"] for c in counts) >= len(rows), True)
        cutoff = instant(as_of)
        for row in rows:
            milestone = self.world.nodes[row["milestone_id"]].properties
            self.assertLess(instant(milestone["latest_at"]), cutoff)
            self.assertFalse(any(n.kind == "CustodyEvent" and n.properties.get("package_id") == row["package_id"]
                                 and n.properties.get("event_type") == row["predicate"] and n.properties.get("facility_id") == facility
                                 and instant(n.properties["recorded_at"]) <= cutoff for n in self.world.owned(row["shipment_id"])))


if __name__ == "__main__":
    unittest.main()
