"""Compiles the pipeline stages into one LangGraph StateGraph:

    extract -> retrieve -> classify -> recommend -> review
                             ^                        |
                             |   reject (loop_count < MAX_LOOPS)
                             +------------------------+
                                       |
                            accept     v      reject (cap hit)
                          writeback ---+--- escalate
                               |             |
                               +---> END <---+

Mirrors chat/llm/agent.py's shape (one compiled, memoized graph object) but assembled by
hand with StateGraph rather than create_react_agent, because this graph has real branching:
the reject edge back to `classify` is the AFL loop the architecture is named for.

Why the loop targets `classify` and not `recommend`: a rejection usually means the premise
was wrong, not just the chosen action. Re-running the recommender against an unchanged
classification would re-derive the same proposal from the same reasoning. Routing to the
classifier lets the root cause itself be revised, with the reviewer's objection in hand.

MAX_LOOPS bounds it: a persistently-rejected recommendation escalates to a human instead of
looping the classify/recommend/review triangle forever. Escalation is a legitimate outcome
here, not a failure - it's the diagram's "Accept -> Execute or Escalate" fork.
"""
import logging
from functools import lru_cache

from langgraph.graph import END, StateGraph

from llm.pipeline import classifier, extract, recommender, retrieve, reviewer, writeback
from llm.pipeline.state import PipelineState

log = logging.getLogger("pipeline.graph")

MAX_LOOPS = 2


# --- nodes ------------------------------------------------------------------------------
# Each returns only the keys it changes; LangGraph merges them into the state.

def _extract(state: PipelineState) -> dict:
    return {"extracted": extract.extract_entities(state["complaint_text"])}


def _retrieve(state: PipelineState) -> dict:
    return {"context": retrieve.retrieve_context(state["extracted"])}


def _classify(state: PipelineState) -> dict:
    return {"classification": classifier.classify(state)}


def _recommend(state: PipelineState) -> dict:
    return {"recommendation": recommender.recommend(state)}


def _review(state: PipelineState) -> dict:
    result = reviewer.review(state)
    update: dict = {"review": result}
    if result["verdict"] == "reject":
        # Accumulate, don't overwrite: on a second rejection the classifier should see both
        # objections, or it can "fix" one by reintroducing the other.
        update["review_notes"] = [*(state.get("review_notes") or []), result["reason"]]
        update["loop_count"] = (state.get("loop_count") or 0) + 1
    return update


def _writeback(state: PipelineState) -> dict:
    return {"disposition": "execute", "resolution_id": writeback.write_resolution(state)}


def _escalate(state: PipelineState) -> dict:
    log.info("escalating after %d rejected attempt(s)", state.get("loop_count") or 0)
    return {"disposition": "escalate"}


# --- edges ------------------------------------------------------------------------------

def _after_review(state: PipelineState) -> str:
    """Conditional edge out of review: accept -> writeback, reject -> classify (under the
    cap) or escalate (cap reached)."""
    verdict = (state.get("review") or {}).get("verdict")
    if verdict == "accept":
        return "writeback"
    if (state.get("loop_count") or 0) >= MAX_LOOPS:
        return "escalate"
    return "classify"


@lru_cache(maxsize=1)
def build_pipeline():
    """Assemble and compile the graph. Memoized the same way chat/llm/agent.py._agent() is -
    expensive to build, safe to reuse across requests."""
    g = StateGraph(PipelineState)
    g.add_node("extract", _extract)
    g.add_node("retrieve", _retrieve)
    g.add_node("classify", _classify)
    g.add_node("recommend", _recommend)
    g.add_node("review", _review)
    g.add_node("writeback", _writeback)
    g.add_node("escalate", _escalate)

    g.set_entry_point("extract")
    g.add_edge("extract", "retrieve")
    g.add_edge("retrieve", "classify")
    g.add_edge("classify", "recommend")
    g.add_edge("recommend", "review")
    g.add_conditional_edges("review", _after_review,
                            {"writeback": "writeback", "classify": "classify", "escalate": "escalate"})
    g.add_edge("writeback", END)
    g.add_edge("escalate", END)
    return g.compile()


def run_complaint(complaint_text: str) -> PipelineState:
    """Run one complaint end to end and return the final state - classification,
    recommendation, review verdict, disposition (execute/escalate), and the resolution_id if
    it was written back."""
    initial: PipelineState = {
        "complaint_text": complaint_text,
        "extracted": None,
        "context": None,
        "classification": None,
        "recommendation": None,
        "review": None,
        "review_notes": [],
        "loop_count": 0,
        "disposition": None,
        "resolution_id": None,
    }
    return build_pipeline().invoke(initial)
