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
