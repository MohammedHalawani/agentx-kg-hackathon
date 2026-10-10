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
    "REQUEST_DEVICE_SYNC": ("AUTO", {"DELAYED_SYNC"}, True,
                            "Ask the device to upload its buffered scans; the late-arriving records confirm the missing observations."),
    "PHYSICAL_CUSTODY_CHECK": ("HUMAN_REVIEW", {"UNRECONCILED_CUSTODY", "CUSTODY_GAP", "CONFLICTING_CUSTODY", "MANIFEST_CONFLICT"}, True,
                               "A person physically locates the parcel with its last corroborated holder."),
    "MANIFEST_RECONCILIATION_REVIEW": ("HUMAN_REVIEW", {"MANIFEST_CONFLICT"}, True,
                                       "A person reconciles the dispatch manifest with confirmed custody."),
    "COMPENSATION": ("PROHIBITED", set(), False, "Compensation or refund."),
    "LIABILITY_DETERMINATION": ("PROHIBITED", set(), False, "Liability, fraud or theft determination."),
}
# Arabic summary of every catalogue action, with the same meaning as the English summary above. A
# proposal's Arabic text comes from here, never from a scripted story.
ACTION_SUMMARY_AR = {
    "REQUEST_RESCAN": "طلب إعادة مسح الطرد في المنشأة الحالية.",
    "REQUEST_REWEIGH": "طلب إعادة وزن الطرد بميزان معاير قبل متابعة مناولته.",
    "INITIATE_CUSTODY_RECONCILIATION": "مطابقة حيازة الطرد بدءًا من آخر حائز تؤيده الأدلة.",
    "REQUEST_HUB_CHECK": "مطالبة المنشأة المتوقعة بالبحث عن الطرد وتسجيل مسح له.",
    "PRIORITIZE_NEXT_SESSION": "إعطاء الطرد الأولوية في دورة التسليم المؤهلة التالية.",
    "REQUEST_ADDRESS_CONFIRMATION": "طلب تأكيد العنوان أو البوابة من المستلم قبل محاولة التسليم التالية.",
    "REQUEST_ADDITIONAL_EVIDENCE": "طلب الأدلة التشغيلية المفقودة المرتبطة بالطرد.",
    "REROUTE_TO_CONFIRMED_DESTINATION": "إعادة توجيه الطرد إلى وجهة أخرى مؤكدة.",
    "RETURN_TO_SENDER": "إعادة الطرد إلى المرسل.",
    "DELIVERY_DISPUTE_REVIEW": "مراجعة بشرية لبلاغ المستلم ودليل التسليم المرتبط بالطرد والعنوان والحيازة.",
    "CONFLICTING_CUSTODY_REVIEW": "مطابقة بشرية لتقارير الحيازة المتعارضة.",
    "REQUEST_DEVICE_SYNC": "مطالبة الجهاز برفع عمليات المسح المخزنة لديه؛ فالسجلات التي تصل متأخرة تؤكد الملاحظات المفقودة.",
    "PHYSICAL_CUSTODY_CHECK": "يحدد شخص موقع الطرد فعليًا لدى آخر حائز تؤيده الأدلة.",
    "MANIFEST_RECONCILIATION_REVIEW": "يطابق شخص بيان الإرسال مع الحيازة المؤكدة.",
    "COMPENSATION": "تعويض أو استرداد.",
    "LIABILITY_DETERMINATION": "تحديد المسؤولية أو الاحتيال أو السرقة.",
}
SENSITIVE_CODES = frozenset(("DELIVERY_DISPUTE", "POSSIBLE_MISDELIVERY", "CONFLICTING_CUSTODY"))
# Observed symptoms that set a human-investigation floor whatever the diagnosis: a wrong diagnosis can
# never lower such a case to automatic closure. Evidence-gathering may still run automatically.
HUMAN_FLOOR_SYMPTOMS = frozenset(("SESSION_END_UNRECONCILED", "CUSTODY_REPORTS_CONFLICT", "MANIFEST_CUSTODY_CONFLICT",
                                  "RECIPIENT_REPORTED_NOT_RECEIVED"))
EVIDENCE_GATHERING = frozenset(("REQUEST_RESCAN", "REQUEST_REWEIGH", "REQUEST_DEVICE_SYNC", "REQUEST_ADDITIONAL_EVIDENCE",
                                "REQUEST_HUB_CHECK"))


def symptom_floor(risk, reason, action_type, symptoms):
    """Apply the human floor. Returns (risk, reason, closure) where closure is AUTO or HUMAN."""
    floor = sorted(set(symptoms or []) & HUMAN_FLOOR_SYMPTOMS)
    if not floor:
        return risk, reason, "AUTO"
    if risk == "AUTO" and action_type in EVIDENCE_GATHERING:
        return risk, reason + f" Observed {', '.join(floor)}: the evidence request may run, but only a person can close the case.", "HUMAN"
    if risk in ("AUTO", "APPROVAL_REQUIRED"):
        return "HUMAN_REVIEW", f"Observed {', '.join(floor)} requires human investigation regardless of the diagnosis.", "HUMAN"
    return risk, reason, "HUMAN"


STATE = {"AUTO": "AWAITING_OUTCOME", "APPROVAL_REQUIRED": "AWAITING_APPROVAL", "HUMAN_REVIEW": "HUMAN_REVIEW", "PROHIBITED": "HUMAN_REVIEW"}


def authorize(action_type, diagnosis_codes, *, review_verdict, evidence_conflict, synthetic, live_session, degraded=False,
              contractor_custody=False):
    """Return the risk class and the reason. Never AUTO outside a synthetic live session, and
    never AUTO without an explicit ACCEPT from the independent model reviewer (fail closed)."""
    entry = ACTIONS.get(action_type)
    codes = set(diagnosis_codes)
    if entry is None:
        return "HUMAN_REVIEW", "Unknown action type; a person must decide."
    risk, addresses, _, _ = entry
    if risk == "PROHIBITED":
        # Checked first so that no other branch can relabel it: never executed, whoever approves.
        return "PROHIBITED", "Money, liability or blame decisions are never automated."
    if degraded or review_verdict == "UNAVAILABLE":
        return "HUMAN_REVIEW", "A model role failed or was unavailable; automatic execution is blocked and a person must review."
    if review_verdict in ("HUMAN_REVIEW", "ESCALATE"):
        return "HUMAN_REVIEW", "Reviewer requested human judgment."
    if contractor_custody:
        return "HUMAN_REVIEW", "The parcel's last corroborated holder is a contractor or independent driver; physical reconciliation needs a person."
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


EXECUTION_PATHS = ("AUTO_POLICY", "OPERATOR_APPROVAL")


def execution_permission(action_type, path, decided_risk):
    """Re-checked whenever an action is about to be authorized for execution and again before it is
    dispatched, on every path. Returns (allowed, rule_id, reason).

    AUTO_POLICY: the automatic switch may run only an AUTO-class action the policy decided AUTO.
    OPERATOR_APPROVAL: a person may authorize AUTO or APPROVAL_REQUIRED actions, including on a case the
    policy sent to human review (the person is that review). HUMAN_REVIEW-class actions are carried out by
    a person, never by the system, and PROHIBITED actions never execute, whoever approves."""
    entry = ACTIONS.get(action_type)
    if entry is None:
        return False, "AUTH-01-unknown-action", "Unknown action type; nothing executes."
    base = entry[0]
    if base == "PROHIBITED" or decided_risk == "PROHIBITED":
        return False, "AUTH-13-prohibited", "Money, liability or blame actions never execute, whoever approves."
    if base == "HUMAN_REVIEW":
        return False, "AUTH-12-human-review-action", ("A person carries out this action; the system never executes it. "
                                                       "Record the person's verified finding instead.")
    if path == "AUTO_POLICY":
        if base == "AUTO" and decided_risk == "AUTO":
            return True, "AUTH-10-auto-allowlist", "AUTO-class action decided AUTO by the authority policy."
        return False, "AUTH-18-auto-not-decided", "Automatic execution needs an AUTO-class action decided AUTO by the authority policy."
    if path == "OPERATOR_APPROVAL":
        return True, "AUTH-19-operator-approved", "A person approved an action the policy allows a person to authorize."
    return False, "AUTH-00-unclassified", "Unknown execution path; nothing executes."


def default_action(code):
    """Deterministic fallback mapping from a diagnosis code to its catalog action."""
    for name, (risk, addresses, _, _) in ACTIONS.items():
        if code in addresses and risk in ("AUTO", "HUMAN_REVIEW"):
            return name
    return "REQUEST_ADDITIONAL_EVIDENCE"


RULE_IDS = {
    "Unknown action type": "AUTH-01-unknown-action",
    "A model role failed": "AUTH-02-model-degraded",
    "Reviewer requested human judgment": "AUTH-03-reviewer-human",
    "The parcel's last corroborated holder is a contractor": "AUTH-04-contractor-custody",
    "Sensitive or rights-impacting evidence": "AUTH-05-sensitive",
    "Deterministic evidence rules flagged a conflict": "AUTH-06-evidence-conflict",
    "Proposed action does not address": "AUTH-07-action-mismatch",
    "Automatic execution is limited to synthetic": "AUTH-08-not-live-synthetic",
    "No independent model review accepted": "AUTH-09-no-review-accept",
    "Low-risk, reversible": "AUTH-10-auto-allowlist",
    "Action changes destination": "AUTH-11-approval-required",
    "Sensitive judgment reserved": "AUTH-12-human-review-action",
    "Money, liability or blame": "AUTH-13-prohibited",
    "requires human investigation regardless": "AUTH-14-symptom-floor",
    "Evidence kept changing": "AUTH-15-superseded-snapshot",
    "Model role unavailable": "AUTH-02-model-degraded",
    "Reviewer rejected": "AUTH-16-review-rejected",
    "No grounded proposal": "AUTH-17-no-proposal",
}


def rule_id(reason):
    """Stable identifier of the deterministic authority rule that produced a decision."""
    return next((rule for prefix, rule in RULE_IDS.items() if (reason or "").startswith(prefix) or prefix in (reason or "")),
                "AUTH-00-unclassified")
