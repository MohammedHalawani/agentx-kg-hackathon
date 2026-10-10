"""World-1 CLI: export a validated bundle, import it into an isolated world database, run Cypher checks.

  uv run python -m world.export export --output ../artifacts/world/world-1-small-r2 [--total 600 --days 8 --seed 20261010]
                                       [--with-heldout] [--eval-dir ../docs/evals/2026-10-10_world1_small] [--determinism]
  uv run python -m world.export apply ../artifacts/world/world-1-small-r2 --database shipments-v2-world-1-small [--replace]
  uv run python -m world.export check ../artifacts/world/world-1-small-r2 --database shipments-v2-world-1-small
                                      --out ../docs/evals/2026-10-10_world1_small/cypher.json [--ingest]

export   refuses an existing directory; writes the V2 bundle (nodes, edges, gold, feed, manifest, validation,
         statistics, feed_manifest) plus world_manifest.json and world_validation.json. The bundle holds only what is
         imported or fed, and nothing that names a mechanism's outcome. Two private outputs go OUTSIDE the repository:
           truth labels (mechanisms, causes, discrimination specs, the canary, the monitor replay per shipment) to
             <truth-root>/<dataset_id>/, default C:\\Projects\\suhail-eval-truth\\<export name>\\<dataset_id>\\, with one
             sub-directory per export (development, held_out): a spec cites only records that export contains;
           the physical world state the Stage 4 operational simulator reads (parcel and container locations, device
             buffers and reconnect times, recipient availability and correct addresses, trips, routes), restricted
             to that export's shipments, to <state-root>/<dataset_id>/<live split>/, default
             C:\\Projects\\suhail-sim-state\\<export name>\\... . Causes can be worked out from it, so it is protected by
             where it lives and by who may open it, not by a scan.
         --with-heldout also writes <output>-heldout, where the held-out days are live and everything recorded
         before their start is imported.
apply    imports into a database whose name starts with shipments-v2-world- (never any other), reusing
         dataset_v2.load.apply_bundle, load_feed and target_guard. --replace recreates that database first.
check    read-only integrity queries, timed cross-shipment traversals through the one time-correct predicate
         (recorded_at <= as_of and occurred_at <= as_of) and the database isolation scan (canary, mechanism ids and
         names); --ingest additionally replays the whole feed through the real ingestion gateway in six-hour steps
         to the end of the horizon, checks at a mid-simulation instant that no traversal returns a record from after
         it, repeats the checks on live evidence, and resets the live session afterwards (Gateway.reset), leaving
         the database as imported.
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
from world.config import DEFAULT_STATE_ROOT, DEFAULT_TRUTH_ROOT, WORLD_VERSION, WorldConfig, WorldV2Config

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


def private_physical(build, live_split="development"):
    """The physical world state the Stage 4 operational simulator reads, for one export: parcel and container
    locations over time, device connectivity and buffers with reconnect times, scale offsets, facility capacity,
    trips and routes as they ran, recipient availability and correct addresses, messaging outages, traffic.

    Restricted to the shipments of that export (earlier booking days and the live split; never later days). Every
    device is listed, most with no window, so being in the file says nothing. It names no cause code, mechanism or
    label, but it records what really happened: causes can be worked out from it. It is therefore written outside
    the repository, to the simulator-only root, and no runtime module but the simulator may open it."""
    from world.build import labels_for
    sim, plan, net, obs = build.sim, build.plan, build.network, build.observer
    labels = labels_for(live_split)
    included = {sid for sid, s in build.shipments.items() if labels[s.split]}
    mine = lambda pid: pid.rsplit("-PKG-", 1)[0] in included
    out = {}
    out["parcels"] = [{"package_id": pid, "shipment_id": st.shipment.sid, "timeline": st.timeline, "custody": st.custody,
                       "status": st.status, "attempts": st.attempts, "true_kg": st.parcel.true_kg, "declared_kg": st.parcel.declared_kg,
                       "manifest_barcode": st.parcel.barcode, "label_barcode": st.parcel.label_barcode}
                      for pid, st in sorted(sim.p.items()) if mine(pid)]
    out["containers"] = [{"container_id": cid, "origin": c.origin, "destination": c.depot, "created_at": c.created_at, "sealed_at": c.sealed_at,
                          "opened_at": c.opened_at, "timeline": c.timeline, "parcels": [pid for pid in c.parcels if mine(pid)]}
                         for cid, c in sorted(sim.containers.items()) if any(mine(pid) for pid in c.parcels)]
    kept_containers = {row["container_id"] for row in out["containers"]}
    loss_windows = {mid: (device, start) for device, windows in plan.device_loss.items() for start, end, fraction, mid, release in windows}
    stuck = defaultdict(list)
    for nid, meta in sorted(obs.records.items()):
        if not meta["sid"] or meta["sid"] not in included:
            continue
        for mid in meta["mech"]:
            if mid in loss_windows:
                stuck[loss_windows[mid]].append({"record": nid, "shipment_id": meta["sid"]})
    devices = []
    for device in sorted(set(net.devices) | set(plan.scale_drift)):
        info = net.devices.get(device)
        records = sorted((r for r in obs.device_records.get(device, []) if r[0] is not None and obs.records[r[2]]["sid"] in included),
                         key=lambda r: (r[0], r[2]))
        devices.append({
            "device_id": device, "kind": info.kind if info else "SCALE", "telemetry": info.telemetry if info else "NONE",
            "offline": [{"from": a, "reconnect_at": b,
                         "buffered_records": [{"record": nid, "shipment_id": obs.records[nid]["sid"]} for occ, rec, nid in records if a <= occ < b]}
                        for a, b, _ in plan.device_down.get(device, [])],
            "upload_stuck": [{"from": a, "until": b, "share_stuck": f, "uploaded_at": release, "stuck_records": stuck.get((device, a), [])}
                             for a, b, f, _, release in plan.device_loss.get(device, [])],
            "scale_offset": [{"from": a, "until": b, "relative_offset": f} for a, b, f, _ in plan.scale_drift.get(device, [])]})
    out["devices"] = devices
    out["facility_capacity"] = [{"facility_id": f, "from": a, "until": b, "capacity_factor": factor}
                                for f, rows in sorted(plan.backlog.items()) for a, b, factor, _ in rows]
    out["trips"] = [{"trip_id": tid, "vehicle_id": t.plan.vehicle, "scheduled_departure": t.plan.scheduled_departure,
                     "scheduled_arrival": t.plan.scheduled_arrival, "departed_at": t.departed_at, "arrived_at": t.arrived_at,
                     "stopped": t.breakdown, "containers": [cid for cid in t.containers if cid in kept_containers]}
                    for tid, t in sorted(sim.trips.items()) if t.departed_at and not t.cancelled
                    and (any(cid in kept_containers for cid in t.containers) or any(mine(pid) for pid in t.parcels))]
    out["routes"] = [{"route_run_id": rid, "depot_id": r.depot, "date": r.date, "driver_id": r.driver, "vehicle_id": r.vehicle, "device_id": r.device,
                      "login_at": r.login_at, "departed_at": r.departed_at, "returned_at": r.returned_at,
                      "parcels": [pid for pid in r.parcels if mine(pid)], "loaded": [pid for pid in r.loaded if mine(pid)],
                      "kept_by_driver": r.retained, "passed_to_other_driver": [pid for pid in r.handed_out if mine(pid)],
                      "received_from_other_driver": [pid for pid in r.handed_in if mine(pid)]}
                     for rid, r in sorted(sim.routes.items()) if any(mine(pid) for pid in r.parcels)]
    recipients = []
    for sid, s in sorted(build.shipments.items()):
        if sid not in included:
            continue
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
    events = []
    for e in sorted(sim.events, key=lambda e: (e["t"], e["type"], str(e.get("pid") or e.get("sid") or e.get("route") or ""))):
        row = {**_clean(e), "type": EVENT_NAMES.get(e["type"], e["type"])}
        if "parcels" in row:
            row["parcels"] = [pid for pid in row["parcels"] if mine(pid)]
        keep = (mine(row["pid"]) if row.get("pid") else row["sid"] in included if row.get("sid") else bool(row.get("parcels")))
        if keep:
            events.append(row)
    out["events"] = events
    return out


def truth_records(build):
    """World-level truth (B1b): the mechanism instances and the private record index. Written only to the external truth
    directory. Per-shipment truth rows are per export (see write_truth)."""
    sim, plan = build.sim, build.plan
    mechanisms = []
    for mid, mech in sorted(plan.items.items()):
        mechanisms.append({"mechanism_id": mid, "type": mech.type, "subtype": mech.subtype, "origin": mech.origin,
                           "started_at": mech.started_at, "ended_at": mech.ended_at, "params": mech.params,
                           "caused_shipments": sorted(build.caused.get(mid, set())), "caused_parcels": sorted(sim.touch.get(mid, set())),
                           "exposed_shipments": sorted(build.exposed.get(mid, set()))})
    index = [{"evidence_id": nid, **meta} for nid, meta in sorted(build.observer.records.items())]
    return {"mechanisms": mechanisms, "record_index": index, "acts": sim.acts,
            "physical_events": sorted(sim.events, key=lambda e: (e["t"], e["type"], str(e.get("pid") or e.get("sid") or e.get("route") or "")))}


def repo_root():
    return Path(__file__).resolve().parents[2]


def _outside_repository(target, what):
    repo = repo_root()
    if target == repo or repo in target.parents or "artifacts" in {p.name.lower() for p in [target, *target.parents]}:
        raise ValueError(f"{what} must live outside the repository and outside artifacts/")
    return target


def export_name(output):
    """The name private outputs are filed under: the bundle directory's name (without a held-out suffix)."""
    return Path(output).name.removesuffix("-heldout")


def truth_directory(root, dataset_id, name=None):
    """<root>/<dataset_id>, refusing anything inside the repository or under an artifacts directory. With no explicit
    root: SUHAIL_EVAL_TRUTH_ROOT, else <default root>/<export name>."""
    import os
    root = root or os.environ.get("SUHAIL_EVAL_TRUTH_ROOT") or (Path(DEFAULT_TRUTH_ROOT) / name if name else DEFAULT_TRUTH_ROOT)
    return _outside_repository(Path(root).resolve() / dataset_id, "Truth labels")


def state_directory(root, dataset_id, name=None):
    """<root>/<dataset_id> for the simulator's physical world state, with the same refusals as the truth directory."""
    import os
    root = root or os.environ.get("SUHAIL_SIM_STATE_ROOT") or (Path(DEFAULT_STATE_ROOT) / name if name else DEFAULT_STATE_ROOT)
    return _outside_repository(Path(root).resolve() / dataset_id, "The physical world state")


def write_truth(build, root, replays, precedents, *, name=None, report=None):
    """Write the truth-label directory once per build; refuses an existing one (truth is immutable like exports).

    <dir>/mechanisms.jsonl, record_index.jsonl, acts.jsonl, physical_events.jsonl, precedents.json, manifest.json
    <dir>/<live split>/truth.jsonl, truth_manifest.json, monitor_replay.json, monitor_replay_rows.jsonl"""
    from world.build import truth_manifest
    target = truth_directory(root, build.config.dataset_id, name)
    if target.exists():
        raise ValueError(f"Choose a new truth root or remove {target}; truth directories are immutable")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".truth-stage-", dir=target.parent) as directory:
        stage = Path(directory) / "truth"
        stage.mkdir()
        for file_name, rows in truth_records(build).items():
            _write_jsonl(stage / f"{file_name}.jsonl", rows)
        hashes = {}
        for split, (imported, items, truth, live_start) in sorted(build.exports.items()):
            folder = stage / split
            folder.mkdir()
            rows = [truth[k] for k in sorted(truth)]
            _write_jsonl(folder / "truth.jsonl", rows)
            _write_json(folder / "truth_manifest.json", truth_manifest(build, split, truth))
            hashes[split] = digest(rows)
            if split in replays:
                _write_json(folder / "monitor_replay.json", replay_summary(replays[split]))
                _write_jsonl(folder / "monitor_replay_rows.jsonl", ({"shipment_id": sid, **row} for sid, row in sorted(replays[split]["shipments"].items())))
        _write_json(stage / "precedents.json", precedents)
        if report is not None:
            _write_json(stage / "validation.json", {k: v for k, v in report.items() if k != "exports"}
                        | {"exports": {s: {k: v for k, v in e.items() if k != "foundation_raw"} for s, e in report["exports"].items()}})
        from world.truth import TRUTH_SCHEMA, canary_token
        _write_json(stage / "manifest.json", {"dataset_id": build.config.dataset_id, "seed": build.config.seed, "world_version": WORLD_VERSION,
                                              "truth_schema": TRUTH_SCHEMA, "canary": canary_token(build.config),
                                              "exports": sorted(build.exports), "truth_hashes": hashes,
                                              "note": "Truth labels for evaluation only. Never imported; never read by backend or operations code."})
        stage.rename(target)
    return str(target)


def write_state(build, root, *, name=None):
    """Write the simulator's physical world state, one folder per export; refuses an existing directory."""
    target = state_directory(root, build.config.dataset_id, name)
    if target.exists():
        raise ValueError(f"Choose a new state root or remove {target}; state directories are immutable")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".state-stage-", dir=target.parent) as directory:
        stage = Path(directory) / "state"
        stage.mkdir()
        for split in sorted(build.exports):
            folder = stage / split
            folder.mkdir()
            for file_name, rows in private_physical(build, split).items():
                _write_jsonl(folder / f"{file_name}.jsonl", rows)
        (stage / "README.txt").write_text(
            "Physical world state for the Stage 4 operational simulator, one folder per export, restricted to that export's "
            "shipments: parcel and container locations, device buffers and reconnect times, recipient availability and correct "
            "addresses, trips and routes as they ran. It names no cause, but causes can be worked out from it: never imported, "
            "never shown to the investigator, its tools, the reviewer or any API, and opened by no runtime module but the "
            "simulator. Truth labels live in a separate directory (world/config.py DEFAULT_TRUTH_ROOT).\n", encoding="utf-8")
        stage.rename(target)
    return str(target)


def read_truth_labels(root, dataset_id, name=None):
    """Evaluation tooling only (never backend or operations): canary and mechanism ids for the isolation scans."""
    target = truth_directory(root, dataset_id, name)
    if not (target / "manifest.json").exists():
        return None
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    mechanisms = list(_records(target / "mechanisms.jsonl"))
    return {"canary": [manifest["canary"]], "mechanism_ids": sorted(m["mechanism_id"] for m in mechanisms),
            "mechanism_types": sorted({m["type"] for m in mechanisms}), "directory": str(target)}


def write_bundle(build, live_split, destination, report, replay=None):
    """The importable bundle: nodes, edges, gold, feed and their manifests. Nothing private and nothing that names a
    mechanism's outcome is written here (the replay, the coverage and the tell reports are in the truth directory)."""
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
        feed_manifest = {"feed_version": FEED_VERSION, "network_version": WORLD_VERSION, "items": len(items), "hash": digest(items)}
        for file_name, value in (("manifest", imported.manifest()), ("validation", validation), ("statistics", validation["statistics"]),
                                 ("feed_manifest", feed_manifest), ("world_manifest", world_manifest(build, live_split, imported, items, truth)),
                                 ("world_validation", bundle_gate(report, live_split))):
            _write_json(stage / f"{file_name}.json", value)
        stage.rename(destination)
    return feed_manifest


def bundle_gate(report, live_split):
    """What the bundle carries of the validation: the overall verdict and the checks of the importable data itself."""
    export = report["exports"][live_split]
    slim = lambda section: {k: section[k] for k in ("pass", "checked", "failed_counts") if k in section}
    return {"pass": report["pass"],
            "export": {"foundation": {k: v for k, v in export["foundation"].items() if k in ("pass", "validate_live_bundle_pass", "error_codes", "checks", "feed")}
                       | {"documented_exceptions": slim(export["foundation"]["documented_exceptions"])},
                       "isolation": {k: export["isolation"][k] for k in ("pass", "terms_scanned", "canary_checked", "canary_hits", "mechanism_id_hits", "texts_scanned")}},
            "import_cut": {"pass": report["import_cut"]["pass"], **report["import_cut"]["per_export"][live_split]},
            "physics": slim(report["physics"]), "observation": slim(report["observation"]), "forecasts": slim(report["forecasts"]),
            "determinism": report.get("determinism", {}).get("pass")}


def replay_summary(replay):
    """The monitor replay without per-shipment rows."""
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


def visible(alias):
    """THE time-correct predicate: every cross-shipment lookup (these checks, and every Stage 2 tool) must filter each
    record it returns through it. A record exists for an investigation at as_of only if the gateway had recorded it by
    then and it had happened by then; without it a query reads the future (later uploads of a buffered record, later
    days' route runs)."""
    return f"{alias}.recorded_at <= $as_of AND ({alias}.occurred_at IS NULL OR {alias}.occurred_at <= $as_of)"


def cypher_checks(directory, database, ingest=False, truth_root=None, state_root=None):
    world_guard(database)
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    world_manifest = json.loads((directory / "world_manifest.json").read_text(encoding="utf-8"))
    live_start, end = instant(world_manifest["live_start"]), instant(manifest["as_of"])
    expected_kinds = Counter(json.loads(line)["kind"] for line in (directory / "nodes.jsonl").open(encoding="utf-8"))
    expected_rels = Counter(json.loads(line)["kind"] for line in (directory / "edges.jsonl").open(encoding="utf-8"))
    feed_count = sum(1 for _ in (directory / "feed.jsonl").open(encoding="utf-8"))
    name = export_name(directory)
    state = state_directory(state_root, manifest["dataset_id"], name) / world_manifest["live_split"]
    physical = {file_name: list(_records(state / f"{file_name}.jsonl")) for file_name in ("devices", "messaging_outages")}
    labels = read_truth_labels(truth_root, manifest["dataset_id"], name)
    driver, config = _driver()
    out = {"database": database, "dataset_id": manifest["dataset_id"], "manifest_counts": manifest["counts"], "live_start": iso(live_start)}
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
            out["temporal"] = temporal(session, live_start)
            out["schema"] = {"indexes": sorted(r["name"] for r in session.run("SHOW INDEXES YIELD name RETURN name")),
                             "constraints": sorted(r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name RETURN name"))}
            v2_split = {json.loads(line)["shipment_id"]: json.loads(line)["split"] for line in (directory / "gold.jsonl").open(encoding="utf-8")}
            history_sids = {sid for sid, split in v2_split.items() if split == "history"}
            live_sids = {sid for sid, split in v2_split.items() if split == "development"}
            out["traversals_imported"] = traversals(session, physical, live_start, scope_sids=history_sids)
            out["precedents"] = precedents(session, manifest["dataset_id"])
            out["isolation"] = database_isolation(session, labels)
        if ingest:
            # The feed is replayed in six-hour steps. At a mid-simulation instant the traversals run with the clock
            # there; after the whole feed is in they run again AS OF that instant and must return the same rows, none
            # of them recorded after it.
            middle = live_start + (end - live_start) / 2
            middle = middle.replace(minute=0, second=0, microsecond=0)
            out["ingestion"], at_middle = ingest_all(driver, database, manifest["dataset_id"], live_start, end, middle, physical, live_sids)
            with driver.session(database=database, default_access_mode="READ") as session:
                out["referential_after_ingestion"] = referential(session)
                out["temporal_after_ingestion"] = temporal(session, live_start)
                out["traversals_live"] = traversals(session, physical, end, scope_sids=live_sids)
                again = traversals(session, physical, middle, scope_sids=live_sids)
                same = {k: _stable(v) for k, v in at_middle.items()} == {k: _stable(v) for k, v in again.items()}
                late = {k: v["latest_recorded_at"] for k, v in again.items() if v.get("latest_recorded_at") and instant(v["latest_recorded_at"]) > middle}
                out["time_correct_traversals"] = {"as_of": iso(middle), "pass": same and not late and bool(again),
                                                  "same_rows_with_the_clock_there_and_after_full_ingestion": same,
                                                  "traversals_returning_a_record_from_after_as_of": late,
                                                  "with_the_clock_at_as_of": at_middle, "as_of_after_full_ingestion": again}
                out["isolation_after_ingestion"] = database_isolation(session, labels)
            reset(driver, database, manifest["dataset_id"])
            with driver.session(database=database, default_access_mode="READ") as session:
                remaining = session.run("MATCH (n:LiveIngested) RETURN count(n) AS n").single()["n"]
                pending = session.run("MATCH (f:ProviderFeedItem) WHERE f.status <> 'PENDING' RETURN count(f) AS n").single()["n"]
            out["reset_after_ingestion"] = {"live_ingested_nodes_left": remaining, "feed_items_not_pending": pending}
    out["pass"] = bool(out["pass_counts"] and out["referential"]["pass"] and out["temporal"]["pass"] and out["isolation"]["pass"]
                       and (not ingest or (out["ingestion"]["rejected"] == 0 and out["ingestion"]["conflicting_duplicate"] == 0
                                           and out["referential_after_ingestion"]["pass"] and out["temporal_after_ingestion"]["pass"]
                                           and out["time_correct_traversals"]["pass"] and out["isolation_after_ingestion"]["pass"])))
    return out


def _stable(row):
    return {k: v for k, v in row.items() if k not in ("median_ms", "max_ms", "runs")}


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


BOOKING_CONTEXT_LABELS = ("Shipment", "Package", "Customer", "Address", "AddressVersion", "LocationPin", "DeliveryInstruction",
                          "InventoryRecord", "Route", "JourneyPlan", "RouteSegment", "RouteMilestone", "ExpectedMilestone")


def temporal(session, live_start):
    checks = {
        "evidence_recorded_before_occurred": "MATCH (n:V2Entity) WHERE n.occurred_at IS NOT NULL AND n.recorded_at < n.occurred_at RETURN count(n) AS n",
        "milestone_window_inverted": "MATCH (m:ExpectedMilestone) WHERE m.latest_at <= m.earliest_at RETURN count(m) AS n",
        "interval_inverted": "MATCH (n:V2Entity) WHERE n.start_at IS NOT NULL AND n.end_at IS NOT NULL AND n.end_at <= n.start_at RETURN count(n) AS n",
        "assignment_interval_inverted": "MATCH (a:VehicleAssignment) WHERE a.valid_to <= a.valid_from RETURN count(a) AS n",
        # Nothing recorded after the live start is in the import, except the booking-time context of a live shipment
        # (stamped exactly at its booking); everything else from after the start arrives as feed messages.
        "imported_after_live_start_other_than_live_booking_context":
            "MATCH (n:V2Entity) WHERE NOT n:LiveIngested AND (n.recorded_at > $live_start OR n.occurred_at > $live_start) "
            "AND NOT (n.split = 'development' AND n.holdout_group IS NOT NULL AND any(l IN labels(n) WHERE l IN $booking) "
            "AND EXISTS { MATCH (s:Shipment {entity_id:n.holdout_group}) WHERE s.recorded_at = n.recorded_at }) RETURN count(n) AS n",
        "development_records_imported_after_booking": "MATCH (n:V2Entity {split:'development'}) WHERE NOT n:LiveIngested AND n.holdout_group IS NOT NULL "
                                                      "MATCH (s:Shipment {entity_id:n.holdout_group}) WHERE n.recorded_at > s.recorded_at RETURN count(n) AS n",
        "custody_before_its_source_scan_recorded": "MATCH (c:CustodyEvent)-[:OBSERVED_BY]->(s:ScanEvent) WHERE c.recorded_at < s.recorded_at RETURN count(c) AS n",
        "feed_delivered_before_event": "MATCH (f:ProviderFeedItem) WITH f, f.deliver_at AS d MATCH (n:V2Entity {entity_id:f.source_event_id}) "
                                       "WHERE n.occurred_at > d RETURN count(f) AS n",
        "feed_delivered_at_or_before_live_start": "MATCH (f:ProviderFeedItem) WHERE f.deliver_at <= $live_start RETURN count(f) AS n",
        "ingested_before_occurred": "MATCH (n:LiveIngested) WHERE datetime(n.ingested_at) < n.occurred_at RETURN count(n) AS n",
    }
    out = {name: session.run(query, live_start=live_start, booking=list(BOOKING_CONTEXT_LABELS)).single()["n"] for name, query in checks.items()}
    booking = session.run("MATCH (n:V2Entity {split:'development'}) WHERE NOT n:LiveIngested AND n.holdout_group IS NOT NULL "
                          "AND n.recorded_at > $live_start RETURN count(n) AS n", live_start=live_start).single()["n"]
    return {"pass": all(v == 0 for v in out.values()), **out, "live_booking_context_records_imported": booking}


def traversals(session, physical, as_of, scope_sids=()):
    """Representative cross-shipment lookups (the ones Stage 2 tools will need), timed, every one through visible():
    only records recorded and occurred at or before as_of. Each reports the latest recorded_at it returned. Example
    windows come from the simulator's physical state: the device-offline window that ended before as_of with most
    buffered records of shipments in scope, and the longest messaging outage that ended before as_of."""
    import datetime as _dt
    out = {}
    scope_sids = set(scope_sids)

    def stamp(value):
        return iso(value.to_native()) if value is not None else None
    windows = [(device["device_id"], w) for device in physical["devices"] for w in device["offline"] if instant(w["reconnect_at"]) <= as_of]
    outage = max(windows, key=lambda dw: (sum(r["shipment_id"] in scope_sids for r in dw[1]["buffered_records"]), dw[0], dw[1]["from"]), default=None)
    if outage:
        params = {"d": outage[0], "a": instant(outage[1]["from"]), "b": instant(outage[1]["reconnect_at"]), "as_of": as_of}
        rows, timing = _timed(session, f"MATCH (n:ScanEvent) WHERE n.device_ref = $d AND n.occurred_at >= $a AND n.occurred_at < $b AND {visible('n')} "
                                       "RETURN n.shipment_id AS shipment, count(*) AS scans, max(n.recorded_at) AS latest ORDER BY shipment", **params)
        beats, btiming = _timed(session, "MATCH (h:DeviceHeartbeat) WHERE h.device_id = $d AND h.occurred_at >= $a - duration('PT2H') "
                                         f"AND h.occurred_at <= $b + duration('PT1H') AND {visible('h')} "
                                         "RETURN h.occurred_at AS at, h.pending_uploads AS pending, h.recorded_at AS recorded ORDER BY at", **params)
        out["same_device_in_window"] = {"device": params["d"], "shipments": len(rows), "scans": sum(r["scans"] for r in rows),
                                        "latest_recorded_at": stamp(max((r["latest"] for r in rows), default=None)), **timing}
        out["device_heartbeats_around_window"] = {"beats": len(beats), "max_pending": max((b["pending"] for b in beats), default=None),
                                                  "latest_recorded_at": stamp(max((b["recorded"] for b in beats), default=None)), **btiming}
    route = session.run(f"MATCH (r:RouteRun)<-[:ON_ROUTE_RUN]-(a:VehicleAssignment) WHERE {visible('r')} AND {visible('a')} "
                        "WITH r, count(a) AS n ORDER BY n DESC, r.entity_id LIMIT 1 RETURN r.entity_id AS id", as_of=as_of).single()
    if route:
        rows, timing = _timed(session, f"MATCH (r:RouteRun {{entity_id:$r}})<-[:ON_ROUTE_RUN]-(a:VehicleAssignment) WHERE {visible('r')} AND {visible('a')} "
                                       f"OPTIONAL MATCH (e:CustodyEvent {{route_run_id:$r}}) WHERE e.shipment_id = a.shipment_id AND {visible('e')} "
                                       "RETURN a.shipment_id AS shipment, count(e) AS custody_events, max(a.recorded_at) AS la, max(e.recorded_at) AS le",
                              r=route["id"], as_of=as_of)
        out["same_route_run"] = {"route_run": route["id"], "shipments": len(rows), "custody_events": sum(r["custody_events"] for r in rows),
                                 "latest_recorded_at": stamp(max((x for r in rows for x in (r["la"], r["le"]) if x is not None), default=None)), **timing}
    container = session.run(f"MATCH (c:Container)<-[:IN_CONTAINER]-(s:ScanEvent) WHERE {visible('c')} AND {visible('s')} "
                            "WITH c, count(DISTINCT s.package_id) AS n ORDER BY n DESC, c.entity_id LIMIT 1 RETURN c.entity_id AS id", as_of=as_of).single()
    if container:
        rows, timing = _timed(session, f"MATCH (c:Container {{entity_id:$c}})<-[:IN_CONTAINER]-(s:ScanEvent) WHERE {visible('c')} AND {visible('s')} "
                                       "RETURN s.package_id AS package, s.shipment_id AS shipment, max(s.recorded_at) AS latest", c=container["id"], as_of=as_of)
        out["same_container"] = {"container": container["id"], "parcels": len(rows), "shipments": len({r["shipment"] for r in rows}),
                                 "latest_recorded_at": stamp(max((r["latest"] for r in rows), default=None)), **timing}
    trip = session.run(f"MATCH (t:Trip)<-[:ON_TRIP]-(e:CustodyEvent) WHERE {visible('t')} AND {visible('e')} "
                       "WITH t, count(DISTINCT e.shipment_id) AS n ORDER BY n DESC, t.entity_id LIMIT 1 RETURN t.entity_id AS id", as_of=as_of).single()
    if trip:
        rows, timing = _timed(session, f"MATCH (t:Trip {{entity_id:$t}})<-[:ON_TRIP]-(e:CustodyEvent) WHERE {visible('t')} AND {visible('e')} "
                                       f"OPTIONAL MATCH (t)-[:HAS_TRIP_EVENT]->(ev:TripEvent) WHERE {visible('ev')} "
                                       "RETURN count(DISTINCT e.shipment_id) AS shipments, count(DISTINCT ev) AS trip_events, "
                                       "max(e.recorded_at) AS le, max(ev.recorded_at) AS lv", t=trip["id"], as_of=as_of)
        out["same_trip"] = {"trip": trip["id"], "shipments": rows[0]["shipments"], "trip_events": rows[0]["trip_events"],
                            "latest_recorded_at": stamp(max((x for x in (rows[0]["le"], rows[0]["lv"]) if x is not None), default=None)), **timing}
    facility = session.run(f"MATCH (n:CustodyEvent) WHERE n.facility_id STARTS WITH 'DEMO-DEPOT' AND {visible('n')} AND n.occurred_at <= $as_of - duration('PT12H') "
                           "WITH n.facility_id AS f, max(n.occurred_at) AS last RETURN f, last ORDER BY f LIMIT 1", as_of=as_of).single()
    if facility:
        start = facility["last"].to_native().replace(minute=0, second=0, microsecond=0) - _dt.timedelta(hours=6)
        params = {"f": facility["f"], "a": start, "b": start + _dt.timedelta(hours=12), "as_of": as_of}
        rows, timing = _timed(session, f"MATCH (n:CustodyEvent) WHERE n.facility_id = $f AND n.occurred_at >= $a AND n.occurred_at < $b AND {visible('n')} "
                                       "RETURN n.event_type AS event, count(DISTINCT n.shipment_id) AS shipments, max(n.recorded_at) AS latest ORDER BY event", **params)
        thr, _ = _timed(session, f"MATCH (h:FacilityThroughput) WHERE h.facility_id = $f AND h.start_at >= $a AND h.start_at < $b AND {visible('h')} "
                                 "RETURN count(h) AS hours, max(h.oldest_waiting_minutes) AS oldest, max(h.recorded_at) AS latest", **params)
        out["same_facility_in_window"] = {"facility": params["f"], "window_hours": 12, "by_event": {r["event"]: r["shipments"] for r in rows},
                                          "throughput_hours": thr[0]["hours"], "oldest_waiting_minutes_max": thr[0]["oldest"],
                                          "latest_recorded_at": stamp(max((x for x in [*(r["latest"] for r in rows), thr[0]["latest"]] if x is not None), default=None)),
                                          **timing}
    spans = [w for w in physical["messaging_outages"] if instant(w["until"]) <= as_of]
    sms = max(spans, key=lambda w: (instant(w["until"]) - instant(w["from"]), w["carrier_route"]), default=None)
    if sms:
        params = {"r": sms["carrier_route"], "a": instant(sms["from"]) - _dt.timedelta(hours=1), "b": instant(sms["until"]) + _dt.timedelta(hours=1), "as_of": as_of}
        rows, timing = _timed(session, f"MATCH (c:CommunicationEvent) WHERE c.carrier_route = $r AND c.occurred_at >= $a AND c.occurred_at < $b AND {visible('c')} "
                                       "RETURN c.delivery_status AS status, count(*) AS n, max(c.recorded_at) AS latest ORDER BY status", **params)
        out["same_sms_route_in_window"] = {"carrier_route": params["r"], "by_status": {r["status"]: r["n"] for r in rows},
                                           "latest_recorded_at": stamp(max((r["latest"] for r in rows), default=None)), **timing}
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


def ingest_all(driver, database, dataset_id, live_start, end, middle, physical, live_sids):
    """Replay the whole feed through the real gateway, advancing the clock in six-hour steps (a record's recorded_at is
    the clock at which it was ingested). Returns (totals, the traversals run with the clock at `middle`)."""
    import datetime as _dt
    from operations.ingestion import Gateway
    gateway = Gateway(driver, database, dataset_id)
    with driver.session(database=database, default_access_mode="READ") as session:
        last = session.run("MATCH (f:ProviderFeedItem) RETURN max(f.deliver_at) AS t").single()["t"].to_native()
    totals = Counter()
    started = time.perf_counter()
    at_middle = {}
    clock = live_start
    final = max(last, end)
    while clock < final:
        clock = min(clock + _dt.timedelta(hours=6), final)
        while True:
            batch = gateway.ingest_due(clock.isoformat(), limit=1000)
            for key in ("ingested", "duplicate", "conflicting_duplicate", "rejected", "messages"):
                totals[key] += batch[key]
            if batch["messages"] < 1000:
                break
        totals["steps"] += 1
        if clock == middle:
            with driver.session(database=database, default_access_mode="READ") as session:
                at_middle = traversals(session, physical, middle, scope_sids=live_sids)
    return {**totals, "seconds": round(time.perf_counter() - started, 1), "clock": iso(final), "step_hours": 6}, at_middle


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
    export.add_argument("--days", type=int, default=WorldConfig.days)
    export.add_argument("--seed", type=int, default=WorldConfig.seed)
    export.add_argument("--dataset-id", default=WorldConfig.dataset_id)
    export.add_argument("--with-heldout", action="store_true")
    export.add_argument("--eval-dir", type=Path)
    export.add_argument("--determinism", action="store_true")
    export.add_argument("--truth-root", type=Path, help="truth-label root outside the repository (default SUHAIL_EVAL_TRUTH_ROOT or "
                                                        "C:\\Projects\\suhail-eval-truth)")
    export.add_argument("--state-root", type=Path, help="simulator physical-state root outside the repository (default SUHAIL_SIM_STATE_ROOT or "
                                                        "C:\\Projects\\suhail-sim-state\\<export name>)")
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
    check.add_argument("--state-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "export":
        from world.pipeline import run_export
        result = run_export(WorldConfig(total=args.total, days=args.days, seed=args.seed, dataset_id=args.dataset_id), args.output,
                            with_heldout=args.with_heldout, eval_dir=args.eval_dir, determinism=args.determinism,
                            truth_root=args.truth_root, state_root=args.state_root, tell_seed=args.tell_seed)
        print(canonical(result))
        if not result["pass"]:
            raise SystemExit(1)
    elif args.command == "apply":
        print(canonical(_jsonable(apply(args.directory, args.database, replace=args.replace))))
    else:
        result = cypher_checks(args.directory, args.database, ingest=args.ingest, truth_root=args.truth_root, state_root=args.state_root)
        text = json.dumps(_jsonable(result), indent=1, ensure_ascii=False, sort_keys=True)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
        print(canonical({"pass": result["pass"], "counts_pass": result["pass_counts"], "referential": result["referential"]["pass"],
                         "temporal": result["temporal"]["pass"], "isolation": result["isolation"]["pass"],
                         "time_correct_traversals": result.get("time_correct_traversals", {}).get("pass")}))


if __name__ == "__main__":
    main()
