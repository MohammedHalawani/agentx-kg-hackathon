"""Deterministic Suhail V3 source profile.

Commands (run from chat):
  uv run python -m world.v3_scenarios fixture
  uv run python -m world.v3_scenarios export
  uv run python -m world.v3_scenarios validate

``fixture`` writes an early source-backed route schema and bounded fixture. ``export``
builds and validates the entire 240-shipment world before writing the immutable V2
bundle, physical state and private truth to separate external roots. It then emits
label-free neutral packets for the sealed development selection. ``validate`` checks
an existing bundle without importing or resetting any database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dataset_v2.contracts import Edge, World, digest, instant
from dataset_v2.feed import reconstitute
from operations.reasoning import public_evidence
from operations.route_evidence import build_route_evidence
from world.build import build_world, export_bundle
from world.config import WorldConfig, uniform_rates


DATASET_ID = "DEMO-SUHAIL-WORLD-V3-20261013"
SEED = 11
DATA_ROOT = Path(r"C:\Projects\suhail-v3-data\world-v3-20261013")
STATE_ROOT = Path(r"C:\Projects\suhail-v3-state\world-v3-20261013")
PRIVATE_ROOT = Path(r"C:\Projects\suhail-v3-private\world-v3-20261013")
BUNDLE = DATA_ROOT / "bundle"
CASES = ("DEMO-SHP-000051", "DEMO-SHP-000129", "DEMO-SHP-000133", "DEMO-SHP-000134",
         "DEMO-SHP-000182", "DEMO-SHP-000194", "DEMO-SHP-000222", "DEMO-SHP-000226")
FORBIDDEN_RUNTIME_KEYS = {"scenario_family", "expected_cause", "root_cause", "gold", "scoring_truth",
                          "desired_outcome", "allowed_operational_outcomes", "mechanism_id", "recipe"}


def config():
    return WorldConfig(total=240, seed=SEED, dataset_id=DATASET_ID, rates=uniform_rates(.012, .012))


ROUTE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "route-evidence-v3-1", "title": "RouteEvidenceV3",
    "type": "object", "required": ["schema", "shipment_id", "as_of", "contexts", "observations", "summary",
                                    "source_nodes", "source_relationships", "truncated"],
    "properties": {
        "schema": {"const": "route-evidence-v3-1"}, "shipment_id": {"type": "string", "maxLength": 160},
        "as_of": {"type": "string", "format": "date-time"},
        "contexts": {"type": "array", "maxItems": 4, "items": {"type": "object", "required": ["route_run_id", "trip_id", "assignment_id", "vehicle_id", "device_id", "valid_from", "valid_to", "plan_source_ids", "custody_source_ids"]}},
        "observations": {"type": "array", "maxItems": 160, "items": {"type": "object",
            "required": ["entity_id", "evidence_id", "vehicle_id", "route_run_id", "trip_id", "lat", "lng",
                         "accuracy_m", "speed_kmh", "occurred_at", "recorded_at", "source_ref", "position_scope", "classification", "source_event_id"],
            "properties": {"lat": {"type": "number", "minimum": -90, "maximum": 90},
                           "lng": {"type": "number", "minimum": -180, "maximum": 180},
                           "position_scope": {"const": "VEHICLE_ONLY"}, "classification": {"const": "observed_vehicle"}}}},
        "summary": {"type": "object"}, "source_nodes": {"type": "array"},
        "source_relationships": {"type": "array"}, "truncated": {"type": "object"}},
    "additionalProperties": False}


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_label_free(value):
    """Fail closed on answer metadata before any runtime manifest or QA packet is saved."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_RUNTIME_KEYS or key.lower().startswith(("gold_", "recipe_")):
                raise ValueError(f"Private answer key in runtime artifact: {key}")
            assert_label_free(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_label_free(item)


def delivery_providers(items):
    """Provider that delivered each first-delivered record (the feed envelope's ``provider_id``)."""
    providers = {}
    for item in items:
        providers.setdefault(item["source_event_id"], item["provider_id"])
    return providers


def _gateway_world(imported, items):
    """Decode feed with its gateway receipt times and materialize only gateway-defined edges.

    ``operations.ingestion`` stamps each ingested record with its delivery envelope, including the
    delivering ``provider_id``, and the read model hydrates every shared record that a visible
    record references. ``dataset_v2.feed.reconstitute`` decodes payloads only, so the delivering
    provider is re-attached here. A payload that already names its own ``provider_id`` keeps that
    domain value: replacing it with the channel provider would misstate the record.
    """
    from operations.ingestion import EDGE_RULES
    world = reconstitute(imported, items)
    delivered_by = delivery_providers(items)
    for key in sorted(set(world.nodes) - set(imported.nodes)):
        node = world.nodes[key]
        if delivered_by.get(key):
            node.properties.setdefault("provider_id", delivered_by[key])
        sid = node.properties.get("holdout_group")
        for rule_kind, prop, rel, outward in EDGE_RULES:
            if rule_kind != node.kind:
                continue
            targets = node.properties.get(prop) if prop != "shipment_id" else sid
            for target in targets if isinstance(targets, list) else [targets]:
                if isinstance(target, str) and target.startswith("DEMO-") and target in world.nodes:
                    start, end = (key, target) if outward else (target, key)
                    edge_id = "DEMO-EDGE-" + digest([start, rel, end, "live-ingestion-1"])[:24]
                    world.edges[edge_id] = Edge(edge_id, rel, start, end,
                                                {"edge_id": edge_id, "holdout_group": sid,
                                                 "recorded_at": node.properties["recorded_at"]})
    return world


def _route(world, sid, cutoff):
    from tests.world_fixture import MemoryPort
    # Match the reader's bounded hydration: owned records plus references to
    # visible shared catalogue, rather than traversing the entire shared graph.
    scoped = World(world.config)
    at = instant(cutoff)
    owned = [n for n in world.nodes.values() if n.properties.get("holdout_group") == sid
             and instant(n.properties["recorded_at"]) <= at]
    for node in owned:
        scoped.nodes[node.id] = node
    refs = set()
    for node in owned:
        for value in node.properties.values():
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str) and item.startswith("DEMO-"):
                    refs.add(item)
    for key in sorted(refs):
        node = world.nodes.get(key)
        if node and node.properties.get("split") == "shared" and instant(node.properties["recorded_at"]) <= at:
            scoped.nodes[key] = node
    for edge in world.edges.values():
        if (edge.start in scoped.nodes and edge.end in scoped.nodes
                and edge.properties.get("holdout_group") in (None, sid)
                and (not edge.properties.get("recorded_at") or instant(edge.properties["recorded_at"]) <= at)):
            scoped.edges[edge.id] = edge
    context = public_evidence(scoped, sid, cutoff)
    port = MemoryPort(world)
    route = build_route_evidence(context, lambda name, **kw: port.fetch(name, as_of=context["as_of"], **kw))
    return context, route, port


def _cutoffs(world, sid):
    records = sorted((n.properties for n in world.nodes.values()
                      if n.properties.get("holdout_group") == sid and n.kind in ("ScanEvent", "DeliveryAttempt", "RecipientReport")
                      and n.properties.get("occurred_at") and n.properties.get("recorded_at")
                      and instant(n.properties["recorded_at"]) > instant(n.properties["occurred_at"])),
                     key=lambda p: (instant(p["recorded_at"]) - instant(p["occurred_at"])).total_seconds(), reverse=True)
    if not records:
        raise ValueError(f"No receipt-cutoff source for {sid}")
    p = records[0]
    from datetime import timedelta
    before = instant(p["recorded_at"]) - timedelta(seconds=1)
    after = instant(p["recorded_at"])
    return p["entity_id"], before.isoformat(), after.isoformat()


def write_fixture(world, root=DATA_ROOT):
    root.mkdir(parents=True, exist_ok=True)
    schema_file = root / "route-evidence.schema.json"
    fixture_file = root / "route-evidence.fixture.json"
    _, route, _ = _route(world, CASES[0], world.config.as_of)
    if not route["observations"] or len(route["observations"]) > 160:
        raise ValueError("Fixture must contain valid bounded vehicle observations")
    _json(schema_file, ROUTE_SCHEMA)
    _json(fixture_file, route)
    return {"schema": str(schema_file), "schema_sha256": _sha(schema_file),
            "fixture": str(fixture_file), "fixture_sha256": _sha(fixture_file)}


def write_neutral_packets(world, bundle_manifest_sha256, root=DATA_ROOT):
    from operations.tools import InvestigationTools
    packets = root / "neutral-packets"
    packets.mkdir(parents=True, exist_ok=True)
    records = []
    for sid in CASES:
        source_id, before, after = _cutoffs(world, sid)
        snapshots = []
        cutoffs = list(dict.fromkeys((before, after, world.config.as_of)))
        for cutoff in cutoffs:
            context, route, port = _route(world, sid, cutoff)
            belt = InvestigationTools(context, world.config, port=port.fetch)
            tools = {name: belt.call(name, {}) for name in ("shipment_overview", "route_observations", "vehicle_and_manifest")}
            snapshots.append({"as_of": cutoff, "source_nodes": context["nodes"], "source_relationships": context["edges"],
                              "route_evidence": route, "permitted_tool_snapshot": tools})
        path = packets / f"{sid}.json"
        packet = {"schema": "v3-neutral-source-packet-1", "dataset_id": DATASET_ID,
                  "shipment_id": sid, "case_id": None, "receipt_source_id": source_id,
                  "replay_cutoffs": cutoffs, "bundle_manifest_sha256": bundle_manifest_sha256,
                  "snapshots": snapshots}
        assert_label_free(packet)
        _json(path, packet)
        records.append({"shipment_id": sid, "packet": str(path), "sha256": _sha(path),
                        "receipt_source_id": source_id, "replay_cutoffs": cutoffs})
    return records


def _manifest(world, packets, bundle_hash):
    record_ids = sorted({r["receipt_source_id"] for r in packets})
    cutoffs = sorted({t for r in packets for t in r["replay_cutoffs"]})
    return {"schema": "v3-runtime-fixtures-1", "dataset_id": DATASET_ID, "seed": SEED,
            "fixture_id": "DEMO-V3-FIXTURE-001", "shipment_ids": list(CASES),
            "source_record_ids": record_ids, "replay_cutoffs": cutoffs,
            "content_hashes": {"bundle_manifest_sha256": bundle_hash,
                               "source_record_ids_sha256": digest(record_ids),
                               "neutral_packet_sha256": {r["shipment_id"]: r["sha256"] for r in packets}}}


def export():
    from world.export import write_bundle, write_state, write_truth
    from world.pipeline import build_and_validate
    if BUNDLE.exists():
        raise ValueError("V3 bundle already exists; immutable export requires a new approved target")
    build, report, replays = build_and_validate(config(), determinism=True)
    if not report["pass"]:
        _json(DATA_ROOT / "validation-failed.json", {k: v for k, v in report.items() if k != "exports"})
        raise ValueError("Full-world validation failed; no bundle or private state written")
    world = _gateway_world(*build.exports["development"][:2])
    for sid in CASES:
        if sid not in world.nodes or world.nodes[sid].properties.get("split") != "development":
            raise ValueError(f"Curated shipment not in development: {sid}")
    fixture = write_fixture(world)
    write_truth(build, PRIVATE_ROOT, replays, build.history_reports, name=BUNDLE.name, report=report)
    write_state(build, STATE_ROOT, name=BUNDLE.name)
    write_bundle(build, "development", BUNDLE, report, replay=replays.get("development"))
    bundle_hash = _sha(BUNDLE / "manifest.json")
    packets = write_neutral_packets(world, bundle_hash)
    runtime = DATA_ROOT / "runtime-fixtures.json"
    runtime_value = _manifest(world, packets, bundle_hash)
    assert_label_free(runtime_value)
    _json(runtime, runtime_value)
    validation = DATA_ROOT / "validation.json"
    _json(validation, {"pass": report["pass"], "timings_seconds": report["timings_seconds"],
                       "digests": report["digests"], "monitor_replay_pass": report["monitor_replay_pass"]})
    return {**fixture, "bundle": str(BUNDLE), "bundle_manifest_sha256": bundle_hash,
            "runtime_manifest": str(runtime), "runtime_manifest_sha256": _sha(runtime),
            "validation": str(validation), "neutral_packets": packets,
            "physical_root": str(STATE_ROOT), "private_root": str(PRIVATE_ROOT)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fixture", "export", "validate", "packets"))
    parser.add_argument("--output-root", type=Path, default=DATA_ROOT,
                        help="packets only: directory for the regenerated packets, route fixture and runtime manifest; "
                             "use a new directory to leave the originals untouched")
    args = parser.parse_args(argv)
    if args.command == "fixture":
        build = build_world(config())
        imported, items, _, _ = export_bundle(build, "development")
        result = write_fixture(_gateway_world(imported, items))
    elif args.command == "export":
        result = export()
    elif args.command == "packets":
        from world.export import read_world_bundle
        loaded, items = read_world_bundle(BUNDLE)
        world = _gateway_world(loaded.world, items)
        root = args.output_root
        fixture = write_fixture(world, root)
        bundle_hash = _sha(BUNDLE / "manifest.json")
        packets = write_neutral_packets(world, bundle_hash, root)
        runtime = root / "runtime-fixtures.json"
        runtime_value = _manifest(world, packets, bundle_hash)
        assert_label_free(runtime_value)
        _json(runtime, runtime_value)
        result = {**fixture, "neutral_packets": packets, "runtime_manifest": str(runtime),
                  "runtime_manifest_sha256": _sha(runtime)}
    else:
        from world.export import read_world_bundle
        loaded = read_world_bundle(BUNDLE)
        result = {"bundle": str(BUNDLE), "nodes": len(loaded[0].world.nodes), "items": len(loaded[1]),
                  "manifest_sha256": _sha(BUNDLE / "manifest.json")}
    print(json.dumps(result, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
