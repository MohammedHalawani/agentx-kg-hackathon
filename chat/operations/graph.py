"""The V2 investigation LangGraph, with every stage recorded as a real backend event.

With an investigator (GPT-OSS, operations.investigator) the `classify` stage is an iterative tool
loop over the shipment's time-correct Neo4j evidence: each tool call is emitted as a RUNNING event
with the evidence ids it returned. A rejection by the independent reviewer sends the case back to
`classify` with the reviewer's feedback (bounded): the same conversation, tool belt and retrieved
records continue, under one model-call budget for the whole case investigation. Deterministic code
builds the proposal from the agent's recommended catalog action, runs the safety guard, the fact
checks and the citation-validity check, and the deterministic authority policy alone decides who
may act. Every round is logged with the run (tool calls and arguments, returned record and
computed-result ids, the conclusion, the reviewer's verdict, feedback and unsupported claims, the
snapshot time, model calls used, validation errors); no chain-of-thought is requested or stored.

Without an investigator the graph runs the deterministic evidence rules only; such runs never
receive automatic authority (no independent model review).
"""
from datetime import datetime, timezone
import inspect
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END
from dataset_v2.contracts import digest, instant
from operations.reasoning import triage, operational_status

MAX_REVIEW_ROUNDS = 2
# Reviewer verdicts that send the investigation back for another round while rounds and model calls remain.
REVISION_VERDICTS = ("REVISE", "INSUFFICIENT_EVIDENCE")


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
    log: dict


def topology():
    graph = build_graph(None, lambda *_: {}, lambda *_: []).get_graph()
    return {"engine": "langgraph", "mode": "agent_tool_loop",
            "nodes": [n for n in graph.nodes if not n.startswith("__")],
            "edges": [{"source": e.source, "target": e.target, "conditional": e.conditional}
                      for e in graph.edges], "retry_limit": MAX_REVIEW_ROUNDS}


def analysis(state, events):
    investigation = state.get("investigation")
    run_log = state.get("log")
    if isinstance(investigation, dict) and isinstance(run_log, dict):
        # The conclusion predates its final review. The completed run log holds
        # the shared session's final counters, including that review and retries.
        counters = ("model_call_cap", "model_calls_used", "model_calls_by_role", "cap_reached", "calls_refused_by_cap")
        if all(key in run_log for key in counters):
            investigation = {**investigation, "model_calls": {key: run_log[key] for key in counters}}
    return {"result": state["result"], "proposal": state.get("proposal"), "review": state["review"],
            "trace": state["trace"], "context_hash": digest(state["context"]),
            "afl": {"iterations": len(state["trace"])}, "degraded": state.get("degraded") or [],
            "mode": state.get("mode", "deterministic_evidence_rules"), "outcome": None,
            "investigation": investigation, "checks": state.get("checks"), "authority": state.get("authority"),
            # Every investigation round, for audit and later scoring (None for rules-only runs).
            "investigation_log": state.get("log"),
            "pipeline_events": list(events), "topology": topology()}


def agent_result(investigation, context):
    """Case result fields derived from the agent's own conclusion (never from rule codes)."""
    known = {n["id"] for n in context["nodes"]}
    diagnoses = []
    for h in investigation.get("hypotheses") or []:
        if h["status"] == "refuted":
            continue
        diagnoses.append({"code": h["cause"], "status": h["status"], "summary": h.get("assessment") or "", "summary_en": h.get("assessment") or "",
                          # The assessment is the model's own text; a rule-definition sentence is not its translation.
                          "summary_ar": None,
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


def cited_device(tools, evidence_ids):
    """The device a recommendation's own evidence names, read by code from the cited records: a cited device, heartbeat
    or device-telemetry computation first, then the device that made a cited scan. None when the evidence names none."""
    direct, by_scan = [], []
    for ref in evidence_ids or []:
        node = tools.nodes.get(ref)
        if node is not None:
            if node.kind == "Device":
                direct.append(ref)
            elif node.kind == "DeviceHeartbeat":
                direct.append(node.properties.get("device_id"))
            elif node.kind == "ScanEvent":
                by_scan.append(node.properties.get("device_ref"))
            continue
        record = tools.external.get(ref) or {}
        if record.get("kind") == "Device":
            direct.append(record.get("device_id") or ref)
        elif record.get("kind") == "DeviceHeartbeat" or record.get("computation") == "DEVICE_TELEMETRY":
            direct.append(record.get("device_id"))
    return next((d for d in direct + by_scan if isinstance(d, str) and d), None)


def action_target(tools, evidence_ids=None, action_type=None):
    """What an executed action must later be checked against, computed by code from this snapshot:
    the expected observations that are missing now and the silent device that should have made them. When the
    snapshot names no such device, the target is the device the recommendation cites as evidence (cited_device).
    A rescan is also expected at the facility where this shipment's own package was read with a differing label."""
    rows = [r for r in tools._journey()["milestones"] if r["state"] == "missing_after_deadline"]
    silent = [d for d, report in tools.device_reports.items() if report.get("reporting_state") == "SILENT"]
    expected = []
    for r in rows:
        briefs = r.get("expected_device_telemetry")
        expected += [b["device_id"] for b in briefs if b.get("device_id")] if isinstance(briefs, list) else []
        if r.get("facility_handheld"):
            expected.append(r["facility_handheld"])
    expected = list(dict.fromkeys(expected))
    # The device that should have made the missing observation, when it is silent; else any silent device.
    device = next((d for d in expected if d in silent), None) or (silent[0] if silent else (expected[0] if expected else None))
    device = device or cited_device(tools, evidence_ids)
    from dataset_v2.derive import custody_corroborated
    from operations.outcome_engine import FACILITIES
    facilities={r["location_id"] for r in rows if r.get("location_id") in tools.nodes and tools.nodes[r["location_id"]].kind in FACILITIES}
    for package in (n for n in tools.nodes.values() if n.kind=="Package"):
        events=sorted((n for n in tools.nodes.values() if n.kind=="CustodyEvent" and n.properties.get("package_id")==package.id),
                      key=lambda n:n.properties.get("occurred_at") or "",reverse=True)
        latest=next((n for n in events if custody_corroborated(tools.world,n,instant(tools.as_of))),None)
        if latest and latest.properties.get("to_id") in tools.nodes and tools.nodes[latest.properties["to_id"]].kind in FACILITIES:
            facilities.add(latest.properties["to_id"])
    mismatches=[n.id for n in tools.nodes.values() if n.kind=="ScanEvent" and n.properties.get("package_id") in tools.nodes and
                n.properties.get("observed_barcode") is not None and
                n.properties["observed_barcode"]!=tools.nodes[n.properties["package_id"]].properties.get("manifest_barcode")]
    if action_type=="REQUEST_RESCAN":
        for k in mismatches:
            scan,package=tools.nodes[k].properties,tools.nodes[tools.nodes[k].properties["package_id"]]
            place=tools.nodes.get(scan.get("facility_id"))
            if (scan.get("shipment_id")==tools.sid and package.kind=="Package" and package.properties.get("shipment_id")==tools.sid
                    and place is not None and place.kind in FACILITIES):
                facilities.add(scan["facility_id"])
    devices=sorted({tools.nodes[k].properties["device_ref"] for k in mismatches or evidence_ids or []
                    if k in tools.nodes and tools.nodes[k].kind=="ScanEvent" and tools.nodes[k].properties.get("device_ref")})
    return {"device_id": device, "facility_ids":sorted(facilities),"baseline_device_ids":devices,
            "package_ids":sorted(n.id for n in tools.nodes.values() if n.kind=="Package"),
            "expected_evidence": [{"package_id": r["package_id"], "predicate": r["predicate"],
                                                        "location_id": r["location_id"]} for r in rows]}


def _accepted(function, **extra):
    """The keyword arguments an agent callable accepts: newer ones (session, review context) are passed only where the
    callable declares them, so older investigator doubles keep working."""
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return extra
    return {k: v for k, v in extra.items() if k in parameters}


def build_graph(config, retrieve, precedents, *, commit=None, on_event=None, events=None,
                agents=None, live_session=False, symptoms=(), heartbeats=None, port=None, disabled_tools=(), call_cap=None, meter=None):
    """agents: None (deterministic rules only) or an investigator (operations.investigator or a test double).
    port: the read model's fixed cross-shipment queries (fetch), or None. call_cap: the per-case model-call cap.
    meter: an operations.latency.Meter that times this run (measurement only), or None."""
    from operations.worker import review as guard, REVIEW_SUMMARY_AR
    from operations.authority import (authorize, symptom_floor, abstention_floor, reviewer_doubt_allows, reviewer_doubt_floor,
                                      ACTIONS, ACTION_SUMMARY_AR, STATE)
    from operations.checks import fact_checks, cited_records, review_context
    from operations.investigator import Session, abstains
    events = events if events is not None else []
    holder = {}

    def emit(stage, status, state, output=None):
        event = {"sequence": len(events)+1, "stage": stage, "status": status,
                 "iteration": state.get("iteration", 0),
                 "recorded_at": datetime.now(timezone.utc).isoformat(),
                 "evidence_as_of": state["as_of"], "output": output or {}}
        if meter is not None:
            event["elapsed_seconds"] = meter.elapsed()     # since the graph started; measurement only
        events.append(event)
        if on_event:
            if meter is not None:
                meter.timed_write(on_event, event, list(events))
            else:
                on_event(event, list(events))

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
            verdict = update["review"]["verdict"] if name == "review" else None
            # Nothing to review: shown as not taken, or as unavailable when the investigator failed; never as a rejection.
            status = ("REJECTED" if verdict == "reject" else
                      "HUMAN_REVIEW" if verdict == "human_review" else
                      ("DEGRADED" if update["review"].get("reason_code") in ("INVESTIGATOR_UNAVAILABLE", "INVESTIGATOR_CONTEXT_EXHAUSTED") else "SKIPPED")
                      if verdict == "no_proposal" else
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
        # One tool belt for the whole case investigation: a revision round keeps every record, computed result and
        # call of the earlier round. Only the round number changes.
        if "tools" not in holder or holder["tools"].as_of != s["as_of"]:
            holder["tools"] = InvestigationTools(s["context"], config, symptoms=s.get("symptoms") or [], heartbeats=heartbeats,
                                                 precedents=lambda cause: precedents(s["shipment_id"], [cause]), port=port,
                                                 disabled=disabled_tools)
            holder["session"] = Session(call_cap)
            holder["rounds"] = []
            if meter is not None:
                meter.session, meter.tools = holder["session"], holder["tools"]
        holder["tools"].begin_round(s.get("iteration", 0))
        return holder["tools"]

    def classify(s):
        if not agents:
            result = triage(s["context"], config)
            return {"result": result}, {"diagnoses": result["diagnoses"], "expected_vs_actual": result["assessment"]["expected_vs_actual"],
                "requires_human_review": result["assessment"]["requires_human_review"],
                "evidence_ids": sorted({i for d in result["diagnoses"] for i in d["evidence_ids"]}), "agent": "evidence_rules"}
        tools = tools_for(s)
        session = holder["session"]
        def on_step(step):
            emit("classify", "RUNNING", s, {"kind": "tool_call", "agent": "gpt-oss", **step})
        def on_repair(event):
            # SUHAIL_INVALID_OUTPUT_REPAIR: the reply was invalid twice and is asked for once more ("model reply invalid, retrying").
            emit("classify", "RETRYING", s, {"agent": "gpt-oss", **event})
        def on_forced(event):
            # SUHAIL_FORCED_CONCLUSION: the turn budget is exhausted and the investigator gets one final conclude-only turn.
            emit("classify", "RUNNING", s, {"agent": "gpt-oss", **event})
        revising = bool(s.get("iteration"))
        investigation = agents.investigate(tools, on_step=on_step, feedback=s.get("feedback") if revising else None,
                                           **_accepted(agents.investigate, session=session, on_repair=on_repair, on_forced=on_forced,
                                                       review=(session.reviews[-1] if revising and session.reviews else None)))
        holder["investigation"] = investigation
        update = {"investigation": investigation, "mode": "gpt_oss_agents", "result": agent_result(investigation, s["context"])}
        if investigation.get("degraded"):
            update["degraded"] = [*s.get("degraded", []), {"role": "investigator", "error": investigation["validation_error"],
                                                            "kind": investigation["mode"]}]
        cited = sorted({i for h in investigation.get("hypotheses") or [] for i in h.get("supporting_evidence_ids", []) + h.get("contradicting_evidence_ids", [])})
        return update, {"diagnoses": update["result"]["diagnoses"], "evidence_ids": cited or investigation.get("retrieved_evidence_ids", []),
                        "agent": investigation["mode"], "tool_calls": len(investigation.get("steps") or []),
                        "model_calls": session.budget.snapshot(),
                        "investigation": {"primary_hypothesis": investigation.get("primary_cause"), "confidence": investigation.get("confidence"),
                                          "summary": investigation.get("summary"), "hypotheses": investigation.get("hypotheses"),
                                          "missing_evidence": investigation.get("missing_evidence"),
                                          "next_evidence_step": investigation.get("next_evidence_step"),
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
                known = inv.get("primary_cause") is not None and not abstains(inv.get("primary_cause"))
                primary = next((h for h in inv["hypotheses"] if h["cause"] == inv["primary_cause"]), {}) if known else {}
                basis = primary.get("supporting_evidence_ids") or inv.get("retrieved_evidence_ids", [])[:10]
                code = inv["primary_cause"] if known else "INSUFFICIENT_EVIDENCE"
                text = ACTIONS[action][3]
                proposal = {"code": code, "action_code": code, "action_type": action, "action": text, "action_en": text,
                            "action_ar": ACTION_SUMMARY_AR[action],
                            "evidence_ids": basis, "requires_approval": True, "resolves": False, "target": action_target(tools_for(s), basis, action),
                            "investigated_by": "agent",
                            "planner": {"mode": inv["mode"], "action_type": action, "evidence_basis": basis}}
        elif s["result"]["recommendations"]:
            from operations.authority import default_action
            r = s["result"]["recommendations"][0]
            # Rules-only: shown to a person for information. No agent investigated and no model reviewed it, so the
            # store never lets an approval make it executable (AUTH-22).
            proposal = {**r, "action_code": r["code"], "action_type": default_action(r["code"]), "resolves": False,
                        "investigated_by": "rules"}
        return {"proposal": proposal}, {"proposal": proposal, "evidence_ids": (proposal or {}).get("evidence_ids", []),
            "feedback_received": s.get("feedback"), "verified_precedents": len(s.get("precedents", [])),
            "agent": "authority_catalog" if agents else "evidence_rules"}

    def round_log(s, inv, tools, checks, verdict, model_review):
        """One investigation round as later scoring reads it. Declared outputs only; no reasoning text beyond them."""
        session = holder.get("session")
        number = s.get("iteration", 0)
        calls = [{k: c.get(k) for k in ("tool", "args", "evidence_ids", "computed_ids", "omitted_rows", "failure",
                                        "seconds", "queries", "query_seconds", "cached_queries")}
                 for c in (tools.round_calls(number) if tools else [])]
        conclusion = None
        if inv and not inv.get("degraded"):
            conclusion = {k: inv.get(k) for k in ("primary_cause", "confidence", "hypotheses", "missing_evidence", "next_evidence_step",
                                                  "recommended_action", "requires_physical_check", "summary")}
        return {"round": number, "snapshot_as_of": s["as_of"], "tool_calls": calls, "conclusion": conclusion,
                "investigator": {"mode": (inv or {}).get("mode"), "degraded": bool((inv or {}).get("degraded")),
                                 "validation_error": (inv or {}).get("validation_error"),
                                 "validation_errors": (inv or {}).get("validation_errors") or [],
                                 **({"forced_final_turn": True} if (inv or {}).get("forced_final_turn") else {}),
                                 # V3.4.1: present only when the round came near its input limit.
                                 **({"context_conclude_only": True} if (inv or {}).get("context_conclude_only") else {}),
                                 **({"partial_investigation": inv["partial_investigation"]} if (inv or {}).get("partial_investigation") else {})},
                "citation_validity": (checks or {}).get("citations"),
                "fact_checks": (checks or {}).get("checks"),
                "review": {"verdict": verdict.get("verdict"), "model_verdict": verdict.get("model_verdict"), "reason_code": verdict.get("reason_code"),
                           "feedback": (model_review or {}).get("feedback") if model_review else verdict.get("feedback"),
                           "unsupported_claims": (model_review or {}).get("unsupported_claims") or [],
                           "unaddressed_contradictions": (model_review or {}).get("unaddressed_contradictions") or [],
                           "alternatives_tested": (model_review or {}).get("alternatives_tested"),
                           "mode": (model_review or {}).get("mode", "deterministic_evidence_guard"),
                           "degraded": bool((model_review or {}).get("degraded")),
                           "validation_error": (model_review or {}).get("validation_error"),
                           **({"context_management": model_review["context_management"]} if (model_review or {}).get("context_management") else {})},
                **(session.budget.snapshot() if session else {})}

    def run_log(tools):
        session = holder.get("session")
        if session is None:
            return None
        rounds = holder.get("rounds") or []
        cited = {i for r in rounds for h in ((r.get("conclusion") or {}).get("hypotheses") or [])
                 for i in [*(h.get("supporting_evidence_ids") or []), *(h.get("contradicting_evidence_ids") or [])]}
        seen = [k for k in tools.computed if k in tools.retrieved] if tools else []
        return {"snapshot_as_of": tools.as_of if tools else None, **session.budget.snapshot(), "rounds": rounds,
                # Present only when a round used the forced final turn (SUHAIL_FORCED_CONCLUSION).
                **({"forced_final_turn": True} if any((r.get("investigator") or {}).get("forced_final_turn") for r in rounds) else {}),
                # What the investigator saw beyond the shipment's own evidence nodes, kept so a citation can be resolved later.
                "computed_results": {k: tools.computed[k] for k in seen} if tools else {},
                "cited_external_records": {k: tools.external[k] for k in sorted(cited) if tools and k in tools.external and k not in tools.computed},
                "evidence_index": {k: tools.index[k] for k in sorted(tools.retrieved) if k in tools.index} if tools else {},
                "disabled_tools": sorted(tools.disabled) if tools else [],
                # V3.4.1: what was done to stay within the input limit (shortened results keep their ids), when anything was.
                **({"context_management": session.context.record()} if session.context.record() else {})}

    def review_stage(s):
        kinds = {n["id"]: n["kind"] for n in s["context"]["nodes"]}
        tools = holder.get("tools")
        visible = set(kinds) | (set(tools.external) if tools else set())
        inv = s.get("investigation")
        if s["proposal"]:
            verdict = guard(s["proposal"], visible, kinds)
        elif agents and inv is not None and inv.get("degraded") and inv.get("mode") == "context_exhausted":
            # V3.4.1: the investigation stopped at its input limit. Nothing oversized was sent; what it gathered is attached.
            verdict = {"verdict": "no_proposal", "reason_code": "INVESTIGATOR_CONTEXT_EXHAUSTED",
                       "feedback": "The investigation stopped at its input limit before a valid conclusion; the evidence it gathered is attached, there is no proposal to review and a person must review the case."}
        elif agents and (inv is None or inv.get("degraded")):
            # The investigator failed: there is nothing to review. Not a rejection, and no guard check fired.
            verdict = {"verdict": "no_proposal", "reason_code": "INVESTIGATOR_UNAVAILABLE",
                       "feedback": "The investigation agent did not reach a valid conclusion; there is no proposal to review and a person must review the case."}
        else:
            verdict = {"verdict": "no_proposal", "reason_code": "NO_PROPOSAL", "feedback": "No grounded investigation action at this snapshot."}
        degraded = list(s.get("degraded", []))
        checks, model_review = None, None
        session = holder.get("session")
        if agents and inv and not inv.get("degraded"):
            tools = tools_for(s)
            checks = fact_checks(inv, tools)
            if s["proposal"] and verdict["verdict"] == "accept":
                context = review_context(inv, tools, checks["citations"], round_number=s.get("iteration", 0),
                                         previous_reviews=session.reviews if session else ())
                model_review = agents.review(inv, cited_records(inv, tools), checks["checks"], s.get("symptoms") or [],
                                             **_accepted(agents.review, context=context, session=session,
                                                         on_repair=lambda event: emit("review", "RETRYING", s, {"agent": "gpt-oss", **event})))
                if session is not None:
                    session.reviews.append({"round": s.get("iteration", 0), "verdict": model_review["verdict"], "model_verdict": model_review["verdict"],
                                            "feedback": model_review.get("feedback"), "unsupported_claims": model_review.get("unsupported_claims") or [],
                                            "unaddressed_contradictions": model_review.get("unaddressed_contradictions") or [],
                                            "invalid_citations": checks["citations"]["invalid_ids"]})
                if model_review["verdict"] == "UNAVAILABLE":
                    # Failure, timeout or invalid output: recorded as an unavailable review, never as a pass.
                    degraded.append({"role": "reviewer", "error": model_review["validation_error"], "kind": model_review.get("mode")})
                    verdict = {"verdict": "review_unavailable", "guard_verdict": verdict["verdict"], "model_verdict": "UNAVAILABLE",
                               "degraded": True, "reason_code": "REVIEWER_UNAVAILABLE",
                               "feedback": "Independent model review could not be completed; automatic execution is blocked and a person must review."}
                elif model_review["verdict"] == "REVISE":
                    verdict = {"verdict": "reject", "model_verdict": "REVISE", "reason_code": "MODEL_REVISE",
                               "feedback": model_review["feedback"] or "Reviewer requested a revision."}
                elif model_review["verdict"] == "INSUFFICIENT_EVIDENCE":
                    # Evidence-insufficient: more evidence gathering while a round remains, then a person. Never a pass.
                    verdict = {"verdict": "reject", "model_verdict": "INSUFFICIENT_EVIDENCE", "reason_code": "MODEL_INSUFFICIENT_EVIDENCE",
                               "feedback": model_review["feedback"] or "The reviewer found the evidence insufficient for this conclusion."}
                elif model_review["verdict"] in ("HUMAN_REVIEW", "ESCALATE"):
                    # The reviewer asked for a person to decide: not a pass either.
                    verdict = {"verdict": "human_review", "guard_verdict": verdict["verdict"], "model_verdict": model_review["verdict"],
                               "reason_code": "MODEL_ESCALATE" if model_review["verdict"] == "ESCALATE" else "MODEL_HUMAN_REVIEW",
                               "feedback": model_review["feedback"] or "The independent reviewer asked for a person to decide."}
                else:
                    verdict = {**verdict, "model_verdict": model_review["verdict"], "reason_code": "MODEL_ACCEPT",
                               "feedback": model_review["feedback"] or verdict["feedback"]}
        # Arabic text chosen from the reason that actually produced this verdict.
        verdict = {**verdict, "summary_ar": REVIEW_SUMMARY_AR[verdict["reason_code"]]}
        trace = [*s["trace"], {"iteration": s.get("iteration", 0), "proposal": s["proposal"], "review": verdict,
            "feedback_received": s.get("feedback"), "mode": (model_review or {}).get("mode", "deterministic_evidence_guard")}]
        log = None
        if agents and session is not None:
            holder["rounds"].append(round_log(s, inv, holder.get("tools"), checks, verdict, model_review))
            log = run_log(holder.get("tools"))
        # The checks as recorded with the run: per-citation rows stay in the investigation log.
        recorded = None if checks is None else {**checks, "citations": {k: v for k, v in checks["citations"].items() if k != "citations"}}
        return {"review": verdict, "trace": trace, "feedback": verdict["feedback"], "iteration": s.get("iteration", 0)+1,
                "degraded": degraded, "checks": recorded, "log": log}, {
            **verdict, "degraded": degraded, "evidence_ids": (s["proposal"] or {}).get("evidence_ids", []),
            "checks": ["shipment_bound_evidence", "operator_approval", "no_gps_delivery_certification", "independent_verified_outcome"],
            "fact_checks": (checks or {}).get("checks"), "citation_validity": (recorded or {}).get("citations"),
            "agent": (model_review or {}).get("mode", "deterministic_guard"),
            "model_review": model_review, "model_calls": session.budget.snapshot() if (agents and session) else None}

    def policy_decision(s):
        # The deterministic authority policy, never the model, decides who may act. Returns (risk, reason, closure).
        checks = s.get("checks") or {}
        codes = s["result"]["assessment"]["supported_codes"] or [s["proposal"]["action_code"]]
        inv = s.get("investigation")
        # The investigator asking for a physical check is its own reason (AUTH-23), not a rule-detected conflict.
        physical = bool(inv and inv.get("requires_physical_check"))
        conflict = ((not inv and s["result"]["assessment"]["requires_human_review"]) or checks.get("unsupported") or checks.get("sensitive"))
        risk, reason = authorize(s["proposal"]["action_type"], codes, review_verdict=s["review"].get("model_verdict"),
                                 evidence_conflict=bool(conflict), synthetic=True, live_session=live_session,
                                 degraded=bool(s.get("degraded")), contractor_custody=bool(checks.get("contractor_custody")),
                                 physical_check=physical)
        risk, reason, closure = symptom_floor(risk, reason, s["proposal"]["action_type"], s.get("symptoms"))
        # An insufficient-evidence conclusion never carries automatic closing authority.
        risk, reason, closure = abstention_floor(risk, reason, closure, s["proposal"]["action_type"], codes)
        # AUTH-27: an action that ran under a reviewer's doubt never closes the case by itself.
        return reviewer_doubt_floor(risk, reason, closure, s["proposal"]["action_type"], s["review"].get("model_verdict"))

    def doubted_evidence_request(s):
        # AUTH-27: the model reviewer's doubt (REVISE or INSUFFICIENT_EVIDENCE after the bounded rounds) on a proposal the
        # deterministic guard passed, for an evidence-gathering action that every other authority rule allows to run
        # automatically. Anything else stays the rejection it was: a guard rejection carries no model verdict, and a
        # doubted request another rule holds back is escalated, not made approvable.
        review, proposal = s["review"], s.get("proposal") or {}
        return (review["verdict"] == "reject" and reviewer_doubt_allows(proposal.get("action_type"), review.get("model_verdict"))
                and policy_decision(s)[0] == "AUTO")

    def route(s):
        state = s
        checks = s.get("checks") or {}
        if s.get("degraded"):
            roles = ", ".join(sorted({d["role"] for d in s["degraded"]}))
            # V3.4.1: a role that stopped at its input limit is not an unavailable model (AUTH-28, not AUTH-02).
            context = all(d.get("kind") == "context_exhausted" for d in s["degraded"])
            reason = (f"Input limit reached ({roles}): no oversized request was sent; the evidence gathered so far is attached and "
                      "automatic execution is blocked." if context else f"Model role unavailable ({roles}); automatic execution blocked.")
            authority = {"risk_class": "HUMAN_REVIEW", "reason": reason,
                         "action_type": (s.get("proposal") or {}).get("action_type"), "policy": "deterministic_action_authority"}
            state = {**s, "authority": authority, "result": {**s["result"], "workflow_state": "HUMAN_REVIEW"}}
        elif s["review"]["verdict"] not in ("accept", "human_review") and not doubted_evidence_request(s):
            # Denials are policy decisions too: recorded with their rule and inputs.
            insufficient = s["review"].get("model_verdict") == "INSUFFICIENT_EVIDENCE"
            reason = ("Reviewer found the evidence insufficient; a person or further evidence gathering must follow." if s["proposal"] and insufficient
                      else "Reviewer rejected the proposal after the bounded revision rounds." if s["proposal"]
                      else "No grounded proposal at this snapshot; evidence is needed first.")
            authority = {"risk_class": "HUMAN_REVIEW", "reason": reason, "action_type": (s.get("proposal") or {}).get("action_type"),
                         "policy": "deterministic_action_authority"}
            state = {**s, "authority": authority, "result": {**s["result"], "workflow_state": "ESCALATED" if s["proposal"] else "NEEDS_EVIDENCE"}}
        elif s["proposal"] and s["proposal"].get("action_type"):
            risk, reason, closure = policy_decision(s)
            authority = {"risk_class": risk, "reason": reason, "action_type": s["proposal"]["action_type"], "closure": closure,
                         "policy": "deterministic_action_authority"}
            state = {**s, "authority": authority, "result": {**s["result"], "workflow_state": STATE[risk]}}
        if state.get("authority"):
            from operations.authority import rule_id
            state["authority"] = {**state["authority"], "rule_id": rule_id(state["authority"]["reason"]), "inputs": {
                "action_type": (s.get("proposal") or {}).get("action_type"), "diagnosis_codes": s["result"]["assessment"]["supported_codes"],
                "review_verdict": s["review"].get("model_verdict") or s["review"].get("verdict"), "symptoms": list(s.get("symptoms") or []),
                "degraded": [d["role"] for d in s.get("degraded") or []],
                "fact_checks": {k: checks.get(k) for k in ("unsupported", "sensitive", "contractor_custody")},
                "citations_valid": (checks.get("citations") or {}).get("all_valid"),
                "requires_physical_check": bool((s.get("investigation") or {}).get("requires_physical_check")),
                "rule_conflict": bool(not s.get("investigation") and s["result"]["assessment"]["requires_human_review"])}}
        receipt = commit(analysis(state, events)) if commit else None
        return {"result": state["result"], "disposition": receipt, "authority": state.get("authority")}, {
            "authority": state.get("authority"), "agent": "authority_policy",
            "workflow_state": (receipt or {}).get("workflow_state", state["result"]["workflow_state"]),
            "physical_execution": False, "outcome": None}

    def after_review(s):
        # A pass, an unavailable review and a request for human judgment all go to the authority policy,
        # which routes the last two to a person; only a rejection loops back for revision.
        if s["review"]["verdict"] in ("accept", "review_unavailable", "human_review"): return "writeback"
        if s["iteration"] < MAX_REVIEW_ROUNDS and s.get("proposal"):
            if agents and s["review"].get("model_verdict") in REVISION_VERDICTS:
                # A revision needs at least one investigator turn and one review within the case's model-call cap.
                session = holder.get("session")
                return "classify" if session is None or session.budget.remaining >= 2 else "escalate"
            return "recommend"
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
                agents=None, live_session=False, symptoms=(), heartbeats=None, port=None, disabled_tools=(), call_cap=None):
    from operations.latency import Meter
    events = []
    meter = Meter()
    graph = build_graph(config,retrieve,precedents,commit=commit,on_event=on_event,events=events,
                        agents=agents,live_session=live_session,symptoms=symptoms,heartbeats=heartbeats,
                        port=port,disabled_tools=disabled_tools,call_cap=call_cap,meter=meter)
    result = graph.invoke({"shipment_id":shipment_id,"as_of":as_of,"symptoms":list(symptoms),"trace":[],"iteration":0,
                           "feedback":None,"degraded":[]})
    recorded = analysis(result,events)
    recorded["latency"] = meter.summary(events)
    return recorded, result.get("disposition")
