"""GPT-OSS investigation agent: an iterative tool loop over the shipment's Neo4j evidence.

The model decides which evidence to retrieve next, forms and revises competing hypotheses, and
concludes with supported, refuted or uncertain explanations, each citing only evidence ids that
its own tool calls returned. Deterministic code owns the loop bounds, tool access (time-correct,
shipment-scoped, read-only), schema validation and the safety checks; it never proposes a cause.
An independent reviewer then re-checks the conclusion against the cited records themselves.

Failure handling is fail-closed: a provider error, timeout or invalid output that survives one
corrective retry ends the investigation as DEGRADED, with no substituted diagnosis.
No chain-of-thought is requested, stored or returned; only declared output fields are kept.
"""
import json

from operations.agents import BLAME, CAUSES, GPS_DELIVERY, VERDICTS
from operations.authority import ACTIONS

MAX_TOOL_CALLS = 10
MAX_TURNS = 14
ATTEMPTS_PER_TURN = 2
CAUSE_CHOICES = (*CAUSES, "UNKNOWN")

SYSTEM = """You are Suhail's investigation agent for a synthetic logistics operation (synthetic data, not SPL production).
A monitor opened this case from observable symptoms. Find out what actually happened to the shipment.

Work iteratively: call one tool at a time, read its result, and decide what to examine next. Form
competing hypotheses early, look for evidence that would distinguish or contradict them, and check
verified precedents for your leading hypothesis before concluding.

Typical alternative explanations to weigh (do not assume any of them):
- For a missing or late observation: whether the parcel moved, whether it was scanned, and whether the
  record has reached Suhail yet.
- For a failed or disputed delivery: address or access problems, an unreachable recipient, proof that does
  not bind to the recipient, or a handover to someone else.
- For custody that does not reconcile: who last held the parcel with corroboration, and whether any later
  evidence (scans, attempts, returns, manifests) shows where it went.
Before concluding, retrieve at least one piece of evidence that could distinguish your leading hypothesis
from its closest alternative.

Rules:
- Cite only ids listed under CITABLE_EVIDENCE_IDS in the tool results you received.
- Tools only read evidence. Actions (action types) are never tools: you recommend one in your conclusion.
- Vehicle GPS is a vehicle position, never a parcel location or delivery proof.
- A driver assignment or manifest entry is not physical custody; custody needs a corroborated transfer.
- A missing scan is not proof of loss. A late upload (recorded long after it occurred) is a data delay.
- Never attribute blame, fraud or negligence to any person or company.
- Do not invent numbers, times, attempts or records. Say what is missing instead.

Respond with exactly one JSON object and nothing else, either:
{"action":"call","tool":"<tool name>","args":{...},"purpose":"<one short sentence>"}
or, when the evidence supports a conclusion (or you must stop):
{"action":"conclude","hypotheses":[{"cause":"<cause code>","status":"supported|refuted|uncertain",
  "supporting_evidence_ids":[...],"contradicting_evidence_ids":[...],"assessment":"<one or two sentences>"}],
 "primary_cause":"<cause code>","confidence":"low|medium|high","missing_evidence":["..."],
 "recommended_action":"<action type>","requires_physical_check":true|false,"summary":"<two or three sentences>"}
"""


def failure_mode(error):
    """How a model role failed: the provider call itself, or output that never passed validation."""
    return "model_unavailable" if str(error or "").startswith("model call failed") else "invalid_model_output"


def _sanitize(text, limit=400):
    return str(text or "")[:limit]


def _ids_in(record):
    return {x for x in (record or {}).get("supporting_evidence_ids", []) + (record or {}).get("contradicting_evidence_ids", []) if isinstance(x, str)}


def validate_conclusion(out, retrieved):
    """Schema and safety. Returns an error string for the model to correct, or None."""
    hypotheses = out.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        return "hypotheses must be a non-empty list"
    if out.get("primary_cause") not in CAUSE_CHOICES:
        return "primary_cause must be one of the cause codes"
    if out.get("confidence") not in ("low", "medium", "high"):
        return "confidence must be low|medium|high"
    action = out.get("recommended_action")
    if action not in ACTIONS:
        return "recommended_action must be one of the action types"
    if ACTIONS[action][0] == "PROHIBITED":
        return "Prohibited actions (money, liability, blame) cannot be recommended"
    primary = None
    for h in hypotheses:
        if not isinstance(h, dict) or h.get("cause") not in CAUSE_CHOICES or h.get("status") not in ("supported", "refuted", "uncertain"):
            return "each hypothesis needs a cause code and status supported|refuted|uncertain"
        unknown = sorted(_ids_in(h) - retrieved)
        if unknown:
            return "cited evidence ids were not returned by your tools: " + ", ".join(unknown[:4])
        if h["cause"] == out["primary_cause"]:
            primary = h
    if out["primary_cause"] != "UNKNOWN":
        if primary is None or primary["status"] != "supported" or not primary.get("supporting_evidence_ids"):
            return "the primary cause must be a supported hypothesis that cites supporting evidence"
    texts = [out.get("summary", ""), *[h.get("assessment", "") for h in hypotheses], *map(str, out.get("missing_evidence") or [])]
    for text in texts:
        if BLAME.search(text or ""):
            return "output attributes blame or wrongdoing to a person"
        if GPS_DELIVERY.search(text or ""):
            return "output treats vehicle GPS as parcel delivery or location evidence"
    return None


def _clean_conclusion(out):
    keep = ("cause", "status", "supporting_evidence_ids", "contradicting_evidence_ids", "assessment")
    return {"hypotheses": [{k: (_sanitize(h.get(k)) if k == "assessment" else h.get(k)) for k in keep} for h in out["hypotheses"]][:6],
            "primary_cause": out["primary_cause"], "confidence": out["confidence"],
            "missing_evidence": [_sanitize(x, 200) for x in (out.get("missing_evidence") or [])][:6],
            "recommended_action": out["recommended_action"], "requires_physical_check": bool(out.get("requires_physical_check")),
            "summary": _sanitize(out.get("summary"), 600)}


def model_turn(messages):
    """One provider call; returns the parsed JSON object or None. Raises on transport errors."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from llm.pipeline import _llm
    wire = [SystemMessage(messages[0]["content"])] + [
        (AIMessage if m["role"] == "assistant" else HumanMessage)(m["content"]) for m in messages[1:]]
    response = _llm.model().invoke(wire)
    return _llm.parse_json(_llm.message_text(getattr(response, "content", None)))


def investigate(tools, *, turn=None, on_step=None, feedback=None):
    """Run the bounded tool loop. Returns a result dict; never raises for model failures."""
    turn = turn or model_turn
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps({
                    "case": {"shipment_id": tools.sid, "as_of": tools.as_of, "symptoms": tools.symptoms},
                    "tools": tools.describe(), "cause_codes": list(CAUSE_CHOICES),
                    "action_types": {k: {"authority": v[0], "addresses": sorted(v[1]), "summary": v[3]} for k, v in ACTIONS.items()},
                    "limits": {"max_tool_calls": MAX_TOOL_CALLS},
                    **({"reviewer_feedback": feedback} if feedback else {})}, ensure_ascii=False)}]
    steps, error = [], None
    for _ in range(MAX_TURNS):
        out, problem = None, None
        for _attempt in range(ATTEMPTS_PER_TURN):
            try:
                out = turn(messages + ([{"role": "user", "content": f"Your previous reply was rejected: {problem}. Reply with one corrected JSON object."}] if problem else []))
            except Exception as exc:  # Transport/provider failure: type only.
                problem, out = f"model call failed ({type(exc).__name__})", None
                continue
            if not isinstance(out, dict) or out.get("action") not in ("call", "conclude"):
                problem, out = "reply must be one JSON object with action call or conclude", None
                continue
            if out["action"] == "call" and (out.get("tool") not in tools.CATALOG):
                problem, out = f"unknown tool {out.get('tool')}", None
                continue
            if out["action"] == "call" and len(tools.calls) >= MAX_TOOL_CALLS:
                problem, out = "tool budget exhausted; conclude now with what you have", None
                continue
            if out["action"] == "conclude":
                problem = validate_conclusion(out, tools.retrieved)
                if problem:
                    out = None
                    continue
            break
        if out is None:
            error = problem
            break
        if out["action"] == "call":
            purpose = _sanitize(out.get("purpose"), 160)
            if BLAME.search(purpose) or GPS_DELIVERY.search(purpose):
                purpose = ""
            result = tools.call(out["tool"], out.get("args") or {})
            step = {"tool": out["tool"], "args": tools.calls[-1]["args"], "purpose": purpose, "evidence_ids": result["evidence_ids"]}
            steps.append(step)
            if on_step:
                on_step(step)
            messages.append({"role": "assistant", "content": json.dumps({k: out.get(k) for k in ("action", "tool", "args", "purpose")}, ensure_ascii=False)})
            messages.append({"role": "user", "content": f"TOOL RESULT {out['tool']}: {result['result']}"})
            continue
        conclusion = _clean_conclusion(out)
        return {"mode": "gpt-oss", "degraded": False, "steps": steps, "retrieved_evidence_ids": sorted(tools.retrieved),
                "validation_error": None, **conclusion}
    # A provider failure is "model_unavailable"; a model that answered but never produced a valid conclusion (schema,
    # citation, blame or GPS violations that survived the corrective retry, or the turn budget) is "invalid_model_output".
    return {"mode": failure_mode(error), "degraded": True, "steps": steps, "retrieved_evidence_ids": sorted(tools.retrieved),
            "validation_error": error or "turn budget exhausted without a valid conclusion", "hypotheses": [],
            "primary_cause": None, "confidence": None, "missing_evidence": [], "recommended_action": None,
            "requires_physical_check": True, "summary": "Investigation could not reach a valid conclusion; no AI diagnosis was produced."}


REVIEWER_SYSTEM = """You are Suhail's independent reviewer for a synthetic logistics operation. You did not run the
investigation. Check the investigator's conclusion against the cited evidence records below (these are the
actual records, not the investigator's description) and the deterministic fact checks.

Decide:
- ACCEPT: the primary cause is supported by the cited records, contradictions were considered, and the
  recommended action addresses that cause within policy.
- REVISE: a specific claim is not supported, evidence is misread, or an obvious alternative was ignored.
  Say exactly what to re-examine.
- HUMAN_REVIEW: the evidence is genuinely ambiguous, disputed or needs a physical check.
- ESCALATE: the conclusion or action could cause harm (blame, money, unsafe change).
Vehicle GPS never proves parcel location. Never blame a person.
Respond with exactly one JSON object: {"verdict":"ACCEPT|REVISE|HUMAN_REVIEW|ESCALATE","feedback":"<one to three sentences>",
"unsupported_claims":["..."]}"""


def review(conclusion, records, checks, symptoms, *, ask=None):
    """Independent review; a failed reviewer is UNAVAILABLE (fail closed), never ACCEPT."""
    from operations.agents import _ask
    ask = ask or _review_call
    packet = {"case_symptoms": symptoms, "investigator_conclusion": {k: conclusion.get(k) for k in
              ("hypotheses", "primary_cause", "confidence", "missing_evidence", "recommended_action", "requires_physical_check", "summary")},
              "cited_records": records, "deterministic_checks": checks, "visible_evidence_ids": sorted(records)}
    default = {"verdict": "", "feedback": "", "unsupported_claims": []}
    def validate(out):
        if out.get("verdict") not in VERDICTS:
            return "verdict must be ACCEPT|REVISE|HUMAN_REVIEW|ESCALATE"
        if not isinstance(out.get("feedback"), str) or not isinstance(out.get("unsupported_claims") or [], list):
            return "feedback must be text and unsupported_claims a list"
        if BLAME.search(out.get("feedback") or "") or GPS_DELIVERY.search(out.get("feedback") or ""):
            return "feedback attributes blame or misuses GPS"
        return None
    out, mode, error = _ask(REVIEWER_SYSTEM, packet, {}, default, validate, ask)
    if out is None:
        # Still UNAVAILABLE for authority (fail closed); the mode says whether the call failed or its output was invalid.
        return {"verdict": "UNAVAILABLE", "feedback": "Independent model review could not be completed.", "unsupported_claims": [],
                "mode": failure_mode(error), "degraded": True, "validation_error": error}
    return {"verdict": out["verdict"], "feedback": _sanitize(out["feedback"], 500),
            "unsupported_claims": [_sanitize(x, 200) for x in out.get("unsupported_claims") or []][:6],
            "mode": mode, "degraded": False, "validation_error": None}


def _review_call(system, user, default):
    from llm.pipeline._llm import ask_json
    return ask_json(system, user, default)
