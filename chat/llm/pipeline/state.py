"""The LangGraph state threaded through every pipeline node (see graph.py). One dict per
in-flight complaint; nothing here is persisted between runs - see writeback.py for the one
thing that is (the new Resolution/Outcome chain, once a recommendation is accepted).
"""
from typing import Literal, TypedDict


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
    """The fused output of retrieve.py's vector_search + graph_traversal, ready for the
    classifier - resolved historical cases (with their FailureReason/Resolution/Outcome
    chain) plus any graph-local context around the current complaint's own shipment."""
    similar_cases: list[dict]     # resolved FailureReason nodes + their case_summary, ranked
    local_subgraph: dict          # nodes/relationships within N hops of the matched shipment


class Classification(TypedDict):
    category: str        # matches an existing FailureReason.category value where possible
    confidence: float     # 0-1
    priority: Literal["low", "medium", "high"]
    rationale: str


class Recommendation(TypedDict):
    action: str                 # matches the Resolution.action vocabulary already in the graph
    grounded_in: list[str]      # resolution_id(s) of the similar cases this action is based on
    rationale: str


class Review(TypedDict):
    verdict: Literal["accept", "reject"]
    reason: str
    checked_against: list[str]  # e.g. ["SLA", "evidence", "business_rules", "prior_outcomes"]


class PipelineState(TypedDict):
    complaint_text: str
    extracted: ExtractedComplaint | None
    context: RetrievedContext | None
    classification: Classification | None
    recommendation: Recommendation | None
    review: Review | None
    review_notes: list[str]     # accumulated reviewer feedback, carried into re-classification
    loop_count: int             # AFL retries so far; graph.py caps this to avoid infinite loops
    resolution_id: str | None   # set by writeback.py once accepted and written to Neo4j
