"""Deterministic safety guard applied to every proposal before any model review or authority."""
import re

# A proposal may never certify delivery or parcel location from vehicle telemetry.
GPS_CERTIFICATION = re.compile(r"\b(gps|telemetry|vehicle position)\b[^.]{0,80}\b(deliver|parcel|package|custody)", re.I)
CERTIFYING_CODES = re.compile(r"(MARK|CERTIFY|CONFIRM)_(DELIVERED|DELIVERY|CUSTODY)", re.I)

# Every review verdict carries the code of the check or reviewer decision that produced it. The Arabic
# summary is chosen from that code alone, so it states the actual reason: the GPS sentence appears only
# when the GPS check fired, and a missing proposal or a failed model is never described as a rejection.
REVIEW_SUMMARY_AR = {
    "EVIDENCE_BOUND": "تدعم أدلة مرتبطة بالشحنة هذا المقترح؛ يظل اعتماد المشغّل ونتيجة موثّقة مستقلة مطلوبين قبل الإغلاق.",
    "MODEL_ACCEPT": "قبل المراجع المستقل المقترح استنادًا إلى السجلات المستشهد بها؛ القبول ليس نتيجة موثّقة.",
    "GPS_DELIVERY_CLAIM": "رفض فحص السلامة المقترح لأنه يعتمد موقع المركبة دليلًا على التسليم أو على موقع الطرد؛ موقع المركبة لا يثبت تسليم الطرد.",
    "CERTIFIES_OUTCOME": "رفض فحص السلامة المقترح لأنه يحاول اعتماد نتيجة؛ التوصية لا تعتمد نتيجة وتتطلب صلاحية المشغّل.",
    "EVIDENCE_NOT_BOUND": "رفض فحص السلامة المقترح لأنه لا يستشهد بأدلة مرئية مرتبطة بهذه الشحنة.",
    "MODEL_REVISE": "طلب المراجع المستقل تعديل المقترح؛ ملاحظاته مسجلة بنصها الأصلي.",
    "MODEL_HUMAN_REVIEW": "طلب المراجع المستقل أن يقرر شخص؛ لا تنفيذ تلقائي.",
    "MODEL_INSUFFICIENT_EVIDENCE": "رأى المراجع المستقل أن الأدلة غير كافية لدعم الاستنتاج؛ لا تنفيذ تلقائي، ويلزم جمع أدلة إضافية أو قرار من شخص.",
    "MODEL_ESCALATE": "رأى المراجع المستقل أن المقترح قد يسبب ضررًا وطلب التصعيد إلى شخص؛ لا تنفيذ تلقائي.",
    "REVIEWER_UNAVAILABLE": "تعذّر إكمال المراجعة المستقلة؛ أُوقف التنفيذ التلقائي ويجب أن يراجع شخص الحالة.",
    "INVESTIGATOR_UNAVAILABLE": "لم يصل وكيل التحقيق إلى استنتاج صالح، فلا يوجد مقترح للمراجعة؛ يجب أن يراجع شخص الحالة.",
    "NO_PROPOSAL": "لا يوجد إجراء مستند إلى الأدلة في هذه اللقطة؛ يلزم جمع الأدلة أولًا.",
    "UNCLASSIFIED": "سُجّل قرار المراجعة؛ سببه محفوظ بنصه الأصلي.",
}
_LEGACY_GUARD_FEEDBACK = (("Vehicle GPS cannot establish", "GPS_DELIVERY_CLAIM"), ("Recommendations cannot certify", "CERTIFIES_OUTCOME"),
                          ("Recommendation requires visible", "EVIDENCE_NOT_BOUND"), ("No grounded", "NO_PROPOSAL"))


def review_reason(review):
    """The reason code of a stored or recorded review. Records written before reason codes existed are
    classified from their verdict and the guard's fixed feedback, never from a default story."""
    review = review or {}
    if review.get("reason_code") in REVIEW_SUMMARY_AR:
        return review["reason_code"]
    verdict, model = review.get("verdict"), review.get("model_verdict")
    feedback = str(review.get("feedback") or review.get("summary_en") or "")
    if verdict == "review_unavailable" or model == "UNAVAILABLE":
        return "REVIEWER_UNAVAILABLE"
    if verdict == "human_review":
        return "MODEL_ESCALATE" if model == "ESCALATE" else "MODEL_HUMAN_REVIEW"
    if verdict == "accept":
        return "MODEL_ACCEPT" if model == "ACCEPT" else "EVIDENCE_BOUND"
    if model == "REVISE":
        return "MODEL_REVISE"
    if model == "INSUFFICIENT_EVIDENCE":
        return "MODEL_INSUFFICIENT_EVIDENCE"
    return next((code for prefix, code in _LEGACY_GUARD_FEEDBACK if feedback.startswith(prefix)), "UNCLASSIFIED")


def review_summary_ar(review):
    return REVIEW_SUMMARY_AR[review_reason(review)]


def with_review_reason(review):
    """A served copy of a review whose Arabic summary is derived from its reason (stored records written
    before reason codes existed may carry an older fixed sentence; it is replaced, never shown)."""
    if not isinstance(review, dict) or not review.get("verdict"):
        return review
    reason = review_reason(review)
    return {**review, "reason_code": reason, "summary_ar": REVIEW_SUMMARY_AR[reason]}


def review(proposal, visible_ids, kinds=None):
    """kinds: evidence id -> kind for the visible snapshot (used to detect GPS-only certification)."""
    kinds = kinds or {}
    cited = proposal.get("evidence_ids") or []
    text = " ".join(str(proposal.get(key) or "") for key in ("action", "action_en", "expected_result"))
    certifies = bool(CERTIFYING_CODES.search(str(proposal.get("action_code") or "")) or proposal.get("resolves"))
    if GPS_CERTIFICATION.search(text) or (certifies and cited and all(kinds.get(i) == "GPSObservation" for i in cited)):
        return {"verdict": "reject", "reason_code": "GPS_DELIVERY_CLAIM",
                "feedback": "Vehicle GPS cannot establish parcel delivery. Revise to an evidence-bound investigation action."}
    if certifies or not proposal.get("requires_approval"):
        return {"verdict": "reject", "reason_code": "CERTIFIES_OUTCOME",
                "feedback": "Recommendations cannot certify outcomes and require operator authority."}
    if not cited or not set(cited) <= set(visible_ids):
        return {"verdict": "reject", "reason_code": "EVIDENCE_NOT_BOUND",
                "feedback": "Recommendation requires visible shipment-bound supporting evidence."}
    return {"verdict": "accept", "reason_code": "EVIDENCE_BOUND",
            "feedback": "Bound evidence supports this investigation proposal; operator approval and an independent verified outcome remain required."}


def analyze(context, config, precedents=()):
    from operations.graph import investigate
    result, _ = investigate(context['shipment_id'], context['as_of'], config,
                            lambda *_: context, lambda *_: precedents)
    return result
