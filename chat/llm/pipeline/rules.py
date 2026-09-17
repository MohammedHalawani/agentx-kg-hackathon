"""Business rules - the diagram's "Business rules" input, feeding both المُوصي (recommender)
and المراجع (reviewer).

Deliberately NOT an LLM concern. These are the checks that must hold regardless of what any
model thinks, so they're computed in Python from facts already in the graph and handed to
both stages as plain findings. The recommender uses them to avoid proposing something
inadmissible; the reviewer uses the same list to justify accept/reject. Sharing one
implementation is what stops the two stages from disagreeing about the rules themselves.

Every rule reads from what retrieve.local_subgraph() already fetched - the shipment's
Policy (sla_days, retry_limit) and its Event timeline - so enforcing them costs no extra
round trip.
"""
from datetime import datetime
from typing import TypedDict

# Actions that constitute "try delivering again", for the retry-limit rule. Matched as
# substrings against the proposed action, so each entry has to be specific enough to mean
# re-delivery on its own.
#
# Deliberately NOT the bare "إعادة": that is just the Arabic prefix "re-", so it matches every
# re-anything - including "إعادة التوجيه" (redirect), which is the correct move once the
# original address has failed, not another attempt at the same one. Matching it here made the
# reviewer reject the right action on any shipment that had spent its retries.
# Each phrase appears twice, with and without the definite article "ال", because Arabic
# inserts it between the two words ("إعادة الجدولة" vs "إعادة جدولة التسليم") and a substring
# test sees those as different strings. Both spellings occur in the graph's own vocabulary.
RETRY_ACTIONS = (
    "إعادة الجدولة",   # reschedule
    "إعادة جدولة",     #   "     (no article - "إعادة جدولة التسليم في يوم آخر")
    "إعادة التسليم",   # re-deliver
    "إعادة تسليم",     #   "     (no article)
    "إعادة المحاولة",  # retry the attempt
    "إعادة محاولة",    #   "     (no article)
    "retry",
    "redeliver",
    "reschedule",
)

# An action a near-identical past case already failed with shouldn't be proposed blind.
REPEAT_FAILURE_THRESHOLD = 0.5  # historical success rate below this = flagged


class RuleFinding(TypedDict):
    rule: str
    passed: bool
    detail: str


def _attempts(events: list[dict]) -> int:
    return sum(1 for e in events if (e or {}).get("event_type") == "DELIVERY_ATTEMPT")


def _days_open(events: list[dict]) -> float | None:
    """Days between the CREATED event and the latest event - the elapsed time an SLA is
    measured against. None when the timeline is too sparse to say."""
    stamps = []
    for e in events or []:
        ts = (e or {}).get("timestamp")
        if not ts:
            continue
        try:
            stamps.append(datetime.fromisoformat(str(ts)))
        except ValueError:
            continue
    if len(stamps) < 2:
        return None
    return round((max(stamps) - min(stamps)).total_seconds() / 86400, 2)


def sla_status(local: dict) -> RuleFinding:
    """Has this shipment already blown the SLA its Policy promises?"""
    policy = (local or {}).get("policy") or {}
    sla = policy.get("sla_days")
    elapsed = _days_open((local or {}).get("events") or [])
    if sla is None or elapsed is None:
        return {"rule": "sla", "passed": True,
                "detail": "No policy SLA or insufficient event timeline to judge."}
    breached = elapsed > sla
    return {
        "rule": "sla",
        "passed": not breached,
        "detail": (f"{elapsed} days elapsed against a {sla}-day SLA"
                   f"{' - BREACHED' if breached else ' - within SLA'}."),
    }


def retry_budget(local: dict) -> RuleFinding:
    """Has the shipment already used up the retry attempts its Policy allows? If so, another
    'just try again' recommendation is inadmissible - it must escalate or change approach."""
    policy = (local or {}).get("policy") or {}
    limit = policy.get("retry_limit")
    used = _attempts((local or {}).get("events") or [])
    if limit is None:
        return {"rule": "retry_budget", "passed": True,
                "detail": f"{used} attempt(s) made; policy sets no retry limit."}
    exhausted = used >= limit
    return {
        "rule": "retry_budget",
        "passed": not exhausted,
        "detail": (f"{used} of {limit} permitted attempt(s) used"
                   f"{' - EXHAUSTED, re-delivery not admissible' if exhausted else ''}."),
    }


def precedent_strength(similar_cases: list[dict]) -> RuleFinding:
    """Did the actions taken on comparable cases actually work? A precedent set that mostly
    FAILED is a reason to distrust the obvious recommendation, and is exactly the signal a
    pure similarity search throws away."""
    cases = [c for c in (similar_cases or []) if c.get("success") is not None]
    if not cases:
        return {"rule": "precedent_strength", "passed": True,
                "detail": "No comparable resolved cases with recorded outcomes."}
    wins = sum(1 for c in cases if c.get("success"))
    rate = wins / len(cases)
    return {
        "rule": "precedent_strength",
        "passed": rate >= REPEAT_FAILURE_THRESHOLD,
        "detail": (f"{wins}/{len(cases)} comparable cases succeeded ({rate:.0%})"
                   f"{' - weak precedent' if rate < REPEAT_FAILURE_THRESHOLD else ''}."),
    }


def action_success_rate(similar_cases: list[dict]) -> dict[str, dict]:
    """action -> {tried, succeeded, rate}, so the recommender can prefer what has actually
    worked rather than whatever the nearest single neighbour happened to do."""
    stats: dict[str, dict] = {}
    for case in similar_cases or []:
        action = case.get("action")
        if not action:
            continue
        # A pending outcome (success is null - the agent decided it, nobody has confirmed it)
        # counts neither way. Treating it as a success would let the agent's own choices
        # inflate their track record; treating it as a failure would punish them for not
        # having been verified yet. Excluding it keeps the rate a measure of observed reality.
        if case.get("success") is None:
            continue
        s = stats.setdefault(action, {"tried": 0, "succeeded": 0, "rate": 0.0})
        s["tried"] += 1
        if case.get("success"):
            s["succeeded"] += 1
    for s in stats.values():
        s["rate"] = round(s["succeeded"] / s["tried"], 3) if s["tried"] else 0.0
    return stats


def evaluate(local: dict, similar_cases: list[dict]) -> list[RuleFinding]:
    """Every rule, run over the retrieved context. Order is stable so the reviewer's
    checked_against list reads consistently between runs."""
    return [sla_status(local), retry_budget(local), precedent_strength(similar_cases)]


def summarise(findings: list[RuleFinding]) -> str:
    """One compact block for a prompt - rules are facts the model should reason WITH, not
    re-derive, so they go in as pre-computed statements."""
    return "\n".join(
        f"- {f['rule']}: {'PASS' if f['passed'] else 'FAIL'} - {f['detail']}" for f in findings
    )
