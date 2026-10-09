"""Export, validate and load the live network dataset into its own isolated database.

  uv run python -m dataset_v2.live_bundle export --output ../artifacts/live-network/main
  uv run python -m dataset_v2.live_bundle apply ../artifacts/live-network/main --database shipments-v2-demo-live

The import holds reference data, live shipments' booking-time plans, and the history/held-out
splits. Live observations are loaded only as pending provider feed items (ProviderFeedItem), which
the ingestion worker normalizes into evidence as the simulation clock reaches their delivery
time. truth.jsonl and gold.jsonl stay on disk for evaluation and the simulator; neither is loaded.
The foundation V2 database (shipments-v2-demo) is never touched.
"""
import argparse
import json
from pathlib import Path
import tempfile

from dataset_v2.contracts import canonical, digest, instant
from dataset_v2.feed import FEED_VERSION, split_feed, validate_live_bundle
from dataset_v2.load import ImportRefused, _records, apply_bundle, read_bundle, target_guard
from dataset_v2.network import NETWORK_VERSION, generate_live, live_config

LIVE_DATABASE = "shipments-v2-demo-live"
FEED_BATCH = 500


def export_live(destination, config=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new export directory; existing exports are immutable")
    world, truth = generate_live(config or live_config())
    imported, items = split_feed(world, truth)
    validation = validate_live_bundle(imported, items)
    if not validation["pass"]:
        raise ValueError(f"Live bundle failed validation: {sorted({e['code'] for e in validation['errors']})}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".live-stage-", dir=destination.parent) as directory:
        stage = Path(directory) / "bundle"
        stage.mkdir()
        for name, records in (("nodes", (imported.nodes[k].record() for k in sorted(imported.nodes))),
                              ("edges", (imported.edges[k].record() for k in sorted(imported.edges))),
                              ("gold", (imported.gold[k] for k in sorted(imported.gold))),
                              ("feed", items), ("truth", (truth[k] for k in sorted(truth)))):
            with (stage / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
                for row in records:
                    stream.write(canonical(row) + "\n")
        feed_manifest = {"feed_version": FEED_VERSION, "network_version": NETWORK_VERSION, "items": len(items),
                         "hash": digest(items), "truth_hash": digest([truth[k] for k in sorted(truth)])}
        for name, value in (("manifest", imported.manifest()), ("validation", validation),
                            ("statistics", validation["statistics"]), ("feed_manifest", feed_manifest)):
            (stage / f"{name}.json").write_text(canonical(value) + "\n", encoding="utf-8", newline="\n")
        stage.rename(destination)
    return validation, feed_manifest


def read_feed(directory):
    directory = Path(directory)
    items = list(_records(directory / "feed.jsonl"))
    feed_manifest = json.loads((directory / "feed_manifest.json").read_text(encoding="utf-8"))
    if feed_manifest["hash"] != digest(items) or feed_manifest["items"] != len(items) or feed_manifest["feed_version"] != FEED_VERSION:
        raise ImportRefused("Feed content differs from its manifest")
    return items


def read_truth(directory):
    """Evaluation and simulator only. Never passed to the investigator, its tools or the database."""
    return {row["shipment_id"]: row for row in _records(Path(directory) / "truth.jsonl")}


def read_live_bundle(directory):
    items = read_feed(directory)
    return read_bundle(directory, validator=lambda world: validate_live_bundle(world, items)), items


def load_feed(driver, database, bundle, items):
    """Idempotent: one PENDING ProviderFeedItem per message, keyed by feed_id."""
    with driver.session(database=database) as session:
        session.run("CREATE CONSTRAINT provider_feed_id IF NOT EXISTS FOR (f:ProviderFeedItem) REQUIRE f.feed_id IS UNIQUE").consume()
        session.run("CREATE INDEX provider_feed_due IF NOT EXISTS FOR (f:ProviderFeedItem) ON (f.status, f.deliver_at)").consume()
        created = 0
        for offset in range(0, len(items), FEED_BATCH):
            rows = [{**item, "deliver_at": instant(item["deliver_at"]), "status": "PENDING",
                     "dataset_id": bundle.manifest["dataset_id"], "synthetic": True} for item in items[offset:offset + FEED_BATCH]]
            summary = session.run("UNWIND $rows AS row MERGE (f:ProviderFeedItem {feed_id:row.feed_id}) "
                                  "ON CREATE SET f=row", rows=rows).consume()
            created += summary.counters.nodes_created
        total = session.run("MATCH (f:ProviderFeedItem {origin:'PROVIDER'}) RETURN count(f) AS n").single()["n"]
    if total != len(items):
        raise ImportRefused("Feed item count in the database differs from the bundle")
    return {"feed_items_created": created, "feed_items_total": total}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--output", type=Path, default=Path("../artifacts/live-network/main"))
    apply = sub.add_parser("apply")
    apply.add_argument("directory", type=Path)
    apply.add_argument("--database", required=True)
    args = parser.parse_args(argv)
    if args.command == "export":
        validation, feed_manifest = export_live(args.output)
        print(canonical({"status": "live_export_validated", "output": str(args.output.resolve()),
                         "statistics": validation["statistics"], "feed": feed_manifest}))
        return
    if args.database != LIVE_DATABASE:
        parser.error(f"--database must be {LIVE_DATABASE}; the foundation V2 database is never a live target")
    import config
    from neo4j import GraphDatabase
    protected = (config.SHIPMENT_DATABASE, config.NEO4J_DATABASE, config.CHAT_DATABASE, "shipments-v2-demo")
    target_guard(config.NEO4J_URI, args.database, protected)
    bundle, items = read_live_bundle(args.directory)
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD)) as driver:
        with driver.session(database="system", default_access_mode="READ") as session:
            exists = any(r["name"] == args.database for r in session.run("SHOW DATABASES YIELD name RETURN name"))
        state = None
        if exists:
            with driver.session(database=args.database, default_access_mode="READ") as session:
                row = session.run("MATCH (m:_V2Import) RETURN m.state AS state, m.manifest_hash AS hash").single()
            if row and (row["state"] != "COMPLETE" or row["hash"] != bundle.manifest_hash) and row["state"] != "LOADING":
                raise ImportRefused("Live target holds a different import")
            state = row["state"] if row else None
        report = {"status": "already_complete"} if state == "COMPLETE" else apply_bundle(
            driver, bundle, uri=config.NEO4J_URI, database=args.database, protected=protected)
        if report["status"] == "resumable_incomplete":
            print(canonical(report))
            raise SystemExit(2)
        report.update(load_feed(driver, args.database, bundle, items))
    print(canonical({**report, "gold_imported": False, "truth_imported": False}))


if __name__ == "__main__":
    main()
