"""Deterministic safety guard applied to every proposal before any model review or authority."""
import re

# A proposal may never certify delivery or parcel location from vehicle telemetry.
GPS_CERTIFICATION = re.compile(r"\b(gps|telemetry|vehicle position)\b[^.]{0,80}\b(deliver|parcel|package|custody)", re.I)
CERTIFYING_CODES = re.compile(r"(MARK|CERTIFY|CONFIRM)_(DELIVERED|DELIVERY|CUSTODY)", re.I)


def review(proposal, visible_ids, kinds=None):
    """kinds: evidence id -> kind for the visible snapshot (used to detect GPS-only certification)."""
    kinds = kinds or {}
    cited = proposal.get("evidence_ids") or []
    text = " ".join(str(proposal.get(key) or "") for key in ("action", "action_en", "expected_result"))
    certifies = bool(CERTIFYING_CODES.search(str(proposal.get("action_code") or "")) or proposal.get("resolves"))
    if GPS_CERTIFICATION.search(text) or (certifies and cited and all(kinds.get(i) == "GPSObservation" for i in cited)):
        return {"verdict": "reject", "feedback": "Vehicle GPS cannot establish parcel delivery. Revise to an evidence-bound investigation action."}
    if certifies or not proposal.get("requires_approval"):
        return {"verdict": "reject", "feedback": "Recommendations cannot certify outcomes and require operator authority."}
    if not cited or not set(cited) <= set(visible_ids):
        return {"verdict": "reject", "feedback": "Recommendation requires visible shipment-bound supporting evidence."}
    return {"verdict": "accept", "feedback": "Bound evidence supports this investigation proposal; operator approval and an independent verified outcome remain required."}


def analyze(context, config, precedents=()):
    from operations.graph import investigate
    result, _ = investigate(context['shipment_id'], context['as_of'], config,
                            lambda *_: context, lambda *_: precedents)
    return result
