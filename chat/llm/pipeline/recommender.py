"""المُوصي - propose a resolution action, grounded in resolved cases and constrained by the
business rules.

Runs the diagram's "2nd retrieval": rather than reusing the classifier's context, it issues a
FRESH vector search keyed on the now-known category and root cause. The first retrieval was
seeded by the raw complaint - which is what the customer wrote, not what the problem turned
out to be. Once the classifier has named the root cause, a second search on that phrasing
surfaces precedent the first pass missed. That is the entire reason the arrow exists in the
diagram instead of the recommender just reading state["context"].

Candidate actions are ranked by what actually WORKED historically (rules.action_success_rate),
not by similarity alone - the nearest neighbour may well be a case that failed.
"""
import json
import logging

from llm.pipeline import _llm, retrieve, rules
from llm.pipeline.state import PipelineState, Recommendation

log = logging.getLogger("pipeline.recommender")

# The Resolution.action vocabulary present in the graph's resolved history (see
# shipment_kg/generate_shipment_kg.py's RESOLUTION_ACTIONS). Recommendations should stay
# within this set so a proposal is comparable to precedent instead of a fresh paraphrase.
KNOWN_ACTIONS = [
    "تأكيد العنوان الصحيح مع العميل وإعادة التوجيه",
    "تصحيح العنوان في النظام وإعادة الجدولة",
    "التواصل مع العميل لتحديد الموقع عبر الإحداثيات",
    "إعادة جدولة التسليم في يوم آخر",
    "التنسيق مع العميل عبر الهاتف لتحديد وقت بديل",
    "تسليم لجهة بديلة بموافقة العميل",
    "إعادة محاولة التسليم بعد تصحيح بيانات الشحنة",
    "استبدال الملصق وإعادة فحص الشحنة",
    "تحويل الشحنة إلى مندوب آخر لإعادة المحاولة",
    "إعادة توجيه الشحنة عبر مركز فرز بديل",
    "تسريع الشحنة عبر خط نقل مباشر",
    "إبلاغ العميل بالتأخير وتحديث موعد التسليم",
    "تصعيد الحالة للمشرف واتخاذ إجراء مركب لتصحيح العنوان وإعادة التسليم",
    "التنسيق بين فريق المستودع والمندوب لحل الحالة المركبة",
    "إعادة فتح الطلب ومعالجة جميع أسباب الفشل مجتمعاً",
]

_SYSTEM = (
    "You are a shipping-operations resolution planner. Given a classified root cause, "
    "precedent from resolved cases, and hard business-rule findings, choose the single best "
    "next action.\n\n"
    "Rules you must respect:\n"
    "- Prefer an action from the known list; it is the vocabulary used by past resolutions.\n"
    "- Prefer actions with a high historical success rate over merely similar ones.\n"
    "- If the retry budget has FAILED, do NOT propose another plain re-delivery attempt - "
    "change approach or escalate.\n"
    "- If the SLA is already breached, favour actions that expedite or inform the customer.\n\n"
    "Return ONLY a JSON object:\n"
    '  "action": the chosen action text\n'
    '  "grounded_in": array of resolution_id strings this is based on (may be empty)\n'
    '  "rationale": one or two sentences, citing the precedent and rules you relied on'
)

_DEFAULT: Recommendation = {
    "action": "تصعيد الحالة للمشرف واتخاذ إجراء مركب لتصحيح العنوان وإعادة التسليم",
    "grounded_in": [],
    "rationale": "Model output could not be parsed; escalating for human handling.",
    "candidates": [],
}


def second_retrieval(state: PipelineState, top_k: int = 5) -> list[dict]:
    """The diagram's "2nd retrieval": a fresh vector search keyed on the CLASSIFIED root
    cause rather than the customer's original wording, fused with the first pass's hits."""
    cls = state.get("classification") or {}
    ctx = state.get("context") or {}
    query = f"{cls.get('category', '')} {cls.get('rationale', '')}".strip()
    if not query:
        return ctx.get("similar_cases") or []
    # Honour the holdout exclusion here too: the first retrieval filtering the case out and
    # the second silently letting it back in would leak the answer at the exact stage that
    # chooses the action.
    fresh = retrieve.vector_search(query, exclude_failure_id=state.get("exclude_failure_id"))
    fused = retrieve.fuse_rrf(fresh, ctx.get("similar_cases") or [])
    log.info("2nd retrieval: %d fresh hits -> %d fused", len(fresh), len(fused))
    return fused[:top_k]


def _prompt(state: PipelineState, cases: list[dict], success_rates: dict, findings: list) -> str:
    cls = state.get("classification") or {}
    return "\n\n".join([
        f"COMPLAINT:\n{state['complaint_text']}",
        "CLASSIFIED ROOT CAUSE:\n" + json.dumps(cls, ensure_ascii=False),
        "BUSINESS RULE FINDINGS:\n" + rules.summarise(findings),
        "PRECEDENT (resolved cases, with what was done and whether it worked):\n"
        + json.dumps(
            [{k: c.get(k) for k in
              ("resolution_id", "category", "action", "success", "outcome_notes")} for c in cases],
            ensure_ascii=False, default=str),
        "HISTORICAL SUCCESS RATE BY ACTION:\n" + json.dumps(success_rates, ensure_ascii=False),
        "KNOWN ACTION VOCABULARY:\n" + json.dumps(KNOWN_ACTIONS, ensure_ascii=False),
    ])


def recommend(state: PipelineState) -> Recommendation:
    """Propose an action for the classified root cause, grounded in precedent and filtered
    through the business rules."""
    cases = second_retrieval(state)
    local = (state.get("context") or {}).get("local_subgraph") or {}
    findings = rules.evaluate(local, cases)
    success_rates = rules.action_success_rate(cases)

    out = _llm.ask_json(_SYSTEM, _prompt(state, cases, success_rates, findings),
                        default=dict(_DEFAULT))

    if not isinstance(out.get("grounded_in"), list):
        out["grounded_in"] = []
    # Keep only citations that refer to precedent actually retrieved - a model citing a
    # resolution_id it never saw is exactly what the reviewer should not have to catch.
    seen = {c.get("resolution_id") for c in cases}
    out["grounded_in"] = [g for g in out["grounded_in"] if g in seen]
    # Carry the cited rows themselves, not just their ids, so the reviewer can check WHAT was
    # cited rather than merely THAT something was. Retrieval is similarity-based and crosses
    # category lines freely - a barcode-mismatch case reads much like a wrong-gate one - so
    # "grounded" is meaningless without knowing the precedent's own root cause.
    cited = set(out["grounded_in"])
    out["grounded_cases"] = [
        {k: c.get(k) for k in ("resolution_id", "category", "action", "success")}
        for c in cases if c.get("resolution_id") in cited
    ]
    out["candidates"] = [
        {"action": a, **stats} for a, stats in
        sorted(success_rates.items(), key=lambda kv: kv[1]["rate"], reverse=True)
    ]

    log.info("recommended: %.60s (grounded_in=%d)", out.get("action", ""), len(out["grounded_in"]))
    return out  # type: ignore[return-value]
