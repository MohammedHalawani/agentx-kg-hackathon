"""Actual V2 LangGraph: deterministic evidence stages, with recorded execution events.

No provider calls, private prompts or hidden labels. Topology is read from the
compiled graph, and writeback is the existing transactional case router.
"""
from datetime import datetime, timezone
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END
from dataset_v2.contracts import digest
from operations.reasoning import triage


class Investigation(TypedDict, total=False):
    shipment_id: str
    as_of: str
    context: dict
    result: dict
    precedents: list
    proposal: dict | None
    review: dict
    trace: list
    iteration: int
    feedback: str | None
    disposition: Any


def topology():
    graph = build_graph(None, lambda *_: {}, lambda *_: []).get_graph()
    return {"engine": "langgraph", "mode": "deterministic_evidence_rules",
            "nodes": [n for n in graph.nodes if not n.startswith("__")],
            "edges": [{"source": e.source, "target": e.target, "conditional": e.conditional}
                      for e in graph.edges], "retry_limit": 2}


def analysis(state, events, afl_scenario):
    return {"result": state["result"], "proposal": state.get("proposal"), "review": state["review"],
            "trace": state["trace"], "context_hash": digest(state["context"]),
            "afl": {"iterations": len(state["trace"]), "fixture": bool(afl_scenario)},
            "mode": "deterministic_evidence_rules", "outcome": None,
            "pipeline_events": list(events), "topology": topology()}


def build_graph(config, retrieve, precedents, *, commit=None, on_event=None, events=None, afl_scenario=False):
    from operations.worker import review
    events = events if events is not None else []

    def emit(stage, status, state, output=None):
        event = {"sequence": len(events)+1, "stage": stage, "status": status,
                 "iteration": state.get("iteration", 0),
                 "recorded_at": datetime.now(timezone.utc).isoformat(),
                 "evidence_as_of": state["as_of"], "output": output or {}}
        events.append(event)
        if on_event: on_event(event, list(events))

    def node(name, operation):
        def run(state):
            emit(name, "RETRYING" if name == "recommend" and state.get("iteration",0) else "RUNNING", state)
            try:
                update, output = operation(state)
            except Exception:
                emit(name, "FAILED", state, {"error": "stage_failed"})
                raise
            merged = {**state, **update}
            status = "REJECTED" if name == "review" and update["review"]["verdict"] == "reject" else "COMPLETED"
            emit(name, status, merged, output)
            return update
        return run

    def extract(s):
        return {}, {"shipment_id": s["shipment_id"], "evidence_ids": [s["shipment_id"]], "as_of": s["as_of"]}

    def retrieve_stage(s):
        context = retrieve(s["shipment_id"], s["as_of"])
        counts = {}
        for n in context["nodes"]: counts[n["kind"]] = counts.get(n["kind"], 0)+1
        return {"context": context}, {"nodes": len(context["nodes"]), "relationships": len(context["edges"]),
            "categories": counts, "evidence_ids": [n["id"] for n in context["nodes"]],
            "edge_ids": [e["id"] for e in context["edges"]]}

    def classify(s):
        result = triage(s["context"], config)
        return {"result": result}, {"diagnoses": result["diagnoses"],
            "expected_vs_actual": result["assessment"]["expected_vs_actual"],
            "requires_human_review": result["assessment"]["requires_human_review"],
            "evidence_ids": sorted({i for d in result["diagnoses"] for i in d["evidence_ids"]})}

    def retrieve_context(s):
        rows = list(precedents(s["shipment_id"], s["result"]["assessment"]["supported_codes"]))
        result = {**s["result"], "precedents": rows}
        policies = [n["id"] for n in s["context"]["nodes"] if n["kind"] in ("Policy", "ServiceLevel", "JourneyPlan")]
        return {"precedents": rows, "result": result}, {"verified_precedents": len(rows), "precedents": rows,
            "evidence_ids": policies}

    def recommend(s):
        if afl_scenario and s.get("iteration",0) == 0 and s["result"]["recommendations"]:
            proposal = {"action_code": "MARK_DELIVERED_FROM_GPS", "action": "Certify parcel delivery from vehicle GPS.",
                        "evidence_ids": [], "requires_approval": False, "resolves": True}
        elif s["result"]["recommendations"]:
            if afl_scenario and s.get("iteration",0) and "cannot establish parcel delivery" not in (s.get("feedback") or ""):
                raise ValueError("Revision must consume the actual safety rejection")
            r = s["result"]["recommendations"][0]
            proposal = {**r, "action_code": r["code"], "resolves": False}
        else: proposal = None
        return {"proposal": proposal}, {"proposal": proposal, "evidence_ids": (proposal or {}).get("evidence_ids",[]),
            "feedback_received": s.get("feedback"), "verified_precedents": len(s.get("precedents",[]))}

    def review_stage(s):
        verdict = review(s["proposal"], {n["id"] for n in s["context"]["nodes"]}) if s["proposal"] else {
            "verdict": "reject", "feedback": "No grounded investigation action at this snapshot."}
        trace = [*s["trace"], {"iteration": s.get("iteration",0), "proposal": s["proposal"], "review": verdict,
            "feedback_received": s.get("feedback"), "mode": "deterministic_evidence_guard"}]
        return {"review": verdict, "trace": trace, "feedback": verdict["feedback"], "iteration": s.get("iteration",0)+1}, {
            **verdict, "evidence_ids": (s["proposal"] or {}).get("evidence_ids",[]),
            "checks": ["shipment_bound_evidence", "operator_approval", "no_gps_delivery_certification", "independent_verified_outcome"]}

    def route(s):
        state = s
        if s["review"]["verdict"] != "accept":
            state = {**s, "result": {**s["result"], "workflow_state": "ESCALATED" if s["proposal"] else "NEEDS_EVIDENCE"}}
        receipt = commit(analysis(state, events, afl_scenario)) if commit else None
        return {"result": state["result"], "disposition": receipt}, {"workflow_state": (receipt or {}).get("workflow_state",state["result"]["workflow_state"]),
            "physical_execution": False, "outcome": None}

    def after_review(s):
        if s["review"]["verdict"] == "accept": return "writeback"
        return "recommend" if s["proposal"] and s["iteration"] < 2 else "escalate"

    g = StateGraph(Investigation)
    for name, fn in (("extract",extract),("retrieve",retrieve_stage),("classify",classify),
                     ("retrieve_context",retrieve_context),("recommend",recommend),("review",review_stage),
                     ("writeback",route),("escalate",route)):
        g.add_node(name, node(name,fn))
    g.set_entry_point("extract")
    for a,b in zip(("extract","retrieve","classify","retrieve_context","recommend"),
                   ("retrieve","classify","retrieve_context","recommend","review")): g.add_edge(a,b)
    g.add_conditional_edges("review",after_review,{n:n for n in ("writeback","recommend","escalate")})
    g.add_edge("writeback",END); g.add_edge("escalate",END)
    return g.compile()


def investigate(shipment_id, as_of, config, retrieve, precedents, *, commit=None, on_event=None, afl_scenario=False):
    events = []
    graph = build_graph(config,retrieve,precedents,commit=commit,on_event=on_event,events=events,afl_scenario=afl_scenario)
    result = graph.invoke({"shipment_id":shipment_id,"as_of":as_of,"trace":[],"iteration":0,"feedback":None})
    return analysis(result,events,afl_scenario), result.get("disposition")
