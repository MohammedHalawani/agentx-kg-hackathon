"""Compiles the pipeline stages into one LangGraph StateGraph:

    extract -> retrieve -> classify -> recommend -> review
                    |        ^                        |
      no grounding  |        |   reject (loop_count < MAX_LOOPS)
                    |        +------------------------+
                    |                  |
                    |       accept     v      reject (cap hit)
                    |     writeback ---+--- escalate
                    |          |             ^   |
                    |          | nothing     |   |
                    |          | written ----+   |
                    +--------------------------->+
                               |                 |
                               +---> END <-------+

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

from llm.pipeline import cases, classifier, extract, recommender, retrieve, reviewer, writeback
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
        rejected = (state.get("recommendation") or {}).get("action")
        if rejected:
            update["attempted_actions"] = [*(state.get("attempted_actions") or []), rejected]
    return update


def _writeback(state: PipelineState) -> dict:
    """Record the accepted decision - and only claim "execute" if it was actually recorded.

    write_resolution() returns None when retrieval never resolved a live FailureReason, so
    there is no node to attach the resolution to (a complaint naming no shipment, or one
    naming a shipment that doesn't exist). The decision then cannot enter the graph, which
    means it also can't become precedent and can't be audited later. Reporting that as
    "execute" would tell an operator the case is handled when nothing was written at all -
    a silent failure the human-in-the-loop never sees. Escalating routes it to exactly the
    review the accept path was trying to skip.
    """
    resolution_id = writeback.write_resolution(state)
    if resolution_id is None:
        log.info("accepted recommendation could not be written back - escalating instead")
        return {
            "disposition": "escalate",
            "resolution_id": None,
            "handover": _handover(state),
            "escalation": writeback.write_escalation(state),
        }
    return {"disposition": "execute", "resolution_id": resolution_id}


def _handover(state: PipelineState) -> dict | None:
    """The case file a human inherits with an escalated case.

    Escalating with only the complaint text makes the human start from zero - they get the
    customer's sentence and nothing the pipeline learned. This attaches the shipment's own
    neighbourhood (order, customer, addresses, courier, policy, its whole event timeline, the
    failure and any fix already tried), which the UI renders with the same graph component
    the Explore tab uses.

    Best-effort: a handover that fails must never turn an escalation into an error, because
    the escalation itself is the thing that matters.
    """
    shipment_id = (state.get("extracted") or {}).get("shipment_id")
    if not shipment_id:
        return None
    try:
        return cases.shipment_subgraph(shipment_id)
    except Exception:
        log.exception("could not build the escalation handover subgraph")
        return None


def _escalate(state: PipelineState) -> dict:
    log.info("escalating after %d rejected attempt(s)", state.get("loop_count") or 0)
    filed = writeback.write_escalation(state)
    return {
        "disposition": "escalate",
        "handover": _handover(state),
        "escalation": filed,
    }


# --- edges ------------------------------------------------------------------------------

def _after_retrieve(state: PipelineState) -> str:
    """Conditional edge out of retrieve: is there anything at all to reason from?

    Retrieval having found no precedent above the similarity floor AND no live shipment means
    the graph knows nothing about this complaint - it may not be a complaint at all. Running
    the classifier anyway produces a confident category, an action, and a reviewer that
    accepts it, all built on nothing: the failure mode where "grounded in historical
    precedent" is asserted over five unrelated neighbours the index returned because it
    always returns k of them.

    Escalating here is both more honest and much cheaper - it costs zero model calls instead
    of the five or more a full classify/recommend/review pass would spend before arriving at
    an answer nobody should trust.
    """
    context = state.get("context") or {}
    if not (context.get("similar_cases") or context.get("live_failure_id")):
        log.info("no precedent above the floor and no live shipment - escalating without classifying")
        return "escalate"
    return "classify"


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
    g.add_conditional_edges("retrieve", _after_retrieve,
                            {"classify": "classify", "escalate": "escalate"})
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
        "attempted_actions": [],
        "loop_count": 0,
        "disposition": None,
        "resolution_id": None,
        "handover": None,
        "escalation": None,
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
        "recommendation": None, "review": None, "review_notes": [], "attempted_actions": [],
        "loop_count": 0, "disposition": None, "resolution_id": None, "handover": None,
        "escalation": None,
    }
    merged: dict = dict(state)
    loop = 0
    for step in build_pipeline().stream(state, stream_mode="updates"):
        for node, update in step.items():
            merged.update(update or {})
            loop = merged.get("loop_count") or 0
            yield "stage", _summarize(node, update or {}, loop)
    yield "final", {
        "handover": merged.get("handover"),
        "escalation": merged.get("escalation"),
        "disposition": merged.get("disposition"),
        "resolution_id": merged.get("resolution_id"),
        "loops": merged.get("loop_count") or 0,
        "classification": merged.get("classification"),
        "recommendation": merged.get("recommendation"),
        "review": merged.get("review"),
    }
