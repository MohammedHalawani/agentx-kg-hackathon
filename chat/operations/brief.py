"""The case brief: one plain account of a case for an operator, composed by code from the case's stored records.

Nothing here is a model output and nothing is stored: for the same records the brief is the same. It restates, in
operator language, what the monitor saw, what the investigation suggests (a hypothesis unless the independent review
accepted it), what the review said, what the authority policy permits, what was actually sent (always marked
simulated), what the outcome verifier established or is still waiting for, and what happens next. It never says more
than the records do: `resolved` is true only for a case the verifier closed, and a reviewer's challenge is always
stated. Codes and record ids are kept in separate fields from the sentences.

It also gives the waiting kind (what the case is waiting for), an explanation of each executed action, and a short
fact per pipeline stage built from the stage events the run recorded.
"""
from operations.authority import ACTION_SUMMARY_AR, ACTIONS

SYMPTOMS = {
    "BARCODE_READ_DIFFERS": ("A barcode read does not match the shipment's manifest", "قراءة باركود لا تطابق بيان الشحنة"),
    "WEIGHT_READ_DIFFERS": ("A weight reading differs from the declared weight", "قراءة وزن تختلف عن الوزن المصرّح به"),
    "MILESTONE_OVERDUE": ("An expected step of the journey has not been recorded and its deadline has passed", "خطوة متوقعة في الرحلة لم تُسجَّل وقد انقضى موعدها"),
    "MILESTONE_LATE": ("A step of the journey was recorded later than planned", "خطوة في الرحلة سُجِّلت بعد موعدها المخطط"),
    "CUSTODY_TRANSFER_UNCONFIRMED": ("A handover of the parcel was not confirmed by the receiving side", "تسليم للطرد لم يؤكده الطرف المستلم"),
    "DELIVERY_PROOF_INCOMPLETE": ("The delivery proof is incomplete", "دليل التسليم غير مكتمل"),
    "DELIVERY_ATTEMPT_FAILED": ("A delivery attempt failed", "فشلت محاولة تسليم"),
    "SESSION_END_UNRECONCILED": ("The delivery session ended with this parcel unaccounted for", "انتهت جلسة التوزيع دون تسوية وضع هذا الطرد"),
    "RECIPIENT_REPORTED_NOT_RECEIVED": ("The recipient reported not receiving the parcel", "أبلغ المستلم بعدم استلام الطرد"),
    "CUSTODY_REPORTS_CONFLICT": ("Custody records contradict each other", "سجلات الحيازة متعارضة"),
    "MANIFEST_CUSTODY_CONFLICT": ("The dispatch manifest and the custody records disagree", "بيان الإرسال وسجلات الحيازة غير متطابقين"),
    "OVERDUE_AT_FACILITY": ("The parcel has stayed at a facility longer than planned", "بقي الطرد في المنشأة أطول من المخطط"),
}
CAUSES = {
    "BARCODE_MISMATCH": ("a barcode-reading problem", "مشكلة في قراءة الباركود"),
    "WEIGHT_MISMATCH": ("a weight discrepancy", "اختلاف في الوزن"),
    "MISSED_MILESTONE": ("a missed journey step", "خطوة فائتة في الرحلة"),
    "JOURNEY_DELAY": ("a delay in the journey", "تأخر في الرحلة"),
    "CUSTODY_GAP": ("a gap in the custody chain", "فجوة في سلسلة الحيازة"),
    "UNRECONCILED_CUSTODY": ("custody that was not reconciled", "حيازة لم تُسوَّ"),
    "CONFLICTING_CUSTODY": ("conflicting custody records", "سجلات حيازة متعارضة"),
    "MANIFEST_CONFLICT": ("a conflict with the dispatch manifest", "تعارض مع بيان الإرسال"),
    "PROOF_INSUFFICIENT": ("insufficient delivery proof", "دليل تسليم غير كافٍ"),
    "DELIVERY_DISPUTE": ("a delivery dispute", "نزاع على التسليم"),
    "SLA_RISK": ("a risk to the promised delivery time", "خطر على موعد التسليم الموعود"),
    "DELAYED_SYNC": ("records that reached Suhail late from a device", "سجلات وصلت متأخرة من جهاز"),
    "HUB_DELAY": ("a delay at a facility", "تأخر في منشأة"),
    "ROUTE_DELAY": ("a delay on the route", "تأخر على المسار"),
    "TRAFFIC_DELAY": ("a traffic delay", "تأخر بسبب المرور"),
    "RECIPIENT_UNAVAILABLE": ("an unavailable recipient", "عدم توفر المستلم"),
    "ADDRESS_CONFLICT": ("an address problem", "مشكلة في العنوان"),
    "WRONG_GATE": ("delivery to the wrong gate or entrance", "التوجه إلى بوابة أو مدخل خاطئ"),
    "POSSIBLE_MISDELIVERY": ("a possible misdelivery", "احتمال تسليم خاطئ"),
    "INSUFFICIENT_EVIDENCE": ("no cause it can establish from the evidence", "عدم كفاية الأدلة لتحديد السبب"),
}
ACTION_LABELS = {
    "REQUEST_RESCAN": "Rescan request", "REQUEST_REWEIGH": "Reweigh request", "REQUEST_DEVICE_SYNC": "Device sync request",
    "REQUEST_ADDITIONAL_EVIDENCE": "Evidence request", "REQUEST_HUB_CHECK": "Facility check request",
    "INITIATE_CUSTODY_RECONCILIATION": "Custody reconciliation request", "PRIORITIZE_NEXT_SESSION": "Priority for the next delivery session",
    "REQUEST_ADDRESS_CONFIRMATION": "Address confirmation request", "REROUTE_TO_CONFIRMED_DESTINATION": "Reroute", "RETURN_TO_SENDER": "Return to sender",
    "DELIVERY_DISPUTE_REVIEW": "Delivery dispute review by a person", "CONFLICTING_CUSTODY_REVIEW": "Custody review by a person",
    "PHYSICAL_CUSTODY_CHECK": "Physical check by a person", "MANIFEST_RECONCILIATION_REVIEW": "Manifest review by a person",
}
# What new evidence the verifier waits for after each request (the record the outcome engine looks for).
AWAITED = {
    "REQUEST_RESCAN": ("a new barcode read of this parcel", "قراءة باركود جديدة لهذا الطرد"),
    "REQUEST_REWEIGH": ("a new weight reading of this parcel on a calibrated scale", "قراءة وزن جديدة لهذا الطرد على ميزان معاير"),
    "REQUEST_DEVICE_SYNC": ("the device's buffered records for this parcel", "السجلات المخزنة في الجهاز لهذا الطرد"),
    "REQUEST_ADDITIONAL_EVIDENCE": ("the requested evidence for this parcel", "الأدلة المطلوبة لهذا الطرد"),
    "REQUEST_HUB_CHECK": ("a scan of this parcel by the facility that was asked to look for it", "مسح لهذا الطرد من المنشأة التي طُلب منها البحث عنه"),
    "INITIATE_CUSTODY_RECONCILIATION": ("a corroborated custody record of this parcel at a facility", "سجل حيازة مؤيَّد لهذا الطرد في منشأة"),
    "PRIORITIZE_NEXT_SESSION": ("a corroborated delivery record of this parcel", "سجل تسليم مؤيَّد لهذا الطرد"),
    "REQUEST_ADDRESS_CONFIRMATION": ("the recipient's confirmation of the address", "تأكيد المستلم للعنوان"),
}
WAITING = {
    "queued_for_investigation": ("Waiting to be investigated", "بانتظار بدء التحقيق"),
    "investigating": ("Investigation running", "التحقيق جارٍ"),
    "awaiting_operator_decision": ("Waiting for a person", "بانتظار قرار شخص"),
    "awaiting_operational_action": ("Waiting for the request to be sent", "بانتظار إرسال الطلب"),
    "awaiting_new_evidence": ("Waiting for new evidence", "بانتظار أدلة جديدة"),
    "resolved": ("Resolved and verified", "تمت المعالجة والتحقق"),
    "closed_unresolved": ("Closed without a resolution", "أُغلقت دون معالجة"),
}
STATE_WAITING = {"OPEN": "queued_for_investigation", "REOPENED": "queued_for_investigation", "INVESTIGATING": "investigating",
                 "RECOMMENDATION_READY": "investigating", "AWAITING_APPROVAL": "awaiting_operator_decision", "HUMAN_REVIEW": "awaiting_operator_decision",
                 "ESCALATED": "awaiting_operator_decision", "NEEDS_EVIDENCE": "awaiting_operator_decision", "ACTION_INITIATED": "awaiting_operational_action",
                 "AWAITING_OUTCOME": "awaiting_new_evidence", "RESOLVED": "resolved", "REJECTED": "closed_unresolved"}
KIND_LABELS = {"ScanEvent": "Scan", "CustodyEvent": "Custody record", "StatusEvent": "Status record", "ExpectedMilestone": "Expected step",
               "RouteMilestone": "Planned step", "DeliveryAttempt": "Delivery attempt", "DeliveryProof": "Delivery proof", "HandoffEvidence": "Handover record",
               "PhotoEvidence": "Photo", "SignatureEvidence": "Signature", "DepotReconciliation": "Depot reconciliation", "CommunicationEvent": "Communication",
               "Device": "Device", "DeviceHeartbeat": "Device heartbeat", "Manifest": "Manifest", "Package": "Parcel", "Shipment": "Shipment", "Trip": "Trip",
               "Vehicle": "Vehicle", "RouteRun": "Route run", "ComputedResult": "Computed comparison"}


def _plain(text):
    """True when stored model text can stand in an operator sentence: no internal codes and no record ids."""
    from operations.canopus import code_free
    return code_free(text)


def waiting_kind(state):
    """What the case is waiting for. An unknown state is with a person, never automatic."""
    return STATE_WAITING.get(state, "awaiting_operator_decision")


def _label(table, code, fallback=None):
    en, ar = table.get(code, (fallback or str(code or "").replace("_", " ").lower(), None))
    return en, ar


def _when(value):
    text = str(value or "")
    return text[:16].replace("T", " ") + " UTC" if len(text) >= 16 else None


def _join(parts):
    parts = [p for p in parts if p]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1] if parts else ""


def _symptom_codes(detail):
    codes = detail.get("symptom_codes")
    if codes:
        return list(codes)
    for event in (detail.get("pipeline") or {}).get("events") or []:
        if event.get("stage") == "extract" and (event.get("output") or {}).get("symptoms"):
            return list(event["output"]["symptoms"])
    authority = (((detail.get("run") or {}).get("result") or {}).get("authority") or {}).get("inputs") or {}
    return list(authority.get("symptoms") or [])


def evidence_label(node_id, nodes):
    node = nodes.get(node_id)
    if node is None:
        kind = "ComputedResult" if "-CMP-" in str(node_id) else None
        return {"id": node_id, "kind": kind, "label_en": KIND_LABELS.get(kind, "Record outside this shipment's graph"), "label_ar": None,
                "occurred_at": None, "facility_id": None, "device_id": None, "in_graph": False}
    props = node.get("properties") or {}
    place = props.get("facility_id") or props.get("location_id")
    kind = node.get("kind")
    detail = str(props.get("observation_type") or props.get("event_type") or "").replace("_", " ").lower()
    label = KIND_LABELS.get(kind, kind or "Record") + (f" ({detail})" if detail else "") + (f" at {place}" if place else "") \
        + (f", {_when(props.get('occurred_at'))}" if props.get("occurred_at") else "")
    return {"id": node_id, "kind": kind, "label_en": label, "label_ar": None, "occurred_at": props.get("occurred_at"), "facility_id": place,
            "device_id": props.get("device_ref") or props.get("device_id"), "in_graph": True}


HUMAN_FINDINGS = {
    "parcel_located": ("Parcel located by a person", "عثر شخص على الطرد"),
    "delivered_confirmed_by_person": ("Delivery confirmed by a person from the recorded proof", "أكد شخص التسليم من الدليل المسجَّل"),
    "returned_to_depot": ("Return to the depot confirmed by a person", "أكد شخص عودة الطرد إلى المستودع"),
    "parcel_not_found": ("Parcel not found by a person", "لم يعثر شخص على الطرد"),
    "data_corrected": ("Record corrected by a person", "صحّح شخص السجل"),
}
# What still stands after a person's finding, in a few words each (the Problem line states each in full).
STILL_STANDS = {
    "MANIFEST_CUSTODY_CONFLICT": ("Manifest discrepancy remains", "ما زال تعارض بيان الإرسال قائمًا"),
    "SESSION_END_UNRECONCILED": ("Delivery session not reconciled", "جلسة التوزيع لم تُسوَّ"),
    "MILESTONE_OVERDUE": ("A journey step is still overdue", "ما زالت خطوة في الرحلة متأخرة"),
    "CUSTODY_TRANSFER_UNCONFIRMED": ("A handover is still unconfirmed", "ما زال تسليم غير مؤكَّد"),
    "DELIVERY_PROOF_INCOMPLETE": ("Delivery proof still incomplete", "ما زال دليل التسليم غير مكتمل"),
    "RECIPIENT_REPORTED_NOT_RECEIVED": ("Recipient's non-receipt report still open", "ما زال بلاغ المستلم بعدم الاستلام مفتوحًا"),
    "CUSTODY_REPORTS_CONFLICT": ("Custody records still conflict", "ما زالت سجلات الحيازة متعارضة"),
    "DELIVERY_ATTEMPT_FAILED": ("A failed delivery attempt is still open", "ما زالت محاولة تسليم فاشلة مفتوحة"),
}


def human_finding(outcome):
    """A person's recorded finding that did not close the case: what was recorded and what still stands, or None.
    The finding is on record; the case stays with a person until nothing remains."""
    if outcome.get("verification_status") != "HUMAN_FINDING":
        return None
    found_en, found_ar = HUMAN_FINDINGS.get(outcome.get("outcome_type"), ("Finding recorded by a person", "سجّل شخص نتيجة"))
    # Every standing problem is named, each in a few words; one the table does not know keeps its full sentence.
    remaining = [STILL_STANDS.get(code) or tuple(f"Still stands: {t}" if i == 0 else f"ما زال قائمًا: {t or code}" for i, t in enumerate(_label(SYMPTOMS, code)))
                 for code in outcome.get("remaining_symptoms") or []]
    return {"outcome_type": outcome.get("outcome_type"), "remaining_symptoms": list(outcome.get("remaining_symptoms") or []),
            "text_en": " ".join(part + "." for part in [found_en, *(en for en, _ in remaining), "Human review required"]),
            "text_ar": " ".join(part + "." for part in [found_ar, *(ar for _, ar in remaining), "تلزم مراجعة شخص"]),
            "short_en": "Finding recorded, not resolved", "short_ar": "سُجِّلت نتيجة دون معالجة"}


def _place(facility, nodes):
    """A facility as an operator reads it: its display name with its id, or the id alone."""
    name = ((nodes.get(facility) or {}).get("properties") or {}).get("display_name")
    return f"{name} ({facility})" if name else str(facility)


def resolution(outcome, nodes):
    """What the verifier confirmed, named from the evidence the verified outcome itself cites:
    {"kind", "text_en", "text_ar", "short_en", "short_ar", "facility_id"}. Custody confirmed at a facility, a parcel
    located by a facility's scan, or a delivery whose proof carries the recipient's passed authentication; anything else is the general sentence. A photo
    or a position alone never makes a delivery "verified" here: only the authenticated proof the verifier accepted."""
    cited = [nodes[i] for i in outcome.get("evidence_ids") or [] if i in nodes]
    custody = [n for n in cited if n.get("kind") == "CustodyEvent"]
    props = lambda n: n.get("properties") or {}
    if outcome.get("outcome_type") == "custody_reconciled":
        facility = next((props(n).get("to_id") or props(n).get("facility_id") for n in custody), None)
        where_en = f"{_place(facility, nodes)} recorded the parcel in its custody after the request" if facility else             "A facility recorded the parcel in its custody after the request"
        return {"kind": "custody_confirmed", "facility_id": facility,
                "text_en": f"Resolved: warehouse custody confirmed. {where_en}, and the verifier confirmed it.",
                "text_ar": "تمت المعالجة: تأكدت حيازة المستودع. سجّلت المنشأة الطرد في حيازتها بعد الطلب وأكد المدقق ذلك.",
                "short_en": "Verified: warehouse custody confirmed", "short_ar": "تم التحقق: تأكدت حيازة المستودع"}
    if outcome.get("outcome_type") == "parcel_located":
        facility = next((props(n).get("facility_id") for n in cited if n.get("kind") == "ScanEvent" and props(n).get("facility_id")), None)
        where_en = f"{_place(facility, nodes)} scanned the parcel after the request" if facility else "A facility scanned the parcel after the request"
        return {"kind": "parcel_located", "facility_id": facility,
                "text_en": f"Resolved: parcel located at the warehouse. {where_en}, and the verifier confirmed it.",
                "text_ar": "تمت المعالجة: عُثر على الطرد في المستودع. مسحت المنشأة الطرد بعد الطلب وأكد المدقق ذلك.",
                "short_en": "Verified: parcel located at the warehouse", "short_ar": "تم التحقق: الطرد موجود في المستودع"}
    for event in custody:
        if props(event).get("event_type") != "DELIVERED":
            continue
        proof = nodes.get(props(event).get("proof_id")) or {}
        authentication = nodes.get(props(proof).get("authentication_id")) or {}
        if proof.get("kind") == "DeliveryProof" and props(authentication).get("result") == "PASS":
            return {"kind": "delivery_verified", "facility_id": None,
                    "text_en": "Resolved: delivery status verified. The delivery record, confirmed by the recipient's code, reached Suhail "
                               "after the request, and the verifier confirmed it.",
                    "text_ar": "تمت المعالجة: تم التحقق من حالة التسليم. وصل سجل التسليم المؤكَّد برمز المستلم إلى سهيل بعد الطلب وأكده المدقق.",
                    "short_en": "Verified: delivery status confirmed", "short_ar": "تم التحقق: تأكدت حالة التسليم"}
    return {"kind": "problem_cleared", "facility_id": None,
            "text_en": "Resolved: the verifier confirmed from later evidence that the problem is cleared.",
            "text_ar": "تمت المعالجة: أكد المدقق من أدلة لاحقة زوال المشكلة.", "short_en": "Verified: problem cleared", "short_ar": "تم التحقق: زالت المشكلة"}


def action_explanation(execution, outcome, nodes):
    """What was sent, to whom (as far as the record says), what evidence is awaited and until when. Always simulated."""
    action = execution.get("action_type")
    label = ACTION_LABELS.get(action, str(action or "Action").replace("_", " ").capitalize())
    label_ar = ACTION_SUMMARY_AR.get(action)
    status = {"ACKNOWLEDGED": "sent", "NOT_ACKNOWLEDGED": "not_delivered"}.get(execution.get("status"), "authorized")
    device = execution.get("target_device")
    node = nodes.get(device) if device else None
    facility = ((node or {}).get("properties") or {}).get("facility_id")
    if device:
        # A facility's device stands for the facility: the request goes to the people there, so the facility is named.
        recipient = {"known": True, "kind": "device", "id": device, "facility_id": facility,
                     "facility_name": ((nodes.get(facility) or {}).get("properties") or {}).get("display_name") if facility else None,
                     "label_en": (f"{_place(facility, nodes)}, through its device {device}" if facility else f"device {device}"),
                     "label_ar": f"الجهاز {device}"}
    else:
        recipient = {"known": False, "kind": None, "id": None, "facility_id": None,
                     "label_en": "the facility holding the parcel (the request names no specific recipient)",
                     "label_ar": "المنشأة التي لديها الطرد (الطلب لا يسمّي مستلمًا محددًا)"}
    awaited_en, awaited_ar = AWAITED.get(action, ("new evidence about this parcel", "أدلة جديدة عن هذا الطرد"))
    deadline = execution.get("deadline_at")
    mine = outcome if outcome and outcome.get("execution_id") == execution.get("entity_id") else None
    result = None
    if mine:
        cleared = bool(mine.get("exception_cleared"))
        text = (("The verifier confirmed from later evidence that the problem is cleared. " if mine.get("success") and cleared
                 else "The verifier confirmed the request was carried out, but the problem is not cleared. " if mine.get("success")
                 else "The verifier did not find evidence that the request fixed the problem. ") + str(mine.get("reason") or "")).strip()
        result = {"verification_status": mine.get("verification_status"), "success": mine.get("success"), "outcome_type": mine.get("outcome_type"),
                  "exception_cleared": cleared, "verified_at": mine.get("verified_at"), "text_en": text,
                  "text_ar": ("أكد المدقق من أدلة لاحقة زوال المشكلة." if mine.get("success") and cleared
                              else "أكد المدقق تنفيذ الطلب لكن المشكلة لم تزُل." if mine.get("success") else "لم يجد المدقق دليلًا على أن الطلب عالج المشكلة.")}
    by = "automatic_policy" if execution.get("authority") == "AUTO_POLICY" else "operator_approval"
    who = "under the automatic policy" if by == "automatic_policy" else "after an operator's approval"
    if status == "not_delivered":
        text = (f"{label} could not be delivered (simulated): no recipient system could be named from the evidence. Nothing was sent, so there is "
                "nothing to verify and a person takes the case.")
        text_ar = "تعذّر تسليم الطلب (محاكاة): لم يمكن تحديد نظام مستلم من الأدلة. لم يُرسل شيء، فلا يوجد ما يُتحقق منه والحالة لدى شخص."
    elif result:
        text = f"{label} was sent to {recipient['label_en']} (simulated) {who}. {result['text_en']}"
        text_ar = f"أُرسل الطلب ({label_ar or action}) (محاكاة). {result['text_ar']}"
    elif status == "sent":
        text = (f"{label} sent to {recipient['label_en']} (simulated) {who}. Suhail is waiting for {awaited_en}. When it is recorded, Suhail checks it "
                "and verifies the result automatically." + (f" If nothing arrives by {_when(deadline)}, the verifier records the request as not "
                                                            "confirmed and the case goes to a person." if deadline else ""))
        text_ar = (f"أُرسل الطلب ({label_ar or action}) (محاكاة). ينتظر سهيل {awaited_ar}. عند تسجيلها يتحقق سهيل من النتيجة تلقائيًا."
                   + (f" إذا لم يصل شيء حتى {_when(deadline)} يسجّل المدقق أن الطلب لم يتأكد وتُحال الحالة إلى شخص." if deadline else ""))
    else:
        text = f"{label} is authorised {who} and is about to be sent (simulated)."
        text_ar = f"أُجيز الطلب ({label_ar or action}) وسيُرسل (محاكاة)."
    return {"execution_id": execution.get("entity_id"), "action_type": action, "label_en": label, "label_ar": label_ar, "simulated": True,
            "authorized_by": by, "status": status, "sent_at": execution.get("executed_at"), "recipient": recipient,
            "awaiting": None if result or status != "sent" else {"text_en": awaited_en, "text_ar": awaited_ar},
            # When an answer usually comes is shown only with evidence behind it (the answer times of verified past actions
            # of this type); none is computed yet, so the field is absent and the deadline is the only future time given.
            "expected_response_at": None, "expected_response_basis": None, "deadline_at": deadline,
            "deadline_text_en": (f"If no such record arrives by {_when(deadline)}, the verifier records the request as not confirmed and the case goes to a person."
                                 if deadline and not result and status == "sent" else None),
            "deadline_text_ar": (f"إذا لم يصل هذا السجل حتى {_when(deadline)} يسجّل المدقق أن الطلب لم يتأكد وتُحال الحالة إلى شخص."
                                 if deadline and not result and status == "sent" else None),
            "continues_automatically": status == "sent" and not result, "text_en": text, "text_ar": text_ar, "outcome": result}


POLICY = {
    "AUTO": ("automatic", "This is a safe, reversible request, so Suhail may send it without waiting for approval.",
             "هذا طلب آمن وقابل للتراجع، لذا يجوز لسهيل إرساله دون انتظار موافقة."),
    "APPROVAL_REQUIRED": ("needs_approval", "This action changes how the shipment is handled, so it waits for a person's approval.",
                          "يغيّر هذا الإجراء مناولة الشحنة، لذا ينتظر موافقة شخص."),
    "HUMAN_REVIEW": ("needs_person", "A person must take this case; Suhail may not act on it by itself.",
                     "يجب أن يتولى شخص هذه الحالة؛ لا يجوز لسهيل التصرف فيها بمفرده."),
    "PROHIBITED": ("prohibited", "This kind of decision is never automated.", "هذا النوع من القرارات لا يُؤتمت أبدًا."),
}


def stage_facts(events, verification=None):
    """One short fact per completed pipeline stage and round, from the recorded stage events, then the outcome."""
    facts, running = [], {}
    for event in events or []:
        out, stage, status = event.get("output") or {}, event.get("stage"), event.get("status")
        base = {"stage": stage, "iteration": event.get("iteration") or 0, "sequence": event.get("sequence")}
        if status in ("RUNNING", "RETRYING"):
            if out.get("kind") != "tool_call":
                running[stage] = {**base, "status": "running", "fact_en": None, "fact_ar": None}
            continue
        running.pop(stage, None)
        fact = fact_ar = None
        state = "failed" if status == "FAILED" else "done"
        if stage == "extract":
            names = _join([_label(SYMPTOMS, c)[0].lower() for c in out.get("symptoms") or []])
            fact, fact_ar = (f"Case opened: {names}" if names else "Case opened"), "فُتحت الحالة"
        elif stage == "retrieve":
            fact = f"{out.get('nodes')} records and {out.get('relationships')} connections read from the graph"
            fact_ar = f"قُرئ {out.get('nodes')} سجلًا و{out.get('relationships')} علاقة من الرسم المعرفي"
        elif stage == "classify":
            investigation = out.get("investigation") or {}
            cause = investigation.get("primary_cause") or investigation.get("primary_hypothesis") or next(
                (d.get("code") for d in out.get("diagnoses") or [] if d.get("status") == "supported"), None)
            checks = out.get("tool_calls")
            if cause and not investigation.get("degraded"):
                fact = f"Suspected cause: {_label(CAUSES, cause)[0]}" + (f" ({investigation.get('confidence')} confidence)" if investigation.get("confidence") else "") \
                    + (f", after {checks} checks" if checks else "")
                fact_ar = f"السبب المرجّح: {_label(CAUSES, cause)[1] or cause}"
            else:
                fact, fact_ar, state = "No usable conclusion in this round", "لم تُستخلص نتيجة صالحة في هذه الجولة", "failed"
        elif stage == "retrieve_context":
            count = out.get("verified_precedents") or 0
            fact = f"{count} verified similar case{'s' if count != 1 else ''} found" if count else "No verified similar case found"
            fact_ar = f"وُجد {count} من الحالات المشابهة المتحقق منها" if count else "لم توجد حالة مشابهة متحقق منها"
        elif stage == "recommend":
            action = (out.get("proposal") or {}).get("action_type")
            fact = f"Proposed: {ACTION_LABELS.get(action, action).lower()}" if action else "No action proposed"
            fact_ar = f"المقترح: {ACTION_SUMMARY_AR.get(action, action)}" if action else "لا إجراء مقترح"
        elif stage == "review":
            verdict = out.get("model_verdict") or out.get("verdict")
            accepted = out.get("verdict") == "accept" and verdict == "ACCEPT"
            fact = ("Independent review: accepted" if accepted else "Independent review: a person should decide" if verdict in ("HUMAN_REVIEW", "ESCALATE")
                    else "Independent review: unavailable" if verdict == "UNAVAILABLE" else "Independent review: asked for a revision")
            fact_ar = "المراجعة المستقلة: مقبول" if accepted else "المراجعة المستقلة: لم يُقبل"
            state = "done" if accepted else "rejected"
        elif stage in ("writeback", "escalate"):
            authority = out.get("authority") or {}
            risk, target = authority.get("risk_class"), out.get("workflow_state")
            fact = ("Request sent automatically under policy" if risk == "AUTO" and target in ("AWAITING_OUTCOME", "ACTION_INITIATED")
                    else "Held for a person's approval" if target == "AWAITING_APPROVAL"
                    else "Sent to a person: the review did not accept the investigation" if target == "ESCALATED"
                    else "Sent to a person: more evidence is needed first" if target == "NEEDS_EVIDENCE" else "Sent to a person for a decision")
            fact_ar = "أُرسل الطلب تلقائيًا وفق السياسة" if risk == "AUTO" and target in ("AWAITING_OUTCOME", "ACTION_INITIATED") else "أُحيلت الحالة إلى شخص"
        facts.append({**base, "status": state, "fact_en": fact, "fact_ar": fact_ar})
    facts += list(running.values())
    if verification:
        status = {"verified_resolved": "done", "awaiting_evidence": "running", "not_applicable": "not_reached",
                  "human_finding_not_resolved": "rejected"}.get(verification["status"], "rejected")
        facts.append({"stage": "outcome", "iteration": None, "sequence": None, "status": status, "fact_en": verification["short_en"], "fact_ar": verification["short_ar"]})
    return facts


CLOCK_PAUSED = ("The simulated clock is paused, so no new evidence can arrive. Press Start, or Skip to next event.",
                "الساعة المحاكاة متوقفة، فلا يمكن وصول أدلة جديدة. اضغط «بدء» أو «تخطٍّ إلى الحدث التالي».")


def build(detail):
    """The brief of a case detail (the dict GET /cases/{case_id} serves, before the brief is added). detail["clock"],
    when present, is {"state": "running" | "paused", "speed": n}: a case waiting for evidence while the clock is paused
    says so, because nothing can arrive until the clock runs."""
    state = detail.get("workflow_state")
    run = detail.get("run") or {}
    result = run.get("result") or {}
    authority = result.get("authority") or {}
    diagnosis = detail.get("diagnosis") or {}
    accepted = bool(diagnosis.get("available"))
    findings = diagnosis if accepted else (diagnosis.get("unaccepted_investigation") or {})
    review = detail.get("review") or {}
    recommendation = detail.get("recommendation") or {}
    outcome = detail.get("outcome") or {}
    nodes = {n.get("id"): n for n in (detail.get("evidence") or {}).get("nodes") or []}
    step = detail.get("next_step") or {}
    waiting = waiting_kind(state)
    resolved = state == "RESOLVED"

    codes = _symptom_codes(detail)
    symptoms = [{"code": c, "label_en": _label(SYMPTOMS, c)[0], "label_ar": _label(SYMPTOMS, c)[1]} for c in codes]
    shipment = detail.get("shipment_id")
    happened_en = (f"Suhail's monitor opened this case for shipment {shipment}: " + _join([s["label_en"][0].lower() + s["label_en"][1:] for s in symptoms]) + "."
                   if symptoms else f"Suhail's monitor opened this case for shipment {shipment}.")
    happened_ar = ("فتح نظام المراقبة هذه الحالة: " + "، ".join(s["label_ar"] or s["code"] for s in symptoms) + ".") if symptoms else "فتح نظام المراقبة هذه الحالة."

    cause = findings.get("primary_cause")
    cause_en, cause_ar = _label(CAUSES, cause) if cause else (None, None)
    if cause and accepted:
        cause_status, cause_text = "accepted", f"Suhail's investigation concluded that the cause is {cause_en}, and the independent review accepted it."
        cause_text_ar = f"خلص تحقيق سهيل إلى أن السبب هو {cause_ar or cause}، وقبلته المراجعة المستقلة."
    elif cause:
        cause_status = "hypothesis_not_accepted"
        cause_text = f"The investigation suggests {cause_en}. This is a hypothesis: the independent review has not accepted it."
        cause_text_ar = f"يرجّح التحقيق {cause_ar or cause}. هذه فرضية لم تقبلها المراجعة المستقلة."
    else:
        cause_status = "none"
        cause_text = ("The investigation is still running." if waiting == "investigating" else "The case has not been investigated yet." if waiting == "queued_for_investigation"
                      else "The investigation did not reach a usable conclusion.")
        cause_text_ar = "لم يتوصل التحقيق إلى نتيجة بعد."
    leading = next((h for h in findings.get("hypotheses") or [] if h.get("cause") == cause), None) or next(iter(findings.get("hypotheses") or []), {})
    cited = list(dict.fromkeys((leading.get("supporting_evidence_ids") or []) + (recommendation.get("evidence_ids") or [])))
    evidence = [evidence_label(i, nodes) for i in cited[:6]]

    verdict = review.get("model_verdict") or review.get("verdict")
    summaries = [e for e in (detail.get("narration") or {}).get("events") or [] if e.get("kind") == "canopus_summary" and e.get("phase") == "review"]
    reason_summary = summaries[-1] if summaries else {}
    if not review or not cause:
        review_status, review_en, review_ar = "not_reviewed", "There is no conclusion for the independent review to assess yet.", "لا توجد نتيجة لتقيّمها المراجعة المستقلة بعد."
    elif accepted:
        review_status, review_en, review_ar = "accepted", "The independent review accepted this conclusion.", "قبلت المراجعة المستقلة هذه النتيجة."
    elif verdict in ("HUMAN_REVIEW", "ESCALATE"):
        review_status, review_en, review_ar = "asked_for_person", "The independent review asked for a person to decide.", "طلبت المراجعة المستقلة أن يقرر شخص."
    elif verdict == "UNAVAILABLE":
        review_status, review_en, review_ar = "unavailable", "The independent review could not be completed, so nothing is treated as accepted.", "تعذّر إتمام المراجعة المستقلة، فلا يُعدّ شيء مقبولًا."
    else:
        review_status = "challenged"
        review_en = ("The independent review did not accept this conclusion: it found the evidence does not yet support it."
                     if verdict == "INSUFFICIENT_EVIDENCE" else "The independent review did not accept this conclusion and asked for it to be revised.")
        review_ar = "لم تقبل المراجعة المستقلة هذه النتيجة وطلبت تعديلها أو دعمها بأدلة."

    risk = authority.get("risk_class")
    action = recommendation.get("action_type") or authority.get("action_type")
    decision, policy_en, policy_ar = POLICY.get(risk, ("none", "No action has been decided.", "لم يُقرَّر أي إجراء."))
    if decision == "automatic" and review_status == "challenged":
        policy_en = ("The review did not accept the investigation, so only a safe evidence-gathering request may go out, and its result cannot close the case "
                     "by itself: the case is investigated and reviewed again first.")
        policy_ar = "لم تقبل المراجعة التحقيق، لذا يُسمح فقط بطلب آمن لجمع الأدلة، ولا تُغلق نتيجته الحالة بمفردها: يُعاد التحقيق والمراجعة أولًا."
    if decision == "needs_person" and recommendation.get("approvable"):
        policy_en += " A person may approve the evidence request to gather more evidence; that will not close the case."
        policy_ar += " يمكن لشخص الموافقة على طلب الأدلة لجمع أدلة إضافية، ولن يغلق ذلك الحالة."
    policy = {"decision": decision, "text_en": policy_en, "text_ar": policy_ar, "action_type": action, "action_label_en": ACTION_LABELS.get(action),
              "action_label_ar": ACTION_SUMMARY_AR.get(action), "action_description_en": (ACTIONS.get(action) or (None, None, None, None))[3],
              "rule_id": authority.get("rule_id"), "rule_reason": authority.get("reason")}

    actions = [action_explanation(e, outcome, nodes) for e in detail.get("executions") or []]
    latest = actions[0] if actions else None
    if resolved:
        confirmed = resolution(outcome, nodes)
        verification = {"status": "verified_resolved", "resolution": confirmed["kind"], "facility_id": confirmed["facility_id"],
                        **{k: confirmed[k] for k in ("text_en", "text_ar", "short_en", "short_ar")}}
    elif latest and latest["status"] == "not_delivered" and not latest["outcome"]:
        verification = {"status": "not_delivered", "text_en": "The request could not be delivered, so there is nothing to verify.",
                        "text_ar": "تعذّر تسليم الطلب، فلا يوجد ما يُتحقق منه.", "short_en": "Request not delivered", "short_ar": "تعذّر تسليم الطلب"}
    elif latest and latest["outcome"] and not latest["outcome"]["success"]:
        verification = {"status": "verified_not_fixed", "text_en": latest["outcome"]["text_en"], "text_ar": latest["outcome"]["text_ar"],
                        "short_en": "Not confirmed: problem remains", "short_ar": "لم يتأكد: المشكلة قائمة"}
    elif latest and latest["outcome"] and waiting in ("queued_for_investigation", "investigating"):
        verification = {"status": "verified_awaiting_reassessment",
                        "text_en": "The verifier confirmed the request worked. Because the review had not accepted the investigation, the case is being investigated and reviewed again before anything is closed.",
                        "text_ar": "أكد المدقق نجاح الطلب. ولأن المراجعة لم تكن قد قبلت التحقيق، يُعاد التحقيق والمراجعة قبل أي إغلاق.",
                        "short_en": "Verified; being reassessed", "short_ar": "تم التحقق؛ قيد إعادة التقييم"}
    elif latest and latest["outcome"]:
        # The request worked. Either the problem itself remains, or it is cleared but the case is not closed (the review
        # had not accepted the investigation, or closure is reserved for a person).
        verification = {"status": "verified_not_closed" if latest["outcome"]["exception_cleared"] else "verified_but_problem_remains",
                        "text_en": latest["outcome"]["text_en"] + " The case is not closed.",
                        "text_ar": latest["outcome"]["text_ar"] + " لم تُغلق الحالة.", "short_en": "Verified, not closed", "short_ar": "تم التحقق دون إغلاق"}
    elif latest and latest["status"] == "sent":
        verification = {"status": "awaiting_evidence", "text_en": f"Waiting for {latest['awaiting']['text_en']}. Nothing is verified yet.",
                        "text_ar": f"بانتظار {latest['awaiting']['text_ar']}. لم يُتحقق من شيء بعد.", "short_en": "Awaiting new evidence", "short_ar": "بانتظار أدلة جديدة"}
    else:
        verification = {"status": "not_applicable", "text_en": "No request has been sent, so there is nothing to verify.",
                        "text_ar": "لم يُرسل أي طلب، فلا يوجد ما يُتحقق منه.", "short_en": "Nothing sent", "short_ar": "لم يُرسل شيء"}
    recorded = None if resolved else human_finding(outcome)
    if recorded:
        verification = {"status": "human_finding_not_resolved", "remaining_symptoms": recorded["remaining_symptoms"],
                        **{k: recorded[k] for k in ("text_en", "text_ar", "short_en", "short_ar")}}
    verification.update(outcome_type=outcome.get("outcome_type"), verified_at=outcome.get("verified_at"), verifier_reason=outcome.get("reason"))

    lines = [{"key": "problem", "label_en": "Problem", "label_ar": "المشكلة", "text_en": _join([s["label_en"] for s in symptoms]) + "." if symptoms else happened_en,
              "text_ar": ("، ".join(s["label_ar"] or s["code"] for s in symptoms) + ".") if symptoms else happened_ar},
             {"key": "finding", "label_en": "Finding", "label_ar": "ما توصل إليه التحقيق", "text_en": cause_text, "text_ar": cause_text_ar}]
    if review_status in ("challenged", "asked_for_person", "unavailable"):
        # The Review line states the challenge, so the Finding line does not repeat it. Where a stored summary of the
        # reason exists and reads as plain language, it is the reason given; otherwise the fixed sentence stands.
        if cause:
            lines[1].update(text_en=f"The investigation suggests {cause_en}.", text_ar=f"يرجّح التحقيق {cause_ar or cause}.")
        line_en, line_ar = review_en, review_ar
        summary = reason_summary.get("text_en")
        if review_status == "challenged" and summary and _plain(summary):
            line_en = "The independent review did not accept this conclusion: " + summary[0].lower() + summary[1:]
            if reason_summary.get("text_ar") and _plain(reason_summary["text_ar"]):
                line_ar = "لم تقبل المراجعة المستقلة هذه النتيجة: " + reason_summary["text_ar"]
        lines.append({"key": "review", "label_en": "Review", "label_ar": "المراجعة", "text_en": line_en, "text_ar": line_ar})
    if latest:
        action_en, action_ar = latest["text_en"], latest["text_ar"]
    elif action and decision == "needs_approval":
        action_en, action_ar = f"Recommended: {ACTION_LABELS.get(action, action).lower()}. {policy_en}", f"الموصى به: {ACTION_SUMMARY_AR.get(action, action)} {policy_ar}"
    elif action:
        action_en, action_ar = f"Nothing has been sent. Proposed: {ACTION_LABELS.get(action, action).lower()}. {policy_en}", f"لم يُرسل شيء. المقترح: {ACTION_SUMMARY_AR.get(action, action)} {policy_ar}"
    else:
        action_en, action_ar = "Nothing has been sent.", "لم يُرسل شيء."
    lines.append({"key": "action", "label_en": "Action taken", "label_ar": "الإجراء المتخذ", "text_en": action_en, "text_ar": action_ar})
    status_en = verification["text_en"] if resolved or waiting == "awaiting_new_evidence" else (step.get("text_en") or WAITING[waiting][0] + ".")
    status_ar = verification["text_ar"] if resolved or waiting == "awaiting_new_evidence" else (step.get("text_ar") or WAITING[waiting][1] + ".")
    if recorded:
        status_en, status_ar = recorded["text_en"], recorded["text_ar"]
    clock_paused = (detail.get("clock") or {}).get("state") == "paused" if detail.get("clock") else None
    stalled = bool(clock_paused) and waiting in ("awaiting_new_evidence", "awaiting_operational_action")
    if stalled:
        status_en, status_ar = f"{CLOCK_PAUSED[0]} {status_en}", f"{CLOCK_PAUSED[1]} {status_ar}"
    lines.append({"key": "status", "label_en": "Current status", "label_ar": "الوضع الحالي", "text_en": status_en, "text_ar": status_ar})

    return {
        "version": 1, "source": "composed by code from the case's stored records", "resolved": resolved,
        # clock_paused: whether the simulated clock is paused (None when unknown). waiting_on_paused_clock: the case
        # waits for evidence that cannot arrive until the clock runs.
        "clock_paused": clock_paused, "waiting_on_paused_clock": stalled,
        "waiting_kind": waiting, "waiting_label_en": WAITING[waiting][0], "waiting_label_ar": WAITING[waiting][1], "lines": lines,
        "what_happened": {"text_en": happened_en, "text_ar": happened_ar, "opened_at": detail.get("opened_at"), "symptoms": symptoms},
        "suspected_cause": {"status": cause_status, "code": cause, "label_en": cause_en, "label_ar": cause_ar, "confidence": findings.get("confidence"),
                            "text_en": cause_text, "text_ar": cause_text_ar, "investigator_summary": findings.get("summary")},
        "evidence": evidence,
        "review": {"status": review_status, "text_en": review_en, "text_ar": review_ar, "reason_summary_en": reason_summary.get("text_en"),
                   "reason_summary_ar": reason_summary.get("text_ar"), "reason_original": review.get("feedback"), "verdict_code": verdict},
        "policy": policy, "actions": actions,
        "verification": {k: v for k, v in verification.items() if not k.startswith("short_")},
        "next_step": {k: step.get(k) for k in ("code", "actor", "text_en", "text_ar")},
        "technical": {"workflow_state": state, "state_version": detail.get("state_version"), "run_id": detail.get("last_run_id"),
                      "authority_rule_id": authority.get("rule_id"), "review_verdict": verdict, "closure": authority.get("closure")},
        "_stage_outcome": verification,
    }
