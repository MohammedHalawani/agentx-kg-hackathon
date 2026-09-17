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
            # The action was approved, not yet performed - success records the DECISION's
            # acceptance. A real deployment would update this once the action completes.
            "success": True,
            "notes": f"Agent pipeline: {rev.get('reason', '')}".strip(),
        },
        routing_=RoutingControl.WRITE,
        database_=config.SHIPMENT_DATABASE,
    )
    written = records[0]["resolution_id"] if records else None
    log.info("wrote resolution %s for failure %s", written, failure_id)
    return written
