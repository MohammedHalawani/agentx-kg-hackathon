"""Validate a frozen export offline; explicitly apply only to an isolated local V2 DB.

Bounded transactions populate an isolated LOADING shadow. Only full verification can
publish its COMPLETE marker; interrupted imports resume the same immutable manifest.
Gold is validated offline and is never passed to a Neo4j transaction.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from dataset_v2.contracts import (ALIASES, Config, Edge, KINDS, Node, RELATIONSHIPS,
                                  SCHEMA_VERSION, UTC_FIELDS, World, canonical, digest, instant)

DEFAULT_DATABASE = "shipments-v2-demo"
LOADER_VERSION = "checkpoint-v2-2"
BATCH_SIZE = 1000
MARKER_ID = "DEMO-V2-IMPORT"
INSPECT_QUERIES = {
    "manifest": "MATCH (m:_V2Import) RETURN m",
    "kinds": "MATCH (n:V2Entity) RETURN labels(n) AS labels,count(*) AS count ORDER BY labels",
    "splits": "MATCH (s:Shipment) RETURN s.split AS split,count(*) AS count ORDER BY split",
    "journey": "MATCH (s:Shipment {entity_id:$shipment_id})-[:HAS_PACKAGE]->(p:Package) "
               "RETURN s,p LIMIT 20",
    "shipment_evidence": "MATCH (n:V2Entity {holdout_group:$shipment_id}) RETURN n LIMIT 200",
    "shipment_links": "MATCH (a:V2Entity {holdout_group:$shipment_id})-[r]->(b) RETURN a,r,b LIMIT 200",
    "cases": "MATCH (c:Case) RETURN c LIMIT 20",
    "outcomes": "MATCH (o:Outcome) RETURN o LIMIT 20",
}


class ImportRefused(ValueError):
    """An explicit fail-closed validation or target fence."""


@dataclass(frozen=True)
class Bundle:
    world: World
    manifest: dict
    manifest_hash: str
    validation: dict


def target_guard(uri: str, database: str, protected=()) -> str:
    parsed = urlsplit(uri)
    if (parsed.scheme != "bolt" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ImportRefused("Only an uncredentialed local bolt endpoint is allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ImportRefused("Invalid local bolt port") from exc
    if port not in (None, 7687):
        raise ImportRefused("Only the local bolt default port is allowed")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", database):
        raise ImportRefused("Invalid Neo4j database name; use shipments-v2-demo (no underscores)")
    if database.startswith("system") or database in {"system", "neo4j", *map(str.lower, protected)}:
        raise ImportRefused("Active/default/system databases are protected")
    if not database.startswith("shipments-v2-"):
        raise ImportRefused("Target must use the isolated shipments-v2- prefix")
    return database


def _records(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ImportRefused("Export records must be objects")
                yield value


def _properties(properties: dict) -> dict:
    if not isinstance(properties, dict):
        raise ImportRefused("Record properties must be an object")
    result = {}
    for key, value in properties.items():
        if not isinstance(key, str) or not key or key.startswith("_v2_"):
            raise ImportRefused("Invalid/reserved property name")
        if value is None:
            continue  # Neo4j's absent property represents a JSON null.
        if key in UTC_FIELDS:
            if not isinstance(value, str):
                raise ImportRefused("UTC properties must be offset-aware strings")
            value = instant(value)
        elif isinstance(value, list):
            if value and (type(value[0]) not in (str, int, float, bool)
                          or any(type(item) is not type(value[0]) for item in value)):
                raise ImportRefused("Neo4j properties require homogeneous scalar arrays")
            if any(isinstance(item, float) and not math.isfinite(item) for item in value):
                raise ImportRefused("Nonfinite array property")
        elif type(value) not in (str, int, float, bool):
            raise ImportRefused("Neo4j properties require scalars or scalar arrays")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ImportRefused("Nonfinite property")
        if (type(value) is int and not -(2 ** 63) <= value < 2 ** 63
                or isinstance(value, list) and any(type(item) is int and not -(2 ** 63) <= item < 2 ** 63
                                                 for item in value)):
            raise ImportRefused("Integer property exceeds Neo4j signed 64-bit storage")
        result[key] = value
    return result


def _domain_validate(world: World) -> dict:
    from dataset_v2.validate import validate_world
    return validate_world(world)


def read_bundle(directory: Path | str, validator=None) -> Bundle:
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("synthetic") is not True:
        raise ImportRefused("Unsupported/non-synthetic manifest")
    world = World(Config(**manifest["config"]))
    for row in _records(directory / "nodes.jsonl"):
        node = Node(**row)
        if node.kind not in KINDS or not node.id.startswith("DEMO-") or node.id in world.nodes:
            raise ImportRefused("Invalid/duplicate node identity or kind")
        _properties(node.properties)
        if (node.properties.get("entity_id") != node.id
                or node.properties.get("dataset_id") != world.config.dataset_id
                or node.properties.get("schema_version") != SCHEMA_VERSION
                or node.properties.get("synthetic") is not True):
            raise ImportRefused("Node identity/provenance envelope mismatch")
        world.nodes[node.id] = node
    for row in _records(directory / "edges.jsonl"):
        edge = Edge(**row)
        if (edge.kind not in RELATIONSHIPS or not edge.id.startswith("DEMO-")
                or edge.id in world.edges or edge.start not in world.nodes or edge.end not in world.nodes):
            raise ImportRefused("Invalid/duplicate relationship or endpoint")
        _properties(edge.properties)
        if (edge.properties.get("edge_id") != edge.id
                or edge.properties.get("dataset_id") != world.config.dataset_id
                or edge.properties.get("schema_version") != SCHEMA_VERSION
                or edge.properties.get("synthetic") is not True):
            raise ImportRefused("Relationship identity/provenance envelope mismatch")
        world.edges[edge.id] = edge
    for row in _records(directory / "gold.jsonl"):
        identifier = row.get("shipment_id")
        if not isinstance(identifier, str) or identifier in world.gold:
            raise ImportRefused("Invalid/duplicate scoring identity")
        world.gold[identifier] = row
    if manifest != world.manifest():
        raise ImportRefused("Manifest counts, versions, configuration or canonical content hashes differ")
    # Recompute domain invariants. A writable validation.json PASS is never authority.
    validation = (validator or _domain_validate)(world)
    if not isinstance(validation, dict) or validation.get("pass") is not True or validation.get("errors"):
        raise ImportRefused("Recomputed domain validation failed")
    saved_validation = json.loads((directory / "validation.json").read_text(encoding="utf-8"))
    if saved_validation != validation:
        raise ImportRefused("Saved validation report differs from recomputed report")
    if json.loads((directory / "statistics.json").read_text(encoding="utf-8")) != validation.get("statistics"):
        raise ImportRefused("Saved statistics differ from recomputed statistics")
    return Bundle(world, manifest, digest(manifest), validation)


def _comparable(properties: dict, *, stored=False) -> dict:
    result = {}
    for key, value in properties.items():
        if key == "_v2_record_hash" or value is None:
            continue
        if key in UTC_FIELDS:
            if hasattr(value, "to_native"):
                value = value.to_native()
            if stored and not isinstance(value, datetime):
                raise ImportRefused("Stored UTC property is not a Neo4j temporal value")
            if isinstance(value, datetime):
                value = instant(value.isoformat()).isoformat()
            else:
                value = instant(value).isoformat()
        result[key] = value
    return result


def _read_content(tx, bundle: Bundle, *, allow_partial=False) -> dict:
    """Verify all actual properties/topology, not merely mutable record hash stamps."""
    seen = set()
    ops = {}
    for row in tx.run("MATCH (n) WHERE NOT n:_V2Import RETURN labels(n) AS labels,properties(n) AS props"):
        props = row["props"]
        if "OpsEntity" in row["labels"]:
            if allow_partial:
                raise ImportRefused("LOADING imports cannot contain runtime operations")
            from operations.schema import validate_node
            try:
                validate_node(row["labels"], props, bundle.world)
            except ValueError as exc:
                raise ImportRefused("Unregistered or foreign operations node") from exc
            identifier = props["entity_id"]
            if identifier in ops or identifier in bundle.world.nodes:
                raise ImportRefused("Operations identity collision")
            ops[identifier] = props
            continue
        node = bundle.world.nodes.get(props.get("entity_id"))
        if (node is None or node.id in seen or set(row["labels"]) != set(node.labels)
                or canonical(_comparable(props, stored=True)) != canonical(_comparable(node.properties))
                or props.get("_v2_record_hash") != digest(node.record())):
            raise ImportRefused("Existing target node content differs")
        seen.add(node.id)
    if not allow_partial and len(seen) != len(bundle.world.nodes):
        raise ImportRefused("Existing target node count differs")
    node_ids = seen
    seen = set()
    for row in tx.run("MATCH (a)-[r]->(b) RETURN type(r) AS kind,a.entity_id AS start,"
                      "b.entity_id AS end,properties(r) AS props"):
        props = row["props"]
        if row["kind"].startswith("OPS_"):
            if allow_partial:
                raise ImportRefused("LOADING imports cannot contain runtime operations")
            from operations.schema import validate_edge
            try:
                validate_edge(row["kind"], props, row["start"], row["end"], ops, bundle.world)
            except ValueError as exc:
                raise ImportRefused("Unregistered or foreign operations relationship") from exc
            continue
        edge = bundle.world.edges.get(props.get("edge_id"))
        if (edge is None or edge.id in seen or (row["kind"], row["start"], row["end"])
                != (edge.kind, edge.start, edge.end)
                or canonical(_comparable(props, stored=True)) != canonical(_comparable(edge.properties))
                or props.get("_v2_record_hash") != digest(edge.record())):
            raise ImportRefused("Existing target relationship content differs")
        seen.add(edge.id)
    if not allow_partial and len(seen) != len(bundle.world.edges):
        raise ImportRefused("Existing target relationship count differs")
    return {"node_ids": node_ids, "edge_ids": seen}


def _start_load(tx, bundle: Bundle):
    markers = list(tx.run("MATCH (m:_V2Import) RETURN labels(m) AS labels,properties(m) AS props"))
    if markers:
        expected = _marker_properties(bundle, markers[0]["props"].get("state"))
        if (len(markers) != 1 or markers[0]["props"] != expected
                or markers[0]["labels"] != ["_V2Import"]
                or expected["state"] not in {"LOADING", "COMPLETE"}):
            raise ImportRefused("Existing target has an incompatible manifest")
        return {"created": False, "state": expected["state"]}
    count = tx.run("MATCH (n) RETURN count(n) AS count").single()["count"]
    if count:
        raise ImportRefused("Existing target is nonempty without a compatible manifest")
    tx.run("CREATE (m:_V2Import) SET m=$props", props=_marker_properties(bundle, "LOADING")).consume()
    return {"created": True, "state": "LOADING"}


def _marker_properties(bundle, state="COMPLETE"):
    return {"id": MARKER_ID, "manifest_hash": bundle.manifest_hash,
            "manifest_json": canonical(bundle.manifest), "loader_version": LOADER_VERSION,
            "state": state}


def _require_loading(tx, bundle):
    markers = list(tx.run("MATCH (m:_V2Import) RETURN labels(m) AS labels,properties(m) AS props"))
    if (len(markers) != 1 or markers[0]["labels"] != ["_V2Import"]
            or markers[0]["props"] != _marker_properties(bundle, "LOADING")):
        raise ImportRefused("Batch target lost its matching LOADING manifest")


def _write_batch(tx, bundle, kind, records, *, edges=False):
    _require_loading(tx, bundle)
    if not 0 < len(records) <= BATCH_SIZE:
        raise ImportRefused("Invalid checkpoint batch size")
    if edges:
        rows = [{"start": edge.start, "end": edge.end,
                 "props": {**_properties(edge.properties), "_v2_record_hash": digest(edge.record())}}
                for edge in records]
        query = ("UNWIND $rows AS row MATCH (a:V2Entity {entity_id:row.start}),"
                 f"(b:V2Entity {{entity_id:row.end}}) MERGE (a)-[r:{kind} "
                 "{edge_id:row.props.edge_id}]->(b) ON CREATE SET r=row.props")
    else:
        rows = [{"props": {**_properties(node.properties), "_v2_record_hash": digest(node.record())}}
                for node in records]
        labels = ":".join(("V2Entity", kind, *ALIASES.get(kind, ())))
        query = f"UNWIND $rows AS row CREATE (n:{labels}) SET n=row.props"
    summary = tx.run(query, rows=rows).consume()
    created = summary.counters.relationships_created if edges else summary.counters.nodes_created
    if created != len(records):
        raise ImportRefused("Checkpoint did not create every expected record")
    return created


def _finish_load(tx, bundle):
    _require_loading(tx, bundle)
    _preflight(tx, bundle)
    _read_content(tx, bundle)
    tx.run("MATCH (m:_V2Import {id:$id}) SET m.state='COMPLETE'", id=MARKER_ID).consume()


def apply_bundle(driver, bundle: Bundle, *, uri: str, database: str, protected=()) -> dict:
    target_guard(uri, database, protected)
    if bundle.manifest != bundle.world.manifest() or digest(bundle.manifest) != bundle.manifest_hash:
        raise ImportRefused("Validated in-memory bundle was changed")
    with driver.session(database="system", default_access_mode="READ") as session:
        component = session.run("CALL dbms.components() YIELD name,edition,versions "
                                "WHERE name='Neo4j Kernel' RETURN edition,versions").single()
        if component is None or component["edition"].lower() != "enterprise":
            raise ImportRefused("Enterprise Edition must be verified before creating a shadow database")
        databases = list(session.run("SHOW DATABASES YIELD name,aliases,default,home,type,currentStatus "
                                     "RETURN name,aliases,default,home,type,currentStatus"))
    for row in databases:
        if database in row.get("aliases", []):
            raise ImportRefused("Target resolves through a database alias")
        if row["name"] == database and (row.get("default") or row.get("home")
                                       or row.get("type") != "standard"
                                       or row.get("currentStatus") != "online"):
            raise ImportRefused("Existing target is default/home/nonstandard/offline")
    if not any(row["name"] == database for row in databases):
        with driver.session(database="system") as session:
            session.run(f"CREATE DATABASE `{database}` WAIT 30 SECONDS").consume()
    with driver.session(database=database) as session:
        # Inspect before DDL: foreign populated targets never receive our constraints.
        existing = session.execute_read(_preflight, bundle)
        if existing["state"] == "COMPLETE":
            return _report(bundle, database, "identical_replay", 0, 0, 0)
        session.run("CREATE CONSTRAINT v2_entity_id IF NOT EXISTS FOR (n:V2Entity) "
                    "REQUIRE n.entity_id IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT v2_manifest_id IF NOT EXISTS FOR (n:_V2Import) "
                    "REQUIRE n.id IS UNIQUE").consume()
        session.run("CREATE INDEX v2_holdout IF NOT EXISTS FOR (n:V2Entity) ON (n.holdout_group)").consume()
        session.run("CREATE INDEX v2_split IF NOT EXISTS FOR (n:V2Entity) ON (n.split)").consume()
        marker = session.execute_write(_start_load, bundle)
        if marker["state"] == "COMPLETE":
            session.execute_read(_preflight, bundle)
            return _report(bundle, database, "identical_replay", 0, 0, 0)
        added_nodes, added_edges = 0, 0
        try:
            for edges, records, seen in ((False, bundle.world.nodes, existing["node_ids"]),
                                         (True, bundle.world.edges, existing["edge_ids"])):
                groups = defaultdict(list)
                for identifier in sorted(records):
                    if identifier not in seen:
                        record = records[identifier]
                        groups[record.kind].append(record)
                for kind, group in sorted(groups.items()):
                    for offset in range(0, len(group), BATCH_SIZE):
                        created = session.execute_write(_write_batch, bundle, kind,
                            group[offset:offset + BATCH_SIZE], edges=edges)
                        if edges:
                            added_edges += created
                        else:
                            added_nodes += created
            session.execute_write(_finish_load, bundle)
        except Exception as exc:
            report = _report(bundle, database, "resumable_incomplete", added_nodes, added_edges, int(marker["created"]))
            report.update(state="LOADING", error_type=type(exc).__name__,
                          added_counts_scope="confirmed committed checkpoints; verify target on resume")
            return report
    return _report(bundle, database, "imported" if marker["created"] else "resumed", added_nodes,
                   added_edges, int(marker["created"]))


def _report(bundle, database, status, added_nodes, added_edges, added_marker):
    return {"status": status, "database": database, "manifest_hash": bundle.manifest_hash,
            "nodes": len(bundle.world.nodes), "edges": len(bundle.world.edges),
            "manifest_nodes": 1, "total_graph_nodes": len(bundle.world.nodes) + 1,
            "gold_imported": False, "added_nodes": added_nodes + added_marker,
            "added_entities": added_nodes, "added_manifest_nodes": added_marker, "added_edges": added_edges}


def _preflight(tx, bundle):
    markers = list(tx.run("MATCH (m:_V2Import) RETURN labels(m) AS labels,properties(m) AS props"))
    state = "EMPTY"
    content = {"node_ids": set(), "edge_ids": set()}
    if markers:
        # The read-only verification callback shares all replay validation.
        state = markers[0]["props"].get("state")
        if (len(markers) != 1 or state not in {"LOADING", "COMPLETE"}
                or markers[0]["props"] != _marker_properties(bundle, state)
                or markers[0]["labels"] != ["_V2Import"]):
            raise ImportRefused("Existing target has an incompatible manifest")
        content = _read_content(tx, bundle, allow_partial=state == "LOADING")
    elif tx.run("MATCH (n) RETURN count(n) AS count").single()["count"]:
        raise ImportRefused("Nonempty isolated target lacks the immutable V2 manifest")
    index_definitions = {"v2_entity_id": (["V2Entity"], ["entity_id"]),
                         "v2_manifest_id": (["_V2Import"], ["id"]),
                         "v2_holdout": (["V2Entity"], ["holdout_group"]),
                         "v2_split": (["V2Entity"], ["split"])}
    core_indexes = set(index_definitions)
    constraint_names = {"v2_entity_id", "v2_manifest_id"}
    if state == "COMPLETE":
        from operations.schema import SCHEMA
        index_definitions.update({name: ([label], [prop]) for name, (_, label, prop) in SCHEMA.items()})
        constraint_names.update(name for name, (kind, _, _) in SCHEMA.items() if kind == "CONSTRAINT")
    indexes_seen, constraints_seen = set(), set()
    for row in tx.run("SHOW INDEXES YIELD name,type,entityType,labelsOrTypes,properties,owningConstraint "
                      "RETURN name,type,entityType,labelsOrTypes,properties,owningConstraint"):
        if row["type"] != "LOOKUP" and (row["type"] != "RANGE"
                or row.get("entityType") != "NODE"
                or row.get("owningConstraint") != (row["name"] if row["name"] in constraint_names else None)
                or (row["labelsOrTypes"], row["properties"]) != index_definitions.get(row["name"])):
            raise ImportRefused("Target has foreign/incompatible schema indexes")
        if row["type"] != "LOOKUP":
            indexes_seen.add(row["name"])
    for row in tx.run("SHOW CONSTRAINTS YIELD name,type,entityType,labelsOrTypes,properties "
                      "RETURN name,type,entityType,labelsOrTypes,properties"):
        if (row["name"] not in constraint_names
                or row["type"] not in {"UNIQUENESS", "NODE_PROPERTY_UNIQUENESS"}
                or row.get("entityType") != "NODE"
                or (row["labelsOrTypes"], row["properties"]) != index_definitions.get(row["name"])):
            raise ImportRefused("Target has foreign/incompatible constraints")
        constraints_seen.add(row["name"])
    if markers and (not core_indexes <= indexes_seen
                    or not {"v2_entity_id", "v2_manifest_id"} <= constraints_seen):
        raise ImportRefused("Existing manifest target is missing required loader schema")
    return {"state": state, **content}


def export_target(driver, bundle: Bundle, destination: Path, *, uri: str, database: str, protected=()):
    """Read-only recovery snapshot; never drops/deletes/clears the isolated database."""
    target_guard(uri, database, protected)
    if destination.exists():
        raise ImportRefused("Recovery destination must not already exist")
    with driver.session(database=database, default_access_mode="READ") as session:
        def snapshot(tx):
            if _preflight(tx, bundle)["state"] != "COMPLETE":
                raise ImportRefused("Recovery/read access requires a COMPLETE import")
            return {"manifest": bundle.manifest, "nodes": [n.record() for n in bundle.world.nodes.values()],
                    "edges": [e.record() for e in bundle.world.edges.values()]}
        content = session.execute_read(snapshot)
    destination.mkdir(parents=True)
    for key in ("nodes", "edges"):
        with (destination / f"{key}.jsonl").open("w",encoding="utf-8",newline="\n") as stream:
            for row in sorted(content[key],key=lambda row:row["id"]):
                stream.write(canonical(row)+"\n")
    (destination / "manifest.json").write_text(canonical(content["manifest"]), encoding="utf-8")
    report={"database": database,
        "manifest_hash": bundle.manifest_hash, "gold_included": False,
        "nodes":len(content["nodes"]),"edges":len(content["edges"]),"read_only":True,
        "scope": "verified graph snapshot; retain original scoring export for complete reload"}
    (destination / "recovery.json").write_text(canonical(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database")
    parser.add_argument("--export-target", type=Path)
    args = parser.parse_args(argv)
    bundle = read_bundle(args.directory)
    if not args.apply and not args.export_target:
        print(canonical({"status": "dry_run", "manifest_hash": bundle.manifest_hash,
                         "counts": bundle.manifest["counts"], "gold_imported": False,
                         "suggested_database": DEFAULT_DATABASE, "inspect_queries": INSPECT_QUERIES}))
        return
    if not args.database:
        parser.error("--apply/--export-target require explicit --database shipments-v2-demo")
    if args.apply and args.export_target:
        parser.error("Choose apply or read-only recovery export")
    import config
    protected = (config.SHIPMENT_DATABASE, config.NEO4J_DATABASE, config.CHAT_DATABASE)
    target_guard(config.NEO4J_URI, args.database, protected)
    from neo4j import GraphDatabase
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD)) as driver:
        if args.export_target:
            export_target(driver, bundle, args.export_target, uri=config.NEO4J_URI,
                          database=args.database, protected=protected)
            print(canonical({"status": "recovery_export", "database": args.database, "gold_imported": False}))
        else:
            report = apply_bundle(driver, bundle, uri=config.NEO4J_URI,
                                  database=args.database, protected=protected)
            print(canonical(report))
            if report["status"] == "resumable_incomplete":
                raise SystemExit(2)


if __name__ == "__main__":
    main()
