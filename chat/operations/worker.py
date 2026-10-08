"""Sequential deterministic evidence triage. Explicit AFL fixture is not a model run."""
from dataset_v2.contracts import digest
from operations.reasoning import triage


def review(proposal, visible_ids):
    if proposal.get("action_code") == "MARK_DELIVERED_FROM_GPS":
        return {"verdict": "reject", "feedback": "Vehicle GPS cannot establish parcel delivery. Revise to an evidence-bound investigation action."}
    if proposal.get("resolves") or not proposal.get("requires_approval"):
        return {"verdict": "reject", "feedback": "Recommendations cannot certify outcomes and require operator authority."}
    if not proposal.get("evidence_ids") or not set(proposal["evidence_ids"]) <= set(visible_ids):
        return {"verdict": "reject", "feedback": "Recommendation requires visible shipment-bound supporting evidence."}
    return {"verdict": "accept", "feedback": "Bound evidence supports this investigation proposal; operator approval and an independent verified outcome remain required."}


def analyze(context, config, precedents=(), *, afl_fixture=False):
    result = triage(context, config, precedents)
    visible = {node["id"] for node in context["nodes"]}
    trace = []
    feedback = None
    if afl_fixture and result["recommendations"]:
        initial = {"action_code": "MARK_DELIVERED_FROM_GPS", "action": "Certify parcel delivery from vehicle GPS.",
                   "evidence_ids": [], "requires_approval": False, "resolves": True}
        verdict = review(initial, visible)
        feedback = verdict["feedback"]
        trace.append({"iteration": 0, "proposal": initial, "review": verdict,
                      "mode": "explicit_deterministic_rejection_fixture"})
        # The revision consumes the actual hard feedback, never a simulated model acceptance.
        if "cannot establish parcel delivery" not in feedback:
            raise ValueError("AFL fixture must carry its actual reviewer feedback")
        result = triage(context, config, precedents)
    proposal = None
    if result["recommendations"]:
        recommendation = result["recommendations"][0]
        proposal = {**recommendation, "action_code": recommendation["code"], "resolves": False}
        verdict = review(proposal, visible)
        trace.append({"iteration": len(trace), "proposal": proposal, "review": verdict,
                      "feedback_received": feedback, "mode": "deterministic_evidence_guard"})
        if verdict["verdict"] != "accept":
            result["workflow_state"] = "ESCALATED"
    else:
        verdict = {"verdict": "reject", "feedback": "No grounded investigation action at this snapshot."}
        result["workflow_state"] = "NEEDS_EVIDENCE"
    return {"result": result, "proposal": proposal, "review": verdict, "trace": trace,
            "context_hash": digest(context), "afl": {"iterations": len(trace), "fixture": bool(afl_fixture)},
            "mode": "deterministic_evidence_rules", "outcome": None}
