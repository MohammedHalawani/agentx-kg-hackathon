"""Root-cause classification over the fused subgraph retrieve.py returns.

Re-entered on an AFL loop: when reviewer.py rejects a recommendation, graph.py routes back
here with state["review_notes"] populated, so classify() gets a chance to correct course
(e.g. the reviewer found the priority too low for the SLA already breached) rather than
recommender.py just retrying the same recommendation against the same classification.
"""
from llm.pipeline.state import Classification, PipelineState


def classify(state: PipelineState) -> Classification:
    """Classify the complaint's root cause using state["context"] (and, on a re-entry,
    state["review_notes"]) - an LLM call via config.LLM_MODEL, not a fixed rules engine,
    since FailureReason.category in the graph is itself a small fixed vocabulary the model
    is being asked to pick from (address_conflict, recipient_unavailable,
    failed_attempt_wrong_gate/barcode_mismatch/weight_mismatch, hub_delay, or an
    escalation:<subtype> compound)."""
    ...
