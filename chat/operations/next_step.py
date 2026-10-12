"""What a case needs next, and why it is not resolved: derived by code from the case's own recorded fields.

Nothing here is a model output and nothing is stored: it restates, in one place, what the workflow state, the authority
decision, the final review, the recommendation's approval check, the executed actions and the verified outcome already
say, so the interface can explain an unresolved case without re-deriving the rules. A case is "resolved" only when its
workflow state says so, which only the outcome verifier (or a person's recorded finding) can set.
"""

# code -> (who acts, English, Arabic). {action} is the recommended or executed action type.
STEPS = {
    "NONE": ("none", "No action needed: the case is resolved and the outcome was verified.",
             "لا يلزم أي إجراء: تمت معالجة الحالة والتحقق من النتيجة."),
    "START_INVESTIGATION": ("operator", "This case has not been investigated with the current evidence. Click Investigate now to start; with Auto on, "
                                        "Suhail starts it by itself.",
                            "لم يُحقَّق في هذه الحالة بالأدلة الحالية. اضغط «حقّق الآن» للبدء؛ ومع تشغيل الوضع التلقائي يبدأ سهيل التحقيق بنفسه."),
    "WAIT_INVESTIGATION": ("system", "Waiting for the investigation of the current evidence to finish.",
                           "بانتظار اكتمال التحقيق في الأدلة الحالية."),
    "WAIT_VERIFICATION": ("system", "{action} was sent. Waiting for evidence recorded after it; the verifier then decides whether the problem is cleared.",
                          "تم إرسال الإجراء {action}. بانتظار أدلة تُسجَّل بعده، ثم يقرر المدقق ما إذا زالت المشكلة."),
    "APPROVE_OR_REJECT": ("operator", "Approve or reject {action}. It changes the shipment's handling, so it runs only with a person's approval.",
                          "وافق على الإجراء {action} أو ارفضه. يغيّر هذا الإجراء مناولة الشحنة، لذا لا يُنفَّذ إلا بموافقة شخص."),
    "APPROVE_EVIDENCE_REQUEST_OR_INVESTIGATE": (
        "operator", "A person must investigate this case. You may approve {action} to gather more evidence; it will not close the case.",
        "يجب أن يحقق شخص في هذه الحالة. يمكنك الموافقة على طلب الأدلة الموصى به لجمع أدلة إضافية؛ لن يغلق ذلك الحالة."),
    "INVESTIGATE_AND_RECORD_FINDING": ("operator", "A person must investigate this case and record the finding. Nothing further will run automatically.",
                                       "يجب أن يحقق شخص في هذه الحالة ويسجّل ما توصل إليه. لن يُنفَّذ أي إجراء آخر تلقائيًا."),
    "REVIEW_VERIFIED_RESULT_AND_RECORD_FINDING": (
        "operator", "{action} was already carried out and independently verified, but the investigation was not accepted by the reviewer, so the case is "
                    "not closed. Review the verified result and the reviewer's objection, then record a finding. Approving {action} again would only repeat it.",
        "نُفِّذ الإجراء {action} وتم التحقق منه بشكل مستقل، لكن المراجع لم يقبل نتيجة التحقيق، لذا لم تُغلق الحالة. راجع النتيجة المتحقق منها واعتراض المراجع ثم سجّل ما توصلت إليه. الموافقة على {action} مرة أخرى ستكرره فقط."),
    "REVIEW_UNACCEPTED_INVESTIGATION": (
        "operator", "The independent reviewer did not accept the investigation. Read its objection and the unaccepted findings, then investigate and record a finding.",
        "لم يقبل المراجع المستقل نتيجة التحقيق. اقرأ اعتراضه والنتائج غير المقبولة، ثم حقق وسجّل ما توصلت إليه."),
    "REVIEW_WHAT_STILL_STANDS": (
        "operator", "A person's finding is on record, but the case is not resolved. Review what still stands, then record a correction or a further finding.",
        "سُجِّلت نتيجة شخص، لكن الحالة لم تُعالَج. راجع ما زال قائمًا ثم سجّل تصحيحًا أو نتيجة أخرى."),
    "PROVIDE_EVIDENCE_OR_REANALYSE": ("operator", "There is no grounded recommendation yet. Add or wait for evidence, then re-analyse the case.",
                                      "لا توجد توصية مدعومة بالأدلة بعد. أضف أدلة أو انتظر وصولها، ثم أعد تحليل الحالة."),
}
WAITING_ON_SYSTEM = {"OPEN": "START_INVESTIGATION", "REOPENED": "START_INVESTIGATION", "INVESTIGATING": "WAIT_INVESTIGATION",
                     "RECOMMENDATION_READY": "WAIT_INVESTIGATION", "ACTION_INITIATED": "WAIT_VERIFICATION", "AWAITING_OUTCOME": "WAIT_VERIFICATION"}


def step_code(detail):
    state = detail.get("workflow_state")
    recommendation = detail.get("recommendation") or {}
    if state == "RESOLVED":
        return "NONE"
    if state in WAITING_ON_SYSTEM:
        return WAITING_ON_SYSTEM[state]
    if state == "AWAITING_APPROVAL":
        return "APPROVE_OR_REJECT" if recommendation.get("approvable") else "INVESTIGATE_AND_RECORD_FINDING"
    if state == "ESCALATED":
        # A case is also here after a person's finding that left something standing, and after an investigation the
        # review accepted but the policy reserved for a person: neither is an unaccepted investigation.
        if (detail.get("outcome") or {}).get("verification_status") == "HUMAN_FINDING":
            return "REVIEW_WHAT_STILL_STANDS"
        review = detail.get("review") or {}
        if review.get("verdict") == "accept" and review.get("model_verdict") == "ACCEPT":
            return "INVESTIGATE_AND_RECORD_FINDING"
        return "REVIEW_UNACCEPTED_INVESTIGATION"
    if state == "NEEDS_EVIDENCE":
        return "PROVIDE_EVIDENCE_OR_REANALYSE"
    if state == "HUMAN_REVIEW" and recommendation.get("approvable"):
        # The recommended request was already executed and verified as successful in this case (a reassessment the
        # reviewer did not accept): the person's job is the verified result, not the same request again.
        done = any(a.get("action_type") == recommendation.get("action_type") and a.get("success") is True and a.get("verification_status") == "VERIFIED"
                   for a in attempted_actions(detail))
        return "REVIEW_VERIFIED_RESULT_AND_RECORD_FINDING" if done else "APPROVE_EVIDENCE_REQUEST_OR_INVESTIGATE"
    return "INVESTIGATE_AND_RECORD_FINDING"      # HUMAN_REVIEW and any state not listed: a person, never an automatic step.


def attempted_actions(detail):
    """Every executed or authorized action with the verified outcome recorded for it (None while none is recorded)."""
    outcome = detail.get("outcome") or {}
    rows = []
    for execution in detail.get("executions") or []:
        mine = outcome if outcome and outcome.get("execution_id") == execution.get("entity_id") else {}
        rows.append({"action_type": execution.get("action_type"), "authority": execution.get("authority"), "status": execution.get("status"),
                     "verification_status": mine.get("verification_status"), "success": mine.get("success"),
                     "outcome_type": mine.get("outcome_type"), "exception_cleared": mine.get("exception_cleared"), "reason": mine.get("reason")})
    return rows


def next_step(detail):
    """{code, actor, text_en, text_ar, resolved, blocked_by, missing_evidence, attempted}."""
    code = step_code(detail)
    actor, english, arabic = STEPS[code]
    recommendation = detail.get("recommendation") or {}
    executions = detail.get("executions") or []
    action = (executions[0].get("action_type") if code == "WAIT_VERIFICATION" and executions else recommendation.get("action_type"))
    # In the sentence the action is named in words; the code stays in the recommendation and execution records.
    from operations.brief import ACTION_LABELS
    action = "the " + ACTION_LABELS[action].lower() if action in ACTION_LABELS else "the action"
    authority = (((detail.get("run") or {}).get("result") or {}).get("authority")) or {}
    review = detail.get("review") or {}
    diagnosis = detail.get("diagnosis") or {}
    unaccepted = diagnosis.get("unaccepted_investigation") or {}
    resolved = code == "NONE"
    sentence = english.format(action=action)
    arabic_action = "الإجراء"      # In Arabic the action is referred to generically; its Arabic name is in the recommendation.
    return {"code": code, "actor": actor, "text_en": sentence[0].upper() + sentence[1:], "text_ar": arabic.format(action=arabic_action), "resolved": resolved,
            # Why the system did not resolve it by itself: the authority rule and the reviewer's verdict, as recorded.
            "blocked_by": None if resolved else {"rule_id": authority.get("rule_id"), "reason": authority.get("reason"),
                                                 "risk_class": authority.get("risk_class"), "review_verdict": review.get("model_verdict") or review.get("verdict"),
                                                 "review_feedback": review.get("feedback"),
                                                 "approval_rule": recommendation.get("approval_rule"), "approval_reason": recommendation.get("approval_reason")},
            "missing_evidence": list(diagnosis.get("missing_evidence") or unaccepted.get("missing_evidence") or []),
            "attempted": attempted_actions(detail)}
