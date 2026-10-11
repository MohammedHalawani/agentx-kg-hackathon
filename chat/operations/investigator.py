"""GPT-OSS investigation agent: an iterative tool loop over the shipment's Neo4j evidence.

The model decides which evidence to retrieve next, forms and revises competing hypotheses, and
concludes with supported, refuted or uncertain explanations, each citing only evidence ids that
its own tool calls returned. Deterministic code owns the loop bounds, tool access (time-correct,
dataset-scoped, read-only), schema validation and the safety checks; it never proposes a cause.
An independent reviewer then re-checks the conclusion against the cited records themselves, the
tool-computed results the investigator saw and the evidence it retrieved but did not cite.

One investigation of a case (its first round, any revision round and every retry) shares one
conversation, one tool belt and one model-call budget (Session). A rejected reply on a tool-call
turn is corrected and the investigation continues; the investigation fails closed (DEGRADED, no
substituted diagnosis) only on a repeated provider failure, on a final conclusion that is still
invalid after its corrective retry, or when the model-call cap is reached without a conclusion.
INSUFFICIENT_EVIDENCE is a valid conclusion when it names what is missing and a next
evidence-gathering step. No chain-of-thought is requested, stored or returned; only declared
output fields are kept.
"""
import json
import os

from operations.agents import BLAME, CAUSES, GPS_DELIVERY, VERDICTS
from operations.authority import ACTIONS, EVIDENCE_GATHERING

MAX_TOOL_CALLS = 10          # per investigation round
MAX_TURNS = 14               # model turns per investigation round
ATTEMPTS_PER_TURN = 2        # a provider failure, or an invalid conclusion, gets one retry
DEFAULT_MODEL_CALL_CAP = 12  # investigator turns, reviewer calls, revision rounds and retries of one case investigation
MODEL_CALL_CAP_ENV = "SUHAIL_MODEL_CALL_CAP"
RESERVED_FOR_REVIEW = 1      # the investigator always leaves one call for the independent review
ABSTENTION = "INSUFFICIENT_EVIDENCE"
CAUSE_CHOICES = (*CAUSES, "UNKNOWN")   # UNKNOWN is accepted as an older spelling of INSUFFICIENT_EVIDENCE
# What an INSUFFICIENT_EVIDENCE conclusion may recommend: a request that gathers evidence, or a person's check or review.
NEXT_STEP_ACTIONS = frozenset(EVIDENCE_GATHERING | {name for name, entry in ACTIONS.items() if entry[0] == "HUMAN_REVIEW"})
REVIEW_VERDICTS = (*VERDICTS, "INSUFFICIENT_EVIDENCE")

# One-line operational definitions. An observation says what is wrong in the records; a mechanism says why.
# Each entry names the kind of evidence that would support or refute it. Definitions, not decision rules.
CAUSE_CATALOGUE = {
    "observations": {
        "MISSED_MILESTONE": ("An expected step of the journey has no corroborated record after its deadline.",
                             "the journey shows the step missing after its deadline",
                             "a corroborated record of the step exists, on time or uploaded late"),
        "JOURNEY_DELAY": ("An expected step was recorded, but later than its deadline.",
                          "the journey shows the step observed late", "the step was observed within its deadline"),
        "CUSTODY_GAP": ("A handling step or handover is missing from, or inconsistent in, the custody record itself: it was never "
                        "recorded, as opposed to recorded and uploaded late.",
                        "a transfer without full acknowledgments or without a scan of the parcel; a transfer that starts from someone other "
                        "than the last corroborated holder; a parcel planned for a movement with no confirmation that it joined it",
                        "every transfer is corroborated and follows the previous holder; the missing record later arrives as a late upload"),
        "UNRECONCILED_CUSTODY": ("A delivery session ended, with its grace period, and the parcel is neither delivered with valid proof nor "
                                 "recorded back at the depot.",
                                 "the session's reconciliation state after its end; no return scan, proof or reconciliation of the parcel; what "
                                 "the route run's other parcels and its driver app show",
                                 "a reconciliation record, a corroborated delivery or a return scan of the parcel"),
        "CONFLICTING_CUSTODY": ("Independent records name incompatible holders of the parcel for the same time.",
                                "two custody records from different sources naming different holders",
                                "a single consistent chain of holders"),
        "MANIFEST_CONFLICT": ("The dispatch manifest and the confirmed loading disagree about a parcel.",
                              "the latest manifest version omitting a parcel whose loading was confirmed; the manifest's versions",
                              "the latest manifest lists every parcel whose loading was confirmed"),
        "BARCODE_MISMATCH": ("A readable, confident scan returned a barcode other than the parcel's manifest barcode.",
                             "the barcode comparison; whose label the read barcode is; whether other reads of the parcel match; how the "
                             "same reader read other parcels", "every confident read matches the manifest barcode"),
        "WEIGHT_MISMATCH": ("A calibrated weighing differs from the declared weight by more than the policy tolerance.",
                            "the weight comparison; other weighings of the parcel; how the same scale weighed other parcels",
                            "every calibrated weighing is within tolerance of the declaration"),
        "PROOF_INSUFFICIENT": ("A delivery could not be verified as required: the one-time code was not delivered or not confirmed, or the "
                               "recorded proof lacks a component that binds it to the consignee.",
                               "the proof's corroboration check and its reasons; the code check's result; delivery status of the code "
                               "messages", "a proof whose every component binds to the consignee or an authorised alternate"),
        "DELIVERY_DISPUTE": ("Whether the consignee received the parcel is contested or open to contest: the recipient reports non-receipt, "
                             "or the recorded handover was to another person.",
                             "a recipient report; who the handoff record names and whether an authorisation is on record",
                             "a handover to the consignee with corroborated proof and no report against it"),
        "SLA_RISK": ("The remaining journey is unlikely to meet the service promise, with no fault established.",
                     "the promise time against the steps still pending", "the remaining steps fit before the promise"),
    },
    "mechanisms": {
        "DELAYED_SYNC": ("The step happened and was recorded on a device, but the record had not reached Suhail, or reached it late, "
                         "because the device was offline or its uploads were stuck.",
                         "records made through that device arriving long after they occurred; its heartbeats stopping at hours when it "
                         "normally reports, or reporting pending uploads; other parcels' records from the same device delayed in the same period",
                         "the device kept reporting with nothing pending and its other records from the period arrived promptly; the device "
                         "class has no telemetry stream, so its silence shows nothing"),
        "HUB_DELAY": ("The parcel was held up inside a facility: a processing backlog, a missed cutoff, or handling at a facility it "
                      "should not have gone to.",
                      "the facility's throughput (queue, long waits) in those hours; other shipments overdue at that facility; scans of the "
                      "parcel at a facility outside its plan", "throughput was normal there and the parcel was never recorded at an unplanned facility"),
        "ROUTE_DELAY": ("The transport leg or delivery route carrying the parcel ran late or did not reach the stop: a trip held, delayed "
                        "or stopped, or a route that ran out of time.",
                        "carrier status messages, departure and arrival against the schedule, vehicle positions, stops recorded as not "
                        "attempted, the other parcels of the same trip or route", "the trip or route ran to schedule and its other parcels arrived"),
        "TRAFFIC_DELAY": ("A reported road incident or closure kept the vehicle from reaching the stop in time.",
                          "a traffic incident whose area and time cover the address and the attempt window; stops there not attempted",
                          "no incident near the address at that time"),
        "RECIPIENT_UNAVAILABLE": ("A delivery attempt failed because nobody could receive the parcel at the address.",
                                  "a failed attempt with a not-reached reason and unanswered calls",
                                  "the attempt failed for another recorded reason, or no attempt was made"),
        "ADDRESS_CONFLICT": ("The attempt used an address that is wrong or out of date for the recipient.",
                             "a dated address correction or address report from the recipient; an attempt on a superseded address "
                             "version; an address-not-found reason", "one valid address version, and the attempt was made at it"),
        "WRONG_GATE": ("The driver went to a gate or entrance other than the one the delivery instruction names.",
                       "the attempt's recorded gate compared with the instruction", "the recorded gate is the instructed one, or no gate was recorded"),
        "POSSIBLE_MISDELIVERY": ("The parcel was left or handed over at a place other than the consignee's address.",
                                 "the proof or photo location away from the address by more than the location uncertainty; a non-receipt report",
                                 "the proof location is at the address within its uncertainty"),
    },
    "abstention": {
        "INSUFFICIENT_EVIDENCE": ("The evidence available at this time does not establish any cause.",
                                  "the records that would distinguish the remaining explanations are missing or have not arrived",
                                  "a cause is established by retrieved evidence"),
    },
}
CATALOGUE_GUIDANCE = ("Name a mechanism as primary_cause when retrieved evidence establishes why. Name an observation when the evidence "
                      "establishes the condition but not its cause. Conclude INSUFFICIENT_EVIDENCE when neither is established. Several "
                      "causes can hold at once: list each as its own hypothesis.")


def cause_catalogue():
    return {group: {code: {"definition": text, "evidence_that_supports": supports, "evidence_that_refutes": refutes}
                    for code, (text, supports, refutes) in entries.items()} for group, entries in CAUSE_CATALOGUE.items()}


SYSTEM = """You are Suhail's investigation agent for a synthetic logistics operation (synthetic data, not SPL production).
A monitor opened this case from observable symptoms. A symptom says what looks wrong, never why. Find out what actually
happened to the shipment.

Work iteratively: call one tool at a time, read its result, and decide what to examine next. Form competing
hypotheses early and look for evidence that would distinguish or contradict them. A shipment's own records often do not
hold the explanation: the devices, route runs, containers, trips and facilities its records name are shared with other
parcels, and what happened to those parcels in the same period is evidence too (shipment_overview lists the ids to ask
about). Correlation is evidence, not proof: check whether a shared pattern actually covers this parcel.

Questions worth asking (do not assume any answer):
- For a missing or late observation: did the parcel move, was it scanned, and has the record reached Suhail yet?
- For a failed or disputed delivery: address or access, an unreachable recipient, proof that does not bind to the
  recipient, a handover to someone else, or a record made by someone other than the planned driver?
- For custody that does not reconcile: who last held the parcel with corroboration, and does any later evidence
  (scans, attempts, returns, manifests, the route run's other parcels) show where it went?
Before concluding, retrieve at least one piece of evidence that could distinguish your leading hypothesis from its
closest alternative, and record that alternative as a hypothesis (refuted or uncertain) with the evidence.

An independent reviewer checks your conclusion. It sees: the records you cite, as recorded; the tool-computed results
you saw (comparisons and counts, cited by their DEMO-CMP ids); the ids and kinds of everything you retrieved but did
not cite; the tool calls you made; and deterministic checks of your citations. It checks that every citation resolves,
that retrieved evidence contradicting your conclusion is addressed, and that at least one alternative was tested. So:
cite the comparison a tool computed as well as the observation, address contradicting evidence explicitly
(contradicting_evidence_ids), and use only numbers, times and counts that appear in a record or computed result you cite.

Rules:
- Cite only ids listed under CITABLE_EVIDENCE_IDS in the tool results you received.
- Tools only read evidence. Actions (action types) are never tools: you recommend one in your conclusion.
- Tools return facts, never a diagnosis. UNKNOWN or NONE in a result means there is no such evidence at this time.
- Vehicle GPS is a vehicle position, never a parcel location or delivery proof.
- A driver assignment or manifest entry is not physical custody; custody needs a corroborated transfer.
- A missing scan is not proof of loss. A late upload (recorded long after it occurred) is a data delay.
- A recipient's or a driver's statement is an attributed report, not an established fact.
- Never attribute blame, fraud or negligence to any person or company.
- Do not invent numbers, times, attempts or records. Say what is missing instead.
- If the evidence available now does not establish a cause, conclude INSUFFICIENT_EVIDENCE: list what is missing in
  missing_evidence, say in next_evidence_step what should be obtained next and from where, and recommend an
  evidence-gathering action or a person's check. That is a good answer when it is true; a guess is not.
- confidence: high when the cited evidence establishes the cause and the closest alternative is refuted by evidence;
  medium when it supports the cause but an alternative is still open; low when it does not establish the cause. If your
  honest confidence is low, or nothing you retrieved distinguishes your cause from its closest alternative, the
  conclusion is INSUFFICIENT_EVIDENCE, not the most familiar cause.
- requires_physical_check: true only when, in your judgment, a person must go and physically locate or inspect the parcel
  before anything else can safely happen. An evidence request carried out through the system (a rescan, a reweigh, a
  device sync, a facility's check of its own records and shelves, a request for more evidence) is not by itself such a
  check: set false when that request is all you recommend.
- Your turns are limited (limits). Leave a turn for the conclusion.

Respond with exactly one JSON object and nothing else, either:
{"action":"call","tool":"<tool name>","args":{...},"purpose":"<one short sentence>"}
or, when the evidence supports a conclusion (or you must stop):
{"action":"conclude","hypotheses":[{"cause":"<cause code>","status":"supported|refuted|uncertain",
  "supporting_evidence_ids":[...],"contradicting_evidence_ids":[...],"assessment":"<one or two sentences>"}],
 "primary_cause":"<cause code>","confidence":"low|medium|high","missing_evidence":["..."],
 "next_evidence_step":"<one sentence, required for INSUFFICIENT_EVIDENCE, else empty>",
 "recommended_action":"<action type>","requires_physical_check":true|false,"summary":"<two or three sentences>"}
"""


def model_call_cap():
    """The per-case model-call cap: SUHAIL_MODEL_CALL_CAP, default 12, kept within sane bounds."""
    try:
        value = int(os.environ.get(MODEL_CALL_CAP_ENV, "").strip() or DEFAULT_MODEL_CALL_CAP)
    except ValueError:
        value = DEFAULT_MODEL_CALL_CAP
    return max(3, min(value, 60))


class CallBudget:
    """One counter for every model call of one case investigation: investigator turns, reviewer calls, revision
    rounds and retries. A call past the cap is refused in code."""

    def __init__(self, cap=None):
        self.cap = model_call_cap() if cap is None else max(1, int(cap))
        self.used, self.by_role, self.refused = 0, {}, 0

    @property
    def remaining(self):
        return self.cap - self.used

    def take(self, role, reserve=0):
        """Count one model call, or refuse it: at the cap, or when it would use up calls reserved for a later role."""
        if self.used >= self.cap - reserve:
            self.refused += 1
            return False
        self.used += 1
        self.by_role[role] = self.by_role.get(role, 0) + 1
        return True

    def snapshot(self):
        return {"model_call_cap": self.cap, "model_calls_used": self.used, "model_calls_by_role": dict(self.by_role),
                "cap_reached": self.refused > 0, "calls_refused_by_cap": self.refused}


class Session:
    """One case investigation across its review rounds: the conversation, the call budget and what was rejected."""

    def __init__(self, cap=None):
        self.budget = CallBudget(cap)
        self.messages = None        # the conversation, kept for a revision round
        self.steps = []             # every tool call of every round
        self.rounds = 0
        self.reviews = []           # earlier review results (verdict, feedback, unsupported claims)


class CallCapReached(RuntimeError):
    pass


def failure_mode(error):
    """How a model role failed: the provider call itself, the model-call cap, or output that never passed validation."""
    text = str(error or "")
    if text.startswith("model-call cap"):
        return "model_call_cap"
    return "model_unavailable" if text.startswith("model call failed") else "invalid_model_output"


def _sanitize(text, limit=400):
    return str(text or "")[:limit]


def _ids_in(record):
    record = record or {}
    values = [*(record.get("supporting_evidence_ids") or []), *(record.get("contradicting_evidence_ids") or [])]
    return {x for x in values if isinstance(x, str)}


def abstains(cause):
    return cause in (ABSTENTION, "UNKNOWN")


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
        if not all(isinstance(h.get(k) or [], (list, tuple)) for k in ("supporting_evidence_ids", "contradicting_evidence_ids")):
            return "evidence ids must be lists"
        unknown = sorted(_ids_in(h) - retrieved)
        if unknown:
            return "cited evidence ids were not returned by your tools: " + ", ".join(unknown[:4])
        if h["cause"] == out["primary_cause"]:
            primary = h
    if abstains(out["primary_cause"]):
        # A first-class conclusion: it must say what is missing and what to obtain next, and it cannot also claim a cause.
        missing = [x for x in (out.get("missing_evidence") or []) if isinstance(x, str) and x.strip()]
        if not missing:
            return "an INSUFFICIENT_EVIDENCE conclusion must name the missing evidence in missing_evidence"
        if action not in NEXT_STEP_ACTIONS:
            return "an INSUFFICIENT_EVIDENCE conclusion must recommend an evidence-gathering action or a person's check as its next step"
        if any(h["status"] == "supported" and not abstains(h["cause"]) for h in hypotheses):
            return "an INSUFFICIENT_EVIDENCE conclusion cannot mark a cause as supported; make that cause the primary cause instead"
    elif primary is None or primary["status"] != "supported" or not primary.get("supporting_evidence_ids"):
        return "the primary cause must be a supported hypothesis that cites supporting evidence"
    texts = [out.get("summary", ""), out.get("next_evidence_step", ""), *[h.get("assessment", "") for h in hypotheses],
             *map(str, out.get("missing_evidence") or [])]
    for text in texts:
        if BLAME.search(str(text or "")):
            return "output attributes blame or wrongdoing to a person"
        if GPS_DELIVERY.search(str(text or "")):
            return "output treats vehicle GPS as parcel delivery or location evidence"
    return None


def _clean_conclusion(out):
    keep = ("cause", "status", "supporting_evidence_ids", "contradicting_evidence_ids", "assessment")
    def cause(code):
        return ABSTENTION if code == "UNKNOWN" else code
    hypotheses = [{k: (_sanitize(h.get(k)) if k == "assessment" else cause(h.get(k)) if k == "cause" else (h.get(k) or [] if k.endswith("_ids") else h.get(k)))
                   for k in keep} for h in out["hypotheses"]][:6]
    return {"hypotheses": hypotheses, "primary_cause": cause(out["primary_cause"]), "confidence": out["confidence"],
            "missing_evidence": [_sanitize(x, 200) for x in (out.get("missing_evidence") or [])][:6],
            "next_evidence_step": _sanitize(out.get("next_evidence_step"), 300),
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


def case_packet(tools, session, feedback=None):
    """The investigator's opening input: symptoms, tools, the cause catalogue and the action names. No rule codes,
    no fact checks, and no mapping from actions to the causes they address."""
    return {"case": {"shipment_id": tools.sid, "as_of": tools.as_of, "symptoms": tools.symptoms},
            "tools": tools.describe(),
            "cause_catalogue": cause_catalogue(), "cause_catalogue_guidance": CATALOGUE_GUIDANCE,
            "action_types": {name: {"authority": entry[0], "summary": entry[3]} for name, entry in ACTIONS.items()},
            "limits": {"max_tool_calls": MAX_TOOL_CALLS,
                       "model_turns_available": max(session.budget.remaining - RESERVED_FOR_REVIEW, 0),
                       "note": "Turns are shared with the review of your conclusion and with any revision it asks for."},
            **({"reviewer_feedback": feedback} if feedback else {})}


def revision_message(review, feedback, remaining):
    """What the investigator is told when the reviewer sends the case back: it keeps its conversation and records."""
    review = review or {}
    points = {"reviewer_verdict": review.get("model_verdict") or review.get("verdict") or "REVISE",
              "reviewer_feedback": feedback or review.get("feedback") or "",
              "unsupported_claims": review.get("unsupported_claims") or [],
              "unaddressed_contradicting_evidence_ids": review.get("unaddressed_contradictions") or [],
              "invalid_citations": review.get("invalid_citations") or []}
    return ("REVIEW OF YOUR CONCLUSION: " + json.dumps(points, ensure_ascii=False) + " Everything you retrieved is still available and "
            "citable. Address each point: call tools if more evidence is needed, then conclude again. If the evidence does not establish "
            f"a cause, conclude INSUFFICIENT_EVIDENCE with what is missing and the next step. Model turns available: {remaining}.")


def investigate(tools, *, turn=None, on_step=None, feedback=None, session=None, review=None):
    """Run one investigation round of the bounded tool loop. Returns a result dict; never raises for model failures.

    session: the case investigation this round belongs to (conversation, call budget). A revision round continues the
    same conversation with the reviewer's feedback; without a session each call is a self-contained investigation."""
    turn = turn or model_turn
    session = session or Session()
    budget = session.budget
    revising = session.messages is not None
    if not revising:
        session.messages = [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": json.dumps(case_packet(tools, session, feedback), ensure_ascii=False)}]
    else:
        session.messages.append({"role": "user", "content": revision_message(review, feedback, max(budget.remaining - RESERVED_FOR_REVIEW, 0))})
    messages = session.messages
    session.rounds += 1
    round_number = getattr(tools, "round", 0)
    made = lambda: len(tools.round_calls()) if hasattr(tools, "round_calls") else len(tools.calls)
    steps, errors = [], []
    error, problem, turns, provider_failures, invalid_conclusions = None, None, 0, 0, 0

    def reject(text):
        errors.append({"turn": turns, "error": text})
        return text

    while True:
        if turns >= MAX_TURNS:
            error = "turn budget exhausted without a valid conclusion"
            break
        if not budget.take("investigator", reserve=RESERVED_FOR_REVIEW):
            error = "model-call cap reached before a valid conclusion"
            break
        turns += 1
        last = budget.remaining <= RESERVED_FOR_REVIEW or turns >= MAX_TURNS
        notes = []
        if problem:
            notes.append(f"Your previous reply was rejected: {problem}. Reply with one corrected JSON object.")
        if last or made() >= MAX_TOOL_CALLS:
            notes.append("No further tool calls are possible: reply with action conclude now. If the evidence does not establish a cause, "
                         "conclude INSUFFICIENT_EVIDENCE and name what is missing and the next step.")
        try:
            out = turn(messages + [{"role": "user", "content": " ".join(notes)}] if notes else messages)
        except Exception as exc:  # Transport/provider failure: type only.
            provider_failures += 1
            problem = reject(f"model call failed ({type(exc).__name__})")
            if provider_failures >= ATTEMPTS_PER_TURN:
                error = problem
                break
            continue
        provider_failures = 0
        # A rejected reply on a tool-call turn is corrected on the next turn; it never ends the investigation by itself.
        if not isinstance(out, dict) or out.get("action") not in ("call", "conclude"):
            problem = reject("reply must be one JSON object with action call or conclude")
            continue
        if out["action"] == "call":
            if out.get("tool") not in tools.CATALOG or out.get("tool") in getattr(tools, "disabled", ()):
                problem = reject(f"unknown tool {_sanitize(out.get('tool'), 60)}")
                continue
            if made() >= MAX_TOOL_CALLS or last:
                problem = reject("tool budget exhausted; conclude now with what you have")
                continue
            problem = None
            purpose = _sanitize(out.get("purpose"), 160)
            if BLAME.search(purpose) or GPS_DELIVERY.search(purpose):
                purpose = ""
            result = tools.call(out["tool"], out.get("args") or {})
            step = {"round": round_number, "tool": out["tool"], "args": tools.calls[-1]["args"], "purpose": purpose,
                    "evidence_ids": result["evidence_ids"], "computed_ids": result.get("computed_ids", [])}
            steps.append(step)
            session.steps.append(step)
            if on_step:
                on_step(step)
            messages.append({"role": "assistant", "content": json.dumps({k: out.get(k) for k in ("action", "tool", "args", "purpose")}, ensure_ascii=False)})
            messages.append({"role": "user", "content": f"TOOL RESULT {out['tool']}: {result['result']}"})
            continue
        problem = validate_conclusion(out, tools.retrieved)
        if problem:
            # Only a final conclusion that is still invalid after its corrective retry fails closed.
            invalid_conclusions += 1
            reject(problem)
            if invalid_conclusions >= ATTEMPTS_PER_TURN:
                error = problem
                break
            continue
        conclusion = _clean_conclusion(out)
        messages.append({"role": "assistant", "content": json.dumps({"action": "conclude", **conclusion}, ensure_ascii=False)})
        return {"mode": "gpt-oss", "degraded": False, "steps": list(session.steps), "round_steps": steps,
                "retrieved_evidence_ids": sorted(tools.retrieved), "validation_error": None, "validation_errors": errors,
                "model_calls": budget.snapshot(), **conclusion}
    # A provider failure is "model_unavailable"; the cap is "model_call_cap"; a model that answered but never produced a
    # valid conclusion (schema, citation, blame or GPS violations that survived the corrective retry, or the turn budget)
    # is "invalid_model_output". No diagnosis is substituted in any of them.
    return {"mode": failure_mode(error), "degraded": True, "steps": list(session.steps), "round_steps": steps,
            "retrieved_evidence_ids": sorted(tools.retrieved), "validation_error": error, "validation_errors": errors,
            "model_calls": budget.snapshot(), "hypotheses": [], "primary_cause": None, "confidence": None, "missing_evidence": [],
            "next_evidence_step": "", "recommended_action": None, "requires_physical_check": True,
            "summary": "Investigation could not reach a valid conclusion; no AI diagnosis was produced."}


REVIEWER_SYSTEM = """You are Suhail's independent reviewer for a synthetic logistics operation. You did not run the
investigation. You receive:
- investigator_conclusion: its hypotheses, primary cause, recommended action and summary;
- cited_records: the records it cited, as recorded (not the investigator's description of them);
- computed_results_seen: comparisons and counts that tool code computed and showed to the investigator. Treat each as a
  fact about the records named in its input_ids, as of computed_as_of;
- retrieved_but_uncited: ids and kinds of everything the investigator retrieved and did not cite, and tool_calls: the
  evidence queries it made;
- citation_validity and deterministic_checks: computed by code;
- in a revision round, previous_reviews: your own earlier feedback and unsupported claims.

Check, in this order:
1. Citations. citation_validity says whether each cited id resolves, was retrieved in this investigation and was
   recorded by the snapshot. A claim resting on an invalid citation is unsupported.
2. Support. Does each cited record or computed result say what the conclusion claims? Numbers, times and counts in the
   summary and assessments must appear in a cited record or computed result.
3. Contradictions. Among the cited records, the computed results and what was retrieved but not cited, is there evidence
   that contradicts the primary cause and that the conclusion does not address? List those ids.
4. Alternatives. Was at least one alternative explanation tested: a hypothesis other than the primary cause, refuted or
   left uncertain on evidence from a tool call that could tell them apart?
5. In a revision round: was each of your earlier points addressed?

Decide:
- ACCEPT: citations are valid, the primary cause is supported by them, contradicting evidence is addressed, an
  alternative was tested, and the recommended action fits the cause within policy. An INSUFFICIENT_EVIDENCE conclusion
  that names the missing evidence and a sensible next evidence-gathering step is acceptable when the retrieved evidence
  indeed does not establish a cause.
- REVISE: a specific claim is unsupported, evidence is misread, a contradiction is not addressed or no alternative was
  tested, and more work by the investigator could fix it. Say exactly what to re-examine.
- INSUFFICIENT_EVIDENCE: the evidence that exists at this time cannot establish this cause or any other. The case
  goes to a person or to more evidence gathering; no action runs automatically.
- HUMAN_REVIEW: the evidence is genuinely ambiguous, disputed or needs a physical check.
- ESCALATE: the conclusion or action could cause harm (blame, money, unsafe change).
Vehicle GPS never proves parcel location. Never blame a person.
Respond with exactly one JSON object: {"verdict":"ACCEPT|REVISE|INSUFFICIENT_EVIDENCE|HUMAN_REVIEW|ESCALATE",
"feedback":"<one to three sentences>","unsupported_claims":["..."],"unaddressed_contradictions":["<evidence id>"],
"alternatives_tested":"yes|no"}"""

CONCLUSION_FIELDS = ("hypotheses", "primary_cause", "confidence", "missing_evidence", "next_evidence_step", "recommended_action",
                     "requires_physical_check", "summary")


def review(conclusion, records, checks, symptoms, *, ask=None, context=None, session=None):
    """Independent review; a failed reviewer is UNAVAILABLE (fail closed), never ACCEPT.

    context: what the graph adds for the reviewer (citation validity, the tool-computed results the investigator saw,
    retrieved-but-uncited evidence, the tool calls, earlier reviews). session: the case's model-call budget; a call the
    cap refuses is a failed review."""
    from operations.agents import _ask
    ask = ask or _review_call
    packet = {"case_symptoms": symptoms, "investigator_conclusion": {k: conclusion.get(k) for k in CONCLUSION_FIELDS if k in conclusion or k != "next_evidence_step"},
              "cited_records": records, "deterministic_checks": checks, "visible_evidence_ids": sorted(records), **(context or {})}
    default = {"verdict": "", "feedback": "", "unsupported_claims": [], "unaddressed_contradictions": [], "alternatives_tested": ""}

    def validate(out):
        if out.get("verdict") not in REVIEW_VERDICTS:
            return "verdict must be ACCEPT|REVISE|INSUFFICIENT_EVIDENCE|HUMAN_REVIEW|ESCALATE"
        if not isinstance(out.get("feedback"), str) or not isinstance(out.get("unsupported_claims") or [], list):
            return "feedback must be text and unsupported_claims a list"
        if not isinstance(out.get("unaddressed_contradictions") or [], list):
            return "unaddressed_contradictions must be a list of evidence ids"
        if BLAME.search(out.get("feedback") or "") or GPS_DELIVERY.search(out.get("feedback") or ""):
            return "feedback attributes blame or misuses GPS"
        return None

    def counted(system, user, default_):
        if session is not None and not session.budget.take("reviewer"):
            raise CallCapReached("model-call cap reached")
        return ask(system, user, default_)

    refused_before = session.budget.refused if session is not None else 0
    out, mode, error = _ask(REVIEWER_SYSTEM, packet, {}, default, validate, counted)
    if out is None:
        capped = session is not None and session.budget.refused > refused_before
        # Still UNAVAILABLE for authority (fail closed); the mode says whether the call failed, was refused by the cap or
        # returned invalid output.
        return {"verdict": "UNAVAILABLE", "feedback": "Independent model review could not be completed.", "unsupported_claims": [],
                "unaddressed_contradictions": [], "alternatives_tested": "",
                "mode": "model_call_cap" if capped else failure_mode(error), "degraded": True,
                "validation_error": "model-call cap reached before the review completed" if capped else error}
    return {"verdict": out["verdict"], "feedback": _sanitize(out["feedback"], 500),
            "unsupported_claims": [_sanitize(x, 200) for x in out.get("unsupported_claims") or []][:6],
            "unaddressed_contradictions": [_sanitize(x, 160) for x in out.get("unaddressed_contradictions") or [] if isinstance(x, str)][:10],
            "alternatives_tested": out.get("alternatives_tested") if out.get("alternatives_tested") in ("yes", "no") else "",
            "mode": mode, "degraded": False, "validation_error": None}


def _review_call(system, user, default):
    from llm.pipeline._llm import ask_json
    return ask_json(system, user, default)
