"""The pipeline's only write path against config.SHIPMENT_DATABASE - deliberately isolated
here the same way scripts/embed_backfill.py's write path is kept out of the read-only FastAPI
backend (see backend/main.py: "none of which generate Cypher on the fly"). This module is the
one narrow exception, and only for a single fixed shape of write.

Runs once reviewer.py accepts: appends
    (FailureReason)-[:RESOLVES_WITH]->(Resolution)-[:HAD_OUTCOME]->(Outcome)
onto the live FailureReason the complaint resolved to, in exactly the shape
shipment_kg/generate_shipment_kg.py used for the historical cases. This records the reviewed
recommendation for audit. The pending Outcome is not observed
success and must not become historical precedent until actual execution is confirmed.

The new Resolution is written WITHOUT a case_summary embedding. Observed outcome backfill
is separate. Embedding inline would put a model call inside a write
transaction, and a slow or unavailable Ollama would then roll back a decision that was
already approved.
"""
import logging
import math
import uuid
from datetime import datetime, timezone

from neo4j import RoutingControl

import config
from core.query_runner import get_driver
from llm.pipeline import _llm, operator_output
from llm.pipeline.reviewer import ACCEPT_THRESHOLD
from llm.pipeline.state import PipelineState

log = logging.getLogger("pipeline.writeback")

# Lock the validated failure before checking its existing chain. The temporary property is
# removed in the same transaction (Neo4j's documented lock pattern), never persisted.
# The create branch only handles an unresolved failure; replay returns only an identical
# agent recommendation. Seeded history and different pending actions are never overwritten.
_WRITE = """
MATCH (s:Shipment {shipment_id: $shipment_id})-[:HAS_EVENT]->(:Event)
      -[:CAUSED_BY]->(f:FailureReason {failure_id: $failure_id})
WHERE ($tracking_id IS NULL OR s.tracking_id = $tracking_id)
  AND NOT EXISTS {
    MATCH (other:Shipment)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(f)
    WHERE other <> s
  }
WITH DISTINCT s, f
WHERE f.__suhail_write_lock IS NULL
SET f.__suhail_write_lock = true
REMOVE f.__suhail_write_lock
WITH s, f
CALL (s, f) {
  WITH s, f
  WHERE NOT EXISTS { MATCH (f)-[:RESOLVES_WITH]->(:Resolution) }
  CREATE (f)-[:RESOLVES_WITH]->(r:Resolution {
    resolution_id: $resolution_id, action: $action, timestamp: $timestamp,
    source: 'agent_pipeline', shipment_id: $shipment_id, failure_id: $failure_id,
    review_verdict: 'accept', review_score: $review_score, approval_type: 'agent_review'
  })-[:HAD_OUTCOME]->(o:Outcome {
    outcome_id: $outcome_id, status: 'pending', success: $success,
    notes: $notes, timestamp: $timestamp,
    source: 'agent_pipeline', shipment_id: $shipment_id, failure_id: $failure_id
  })
  SET f.case_summary = coalesce(f.case_summary,
        f.category + ' | city=' + coalesce(f.city, '') +
        ' | district=' + coalesce(f.district, '') +
        ' | courier=' + coalesce(f.courier, '') +
        ' | ' + coalesce(f.description, '') +
        ' | timestamp=' + coalesce(toString(f.timestamp), ''))
  RETURN r.resolution_id AS resolution_id
  UNION
  WITH s, f
  MATCH (f)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
  WHERE r.resolution_id = $resolution_id AND r.action = $action
    AND r.source = 'agent_pipeline' AND r.shipment_id = $shipment_id
    AND r.failure_id = $failure_id AND o.outcome_id = $outcome_id
    AND o.source = 'agent_pipeline'
    AND NOT EXISTS {
      MATCH (f)-[:RESOLVES_WITH]->(other:Resolution) WHERE other <> r
    }
  RETURN r.resolution_id AS resolution_id
}
RETURN resolution_id
"""


def _identity(state: PipelineState) -> tuple[str, str, str | None] | None:
    """Require extraction, retrieval and local evidence to name the same shipment/failure."""
    extracted = state.get("extracted") or {}
    ctx = state.get("context") or {}
    local = ctx.get("local_subgraph") or {}
    shipment = local.get("shipment") or {}
    failure = local.get("live_failure") or {}
    shipment_id = shipment.get("shipment_id")
    failure_id = ctx.get("live_failure_id")
    if not isinstance(shipment_id, str) or not isinstance(failure_id, str):
        return None
    if not shipment_id.strip() or not failure_id.strip() or failure.get("failure_id") != failure_id:
        return None
    sid, tracking = extracted.get("shipment_id"), extracted.get("tracking_id")
    if not (sid or tracking):
        return None
    if sid and sid != shipment_id:
        return None
    if tracking and tracking != shipment.get("tracking_id"):
        return None
    return shipment_id, failure_id, tracking


def _stable_id(prefix: str, *values: str) -> str:
    # uuid5 is stable across process restarts and execute_query transaction retries.
    key = "suhail:" + ":".join(f"{len(value)}:{value}" for value in values)
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, key).hex}"


def write_resolution(state: PipelineState) -> str | None:
    """Write the accepted recommendation as a new Resolution + Outcome chain off the live
    FailureReason this complaint resolved to, and return the new resolution_id.

    Returns None (without writing) when retrieval never identified a live FailureReason -
    there is nothing to attach the resolution to, and inventing a node to hang it from would
    corrupt the graph the next run retrieves from.
    """
    rec = state.get("recommendation") or {}
    rev = state.get("review") or {}
    action = rec.get("action")
    score = rev.get("score")
    if (rev.get("verdict") != "accept" or not isinstance(action, str)
            or type(score) not in (int, float) or not math.isfinite(score)
            or not ACCEPT_THRESHOLD <= score <= 1):
        log.info("recommendation has no valid accepted review - skipping write-back")
        return None
    action = _llm.final_text(action).strip()
    identity = _identity(state)
    if not action or not identity:
        log.info("recommendation has no action or consistent shipment/failure identity - skipping write-back")
        return None
    shipment_id, failure_id, tracking_id = identity
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resolution_id = _stable_id("RES", shipment_id, failure_id, action)

    records, _, _ = get_driver().execute_query(
        _WRITE,
        parameters_={
            "failure_id": failure_id,
            "shipment_id": shipment_id,
            "tracking_id": tracking_id,
            "resolution_id": resolution_id,
            "action": action,
            "timestamp": now,
            "outcome_id": _stable_id("OUT", resolution_id),
            "review_score": score,
            # Flips to 'succeeded'/'failed' when the action is actually carried out and
            # reported back - the feedback path a real deployment supplies and this one does
            # not yet have.
            # NOT True. The action was approved, not performed: nobody has observed whether
            # it worked. Writing success=true would feed the graph an outcome it never saw,
            # and because the recommender ranks candidate actions BY historical success rate,
            # those invented successes would compound - the agent would increasingly prefer
            # whatever it had already chosen, on evidence it manufactured. null plus an
            # explicit status keeps "decided" and "worked" as different facts, and the
            # success-rate queries all skip nulls rather than counting them either way.
            "success": None,
            "notes": ("Agent recommendation accepted; execution unconfirmed. "
                      + operator_output.review_summary(state, rev)).strip(),
        },
        routing_=RoutingControl.WRITE,
        database_=config.SHIPMENT_DATABASE,
    )
    written = records[0]["resolution_id"] if records else None
    log.info("resolution recording result %s for failure %s", written, failure_id)
    return written


# --- escalations --------------------------------------------------------------------------
# An escalation used to exist only as a flag in memory: the run ended, and everything the
# pipeline had worked out lived in the browser tab of whoever submitted the complaint. Close
# it and a colleague picking the case up later had the customer's sentence and nothing else.
# Persisting it makes escalation a handover rather than a dead end - and gives the Decisions
# view a real queue to show.

# Which team owns which root cause. Derived from the category rather than chosen by a model:
# routing is an org-chart fact, not a judgement call, and a hallucinated team name would send
# a case nowhere. Unknown or unclassified causes go to general support rather than being
# dropped - the fallback has to be a real queue, not silence.
TEAM_BY_CATEGORY: dict[str, str] = {
    "address_conflict": "عمليات العناوين",
    "recipient_unavailable": "خدمة العملاء",
    "hub_delay": "عمليات المستودع",
    "failed_attempt_wrong_gate": "عمليات التسليم",
    "failed_attempt_barcode_mismatch": "عمليات الفرز",
    "failed_attempt_weight_mismatch": "عمليات الفرز",
}
DEFAULT_TEAM = "الدعم العام"

# Require an actual shipment; a supplied failure must belong to that shipment. Stable IDs
# plus a temporary shipment lock make repeated handoff attempts duplicate-safe. Existing
# handoffs are replayed unchanged only when their category agrees with this attempt.
_WRITE_ESCALATION = """
MATCH (s:Shipment {shipment_id: $shipment_id})
WHERE ($tracking_id IS NULL OR s.tracking_id = $tracking_id)
  AND ($failure_id IS NULL OR EXISTS {
    MATCH (s)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(f:FailureReason {failure_id: $failure_id})
  })
  AND s.__suhail_escalation_lock IS NULL
SET s.__suhail_escalation_lock = true
REMOVE s.__suhail_escalation_lock
WITH s
OPTIONAL MATCH (existing:EscalatedCase {escalation_id: $escalation_id})
WITH s, existing
WHERE existing IS NULL OR (existing.source = 'agent_pipeline'
  AND existing.shipment_id = $shipment_id
  AND coalesce(existing.category, '') = coalesce($category, ''))
MERGE (e:EscalatedCase {escalation_id: $escalation_id})
  ON CREATE SET e.complaint       = $complaint,
                e.created_at      = $created_at,
                e.status          = 'open',
                e.source          = 'agent_pipeline',
                e.failure_id      = $failure_id,
                e.team            = $team,
                e.reason          = $reason,
                e.category        = $category,
                e.confidence      = $confidence,
                e.priority        = $priority,
                e.shipment_id     = $shipment_id,
                e.loops           = $loops,
                e.attempted_actions = $attempted_actions,
                e.review_notes    = $review_notes
WITH e
CALL (e) {
  WITH e
  MATCH (f:FailureReason {failure_id: $failure_id})
  MERGE (e)-[:ESCALATES]->(f)
  RETURN count(*) AS linked
}
RETURN e.escalation_id AS escalation_id, e.team AS team
"""


def _escalation_reason(state: PipelineState) -> str:
    """Why this case is with a human, in the vocabulary the pipeline actually used."""
    review = state.get("review") or {}
    if not review:
        return "No eligible observed precedent above the similarity floor; human investigation required."
    if review.get("verdict") == "accept":
        return ("Recommendation accepted but not recordable against a verified unresolved "
                "failure. Existing recommendations or conflicting identity require operator review.")
    return operator_output.review_summary(state, review)


def write_escalation(state: PipelineState) -> dict | None:
    """Record an escalated case so it outlives the request, and return {escalation_id, team}.

    Only for a complaint that resolved to a real shipment. An earlier version of this filed
    every escalation, and since the intake box accepted free text at the time, anything typed
    into it landed in the knowledge graph permanently - "asdf qwerty 12345" became a row in
    the escalation table. The composer is gone now and the worklist only offers real cases,
    but the guard belongs here rather than in the UI: the graph should not depend on a
    frontend choice to stay clean.

    A case with no shipment is still escalated and still shown - it simply is not written
    down, because there is nothing to write it against.

    Best-effort by contract: the caller treats a None here as "not recorded" and still
    escalates. Failing to file the paperwork must not change the decision.
    """
    extracted = state.get("extracted") or {}
    ctx = state.get("context") or {}
    local_shipment = (ctx.get("local_subgraph") or {}).get("shipment") or {}
    shipment_id = local_shipment.get("shipment_id") or extracted.get("shipment_id")
    failure_id = ctx.get("live_failure_id")
    tracking_id = extracted.get("tracking_id")
    if (not isinstance(shipment_id, str) or not shipment_id.strip()
            or (extracted.get("shipment_id") and extracted["shipment_id"] != shipment_id)
            or (tracking_id and tracking_id != local_shipment.get("tracking_id"))
            or (failure_id and _identity(state) is None)):
        log.info("escalation not recorded - the complaint named no shipment")
        return None
    classification = state.get("classification") or {}
    category = classification.get("category")
    team = TEAM_BY_CATEGORY.get(category or "", DEFAULT_TEAM)

    # Every action the pipeline proposed and the reviewer turned down - the single most useful
    # thing for the human, since it says what has already been ruled out and why.
    attempted = [_llm.final_text(r) for r in (state.get("attempted_actions") or []) if isinstance(r, str) and r]
    rec = state.get("recommendation") or {}
    if isinstance(rec.get("action"), str) and (action := _llm.final_text(rec["action"])) and action not in attempted:
        attempted.append(action)

    escalation_id = _stable_id("ESC", shipment_id, failure_id or "no_live_failure")
    params = {
        "escalation_id": escalation_id,
        "complaint": state.get("complaint_text"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "team": team,
        "reason": _llm.final_text(_escalation_reason(state)),
        "category": category,
        "confidence": classification.get("confidence"),
        "priority": classification.get("priority"),
        "shipment_id": shipment_id,
        "tracking_id": tracking_id,
        "loops": state.get("loop_count") or 0,
        "attempted_actions": attempted,
        "review_notes": [operator_output.review_summary(state, state.get("review") or {})]
                        if state.get("review_notes") else [],
        # NULL is fine: the CALL subquery simply matches nothing and the node stands alone.
        "failure_id": failure_id,
    }
    try:
        records, _, _ = get_driver().execute_query(
            _WRITE_ESCALATION, parameters_=params,
            routing_=RoutingControl.WRITE, database_=config.SHIPMENT_DATABASE,
        )
    except Exception as exc:
        log.error("could not record the escalated case (%s)", type(exc).__name__)
        return None
    if not records:
        return None
    log.info("recorded escalation %s for team %s", escalation_id, team)
    return {"escalation_id": escalation_id, "team": team}
