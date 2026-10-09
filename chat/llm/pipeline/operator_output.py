"""Operator summaries from recorded facts, separate from unverified model prose.

Model rationale/reviewer feedback remains inside the decision loop. It is not an
authoritative statement of counts, custody, historical rates or execution status.
"""
from llm.pipeline import rules


def _local(state):
    return (state.get("context") or {}).get("local_subgraph") or {}


def recorded_facts(state):
    local = _local(state)
    events = local.get("events")
    if not isinstance(events, list):
        return "Recorded attempt history unavailable."
    used = rules._attempts(events)
    limit = (local.get("policy") or {}).get("retry_limit")
    text = f"Recorded delivery attempts: {used}"
    if limit is not None:
        text += f" of {limit} permitted"
        text += " (budget exhausted)" if used >= limit else " (budget remains)"
    text += "."
    span = rules._days_open(events)
    sla = (local.get("policy") or {}).get("sla_days")
    if span is not None and sla is not None:
        text += f" Recorded timeline span: {span} days against {sla}-day policy SLA"
        text += " (breached)." if span > sla else " (within SLA)."
    return text


def classification_summary(state, value):
    category = value.get("category") or "unknown"
    local = _local(state)
    text = f"Model hypothesis: {category}; requires evidence verification. " + recorded_facts(state)
    if category == "hub_delay" and any(event.get("event_type") == "HUB_DELAY"
                                        for event in local.get("events") or []):
        text += " A HUB_DELAY event is recorded; causal attribution still requires review."
    elif category in ("failed_attempt_barcode_mismatch", "failed_attempt_weight_mismatch", "failed_attempt_wrong_gate"):
        text += " This context has no measured barcode, weight or gate observations to establish that subtype."
    elif category == "address_conflict":
        addresses = {address.get("full_address") for address in local.get("addresses") or []
                     if address.get("full_address")}
        text += f" Distinct recorded address values: {len(addresses)}; compare versions and attempt evidence."
    else:
        text += " Complaint statements are reports, not independently verified operational facts."
    return text


def recommendation_summary(state, value):
    # Rebuild from observed source rows, never from a model-supplied statistic/candidate.
    cases = {case.get("resolution_id"): case for case in value.get("grounded_cases") or []
             if case.get("resolution_id") and type(case.get("success")) is bool}
    matching = [case for case in cases.values() if case.get("action") == value.get("action")]
    text = f"Cited observed synthetic histories: {len(cases)}; exact-action matches: {len(matching)}."
    if matching:
        succeeded = sum(case["success"] for case in matching)
        text += f" Matching cited outcomes: {succeeded}/{len(matching)} succeeded ({100*succeeded/len(matching):.1f}%)."
        text += " This small cited sample is not a success guarantee."
    else:
        text += " Cited histories do not establish success for this exact action."
    return text + " Operator approval, external execution and outcome remain unconfirmed."


def review_summary(state, value):
    if value.get("verdict") == "accept":
        return ("Agent review accepted a proposed recommendation; this does not establish correctness, "
                "human approval, execution or success. " + recorded_facts(state))
    # Deterministic rejections have an auditable reason; model prose can invent rules.
    from llm.pipeline.reviewer import _hard_rejects
    context = state.get("context") or {}
    blocking = _hard_rejects(state, rules.evaluate(_local(state), context.get("similar_cases") or []))
    if blocking:
        return " ".join(blocking)
    return ("Agent review rejected the proposal. Reconsider the diagnosis/action or obtain human "
            "verification; the model's policy interpretation is not an authoritative rule. " + recorded_facts(state))


def summary(stage, value, state):
    if stage == "classify":
        return classification_summary(state, value)
    if stage == "recommend":
        return recommendation_summary(state, value)
    if stage == "review":
        return review_summary(state, value)
    raise ValueError("Unsupported operator summary stage")
