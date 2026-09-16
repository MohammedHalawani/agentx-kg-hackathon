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


# --- streaming --------------------------------------------------------------------------

# What each node contributes to the live trace the UI renders (backend /complaint -> SSE).
# Per-node trace vocabulary, taken from the architecture diagram so the UI and the diagram
# say the same words: the diagram's swimlane on the left, and for the three agents the Arabic
# name it gives them. Kept here rather than in the backend so the stage vocabulary lives next
# to the nodes it names - adding a node above and forgetting it here is a one-file mistake.
STAGE_META: dict[str, dict[str, str]] = {
    "extract":   {"label": "Entity Extraction",        "lane": "Input",            "arabic": ""},
    "retrieve":  {"label": "Vector KNN + Graph \u2192 RRF", "lane": "Hybrid Retrieval", "arabic": ""},
    "classify":  {"label": "Root-cause classification", "lane": "Classification",   "arabic": "\u0627\u0644\u0645\u0635\u0646\u0651\u0641"},
    "recommend": {"label": "Candidate actions",         "lane": "Recommendation",   "arabic": "\u0627\u0644\u0645\u064f\u0648\u0635\u064a"},
    "review":    {"label": "Validation",                "lane": "Evaluation",       "arabic": "\u0627\u0644\u0645\u0631\u0627\u062c\u0639"},
    "writeback": {"label": "Write-back",                "lane": "Output",           "arabic": ""},
    "escalate":  {"label": "Escalate",                  "lane": "Output",           "arabic": ""},
}

# The three agents the diagram actually names in Arabic, as opposed to the support stages.
# The UI badges these differently - extract/retrieve are plumbing, these three decide.
AGENT_NODES = frozenset({"classify", "recommend", "review"})


def _summarize(node: str, update: dict, loop: int) -> dict:
    """One node's state update, flattened into the compact shape the trace renders. Only
    what a reader needs to see the decision being made - never the whole state, which
    carries the full retrieved subgraph and would dwarf the trace."""
    meta = STAGE_META.get(node, {})
    out: dict = {
        "stage": node,
        "label": meta.get("label", node),
        "lane": meta.get("lane", ""),
        "arabic": meta.get("arabic", ""),
        "is_agent": node in AGENT_NODES,
        "loop": loop,
    }
    if node == "extract" and (e := update.get("extracted")):
        out["detail"] = {k: v for k, v in e.items() if k != "raw_text" and v}
    elif node == "retrieve" and (c := update.get("context")):
        out["detail"] = {
            "similar_cases": len(c.get("similar_cases") or []),
            "live_failure_id": c.get("live_failure_id"),
            "precedent": (c.get("similar_cases") or [])[:3],
        }
    elif node == "classify" and (c := update.get("classification")):
        out["detail"] = dict(c)
    elif node == "recommend" and (r := update.get("recommendation")):
        out["detail"] = dict(r)
    elif node == "review" and (r := update.get("review")):
        out["detail"] = dict(r)
        out["verdict"] = r.get("verdict")
    elif node == "writeback":
        out["detail"] = {"resolution_id": update.get("resolution_id")}
    return out


def stream_complaint(complaint_text: str):
    """Run one complaint, yielding (kind, payload) per pipeline stage as it completes.

    kind is "stage" for each node, then "final" once with the disposition. The AFL loop
    shows up naturally: `classify` is simply yielded a second time with loop=1, which is
    what makes the retry visible in the UI rather than merely asserted.
    """
    state: PipelineState = {
        "complaint_text": complaint_text,
        "extracted": None, "context": None, "classification": None,
        "recommendation": None, "review": None, "review_notes": [],
        "loop_count": 0, "disposition": None, "resolution_id": None,
    }
    merged: dict = dict(state)
    loop = 0
    for step in build_pipeline().stream(state, stream_mode="updates"):
        for node, update in step.items():
            merged.update(update or {})
            loop = merged.get("loop_count") or 0
            yield "stage", _summarize(node, update or {}, loop)
    yield "final", {
        "disposition": merged.get("disposition"),
        "resolution_id": merged.get("resolution_id"),
        "loops": merged.get("loop_count") or 0,
        "classification": merged.get("classification"),
        "recommendation": merged.get("recommendation"),
        "review": merged.get("review"),
    }
