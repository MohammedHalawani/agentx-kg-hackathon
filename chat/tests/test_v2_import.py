"""Loader boundary tests: no sockets, providers, credentials or actual databases.

Small envelope fixtures isolate importer behavior; full evidence-domain validation is
owned/tested by dataset_v2.validate and is invoked (never replaced) by the real CLI.
"""
import copy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dataset_v2.contracts import Config, World, canonical, digest
from dataset_v2 import load


def fixture():
    world = World(Config(total=30))
    world.node("City", "DEMO-CITY-1", name="Test")
    world.node("Shipment", "DEMO-SHP-1", shipment_id="DEMO-SHP-1", split="held_out")
    world.node("Package", "DEMO-PKG-1", shipment_id="DEMO-SHP-1", split="held_out", weight_kg=1.2)
    world.edge("DEMO-SHP-1", "HAS_PACKAGE", "DEMO-PKG-1")
    world.gold["DEMO-SHP-1"] = {"shipment_id": "DEMO-SHP-1", "recipe_id": "PRIVATE-GOLD-SENTINEL"}
    validation = {"pass": True, "errors": [], "checks": {"unit_envelope": True},
                  "statistics": {"nodes": 3}}
    return load.Bundle(world, world.manifest(), digest(world.manifest()), validation)


def write_fixture(path, bundle):
    for name, records in (("nodes", [node.record() for node in bundle.world.nodes.values()]),
                          ("edges", [edge.record() for edge in bundle.world.edges.values()]),
                          ("gold", list(bundle.world.gold.values()))):
        (path / f"{name}.jsonl").write_text("".join(canonical(row) + "\n" for row in records), encoding="utf-8")
    for name, value in (("manifest", bundle.manifest), ("validation", bundle.validation),
                        ("statistics", bundle.validation["statistics"])):
        (path / f"{name}.json").write_text(canonical(value), encoding="utf-8")


class Result(list):
    def __init__(self, rows=(), *, nodes_created=0, relationships_created=0):
        super().__init__(rows)
        self.counters = SimpleNamespace(nodes_created=nodes_created, relationships_created=relationships_created)
    def single(self):
        return self[0] if self else None

    def consume(self):
        return self


class Transaction:
    def __init__(self, driver, store):
        self.driver, self.store = driver, store

    def run(self, query, **parameters):
        self.driver.queries.append((query, parameters))
        if query.startswith("MATCH (m:_V2Import)"):
            return Result(self.store["markers"])
        if query == "MATCH (n) RETURN count(n) AS count":
            return Result([{"count": len(self.store["nodes"]) + len(self.store["markers"])}])
        if query.startswith("SHOW INDEXES"):
            return Result(self.driver.indexes)
        if query.startswith("SHOW CONSTRAINTS"):
            return Result(self.driver.constraints)
        if query.startswith("CREATE (m:_V2Import)"):
            self.store["markers"].append({"labels": ["_V2Import"], "props": parameters["props"]})
        elif query.startswith("UNWIND") and "CREATE (n:" in query:
            labels = query.split("CREATE (n:")[1].split(")")[0].split(":")
            self.store["nodes"].extend({"labels": labels, "props": row["props"]} for row in parameters["rows"])
        elif query.startswith("UNWIND") and "MERGE (a)-[r:" in query:
            self.driver.edge_calls += 1
            if self.driver.fail_edges or self.driver.edge_calls == self.driver.fail_edge_call:
                raise RuntimeError("injected edge transaction failure")
            kind = query.split("MERGE (a)-[r:")[1].split(" ")[0]
            fresh = [row for row in parameters["rows"] if not any(existing["props"]["edge_id"] == row["props"]["edge_id"]
                     and existing["start"] == row["start"] and existing["end"] == row["end"]
                     for existing in self.store["edges"])]
            self.store["edges"].extend({"kind": kind, **row} for row in fresh)
            return Result(relationships_created=len(fresh))
        elif query.startswith("MATCH (m:_V2Import {id:$id}) SET m.state="):
            self.store["markers"][0]["props"]["state"] = "COMPLETE"
        elif query.startswith("MATCH (n) WHERE NOT n:_V2Import"):
            return Result(self.store["nodes"])
        elif query.startswith("MATCH (a)-[r]->(b)"):
            return Result(self.store["edges"])
        else:
            raise AssertionError("Unexpected transaction query: " + query)
        return Result(nodes_created=len(parameters.get("rows", [])) if "CREATE (n:" in query else 0)


class Session:
    def __init__(self, driver, database):
        self.driver, self.database = driver, database

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, **parameters):
        self.driver.queries.append((query, parameters))
        if query.startswith("CALL dbms.components"):
            return Result([{"edition": self.driver.edition, "versions": ["2026.09.0"]}])
        if query.startswith("SHOW DATABASES"):
            return Result(self.driver.databases)
        if query.startswith("CREATE DATABASE"):
            self.driver.databases.append({"name": load.DEFAULT_DATABASE, "aliases": [], "default": False,
                                          "home": False, "type": "standard", "currentStatus": "online"})
        elif query.startswith(("CREATE CONSTRAINT", "CREATE INDEX")):
            name = query.split()[2]
            labels, properties = {
                "v2_entity_id": (["V2Entity"], ["entity_id"]),
                "v2_manifest_id": (["_V2Import"], ["id"]),
                "v2_holdout": (["V2Entity"], ["holdout_group"]),
                "v2_split": (["V2Entity"], ["split"])}[name]
            is_constraint = query.startswith("CREATE CONSTRAINT")
            if not any(row["name"] == name for row in self.driver.indexes):
                self.driver.indexes.append({"name": name, "type": "RANGE", "entityType": "NODE",
                    "labelsOrTypes": labels, "properties": properties,
                    "owningConstraint": name if is_constraint else None})
            if is_constraint and not any(row["name"] == name for row in self.driver.constraints):
                self.driver.constraints.append({"name": name, "type": "UNIQUENESS", "entityType": "NODE",
                                               "labelsOrTypes": labels, "properties": properties})
        else:
            raise AssertionError("Unexpected autocommit query: " + query)
        return Result()

    def execute_read(self, fn, *args):
        return fn(Transaction(self.driver, self.driver.store), *args)

    def execute_write(self, fn, *args, **kwargs):
        self.driver.write_transactions += 1
        candidate = copy.deepcopy(self.driver.store)
        result = fn(Transaction(self.driver, candidate), *args, **kwargs)
        self.driver.store = candidate  # Commit only if all writes and verification succeed.
        return result


class Driver:
    def __init__(self):
        self.store = {"nodes": [], "edges": [], "markers": []}
        self.queries, self.sessions, self.indexes, self.constraints = [], [], [], []
        self.edition, self.fail_edges = "enterprise", False
        self.edge_calls, self.fail_edge_call, self.write_transactions = 0, None, 0
        self.databases = [{"name": name, "aliases": [], "default": name == "neo4j", "home": False,
                           "type": "system" if name == "system" else "standard", "currentStatus": "online"}
                          for name in ("neo4j", "shipments", "system")]

    def session(self, *, database, **kwargs):
        self.sessions.append(database)
        return Session(self, database)


class V2ImportTests(unittest.TestCase):
    def apply(self, driver, bundle=None, **kwargs):
        return load.apply_bundle(driver, bundle or fixture(), uri="bolt://localhost:7687",
                                 database=load.DEFAULT_DATABASE, protected=("shipments", "neo4j", "chat"), **kwargs)

    def test_canonical_hashes_are_order_independent_and_domain_recomputed(self):
        bundle = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_fixture(path, bundle)
            lines = (path / "nodes.jsonl").read_text().splitlines()
            (path / "nodes.jsonl").write_text("\n".join(reversed(lines)), encoding="utf-8")
            calls = []
            loaded = load.read_bundle(path, validator=lambda world: calls.append(world) or bundle.validation)
            self.assertEqual(loaded.manifest_hash, bundle.manifest_hash)
            self.assertEqual(len(calls), 1)
            self.assertIsInstance(calls[0], World)
            with self.assertRaises(load.ImportRefused):
                load.read_bundle(path, validator=lambda _: {"pass": False, "errors": ["domain-invalid"]})

    def test_changed_content_and_forged_pass_report_refused(self):
        bundle = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_fixture(path, bundle)
            with self.assertRaises(load.ImportRefused):
                load.read_bundle(path, validator=lambda _: {**bundle.validation, "checks": {}})
            (path / "statistics.json").write_text("{}")
            with self.assertRaises(load.ImportRefused):
                load.read_bundle(path, validator=lambda _: bundle.validation)
            write_fixture(path, bundle)
            rows = [json.loads(line) for line in (path / "nodes.jsonl").read_text().splitlines()]
            rows[0]["properties"]["name"] = "altered"
            (path / "nodes.jsonl").write_text("\n".join(canonical(row) for row in rows), encoding="utf-8")
            with self.assertRaises(load.ImportRefused):
                load.read_bundle(path, validator=lambda _: bundle.validation)

    def test_duplicate_identity_and_dangling_edge_refused(self):
        bundle = fixture()
        for name in ("nodes", "edges"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                write_fixture(path, bundle)
                content = (path / f"{name}.jsonl").read_text()
                if name == "nodes":
                    content += content.splitlines()[0] + "\n"
                else:
                    row = json.loads(content)
                    row["end"] = "DEMO-NONEXISTENT"
                    content = canonical(row)
                (path / f"{name}.jsonl").write_text(content, encoding="utf-8")
                with self.assertRaises(load.ImportRefused):
                    load.read_bundle(path, validator=lambda _: bundle.validation)

    def test_dry_run_never_imports_config_or_constructs_driver(self):
        import sys
        from types import ModuleType
        sentinel = ModuleType("config")
        def forbidden(name):
            raise AssertionError("Dry-run accessed live configuration")
        sentinel.__getattr__ = forbidden
        with patch.object(load, "read_bundle", return_value=fixture()), patch.dict(sys.modules, {"config": sentinel}), \
                patch("sys.stdout", new_callable=io.StringIO) as stdout:
            load.main(["unused-export-directory"])
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "dry_run")
        self.assertFalse(report["gold_imported"])

    def test_database_and_endpoint_fences_before_any_driver_call(self):
        invalid = [("bolt://example.com:7687", load.DEFAULT_DATABASE),
                   ("neo4j://localhost:7687", load.DEFAULT_DATABASE),
                   ("bolt://user:pass@localhost:7687", load.DEFAULT_DATABASE),
                   ("bolt://localhost:9999", load.DEFAULT_DATABASE),
                   ("bolt://localhost:7687/path", load.DEFAULT_DATABASE),
                   ("bolt://localhost:7687", "shipments_v2_demo"),
                   ("bolt://localhost:7687", "neo4j"),
                   ("bolt://localhost:7687", "shipments"),
                   ("bolt://localhost:7687", "system"),
                   ("bolt://localhost:7687", "shipments-v2-active")]
        for uri, target in invalid:
            driver = Driver()
            with self.subTest(uri=uri, target=target), self.assertRaises(load.ImportRefused):
                load.apply_bundle(driver, fixture(), uri=uri, database=target,
                                  protected=("shipments", "shipments-v2-active"))
            self.assertEqual(driver.sessions, [])

    def test_enterprise_verified_before_create(self):
        driver = Driver()
        driver.edition = "community"
        with self.assertRaises(load.ImportRefused):
            self.apply(driver)
        self.assertFalse(any(query.startswith("CREATE") for query, _ in driver.queries))
        self.assertEqual(driver.sessions, ["system"])

    def test_alias_and_home_database_refused(self):
        for row in ({"name": "shipments", "aliases": [load.DEFAULT_DATABASE]},
                    {"name": load.DEFAULT_DATABASE, "aliases": [], "home": True, "type": "standard",
                     "currentStatus": "online"}):
            driver = Driver()
            driver.databases.append(row)
            with self.assertRaises(load.ImportRefused):
                self.apply(driver)
            self.assertFalse(any(query.startswith("CREATE") for query, _ in driver.queries))

    def test_checkpoint_import_typed_utc_and_gold_never_sent_to_database(self):
        driver = Driver()
        report = self.apply(driver)
        self.assertEqual((report["added_nodes"], report["added_entities"], report["added_edges"]), (4, 3, 1))
        self.assertTrue(all(isinstance(row["props"]["recorded_at"], datetime) for row in driver.store["nodes"]))
        self.assertTrue(all(row["props"]["recorded_at"].utcoffset().total_seconds() == 0
                            for row in driver.store["nodes"]))
        self.assertNotIn("PRIVATE-GOLD-SENTINEL", str(driver.queries))
        self.assertTrue(set(driver.sessions) <= {"system", load.DEFAULT_DATABASE})
        self.assertFalse(any("DELETE" in query or "DROP" in query for query, _ in driver.queries))

    def test_exact_replay_adds_no_objects_and_no_data_writes(self):
        driver = Driver()
        self.apply(driver)
        before = copy.deepcopy(driver.store)
        offset = len(driver.queries)
        report = self.apply(driver)
        self.assertEqual(report["status"], "identical_replay")
        self.assertEqual((report["added_nodes"], report["added_edges"]), (0, 0))
        self.assertEqual(driver.store, before)
        self.assertFalse(any(query.startswith(("UNWIND", "CREATE (")) for query, _ in driver.queries[offset:]))

    def test_interrupted_checkpoint_remains_loading_and_resumes_without_duplicates(self):
        driver = Driver()
        driver.fail_edges = True
        report = self.apply(driver)
        self.assertEqual(report["status"], "resumable_incomplete")
        self.assertEqual(driver.store["markers"][0]["props"]["state"], "LOADING")
        self.assertEqual(len(driver.store["nodes"]), 3)
        self.assertEqual(len(driver.store["edges"]), 0)
        driver.fail_edges = False
        resumed = self.apply(driver)
        self.assertEqual(resumed["status"], "resumed")
        self.assertEqual((resumed["added_nodes"], resumed["added_edges"]), (0, 1))
        self.assertEqual(driver.store["markers"][0]["props"]["state"], "COMPLETE")
        self.assertEqual(len(driver.store["nodes"]), 3)
        self.assertEqual(self.apply(driver)["status"], "identical_replay")

    def test_sorted_bounded_checkpoint_batches_resume_late_failure(self):
        original = fixture()
        world = original.world
        for index in reversed(range(1001)):
            identifier = f"DEMO-CITY-BATCH-{index:04d}"
            world.node("City", identifier)
            world.edge("DEMO-CITY-1", "IN_CITY", identifier)
        bundle = load.Bundle(world, world.manifest(), digest(world.manifest()), original.validation)
        driver = Driver()
        self.apply(driver, bundle)
        writes = [(query, parameters["rows"]) for query, parameters in driver.queries if query.startswith("UNWIND")]
        self.assertEqual(driver.write_transactions, len(writes) + 2)  # LOADING + batches + COMPLETE.
        self.assertEqual(max(len(rows) for _, rows in writes), 1000)
        by_query = {}
        for query, rows in writes:
            key = "entity_id" if "CREATE (n:" in query else "edge_id"
            by_query.setdefault(query, []).extend(row["props"][key] for row in rows)
        self.assertTrue(all(ids == sorted(ids) for ids in by_query.values()))
        late_failure = Driver()
        late_failure.fail_edge_call = 3  # After all node batches and 1001 prior edges.
        interrupted = self.apply(late_failure, bundle)
        self.assertEqual(interrupted["status"], "resumable_incomplete")
        self.assertEqual(len(late_failure.store["nodes"]), len(world.nodes))
        self.assertEqual(len(late_failure.store["edges"]), 1001)
        self.assertEqual(late_failure.store["markers"][0]["props"]["state"], "LOADING")
        late_failure.fail_edge_call = None
        resumed = self.apply(late_failure, bundle)
        self.assertEqual((resumed["added_nodes"], resumed["added_edges"]), (0, 1))
        self.assertEqual(len(late_failure.store["edges"]), len(world.edges))

    def test_loading_tamper_and_manifest_mismatch_refused_and_recovery_is_unavailable(self):
        for corruption in ("foreign", "property", "manifest"):
            driver = Driver()
            driver.fail_edges = True
            self.apply(driver)
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(load.ImportRefused):
                load.export_target(driver, fixture(), Path(directory) / "recovery",
                    uri="bolt://localhost:7687", database=load.DEFAULT_DATABASE)
            if corruption == "foreign":
                driver.store["nodes"].append({"labels": ["Foreign"], "props": {}})
            elif corruption == "property":
                driver.store["nodes"][0]["props"]["name"] = "tampered"
            else:
                driver.store["markers"][0]["props"]["manifest_hash"] = "wrong"
            offset = len(driver.queries)
            with self.subTest(corruption=corruption), self.assertRaises(load.ImportRefused):
                self.apply(driver)
            self.assertFalse(any(query.startswith(("CREATE", "UNWIND")) for query, _ in driver.queries[offset:]))

    def test_complete_replay_preserves_only_registered_development_operations(self):
        bundle = fixture()
        bundle.world.nodes["DEMO-SHP-1"].properties["split"] = "development"
        bundle = load.Bundle(bundle.world, bundle.world.manifest(), digest(bundle.world.manifest()), bundle.validation)
        for corruption in (None, "unknown", "foreign_owner", "foreign_field", "unregistered_edge"):
            with self.subTest(corruption=corruption):
                driver = Driver()
                self.apply(driver, bundle)
                props = {"entity_id": "DEMO-OPS-CASE-1", "dataset_id": bundle.world.config.dataset_id,
                         "synthetic": True, "split": "development", "shipment_id": "DEMO-SHP-1",
                         "holdout_group": "DEMO-SHP-1", "recorded_at": load.instant(bundle.world.config.start_at),
                         "workflow_state": "OPEN", "state_version": 0}
                labels = ["OpsEntity", "OpsCase"]
                if corruption == "unknown": labels[1] = "OpsUnknown"
                if corruption == "foreign_owner": props["shipment_id"] = "DEMO-FOREIGN"
                if corruption == "foreign_field": props["raw_reasoning"] = "forbidden"
                driver.store["nodes"].append({"labels": labels, "props": props})
                driver.store["edges"].append({"kind": "OPS_FORGED" if corruption == "unregistered_edge" else "OPS_ABOUT",
                    "start": props["entity_id"], "end": "DEMO-SHP-1", "props": {
                        "edge_id": "DEMO-OPS-EDGE-1", "dataset_id": bundle.world.config.dataset_id,
                        "synthetic": True, "split": "development", "shipment_id": "DEMO-SHP-1", "holdout_group": "DEMO-SHP-1"}})
                if corruption:
                    with self.assertRaises(load.ImportRefused): self.apply(driver, bundle)
                else:
                    before = copy.deepcopy(driver.store)
                    self.assertEqual(self.apply(driver, bundle)["status"], "identical_replay")
                    self.assertEqual(driver.store, before)

    def test_loading_import_cannot_host_operations(self):
        driver, bundle = Driver(), fixture()
        driver.fail_edges = True
        self.apply(driver, bundle)
        driver.store["nodes"].append({"labels": ["OpsEntity", "OpsControl"], "props": {
            "entity_id": "DEMO-OPS-CONTROL", "dataset_id": bundle.world.config.dataset_id,
            "synthetic": True, "split": "development", "recorded_at": load.instant(bundle.world.config.start_at)}})
        with self.assertRaises(load.ImportRefused): self.apply(driver, bundle)

    def test_corrupt_property_or_extra_object_refused_even_with_record_hash_unchanged(self):
        for corruption in ("property", "extra", "topology", "marker", "untyped_timestamp", "scalar_type"):
            with self.subTest(corruption=corruption):
                driver = Driver()
                self.apply(driver)
                if corruption == "property":
                    driver.store["nodes"][0]["props"]["name"] = "tampered"
                elif corruption == "extra":
                    driver.store["nodes"].append({"labels": ["Foreign"], "props": {}})
                elif corruption == "topology":
                    driver.store["edges"][0]["end"] = "DEMO-CITY-1"
                elif corruption == "untyped_timestamp":
                    driver.store["nodes"][0]["props"]["recorded_at"] = fixture().world.config.start_at
                elif corruption == "scalar_type":
                    driver.store["nodes"][0]["props"]["synthetic"] = 1
                else:
                    driver.store["markers"][0]["props"]["state"] = "INCOMPLETE"
                offset = len(driver.queries)
                with self.assertRaises(load.ImportRefused):
                    self.apply(driver)
                self.assertFalse(any(query.startswith("CREATE") for query, _ in driver.queries[offset:]))

    def test_foreign_content_or_schema_refused_before_ddl(self):
        for foreign in ("node", "index", "constraint", "reserved_index_wrong_definition", "nonunique_manifest_index"):
            driver = Driver()
            if foreign == "node":
                driver.store["nodes"].append({"labels": ["Foreign"], "props": {}})
            elif foreign == "index":
                driver.indexes.append({"name": "foreign", "type": "RANGE", "labelsOrTypes": ["Foreign"],
                                       "properties": ["id"]})
            elif foreign == "constraint":
                driver.constraints.append({"name": "foreign", "type": "UNIQUENESS",
                                           "labelsOrTypes": ["Foreign"], "properties": ["id"]})
            elif foreign == "reserved_index_wrong_definition":
                driver.indexes.append({"name": "v2_manifest_id", "type": "RANGE", "labelsOrTypes": ["Foreign"],
                                       "properties": ["id"]})
            else:
                driver.indexes.append({"name": "v2_manifest_id", "type": "RANGE", "entityType": "NODE",
                                       "labelsOrTypes": ["_V2Import"], "properties": ["id"],
                                       "owningConstraint": None})
            with self.subTest(foreign=foreign), self.assertRaises(load.ImportRefused):
                self.apply(driver)
            self.assertFalse(any(query.startswith(("CREATE CONSTRAINT", "CREATE INDEX", "CREATE ("))
                                 for query, _ in driver.queries))

    def test_existing_compatible_schema_permits_replay(self):
        for constraint_type in ("UNIQUENESS", "NODE_PROPERTY_UNIQUENESS"):
            with self.subTest(constraint_type=constraint_type):
                driver = Driver()
                self.apply(driver)
                for row in driver.constraints:
                    row["type"] = constraint_type
                driver.indexes.append({"name": "node_lookup", "type": "LOOKUP"})
                self.assertEqual(self.apply(driver)["status"], "identical_replay")

    def test_completed_target_missing_schema_is_refused(self):
        for missing in ("constraint", "index"):
            driver = Driver()
            self.apply(driver)
            if missing == "constraint":
                driver.constraints.clear()
            else:
                driver.indexes = [row for row in driver.indexes if row["name"] != "v2_split"]
            offset = len(driver.queries)
            with self.subTest(missing=missing), self.assertRaises(load.ImportRefused):
                self.apply(driver)
            self.assertFalse(any(query.startswith("CREATE") for query, _ in driver.queries[offset:]))

    def test_in_memory_bundle_mutation_refused_before_driver(self):
        bundle, driver = fixture(), Driver()
        bundle.world.nodes["DEMO-CITY-1"].properties["name"] = "altered"
        with self.assertRaises(load.ImportRefused):
            self.apply(driver, bundle)
        self.assertEqual(driver.sessions, [])

    def test_property_types_refuse_lossy_or_untyped_values(self):
        for value in ({"occurred_at": "2026-01-01T03:00:00+03:00"}, {"metadata": {"x": 1}},
                      {"items": [1, "two"]}, {"items": [None]}, {"x": float("nan")},
                      {"x": 2 ** 63}, {"_v2_record_hash": "forged"}):
            with self.subTest(value=value), self.assertRaises((ValueError, load.ImportRefused)):
                load._properties(value)

    def test_recovery_export_is_read_only_and_refuses_existing_destination(self):
        driver, bundle = Driver(), fixture()
        self.apply(driver, bundle)
        before = copy.deepcopy(driver.store)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "recovery"
            offset = len(driver.queries)
            load.export_target(driver, bundle, destination, uri="bolt://localhost:7687", database=load.DEFAULT_DATABASE)
            self.assertEqual(driver.store, before)
            self.assertFalse(any(query.startswith(("CREATE", "UNWIND")) for query, _ in driver.queries[offset:]))
            self.assertFalse((destination / "gold.jsonl").exists())
            self.assertEqual(json.loads((destination / "recovery.json").read_text())["gold_included"], False)
            with self.assertRaises(load.ImportRefused):
                load.export_target(driver, bundle, destination, uri="bolt://localhost:7687", database=load.DEFAULT_DATABASE)


if __name__ == "__main__":
    unittest.main()
