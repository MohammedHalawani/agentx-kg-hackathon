"""Read-only evidence separability audit for the initial synthetic benchmark."""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))
import config
from core.query_runner import get_driver
from neo4j import RoutingControl


def main():
    query = """
    MATCH (s:Shipment)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(f:FailureReason)
    MATCH (f)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
    WHERE r.source IS NULL AND o.success IN [true, false]
    WITH DISTINCT s, f
    OPTIONAL MATCH (s)-[:GOVERNED_BY]->(p:Policy)
    OPTIONAL MATCH (s)-[:HAS_EVENT]->(e:Event)
    RETURN s.shipment_id AS shipment_id, f.category AS category,
           p.sla_days AS sla_days, p.retry_limit AS retry_limit,
           collect(DISTINCT e.event_type) AS event_types,
           keys(s) AS shipment_fields, collect(DISTINCT keys(e)) AS event_fields
    """
    records, _, _ = get_driver().execute_query(
        query, database_=config.SHIPMENT_DATABASE, routing_=RoutingControl.READ)
    categories = defaultdict(list)
    signatures = defaultdict(set)
    for record in records:
        row = record.data()
        category = row["category"].removeprefix("escalation:")
        categories[category].append(row)
        signatures[tuple(sorted(row["event_types"]))].add(category)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": "local synthetic recorded history",
        "recorded_failure_histories": len(records),
        "model_local_projection": {
            "shipment": ["shipment_id", "tracking_id", "order_id", "carrier", "status"],
            "event": ["event_id", "event_type", "timestamp"],
            "policy": ["policy_id", "name", "sla_days", "retry_limit"],
            "addresses": ["address_id", "full_address", "district", "city", "lat", "lng", "version"],
        },
        "categories": {},
        "shared_event_type_signatures": [
            {"event_types": list(signature), "categories": sorted(cats)}
            for signature, cats in signatures.items() if len(cats) > 1],
        "interpretation": (
            "Shared event-type signatures do not prove all evidence is identical: timestamps, "
            "addresses and complaint symptoms can differ. However the model projection has no "
            "measured weight, observed barcode, gate scan or contact-attempt outcome. Removing "
            "the seeded FailureReason label therefore leaves some subtypes underidentified. "
            "Do not claim all benchmark misses could be solved by increasing model size."),
    }
    for category, rows in sorted(categories.items()):
        report["categories"][category] = {
            "histories": len(rows),
            "policies": dict(Counter(f"sla={r['sla_days']},retry={r['retry_limit']}" for r in rows)),
            "shipment_fields": sorted({k for r in rows for k in r["shipment_fields"]}),
            "event_fields": sorted({k for r in rows for fields in r["event_fields"] for k in fields}),
        }
    target = ROOT / "docs/evals/2026-10-07_gpt-oss-v1-evidence-audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"histories": len(records), "categories": {
        k: v["histories"] for k, v in report["categories"].items()},
        "shared_signatures": report["shared_event_type_signatures"]}))


if __name__ == "__main__":
    main()
