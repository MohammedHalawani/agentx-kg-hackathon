"""Bounded, read-only shipment evidence for all Explore lenses.

Filters describe operational evidence, never a model's confidence or a completed delivery
inferred from a recommendation. See docs/explore-shipment-contract.md for their definitions.
"""
import math
from datetime import datetime

from neo4j import RoutingControl

import config
from core.query_runner import get_driver
from llm.pipeline import cases

FILTERS = ("needs_attention", "all", "stalled", "critical", "delivered")
SCAN_LIMIT = 1000
MAX_LIMIT = 50
MAX_GRAPH_NODES = 500
MAX_GRAPH_EDGES = 800

# Each optional leg is aggregated before the next one to avoid multiplying event/address
# rows. Coordinate/event metadata is evidence from the graph; origins are labelled centroids.
_SHIPMENTS = """
MATCH (s:Shipment)
WITH s ORDER BY s.shipment_id LIMIT $scan_limit
OPTIONAL MATCH (s)-[:HAS_EVENT]->(e:Event)
WITH s, e ORDER BY e.timestamp DESC, e.event_id
WITH s, head(collect(e {.event_type, .timestamp})) AS last_event,
     min(e.timestamp) AS first_timestamp,
     sum(CASE WHEN e.event_type = 'DELIVERY_ATTEMPT' THEN 1 ELSE 0 END) AS attempts
OPTIONAL MATCH (s)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(f:FailureReason)
WITH s, last_event, first_timestamp, attempts,
     collect(DISTINCT f.category) AS root_causes,
     count(CASE WHEN f IS NOT NULL AND NOT EXISTS {
       MATCH (f)-[:RESOLVES_WITH]->(:Resolution)
     } THEN f END) > 0 AS unresolved,
     count(CASE WHEN EXISTS {
       MATCH (f)-[:RESOLVES_WITH]->(:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
       WHERE o.success IS NULL
     } THEN f END) > 0 AS pending_recommendation
OPTIONAL MATCH (s)-[:GOVERNED_BY]->(p:Policy)
WITH s, last_event, first_timestamp, attempts, root_causes, unresolved,
     pending_recommendation, head(collect(p {.sla_days, .retry_limit})) AS policy
OPTIONAL MATCH (s)<-[:HAS_SHIPMENT]-(o:Order)
OPTIONAL MATCH (s)-[:ASSIGNED_TO]->(c:Courier)
WITH s, last_event, first_timestamp, attempts, root_causes, unresolved,
     pending_recommendation, policy, head(collect(c.name)) AS courier,
     head(collect(o {.origin_warehouse, .origin_warehouse_id})) AS warehouse
OPTIONAL MATCH (s)-[:DELIVERED_TO]->(a:Address)
WITH s, last_event, first_timestamp, attempts, root_causes, unresolved,
     pending_recommendation, policy, courier, warehouse,
     collect(DISTINCT a {.lat, .lng, .city, .district, full: a.full_address,
                         kind: 'delivery'})[0..8] AS destinations
RETURN s.shipment_id AS shipment_id, s.tracking_id AS tracking_id,
       s.status AS status, s.carrier AS carrier,
       last_event, first_timestamp, attempts, root_causes, unresolved,
       pending_recommendation, policy, courier, warehouse, destinations,
       EXISTS { MATCH (x:EscalatedCase {shipment_id: s.shipment_id})
                WHERE x.status = 'open' } AS open_escalation
ORDER BY shipment_id
"""

# Reuse the case-file's curated terminal hub branches, never expand Courier/Policy into
# other shipments. This is a fixed query, with shipment IDs passed only as parameters.
_GRAPH = cases._SHIPMENT_NEIGHBOURHOOD.replace(
    "MATCH (s:Shipment {shipment_id: $shipment_id})",
    "MATCH (s:Shipment) WHERE s.shipment_id IN $shipment_ids",
).replace("CALL (s) {", "CALL (s) {\n  RETURN s AS p\n  UNION") + "\nLIMIT 1201"


def _point(p: dict | None) -> bool:
    if not p:
        return False
    lat, lng = p.get("lat"), p.get("lng")
    return (type(lat) in (int, float) and type(lng) in (int, float)
            and math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180)


def _elapsed(first, last) -> float | None:
    try:
        return (datetime.fromisoformat(str(last)) - datetime.fromisoformat(str(first))).total_seconds() / 86400
    except (ValueError, TypeError):
        return None


def shipment_summary(row: dict) -> dict:
    """Compute filter flags once; map/list/graph membership uses this same result."""
    destinations = [p for p in row.get("destinations", []) if _point(p)]
    warehouse = row.get("warehouse") or {}
    coords = cases._WAREHOUSE_COORDS.get(warehouse.get("origin_warehouse_id"))
    origin = ({"lat": coords[0], "lng": coords[1], "kind": "warehouse",
               "full": warehouse.get("origin_warehouse"), "approximate": True,
               "coordinate_source": "city_centroid"} if coords else None)
    roots = sorted(set(row.get("root_causes") or []))
    pending = bool(row.get("pending_recommendation"))
    attention = bool(row.get("unresolved") or pending or row.get("open_escalation"))
    last = row.get("last_event") or None
    elapsed = _elapsed(row.get("first_timestamp"), (last or {}).get("timestamp"))
    policy = row.get("policy") or {}
    sla = policy.get("sla_days")
    retry_limit = policy.get("retry_limit")
    sla_breached = sla is not None and elapsed is not None and elapsed > sla
    exhausted = retry_limit is not None and row.get("attempts", 0) >= retry_limit
    stalled = attention and (any(c.removeprefix("escalation:") == "hub_delay" for c in roots)
                              or (last or {}).get("event_type") == "HUB_DELAY")
    critical = attention and (sla_breached or exhausted or bool(row.get("open_escalation")))
    return {
        "shipment_id": row.get("shipment_id"), "tracking_id": row.get("tracking_id"),
        "status": row.get("status"), "carrier": row.get("carrier"),
        "priority": "high" if critical else "medium" if attention else "low",
        "priority_source": "operational_rules", "root_causes": roots,
        "needs_attention": attention, "stalled": stalled, "critical": critical,
        "delivered": row.get("status") == "DELIVERED",
        "pending_recommendation": pending, "open_escalation": bool(row.get("open_escalation")),
        "last_event": last, "origin": origin, "destinations": destinations,
        "city": next((p.get("city") for p in row.get("destinations", []) if p and p.get("city")), None),
        "courier": row.get("courier"), "sla_breached": sla_breached,
        "retry_budget_exhausted": exhausted,
    }


def shipment_graph(shipment_ids: list[str]) -> dict:
    if not shipment_ids:
        return {"nodes": [], "relationships": [], "truncated": False}
    def bounded_result(result):
        records = list(result)
        return result.graph(), len(records)

    graph, path_count = get_driver().execute_query(
        _GRAPH, parameters_={"shipment_ids": shipment_ids[:MAX_LIMIT]},
        database_=config.SHIPMENT_DATABASE, routing_=RoutingControl.READ,
        result_transformer_=bounded_result,
    )
    ordered = sorted(graph.nodes, key=lambda n: ("Shipment" not in n.labels, n.element_id))
    nodes = [cases._node_dict(n) for n in ordered[:MAX_GRAPH_NODES]]
    kept = {n["id"] for n in nodes}
    relationships = [{"id": r.element_id, "type": r.type,
                      "from": r.start_node.element_id, "to": r.end_node.element_id}
                     for r in sorted(graph.relationships, key=lambda r: r.element_id)
                     if r.start_node.element_id in kept and r.end_node.element_id in kept]
    return {"nodes": nodes, "relationships": relationships[:MAX_GRAPH_EDGES],
            "truncated": path_count >= 1201 or len(ordered) > len(nodes) or len(relationships) > MAX_GRAPH_EDGES}


def overview(filter: str = "needs_attention", limit: int = 25) -> dict:
    if filter not in FILTERS:
        raise ValueError("Unsupported Explore filter")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"Explore limit must be between 1 and {MAX_LIMIT}")
    rows, _, _ = get_driver().execute_query(
        _SHIPMENTS, parameters_={"scan_limit": SCAN_LIMIT + 1},
        database_=config.SHIPMENT_DATABASE, routing_=RoutingControl.READ,
    )
    dataset_truncated = len(rows) > SCAN_LIMIT
    summaries = [shipment_summary(dict(r)) for r in rows[:SCAN_LIMIT]]
    counts = {f: len(summaries) if f == "all" else sum(s[f] for s in summaries) for f in FILTERS}
    matching = summaries if filter == "all" else [s for s in summaries if s[filter]]
    selected = matching[:limit]
    return {"shipments": selected, "counts": counts, "filter": filter, "limit": limit,
            "total": len(matching), "returned": len(selected),
            "truncated": len(matching) > limit, "dataset_truncated": dataset_truncated,
            "counts_scope": "first_1000_shipments" if dataset_truncated else "all_shipments",
            "graph": shipment_graph([s["shipment_id"] for s in selected])}
