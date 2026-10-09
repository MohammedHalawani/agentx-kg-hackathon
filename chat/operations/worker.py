"""Sequential deterministic evidence triage. Explicit AFL rehearsal is not a model run."""


def review(proposal, visible_ids):
    if proposal.get("action_code") == "MARK_DELIVERED_FROM_GPS":
        return {"verdict": "reject", "feedback": "Vehicle GPS cannot establish parcel delivery. Revise to an evidence-bound investigation action."}
    if proposal.get("resolves") or not proposal.get("requires_approval"):
        return {"verdict": "reject", "feedback": "Recommendations cannot certify outcomes and require operator authority."}
    if not proposal.get("evidence_ids") or not set(proposal["evidence_ids"]) <= set(visible_ids):
        return {"verdict": "reject", "feedback": "Recommendation requires visible shipment-bound supporting evidence."}
    return {"verdict": "accept", "feedback": "Bound evidence supports this investigation proposal; operator approval and an independent verified outcome remain required."}


def analyze(context, config, precedents=(), *, afl_fixture=False):
    from operations.graph import investigate
    result, _ = investigate(context['shipment_id'], context['as_of'], config,
                            lambda *_: context, lambda *_: precedents, afl_scenario=afl_fixture)
    return result
