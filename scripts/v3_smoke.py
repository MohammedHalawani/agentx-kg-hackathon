"""Read-only checks of the merged V3 backend against the V3 development database.

Target: ONLY `shipments-v2-world-v3-20261013` on the local server. Every session this script opens is a READ
session (a driver wrapper refuses any other), so the server itself rejects a write. Nothing is imported, reset,
replayed or investigated; no model is called; no private or truth file is opened.

Checked:
  target      the database is online, is not one of the application's configured databases, and holds one COMPLETE
              import of the V3 dataset whose stored manifest hash matches its manifest
  counts      nodes, relationships, ingested records, feed items and operations cases (reported; compared with
              --expect-counts when given)
  status      the ledger's worker status and every case's investigation_status, as the merged store and read model
              serve them, carry the frozen suhail-v3-1 fields (cases written before the merge included)
  parity      for the curated shipments, at every cutoff of the frozen corrected neutral packets: the live read
              model returns the same evidence records, relationships, vehicle observations and route summary;
              nothing is later than its cutoff; the vehicle_path layer is the same projection

Run from `chat` (database settings from the checkout's ignored .env):
    uv run python ../scripts/v3_smoke.py [--expect-counts nodes,relationships,ingested,feed,cases]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))

TARGET = "shipments-v2-world-v3-20261013"
DATASET_ID = "DEMO-SUHAIL-WORLD-V3-20261013"
LOCAL_URI = "bolt://127.0.0.1:7687"
PACKETS = Path(r"C:\Projects\suhail-v3-data\world-v3-20261013\corrected-r1\neutral-packets")
CONTRACT = ROOT / "docs" / "v3" / "06-contract-examples.json"
# Dataset records and the relationships between them; feed items and the operations ledger are counted on their own.
COUNTS = {"nodes": "MATCH (n:V2Entity) RETURN count(n) AS n",
          "relationships": "MATCH (:V2Entity)-[r]->(:V2Entity) RETURN count(r) AS n",
          "ingested": "MATCH (n:LiveIngested) RETURN count(n) AS n",
          "feed": "MATCH (n:ProviderFeedItem) RETURN count(n) AS n",
          "cases": "MATCH (n:OpsEntity:OpsCase) RETURN count(n) AS n"}


class ReadOnly:
    """A driver that opens READ sessions only. Anything else is refused before it reaches the server."""

    def __init__(self, driver):
        self._driver = driver

    def session(self, **options):
        if options.get("default_access_mode") != "READ":
            raise RuntimeError("v3_smoke opens read sessions only")
        return self._driver.session(**options)

    def close(self):
        self._driver.close()


def ids(rows):
    return sorted(row["id"] for row in rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--expect-counts", help="nodes,relationships,ingested,feed,cases")
    args = parser.parse_args(argv)
    import logging
    import config
    from neo4j import GraphDatabase
    from dataset_v2.contracts import digest, instant
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)      # a ledger with no runs yet has no such label
    from operations.datasets import dataset_config
    from operations.identifiers import public_value
    from operations.read_model import OperationsReader
    from operations.route_evidence import build_route_evidence
    from operations.store import OperationsStore

    protected = (config.NEO4J_DATABASE, config.SHIPMENT_DATABASE, config.CHAT_DATABASE)
    if config.NEO4J_URI != LOCAL_URI or TARGET.lower() in {str(name).lower() for name in protected}:
        raise SystemExit("Refusing: not the local server, or the target is a configured application database")
    report, failures = {"database": TARGET, "dataset_id": DATASET_ID, "access": "READ sessions only"}, []

    def check(name, ok, detail=None):
        report.setdefault("checks", {})[name] = "PASS" if ok else "FAIL"
        if not ok:
            failures.append({"check": name, "detail": detail})

    driver = ReadOnly(GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD)))
    try:
        with driver.session(database="system", default_access_mode="READ") as session:
            on_server = {row["name"]: row["currentStatus"] for row in session.run("SHOW DATABASES YIELD name, currentStatus")}
        check("target_online", str(on_server.get(TARGET)).lower() == "online", on_server.get(TARGET))
        if failures:
            raise SystemExit(json.dumps({**report, "failures": failures}, indent=1))
        with driver.session(database=TARGET, default_access_mode="READ") as session:
            markers = [dict(row["props"]) for row in session.run("MATCH (m:_V2Import) RETURN properties(m) AS props")]
            report["counts"] = {name: session.run(query).single()["n"] for name, query in COUNTS.items()}
        manifest = json.loads(markers[0]["manifest_json"]) if len(markers) == 1 else {}
        check("one_complete_import_of_the_v3_dataset",
              len(markers) == 1 and markers[0].get("state") == "COMPLETE" and manifest.get("dataset_id") == DATASET_ID
              and manifest.get("synthetic") is True and digest(manifest) == markers[0].get("manifest_hash"))
        report["manifest_hash"] = markers[0].get("manifest_hash") if markers else None
        if args.expect_counts:
            expected = dict(zip(COUNTS, (int(part) for part in args.expect_counts.split(","))))
            check("counts_as_expected", report["counts"] == expected, {"expected": expected, "found": report["counts"]})
        if failures:
            raise SystemExit(json.dumps({**report, "failures": failures}, indent=1))

        cfg = dataset_config(manifest["config"])
        frozen = json.loads(CONTRACT.read_text(encoding="utf-8"))
        fields = set(frozen["finalized_case_status_http_example"])
        result_fields = set(frozen["finalized_case_status_http_example"]["final_result"])

        # ---- status: the merged store and read model over the ledger as it is (read transactions only)
        reader = OperationsReader(driver, TARGET, cfg.dataset_id, cfg, lambda: store.status()["as_of"])
        store = OperationsStore(driver, TARGET, cfg.dataset_id, cfg, reader=reader, uri=config.NEO4J_URI, protected=protected)
        reader.store = store
        status = public_value(store.status())
        worker = status["worker"]
        report["worker"] = {key: worker.get(key) for key in ("state", "concurrency", "active_count", "active_case_id", "processed_count")}
        report["clock"] = status["as_of"]
        check("worker_status_has_the_frozen_fields", set(frozen["worker_status_http_example"]["worker"]) <= set(worker)
              and worker["active_count"] == len(worker["active_cases"]) and worker["concurrency"] in (1, 2), sorted(worker))
        with driver.session(database=TARGET, default_access_mode="READ") as session:
            case_ids = [row["id"] for row in session.run("MATCH (c:OpsEntity:OpsCase {dataset_id:$d}) RETURN c.entity_id AS id ORDER BY id", d=DATASET_ID)]
        cases = []
        for case_id in case_ids:
            detail = reader.case_detail(case_id)
            served = public_value(detail)["investigation_status"]
            ok = (set(served) == fields and detail["investigation_status"] == store.case_detail(case_id)["investigation_status"]
                  and served["run_status"] in ("QUEUED", "RUNNING", "REVIEWED", "ABORTED", "FAILED")
                  and type(served["claim_epoch"]) is int and served["claim_epoch"] >= 0
                  and (served["final_result"] is None or set(served["final_result"]) == result_fields)
                  and "DEMO-" not in json.dumps(served)
                  and detail["route_evidence"]["schema"] == "route-evidence-v3-1")
            cases.append({"case_id": served["case_id"], "shipment_id": served["shipment_id"], "workflow_state": served["workflow_state"],
                          "run_status": served["run_status"], "claim_epoch": served["claim_epoch"], "ok": ok})
        report["cases"] = cases
        check("every_case_serves_the_frozen_investigation_status", bool(cases) and all(c["ok"] for c in cases),
              [c["case_id"] for c in cases if not c["ok"]])

        # ---- parity with the frozen corrected neutral packets, at each of their cutoffs
        rows, top = [], set(frozen["route_evidence_http_example"])
        for path in sorted(PACKETS.glob("DEMO-SHP-*.json")):
            packet = json.loads(path.read_text(encoding="utf-8"))
            sid = packet["shipment_id"]
            for snapshot in packet["snapshots"]:
                cutoff = snapshot["as_of"]
                at = OperationsReader(driver, TARGET, cfg.dataset_id, cfg, clock=lambda cutoff=cutoff: cutoff)
                detail = at.shipment_detail(sid, cutoff)
                evidence, route, wanted = detail["evidence"], detail["route_evidence"], snapshot["route_evidence"]
                again = build_route_evidence(evidence, lambda name, **params: at.fetch(name, as_of=evidence["as_of"], **params))
                limit = instant(cutoff)
                times = [instant(str(n["properties"][key])) for n in evidence["nodes"] for key in ("recorded_at",) if n["properties"].get(key)]
                times += [instant(p[key]) for p in route["observations"] for key in ("occurred_at", "recorded_at")]
                rows.append({
                    "shipment_id": sid, "as_of": cutoff,
                    "nodes": ids(evidence["nodes"]) == ids(snapshot["source_nodes"]),
                    "relationships": ids(evidence["edges"]) == ids(snapshot["source_relationships"]),
                    "observations": [p["evidence_id"] for p in route["observations"]] == [p["evidence_id"] for p in wanted["observations"]],
                    "summary": route["summary"] == wanted["summary"],
                    "fields": set(route) == top and route["schema"] == "route-evidence-v3-1" and route["as_of"] == detail["as_of"],
                    "within_cutoff": all(t <= limit for t in times),
                    "vehicle_path": [p["evidence_id"] for p in detail["route_layers"]["layers"]["vehicle_path"]]
                                    == [p["evidence_id"] for p in route["observations"]],
                    "repeatable": again == route,
                    "points": len(route["observations"])})
        columns = ("nodes", "relationships", "observations", "summary", "fields", "within_cutoff", "vehicle_path", "repeatable")
        report["parity"] = {"snapshots": len(rows), "shipments": len({r["shipment_id"] for r in rows}),
                            **{column: sum(bool(r[column]) for r in rows) for column in columns}}
        bad = [{k: r[k] for k in ("shipment_id", "as_of", *columns)} for r in rows if not all(r[c] for c in columns)]
        check("live_read_model_matches_the_frozen_packets", bool(rows) and not bad, bad[:8])
    finally:
        driver.close()
    report["result"] = "FAIL" if failures else "PASS"
    if failures:
        report["failures"] = failures
    print(json.dumps(report, indent=1, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
