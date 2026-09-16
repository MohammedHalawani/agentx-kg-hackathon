"""Accept or reject the recommendation before anything is written back to Neo4j - the last
check before writeback.py runs, and the source of the AFL loop's feedback when it rejects.

Checks against (see Review.checked_against in state.py): the policy's SLA (Shipment
-[:GOVERNED_BY]->Policy.sla_days/retry_limit), whether the recommendation actually cites
evidence from state["context"] rather than asserting unsupported claims, fixed business
rules (e.g. don't recommend re-delivery on a shipment that already hit Policy.retry_limit),
and whether a near-identical past case's Outcome.success was false - if so, recommending
the same action again should raise the bar for acceptance, not repeat a known failure.
"""
from llm.pipeline.state import PipelineState, Review


def review(state: PipelineState) -> Review:
    """Judge state["recommendation"] against state["context"] and the shipment's own
    Policy - an LLM call via config.LLM_MODEL for the judgment itself, but every check it
    can lean on (SLA breach, retry_limit, a prior failed Outcome for this exact action) is
    a fact pulled from the graph, not the model's own recollection."""
    ...
