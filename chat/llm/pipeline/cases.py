"""Read-only aggregates over the shipment graph for the Decisions view.

Everything here answers one question: *is the closed loop actually working?* The graph
carries both the seeded history and every Resolution the pipeline has written back
(writeback.py stamps `source` so the two can be told apart), which means the same query
that describes the ministry's historical performance also measures the agent's.

Frozen, parameterless Cypher against config.SHIPMENT_DATABASE - the same
no-generated-Cypher rule the rest of the app follows (see core/query_runner.py). Nothing
here writes; the pipeline's writeback is still the only write path.
"""
import logging

from neo4j import RoutingControl

import config
from core.query_runner import get_driver

log = logging.getLogger("pipeline.cases")

# The unresolved FailureReasons - the queue the agent exists to work through. These are the
# nodes with no RESOLVES_WITH edge, i.e. the live complaints, not the precedent.
_QUEUE = """
MATCH (f:FailureReason)
WHERE NOT (f)-[:RESOLVES_WITH]->()
OPTIONAL MATCH (s:Shipment)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(f)
OPTIONAL MATCH (s)-[:ASSIGNED_TO]->(c:Courier)
RETURN f.failure_id  AS failure_id,
       f.category    AS category,
       f.description AS description,
       f.city        AS city,
       f.district    AS district,
       coalesce(c.name, f.courier) AS courier,
       s.shipment_id AS shipment_id
ORDER BY f.failure_id
LIMIT 200
"""

# Resolved vs unresolved: the part-to-whole the StackedBar renders.
_COVERAGE = """
MATCH (f:FailureReason)
RETURN sum(CASE WHEN (f)-[:RESOLVES_WITH]->() THEN 1 ELSE 0 END) AS resolved,
       sum(CASE WHEN (f)-[:RESOLVES_WITH]->() THEN 0 ELSE 1 END) AS unresolved,
       count(f) AS total
"""

# Per-category success rate, the ranked comparison. This is the precedent the recommender
# actually draws on, so it doubles as an explanation of why it favours the actions it does.
_BY_CATEGORY = """
MATCH (f:FailureReason)-[:RESOLVES_WITH]->(:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
WITH f.category AS category,
     count(*) AS cases,
     sum(CASE WHEN o.success THEN 1 ELSE 0 END) AS succeeded
RETURN category,
       cases,
       succeeded,
       toFloat(succeeded) / cases * 100 AS success_rate
ORDER BY cases DESC
"""

# Which actions the graph has actually seen work, across every category.
_BY_ACTION = """
MATCH (:FailureReason)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
WITH r.action AS action,
     count(*) AS used,
     sum(CASE WHEN o.success THEN 1 ELSE 0 END) AS succeeded
RETURN action,
       used,
       succeeded,
       toFloat(succeeded) / used * 100 AS success_rate
ORDER BY used DESC
LIMIT 8
"""

# The closed loop, measured: Resolutions the pipeline wrote vs the seeded history.
# writeback.py sets source='agent_pipeline' on everything it creates; the dump's own rows have no
# such property, which is what makes this a clean split rather than a guess.
_AGENT_WRITEBACKS = """
MATCH (r:Resolution)
RETURN sum(CASE WHEN r.source = 'agent_pipeline' THEN 1 ELSE 0 END) AS by_agent,
       sum(CASE WHEN r.source = 'agent_pipeline' THEN 0 ELSE 1 END) AS seeded,
       count(r) AS total
"""


# Cases the pipeline handed to a human, newest first - the queue that used to exist only in
# whoever's browser tab. Open ones first, because a closed escalation is history.
_ESCALATIONS = """
MATCH (e:EscalatedCase)
OPTIONAL MATCH (e)-[:ESCALATES]->(f:FailureReason)
RETURN e.escalation_id     AS escalation_id,
       e.complaint         AS complaint,
       e.created_at        AS created_at,
       e.status            AS status,
       e.team              AS team,
       e.reason            AS reason,
       e.category          AS category,
       e.priority          AS priority,
       e.shipment_id       AS shipment_id,
       e.loops             AS loops,
       e.attempted_actions AS attempted_actions,
       f.failure_id        AS failure_id
ORDER BY e.status = 'open' DESC, e.created_at DESC
LIMIT 100
"""

# How the escalated workload splits across teams - the part-to-whole for the Decisions view.
_ESCALATIONS_BY_TEAM = """
MATCH (e:EscalatedCase)
WHERE e.status = 'open'
RETURN e.team AS team, count(*) AS cases
ORDER BY cases DESC
"""


def _read(cypher: str) -> list[dict]:
    return get_driver().execute_query(
        cypher, routing_=RoutingControl.READ, database_=config.SHIPMENT_DATABASE,
        result_transformer_=lambda res: [r.data() for r in res],
    )


def _one(cypher: str) -> dict:
    rows = _read(cypher)
    return rows[0] if rows else {}


def queue() -> list[dict]:
    """Unresolved failures - the live complaint queue."""
    return _read(_QUEUE)


def overview() -> dict:
    """Everything the Decisions view needs in one round trip, so the page renders from a
    single fetch rather than fanning out five requests the UI would have to sequence."""
    return {
        "coverage": _one(_COVERAGE),
        "by_category": _read(_BY_CATEGORY),
        "by_action": _read(_BY_ACTION),
        "writebacks": _one(_AGENT_WRITEBACKS),
        "queue": queue(),
        "escalations": _read(_ESCALATIONS),
        "escalations_by_team": _read(_ESCALATIONS_BY_TEAM),
    }


# Complaint text for the intake chips. Built from real queue rows so the shipment id in the
# chip resolves during extraction and seeds a real graph traversal - a plausible-looking but
# fabricated id extracts fine and then retrieves nothing, which looks like a pipeline bug.
_PHRASING = {
    "address_conflict": "الشحنة {sid} لم تصل والعنوان المسجل غير صحيح",
    "recipient_unavailable": "لم يتم تسليم الشحنة {sid} ولم يتواصل معي المندوب",
    "hub_delay": "الشحنة {sid} متأخرة كثيراً ولم تتحرك من المستودع",
}
_DEFAULT_PHRASING = "لدي مشكلة في الشحنة {sid} ولم يتم حلها حتى الآن"


def examples(limit: int = 4) -> list[dict]:
    """One example complaint per distinct category, capped - enough to show the pipeline
    behaving differently per root cause without turning the composer into a menu."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in queue():
        category = row.get("category") or ""
        if category in seen or not row.get("shipment_id"):
            continue
        seen.add(category)
        template = _PHRASING.get(category, _DEFAULT_PHRASING)
        out.append({
            "category": category,
            "city": row.get("city"),
            "text": template.format(sid=row["shipment_id"]),
        })
        if len(out) >= limit:
            break
    return out


# --- escalation handover packet ----------------------------------------------------------
# When the pipeline gives up, the human inherits the case. Handing over the complaint text
# alone makes them start from zero, so the escalation carries the shipment's own
# neighbourhood: every node it touches and every relationship between them, in the same
# {nodes, relationships} shape the Explore graph view already renders (view/subgraph.py).
#
# Two hops, not one: one hop reaches the Events and the Courier, but the FailureReason hangs
# off an Event rather than the Shipment, so a one-hop view would omit the very thing the case
# is about. Two hops also brings in the precedent chain (Resolution/Outcome) on any sibling
# failure, which is exactly what a human wants to compare against.
# Curated rather than a blind (s)-[*1..2]-(m) walk. Two hops in any direction leaves the
# Shipment, reaches its Policy or Courier, and comes straight back down into every OTHER
# shipment sharing them - measured on SHP-0004 that was 136 nodes, 123 of them unrelated
# shipments. A case file has to be the ONE shipment's story, so each leg is named explicitly
# and hub nodes are terminal: reached, never expanded back out of.
_SHIPMENT_NEIGHBOURHOOD = """
MATCH (s:Shipment {shipment_id: $shipment_id})
CALL (s) {
  // who it belongs to, and where it was going
  OPTIONAL MATCH p = (s)<-[:HAS_SHIPMENT]-(:Order)-[:PLACED_BY]->(:Customer)-[:LIVES_AT]->(:Address)
  RETURN p AS p
  UNION
  OPTIONAL MATCH p = (s)-[:DELIVERED_TO]->(:Address)
  RETURN p AS p
  UNION
  // who was carrying it, and under which SLA - both terminal, not expanded further
  OPTIONAL MATCH p = (s)-[:ASSIGNED_TO]->(:Courier)
  RETURN p AS p
  UNION
  OPTIONAL MATCH p = (s)-[:GOVERNED_BY]->(:Policy)
  RETURN p AS p
  UNION
  // the journey itself, and whatever went wrong on it
  OPTIONAL MATCH p = (s)-[:HAS_EVENT]->(:Event)
  RETURN p AS p
  UNION
  OPTIONAL MATCH p = (s)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(:FailureReason)
  RETURN p AS p
  UNION
  // any fix already attempted on this shipment's own failures, and whether it worked
  OPTIONAL MATCH p = (s)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(:FailureReason)
        -[:RESOLVES_WITH]->(:Resolution)-[:HAD_OUTCOME]->(:Outcome)
  RETURN p AS p
}
WITH p WHERE p IS NOT NULL
RETURN p
"""


# Per-label caption property, in preference order - the shipment graph's equivalent of
# schema.yaml's displayName_* for the governance graph. Without this every node renders as
# its bare label and a 30-node view says nothing.
_CAPTION_PROPS: dict[str, list[str]] = {
    "Shipment": ["shipment_id"],
    "Order": ["order_id"],
    "Customer": ["name", "customer_id"],
    "Courier": ["name", "courier_id"],
    "Address": ["district", "city"],
    "Event": ["event_type"],
    "FailureReason": ["category"],
    "Resolution": ["action"],
    "Outcome": ["notes"],
    "Policy": ["name", "policy_id"],
}
_CAPTION_MAX = 24


def _caption(labels: list[str], props: dict) -> str:
    for label in labels:
        for prop in _CAPTION_PROPS.get(label, []):
            value = props.get(prop)
            if value not in (None, ""):
                text = " ".join(str(value).split())
                return text if len(text) <= _CAPTION_MAX else text[: _CAPTION_MAX - 1] + "…"
    return ":".join(labels) if labels else "?"


def _node_dict(node) -> dict:
    labels = list(node.labels)
    # Drop the embedding: 1024 floats per node, useless to a human and enough to bloat the
    # SSE frame past anything the browser should be parsing mid-stream.
    props = {k: v for k, v in dict(node).items()
             if k != "embedding" and not isinstance(v, (bytes, bytearray))}
    return {"id": node.element_id, "labels": labels,
            "caption": _caption(labels, props), "properties": props}


def shipment_subgraph(shipment_id: str | None) -> dict | None:
    """The shipment's two-hop neighbourhood for an escalated case, or None when the complaint
    never resolved to a shipment (nothing to draw, and inventing one would mislead)."""
    if not shipment_id:
        return None
    from neo4j import Result
    graph = get_driver().execute_query(
        _SHIPMENT_NEIGHBOURHOOD, shipment_id=shipment_id,
        routing_=RoutingControl.READ, database_=config.SHIPMENT_DATABASE,
        result_transformer_=Result.graph,
    )
    if not graph.nodes:
        return None
    return {
        "nodes": [_node_dict(n) for n in graph.nodes],
        "relationships": [{"id": r.element_id, "type": r.type,
                           "from": r.start_node.element_id, "to": r.end_node.element_id}
                          for r in graph.relationships],
    }
