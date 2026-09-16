"""المصنّف - root-cause classification over the fused subgraph retrieve.py returns.

Re-entered on an AFL loop: when reviewer.py rejects, graph.py routes back here with
state["review_notes"] populated, so the classification itself gets a chance to change (e.g.
the reviewer found the priority too low for an already-breached SLA). Looping to the
recommender alone would just re-derive the same action from the same unchanged premise,
which is why the feedback edge targets this stage and not that one.
"""
import json
import logging

from llm.pipeline import _llm
from llm.pipeline.extract import CATEGORIES
from llm.pipeline.state import Classification, PipelineState

log = logging.getLogger("pipeline.classifier")

_SYSTEM = (
    "You are a shipping-operations analyst. Given a customer complaint, the delivery "
    "history of the shipment it concerns, and similar past cases, identify the ROOT CAUSE.\n\n"
    f"Choose a category from exactly this list: {CATEGORIES}\n\n"
    "Return ONLY a JSON object:\n"
    '  "category": one of the listed categories\n'
    '  "confidence": a number 0-1 reflecting how well the evidence supports that category\n'
    '  "priority": "low" | "medium" | "high"\n'
    '  "rationale": one or two sentences citing the specific evidence you used\n\n'
    "Base the category on the shipment's own event history and failure record where "
    "available; use the similar past cases as supporting evidence, not as the answer. "
    "Lower your confidence when the evidence is thin or the similar cases disagree. "
    "Raise the priority when the delivery has already failed repeatedly or breached its SLA."
)

_DEFAULT: Classification = {
    "category": "recipient_unavailable",
    "confidence": 0.0,
    "priority": "medium",
    "rationale": "Model output could not be parsed; defaulted pending review.",
}


def _prompt(state: PipelineState) -> str:
    ctx = state.get("context") or {}
    local = ctx.get("local_subgraph") or {}
    parts = [f"COMPLAINT:\n{state['complaint_text']}"]

    if local:
        parts.append(
            "THIS SHIPMENT:\n" + json.dumps(
                {
                    "shipment": local.get("shipment"),
                    "courier": local.get("courier"),
                    "policy": local.get("policy"),
                    "addresses": local.get("addresses"),
                    "events": local.get("events"),
                    "recorded_failure": local.get("live_failure"),
                },
                ensure_ascii=False, default=str,
            )
        )
    else:
        parts.append("THIS SHIPMENT:\nNot identified - the complaint named no shipment or "
                     "tracking id that matched the database.")

    cases = ctx.get("similar_cases") or []
    if cases:
        parts.append(
            "SIMILAR PAST CASES:\n" + json.dumps(
                [{k: c.get(k) for k in
                  ("category", "description", "city", "district", "courier", "action", "success")}
                 for c in cases],
                ensure_ascii=False, default=str,
            )
        )

    notes = state.get("review_notes") or []
    if notes:
        # Only present on an AFL re-entry - this is the whole point of the loop.
        parts.append(
            "A REVIEWER REJECTED THE PREVIOUS ATTEMPT. Address these points and revise your "
            "classification rather than repeating it:\n"
            + "\n".join(f"- {n}" for n in notes)
        )
    return "\n\n".join(parts)


def classify(state: PipelineState) -> Classification:
    """Classify the complaint's root cause from the retrieved context (and, on a re-entry,
    the reviewer's objections)."""
    out = _llm.ask_json(_SYSTEM, _prompt(state), default=dict(_DEFAULT))

    if out.get("category") not in CATEGORIES:
        log.warning("classifier returned unknown category %r - keeping default", out.get("category"))
        out["category"] = _DEFAULT["category"]
        out["confidence"] = min(float(out.get("confidence") or 0.0), 0.3)
    if out.get("priority") not in ("low", "medium", "high"):
        out["priority"] = "medium"
    try:
        out["confidence"] = max(0.0, min(1.0, float(out.get("confidence", 0.0))))
    except (TypeError, ValueError):
        out["confidence"] = 0.0

    log.info("classified: %s (confidence=%.2f, priority=%s)",
             out["category"], out["confidence"], out["priority"])
    return out  # type: ignore[return-value]
