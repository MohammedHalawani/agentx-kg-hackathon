"""Measure the pipeline against cases whose real answer is already known.

"Accuracy of root-cause classification" and "appropriateness of the recommended action" are
the first two things the challenge is judged on, and until now neither had a number attached.
This produces one.

The 165 resolved cases are the holdout: each records the category a human assigned, the
action they took, and whether it worked. The pipeline is run on a synthesized complaint for
each, and its answers compared against those. Two numbers come out:

  category   - did the classifier reach the same root cause the human recorded?
  action     - did the recommender choose the same action the human took?

Action agreement is the weaker of the two, and deliberately so: a different action is not
necessarily a worse one, several actions are legitimate for most categories, and a case can
be resolved more than one way. Read it as a similarity signal, not a mark out of ten. The
`plausible` column is the honest complement - the chosen action has historically succeeded
for the true category, even if it isn't what happened this time.

Leakage is the thing to be careful about here, and it is guarded in two places:

  * The case under test is resolved, so it sits in the vector index and would be retrieved as
    its own answer. `exclude_failure_id` removes it from both retrieval passes.
  * The graph records the true category on the FailureReason itself, and the local subgraph
    carries that node. The classifier would then be reading the answer rather than inferring
    it, so the live-failure block is stripped from the context before classification.

There is a third leak the flags control rather than fix. This dataset's `description` field
restates the category in Arabic prose - "تعارض في العنوان" for address_conflict - so a
complaint built from it hands the classifier its answer, and the default mode scores at or
near 100%. That number measures reading, not inference. `--hard` substitutes a symptom-level
sentence of the kind a customer would actually write, and is the setting worth quoting.

Even in hard mode the complaint is synthesized from the case's own fields, so it stays
cleaner and more on-topic than real traffic. Treat every number here as an upper bound.

What has already been tried, so it is not tried again:

  * Self-reported confidence as an escalation trigger. Flat - 0.86 stated when right, 0.84
    when wrong. Nothing in the pipeline reads the field, and on this evidence nothing should.
  * Precedent agreement (share of retrieved cases sharing a majority category) as an
    evidence-side signal. Also flat, and it inverted between samples: 0.86/0.83 on one seed,
    0.57/0.94 on another.
  * Asking the classifier to name a runner-up category and escalating on a narrow margin.
    Ranking should be an easier question than self-assessment, but measured it cost accuracy
    to ask - 76% without the runner-up prompt, 64-68% with it - and the margin caught 2 of 8
    misses on one seed while catching none on another. Reverted.

Still untried: classifying twice and escalating on disagreement (reliable, doubles the cost
per case), and treating structurally inseparable pairs - a weight mismatch and a barcode
mismatch look identical from a customer's description - as escalate-by-policy rather than
something inference can fix.

Usage (from chat/):
    uv run python scripts/eval_pipeline.py --hard          # the realistic number
    uv run python scripts/eval_pipeline.py                 # easy mode, description included
    uv run python scripts/eval_pipeline.py --hard -n 50    # more cases, slower
    uv run python scripts/eval_pipeline.py --hard --verbose
"""
import argparse
import logging
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neo4j import RoutingControl  # noqa: E402

import config  # noqa: E402
from core.query_runner import get_driver  # noqa: E402
from llm.pipeline import classifier, recommender, retrieve, rules  # noqa: E402

# The resolved cases, with the human's verdict attached - the ground truth being graded
# against. Only seeded rows: an agent-written resolution is a prediction, not an answer, and
# grading predictions against predictions measures nothing.
_HOLDOUT = """
MATCH (f:FailureReason)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
WHERE r.source IS NULL
OPTIONAL MATCH (s:Shipment)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(f)
RETURN f.failure_id  AS failure_id,
       f.category    AS true_category,
       f.description AS description,
       f.city        AS city,
       f.district    AS district,
       f.courier     AS courier,
       s.shipment_id AS shipment_id,
       r.action      AS true_action,
       o.success     AS true_success
"""

# How often each action worked, per true category - used for the `plausible` column.
_ACTION_STATS = """
MATCH (f:FailureReason)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
WHERE r.source IS NULL
RETURN f.category AS category, r.action AS action,
       count(*) AS used, sum(CASE WHEN o.success THEN 1 ELSE 0 END) AS ok
"""


def _read(cypher: str) -> list[dict]:
    return get_driver().execute_query(
        cypher, routing_=RoutingControl.READ, database_=config.SHIPMENT_DATABASE,
        result_transformer_=lambda res: [r.data() for r in res],
    )


def _base(category: str | None) -> str:
    """Root cause without the escalation marker - see reviewer._base_category."""
    c = (category or "").strip()
    return c[len("escalation:"):] if c.startswith("escalation:") else c


# What a customer might plausibly say per root cause, in symptoms rather than diagnosis.
# Used by --hard; see _complaint_for.
_SYMPTOMS = {
    "address_conflict": "الشحنة لم تصل والمندوب اتصل وقال إن العنوان غير واضح",
    "recipient_unavailable": "لم يصلني شيء ولم أجد أي إشعار من المندوب",
    "hub_delay": "الشحنة واقفة من فترة طويلة ولم تتحرك",
    "failed_attempt_wrong_gate": "المندوب جاء ولم يستطع الوصول إليّ ورجع بالشحنة",
    "failed_attempt_barcode_mismatch": "المندوب قال إن هناك مشكلة في بيانات الشحنة ولم يسلّمها",
    "failed_attempt_weight_mismatch": "المندوب قال إن هناك مشكلة في بيانات الشحنة ولم يسلّمها",
}
_SYMPTOM_FALLBACK = "شحنتي لم تصل ولا أعرف ما المشكلة"


def _complaint_for(case: dict, hard: bool = False) -> str:
    """A customer-style complaint built from the case's own facts.

    The category is never named. But by default the case's `description` is included, and in
    this dataset that field is a restatement of the category in Arabic prose - "تعارض في
    العنوان" for address_conflict, and so on. Classifying from it measures reading
    comprehension, not inference, which is why the default score comes out at or near 100%.

    `hard` replaces it with a symptom-level sentence of the kind a customer would actually
    write: what they noticed, not what was wrong. Several categories deliberately share a
    phrasing - a barcode mismatch and a weight mismatch look identical from the doorstep - so
    the classifier has to separate them using the shipment's event history and precedent, the
    evidence it would really have. That number is the one worth quoting.
    """
    parts = [f"الشحنة {case['shipment_id']}" if case.get("shipment_id") else "شحنتي"]
    if hard:
        parts.append(_SYMPTOMS.get(_base(case.get("true_category")), _SYMPTOM_FALLBACK))
    elif case.get("description"):
        parts.append(str(case["description"]))
    if case.get("city"):
        parts.append(f"في {case['city']}")
    return " ".join(parts)


def _evaluate_one(case: dict, action_stats: dict, hard: bool = False) -> dict:
    fid = case["failure_id"]
    extracted = {
        "shipment_id": case.get("shipment_id"),
        "tracking_id": None,
        "city": case.get("city"),
        "district": case.get("district"),
        "courier": case.get("courier"),
        "category_hint": None,      # withheld: this is what we are predicting
        "raw_text": _complaint_for(case, hard=hard),
    }

    context = retrieve.retrieve_context(extracted, exclude_failure_id=fid)
    # Strip the answer out of the evidence: the live-failure block carries this failure's own
    # recorded category, which the classifier would otherwise simply read back.
    local = dict(context.get("local_subgraph") or {})
    local.pop("live_failure", None)
    context = {**context, "local_subgraph": local, "live_failure_id": None}

    state = {
        "complaint_text": extracted["raw_text"],
        "extracted": extracted,
        "context": context,
        "classification": None, "recommendation": None, "review": None,
        "review_notes": [], "attempted_actions": [], "loop_count": 0,
        "disposition": None, "resolution_id": None, "handover": None,
        "exclude_failure_id": fid,
    }
    state["classification"] = classifier.classify(state)
    state["recommendation"] = recommender.recommend(state)

    predicted_cat = (state["classification"] or {}).get("category")
    predicted_act = (state["recommendation"] or {}).get("action")
    true_cat, true_act = case["true_category"], case["true_action"]

    # How much the retrieved precedent agrees with itself. The model's own confidence turns
    # out to be flat between hits and misses, so the question is whether the evidence carries
    # a signal the model does not: when the neighbours disagree about the category, is the
    # classifier more likely to be wrong?
    cats = [_base(c.get("category")) for c in (context.get("similar_cases") or []) if c.get("category")]
    top_share = (max(Counter(cats).values()) / len(cats)) if cats else 0.0

    stats = action_stats.get((true_cat, predicted_act))
    return {
        "precedent_agreement": round(top_share, 2),
        "precedent_n": len(cats),
        "failure_id": fid,
        "true_category": true_cat,
        "predicted_category": predicted_cat,
        "category_ok": _base(predicted_cat) == _base(true_cat),
        "true_action": true_act,
        "predicted_action": predicted_act,
        "action_ok": predicted_act == true_act,
        # The action isn't what the human did, but history says it works for this root cause.
        "plausible": bool(stats and stats["used"] and stats["ok"] / stats["used"] >= 0.5),
        "confidence": (state["classification"] or {}).get("confidence"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", type=int, default=20, help="how many cases to evaluate")
    ap.add_argument("--seed", type=int, default=0, help="sample seed, for a reproducible run")
    ap.add_argument("--verbose", action="store_true", help="print every case, not just misses")
    ap.add_argument("--hard", action="store_true",
                    help="use symptom-level complaints instead of the dataset's own "
                         "category-restating description - the realistic setting")
    args = ap.parse_args()

    logging.disable(logging.WARNING)

    cases = _read(_HOLDOUT)
    action_stats = {(r["category"], r["action"]): {"used": r["used"], "ok": r["ok"]}
                    for r in _read(_ACTION_STATS)}
    random.Random(args.seed).shuffle(cases)
    sample = cases[: args.n]

    mode = "hard: symptom-level complaints" if args.hard else "easy: dataset description included"
    print(f"Evaluating {len(sample)} of {len(cases)} resolved cases "
          f"(model={config.LLM_MODEL}, seed={args.seed})")
    print(f"Mode - {mode}\n")

    results = []
    for i, case in enumerate(sample, 1):
        try:
            r = _evaluate_one(case, action_stats, hard=args.hard)
        except Exception as exc:  # one bad case must not lose the whole run
            print(f"  [{i}/{len(sample)}] {case['failure_id']} FAILED: {type(exc).__name__}: {exc}")
            continue
        results.append(r)
        if args.verbose or not r["category_ok"]:
            mark = "ok " if r["category_ok"] else "MISS"
            print(f"  [{i}/{len(sample)}] {mark} {r['failure_id']}  "
                  f"true={r['true_category']}  predicted={r['predicted_category']}")
            if args.verbose:
                print(f"         human action: {r['true_action'][:52]}")
                print(f"         agent action: {str(r['predicted_action'])[:52]}"
                      f"{'  [exact]' if r['action_ok'] else '  [plausible]' if r['plausible'] else '  [unsupported]'}")

    if not results:
        print("No cases evaluated.")
        return

    n = len(results)
    cat_ok = sum(r["category_ok"] for r in results)
    act_ok = sum(r["action_ok"] for r in results)
    plausible = sum(r["action_ok"] or r["plausible"] for r in results)

    print(f"\n{'=' * 64}")
    print(f"Root-cause classification : {cat_ok}/{n}  ({100 * cat_ok / n:.0f}%)")
    print(f"Action matches the human  : {act_ok}/{n}  ({100 * act_ok / n:.0f}%)")
    print(f"Action exact or plausible : {plausible}/{n}  ({100 * plausible / n:.0f}%)")
    print("  plausible = not what was done, but historically succeeds for the true category")

    # Does the classifier know when it is wrong? If confidence is as high on the misses as on
    # the hits, it carries no signal and cannot be used as an escalation trigger.
    hit_conf = [r["confidence"] for r in results if r["category_ok"] and r["confidence"] is not None]
    miss_conf = [r["confidence"] for r in results if not r["category_ok"] and r["confidence"] is not None]
    if hit_conf and miss_conf:
        print(f"\nStated confidence when right : {sum(hit_conf)/len(hit_conf):.2f}  "
              f"(min {min(hit_conf):.2f})")
        print(f"Stated confidence when wrong : {sum(miss_conf)/len(miss_conf):.2f}  "
              f"(min {min(miss_conf):.2f})")
        print("  A gap here means confidence could gate escalation; no gap means it cannot.")

    hit_agree = [r["precedent_agreement"] for r in results if r["category_ok"]]
    miss_agree = [r["precedent_agreement"] for r in results if not r["category_ok"]]
    if hit_agree and miss_agree:
        print(f"\nPrecedent agreement when right: {sum(hit_agree)/len(hit_agree):.2f}")
        print(f"Precedent agreement when wrong: {sum(miss_agree)/len(miss_agree):.2f}")
        print("  Share of retrieved cases sharing the majority category - an evidence-side")
        print("  uncertainty signal, independent of what the model claims about itself.")

    misses = Counter(f"{r['true_category']} -> {r['predicted_category']}"
                     for r in results if not r["category_ok"])
    if misses:
        print("\nMost common confusions:")
        for pair, count in misses.most_common(5):
            print(f"  {count}x  {pair}")


if __name__ == "__main__":
    main()
