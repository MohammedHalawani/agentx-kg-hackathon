"""The pipeline's only write path against config.SHIPMENT_DATABASE - deliberately isolated
here the same way chat/scripts/embed_backfill.py's write path is kept out of the read-only
FastAPI backend (see backend/main.py's docstring: "none of which generate Cypher on the
fly" - this module is the one deliberate, narrow exception, and only for one fixed shape
of write, not arbitrary Cypher).

Runs once reviewer.py returns an "accept" verdict: appends
    (FailureReason)-[:RESOLVES_WITH]->(Resolution)-[:HAD_OUTCOME]->(Outcome)
onto the live FailureReason node the complaint resolved to, in exactly the shape
generate_shipment_kg.py already used for the 150 historical resolved cases - so the case
this pipeline just handled becomes retrievable precedent for the next one.
"""
from llm.pipeline.state import PipelineState


def write_resolution(state: PipelineState) -> str:
    """Write the accepted state["recommendation"] as a new Resolution + Outcome chain off
    the FailureReason state["extracted"]/state["context"] resolved to, and return the new
    resolution_id. Only ever called after review.verdict == "accept"."""
    ...
