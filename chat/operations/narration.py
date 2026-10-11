"""Canopus narration: a read-only account of one investigation, built from what the run already recorded.

The narrator reads a run's stored pipeline events and the case's audit entries and turns them into an append-only list
of narration events of three kinds, which the interface labels differently:

  system_event     written by code from a deterministic record (the monitor's finding, what was retrieved, the proposed
                   catalogue action, the authority decision, an execution receipt, the verifier's result);
  agent_output     the investigator's or the reviewer's own recorded words, quoted, never rewritten;
  canopus_summary  written by the narrator model from the recorded events of one investigator round or one review
                   round (and one wrap-up after a verified outcome).

It has no tools and writes only narration records. Nothing reads narration back: it cannot change a conclusion, an
authority decision, an execution or a state. It is given recorded events only (tool names, arguments, stated purposes,
evidence ids, conclusions, verdicts, feedback), never a prompt, a raw model reply or simulator truth. A summary that
names a record id it was not given, or that says a case is resolved when its recorded state is not RESOLVED, is not
stored; a system_event with `fallback` true takes its place.

Model calls are bounded per run (SUHAIL_NARRATION_MAX_CALLS, default 6; 0 turns the model off and every summary falls
back) and are made on the narrator's own thread after the source events are stored, so an investigation never waits
for narration and never fails because of it.
"""
import json
import logging
import os
import queue
import re
import threading

log = logging.getLogger("suhail.operations")

STAGES = ("extract", "retrieve", "classify", "retrieve_context", "recommend", "review", "writeback", "escalate")
KINDS = ("canopus_summary", "agent_output", "system_event")
PHASES = ("investigation", "review", "authority", "execution", "verification", "reassessment")
MAX_CALLS_ENV = "SUHAIL_NARRATION_MAX_CALLS"
DEFAULT_MAX_CALLS = 6
CALL_DEADLINE_SECONDS = 30
ID_SHAPE = re.compile(r"\b(?:DEMO|SYN)-[A-Z0-9][A-Z0-9-]*[A-Z0-9]\b")
RESOLVED_WORDS = re.compile(r"\bresolv(?:ed|es|ing)\b|\bclosed\b", re.IGNORECASE)

# Audit entries narrated after the pipeline: event type -> (phase, English title, Arabic title, Arabic text, state after or None).
AUDIT_EVENTS = {
    "REVIEWER_DOUBT_RECORDED": ("authority", "Reviewer's doubt kept on record", "تسجيل تحفظ المراجع",
                                "لم يقبل المراجع نتيجة التحقيق وتحفظه مسجل. يُنفَّذ طلب جمع الأدلة فقط، ولا يُعدّ ذلك قبولًا.", None),
    "ACTION_AUTHORIZED": ("authority", "Action authorized by policy", "أجازت السياسة الإجراء",
                          "أجازت سياسة الصلاحيات تنفيذ الإجراء تلقائيًا لأنه آمن وقابل للتراجع.", None),
    "OPERATOR_DECISION": ("authority", "Operator decision recorded", "تسجيل قرار المشغّل", "سُجِّل قرار المشغّل على هذه الحالة.", None),
    "EXECUTION_REFUSED": ("execution", "Execution refused", "رفض التنفيذ", "رفضت سياسة الصلاحيات تنفيذ الإجراء وأُحيلت الحالة إلى شخص.", "HUMAN_REVIEW"),
    "ACTION_EXECUTED": ("execution", "Request sent (simulated)", "إرسال الطلب (محاكاة)",
                        "أُرسل الطلب إلى النظام الميداني المحاكى واستُلم. لا يثبت ذلك زوال المشكلة.", None),
    "ACTION_NOT_ACKNOWLEDGED": ("execution", "Request not delivered (simulated)", "تعذّر تسليم الطلب (محاكاة)",
                                "لم يستلم أي نظام ميداني الطلب، فلا يمكن التحقق من شيء وتبقى الحالة لدى شخص.", "HUMAN_REVIEW"),
    "OUTCOME_VERIFIED": ("verification", "Verified: the problem is cleared", "تم التحقق: زالت المشكلة",
                         "أكد المدقق المستقل من أدلة سُجِّلت بعد الإجراء أن المشكلة زالت.", "RESOLVED"),
    "CASE_RESOLVED": ("verification", "Case resolved", "تمت معالجة الحالة", "أُغلقت الحالة بناءً على أدلة لاحقة تم التحقق منها بشكل مستقل.", "RESOLVED"),
    "OUTCOME_VERIFIED_EXCEPTION_REMAINS": ("verification", "Action worked, problem remains", "نجح الإجراء وبقيت المشكلة",
                                           "تحقق المدقق من نتيجة الإجراء لكن المشكلة ما زالت قائمة، فلم تُغلق الحالة وأُحيلت إلى شخص.", "HUMAN_REVIEW"),
    "OUTCOME_VERIFIED_HUMAN_CLOSURE": ("verification", "Verified; a person must close", "تم التحقق؛ الإغلاق لشخص",
                                       "تحقق المدقق من نتيجة الإجراء، لكن إغلاق هذه الحالة محفوظ لشخص.", "HUMAN_REVIEW"),
    "OUTCOME_VERIFIED_REASSESSMENT": ("reassessment", "Verified; investigation repeated first", "تم التحقق؛ يُعاد التحقيق أولًا",
                                      "تحقق المدقق من نتيجة الإجراء، لكن المراجع لم يكن قد قبل التحقيق، فيُعاد التحقيق والمراجعة على الأدلة الجديدة قبل أي إغلاق.", "OPEN"),
    "OUTCOME_FAILED": ("verification", "Not confirmed: case stays open", "لم يتأكد: الحالة ما زالت مفتوحة",
                       "لم يجد المدقق أدلة لاحقة تؤكد نجاح الإجراء، فبقيت الحالة مفتوحة وأُحيلت إلى شخص.", "HUMAN_REVIEW"),
    "REASSESSMENT_ACCEPTED": ("reassessment", "Reassessment accepted", "قبول إعادة التقييم",
                              "قبل المراجع المستقل التحقيق المعاد على الأدلة الجديدة ولم تبق أي مشكلة.", "RESOLVED"),
    "REASSESSMENT_NOT_ACCEPTED": ("reassessment", "Reassessment not accepted", "عدم قبول إعادة التقييم",
                                  "لم تُغلق الحالة بعد إعادة التقييم وأُحيلت إلى شخص. لم يُنفَّذ أي إجراء من هذه الجولة.", "HUMAN_REVIEW"),
    "REINVESTIGATION_QUEUED": ("investigation", "New evidence: investigating again", "أدلة جديدة: إعادة التحقيق",
                               "ظهرت أدلة أو أعراض جديدة بعد التحقيق، فيُعاد التحقيق في الحالة مع بقاء التحقيق السابق مسجلًا.", "OPEN"),
    "MODEL_DEGRADED": ("investigation", "Model output unusable", "مخرجات النموذج غير صالحة",
                       "لم ينتج النموذج مخرجات صالحة في هذه الجولة، فمُنع التنفيذ التلقائي.", None),
}


def max_calls():
    try:
        return max(0, min(12, int(os.environ.get(MAX_CALLS_ENV, DEFAULT_MAX_CALLS))))
    except ValueError:
        return DEFAULT_MAX_CALLS


def _ids(values, limit=40):
    out = []
    for value in values or []:
        if isinstance(value, str) and value not in out:
            out.append(value)
    return out[:limit]


def _draft(key, stage, phase, kind, text_en, *, title_en, title_ar=None, text_ar=None, iteration=0, evidence=(), sequences=(), audit=(),
           records=(), occurred_at=None, scenario_time=None, outcome_state=None, job=None):
    return {"key": key, "stage": stage, "phase": phase, "kind": kind, "iteration": iteration, "title_en": title_en, "title_ar": title_ar,
            "text_en": text_en, "text_ar": text_ar, "evidence_ids": _ids(evidence), "outcome_state": outcome_state,
            "source": {"pipeline_sequences": list(sequences), "audit_event_types": list(audit), "record_ids": list(records)},
            "occurred_at": occurred_at, "scenario_time": scenario_time, "job": job}


def _by_kind(categories):
    rows = sorted((categories or {}).items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{count} {kind}" for kind, count in rows[:8])


def pipeline_drafts(events):
    """Drafts for a run's recorded pipeline events, in source order. Only completed sources are narrated."""
    drafts, tools = [], []
    for event in events or []:
        out, stage, status = event.get("output") or {}, event.get("stage"), event.get("status")
        seq, iteration = event.get("sequence"), event.get("iteration") or 0
        common = {"iteration": iteration, "occurred_at": event.get("recorded_at"), "scenario_time": event.get("evidence_as_of")}
        if stage == "extract" and status == "COMPLETED":
            symptoms = ", ".join(out.get("symptoms") or []) or "no symptom code"
            drafts.append(_draft(f"p{seq}", stage, "investigation", "system_event",
                                 f"The monitor opened this case for shipment {out.get('shipment_id')} because it observed: {symptoms}. "
                                 f"The investigation reads the evidence recorded up to {out.get('as_of')}.",
                                 title_en="Why this case exists", title_ar="سبب فتح الحالة",
                                 text_ar=f"فتح نظام المراقبة هذه الحالة للشحنة {out.get('shipment_id')} لأنه رصد: {symptoms}. يقرأ التحقيق الأدلة المسجلة حتى {out.get('as_of')}.",
                                 evidence=out.get("evidence_ids"), sequences=[seq], **common))
        elif stage == "retrieve" and status == "COMPLETED":
            kinds = _by_kind(out.get("categories"))
            drafts.append(_draft(f"p{seq}", stage, "investigation", "system_event",
                                 f"Read {out.get('nodes')} records and {out.get('relationships')} relationships for this shipment from the knowledge graph"
                                 + (f" ({kinds})." if kinds else "."),
                                 title_en="Evidence retrieved from the graph", title_ar="استرجاع الأدلة من الرسم المعرفي",
                                 text_ar=f"قُرئ {out.get('nodes')} سجلًا و{out.get('relationships')} علاقة لهذه الشحنة من الرسم المعرفي.",
                                 evidence=out.get("evidence_ids"), sequences=[seq], **common))
        elif stage == "classify" and status == "RUNNING" and out.get("kind") == "tool_call":
            tools.append(event)
            drafts.append(_draft(f"p{seq}", stage, "investigation", "agent_output", str(out.get("purpose") or "").strip() or f"Called {out.get('tool')}.",
                                 title_en=f"Investigator checks: {out.get('tool')}", evidence=out.get("evidence_ids"), sequences=[seq], **common))
        elif stage == "classify" and status == "COMPLETED":
            investigation = dict(out.get("investigation") or {})
            # The recorded stage event names the conclusion `primary_hypothesis`; the stored run names it `primary_cause`.
            leading = next((d.get("code") for d in out.get("diagnoses") or [] if d.get("status") == "supported"), None)
            investigation.setdefault("primary_cause", investigation.get("primary_hypothesis") or leading)
            calls = [{"tool": (t.get("output") or {}).get("tool"), "arguments": (t.get("output") or {}).get("args"),
                      "purpose": (t.get("output") or {}).get("purpose"), "records_returned": len((t.get("output") or {}).get("evidence_ids") or []),
                      "evidence_ids": _ids((t.get("output") or {}).get("evidence_ids"), 6)} for t in tools]
            sequences = [t.get("sequence") for t in tools] + [seq]
            conclusion = {"primary_cause": investigation.get("primary_cause"), "confidence": investigation.get("confidence"),
                          "summary": investigation.get("summary"), "missing_evidence": investigation.get("missing_evidence"),
                          "hypotheses": [{"cause": h.get("cause") or h.get("code"), "status": h.get("status"), "assessment": h.get("assessment"),
                                          "supporting_evidence_ids": _ids(h.get("supporting_evidence_ids"), 8)} for h in investigation.get("hypotheses") or []],
                          "recommended_action": investigation.get("recommended_action")}
            degraded = bool(investigation.get("degraded"))
            fallback = ((f"The investigator made {len(calls)} tool call(s) ({', '.join(str(c['tool']) for c in calls[:8])})" if calls
                         else "The investigator revised its conclusion from the evidence already retrieved, without new tool calls,")
                        + (". It did not reach a usable conclusion in this round." if degraded or not investigation.get("primary_cause")
                           else f" and concluded {investigation.get('primary_cause')} with {investigation.get('confidence')} confidence. "
                                "This is a hypothesis until the independent review."))
            drafts.append(_draft(f"p{seq}s", stage, "investigation", "canopus_summary", fallback,
                                 title_en="What the investigator did" if not iteration else "What the investigator changed", evidence=out.get("evidence_ids"),
                                 sequences=sequences, job={"task": "investigation_round", "round": iteration, "tool_calls": calls, "conclusion": conclusion,
                                                           "degraded": degraded}, **common))
            if investigation.get("summary"):
                drafts.append(_draft(f"p{seq}a", stage, "investigation", "agent_output", str(investigation["summary"]),
                                     title_en="Investigator's conclusion (not yet reviewed)", evidence=out.get("evidence_ids"), sequences=[seq], **common))
            tools = []
        elif stage == "retrieve_context" and status == "COMPLETED":
            count = out.get("verified_precedents") or 0
            drafts.append(_draft(f"p{seq}", stage, "investigation", "system_event",
                                 f"Looked up verified earlier outcomes for the same kind of problem: {count} found. Only independently verified outcomes are used as precedents.",
                                 title_en="Verified precedents", title_ar="السوابق المتحقق منها",
                                 text_ar=f"بُحث عن نتائج سابقة متحقق منها لمشكلات من النوع نفسه: وُجد {count}. تُستخدم فقط النتائج المتحقق منها بشكل مستقل.",
                                 evidence=out.get("evidence_ids"), sequences=[seq], **common))
        elif stage == "recommend" and status == "COMPLETED" and out.get("proposal"):
            proposal = out["proposal"]
            drafts.append(_draft(f"p{seq}", stage, "investigation", "system_event",
                                 f"Proposed action from the catalogue: {proposal.get('action_type')} ({proposal.get('action_en') or proposal.get('action')}) "
                                 "It is a proposal only: the review and the authority policy decide whether anything runs.",
                                 title_en="Proposed action", title_ar="الإجراء المقترح",
                                 text_ar=f"الإجراء المقترح من القائمة المعتمدة: {proposal.get('action_type')} ({proposal.get('action_ar') or ''}) هذا مقترح فقط، والمراجعة وسياسة الصلاحيات تقرران ما يُنفَّذ.",
                                 evidence=out.get("evidence_ids"), sequences=[seq], **common))
        elif stage == "review" and status not in ("RUNNING", "RETRYING") and out.get("verdict"):
            review = out.get("model_review") or {}
            verdict = out.get("model_verdict") or out.get("verdict")
            citations = out.get("citation_validity") or {}
            job = {"task": "review_round", "round": iteration, "verdict": verdict, "accepted": out.get("verdict") == "accept" and verdict == "ACCEPT",
                   "feedback": out.get("feedback"), "unsupported_claims": review.get("unsupported_claims"),
                   "unaddressed_contradictions": review.get("unaddressed_contradictions"),
                   "citations": {"cited": citations.get("cited"), "valid": citations.get("valid"), "invalid_ids": citations.get("invalid_ids")},
                   "fact_checks": [{"check": c.get("check"), "passed": c.get("passed"), "detail": c.get("detail")} for c in out.get("fact_checks") or []][:8]}
            fallback = (f"The independent reviewer's verdict is {verdict}. " + ("It accepted the investigation." if job["accepted"]
                        else "This is not an acceptance; its objection is recorded below."))
            drafts.append(_draft(f"p{seq}s", stage, "review", "canopus_summary", fallback, title_en="What the reviewer decided", evidence=out.get("evidence_ids"),
                                 sequences=[seq], job=job, **common))
            if out.get("feedback"):
                drafts.append(_draft(f"p{seq}a", stage, "review", "agent_output", str(out["feedback"]), title_en=f"Reviewer's own words ({verdict})",
                                     evidence=out.get("evidence_ids"), sequences=[seq], **common))
        elif stage in ("writeback", "escalate") and status == "COMPLETED" and out.get("authority"):
            authority = out["authority"]
            state = out.get("workflow_state")
            drafts.append(_draft(f"p{seq}", stage, "authority", "system_event",
                                 f"Authority decision for {authority.get('action_type') or 'no action'}: {authority.get('risk_class')} under rule {authority.get('rule_id')}. "
                                 f"{authority.get('reason')} The case is now {state}. Nothing here is a verified outcome.",
                                 title_en="Who may act", title_ar="من يملك صلاحية التنفيذ",
                                 text_ar=f"قرار الصلاحية للإجراء {authority.get('action_type') or '—'}: {authority.get('risk_class')} وفق القاعدة {authority.get('rule_id')}. حالة الملف الآن {state}. لا يُعدّ ذلك نتيجة متحققًا منها.",
                                 sequences=[seq], outcome_state=state, **common))
    return drafts


def audit_drafts(audits):
    """Drafts for the case's audit entries that follow the pipeline (authorization, execution, verification), oldest first."""
    drafts = []
    for entry in audits or []:
        spec = AUDIT_EVENTS.get(entry.get("event_type"))
        if not spec:
            continue
        phase, title_en, title_ar, text_ar, state = spec
        text = str(entry.get("result") or "").strip() or title_en + "."
        drafts.append(_draft("a" + str(entry.get("entity_id")), "writeback", phase, "system_event", text, title_en=title_en, title_ar=title_ar, text_ar=text_ar,
                             audit=[entry.get("event_type")], records=[entry.get("entity_id")], occurred_at=entry.get("wall_recorded_at"),
                             scenario_time=entry.get("occurred_at"), outcome_state=state))
    return drafts


def wrap_up_draft(audits, investigation, review, case_state):
    """One summary after the last verification entry: the conclusion, the action and what the verifier found."""
    final = [a for a in audits or [] if a.get("event_type") in ("OUTCOME_VERIFIED", "OUTCOME_VERIFIED_EXCEPTION_REMAINS", "OUTCOME_VERIFIED_HUMAN_CLOSURE",
                                                              "OUTCOME_VERIFIED_REASSESSMENT", "OUTCOME_FAILED", "REASSESSMENT_ACCEPTED",
                                                              "REASSESSMENT_NOT_ACCEPTED", "ACTION_NOT_ACKNOWLEDGED")]
    if not final:
        return None
    last = final[-1]
    trail = [{"event": a.get("event_type"), "text": a.get("result")} for a in audits if a.get("event_type") in AUDIT_EVENTS][-8:]
    state = "RESOLVED" if case_state == "RESOLVED" else case_state
    fallback = (f"After the action, the case is {state}. " + ("The verifier confirmed from later evidence that the problem is cleared." if state == "RESOLVED"
                else "It is not resolved: a person takes it from here."))
    return _draft("w" + str(last.get("entity_id")), "writeback", "verification", "canopus_summary", fallback, title_en="Where the case stands",
                  audit=[a["event"] for a in trail], records=[last.get("entity_id")], occurred_at=last.get("wall_recorded_at"),
                  scenario_time=last.get("occurred_at"), outcome_state=state,
                  job={"task": "wrap_up", "case_state": state, "investigator_conclusion": {k: (investigation or {}).get(k) for k in ("primary_cause", "confidence", "summary")},
                       "reviewer_verdict": (review or {}).get("model_verdict") or (review or {}).get("verdict"), "recorded_trail": trail})


SYSTEM_PROMPT = (
    "You are Canopus, the narrator of a logistics exception investigation system. You are given the RECORDED events of one step of one "
    "investigation as JSON. Explain it to an operations operator in plain English, in 2 to 4 short sentences: what was checked, what was "
    "found, and why it matters for the next step. Rules: use only facts in the JSON; do not add a cause, an outcome, a number or a record id "
    "that is not there; mention at most three record ids and copy them exactly with plain hyphens; a hypothesis is not a fact, so say "
    "'the investigator concluded' in an investigation_round (when round is 0 the reviewer has not acted yet, do not mention it) and 'the reviewer found' "
    "in a review_round; never say the case is resolved, fixed or closed unless case_state is exactly RESOLVED; do not "
    "describe your own reasoning. Reply with JSON only: {\"title_en\": up to 8 words, \"text_en\": the explanation, \"text_ar\": the same "
    "explanation in Modern Standard Arabic}.")


def grounded(text, allowed_ids, resolved):
    """True when the text names only ids it was given and does not claim a resolution the record does not show."""
    if not isinstance(text, str) or not text.strip():
        return False
    allowed = {i.replace("SYN-", "DEMO-", 1) for i in allowed_ids}
    if any(found.replace("SYN-", "DEMO-", 1) not in allowed for found in ID_SHAPE.findall(text)):
        return False
    return resolved or not RESOLVED_WORDS.search(text.replace("unresolved", "").replace("not resolved", "").replace("not closed", ""))


def plain_hyphens(value):
    """A model often writes ids with typographic hyphens; they are put back so an id is checked and can be linked."""
    return value.replace("\u2011", "-").replace("\u2010", "-") if isinstance(value, str) else value


def summarize(draft, ask):
    """The model's summary for a draft with a job, or None when it is unusable. ask(system, user) -> dict."""
    job = draft["job"]
    payload = json.dumps(job, ensure_ascii=False, sort_keys=True, default=str)
    reply = ask(SYSTEM_PROMPT, payload)
    if not isinstance(reply, dict):
        return None
    reply = {key: plain_hyphens(value) for key, value in reply.items()}
    # In the first investigation round only the investigator has acted: a summary that credits the reviewer there
    # misattributes. A later round answers the reviewer's objection, so it may name the reviewer.
    if job.get("task") == "investigation_round" and not job.get("round") and re.search(r"\breviewer\b", str(reply.get("text_en") or ""), re.IGNORECASE):
        return None
    allowed = set(ID_SHAPE.findall(payload))
    resolved = job.get("case_state") == "RESOLVED"
    text = reply.get("text_en")
    if not grounded(text, allowed, resolved) or len(text) > 1200:
        return None
    arabic = reply.get("text_ar") if grounded(reply.get("text_ar"), allowed, True) and len(str(reply.get("text_ar"))) <= 1500 else None
    title = reply.get("title_en") if isinstance(reply.get("title_en"), str) and 0 < len(reply["title_en"]) <= 80 and grounded(reply["title_en"], allowed, resolved) else None
    return {"text_en": text.strip(), "text_ar": arabic.strip() if arabic else None, "title_en": title or draft["title_en"]}


def graph_ids(evidence_ids, shipment_id, retrieved):
    """The cited ids that are nodes of the case's evidence graph: the shipment's own records and the records the
    retrieve stage read. Tool computations and shared records outside the shipment are not graph nodes."""
    retrieved = set(retrieved or [])
    return [i for i in evidence_ids if "-CMP-" not in i and (i == shipment_id or i.startswith(str(shipment_id) + "-") or i in retrieved)]


def provider_ask(system, user):
    from llm.pipeline import _llm
    # The default is the reply's schema: ask_json keeps only these keys, as strings.
    return _llm.ask_json(system, user, {"title_en": None, "text_en": None, "text_ar": None}, deadline=CALL_DEADLINE_SECONDS)


def model_label():
    try:
        import config
        return str(config.LLM_MODEL).split("/", 1)[-1]
    except Exception:  # noqa: BLE001
        return "model"


class Narrator:
    """Builds and stores the narration of cases on its own thread. `store` supplies narration_sources(case_id) and
    narration_append(case_id, run_id, events); nothing else of the store is used."""

    def __init__(self, store, ask=None, limit=None, threaded=True):
        self.store, self.ask, self.limit = store, ask, limit
        self.pending = queue.Queue()
        self.queued = set()
        self.lock = threading.Lock()
        self.thread = None
        if threaded:
            self.thread = threading.Thread(target=self._loop, name="suhail-narrator", daemon=True)
            self.thread.start()

    def request(self, case_id):
        """Ask for a case's narration to be brought up to date (returns at once)."""
        if not case_id:
            return
        with self.lock:
            if case_id in self.queued:
                return
            self.queued.add(case_id)
        self.pending.put(case_id)

    def _loop(self):
        while True:
            case_id = self.pending.get()
            with self.lock:
                self.queued.discard(case_id)
            try:
                self.sync(case_id)
            except Exception as error:  # noqa: BLE001  Narration never takes anything else down.
                log.warning("Narration of %s failed: %s", case_id, type(error).__name__)

    def sync(self, case_id):
        """Store every narration event whose source is recorded and that is not stored yet, in source order."""
        sources = self.store.narration_sources(case_id)
        if not sources or not sources.get("run_id"):
            return []
        existing = set(sources["existing_keys"])
        drafts = pipeline_drafts(sources["pipeline_events"]) + audit_drafts(sources["audits"])
        wrap = wrap_up_draft(sources["audits"], sources.get("investigation"), sources.get("review"), sources["case"]["workflow_state"])
        if wrap:
            drafts.append(wrap)
        retrieved = next((e.get("output", {}).get("evidence_ids") for e in sources["pipeline_events"]
                          if e.get("stage") == "retrieve" and e.get("status") == "COMPLETED"), [])
        calls, limit, stored = sources["model_calls"], max_calls() if self.limit is None else self.limit, []
        for draft in drafts:
            if draft["key"] in existing:
                continue
            event = {k: v for k, v in draft.items() if k != "job"}
            event.update(model=None, grounded=None, fallback=False)
            if draft["kind"] == "canopus_summary":
                summary = None
                if calls < limit:
                    calls += 1
                    try:
                        summary = summarize(draft, self.ask or provider_ask)
                    except Exception as error:  # noqa: BLE001  Provider failure, timeout or invalid reply: the record-based text stands.
                        log.info("Narrator call failed (%s); using the recorded text", type(error).__name__)
                    event["model_call"] = True
                if summary:
                    event.update(summary, model=model_label(), grounded=True)
                else:
                    event.update(kind="system_event", fallback=True)
            event["graph_node_ids"] = graph_ids(event["evidence_ids"], sources["case"]["shipment_id"], retrieved)
            stored += self.store.narration_append(case_id, sources["run_id"], [event])
            existing.add(draft["key"])
        return stored
