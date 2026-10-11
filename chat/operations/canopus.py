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
    "You are Canopus, the assistant of a logistics exception investigation system. An operator asks a question about ONE case. You are "
    "given that case's RECORDED facts as JSON: its state, what the investigator and the reviewer recorded, the authority decision, the "
    "actions attempted and what the verifier found, what is needed next, the quotes available, and the offers the rules allow. Answer in "
    "2 to 5 short sentences, in plain language. Rules: use only the JSON; if it does not contain the answer, say what is not recorded; "
    "never add a cause, an outcome, a number or a record id that is not there, and copy record ids exactly with plain hyphens; a "
    "hypothesis is not a fact, so say 'the investigator concluded' or 'the reviewer found'; never say the case is resolved, fixed or "
    "closed unless workflow_state is exactly RESOLVED; you cannot perform, approve or authorize anything: when the operator asks for an "
    "action, say which offer in `offers` covers it and that the operator must confirm it, or that the rules do not allow it and why; do "
    "not quote the investigator or the reviewer from memory: to show their words, put the ids of the matching entries of `quotes` in "
    "quote_ids and the interface shows the originals beside your answer (never write a quote's id in the answer text; say that the "
    "original is shown below); when asked for an agent's message or original output, choose its `conclusion` or "
    "`review_feedback` entries, and a `tool_call_purpose` only when the question is about that step. Reply with JSON only: {\"answer_en\": the answer in English, \"answer_ar\": the "
    "same answer in Modern Standard Arabic, \"quote_ids\": [ids from `quotes` worth showing, at most 4], \"evidence_ids\": [record ids "
    "from the JSON that the answer relies on, at most 8]}.")


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


def offers_of(detail):
    """What the existing rules allow an operator to do for this case now, with the existing endpoint for each. Computed
    by code from the case's state and the recommendation's own approval check; nothing here is decided by a model."""
    case_id, state, version = detail.get("case_id"), detail.get("workflow_state"), detail.get("state_version")
    recommendation = detail.get("recommendation") or {}
    action = recommendation.get("action_type")
    out = []
    if action in EVIDENCE_GATHERING:
        allowed = bool(recommendation.get("approvable"))
        out.append({"type": "approve_recommendation", "action_type": action, "allowed": allowed, "rule_id": recommendation.get("approval_rule"),
                    "reason": recommendation.get("approval_reason"),
                    "label_en": f"Approve the evidence request {action}: {ACTIONS[action][3]}", "label_ar": f"الموافقة على طلب الأدلة {action}",
                    "confirm": {"method": "POST", "path": f"/cases/{case_id}/decision", "body": {"decision": "approve", "expected_version": version}}})
    elif action:
        out.append({"type": "approve_recommendation", "action_type": action, "allowed": False, "rule_id": "CANOPUS-evidence-requests-only",
                    "reason": f"{action} is not an evidence-gathering request. Canopus can only point to evidence requests; this action is decided in Review & authorize.",
                    "label_en": f"{action} is decided in Review & authorize", "label_ar": f"الإجراء {action} يُقرَّر في صفحة المراجعة والتفويض", "confirm": None})
    for kind, states, label_en, label_ar, path, body in (
            ("request_evidence", REQUEST_EVIDENCE_STATES, "Mark the case as needing more evidence", "تعليم الحالة بأنها تحتاج إلى أدلة إضافية",
             f"/cases/{case_id}/decision", {"decision": "request_evidence", "expected_version": version}),
            ("reanalyze", REANALYSE_STATES, "Investigate the case again with the evidence visible now", "إعادة التحقيق في الحالة بالأدلة الظاهرة الآن",
             f"/cases/{case_id}/reanalyze", {"expected_version": version})):
        allowed = state in states
        out.append({"type": kind, "action_type": None, "allowed": allowed, "rule_id": None if allowed else "LIFECYCLE-not-available-in-state",
                    "reason": None if allowed else f"Not available while the case is {state}.", "label_en": label_en, "label_ar": label_ar,
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
    """The recorded facts the model is given for one question."""
    run = detail.get("run") or {}
    result = run.get("result") or {}
    authority = result.get("authority") or {}
    diagnosis = detail.get("diagnosis") or {}
    findings = diagnosis if diagnosis.get("available") else (diagnosis.get("unaccepted_investigation") or {})
    review = detail.get("review") or {}
    outcome = detail.get("outcome") or {}
    narration = [{"sequence": e.get("sequence"), "stage": e.get("stage"), "phase": e.get("phase"), "source": e.get("kind"), "title": e.get("title_en"),
                  "text": _clip(e.get("text_en"), 360), "evidence_ids": (e.get("evidence_ids") or [])[:4]}
                 for e in (detail.get("narration") or {}).get("events") or [] if e.get("kind") != "agent_output"][-14:]
    kinds = {}
    for node in (detail.get("evidence") or {}).get("nodes") or []:
        kinds[node.get("kind")] = kinds.get(node.get("kind"), 0) + 1
    return {
        "case_id": detail.get("case_id"), "shipment_id": detail.get("shipment_id"), "workflow_state": detail.get("workflow_state"),
        "investigation_status": run.get("status"), "simulation_clock": detail.get("as_of"),
        "investigator": {"accepted_by_reviewer": bool(diagnosis.get("available")), "primary_cause": findings.get("primary_cause"),
                         "confidence": findings.get("confidence"), "summary": _clip(findings.get("summary"), 700),
                         "missing_evidence": findings.get("missing_evidence") or [],
                         "hypotheses": [{"cause": h.get("cause"), "status": h.get("status"), "assessment": _clip(h.get("assessment"), 300),
                                         "supporting_evidence_ids": (h.get("supporting_evidence_ids") or [])[:6]} for h in findings.get("hypotheses") or []][:4]},
        "reviewer": {"verdict": review.get("model_verdict") or review.get("verdict"), "accepted": review.get("verdict") == "accept",
                     "feedback": _clip(review.get("feedback"), 700)},
        "authority": {k: authority.get(k) for k in ("rule_id", "risk_class", "reason", "action_type", "closure")},
        "recommendation": {k: (detail.get("recommendation") or {}).get(k) for k in ("action_type", "action_en", "approvable", "approval_rule", "approval_reason")},
        "attempted_actions": (detail.get("next_step") or {}).get("attempted") or [],
        "verified_outcome": {k: outcome.get(k) for k in ("verification_status", "success", "outcome_type", "exception_cleared", "reason")} if outcome else None,
        "next_step": {k: (detail.get("next_step") or {}).get(k) for k in ("code", "actor", "text_en", "missing_evidence")},
        "recorded_events": narration,
        "evidence_records_by_kind": kinds,
        # `what` tells a conclusion or review feedback from the purpose the investigator stated for one tool call.
        "quotes": [{"id": key, "role": q["role"], "what": quote_type(q), "title": q["title_en"], "text": _clip(q["text"], 420)}
                   for key, q in sorted(quotes.items(), key=lambda item: quote_type(item[1]) == "tool_call_purpose")[:16]],
        "offers": [{"type": o["type"], "action_type": o["action_type"], "allowed": o["allowed"], "reason": o["reason"], "label": o["label_en"]} for o in offers],
    }


def record_answer(detail, question, quotes):
    """The answer built by code when the model's reply cannot be used: the recorded state, why, and what is next."""
    step = detail.get("next_step") or {}
    blocked = step.get("blocked_by") or {}
    state = detail.get("workflow_state")
    parts = [f"The case is {state}."]
    if blocked.get("rule_id"):
        parts.append(f"Authority rule {blocked['rule_id']}: {blocked.get('reason')}")
    if blocked.get("review_verdict"):
        parts.append(f"The reviewer's verdict was {blocked['review_verdict']}.")
    for attempt in step.get("attempted") or []:
        if attempt.get("outcome_type"):
            parts.append(f"{attempt['action_type']} was sent; the verifier recorded {attempt['outcome_type']} (success: {attempt.get('success')}).")
    if step.get("missing_evidence"):
        parts.append("Missing evidence recorded: " + "; ".join(step["missing_evidence"][:3]) + ".")
    if step.get("text_en"):
        parts.append(step["text_en"])
    wanted = "reviewer" if re.search(r"review", question, re.IGNORECASE) else "investigator" if re.search(r"investigat|original|message", question, re.IGNORECASE) else None
    chosen = [key for key, q in quotes.items() if q["role"] == wanted][-2:] if wanted else []
    return " ".join(parts), step.get("text_ar"), chosen


def provider_ask(system, user):
    from llm.pipeline import _llm
    return _llm.ask_json(system, user, dict(REPLY_SCHEMA), deadline=CALL_DEADLINE_SECONDS)


def answer(detail, question, *, language="en", history=(), ask=None, use_model=True):
    """The response of POST /cases/{case_id}/canopus/ask for a case detail. Reads only `detail`; writes nothing."""
    quotes = quotes_of(detail)
    offers = offers_of(detail)
    state = detail.get("workflow_state")
    evidence_nodes = {n.get("id") for n in (detail.get("evidence") or {}).get("nodes") or []}
    base = {"case_id": detail.get("case_id"), "shipment_id": detail.get("shipment_id"), "run_id": detail.get("last_run_id"), "workflow_state": state,
            "answered_at": datetime.now(timezone.utc).isoformat(), "offers": offers, "next_step": detail.get("next_step")}
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
            if grounded(candidate, allowed, state == "RESOLVED") and len(candidate) <= 1500 and all(q in quotes for q in picked):
                usable, text, model = True, candidate.strip(), model_label()
                arabic = reply.get("answer_ar") if grounded(reply.get("answer_ar"), allowed, True) and len(str(reply.get("answer_ar"))) <= 2000 else None
                chosen = picked[:4]
                normal = {a.replace("SYN-", "DEMO-", 1): a for a in allowed}
                cited = [normal[e.replace("SYN-", "DEMO-", 1)] for e in reply.get("evidence_ids") or []
                         if isinstance(e, str) and e.replace("SYN-", "DEMO-", 1) in normal][:8]
    if not usable:
        text, arabic, chosen = record_answer(detail, question, quotes)
    retrieved = [n for n in cited if n in evidence_nodes]
    return {**base, "kind": "canopus_answer" if usable else "record_answer", "answer_en": text, "answer_ar": arabic, "evidence_ids": cited,
            "graph_node_ids": retrieved or graph_ids(cited, detail.get("shipment_id"), evidence_nodes), "quotes": [quotes[q] for q in chosen],
            "model": model, "grounded": True if usable else None, "fallback": bool(use_model and not usable), "model_calls": calls}
