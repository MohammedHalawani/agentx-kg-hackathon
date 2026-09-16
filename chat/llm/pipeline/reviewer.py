"""المراجع - accept or reject the recommendation before anything is written back to Neo4j,
and produce the feedback that drives the AFL loop when it rejects.

Validates against the four things the diagram names:
  original evidence  - does the recommendation actually follow from THIS shipment's events,
                       or was it asserted from nothing?
  business rules     - rules.evaluate()'s findings, computed in Python, not re-judged here
  SLA                - the shipment's own Policy.sla_days, via the sla rule
  historical outcomes - did this action work on comparable cases, or is it a known failure?

Two of those are enforced deterministically BEFORE the model is consulted: a retry-budget
violation and a citation-free recommendation are hard rejects. The model is asked for
judgement, not permission - if it accepts something the rules forbid, the rules win. That
ordering is deliberate: a small local model should not be the only thing standing between a
bad recommendation and a graph write.
"""
import json
import logging

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
)

_DEFAULT: Review = {
    "verdict": "reject",
    "score": 0.0,
    "reason": "Reviewer output could not be parsed; rejecting rather than writing an unverified action.",
    "checked_against": CHECKS,
}


def _hard_rejects(state: PipelineState, findings: list) -> list[str]:
    """Deterministic rejections that don't depend on the model's judgement."""
    reasons = []
    rec = state.get("recommendation") or {}

    retry = next((f for f in findings if f["rule"] == "retry_budget"), None)
    if retry and not retry["passed"]:
        action = rec.get("action", "")
        if any(tok in action for tok in rules.RETRY_ACTIONS):
            reasons.append(
                f"Retry budget exhausted ({retry['detail']}) but the proposed action is another "
                "delivery retry. Propose a different approach or escalate."
            )

    if not rec.get("grounded_in") and (state.get("context") or {}).get("similar_cases"):
        reasons.append(
            "Precedent was retrieved but the recommendation cites none of it. Ground the "
            "action in specific resolved cases or explain why none apply."
        )
    return reasons


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
