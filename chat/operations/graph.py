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
    degraded: list
    iteration: int
    feedback: str | None
    disposition: Any
    investigation: dict
    authority: dict
    mode: str


def topology():
    graph = build_graph(None, lambda *_: {}, lambda *_: []).get_graph()
    return {"engine": "langgraph", "mode": "deterministic_evidence_rules",
            "nodes": [n for n in graph.nodes if not n.startswith("__")],
            "edges": [{"source": e.source, "target": e.target, "conditional": e.conditional}
                      for e in graph.edges], "retry_limit": 2}


def analysis(state, events):
    return {"result": state["result"], "proposal": state.get("proposal"), "review": state["review"],
            "trace": state["trace"], "context_hash": digest(state["context"]),
            "afl": {"iterations": len(state["trace"])}, "degraded": state.get("degraded") or [],
            "mode": state.get("mode", "deterministic_evidence_rules"), "outcome": None,
            "investigation": state.get("investigation"), "authority": state.get("authority"),
            "pipeline_events": list(events), "topology": topology()}


def build_graph(config, retrieve, precedents, *, commit=None, on_event=None, events=None,
                agents=None, live_session=False):
    """agents: None (deterministic only) or a module with facts/investigate/plan/review (operations.agents)."""
    from operations.worker import review
    from operations.authority import authorize, ACTIONS, STATE
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
            status = ("REJECTED" if name == "review" and update["review"]["verdict"] == "reject" else
                      "DEGRADED" if len(update.get("degraded") or []) > len(state.get("degraded") or []) else "COMPLETED")
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
        output = {"diagnoses": result["diagnoses"],
            "expected_vs_actual": result["assessment"]["expected_vs_actual"],
            "requires_human_review": result["assessment"]["requires_human_review"],
            "evidence_ids": sorted({i for d in result["diagnoses"] for i in d["evidence_ids"]}), "agent": "evidence_rules"}
        update = {"result": result}
        if agents and result["diagnoses"]:
            investigation = agents.investigate(agents.facts(s["context"], result))
            update.update(investigation=investigation, mode="gpt_oss_agents")
            if investigation.get("degraded"):
                update["degraded"] = [*s.get("degraded", []), {"role": "investigator", "error": investigation["validation_error"]}]
            cited = set(investigation["supporting_evidence_ids"]) | set(investigation["conflicting_evidence_ids"])
            output.update(investigation=investigation, agent=investigation["mode"], evidence_ids=sorted(cited) or output["evidence_ids"])
        return update, output

    def retrieve_context(s):
        rows = list(precedents(s["shipment_id"], s["result"]["assessment"]["supported_codes"]))
        result = {**s["result"], "precedents": rows}
        policies = [n["id"] for n in s["context"]["nodes"] if n["kind"] in ("Policy", "ServiceLevel", "JourneyPlan")]
        return {"precedents": rows, "result": result}, {"verified_precedents": len(rows), "precedents": rows,
            "evidence_ids": policies}

    def recommend(s):
        degraded = list(s.get("degraded", []))
        if agents and s.get("investigation") and not s["investigation"].get("degraded") and s["result"]["recommendations"]:
            planned = agents.plan(agents.facts(s["context"], s["result"], s.get("precedents", [])), s["investigation"], feedback=s.get("feedback"))
            action = planned["action_type"]
            text = planned["expected_result"] or ACTIONS[action][3]
            proposal = {"code": s["investigation"]["primary_hypothesis"], "action_code": s["investigation"]["primary_hypothesis"],
                        "action_type": action, "action": text, "action_en": text, "action_ar": None,
                        "evidence_ids": planned["evidence_basis"], "requires_approval": True, "resolves": False, "planner": planned}
            if planned.get("degraded"):
                degraded.append({"role": "planner", "error": planned["validation_error"]})
        elif s["result"]["recommendations"]:
            r = s["result"]["recommendations"][0]
            proposal = {**r, "action_code": r["code"], "resolves": False}
        else: proposal = None
        return {"proposal": proposal, "degraded": degraded}, {"proposal": proposal, "degraded": degraded, "evidence_ids": (proposal or {}).get("evidence_ids",[]),
            "feedback_received": s.get("feedback"), "verified_precedents": len(s.get("precedents",[])),
            "agent": ((proposal or {}).get("planner") or {}).get("mode", "evidence_rules")}

    def review_stage(s):
        verdict = review(s["proposal"], {n["id"] for n in s["context"]["nodes"]}, {n["id"]: n["kind"] for n in s["context"]["nodes"]}) if s["proposal"] else {
            "verdict": "reject", "feedback": "No grounded investigation action at this snapshot."}
        model_review = None
        degraded = list(s.get("degraded", []))
        if agents and s["proposal"] and s["proposal"].get("planner") and verdict["verdict"] == "accept":
            model_review = agents.review(agents.facts(s["context"], s["result"], s.get("precedents", [])), s["investigation"], s["proposal"]["planner"])
            if model_review["verdict"] == "UNAVAILABLE":
                # Fail closed: no independent review means no automatic authority. Recorded, not hidden.
                degraded.append({"role": "reviewer", "error": model_review["validation_error"]})
                verdict = {**verdict, "model_verdict": "UNAVAILABLE", "degraded": True,
                           "feedback": "Independent model review could not be completed; automatic execution is blocked and a person must review."}
            elif model_review["verdict"] == "REVISE":
                verdict = {"verdict": "reject", "feedback": model_review["feedback"] or "Reviewer requested a revision."}
            else:
                verdict = {**verdict, "model_verdict": model_review["verdict"], "feedback": model_review["feedback"] or verdict["feedback"]}
        trace = [*s["trace"], {"iteration": s.get("iteration",0), "proposal": s["proposal"], "review": verdict,
            "feedback_received": s.get("feedback"), "mode": "deterministic_evidence_guard"}]
        return {"review": verdict, "trace": trace, "feedback": verdict["feedback"], "iteration": s.get("iteration",0)+1,
                "degraded": degraded}, {"degraded": degraded,
            **verdict, "evidence_ids": (s["proposal"] or {}).get("evidence_ids",[]),
            "checks": ["shipment_bound_evidence", "operator_approval", "no_gps_delivery_certification", "independent_verified_outcome"],
            "agent": (model_review or {}).get("mode", "deterministic_guard"), "model_review": model_review}

    def route(s):
        state = s
        if s.get("degraded"):
            # Fail closed: any unavailable model role sends the case to a person with no automatic authority.
            roles = ", ".join(sorted({d["role"] for d in s["degraded"]}))
            authority = {"risk_class": "HUMAN_REVIEW", "reason": f"Model role unavailable ({roles}); automatic execution blocked.",
                         "action_type": (s.get("proposal") or {}).get("action_type"), "policy": "deterministic_action_authority"}
            state = {**s, "authority": authority, "result": {**s["result"], "workflow_state": "HUMAN_REVIEW"}}
        elif s["review"]["verdict"] != "accept":
            state = {**s, "result": {**s["result"], "workflow_state": "ESCALATED" if s["proposal"] else "NEEDS_EVIDENCE"}}
        elif s["proposal"] and s["proposal"].get("action_type"):
            # The deterministic authority policy, never the model, decides who may act.
            codes = [d["code"] for d in s["result"]["diagnoses"]]
            risk, reason = authorize(s["proposal"]["action_type"], codes, review_verdict=s["review"].get("model_verdict"),
                                     evidence_conflict=s["result"]["assessment"]["requires_human_review"],
                                     synthetic=True, live_session=live_session, degraded=bool(s.get("degraded")))
            authority = {"risk_class": risk, "reason": reason, "action_type": s["proposal"]["action_type"], "policy": "deterministic_action_authority"}
            state = {**s, "authority": authority, "result": {**s["result"], "workflow_state": STATE[risk]}}
        receipt = commit(analysis(state, events)) if commit else None
        return {"result": state["result"], "disposition": receipt, "authority": state.get("authority")}, {"authority": state.get("authority"), "agent": "authority_policy","workflow_state": (receipt or {}).get("workflow_state",state["result"]["workflow_state"]),
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


def investigate(shipment_id, as_of, config, retrieve, precedents, *, commit=None, on_event=None,
                agents=None, live_session=False):
    events = []
    graph = build_graph(config,retrieve,precedents,commit=commit,on_event=on_event,events=events,
                        agents=agents,live_session=live_session)
    result = graph.invoke({"shipment_id":shipment_id,"as_of":as_of,"trace":[],"iteration":0,"feedback":None,"degraded":[]})
    return analysis(result,events), result.get("disposition")
