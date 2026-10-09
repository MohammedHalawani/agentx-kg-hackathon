"""The V2 investigation LangGraph, with every stage recorded as a real backend event.

With an investigator (GPT-OSS, operations.investigator) the `classify` stage is an iterative tool
loop over the shipment's time-correct Neo4j evidence: each tool call is emitted as a RUNNING event
with the evidence ids it returned. A rejection by the independent reviewer sends the case back to
`classify` with the reviewer's feedback (bounded). Deterministic code builds the proposal from the
agent's recommended catalog action, runs the safety guard and fact checks, and the deterministic
authority policy alone decides who may act.

Without an investigator the graph runs the deterministic evidence rules only; such runs never
receive automatic authority (no independent model review).
"""
from datetime import datetime, timezone
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END
from dataset_v2.contracts import digest
from operations.reasoning import triage, operational_status, ARABIC

MAX_REVIEW_ROUNDS = 2


class Investigation(TypedDict, total=False):
    shipment_id: str
    as_of: str
    symptoms: list
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
    checks: dict
    authority: dict
    mode: str


def topology():
    graph = build_graph(None, lambda *_: {}, lambda *_: []).get_graph()
    return {"engine": "langgraph", "mode": "agent_tool_loop",
            "nodes": [n for n in graph.nodes if not n.startswith("__")],
            "edges": [{"source": e.source, "target": e.target, "conditional": e.conditional}
                      for e in graph.edges], "retry_limit": MAX_REVIEW_ROUNDS}


def analysis(state, events):
    return {"result": state["result"], "proposal": state.get("proposal"), "review": state["review"],
            "trace": state["trace"], "context_hash": digest(state["context"]),
            "afl": {"iterations": len(state["trace"])}, "degraded": state.get("degraded") or [],
            "mode": state.get("mode", "deterministic_evidence_rules"), "outcome": None,
            "investigation": state.get("investigation"), "checks": state.get("checks"), "authority": state.get("authority"),
            "pipeline_events": list(events), "topology": topology()}


def agent_result(investigation, context):
    """Case result fields derived from the agent's own conclusion (never from rule codes)."""
    known = {n["id"] for n in context["nodes"]}
    diagnoses = []
    for h in investigation.get("hypotheses") or []:
        if h["status"] == "refuted":
            continue
        diagnoses.append({"code": h["cause"], "status": h["status"], "summary": h.get("assessment") or "", "summary_en": h.get("assessment") or "",
                          "summary_ar": ARABIC.get(h["cause"], (None,))[0],
                          "evidence_ids": [i for i in h.get("supporting_evidence_ids", []) if i in known] or h.get("supporting_evidence_ids", []),
                          "certainty": "model_hypothesis", "requires_human_review": False})
    primary = investigation.get("primary_cause")
    diagnoses.sort(key=lambda d: (d["code"] != primary, d["status"] != "supported"))
    codes = [primary] if primary and primary != "UNKNOWN" else []
    codes += [d["code"] for d in diagnoses if d["status"] == "supported" and d["code"] not in codes and d["code"] != "UNKNOWN"]
    return {"mode": "agent_tool_loop", "synthetic": True, "as_of": context["as_of"], "diagnoses": diagnoses,
            "assessment": {"supported_codes": codes, "requires_human_review": bool(investigation.get("requires_physical_check")),
                           "expected_vs_actual": []},
            "operational_labels": codes, "operational_status": operational_status(codes),
            "workflow_state": "AWAITING_APPROVAL" if codes else "NEEDS_EVIDENCE",
            "recommendations": [], "precedents": [], "outcome": None,
            "limitations": ["Synthetic evidence. Model conclusions are hypotheses checked by an independent reviewer and deterministic facts.",
                            "Vehicle GPS does not prove parcel location. Recommendations do not verify outcomes."]}


def action_target(tools):
    """What an executed action must later be checked against, computed by code from this snapshot:
    the expected observations that are missing now and the silent device that should have made them."""
    rows = [r for r in tools._journey()["milestones"] if r["state"] == "missing_after_deadline"]
    silent = [d for d, report in tools.device_reports.items() if report.get("reporting_state") == "SILENT"]
    device = silent[0] if silent else next((r["facility_handheld"] for r in rows if r.get("facility_handheld")), None)
    return {"device_id": device, "expected_evidence": [{"package_id": r["package_id"], "predicate": r["predicate"],
                                                        "location_id": r["location_id"]} for r in rows]}


def build_graph(config, retrieve, precedents, *, commit=None, on_event=None, events=None,
                agents=None, live_session=False, symptoms=(), heartbeats=None):
    """agents: None (deterministic rules only) or an investigator (operations.investigator or a test double)."""
    from operations.worker import review as guard
    from operations.authority import authorize, symptom_floor, ACTIONS, STATE
    from operations.checks import fact_checks, cited_records
    events = events if events is not None else []
    holder = {}

    def emit(stage, status, state, output=None):
        event = {"sequence": len(events)+1, "stage": stage, "status": status,
                 "iteration": state.get("iteration", 0),
                 "recorded_at": datetime.now(timezone.utc).isoformat(),
                 "evidence_as_of": state["as_of"], "output": output or {}}
        events.append(event)
        if on_event: on_event(event, list(events))

    def node(name, operation, retry_from=None):
        def run(state):
            retrying = state.get("iteration", 0) and name == retry_from
            emit(name, "RETRYING" if retrying else "RUNNING", state)
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
        return {}, {"shipment_id": s["shipment_id"], "symptoms": list(s.get("symptoms") or []),
                    "evidence_ids": [s["shipment_id"]], "as_of": s["as_of"]}

    def retrieve_stage(s):
        context = retrieve(s["shipment_id"], s["as_of"])
        counts = {}
        for n in context["nodes"]: counts[n["kind"]] = counts.get(n["kind"], 0)+1
        return {"context": context}, {"nodes": len(context["nodes"]), "relationships": len(context["edges"]),
            "categories": counts, "evidence_ids": [n["id"] for n in context["nodes"]],
            "edge_ids": [e["id"] for e in context["edges"]]}

    def tools_for(s):
        from operations.tools import InvestigationTools
        # A fresh tool belt per investigation round: a revision gets its own bounded budget.
        if "tools" not in holder or holder["tools"].as_of != s["as_of"] or holder.get("round") != s.get("iteration", 0):
            holder["round"] = s.get("iteration", 0)
            holder["tools"] = InvestigationTools(s["context"], config, symptoms=s.get("symptoms") or [], heartbeats=heartbeats,
                                                 precedents=lambda cause: precedents(s["shipment_id"], [cause]))
        return holder["tools"]

    def classify(s):
        if not agents:
            result = triage(s["context"], config)
            return {"result": result}, {"diagnoses": result["diagnoses"], "expected_vs_actual": result["assessment"]["expected_vs_actual"],
                "requires_human_review": result["assessment"]["requires_human_review"],
                "evidence_ids": sorted({i for d in result["diagnoses"] for i in d["evidence_ids"]}), "agent": "evidence_rules"}
        tools = tools_for(s)
        def on_step(step):
            emit("classify", "RUNNING", s, {"kind": "tool_call", "agent": "gpt-oss", **step})
        investigation = agents.investigate(tools, on_step=on_step, feedback=s.get("feedback") if s.get("iteration") else None)
        update = {"investigation": investigation, "mode": "gpt_oss_agents", "result": agent_result(investigation, s["context"])}
        if investigation.get("degraded"):
            update["degraded"] = [*s.get("degraded", []), {"role": "investigator", "error": investigation["validation_error"]}]
        cited = sorted({i for h in investigation.get("hypotheses") or [] for i in h.get("supporting_evidence_ids", []) + h.get("contradicting_evidence_ids", [])})
        return update, {"diagnoses": update["result"]["diagnoses"], "evidence_ids": cited or investigation.get("retrieved_evidence_ids", []),
                        "agent": investigation["mode"], "tool_calls": len(investigation.get("steps") or []),
                        "investigation": {"primary_hypothesis": investigation.get("primary_cause"), "confidence": investigation.get("confidence"),
                                          "summary": investigation.get("summary"), "hypotheses": investigation.get("hypotheses"),
                                          "missing_evidence": investigation.get("missing_evidence"),
                                          "requires_physical_check": investigation.get("requires_physical_check"),
                                          "steps": investigation.get("steps")}}

    def retrieve_context(s):
        codes = s["result"]["assessment"]["supported_codes"]
        rows = list(precedents(s["shipment_id"], codes)) if codes else []
        result = {**s["result"], "precedents": rows}
        policies = [n["id"] for n in s["context"]["nodes"] if n["kind"] in ("Policy", "ServiceLevel", "JourneyPlan")]
        return {"precedents": rows, "result": result}, {"verified_precedents": len(rows), "precedents": rows, "evidence_ids": policies}

    def recommend(s):
        inv = s.get("investigation")
        proposal = None
        if agents:
            if inv and not inv.get("degraded") and inv.get("recommended_action"):
                action = inv["recommended_action"]
                known = inv.get("primary_cause") not in (None, "UNKNOWN")
                primary = next((h for h in inv["hypotheses"] if h["cause"] == inv["primary_cause"]), {}) if known else {}
                basis = primary.get("supporting_evidence_ids") or inv.get("retrieved_evidence_ids", [])[:10]
                code = inv["primary_cause"] if known else "INSUFFICIENT_EVIDENCE"
                text = ACTIONS[action][3]
                proposal = {"code": code, "action_code": code, "action_type": action, "action": text, "action_en": text, "action_ar": None,
                            "evidence_ids": basis, "requires_approval": True, "resolves": False, "target": action_target(tools_for(s)),
                            "planner": {"mode": inv["mode"], "action_type": action, "evidence_basis": basis}}
        elif s["result"]["recommendations"]:
            r = s["result"]["recommendations"][0]
            proposal = {**r, "action_code": r["code"], "resolves": False}
        return {"proposal": proposal}, {"proposal": proposal, "evidence_ids": (proposal or {}).get("evidence_ids", []),
            "feedback_received": s.get("feedback"), "verified_precedents": len(s.get("precedents", [])),
            "agent": "authority_catalog" if agents else "evidence_rules"}

    def review_stage(s):
        kinds = {n["id"]: n["kind"] for n in s["context"]["nodes"]}
        tools = holder.get("tools")
        visible = set(kinds) | (set(tools.external) if tools else set())
        verdict = guard(s["proposal"], visible, kinds) if s["proposal"] else {
            "verdict": "reject", "feedback": "No grounded investigation action at this snapshot."}
        degraded = list(s.get("degraded", []))
        checks, model_review = None, None
        inv = s.get("investigation")
        if agents and inv and not inv.get("degraded"):
            tools = tools_for(s)
            checks = fact_checks(inv, tools)
            if s["proposal"] and verdict["verdict"] == "accept":
                model_review = agents.review(inv, cited_records(inv, tools), checks["checks"], s.get("symptoms") or [])
                if model_review["verdict"] == "UNAVAILABLE":
                    degraded.append({"role": "reviewer", "error": model_review["validation_error"]})
                    verdict = {**verdict, "model_verdict": "UNAVAILABLE", "degraded": True,
                               "feedback": "Independent model review could not be completed; automatic execution is blocked and a person must review."}
                elif model_review["verdict"] == "REVISE":
                    verdict = {"verdict": "reject", "model_verdict": "REVISE", "feedback": model_review["feedback"] or "Reviewer requested a revision."}
                else:
                    verdict = {**verdict, "model_verdict": model_review["verdict"], "feedback": model_review["feedback"] or verdict["feedback"]}
        trace = [*s["trace"], {"iteration": s.get("iteration", 0), "proposal": s["proposal"], "review": verdict,
            "feedback_received": s.get("feedback"), "mode": (model_review or {}).get("mode", "deterministic_evidence_guard")}]
        return {"review": verdict, "trace": trace, "feedback": verdict["feedback"], "iteration": s.get("iteration", 0)+1,
                "degraded": degraded, "checks": checks}, {
            **verdict, "degraded": degraded, "evidence_ids": (s["proposal"] or {}).get("evidence_ids", []),
            "checks": ["shipment_bound_evidence", "operator_approval", "no_gps_delivery_certification", "independent_verified_outcome"],
            "fact_checks": (checks or {}).get("checks"), "agent": (model_review or {}).get("mode", "deterministic_guard"),
            "model_review": model_review}

    def route(s):
        state = s
        checks = s.get("checks") or {}
        if s.get("degraded"):
            roles = ", ".join(sorted({d["role"] for d in s["degraded"]}))
            authority = {"risk_class": "HUMAN_REVIEW", "reason": f"Model role unavailable ({roles}); automatic execution blocked.",
                         "action_type": (s.get("proposal") or {}).get("action_type"), "policy": "deterministic_action_authority"}
            state = {**s, "authority": authority, "result": {**s["result"], "workflow_state": "HUMAN_REVIEW"}}
        elif s["review"]["verdict"] != "accept":
            # Denials are policy decisions too: recorded with their rule and inputs.
            reason = ("Reviewer rejected the proposal after the bounded revision rounds." if s["proposal"]
                      else "No grounded proposal at this snapshot; evidence is needed first.")
            authority = {"risk_class": "HUMAN_REVIEW", "reason": reason, "action_type": (s.get("proposal") or {}).get("action_type"),
                         "policy": "deterministic_action_authority"}
            state = {**s, "authority": authority, "result": {**s["result"], "workflow_state": "ESCALATED" if s["proposal"] else "NEEDS_EVIDENCE"}}
        elif s["proposal"] and s["proposal"].get("action_type"):
            # The deterministic authority policy, never the model, decides who may act.
            codes = s["result"]["assessment"]["supported_codes"] or [s["proposal"]["action_code"]]
            conflict = (s["result"]["assessment"]["requires_human_review"] or checks.get("unsupported") or checks.get("sensitive"))
            risk, reason = authorize(s["proposal"]["action_type"], codes, review_verdict=s["review"].get("model_verdict"),
                                     evidence_conflict=bool(conflict), synthetic=True, live_session=live_session,
                                     degraded=bool(s.get("degraded")), contractor_custody=bool(checks.get("contractor_custody")))
            risk, reason, closure = symptom_floor(risk, reason, s["proposal"]["action_type"], s.get("symptoms"))
            authority = {"risk_class": risk, "reason": reason, "action_type": s["proposal"]["action_type"], "closure": closure,
                         "policy": "deterministic_action_authority"}
            state = {**s, "authority": authority, "result": {**s["result"], "workflow_state": STATE[risk]}}
        if state.get("authority"):
            from operations.authority import rule_id
            state["authority"] = {**state["authority"], "rule_id": rule_id(state["authority"]["reason"]), "inputs": {
                "action_type": (s.get("proposal") or {}).get("action_type"), "diagnosis_codes": s["result"]["assessment"]["supported_codes"],
                "review_verdict": s["review"].get("model_verdict") or s["review"].get("verdict"), "symptoms": list(s.get("symptoms") or []),
                "degraded": [d["role"] for d in s.get("degraded") or []], "fact_checks": {k: checks.get(k) for k in ("unsupported", "sensitive", "contractor_custody")},
                "requires_physical_check": s["result"]["assessment"]["requires_human_review"]}}
        receipt = commit(analysis(state, events)) if commit else None
        return {"result": state["result"], "disposition": receipt, "authority": state.get("authority")}, {
            "authority": state.get("authority"), "agent": "authority_policy",
            "workflow_state": (receipt or {}).get("workflow_state", state["result"]["workflow_state"]),
            "physical_execution": False, "outcome": None}

    def after_review(s):
        if s["review"]["verdict"] == "accept": return "writeback"
        if s["iteration"] < MAX_REVIEW_ROUNDS and s.get("proposal"):
            return "classify" if agents and s["review"].get("model_verdict") == "REVISE" else "recommend"
        return "escalate"

    g = StateGraph(Investigation)
    for name, fn in (("extract",extract),("retrieve",retrieve_stage),("classify",classify),
                     ("retrieve_context",retrieve_context),("recommend",recommend),("review",review_stage),
                     ("writeback",route),("escalate",route)):
        g.add_node(name, node(name, fn, retry_from="classify" if agents else "recommend"))
    g.set_entry_point("extract")
    for a,b in zip(("extract","retrieve","classify","retrieve_context","recommend"),
                   ("retrieve","classify","retrieve_context","recommend","review")): g.add_edge(a,b)
    g.add_conditional_edges("review",after_review,{n:n for n in ("writeback","recommend","classify","escalate")})
    g.add_edge("writeback",END); g.add_edge("escalate",END)
    return g.compile()


def investigate(shipment_id, as_of, config, retrieve, precedents, *, commit=None, on_event=None,
                agents=None, live_session=False, symptoms=(), heartbeats=None):
    events = []
    graph = build_graph(config,retrieve,precedents,commit=commit,on_event=on_event,events=events,
                        agents=agents,live_session=live_session,symptoms=symptoms,heartbeats=heartbeats)
    result = graph.invoke({"shipment_id":shipment_id,"as_of":as_of,"symptoms":list(symptoms),"trace":[],"iteration":0,
                           "feedback":None,"degraded":[]})
    return analysis(result,events), result.get("disposition")
