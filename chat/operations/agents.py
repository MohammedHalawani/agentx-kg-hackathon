"""Model-backed V2 roles over a deterministic fact packet.

Code computes every canonical fact (counts, timestamps, custody, milestones, signals). GPT-OSS
reasons over those facts and must cite visible evidence IDs. Each output is validated; invalid
output is retried once with feedback, then replaced by a labelled deterministic fallback.
No chain-of-thought is requested, stored or returned.
"""
import json
import os
import re

from operations.authority import ACTIONS, default_action

CAUSES = ("BARCODE_MISMATCH", "WEIGHT_MISMATCH", "CUSTODY_GAP", "CONFLICTING_CUSTODY", "MISSED_MILESTONE", "JOURNEY_DELAY",
          "TRAFFIC_DELAY", "ADDRESS_CONFLICT", "WRONG_GATE", "RECIPIENT_UNAVAILABLE", "DELIVERY_DISPUTE", "PROOF_INSUFFICIENT",
          "UNRECONCILED_CUSTODY", "INSUFFICIENT_EVIDENCE", "SLA_RISK", "HUB_DELAY", "ROUTE_DELAY", "POSSIBLE_MISDELIVERY")
VERDICTS = ("ACCEPT", "REVISE", "HUMAN_REVIEW", "ESCALATE")
BLAME = re.compile(r"\b(driver|courier|employee|customer|recipient)\s+(lost|stole|lied|is lying|was negligent|is responsible|is to blame)\b|\b(theft|stolen|fraud|fraudulent)\b", re.I)
GPS_DELIVERY = re.compile(r"\bgps\b[^.]{0,80}\b(proves?|confirms?|establish(es)?|shows?)\b[^.]{0,40}\b(deliver|parcel|package)", re.I)
OBSERVATION_KINDS = ("ScanEvent", "CustodyEvent", "DeliveryAttempt", "ContactAttempt", "GPSObservation", "TrafficObservation",
                     "DeliveryProof", "RecipientReport", "DepotReconciliation", "AddressVersion", "VehicleAssignment", "HandoffEvidence")
KEEP = ("event_type", "status", "readable", "observed_barcode", "manifest_barcode", "measured_weight_kg", "weight_kg", "facility_id",
        "from_id", "to_id", "vehicle_id", "package_id", "disposition", "report_code", "delay_seconds", "verification_status",
        "service_level", "outcome", "result", "reason_code", "location_id", "occurred_at", "latest_at", "valid_from", "valid_to")


def enabled():
    return os.getenv("SUHAIL_V2_AGENTS", "gpt-oss").lower() not in ("0", "off", "false", "deterministic")


def facts(context, result, precedents=()):
    """Bounded canonical packet. Every value here is computed or copied by code, never by a model."""
    nodes = context["nodes"]
    counts = {}
    for n in nodes:
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1
    obs = sorted((n for n in nodes if n["kind"] in OBSERVATION_KINDS),
                 key=lambda n: str(n["properties"].get("occurred_at") or n["properties"].get("recorded_at") or ""))[-60:]
    shipment = next((n for n in nodes if n["kind"] == "Shipment"), {"properties": {}})
    a = result["assessment"]
    return {
        "shipment_id": context["shipment_id"], "as_of": context["as_of"],
        "shipment": {k: shipment["properties"].get(k) for k in ("status", "service_level", "service_type", "origin_city", "destination_city", "promise_at") if shipment["properties"].get(k) is not None},
        "evidence_counts": counts,
        "deterministic_signals": [{"code": d["code"], "summary": d["summary"], "evidence_ids": d["evidence_ids"][:20],
                                   "requires_human_review": d["requires_human_review"]} for d in result["diagnoses"]],
        "expected_vs_actual": [{k: m.get(k) for k in ("milestone_id", "location_id", "latest_at", "actual_at", "late", "missing_due")}
                               for m in a.get("expected_vs_actual", [])][:20],
        "custody": a.get("custody", [])[:5],
        "observations": [{"id": n["id"], "kind": n["kind"], **{k: n["properties"][k] for k in KEEP if k in n["properties"]}} for n in obs],
        "verified_precedents": [{k: str(p.get(k)) if k == "verified_at" else p.get(k) for k in ("case_id", "exception_codes", "action_type", "action", "success", "verified_at")} for p in precedents][:5],
        "precedent_count": len(list(precedents)),
        "visible_evidence_ids": sorted(n["id"] for n in nodes),
        "rules": ["Vehicle GPS never establishes parcel location or delivery without custody binding.",
                  "Never attribute blame to a person.", "Cite only IDs from visible_evidence_ids.",
                  "Do not state numbers or timestamps that are not present in these facts."],
    }


def _numbers(text):
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def check_text(texts, packet):
    """Unsupported numbers, GPS-as-delivery and personal blame are rejected."""
    known = _numbers(json.dumps(packet, default=str))
    for text in texts:
        if BLAME.search(text or ""):
            return "Output attributes blame or wrongdoing to a person without evidence."
        if GPS_DELIVERY.search(text or ""):
            return "Output treats vehicle GPS as parcel delivery or location evidence."
        invented = _numbers(text) - known
        if invented:
            return "Output states numbers not present in canonical facts: " + ", ".join(sorted(invented)[:5])
    return None


def check_ids(ids, packet, *, required=True):
    visible = set(packet["visible_evidence_ids"])
    if required and not ids:
        return "Output must cite visible evidence IDs."
    unknown = [i for i in ids if i not in visible]
    return ("Output cites evidence IDs that are not visible: " + ", ".join(unknown[:3])) if unknown else None


INVESTIGATOR = {"primary_hypothesis": "", "alternative_hypotheses": [], "supporting_evidence_ids": [], "conflicting_evidence_ids": [],
                "missing_evidence": [], "confidence": "", "sensitivity": "", "summary": ""}
PLANNER = {"action_type": "", "evidence_basis": [], "expected_result": "", "risk_hypothesis": "", "reason": "", "requires_authorization_hint": ""}
REVIEWER = {"verdict": "", "feedback": "", "checks_failed": []}


def validate_investigation(out, packet):
    if out["primary_hypothesis"] not in CAUSES:
        return "primary_hypothesis must be one of the cause codes."
    if packet["deterministic_signals"] and out["primary_hypothesis"] not in {s["code"] for s in packet["deterministic_signals"]} | {"INSUFFICIENT_EVIDENCE"}:
        return "primary_hypothesis must be supported by a deterministic signal in the facts."
    if out["confidence"] not in ("low", "medium", "high") or out["sensitivity"] not in ("low", "high"):
        return "confidence must be low|medium|high and sensitivity low|high."
    return (check_ids(out["supporting_evidence_ids"], packet) or check_ids(out["conflicting_evidence_ids"], packet, required=False)
            or check_text([out["summary"], *out["missing_evidence"]], packet))


def validate_plan(out, packet, investigation):
    if out["action_type"] not in ACTIONS:
        return "action_type must be one of the catalog actions."
    if ACTIONS[out["action_type"]][0] == "PROHIBITED":
        return "Prohibited actions (money, liability, blame) cannot be proposed for automation."
    return check_ids(out["evidence_basis"], packet) or check_text([out["expected_result"], out["reason"]], packet)


def validate_review(out, packet):
    if out["verdict"] not in VERDICTS:
        return "verdict must be ACCEPT|REVISE|HUMAN_REVIEW|ESCALATE."
    return check_text([out["feedback"]], packet)


def _ask(system, packet, extra, default, validate, call):
    """One call plus one corrective retry; returns (output, mode, error)."""
    user = json.dumps({"facts": packet, **extra}, default=str, ensure_ascii=False)
    feedback = None
    for _ in range(2):
        out = call(system, user + (f"\n\nYour previous output was rejected: {feedback} Return corrected JSON only." if feedback else ""), default)
        feedback = validate(out)
        if not feedback:
            return out, "gpt-oss", None
    return None, "deterministic_fallback", feedback


def _model_call(system, user, default):
    from llm.pipeline._llm import ask_json
    return ask_json(system, user, default)


SYSTEM = ("You are Suhail's {role} for a synthetic logistics operation. Use ONLY the provided canonical facts. "
          "Cite only IDs from visible_evidence_ids. Never invent numbers, timestamps, attempts or precedents. "
          "Vehicle GPS is not parcel location. Never blame a person. Return one JSON object with exactly these keys: {keys}. "
          "No explanation outside JSON.")


def investigate(packet, call=None):
    call = call or _model_call
    extra = {"allowed_causes": CAUSES, "confidence": ["low", "medium", "high"], "sensitivity": ["low", "high"]}
    out, mode, error = _ask(SYSTEM.format(role="investigator", keys=list(INVESTIGATOR)), packet, extra, INVESTIGATOR,
                            lambda o: validate_investigation(o, packet), call)
    if out is None:
        top = packet["deterministic_signals"][0] if packet["deterministic_signals"] else None
        out = {**INVESTIGATOR, "primary_hypothesis": top["code"] if top else "INSUFFICIENT_EVIDENCE",
               "supporting_evidence_ids": top["evidence_ids"] if top else [], "confidence": "medium",
               "sensitivity": "high" if top and top["requires_human_review"] else "low",
               "summary": top["summary"] if top else "No supported exception in visible evidence."}
    return {**out, "mode": mode, "validation_error": error}


def plan(packet, investigation, call=None, feedback=None):
    call = call or _model_call
    catalog = {k: {"risk_class": v[0], "addresses": sorted(v[1]), "summary": v[3]} for k, v in ACTIONS.items()}
    extra = {"investigation": {k: investigation[k] for k in INVESTIGATOR}, "action_catalog": catalog,
             "reviewer_feedback": feedback}
    out, mode, error = _ask(SYSTEM.format(role="action planner", keys=list(PLANNER)), packet, extra, PLANNER,
                            lambda o: validate_plan(o, packet, investigation), call)
    if out is None:
        action = default_action(investigation["primary_hypothesis"])
        out = {**PLANNER, "action_type": action, "evidence_basis": investigation["supporting_evidence_ids"],
               "expected_result": ACTIONS[action][3], "reason": "Deterministic catalog action for the supported diagnosis."}
    return {**out, "mode": mode, "validation_error": error}


def review(packet, investigation, proposal, call=None):
    call = call or _model_call
    extra = {"investigation": {k: investigation[k] for k in INVESTIGATOR}, "proposal": {k: proposal[k] for k in PLANNER},
             "check": ["Is the conclusion supported by cited evidence?", "Does the action contradict policy or the catalog?",
                       "Are any numbers invented?", "Is GPS misused?", "Is anyone blamed?", "Are precedents verified?",
                       "Does the action need human authority?"]}
    out, mode, error = _ask(SYSTEM.format(role="reviewer", keys=list(REVIEWER)), packet, extra, REVIEWER,
                            lambda o: validate_review(o, packet), call)
    if out is None:
        out = {**REVIEWER, "verdict": "ACCEPT", "feedback": "Model review unavailable; deterministic safety guard applied."}
    return {**out, "mode": mode, "validation_error": error}
