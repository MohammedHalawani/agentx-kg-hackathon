"""المراجع - accept or reject the recommendation before anything is written back to Neo4j,
and produce the feedback that drives the AFL loop when it rejects.

Validates against the four things the diagram names:
  original evidence  - does the recommendation actually follow from THIS shipment's events,
                       or was it asserted from nothing?
  business rules     - rules.evaluate()'s findings, computed in Python, not re-judged here
  SLA                - the shipment's own Policy.sla_days, via the sla rule
  historical outcomes - did this action work on comparable cases, or is it a known failure?

Retry-budget violations, citation/category conflicts and detectable contradictory recorded
attempt counts are enforced deterministically BEFORE the model is consulted. The model is asked for
judgement, not permission - if it accepts something the rules forbid, the rules win. That
ordering is deliberate: a small local model should not be the only thing standing between a
bad recommendation and a graph write.
"""
import json
import logging
import re

from llm.pipeline import _llm, rules
from llm.pipeline.state import PipelineState, Review

log = logging.getLogger("pipeline.reviewer")

CHECKS = ["evidence", "business_rules", "sla", "historical_outcomes"]
ACCEPT_THRESHOLD = 0.6  # below this score, a recommendation is not actionable

_SYSTEM = (
    "You are a quality reviewer for shipping-operations decisions. Judge whether the "
    "proposed action is justified by the evidence, the precedent, and the business rules.\n\n"
    "Return ONLY a JSON object:\n"
    '  "verdict": "accept" or "reject"\n'
    '  "score": a number 0-1 for how well-justified the action is\n'
    '  "reason": one or two sentences. If rejecting, state specifically what must change - '
    "this text is fed back to the classifier as instructions, so make it actionable.\n\n"
    "Reject when: the action contradicts a failed business rule; the evidence does not "
    "support the classified root cause; or comparable cases show this action usually fails. "
    "Accept when the action follows from the evidence and precedent supports it."
    " Computed findings are authoritative. An exhausted retry budget blocks plain retry/"
    "rescheduling/redelivery; address verification or redirection is not automatically a plain "
    "retry. Do not invent blanket rules or enterprise cancellation/refund authority. Customer "
    "statements and underidentified subtype guesses require verification, not causal certainty."
)

_DEFAULT: Review = {
    "verdict": "reject",
    "score": 0.0,
    "reason": "Reviewer output could not be parsed; rejecting rather than writing an unverified action.",
    "checked_against": CHECKS,
}

_NUMBER_WORDS = {word: number for number, word in enumerate(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"))}
_COUNT = r"(?:\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten)"
_ATTEMPT_CLAIMS = (
    re.compile(rf"\b(?P<count>{_COUNT})\s+(?P<kind>(?:(?:consecutive|failed|unsuccessful|delivery|recorded|previous|past)\s+){{1,4}})attempts?\b", re.I),
    re.compile(rf"\b(?P<kind>(?:(?:consecutive|failed|unsuccessful|delivery|recorded|previous|past)\s+){{1,4}})attempts?\s*(?:\(\s*|:\s*)(?P<count>{_COUNT})\b", re.I),
    re.compile(r"(?P<count>\d+)\s+(?P<kind>محاولات?\s+(?:التسليم|تسليم)(?:\s+فاشلة)?)"),
    re.compile(r"(?P<kind>محاولات?\s+(?:التسليم|تسليم)(?:\s+فاشلة)?)\s*(?:\(\s*|:\s*)(?P<count>\d+)"),
)
_NONFACTUAL_PREFIX = re.compile(
    r"\b(?:may|might|possibly|perhaps|approximately|about|around|roughly|at least|at most|"
    r"up to|or|between|allows?|permits?|limit|budget|maximum|minimum|should|will|would|"
    r"could|recommend\w*|propos\w*|plan\w*|schedul\w*|next|future|additional|customer reports|"
    r"customer says|recipient reports|complaint says|historical cases|similar cases|"
    r"precedent cases)\b|(?:ربما|قد|حوالي|تقريباً|تقريبا|يسمح|يوصي|مقترح|إضافية)", re.I)


def _attempt_count_contradiction(state: PipelineState) -> str | None:
    """Reject only clear final claims contradicted by this shipment's recorded attempts.

    This is a narrow integrity guard, not a natural-language fact checker. Uncertain,
    attributed, future and policy-allowance counts are left to review. A failed subset may
    be smaller than the recorded attempt total; outcomes of each attempt are not supplied.
    """
    local = (state.get("context") or {}).get("local_subgraph") or {}
    if not isinstance(local.get("shipment"), dict) or not isinstance(local.get("events"), list):
        return None
    rationale = (state.get("classification") or {}).get("rationale")
    if not isinstance(rationale, str):
        return None
    actual = rules._attempts(local["events"])
    for pattern in _ATTEMPT_CLAIMS:
        for match in pattern.finditer(rationale):
            # Restrict interpretation to the nearby clause; do not mistake an allowed or
            # hypothetical future retry count for a claim about recorded history.
            prefix = re.split(r"[.!?;؛\n]", rationale[:match.start()])[-1][-70:]
            suffix = rationale[match.end():match.end() + 20]
            if (_NONFACTUAL_PREFIX.search(prefix) or re.search(r"\d+\s*[-–]\s*$", prefix)
                    or re.match(r"\s*(?:[-–]|to\b|or\b|should\b|will\b|would\b|could\b|"
                                r"next\b|(?:are|is)\s+(?:planned|allowed|permitted|recommended|proposed)\b)", suffix, re.I)):
                continue
            token = match.group("count").lower()
            claimed = _NUMBER_WORDS[token] if token in _NUMBER_WORDS else int(token)
            subset = any(word in match.group("kind").lower() for word in ("failed", "unsuccessful", "فاشلة"))
            if claimed == actual or (subset and claimed < actual):
                continue
            return (f"Evidence count contradiction: classification rationale claims {claimed} "
                    f"delivery attempt(s), but this shipment has {actual} recorded DELIVERY_ATTEMPT "
                    "event(s). Correct the rationale using the recorded count; do not invent "
                    "additional attempts or assume every recorded attempt failed.")
    return None


def _hard_rejects(state: PipelineState, findings: list) -> list[str]:
    """Deterministic rejections that don't depend on the model's judgement."""
    reasons = []
    rec = state.get("recommendation") or {}

    count_contradiction = _attempt_count_contradiction(state)
    if count_contradiction:
        reasons.append(count_contradiction)

    retry = next((f for f in findings if f["rule"] == "retry_budget"), None)
    if retry and not retry["passed"]:
        action = rec.get("action", "")
        action = action.casefold() if isinstance(action, str) else ""
        action = re.sub(r"\bre[-‐‑]\s*deliver", "redeliver", action)
        if any(tok.casefold() in action for tok in rules.RETRY_ACTIONS):
            reasons.append(
                f"Retry budget exhausted ({retry['detail']}) but the proposed action is another "
                "delivery retry. Propose a different approach or escalate."
            )

    if not rec.get("grounded_in") and (state.get("context") or {}).get("similar_cases"):
        reasons.append(
            "Precedent was retrieved but the recommendation cites none of it. Ground the "
            "action in specific resolved cases or explain why none apply."
        )
    elif rec.get("grounded_in"):
        mismatch = _category_mismatch(state)
        if mismatch:
            reasons.append(mismatch)
    return reasons


def _base_category(category: str | None) -> str:
    """Root cause without the escalation marker.

    A category of `escalation:address_conflict` is an address conflict that already failed
    ordinary handling once. For the purpose of asking "is this precedent about the same
    problem?" the two are the same problem, so they are compared on the base name.
    """
    c = (category or "").strip()
    return c[len("escalation:"):] if c.startswith("escalation:") else c


def _category_mismatch(state: PipelineState) -> str | None:
    """Reject a recommendation whose every citation is for a different root cause.

    Retrieval fuses a vector search with a graph walk, and the vector half ranks by wording,
    which crosses category lines readily. That is useful for recall and dangerous as
    justification: an action can be cited as precedent-backed while every case behind it
    concerns a different failure. Observed in practice - a wrong-gate failure was resolved by
    replacing the barcode label, the remedy for a different category entirely, and the
    reviewer accepted it because citations were present.

    Only the citations are judged here, not the action: proposing something novel is allowed,
    but then `grounded_in` should be empty and the clause above applies instead.
    """
    classified = _base_category((state.get("classification") or {}).get("category"))
    if not classified:
        return None
    cited = (state.get("recommendation") or {}).get("grounded_cases") or []
    if not cited:
        return None
    if any(_base_category(c.get("category")) == classified for c in cited):
        return None
    seen = sorted({_base_category(c.get("category")) for c in cited if c.get("category")})
    return (f"The root cause is {classified}, but every cited case is about "
            f"{', '.join(seen) or 'another category'}. Cite precedent for {classified}, or "
            f"propose an action without claiming precedent that does not apply.")


def _prompt(state: PipelineState, findings: list) -> str:
    ctx = state.get("context") or {}
    return "\n\n".join([
        f"COMPLAINT:\n{state['complaint_text']}",
        "CLASSIFICATION:\n" + json.dumps(state.get("classification") or {}, ensure_ascii=False),
        "PROPOSED ACTION:\n" + json.dumps(state.get("recommendation") or {},
                                          ensure_ascii=False, default=str),
        "ORIGINAL EVIDENCE (this shipment):\n" + json.dumps(
            ctx.get("local_subgraph") or {}, ensure_ascii=False, default=str),
        "BUSINESS RULE FINDINGS:\n" + rules.summarise(findings),
        "HISTORICAL OUTCOMES FOR COMPARABLE CASES:\n" + json.dumps(
            [{k: c.get(k) for k in ("resolution_id", "action", "success")}
             for c in (ctx.get("similar_cases") or [])],
            ensure_ascii=False, default=str),
    ])


def review(state: PipelineState) -> Review:
    """Judge the recommendation. Hard rule violations reject without consulting the model;
    otherwise the model scores it and the threshold decides."""
    ctx = state.get("context") or {}
    findings = rules.evaluate(ctx.get("local_subgraph") or {}, ctx.get("similar_cases") or [])

    blocking = _hard_rejects(state, findings)
    if blocking:
        log.info("hard reject: %s", blocking)
        return {
            "verdict": "reject",
            "score": 0.0,
            "reason": " ".join(blocking),
            "checked_against": CHECKS,
        }

    out = _llm.ask_json(_SYSTEM, _prompt(state, findings), default=dict(_DEFAULT))

    try:
        out["score"] = max(0.0, min(1.0, float(out.get("score", 0.0))))
    except (TypeError, ValueError):
        out["score"] = 0.0
    if out.get("verdict") not in ("accept", "reject"):
        out["verdict"] = "reject"
    # The threshold is authoritative: an "accept" that scores below it is downgraded, so the
    # score and the verdict can never disagree in the record written to the graph.
    if out["verdict"] == "accept" and out["score"] < ACCEPT_THRESHOLD:
        out["verdict"] = "reject"
        out["reason"] = (f"Score {out['score']:.2f} is below the {ACCEPT_THRESHOLD} bar. "
                         + str(out.get("reason", "")))
    out["checked_against"] = CHECKS

    log.info("review: %s (score=%.2f)", out["verdict"], out["score"])
    return out  # type: ignore[return-value]
