"""Deterministic action-authority policy. The model may propose; only this policy authorizes.

Risk classes:
  AUTO               low-risk, reversible, no rights/money impact; synthetic live sessions only
  APPROVAL_REQUIRED  a person must authorize before any execution
  HUMAN_REVIEW       evidence conflict or sensitive judgment; a person investigates
  PROHIBITED         never automated (money, liability, blame)
"""

# action_type -> (risk class, diagnosis codes it may address, reversible, summary)
ACTIONS = {
    "REQUEST_RESCAN": ("AUTO", {"BARCODE_MISMATCH"}, True, "Request a package rescan at the current facility."),
    "REQUEST_REWEIGH": ("AUTO", {"WEIGHT_MISMATCH"}, True, "Request a calibrated reweigh before onward handling."),
    "INITIATE_CUSTODY_RECONCILIATION": ("AUTO", {"UNRECONCILED_CUSTODY", "CUSTODY_GAP", "MISSED_MILESTONE"}, True,
                                        "Reconcile package custody from the last corroborated holder."),
    "REQUEST_HUB_CHECK": ("AUTO", {"HUB_DELAY", "MISSED_MILESTONE", "JOURNEY_DELAY", "ROUTE_DELAY"}, True,
                          "Ask the expected facility to check for the package and record a scan."),
    "PRIORITIZE_NEXT_SESSION": ("AUTO", {"TRAFFIC_DELAY", "SLA_RISK", "JOURNEY_DELAY", "RECIPIENT_UNAVAILABLE", "ROUTE_DELAY"}, True,
                                "Prioritize the package in the next eligible delivery session."),
    "REQUEST_ADDRESS_CONFIRMATION": ("AUTO", {"ADDRESS_CONFLICT", "WRONG_GATE"}, True,
                                     "Request address/gate confirmation from the recipient before the next attempt."),
    "REQUEST_ADDITIONAL_EVIDENCE": ("AUTO", {"INSUFFICIENT_EVIDENCE", "PROOF_INSUFFICIENT"}, True,
                                    "Request the missing package-bound operational evidence."),
    "REROUTE_TO_CONFIRMED_DESTINATION": ("APPROVAL_REQUIRED", {"ADDRESS_CONFLICT", "WRONG_GATE", "MISSED_MILESTONE"}, False,
                                         "Reroute to a different confirmed destination."),
    "RETURN_TO_SENDER": ("APPROVAL_REQUIRED", {"RECIPIENT_UNAVAILABLE", "ADDRESS_CONFLICT"}, False, "Return the package to the sender."),
    "DELIVERY_DISPUTE_REVIEW": ("HUMAN_REVIEW", {"DELIVERY_DISPUTE", "POSSIBLE_MISDELIVERY", "PROOF_INSUFFICIENT"}, True,
                                "Human review of recipient report, bound proof, address and custody."),
    "CONFLICTING_CUSTODY_REVIEW": ("HUMAN_REVIEW", {"CONFLICTING_CUSTODY"}, True, "Human reconciliation of conflicting custody reports."),
    "COMPENSATION": ("PROHIBITED", set(), False, "Compensation or refund."),
    "LIABILITY_DETERMINATION": ("PROHIBITED", set(), False, "Liability, fraud or theft determination."),
}
SENSITIVE_CODES = frozenset(("DELIVERY_DISPUTE", "POSSIBLE_MISDELIVERY", "CONFLICTING_CUSTODY"))
STATE = {"AUTO": "AWAITING_OUTCOME", "APPROVAL_REQUIRED": "AWAITING_APPROVAL", "HUMAN_REVIEW": "HUMAN_REVIEW", "PROHIBITED": "HUMAN_REVIEW"}


def authorize(action_type, diagnosis_codes, *, review_verdict, evidence_conflict, synthetic, live_session, degraded=False):
    """Return the risk class and the reason. Never AUTO outside a synthetic live session, and
    never AUTO without an explicit ACCEPT from the independent model reviewer (fail closed)."""
    entry = ACTIONS.get(action_type)
    codes = set(diagnosis_codes)
    if entry is None:
        return "HUMAN_REVIEW", "Unknown action type; a person must decide."
    risk, addresses, _, _ = entry
    if degraded or review_verdict == "UNAVAILABLE":
        return "HUMAN_REVIEW", "A model role failed or was unavailable; automatic execution is blocked and a person must review."
    if review_verdict in ("HUMAN_REVIEW", "ESCALATE"):
        return "HUMAN_REVIEW", "Reviewer requested human judgment."
    if codes & SENSITIVE_CODES:
        return "HUMAN_REVIEW", "Sensitive or rights-impacting evidence (dispute, misdelivery or conflicting custody)."
    if evidence_conflict:
        return "HUMAN_REVIEW", "Deterministic evidence rules flagged a conflict requiring human judgment."
    if risk == "AUTO" and not (addresses & codes):
        return "APPROVAL_REQUIRED", "Proposed action does not address a supported diagnosis."
    if risk == "AUTO" and not (synthetic and live_session):
        return "APPROVAL_REQUIRED", "Automatic execution is limited to synthetic live sessions."
    if risk == "AUTO" and review_verdict != "ACCEPT":
        return "APPROVAL_REQUIRED", "No independent model review accepted this action; operator authorization required."
    return risk, {"AUTO": "Low-risk, reversible, evidence-bound action within the synthetic automation allowlist.",
                  "APPROVAL_REQUIRED": "Action changes destination or service; operator authorization required.",
                  "HUMAN_REVIEW": "Sensitive judgment reserved for a person.",
                  "PROHIBITED": "Money, liability or blame decisions are never automated."}[risk]


def default_action(code):
    """Deterministic fallback mapping from a diagnosis code to its catalog action."""
    for name, (risk, addresses, _, _) in ACTIONS.items():
        if code in addresses and risk in ("AUTO", "HUMAN_REVIEW"):
            return name
    return "REQUEST_ADDITIONAL_EVIDENCE"
