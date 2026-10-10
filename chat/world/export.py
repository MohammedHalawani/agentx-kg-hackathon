"""World-1 CLI: export a validated bundle, import it into an isolated world database, run Cypher checks.

  uv run python -m world.export export --output ../artifacts/world/world-1-small [--total 600 --days 6 --seed 20261010]
                                       [--with-heldout] [--eval-dir ../docs/evals/2026-10-10_world1_small] [--determinism]
  uv run python -m world.export apply ../artifacts/world/world-1-small --database shipments-v2-world-1-small [--replace]
  uv run python -m world.export check ../artifacts/world/world-1-small --database shipments-v2-world-1-small
                                      --out ../docs/evals/2026-10-10_world1_small/cypher.json [--ingest]

export   refuses an existing directory; writes the V2 bundle (nodes, edges, gold, feed, manifest, validation,
         statistics, feed_manifest) plus world_manifest.json, world_validation.json, an aggregate monitor_replay.json
         and private/ (label-free physical world state: parcel and container locations, device buffers and reconnect
         times, recipient availability and correct addresses, trips, routes). Nothing private is imported. Truth labels
         (mechanisms, causes, discrimination specs, the canary) go to <truth-root>/<dataset_id>/, outside the repository
         (default C:\\Projects\\suhail-eval-truth). --with-heldout also writes <output>-heldout, where the held-out days
         are live and history plus development are imported in full.
apply    imports into a database whose name starts with shipments-v2-world- (never any other), reusing
         dataset_v2.load.apply_bundle, load_feed and target_guard. --replace recreates that database first.
check    read-only integrity queries, timed cross-shipment traversals and the database isolation scan (canary,
         mechanism ids and names); --ingest additionally replays the whole feed through the real ingestion gateway to
         the end of the horizon, repeats the checks on live evidence, and resets the live session afterwards
         (Gateway.reset), leaving the database as imported.
Neo4j settings come from chat/config.py; credentials are never printed or written.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import tempfile
import time

from dataset_v2.contracts import Edge, KINDS, Node, RELATIONSHIPS, SCHEMA_VERSION, World, canonical, digest, instant, iso
from dataset_v2.feed import FEED_VERSION, validate_live_bundle
from dataset_v2.load import Bundle, ImportRefused, _properties, _records, apply_bundle, target_guard
from world.config import DEFAULT_TRUTH_ROOT, WORLD_VERSION, WorldConfig, WorldV2Config

WORLD_PREFIX = "shipments-v2-world-"
NEVER = ("shipments-v2-demo-live", "shipments-v2-demo", "shipments-v2-demo-test", "shipments-v2-demo-test2")


def _jsonable(value):
    if hasattr(value, "isoformat"):
        return iso(value) if getattr(value, "tzinfo", None) else value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        items = [_jsonable(v) for v in value]
        return sorted(items, key=canonical) if isinstance(value, set) else items
    return value


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(canonical(_jsonable(row)) + "\n")


def _write_json(path, value):
    path.write_text(canonical(_jsonable(value)) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------- private outputs (addendum B1)
EVENT_NAMES = {"booked": "booked", "handover": "handed_over_at_origin", "received_unscanned": "arrived_without_a_receipt_record",
               "returned_unscanned": "back_on_shelf_without_a_return_record", "delivered_unrecorded": "handed_over_without_an_app_record",
               "contractor_retains": "driver_kept_parcels", "unrecorded_handoff": "parcels_moved_between_drivers"}
PRIVATE_KEYS = {"mid", "mech", "mechanism", "mechanism_id", "upload_mech"}


def _clean(row):
    return {k: v for k, v in row.items() if k not in PRIVATE_KEYS}


def private_physical(build):
    """Label-free physical world state (B1a) the Stage 4 operational simulator may read: parcel and container
    locations over time, device connectivity and buffers with reconnect times, scale offsets, facility capacity,
    trips and routes as they ran, recipient availability and correct addresses, messaging outages, traffic.
    No cause codes, mechanism names, mechanism ids or labels (validate.private_state_isolation proves it)."""
    sim, plan, net, obs = build.sim, build.plan, build.network, build.observer
    out = {}
    out["parcels"] = [{"package_id": pid, "shipment_id": st.shipment.sid, "timeline": st.timeline, "custody": st.custody,
                       "status": st.status, "attempts": st.attempts, "true_kg": st.parcel.true_kg, "declared_kg": st.parcel.declared_kg,
                       "manifest_barcode": st.parcel.barcode, "label_barcode": st.parcel.label_barcode}
                      for pid, st in sorted(sim.p.items())]
    out["containers"] = [{"container_id": cid, "origin": c.origin, "destination": c.depot, "created_at": c.created_at, "sealed_at": c.sealed_at,
                          "opened_at": c.opened_at, "timeline": c.timeline, "parcels": c.parcels} for cid, c in sorted(sim.containers.items())]
    loss_windows = {mid: (device, start) for device, windows in plan.device_loss.items() for start, end, fraction, mid in windows}
    stuck = defaultdict(list)
    for nid, meta in sorted(obs.records.items()):
        if not meta["sid"]:
            continue
        for mid in meta["mech"]:
            if mid in loss_windows:
                stuck[loss_windows[mid]].append({"record": nid, "shipment_id": meta["sid"]})
    devices = []
    for device in sorted(set(plan.device_down) | set(plan.device_loss) | set(plan.scale_drift)):
        info = net.devices.get(device)
        records = sorted((r for r in obs.device_records.get(device, []) if r[0] is not None), key=lambda r: (r[0], r[2]))
        devices.append({
            "device_id": device, "kind": info.kind if info else "SCALE", "telemetry": info.telemetry if info else "NONE",
            "offline": [{"from": a, "reconnect_at": b,
                         "buffered_records": [{"record": nid, "shipment_id": obs.records[nid]["sid"]} for occ, rec, nid in records
                                              if a <= occ < b and nid in obs.records]}
                        for a, b, _ in plan.device_down.get(device, [])],
            "upload_stuck": [{"from": a, "until": b, "share_stuck": f, "uploaded_by": "nightly_full_sync", "stuck_records": stuck.get((device, a), [])}
                             for a, b, f, _ in plan.device_loss.get(device, [])],
            "scale_offset": [{"from": a, "until": b, "relative_offset": f} for a, b, f, _ in plan.scale_drift.get(device, [])]})
    out["devices"] = devices
    out["facility_capacity"] = [{"facility_id": f, "from": a, "until": b, "capacity_factor": factor}
                                for f, rows in sorted(plan.backlog.items()) for a, b, factor, _ in rows]
    out["trips"] = [{"trip_id": tid, "vehicle_id": t.plan.vehicle, "scheduled_departure": t.plan.scheduled_departure,
                     "scheduled_arrival": t.plan.scheduled_arrival, "departed_at": t.departed_at, "arrived_at": t.arrived_at,
                     "stopped": t.breakdown, "containers": t.containers}
                    for tid, t in sorted(sim.trips.items()) if t.departed_at and not t.cancelled]
    out["routes"] = [{"route_run_id": rid, "depot_id": r.depot, "date": r.date, "driver_id": r.driver, "vehicle_id": r.vehicle, "device_id": r.device,
                      "login_at": r.login_at, "departed_at": r.departed_at, "returned_at": r.returned_at, "parcels": r.parcels, "loaded": r.loaded,
                      "kept_by_driver": r.retained, "passed_to_other_driver": r.handed_out, "received_from_other_driver": r.handed_in}
                     for rid, r in sorted(sim.routes.items())]
    recipients = []
    for sid, s in sorted(build.shipments.items()):
        flags = plan.shipment.get(sid, {})
        away = flags.get("RECIPIENT_UNAVAILABLE")
        gate = flags.get("WRONG_GATE")
        sms = flags.get("OTP_NOT_RECEIVED")
        r = s.recipient
        recipients.append({"shipment_id": sid, "recipient_id": s.recipient_id, "home_point": r["home"], "registered_point": r["registered_point"],
                           "gate": r["gate"], "gates": r["gates"], "navigation_gate": gate[1].get("pin_gate") if gate else r["pin_gate"],
                           "availability": r["availability"], "contact": r["contact"],
                           "away": [{"from": away[1].get("from") or away[1].get("start"), "until": away[1].get("until") or away[1].get("end")}] if away else [],
                           "sms_unreachable": [{"from": sms[1].get("from"), "until": sms[1].get("until")}] if sms and sms[1].get("from") else []})
    out["recipients"] = recipients
    out["messaging_outages"] = [{"carrier_route": route, "from": a, "until": b} for route, rows in sorted(plan.sms_outage.items()) for a, b, _ in rows]
    out["traffic"] = [{"city": c, "district": d, "from": a, "until": b, "speed_factor": f} for c, d, a, b, f, _ in plan.traffic]
    out["events"] = [{**_clean(e), "type": EVENT_NAMES.get(e["type"], e["type"])} for e in sorted(sim.events, key=lambda e: (e["t"], e["type"]))]
    return out


def truth_records(build):
    """Truth labels (B1b): written only to the external truth directory."""
    sim, plan = build.sim, build.plan
    mechanisms = []
    for mid, mech in sorted(plan.items.items()):
        mechanisms.append({"mechanism_id": mid, "type": mech.type, "subtype": mech.subtype, "origin": mech.origin,
                           "started_at": mech.started_at, "ended_at": mech.ended_at, "params": mech.params,
                           "touched_shipments": sorted(build.touched.get(mid, set())), "touched_parcels": sorted(sim.touch.get(mid, set()))})
    index = [{"evidence_id": nid, **meta} for nid, meta in sorted(build.observer.records.items())]
    return {"truth": [build.truth[k] for k in sorted(build.truth)], "mechanisms": mechanisms, "record_index": index, "acts": sim.acts,
            "physical_events": sorted(sim.events, key=lambda e: (e["t"], e["type"]))}


def repo_root():
    return Path(__file__).resolve().parents[2]


def truth_directory(root, dataset_id):
    """<root>/<dataset_id>, refusing anything inside the repository or under an artifacts directory."""
    import os
    root = Path(root or os.environ.get("SUHAIL_EVAL_TRUTH_ROOT") or DEFAULT_TRUTH_ROOT).resolve()
    target = root / dataset_id
    repo = repo_root()
    if target == repo or repo in target.parents or "artifacts" in {p.name.lower() for p in [target, *target.parents]}:
        raise ValueError("Truth labels must live outside the repository and outside artifacts/")
    return target


def write_truth(build, root, replays, precedents):
    """Write the truth-label directory once per build; refuses an existing one (truth is immutable like exports)."""
    target = truth_directory(root, build.config.dataset_id)
    if target.exists():
        raise ValueError(f"Choose a new truth root or remove {target}; truth directories are immutable")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".truth-stage-", dir=target.parent) as directory:
        stage = Path(directory) / "truth"
        stage.mkdir()
        records = truth_records(build)
        for name, rows in records.items():
            _write_jsonl(stage / f"{name}.jsonl", rows)
        for split, replay in sorted(replays.items()):
            _write_jsonl(stage / f"monitor_replay_rows_{split}.jsonl", ({"shipment_id": sid, **row} for sid, row in sorted(replay["shipments"].items())))
        _write_json(stage / "precedents.json", precedents)
        _write_json(stage / "manifest.json", {"dataset_id": build.config.dataset_id, "seed": build.config.seed, "world_version": WORLD_VERSION,
                                              "truth_schema": records["truth"][0]["truth_schema"] if records["truth"] else None,
                                              "shipments": len(records["truth"]), "truth_hash": digest(records["truth"]),
                                              "note": "Truth labels for evaluation only. Never imported; never read by backend or operations code."})
        stage.rename(target)
    return str(target)


def read_truth_labels(root, dataset_id):
    """Evaluation tooling only (never backend or operations): canary and mechanism ids for the isolation scans."""
    target = truth_directory(root, dataset_id)
    if not (target / "truth.jsonl").exists():
        return None
    rows = list(_records(target / "truth.jsonl"))
    mechanisms = list(_records(target / "mechanisms.jsonl"))
    return {"canary": sorted({r["canary"] for r in rows}), "mechanism_ids": sorted(m["mechanism_id"] for m in mechanisms),
            "mechanism_types": sorted({m["type"] for m in mechanisms}), "directory": str(target)}


def write_bundle(build, live_split, destination, report, replay):
    from world.build import world_manifest
    imported, items, truth, live_start = build.exports[live_split]
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new export directory; existing exports are immutable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    validation = report["exports"][live_split]["foundation_raw"]
    with tempfile.TemporaryDirectory(prefix=".world-stage-", dir=destination.parent) as directory:
        stage = Path(directory) / "bundle"
        stage.mkdir()
        _write_jsonl(stage / "nodes.jsonl", (imported.nodes[k].record() for k in sorted(imported.nodes)))
        _write_jsonl(stage / "edges.jsonl", (imported.edges[k].record() for k in sorted(imported.edges)))
        _write_jsonl(stage / "gold.jsonl", (imported.gold[k] for k in sorted(imported.gold)))
        _write_jsonl(stage / "feed.jsonl", items)
        feed_manifest = {"feed_version": FEED_VERSION, "network_version": WORLD_VERSION, "items": len(items), "hash": digest(items),
                         "truth_hash": digest([truth[k] for k in sorted(truth)])}
        for name, value in (("manifest", imported.manifest()), ("validation", validation), ("statistics", validation["statistics"]),
                            ("feed_manifest", feed_manifest), ("world_manifest", world_manifest(build, live_split, imported, items, truth)),
                            ("world_validation", report_summary(report, live_split)), ("monitor_replay", replay_summary(replay))):
            _write_json(stage / f"{name}.json", value)
        private = stage / "private"
        private.mkdir()
        for name, rows in private_physical(build).items():
            _write_jsonl(private / f"{name}.jsonl", rows)
        (private / "README.txt").write_text(
            "Private physical world state (label-free) for the Stage 4 operational simulator: parcel and container locations, device "
            "buffers and reconnect times, recipient availability and correct addresses, trips and routes as they ran. No cause codes, "
            "mechanism names or labels. Never imported, never shown to the investigator, its tools, the reviewer or any API. Truth "
            "labels live outside the repository (world/config.py DEFAULT_TRUTH_ROOT).\n", encoding="utf-8")
        stage.rename(destination)
    return feed_manifest


def replay_summary(replay):
    """The monitor replay without per-shipment rows (those name mechanisms and live in the truth directory)."""
    return {k: v for k, v in replay.items() if k != "shipments"}


def report_summary(report, live_split):
    out = {k: v for k, v in report.items() if k != "exports"}
    out["export"] = {key: value for key, value in report["exports"][live_split].items() if key != "foundation_raw"}
    return out


# ---------------------------------------------------------------------- reading a world bundle
def read_world_bundle(directory):
    """Like dataset_v2.load.read_bundle (same record checks), with the world's V2 config (an empty split allowed)
    and the world gate: the recomputed foundation validation must equal the saved one, and its only failures must
    be the documented foundation exceptions."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("synthetic") is not True:
        raise ImportRefused("Unsupported/non-synthetic manifest")
    world = World(WorldV2Config(**manifest["config"]))
    for row in _records(directory / "nodes.jsonl"):
        node = Node(**row)
        if node.kind not in KINDS or not node.id.startswith("DEMO-") or node.id in world.nodes:
            raise ImportRefused("Invalid/duplicate node identity or kind")
        _properties(node.properties)
        if (node.properties.get("entity_id") != node.id or node.properties.get("dataset_id") != world.config.dataset_id
                or node.properties.get("schema_version") != SCHEMA_VERSION or node.properties.get("synthetic") is not True):
            raise ImportRefused("Node identity/provenance envelope mismatch")
        world.nodes[node.id] = node
    for row in _records(directory / "edges.jsonl"):
        edge = Edge(**row)
        if edge.kind not in RELATIONSHIPS or edge.id in world.edges or edge.start not in world.nodes or edge.end not in world.nodes:
            raise ImportRefused("Invalid/duplicate relationship or endpoint")
        _properties(edge.properties)
        if edge.properties.get("edge_id") != edge.id or edge.properties.get("synthetic") is not True:
            raise ImportRefused("Relationship identity/provenance envelope mismatch")
        world.edges[edge.id] = edge
    for row in _records(directory / "gold.jsonl"):
        world.gold[row["shipment_id"]] = row
    if manifest != world.manifest():
        raise ImportRefused("Manifest counts, versions, configuration or canonical content hashes differ")
    items = list(_records(directory / "feed.jsonl"))
    feed_manifest = json.loads((directory / "feed_manifest.json").read_text(encoding="utf-8"))
    if feed_manifest["hash"] != digest(items) or feed_manifest["items"] != len(items):
        raise ImportRefused("Feed content differs from its manifest")
    validation = validate_live_bundle(world, items)
    saved = json.loads((directory / "validation.json").read_text(encoding="utf-8"))
    if canonical(_jsonable(validation)) != canonical(saved):
        raise ImportRefused("Saved validation report differs from recomputed report")
    gate = json.loads((directory / "world_validation.json").read_text(encoding="utf-8"))
    foundation = gate["export"]["foundation"]
    if not foundation["pass"] or set(validation_codes(validation)) - set(foundation["error_codes"]) or not gate.get("pass"):
        raise ImportRefused("World validation gate failed")
    return Bundle(world, manifest, digest(manifest), validation), items


def validation_codes(validation):
    return sorted({e["code"] for e in validation["errors"]})


# ---------------------------------------------------------------------- database
def world_guard(database):
    if not database.startswith(WORLD_PREFIX) or database in NEVER:
        raise ImportRefused(f"World imports only target databases named {WORLD_PREFIX}*")
    return database


def _driver():
    import config
    from neo4j import GraphDatabase
    return GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD)), config


WORLD_INDEXES = (
    ("world_scan_device_time", "ScanEvent", ("device_ref", "occurred_at")),
    ("world_scan_container", "ScanEvent", ("container_id",)),
    ("world_custody_facility_time", "CustodyEvent", ("facility_id", "occurred_at")),
    ("world_custody_trip", "CustodyEvent", ("trip_id",)),
    ("world_custody_route", "CustodyEvent", ("route_run_id",)),
    ("world_custody_source", "CustodyEvent", ("source_event_id",)),
    ("world_attempt_route", "DeliveryAttempt", ("route_run_id",)),
    ("world_assignment_route", "VehicleAssignment", ("route_run_id",)),
    ("world_assignment_trip", "VehicleAssignment", ("trip_id",)),
    ("world_assignment_session", "VehicleAssignment", ("session_id",)),
    ("world_heartbeat_device_time", "DeviceHeartbeat", ("device_id", "occurred_at")),
    ("world_gps_vehicle_time", "GPSObservation", ("vehicle_id", "occurred_at")),
    ("world_throughput_facility", "FacilityThroughput", ("facility_id",)),
    ("world_trip_event_trip", "TripEvent", ("trip_id",)),
    ("world_comm_route_time", "CommunicationEvent", ("carrier_route", "occurred_at")),
    ("world_proof_attempt", "DeliveryProof", ("attempt_id",)),
    ("world_contact_attempt", "ContactAttempt", ("attempt_id",)),
    ("world_auth_attempt", "AuthenticationEvidence", ("attempt_id",)),
    ("world_signature_attempt", "SignatureEvidence", ("attempt_id",)),
    ("world_photo_attempt", "PhotoEvidence", ("attempt_id",)),
    ("world_handoff_attempt", "HandoffEvidence", ("attempt_id",)),
    ("world_manifest_supersedes", "Manifest", ("supersedes_id",)),
)


def create_indexes(driver, database):
    with driver.session(database=database) as session:
        for name, label, props in WORLD_INDEXES:
            session.run(f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON ({', '.join('n.' + p for p in props)})").consume()
        session.run("CALL db.awaitIndexes(300)").consume()
    return [name for name, _, _ in WORLD_INDEXES]


def apply(directory, database, replace=False):
    from dataset_v2.live_bundle import load_feed
    world_guard(database)
    driver, config = _driver()
    protected = (config.SHIPMENT_DATABASE, config.NEO4J_DATABASE, config.CHAT_DATABASE, *NEVER)
    target_guard(config.NEO4J_URI, database, protected)
    started = time.perf_counter()
    bundle, items = read_world_bundle(directory)
    read_seconds = round(time.perf_counter() - started, 1)
    with driver:
        if replace:
            with driver.session(database="system") as session:
                session.run(f"CREATE OR REPLACE DATABASE `{database}` WAIT 120 SECONDS").consume()
        with driver.session(database="system", default_access_mode="READ") as session:
            exists = any(r["name"] == database for r in session.run("SHOW DATABASES YIELD name RETURN name"))
        state = None
        if exists:
            with driver.session(database=database, default_access_mode="READ") as session:
                row = session.run("MATCH (m:_V2Import) RETURN m.state AS state, m.manifest_hash AS hash").single()
            if row and (row["hash"] != bundle.manifest_hash) :
                raise ImportRefused("Target holds a different import; use --replace to recreate this world database")
            state = row["state"] if row else None
        t0 = time.perf_counter()
        report = {"status": "already_complete"} if state == "COMPLETE" else apply_bundle(
            driver, bundle, uri=config.NEO4J_URI, database=database, protected=protected)
        if report["status"] == "resumable_incomplete":
            return report
        report.update(load_feed(driver, database, bundle, items))
        report["indexes"] = create_indexes(driver, database)
        report["seconds"] = {"read_and_validate": read_seconds, "import_and_feed": round(time.perf_counter() - t0, 1)}
    return {**report, "database": database, "gold_imported": False, "truth_imported": False}


# ---------------------------------------------------------------------- checks
def _timed(session, query, repeats=5, **params):
    session.run(query, **params).consume()  # warm-up
    times, rows = [], None
    for _ in range(repeats):
        t0 = time.perf_counter()
        rows = [dict(r) for r in session.run(query, **params)]
        times.append((time.perf_counter() - t0) * 1000)
    return rows, {"median_ms": round(statistics.median(times), 2), "max_ms": round(max(times), 2), "runs": repeats}


REFERENCE_FIELDS = ("device_ref", "vehicle_id", "driver_id", "trip_id", "container_id", "route_run_id", "facility_id", "depot_id",
                    "route_manifest_ref", "provider_id", "session_id", "assignment_id", "package_id", "source_event_id", "attempt_id",
                    "proof_id", "receipt_id", "address_version_id", "used_address_version_id", "segment_id", "journey_id",
                    "from_facility_id", "to_facility_id", "lane_id", "city_id", "recipient_id", "authorized_recipient_id",
                    "supersedes_id", "address_id", "pin_id", "authentication_id", "signature_id", "photo_id", "handoff_id",
                    "origin_facility_id", "destination_facility_id", "base_facility_id", "operator_org_id", "type_id", "service_id",
                    "policy_id", "route_id", "current_address_version_id", "sender_id")


def cypher_checks(directory, database, ingest=False, truth_root=None):
    world_guard(database)
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    expected_kinds = Counter(json.loads(line)["kind"] for line in (directory / "nodes.jsonl").open(encoding="utf-8"))
    expected_rels = Counter(json.loads(line)["kind"] for line in (directory / "edges.jsonl").open(encoding="utf-8"))
    feed_count = sum(1 for _ in (directory / "feed.jsonl").open(encoding="utf-8"))
    physical = {name: list(_records(directory / "private" / f"{name}.jsonl")) for name in ("devices", "messaging_outages")}
    labels = read_truth_labels(truth_root, manifest["dataset_id"])
    driver, config = _driver()
    out = {"database": database, "dataset_id": manifest["dataset_id"], "manifest_counts": manifest["counts"]}
    with driver:
        with driver.session(database=database, default_access_mode="READ") as session:
            kinds = {r["kind"]: r["n"] for r in session.run(
                "MATCH (n:V2Entity) WHERE NOT n:LiveIngested UNWIND [l IN labels(n) WHERE NOT l IN ['V2Entity','Facility','ExpectedJourney','ExpectedRoute']] AS kind "
                "RETURN kind, count(*) AS n")}
            rels = {r["kind"]: r["n"] for r in session.run("MATCH ()-[r]->() WHERE r.dataset_id = $d AND r.source_ref <> 'live-ingestion-1' "
                                                          "RETURN type(r) AS kind, count(*) AS n", d=manifest["dataset_id"])}
            feed = session.run("MATCH (f:ProviderFeedItem) RETURN count(f) AS n, count(DISTINCT f.feed_id) AS ids").single()
            out["counts"] = {"nodes_total": sum(kinds.values()), "nodes_expected": manifest["counts"]["nodes"],
                             "edges_total": sum(rels.values()), "edges_expected": manifest["counts"]["edges"],
                             "feed_items": feed["n"], "feed_items_expected": feed_count,
                             "node_kinds_match": dict(sorted(kinds.items())) == dict(sorted(expected_kinds.items())),
                             "relationship_types_match": dict(sorted(rels.items())) == dict(sorted(expected_rels.items())),
                             "by_kind": dict(sorted(kinds.items())), "by_relationship": dict(sorted(rels.items())),
                             "mismatched_kinds": {k: [kinds.get(k, 0), expected_kinds.get(k, 0)] for k in set(kinds) | set(expected_kinds)
                                                  if kinds.get(k, 0) != expected_kinds.get(k, 0)},
                             "mismatched_relationships": {k: [rels.get(k, 0), expected_rels.get(k, 0)] for k in set(rels) | set(expected_rels)
                                                          if rels.get(k, 0) != expected_rels.get(k, 0)}}
            out["pass_counts"] = (out["counts"]["nodes_total"] == out["counts"]["nodes_expected"] and out["counts"]["edges_total"] == out["counts"]["edges_expected"]
                                  and feed["n"] == feed_count and out["counts"]["node_kinds_match"] and out["counts"]["relationship_types_match"])
            out["referential"] = referential(session)
            out["temporal"] = temporal(session)
            out["schema"] = {"indexes": sorted(r["name"] for r in session.run("SHOW INDEXES YIELD name RETURN name")),
                             "constraints": sorted(r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name RETURN name"))}
            v2_split = {json.loads(line)["shipment_id"]: json.loads(line)["split"] for line in (directory / "gold.jsonl").open(encoding="utf-8")}
            history_sids = {sid for sid, split in v2_split.items() if split == "history"}
            live_sids = {sid for sid, split in v2_split.items() if split == "development"}
            out["traversals_imported"] = traversals(session, physical, manifest["dataset_id"], live=False, scope_sids=history_sids)
            out["precedents"] = precedents(session, manifest["dataset_id"])
            out["isolation"] = database_isolation(session, labels)
        if ingest:
            out["ingestion"] = ingest_all(driver, database, manifest["dataset_id"])
            with driver.session(database=database, default_access_mode="READ") as session:
                out["referential_after_ingestion"] = referential(session)
                out["temporal_after_ingestion"] = temporal(session)
                out["traversals_live"] = traversals(session, physical, manifest["dataset_id"], live=True, scope_sids=live_sids)
                out["isolation_after_ingestion"] = database_isolation(session, labels)
            reset(driver, database, manifest["dataset_id"])
            with driver.session(database=database, default_access_mode="READ") as session:
                remaining = session.run("MATCH (n:LiveIngested) RETURN count(n) AS n").single()["n"]
                pending = session.run("MATCH (f:ProviderFeedItem) WHERE f.status <> 'PENDING' RETURN count(f) AS n").single()["n"]
            out["reset_after_ingestion"] = {"live_ingested_nodes_left": remaining, "feed_items_not_pending": pending}
    out["pass"] = bool(out["pass_counts"] and out["referential"]["pass"] and out["temporal"]["pass"] and out["isolation"]["pass"]
                       and (not ingest or (out["ingestion"]["rejected"] == 0 and out["referential_after_ingestion"]["pass"]
                                           and out["temporal_after_ingestion"]["pass"] and out["isolation_after_ingestion"]["pass"])))
    return out


DB_FIXTURE_LABELS = {"Case", "Exception", "AnalysisRun", "Recommendation", "Review", "OperatorDecision", "ActionExecution", "Resolution",
                     "Outcome", "AuditEvent", "Notification"}


def database_isolation(session, labels):
    """Addendum B2: every string in the database (node and relationship properties, provider feed payloads included)
    is scanned for the truth canary, every mechanism id and every mechanism name. Names that are also catalogue
    cause codes (WRONG_GATE, RECIPIENT_UNAVAILABLE) are allowed only on derived case and history fixture nodes,
    where derive and the history record emit catalogue codes; ids and the canary are allowed nowhere."""
    import re
    from operations.agents import CAUSES
    from world.mechanisms import MECHANISM_TYPES
    if labels is None:
        return {"pass": False, "error": "truth directory not found: the canary and mechanism ids cannot be checked"}
    canaries = [c.lower() for c in labels["canary"]]
    ids = set(labels["mechanism_ids"])
    id_re = re.compile(r"W1M-\d{5}")
    names = sorted({t.lower() for t in MECHANISM_TYPES} | {t.lower().replace("_", " ") for t in MECHANISM_TYPES})
    cause_names = {c.lower() for c in CAUSES} | {c.lower().replace("_", " ") for c in CAUSES}
    hits, scanned = Counter(), Counter()

    def scan(origin, value, fixture):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)   # Neo4j temporal values as text.
        lower = text.lower()
        scanned[origin] += 1
        for canary in canaries:
            if canary in lower:
                hits["canary@" + origin] += 1
        for match in id_re.findall(text):
            hits[("mechanism_id@" if match in ids else "mechanism_id_pattern@") + origin] += 1
        for name in names:
            if name in lower and not (fixture and name in cause_names):
                hits[name + "@" + origin] += 1

    started = time.perf_counter()
    for record in session.run("MATCH (n) RETURN labels(n) AS labels, properties(n) AS p"):
        kinds = set(record["labels"])
        origin = "ProviderFeedItem" if "ProviderFeedItem" in kinds else next((k for k in sorted(kinds) if k not in ("V2Entity", "LiveIngested")), "node")
        scan("node:" + origin, record["p"], bool(kinds & DB_FIXTURE_LABELS))
    for record in session.run("MATCH (a)-[r]->(b) RETURN type(r) AS t, properties(r) AS p, labels(a) AS la"):
        scan("rel:" + record["t"], record["p"], record["p"].get("provenance") == "DERIVED" or bool(set(record["la"]) & DB_FIXTURE_LABELS))
    return {"pass": not hits, "canaries": len(canaries), "mechanism_ids": len(ids), "mechanism_names": len(names),
            "records_scanned": dict(sorted(scanned.items())), "records_total": sum(scanned.values()), "hits": dict(sorted(hits.items())),
            "seconds": round(time.perf_counter() - started, 1)}


def referential(session):
    unresolved = {}
    checked = {}
    for field in REFERENCE_FIELDS:
        row = session.run(f"MATCH (n:V2Entity) WHERE n.{field} IS NOT NULL "
                          f"WITH n, CASE WHEN n.{field} IS :: LIST<ANY> THEN n.{field} ELSE [n.{field}] END AS refs "
                          "UNWIND refs AS ref WITH ref WHERE ref STARTS WITH 'DEMO-' "
                          "OPTIONAL MATCH (m:V2Entity {entity_id: ref}) "
                          "RETURN count(ref) AS refs, count(CASE WHEN m IS NULL THEN 1 END) AS missing").single()
        checked[field] = row["refs"]
        if row["missing"]:
            unresolved[field] = row["missing"]
    edges = session.run("MATCH (a:V2Entity)-[r]->(b:V2Entity) WHERE r.holdout_group IS NOT NULL "
                        "AND ((a.holdout_group IS NOT NULL AND a.holdout_group <> r.holdout_group) OR (b.holdout_group IS NOT NULL AND b.holdout_group <> r.holdout_group)) "
                        "RETURN count(r) AS n").single()["n"]
    return {"pass": not unresolved and edges == 0, "references_checked": checked, "unresolved": unresolved,
            "cross_shipment_edges": edges}


def temporal(session):
    checks = {
        "evidence_recorded_before_occurred": "MATCH (n:V2Entity) WHERE n.occurred_at IS NOT NULL AND n.recorded_at < n.occurred_at RETURN count(n) AS n",
        "milestone_window_inverted": "MATCH (m:ExpectedMilestone) WHERE m.latest_at <= m.earliest_at RETURN count(m) AS n",
        "interval_inverted": "MATCH (n:V2Entity) WHERE n.start_at IS NOT NULL AND n.end_at IS NOT NULL AND n.end_at <= n.start_at RETURN count(n) AS n",
        "assignment_interval_inverted": "MATCH (a:VehicleAssignment) WHERE a.valid_to <= a.valid_from RETURN count(a) AS n",
        # Live (development) shipments are imported with booking-time records only; everything later arrives as feed messages.
        "development_records_imported_after_booking": "MATCH (n:V2Entity {split:'development'}) WHERE NOT n:LiveIngested AND n.holdout_group IS NOT NULL "
                                                      "MATCH (s:Shipment {entity_id:n.holdout_group}) WHERE n.recorded_at > s.recorded_at RETURN count(n) AS n",
        "custody_before_its_source_scan_recorded": "MATCH (c:CustodyEvent)-[:OBSERVED_BY]->(s:ScanEvent) WHERE c.recorded_at < s.recorded_at RETURN count(c) AS n",
        "feed_delivered_before_event": "MATCH (f:ProviderFeedItem) WITH f, f.deliver_at AS d MATCH (n:V2Entity {entity_id:f.source_event_id}) "
                                       "WHERE n.occurred_at > d RETURN count(f) AS n",
        "ingested_before_occurred": "MATCH (n:LiveIngested) WHERE datetime(n.ingested_at) < n.occurred_at RETURN count(n) AS n",
    }
    out = {name: session.run(query).single()["n"] for name, query in checks.items()}
    return {"pass": all(v == 0 for v in out.values()), **out}


def traversals(session, physical, dataset_id, live, scope_sids=()):
    """Representative cross-shipment lookups (the ones Stage 2 tools will need), timed. Example windows come from the
    label-free physical state: the device-offline window with most buffered records of shipments in scope (imported
    history, or live shipments after ingestion) and the longest messaging outage."""
    scope = "n:LiveIngested" if live else "NOT n:LiveIngested"
    out = {}
    scope_sids = set(scope_sids)
    windows = [(device["device_id"], w) for device in physical["devices"] for w in device["offline"]]
    outage = max(windows, key=lambda dw: (sum(r["shipment_id"] in scope_sids for r in dw[1]["buffered_records"]), dw[0], dw[1]["from"]), default=None)
    if outage:
        params = {"d": outage[0], "a": instant(outage[1]["from"]), "b": instant(outage[1]["reconnect_at"])}
        rows, timing = _timed(session, f"MATCH (n:ScanEvent) WHERE n.device_ref = $d AND n.occurred_at >= $a AND n.occurred_at < $b AND {scope} "
                                       "RETURN n.shipment_id AS shipment, count(*) AS scans ORDER BY shipment", **params)
        beats, btiming = _timed(session, "MATCH (h:DeviceHeartbeat) WHERE h.device_id = $d AND h.occurred_at >= $a - duration('PT2H') "
                                         "AND h.occurred_at <= $b + duration('PT1H') RETURN h.occurred_at AS at, h.pending_uploads AS pending ORDER BY at", **params)
        out["same_device_in_window"] = {"device": params["d"], "shipments": len(rows), "scans": sum(r["scans"] for r in rows), **timing}
        out["device_heartbeats_around_window"] = {"beats": len(beats), "max_pending": max((b["pending"] for b in beats), default=None), **btiming}
    route = session.run("MATCH (r:RouteRun)<-[:ON_ROUTE_RUN]-(a:VehicleAssignment) WHERE " + scope.replace("n:", "a:")
                        + " WITH r, count(a) AS n ORDER BY n DESC, r.entity_id LIMIT 1 RETURN r.entity_id AS id").single()
    if route:
        rows, timing = _timed(session, "MATCH (r:RouteRun {entity_id:$r})<-[:ON_ROUTE_RUN]-(a:VehicleAssignment) "
                                       "OPTIONAL MATCH (e:CustodyEvent {route_run_id:$r}) WHERE e.shipment_id = a.shipment_id "
                                       "RETURN a.shipment_id AS shipment, count(e) AS custody_events", r=route["id"])
        out["same_route_run"] = {"route_run": route["id"], "shipments": len(rows), **timing}
    container = session.run("MATCH (c:Container)<-[:IN_CONTAINER]-(s:ScanEvent) WHERE " + scope.replace("n:", "s:")
                            + " WITH c, count(DISTINCT s.package_id) AS n ORDER BY n DESC, c.entity_id LIMIT 1 RETURN c.entity_id AS id").single()
    if container:
        rows, timing = _timed(session, "MATCH (c:Container {entity_id:$c})<-[:IN_CONTAINER]-(s:ScanEvent) "
                                       "RETURN DISTINCT s.package_id AS package, s.shipment_id AS shipment", c=container["id"])
        out["same_container"] = {"container": container["id"], "parcels": len(rows), "shipments": len({r["shipment"] for r in rows}), **timing}
    trip = session.run("MATCH (t:Trip)<-[:ON_TRIP]-(e:CustodyEvent) WHERE " + scope.replace("n:", "e:")
                       + " WITH t, count(DISTINCT e.shipment_id) AS n ORDER BY n DESC, t.entity_id LIMIT 1 RETURN t.entity_id AS id").single()
    if trip:
        rows, timing = _timed(session, "MATCH (t:Trip {entity_id:$t})<-[:ON_TRIP]-(e:CustodyEvent) "
                                       "OPTIONAL MATCH (t)-[:HAS_TRIP_EVENT]->(ev:TripEvent) "
                                       "RETURN count(DISTINCT e.shipment_id) AS shipments, count(DISTINCT ev) AS trip_events", t=trip["id"])
        out["same_trip"] = {"trip": trip["id"], **rows[0], **timing}
    facility = session.run("MATCH (n:CustodyEvent) WHERE " + scope + " AND n.facility_id STARTS WITH 'DEMO-DEPOT' "
                           "WITH n.facility_id AS f, min(n.occurred_at) AS first RETURN f, first ORDER BY f LIMIT 1").single()
    if facility:
        params = {"f": facility["f"], "a": facility["first"], "b": facility["first"] + __import__("datetime").timedelta(hours=12)}
        rows, timing = _timed(session, "MATCH (n:CustodyEvent) WHERE n.facility_id = $f AND n.occurred_at >= $a AND n.occurred_at < $b "
                                       "RETURN n.event_type AS event, count(DISTINCT n.shipment_id) AS shipments ORDER BY event", **params)
        out["same_facility_in_window"] = {"facility": params["f"], "window_hours": 12, "by_event": {r["event"]: r["shipments"] for r in rows}, **timing}
    sms = max(physical["messaging_outages"], key=lambda w: (instant(w["until"]) - instant(w["from"]), w["carrier_route"]), default=None)
    if sms:
        params = {"r": sms["carrier_route"], "a": instant(sms["from"]) - __import__("datetime").timedelta(hours=1),
                  "b": instant(sms["until"]) + __import__("datetime").timedelta(hours=1)}
        rows, timing = _timed(session, "MATCH (c:CommunicationEvent) WHERE c.carrier_route = $r AND c.occurred_at >= $a AND c.occurred_at < $b "
                                       "RETURN c.delivery_status AS status, count(*) AS n ORDER BY status", **params)
        out["same_sms_route_in_window"] = {"carrier_route": params["r"], "by_status": {r["status"]: r["n"] for r in rows}, **timing}
    return out


def precedents(session, dataset_id):
    from operations.read_model import PRECEDENTS
    from dataset_v2.context import OBSERVATIONS
    from operations.agents import CAUSES
    rows, timing = _timed(session, PRECEDENTS, dataset_id=dataset_id, shipment_id="DEMO-NONE", codes=sorted(CAUSES),
                          snapshot=instant("2030-01-01T00:00:00+00:00"), candidate_limit=200, precedent_limit=200,
                          evidence_kinds=sorted(OBSERVATIONS), repeats=3)
    items = [r["item"] for r in rows]
    return {"precedents_returned": len(items), "by_action": dict(Counter(i["action_type"] for i in items)),
            "by_success": dict(Counter(str(i["success"]) for i in items)), "by_exception_code": dict(Counter(i["exception_code"] for i in items)), **timing}


def ingest_all(driver, database, dataset_id):
    from operations.ingestion import Gateway
    gateway = Gateway(driver, database, dataset_id)
    with driver.session(database=database, default_access_mode="READ") as session:
        last = session.run("MATCH (f:ProviderFeedItem) RETURN max(f.deliver_at) AS t").single()["t"].to_native()
    totals = Counter()
    started = time.perf_counter()
    while True:
        batch = gateway.ingest_due(last.isoformat(), limit=1000)
        for key in ("ingested", "duplicate", "conflicting_duplicate", "rejected", "messages"):
            totals[key] += batch[key]
        if batch["messages"] < 1000:
            break
    return {**totals, "seconds": round(time.perf_counter() - started, 1), "clock": iso(last)}


def reset(driver, database, dataset_id):
    from operations.ingestion import Gateway
    Gateway(driver, database, dataset_id).reset()


# ---------------------------------------------------------------------- main
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--total", type=int, default=600)
    export.add_argument("--days", type=int, default=6)
    export.add_argument("--seed", type=int, default=WorldConfig.seed)
    export.add_argument("--dataset-id", default=WorldConfig.dataset_id)
    export.add_argument("--with-heldout", action="store_true")
    export.add_argument("--eval-dir", type=Path)
    export.add_argument("--determinism", action="store_true")
    export.add_argument("--truth-root", type=Path, help="truth-label root outside the repository (default SUHAIL_EVAL_TRUTH_ROOT or "
                                                        "C:\\Projects\\suhail-eval-truth)")
    export.add_argument("--tell-seed", type=int, help="seed of the second world for the pre-run tell test (default seed + 1)")
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("directory", type=Path)
    apply_cmd.add_argument("--database", required=True)
    apply_cmd.add_argument("--replace", action="store_true")
    check = sub.add_parser("check")
    check.add_argument("directory", type=Path)
    check.add_argument("--database", required=True)
    check.add_argument("--out", type=Path)
    check.add_argument("--ingest", action="store_true")
    check.add_argument("--truth-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "export":
        from world.pipeline import run_export
        result = run_export(WorldConfig(total=args.total, days=args.days, seed=args.seed, dataset_id=args.dataset_id), args.output,
                            with_heldout=args.with_heldout, eval_dir=args.eval_dir, determinism=args.determinism,
                            truth_root=args.truth_root, tell_seed=args.tell_seed)
        print(canonical(result))
        if not result["pass"]:
            raise SystemExit(1)
    elif args.command == "apply":
        print(canonical(_jsonable(apply(args.directory, args.database, replace=args.replace))))
    else:
        result = cypher_checks(args.directory, args.database, ingest=args.ingest, truth_root=args.truth_root)
        text = json.dumps(_jsonable(result), indent=1, ensure_ascii=False, sort_keys=True)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
        print(canonical({"pass": result["pass"], "counts_pass": result["pass_counts"], "referential": result["referential"]["pass"],
                         "temporal": result["temporal"]["pass"], "isolation": result["isolation"]["pass"]}))


if __name__ == "__main__":
    main()
