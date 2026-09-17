"""The pipeline's only write path against config.SHIPMENT_DATABASE - deliberately isolated
here the same way scripts/embed_backfill.py's write path is kept out of the read-only FastAPI
backend (see backend/main.py: "none of which generate Cypher on the fly"). This module is the
one narrow exception, and only for a single fixed shape of write.

Runs once reviewer.py accepts: appends
    (FailureReason)-[:RESOLVES_WITH]->(Resolution)-[:HAD_OUTCOME]->(Outcome)
onto the live FailureReason the complaint resolved to, in exactly the shape
shipment_kg/generate_shipment_kg.py used for the 150 historical cases. That shape-matching is
what closes the loop in the diagram: the case just handled becomes indistinguishable from
seeded precedent, so the next run's vector search can retrieve it.

The new Resolution is written WITHOUT a case_summary embedding - scripts/embed_backfill_shipments.py
picks it up on its next run. Embedding inline would put a model call inside a write
transaction, and a slow or unavailable Ollama would then roll back a decision that was
already approved.
"""
import logging
import uuid
from datetime import datetime

from neo4j import RoutingControl

import config
from core.query_runner import get_driver
from llm.pipeline.state import PipelineState

log = logging.getLogger("pipeline.writeback")

# MERGE on the ids (not CREATE) so a retried write is idempotent rather than duplicating the
# chain. Also stamps case_summary in the same concatenated format generate_shipment_kg.py
# used, so the backfill script treats this case exactly like a seeded one.
_WRITE = """
MATCH (f:FailureReason {failure_id: $failure_id})
MERGE (f)-[:RESOLVES_WITH]->(r:Resolution {resolution_id: $resolution_id})
  ON CREATE SET r.action = $action,
                r.timestamp = $timestamp,
                r.source = 'agent_pipeline'
MERGE (r)-[:HAD_OUTCOME]->(o:Outcome {outcome_id: $outcome_id})
  ON CREATE SET o.success = $success,
                o.status = $status,
                o.notes = $notes,
                o.timestamp = $timestamp
SET f.case_summary = coalesce(f.case_summary,
      f.category + ' | city=' + coalesce(f.city, '') +
      ' | district=' + coalesce(f.district, '') +
      ' | courier=' + coalesce(f.courier, '') +
      ' | ' + coalesce(f.description, '') +
      ' | timestamp=' + coalesce(toString(f.timestamp), ''))
RETURN r.resolution_id AS resolution_id
"""


def write_resolution(state: PipelineState) -> str | None:
    """Write the accepted recommendation as a new Resolution + Outcome chain off the live
    FailureReason this complaint resolved to, and return the new resolution_id.

    Returns None (without writing) when retrieval never identified a live FailureReason -
    there is nothing to attach the resolution to, and inventing a node to hang it from would
    corrupt the graph the next run retrieves from.
    """
    ctx = state.get("context") or {}
    failure_id = ctx.get("live_failure_id")
    if not failure_id:
        log.warning("no live FailureReason identified - skipping write-back")
        return None

    rec = state.get("recommendation") or {}
    rev = state.get("review") or {}
    now = datetime.now().isoformat(timespec="seconds")
    resolution_id = f"RES-{uuid.uuid4().hex[:10]}"

    records, _, _ = get_driver().execute_query(
        _WRITE,
        parameters_={
            "failure_id": failure_id,
            "resolution_id": resolution_id,
            "action": rec.get("action"),
            "timestamp": now,
            "outcome_id": f"OUT-{uuid.uuid4().hex[:10]}",
            # Flips to 'succeeded'/'failed' when the action is actually carried out and
            # reported back - the feedback path a real deployment supplies and this one does
            # not yet have.
            "status": "pending",
            # NOT True. The action was approved, not performed: nobody has observed whether
            # it worked. Writing success=true would feed the graph an outcome it never saw,
            # and because the recommender ranks candidate actions BY historical success rate,
            # those invented successes would compound - the agent would increasingly prefer
            # whatever it had already chosen, on evidence it manufactured. null plus an
            # explicit status keeps "decided" and "worked" as different facts, and the
            # success-rate queries all skip nulls rather than counting them either way.
            "success": None,
            "notes": f"Agent pipeline: {rev.get('reason', '')}".strip(),
        },
        routing_=RoutingControl.WRITE,
        database_=config.SHIPMENT_DATABASE,
    )
    written = records[0]["resolution_id"] if records else None
    log.info("wrote resolution %s for failure %s", written, failure_id)
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

# Attached to the live FailureReason when one was identified, and standalone otherwise - an
# escalation with no resolvable shipment is exactly the case a human most needs to see, so it
# must still be recorded. MERGE on escalation_id keeps a retried write idempotent.
_WRITE_ESCALATION = """
MERGE (e:EscalatedCase {escalation_id: $escalation_id})
  ON CREATE SET e.complaint       = $complaint,
                e.created_at      = $created_at,
                e.status          = 'open',
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
        return "No precedent above the similarity floor and no matching shipment - nothing to reason from."
    if review.get("verdict") == "accept":
        return ("Recommendation accepted but not recordable: the complaint resolved to no live "
                "failure in the graph.")
    return review.get("reason") or "Rejected by review."


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
    shipment_id = (state.get("extracted") or {}).get("shipment_id")
    if not shipment_id:
        log.info("escalation not recorded - the complaint named no shipment")
        return None
    classification = state.get("classification") or {}
    category = classification.get("category")
    team = TEAM_BY_CATEGORY.get(category or "", DEFAULT_TEAM)

    # Every action the pipeline proposed and the reviewer turned down - the single most useful
    # thing for the human, since it says what has already been ruled out and why.
    attempted = [r for r in (state.get("attempted_actions") or []) if r]
    rec = state.get("recommendation") or {}
    if rec.get("action") and rec["action"] not in attempted:
        attempted.append(rec["action"])

    escalation_id = f"ESC-{uuid.uuid4().hex[:10]}"
    params = {
        "escalation_id": escalation_id,
        "complaint": state.get("complaint_text"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "team": team,
        "reason": _escalation_reason(state),
        "category": category,
        "confidence": classification.get("confidence"),
        "priority": classification.get("priority"),
        "shipment_id": shipment_id,
        "loops": state.get("loop_count") or 0,
        "attempted_actions": attempted,
        "review_notes": state.get("review_notes") or [],
        # NULL is fine: the CALL subquery simply matches nothing and the node stands alone.
        "failure_id": (state.get("context") or {}).get("live_failure_id"),
    }
    try:
        records, _, _ = get_driver().execute_query(
            _WRITE_ESCALATION, parameters_=params,
            routing_=RoutingControl.WRITE, database_=config.SHIPMENT_DATABASE,
        )
    except Exception:
        log.exception("could not record the escalated case")
        return None
    if not records:
        return None
    log.info("recorded escalation %s for team %s", escalation_id, team)
    return {"escalation_id": escalation_id, "team": team}
