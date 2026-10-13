"""Restore the payload's own ``provider_id`` on gateway-ingested nodes whose delivery envelope overwrote it.

Before the gateway fix (operations.ingestion, payload provider outranks the delivering channel) a
Manifest, RouteRun or Trip that named its own provider was stored with the channel's provider instead.
This sets ``provider_id`` back to the value the immutable bundle's feed payload carries, on the isolated
V3 development database only, and changes nothing else: ids, event/receipt/ingest times, hashes and
provenance are verified unchanged afterwards.

Default is a read-only dry run. ``--apply --expect N`` writes in ONE transaction that rolls back unless it
changes exactly the nodes the dry run listed. Guards (each node): it must still carry the channel
provider, and its stored raw payload hash and feed id must equal the bundle's. Re-running is a no-op.
No feed reimport, replay, or other write. Run from ``chat``:
    uv run python -m scripts.repair_provider_overwrite [--apply --expect 201]
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TARGET_DATABASE = "shipments-v2-world-v3-20261013"
DATASET_ID = "DEMO-SUHAIL-WORLD-V3-20261013"
BUNDLE = Path(r"C:\Projects\suhail-v3-data\world-v3-20261013\bundle")
BUNDLE_MANIFEST_SHA256 = "538d9fffe7c23cb9637be959e7c5ac0f83c76b3fab5c67b8e377e071d687e2b6"

STATE = """
UNWIND $ids AS id
OPTIONAL MATCH (n:V2Entity:LiveIngested {entity_id: id, dataset_id: $dataset_id})
OPTIONAL MATCH (f:ProviderFeedItem {feed_id: n.feed_id})
RETURN id, n IS NOT NULL AS found, properties(n) AS props, f.payload_hash AS feed_payload_hash
"""
REPAIR = """
UNWIND $fixes AS f
MATCH (n:V2Entity:LiveIngested {entity_id: f.id, dataset_id: $dataset_id})
WHERE n.provider_id = f.channel_provider AND n.raw_payload_hash = f.payload_hash AND n.feed_id = f.feed_id
SET n.provider_id = f.provider
RETURN count(n) AS repaired
"""


def plan(items, nodes):
    """Records whose payload names a provider other than the channel that delivered them (first deliveries only)."""
    first = {}
    for item in items:
        first.setdefault(item["source_event_id"], item)
    fixes = []
    for key in sorted(first):
        node = nodes.get(key)
        provider = node.properties.get("provider_id") if node is not None else None
        item = first[key]
        if provider is not None and provider != item["provider_id"]:
            fixes.append({"id": key, "kind": node.kind, "provider": provider, "channel_provider": item["provider_id"],
                          "payload_hash": item["payload_hash"], "feed_id": item["feed_id"]})
    return fixes


def other_digest(props):
    rest = {k: v for k, v in props.items() if k != "provider_id"}
    return hashlib.sha256(json.dumps(rest, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def classify(fix, row):
    """repaired | needs_repair | anomalous for one planned fix against its stored node."""
    if not row["found"]:
        return "anomalous"
    props = row["props"]
    if props.get("raw_payload_hash") != fix["payload_hash"] or props.get("feed_id") != fix["feed_id"] \
            or row["feed_payload_hash"] != fix["payload_hash"]:
        return "anomalous"
    if props.get("provider_id") == fix["provider"]:
        return "repaired"
    return "needs_repair" if props.get("provider_id") == fix["channel_provider"] else "anomalous"


def read_state(driver, fixes):
    with driver.session(database=TARGET_DATABASE, default_access_mode="READ") as session:
        rows = {r["id"]: dict(r) for r in session.run(STATE, ids=[f["id"] for f in fixes], dataset_id=DATASET_ID)}
    return {f["id"]: (classify(f, rows[f["id"]]), other_digest(rows[f["id"]]["props"] or {})) for f in fixes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", default=TARGET_DATABASE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect", type=int, help="exact number of affected records (required with --apply)")
    args = parser.parse_args(argv)
    if args.database != TARGET_DATABASE:
        raise SystemExit(f"Refusing: this repair is only for {TARGET_DATABASE}")
    if args.apply and args.expect is None:
        raise SystemExit("--apply requires --expect N")
    from dataset_v2.feed import reconstitute
    from world.export import _driver, read_world_bundle
    manifest = BUNDLE / "manifest.json"
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != BUNDLE_MANIFEST_SHA256:
        raise SystemExit("Refusing: bundle manifest is not the immutable V3 bundle")
    loaded, items = read_world_bundle(BUNDLE)
    fixes = plan(items, reconstitute(loaded.world, items).nodes)
    if args.expect is not None and len(fixes) != args.expect:
        raise SystemExit(f"Refusing: bundle names {len(fixes)} affected records, expected {args.expect}")
    driver, settings = _driver()
    protected = {settings.NEO4J_DATABASE, settings.SHIPMENT_DATABASE, settings.CHAT_DATABASE}
    if TARGET_DATABASE in protected or "-ci-" in TARGET_DATABASE or settings.NEO4J_URI != "bolt://127.0.0.1:7687":
        raise SystemExit("Refusing: target is protected or not the local isolated server")
    with driver:
        with driver.session(database=TARGET_DATABASE, default_access_mode="READ") as session:
            marker = session.run("MATCH (m:_V2Import) RETURN m.state AS state").single()
            if not marker or marker["state"] != "COMPLETE":
                raise SystemExit("Refusing: import marker is not COMPLETE")
        before = read_state(driver, fixes)
        counts = Counter(state for state, _ in before.values())
        by_kind = Counter((f["kind"], f["provider"], before[f["id"]][0]) for f in fixes)
        report = {"database": TARGET_DATABASE, "affected_records": len(fixes), "before": dict(counts),
                  "by_kind_provider_state": {"|".join(k): v for k, v in sorted(by_kind.items())}}
        if counts.get("anomalous"):
            report["anomalous"] = [k for k, (s, _) in before.items() if s == "anomalous"][:10]
            print(json.dumps(report, indent=1))
            raise SystemExit("Refusing: records do not match their bundle payloads")
        if args.apply:
            todo = [f for f in fixes if before[f["id"]][0] == "needs_repair"]

            def write(tx):
                row = tx.run(REPAIR, fixes=todo, dataset_id=DATASET_ID).single()
                if row["repaired"] != len(todo):
                    raise RuntimeError(f"changed {row['repaired']} of {len(todo)}; rolled back")
                return row["repaired"]
            with driver.session(database=TARGET_DATABASE) as session:
                report["written"] = session.execute_write(write) if todo else 0
            after = read_state(driver, fixes)
            report["after"] = dict(Counter(state for state, _ in after.values()))
            report["other_properties_unchanged"] = all(after[k][1] == before[k][1] for k in before)
            if report["after"] != {"repaired": len(fixes)} or not report["other_properties_unchanged"]:
                print(json.dumps(report, indent=1))
                raise SystemExit("Verification failed after repair")
        print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
