"""The LangGraph state threaded through every pipeline node (see graph.py). One dict per
in-flight complaint; nothing here is persisted between runs - see writeback.py for the one
thing that is (the new Resolution/Outcome chain, once a recommendation is accepted).
"""
from typing import Literal, TypedDict

Verdict = Literal["accept", "reject"]
Disposition = Literal["execute", "escalate"]


class ExtractedComplaint(TypedDict):
    """Structured fields pulled from the free-text complaint by extract.py. All optional -
    a complaint may name a courier but not a shipment id, for example."""
    shipment_id: str | None
    tracking_id: str | None
    city: str | None
    district: str | None
    courier: str | None
    category_hint: str | None  # a guess at FailureReason.category, not authoritative
    raw_text: str


class RetrievedContext(TypedDict):
    """The fused output of retrieve.py's vector_search + graph_traversal - resolved
    historical cases (with their FailureReason/Resolution/Outcome chain) plus the graph-local
    context around the complaint's own shipment."""
    similar_cases: list[dict]   # resolved cases, RRF-ranked, each with action + outcome
    local_subgraph: dict        # {shipment, events, failure, courier, address, policy}
    live_failure_id: str | None  # the unresolved FailureReason this complaint is about


class Classification(TypedDict):
    category: str      # matches an existing FailureReason.category where possible
    confidence: float  # 0-1
    priority: Literal["low", "medium", "high"]
    rationale: str


class Recommendation(TypedDict):
    action: str               # ideally from the Resolution.action vocabulary already in the graph
    grounded_in: list[str]    # resolution_id(s) of the cases this action is based on
    rationale: str
    candidates: list[dict]    # the other actions considered, with their historical success rate
    # The cited precedent rows (id, category, action, success), so the reviewer can check the
    # citations are for the same root cause and not merely present.
    grounded_cases: list[dict]


class Review(TypedDict):
    verdict: Verdict
    score: float              # 0-1 evaluation score (the diagram's "Evaluation Score")
    reason: str
    checked_against: list[str]  # e.g. ["evidence", "business_rules", "sla", "historical_outcomes"]


class PipelineState(TypedDict):
    complaint_text: str
    extracted: ExtractedComplaint | None
    context: RetrievedContext | None
    classification: Classification | None
    recommendation: Recommendation | None
    review: Review | None
    review_notes: list[str]      # accumulated reviewer feedback, carried into re-classification
    # Every action the reviewer turned down, in order. Kept alongside review_notes because a
    # human inheriting an escalated case needs to know what has already been ruled out - the
    # notes say why, this says what.
    attempted_actions: list[str]
    loop_count: int              # AFL retries so far; graph.py caps this via MAX_LOOPS
    disposition: Disposition | None  # set at the end: execute (accepted) or escalate
    resolution_id: str | None    # set by writeback.py once written to Neo4j
    # On escalation only: the shipment's own neighbourhood as {nodes, relationships}, so the
    # human inheriting the case gets the graph around it rather than just the complaint text.
    # None when the complaint never resolved to a real shipment - there is nothing to draw.
    handover: dict | None
    # Holdout evaluation only (scripts/eval_pipeline.py): the failure being graded, kept out
    # of retrieval so a resolved case cannot retrieve its own answer. None in normal runs.
    exclude_failure_id: str | None
    # On escalation only: {escalation_id, team} once the case has been filed in the graph,
    # or None if filing was skipped or failed - the decision to escalate stands either way.
    escalation: dict | None
