"""Read-only, secret-free shipment database/runtime census."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))
import config
from core.query_runner import get_driver
from neo4j import RoutingControl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/agent-runs/2026-10-07_shipment-product-coherence-census.json")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    driver = get_driver()
    result = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "target": config.SHIPMENT_DATABASE,
              "local_bolt": config.NEO4J_URI in ("bolt://127.0.0.1:7687", "bolt://localhost:7687"),
              "llm_model": config.LLM_MODEL, "embedding_dimensions": config.EMBEDDING_DIMENSIONS,
              "llm_key_configured": bool(config.LLM_API_KEY)}
    queries = {
        "labels": "MATCH (n) RETURN labels(n) AS labels, count(*) AS count ORDER BY count DESC",
        "relationships": "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC",
        "split": "MATCH (f:FailureReason) RETURN count(f) AS total, sum(CASE WHEN EXISTS {(f)-[:RESOLVES_WITH]->()} THEN 1 ELSE 0 END) AS resolved, sum(CASE WHEN NOT EXISTS {(f)-[:RESOLVES_WITH]->()} THEN 1 ELSE 0 END) AS open",
        "indexes": "SHOW INDEXES YIELD name, type, state, options WHERE type = 'VECTOR' RETURN name,type,state,options",
        "statuses": "MATCH (s:Shipment) RETURN s.status AS status, count(*) AS count",
        "categories": "MATCH (f:FailureReason) RETURN f.category AS category, count(*) AS count",
        "agent_outcomes": "MATCH (f:FailureReason)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome) WHERE r.source = 'agent_pipeline' RETURN f.failure_id AS failure_id, r.resolution_id AS resolution_id, r.action AS action, r.timestamp AS timestamp, o.outcome_id AS outcome_id, o.success AS success, o.status AS status",
        "shp0227": "MATCH (s:Shipment {shipment_id:'SHP-0227'}) OPTIONAL MATCH (s)-[:HAS_EVENT]->(e:Event)-[:CAUSED_BY]->(f:FailureReason) OPTIONAL MATCH (f)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome) RETURN s.shipment_id AS shipment_id, f.failure_id AS failure_id, f.category AS category, r.resolution_id AS resolution_id, r.source AS source, o.success AS success, o.status AS status",
        "synthetic_signature": "MATCH (s:Shipment) RETURN count(s) AS shipments, sum(CASE WHEN s.shipment_id =~ 'SHP-[0-9]{4}' THEN 1 ELSE 0 END) AS synthetic_ids",
    }
    for key, query in queries.items():
        records, _, _ = driver.execute_query(query, database_=config.SHIPMENT_DATABASE, routing_=RoutingControl.READ)
        result[key] = [r.data() for r in records]
    dest = args.output
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    visible = ({k: result[k] for k in ("timestamp", "target", "local_bolt", "llm_model",
                                      "embedding_dimensions", "synthetic_signature", "split", "indexes")}
               if args.summary else result)
    print(json.dumps(visible, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
