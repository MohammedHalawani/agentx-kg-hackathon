"""Canopus questions: an operator asks about one case and is answered from that case's stored records.

One question, one case, at most one model call, nothing stored and nothing written. The answer has three separate parts
the interface shows differently:

  answer     Canopus's own text (kind canopus_answer), or text built by code from the records (kind record_answer) when
             the model's reply is unusable, the call fails or the model is off;
  quotes     the investigator's and the reviewer's recorded words, copied by code from stored records. The model only
             chooses which ids to show; it never supplies their text;
  offers     what the existing rules allow an operator to do for this case right now (approve the recommended
             evidence-gathering request, mark the case as needing evidence, re-analyse it), each with the existing
             endpoint the interface calls after the operator confirms. Canopus performs none of them.

Canopus reads the case detail's stored fields only: state, run, narration, review, recommendation, executions, outcome,
next step, and the ids and kinds of evidence records. It is given no prompt of another agent, no raw model reply and no
simulator state. The grounding check of the narrator applies: an answer that names a record id that is not in the
case's context, or says the case is resolved when its recorded state is not RESOLVED, is discarded.
"""
import json
import os
import re
from datetime import datetime, timezone

from operations.authority import ACTIONS, EVIDENCE_GATHERING
from operations.narration import CALL_DEADLINE_SECONDS, ID_SHAPE, graph_ids, grounded, model_label, plain_hyphens

ENABLED_ENV = "SUHAIL_CANOPUS"
MAX_QUESTION = 500
MAX_HISTORY = 6
REPLY_SCHEMA = {"answer_en": None, "answer_ar": None, "quote_ids": [], "evidence_ids": []}
REQUEST_EVIDENCE_STATES = frozenset(("OPEN", "AWAITING_APPROVAL", "HUMAN_REVIEW", "NEEDS_EVIDENCE", "RECOMMENDATION_READY"))
REANALYSE_STATES = frozenset(("HUMAN_REVIEW", "AWAITING_APPROVAL", "RECOMMENDATION_READY", "NEEDS_EVIDENCE"))

SYSTEM_PROMPT = (
    "You are Canopus, the assistant inside Suhail, a logistics exception platform. An operator is looking at ONE shipment case and asks you a "
    "question. You are given that case's RECORDED facts as JSON, already in plain language. Answer like a helpful colleague in a chat: 1 to 4 "
    "short sentences of normal prose, or a few short bullets when listing; answer the question asked and nothing else. Speak as Suhail's one "
    "voice: do not narrate separate agents unless the operator asks who said what. Rules: use only the JSON; if it does not contain the "
    "answer, say that it is not recorded; never add a cause, an outcome, a time or a number that is not there. Never write internal codes: no "
    "rule ids, no words in capitals with underscores, no state names in capitals, no record ids. You may name the shipment, a facility or a "
    "device by its identifier; refer to any other record by describing it ('the sorter scan at 20:23'). A suspected cause is a hypothesis unless "
    "suspected_cause.status is 'accepted': say 'the investigation suggests' and, when the review did not accept it, say so plainly and why. "
    "Requests are simulated: say so when you describe one being sent. Never say the case is resolved, fixed or closed unless `resolved` is "
    "true. You cannot perform, approve or authorize anything: when asked to act, say what the operator can do now from "
    "`what_the_operator_can_do_now`, or that it is not possible and why from `what_is_not_possible_now`. When, and only when, the operator "
    "asks for an agent's original message or exact words, put the ids of the matching `quotes` entries in quote_ids (prefer `conclusion` and "
    "`review_feedback` entries) and say the original is shown below; never retype a quote. Reply with JSON only: {\"answer_en\": the answer "
    "in English, \"answer_ar\": the same answer in Modern Standard Arabic, \"quote_ids\": [], \"evidence_ids\": []}.")


def enabled():
    return os.environ.get(ENABLED_ENV, "").strip().lower() in ("1", "true", "on", "yes")


def quotes_of(detail):
    """Every recorded message of the investigator and the reviewer that can be shown verbatim, by id."""
    quotes = {}
    for event in (detail.get("narration") or {}).get("events") or []:
        if event.get("kind") != "agent_output":
            continue
        quotes[event["id"]] = {"role": "reviewer" if event.get("phase") == "review" else "investigator", "text": event.get("text_en"),
                               "record_id": event["id"], "run_id": event.get("run_id"), "stage": event.get("stage"),
                               "iteration": event.get("iteration") or 0, "occurred_at": event.get("occurred_at"), "title_en": event.get("title_en")}
    review = detail.get("review") or {}
    run = detail.get("run") or {}
    if review.get("feedback") and not any(q["role"] == "reviewer" for q in quotes.values()):
        key = review.get("entity_id") or f"{detail.get('last_run_id')}-review"
        quotes[key] = {"role": "reviewer", "text": review["feedback"], "record_id": key, "run_id": review.get("run_id") or detail.get("last_run_id"),
                       "stage": "review", "iteration": review.get("iteration") or 0, "occurred_at": review.get("recorded_at"),
                       "title_en": f"Reviewer's own words ({review.get('model_verdict') or review.get('verdict')})"}
    diagnosis = detail.get("diagnosis") or {}
    findings = diagnosis if diagnosis.get("available") else (diagnosis.get("unaccepted_investigation") or {})
    if findings.get("summary") and not any(q["role"] == "investigator" for q in quotes.values()):
        key = f"{detail.get('last_run_id')}-conclusion"
        quotes[key] = {"role": "investigator", "text": findings["summary"], "record_id": key, "run_id": detail.get("last_run_id"), "stage": "classify",
                       "iteration": 0, "occurred_at": run.get("recorded_at"),
                       "title_en": "Investigator's conclusion" + ("" if diagnosis.get("available") else " (not accepted by the reviewer)")}
    return quotes


OFFER_LABELS = {"request_evidence": ("Mark the case as needing more evidence", "تعليم الحالة بأنها تحتاج إلى أدلة إضافية"),
                "reanalyze": ("Investigate the case again with the evidence visible now", "إعادة التحقيق في الحالة بالأدلة الظاهرة الآن")}
WAITING_REASON = {
    "queued_for_investigation": ("the case has not been investigated yet", "لم يبدأ التحقيق في الحالة بعد"),
    "investigating": ("an investigation is running", "التحقيق جارٍ"),
    "awaiting_operational_action": ("a request is being sent", "يجري إرسال طلب"),
    "awaiting_new_evidence": ("a request was sent and Suhail is waiting for its result", "أُرسل طلب وسهيل ينتظر نتيجته"),
    "awaiting_operator_decision": ("the case is with a person in a state that does not allow it", "الحالة لدى شخص في وضع لا يسمح بذلك"),
    "resolved": ("the case is resolved", "تمت معالجة الحالة"),
    "closed_unresolved": ("the case is closed", "الحالة مغلقة"),
}


def offers_of(detail):
    """What the existing rules allow an operator to do for this case now, with the existing endpoint for each, and what
    they do not allow, with the reason in plain words. Computed by code from the case's state and the recommendation's
    own approval check; nothing here is decided by a model. Codes are in `rule_id`, never in a sentence."""
    from operations.brief import ACTION_LABELS, waiting_kind
    case_id, state, version = detail.get("case_id"), detail.get("workflow_state"), detail.get("state_version")
    recommendation = detail.get("recommendation") or {}
    action = recommendation.get("action_type")
    name = ACTION_LABELS.get(action, "the recommended action").lower() if action else None
    why_en, why_ar = WAITING_REASON.get(waiting_kind(state), WAITING_REASON["awaiting_operator_decision"])
    out = []
    if action in EVIDENCE_GATHERING:
        allowed = bool(recommendation.get("approvable"))
        executed = recommendation.get("approval_rule") == "AUTH-24-recommendation-already-executed"
        reason_en = None if allowed else ("this request was already sent; approving it again would repeat it" if executed
                                          else why_en if recommendation.get("approval_rule") == "LIFECYCLE-not-awaiting-decision"
                                          else "the authority rules do not let a person authorise it for this case")
        reason_ar = None if allowed else ("أُرسل هذا الطلب من قبل؛ الموافقة عليه مجددًا ستكرره" if executed
                                          else why_ar if recommendation.get("approval_rule") == "LIFECYCLE-not-awaiting-decision" else "قواعد الصلاحيات لا تسمح لشخص بتفويضه في هذه الحالة")
        out.append({"type": "approve_recommendation", "action_type": action, "allowed": allowed, "rule_id": recommendation.get("approval_rule"),
                    "rule_reason": recommendation.get("approval_reason"), "reason_en": reason_en, "reason_ar": reason_ar,
                    "label_en": f"Approve the {name}", "label_ar": "الموافقة على طلب الأدلة الموصى به",
                    "confirm": {"method": "POST", "path": f"/cases/{case_id}/decision", "body": {"decision": "approve", "expected_version": version}} if allowed else None})
    elif action:
        out.append({"type": "approve_recommendation", "action_type": action, "allowed": False, "rule_id": "CANOPUS-evidence-requests-only", "rule_reason": None,
                    "reason_en": f"{name} is not an evidence request; it is decided in Review & authorize, not from this chat",
                    "reason_ar": "هذا الإجراء ليس طلب أدلة؛ يُقرَّر في صفحة المراجعة والتفويض وليس من هذه المحادثة",
                    "label_en": f"Approve {name}", "label_ar": "الموافقة على الإجراء الموصى به", "confirm": None})
    for kind, states, path, body in (
            ("request_evidence", REQUEST_EVIDENCE_STATES, f"/cases/{case_id}/decision", {"decision": "request_evidence", "expected_version": version}),
            ("reanalyze", REANALYSE_STATES, f"/cases/{case_id}/reanalyze", {"expected_version": version})):
        allowed = state in states
        out.append({"type": kind, "action_type": None, "allowed": allowed, "rule_id": None if allowed else "LIFECYCLE-not-available-in-state", "rule_reason": None,
                    "reason_en": None if allowed else why_en, "reason_ar": None if allowed else why_ar,
                    "label_en": OFFER_LABELS[kind][0], "label_ar": OFFER_LABELS[kind][1],
                    "confirm": {"method": "POST", "path": path, "body": body} if allowed else None})
    return out


def quote_type(quote):
    if quote["role"] == "reviewer":
        return "review_feedback"
    return "tool_call_purpose" if str(quote.get("title_en") or "").startswith("Investigator checks") else "conclusion"


def _clip(text, limit=500):
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "…"


def context_of(detail, quotes, offers):
    """The recorded facts the model is given for one question: the case brief first, in operator language."""
    b = detail.get("brief") or {}
    return {
        "shipment_id": detail.get("shipment_id"), "resolved": bool(b.get("resolved")), "what_the_case_is_waiting_for": b.get("waiting_label_en"),
        "assessment": {line["label_en"]: line["text_en"] for line in b.get("lines") or []},
        "what_happened": (b.get("what_happened") or {}).get("text_en"),
        "suspected_cause": {k: (b.get("suspected_cause") or {}).get(k) for k in ("status", "label_en", "confidence", "text_en", "investigator_summary")},
        "review": {k: (b.get("review") or {}).get(k) for k in ("status", "text_en", "reason_summary_en", "reason_original")},
        "what_policy_permits": (b.get("policy") or {}).get("text_en"),
        "requests_sent": [{"what": a.get("label_en"), "simulated": True, "status": a.get("status"), "authorized_by": a.get("authorized_by"),
                           "recipient": (a.get("recipient") or {}).get("label_en"), "waiting_for": (a.get("awaiting") or {}).get("text_en"),
                           "deadline": a.get("deadline_at"), "explanation": a.get("text_en")} for a in b.get("actions") or []],
        "verification": (b.get("verification") or {}).get("text_en"),
        "next_step": (b.get("next_step") or {}).get("text_en"), "who_acts_next": (b.get("next_step") or {}).get("actor"),
        "missing_evidence": ((detail.get("next_step") or {}).get("missing_evidence") or [])[:5],
        "evidence": [{"description": e.get("label_en"), "shown_in_graph": e.get("in_graph")} for e in b.get("evidence") or []],
        # `what` tells a conclusion or review feedback from the purpose the investigator stated for one tool call.
        "quotes": [{"id": key, "role": q["role"], "what": quote_type(q), "text": _clip(q["text"], 420)}
                   for key, q in sorted(quotes.items(), key=lambda item: quote_type(item[1]) == "tool_call_purpose")[:16]],
        "what_the_operator_can_do_now": [o["label_en"] for o in offers if o["allowed"]],
        "what_is_not_possible_now": [{"action": o["label_en"], "because": o["reason_en"]} for o in offers if not o["allowed"]],
    }


CODE_SHAPES = re.compile(r"\b(?:AUTH|LIFECYCLE|CANOPUS)-[A-Za-z0-9-]+|\b[A-Z]{2,}(?:_[A-Z0-9]+)+\b")
STATE_WORDS = re.compile(r"\b(?:ESCALATED|RESOLVED|REOPENED|INVESTIGATING|REJECTED|ACCEPT|REVISE|ESCALATE|UNAVAILABLE)\b")
OPERATOR_IDS = re.compile(r"^(?:DEMO|SYN)-(?:SHP-\d{6}|(?:DEV|SORT|DEPOT|HUB|ORGWH)-[A-Z0-9-]+)$")


def code_free(text):
    """True when a sentence for the operator carries no rule id, no state, verdict or cause code and no internal record
    id. Shipment, facility and device identifiers are operator vocabulary and are allowed."""
    if not isinstance(text, str):
        return False
    if CODE_SHAPES.search(text) or STATE_WORDS.search(text):
        return False
    return all(OPERATOR_IDS.match(found) for found in ID_SHAPE.findall(text))


def record_answer(detail, question, quotes):
    """The answer built by code when the model's reply cannot be used: the case brief's own lines, in order."""
    b = detail.get("brief") or {}
    text = " ".join(line["text_en"] for line in b.get("lines") or [] if line.get("text_en")) or "Nothing is recorded for this case yet."
    arabic = " ".join(line["text_ar"] for line in b.get("lines") or [] if line.get("text_ar")) or None
    return text, arabic, quotes_asked_for(question, quotes)


ASKS_FOR_WORDS = re.compile(r"original|exact|verbatim|quote|own words|message|what did (?:the )?(?:reviewer|investigator) (?:say|write|conclude)|"
                            r"الأصلي|الأصلية|بالنص|نص الرسالة|ماذا قال", re.IGNORECASE)


def quotes_asked_for(question, quotes):
    """The recorded messages to show, and only when the question asks for an agent's words."""
    if not ASKS_FOR_WORDS.search(question or ""):
        return []
    reviewer = bool(re.search(r"review|مراجع", question, re.IGNORECASE))
    investigator = bool(re.search(r"investigat|محقق", question, re.IGNORECASE))
    wanted = [key for key, q in quotes.items() if quote_type(q) != "tool_call_purpose"
              and (q["role"] == "reviewer" if reviewer and not investigator else q["role"] == "investigator" if investigator and not reviewer else True)]
    return wanted[-3:]


def provider_ask(system, user):
    from llm.pipeline import _llm
    return _llm.ask_json(system, user, dict(REPLY_SCHEMA), deadline=CALL_DEADLINE_SECONDS)


def answer(detail, question, *, language="en", history=(), ask=None, use_model=True):
    """The response of POST /cases/{case_id}/canopus/ask for a case detail. Reads only `detail`; writes nothing."""
    if not detail.get("brief"):
        from operations import brief
        composed = brief.build(detail)
        composed.pop("_stage_outcome", None)
        detail = {**detail, "brief": composed}
    quotes = quotes_of(detail)
    every_offer = offers_of(detail)
    offers = every_offer
    state = detail.get("workflow_state")
    evidence_nodes = {n.get("id") for n in (detail.get("evidence") or {}).get("nodes") or []}
    base = {"case_id": detail.get("case_id"), "shipment_id": detail.get("shipment_id"), "run_id": detail.get("last_run_id"), "workflow_state": state,
            "answered_at": datetime.now(timezone.utc).isoformat(), "next_step": detail.get("next_step"),
            # Only what can be done now is offered. What cannot is listed apart, with the reason in plain words, for the
            # interface to show when the operator asks why.
            "offers": [{k: o[k] for k in ("type", "action_type", "label_en", "label_ar", "confirm")} for o in every_offer if o["allowed"]],
            "unavailable_offers": [{k: o[k] for k in ("type", "action_type", "label_en", "label_ar", "reason_en", "reason_ar", "rule_id")}
                                   for o in every_offer if not o["allowed"]]}
    text, arabic, chosen, cited, model, calls, usable = None, None, [], [], None, 0, False
    if use_model:
        context = context_of(detail, quotes, offers)
        turns = [{"role": t.get("role"), "text": _clip(t.get("text"), 400)} for t in list(history or [])[-MAX_HISTORY:] if isinstance(t, dict)]
        payload = json.dumps({"question": question, "operator_language": language, "earlier_turns": turns, "case": context},
                             ensure_ascii=False, sort_keys=True, default=str)
        calls = 1
        try:
            reply = (ask or provider_ask)(SYSTEM_PROMPT, payload)
        except Exception:  # noqa: BLE001  Provider failure or timeout: the record-based answer stands.
            reply = None
        if isinstance(reply, dict):
            reply = {key: plain_hyphens(value) if isinstance(value, str) else value for key, value in reply.items()}
            allowed = set(ID_SHAPE.findall(payload)) | {str(i) for i in evidence_nodes}
            candidate = reply.get("answer_en")
            picked = [q for q in reply.get("quote_ids") or [] if isinstance(q, str)]
            if (grounded(candidate, allowed, state == "RESOLVED") and code_free(candidate) and len(candidate) <= 1500
                    and all(q in quotes for q in picked)):
                usable, text, model = True, candidate.strip(), model_label()
                arabic = reply.get("answer_ar") if (grounded(reply.get("answer_ar"), allowed, True) and code_free(reply.get("answer_ar"))
                                                    and len(str(reply.get("answer_ar"))) <= 2000) else None
                # The agents' words are shown only when the operator asks for them.
                chosen = picked[:3] if ASKS_FOR_WORDS.search(question or "") else []
                normal = {a.replace("SYN-", "DEMO-", 1): a for a in allowed}
                cited = [normal[e.replace("SYN-", "DEMO-", 1)] for e in reply.get("evidence_ids") or []
                         if isinstance(e, str) and e.replace("SYN-", "DEMO-", 1) in normal][:8]
    if not usable:
        text, arabic, chosen = record_answer(detail, question, quotes)
    retrieved = [n for n in cited if n in evidence_nodes]
    if not retrieved:
        # The answer cited no graph record itself (often it cites a computation or a narration record): highlight the
        # graph records the shown quotes are about, else the ones the leading hypothesis rests on. All are recorded ids.
        events = {e.get("id"): e for e in (detail.get("narration") or {}).get("events") or []}
        diagnosis = detail.get("diagnosis") or {}
        findings = diagnosis if diagnosis.get("available") else (diagnosis.get("unaccepted_investigation") or {})
        about = [i for q in chosen for i in (events.get(q) or {}).get("graph_node_ids") or []]
        about = about or [i for h in (findings.get("hypotheses") or [])[:1] for i in h.get("supporting_evidence_ids") or []]
        retrieved = [i for i in dict.fromkeys(about) if i in evidence_nodes][:12]
    return {**base, "kind": "canopus_answer" if usable else "record_answer", "answer_en": text, "answer_ar": arabic, "evidence_ids": cited,
            "graph_node_ids": retrieved, "quotes": [quotes[q] for q in chosen],
            "technical": {"workflow_state": state, "rule_id": (detail["brief"].get("technical") or {}).get("authority_rule_id"),
                          "review_verdict": (detail["brief"].get("technical") or {}).get("review_verdict"), "evidence_ids": cited},
            "model": model, "grounded": True if usable else None, "fallback": bool(use_model and not usable), "model_calls": calls}
