"""The stratum script (amendment 1, E and F; amendment 2). Scorer side, run before any agent run.

Each opened abnormal shipment of an evaluation world gets one stratum, from truth knowable at its opening:

- unidentifiable: nothing discriminates any explaining mechanism at the opening. Outside the main test; there
  INSUFFICIENT_EVIDENCE with escalation and no automatic action is the correct answer.
- determined: identifiable, and its opening symptom set is determined: one cause code is acceptable for every
  identifiable shipment in the world's census that opens with that set. The census decides when the set has at least
  STRATUM_MIN_SUPPORT (5) identifiable shipments; below that the generator's mechanism-to-symptom map decides
  (truth `shares_opening_with`: no other cause opens with this set anywhere in the world).
- identifiable_ambiguous: identifiable and not determined. E1's cells of this stratum are the main test.

Unidentifiable shipments are left out of the census: whatever their symptom set, their answer is
INSUFFICIENT_EVIDENCE, which is not a cause another answer could share.

`determined_symptom_sets` is the rule on its own, so a test can reproduce the Stage 0 split of S5 (19 determined,
22 ambiguous) with Stage 0's parameters (eventual labels, any support, no fallback), as amendment 1, F asks.
"""
from collections import defaultdict

from stage3_eval.design import STRATUM_MIN_SUPPORT
from stage3_eval.truth_io import explaining_mechanisms, truth_at


def determined_symptom_sets(groups, *, min_support=STRATUM_MIN_SUPPORT):
    """groups: {symptom set: [acceptable cause set per shipment]}. Returns {symptom set: True | False | None}:
    True when one cause is acceptable for every shipment, False when none is, None when the set has fewer than
    `min_support` shipments (the caller's fallback decides)."""
    out = {}
    for key, sets in groups.items():
        if len(sets) < min_support:
            out[key] = None
        else:
            out[key] = bool(frozenset.intersection(*[frozenset(s) for s in sets]))
    return out


def opened_cases(truth, replay_rows):
    """The opened shipments of an export's live split with what the stratum needs, at each opening.
    Healthy shipments the monitor opened are returned apart (they have no cause to diagnose)."""
    cases, healthy_opened = [], []
    for sid, rep in sorted(replay_rows.items()):
        if not rep.get("opened_at"):
            continue
        row = truth[sid]
        if row.get("healthy"):
            healthy_opened.append(sid)
            continue
        codes = rep.get("opening_codes")
        at = truth_at(row, rep["opened_at"], None, opening_codes=codes)
        explaining = explaining_mechanisms(row, codes)
        cases.append({"shipment_id": sid, "opened_at": rep["opened_at"], "symptoms": tuple(sorted(rep.get("opening_symptoms") or [])),
                      "identifiable": at.identifiable, "acceptable": at.acceptable, "mechanism_types": at.mechanism_types,
                      "shared_with_other_causes": any(m.get("discrimination", {}).get("shares_opening_with") for m in explaining)})
    return cases, healthy_opened


def assign_strata(cases, *, min_support=STRATUM_MIN_SUPPORT):
    """{shipment_id: stratum} and the census table that decided it."""
    groups = defaultdict(list)
    for c in cases:
        if c["identifiable"]:
            groups[c["symptoms"]].append(c["acceptable"])
    verdict = determined_symptom_sets(groups, min_support=min_support)
    strata, rule = {}, {}
    for c in cases:
        if not c["identifiable"]:
            strata[c["shipment_id"]], rule[c["shipment_id"]] = "unidentifiable", "nothing discriminating at opening"
            continue
        decided = verdict.get(c["symptoms"])
        if decided is None:
            determined, how = not c["shared_with_other_causes"], "generator map (fewer than %d in census)" % min_support
        else:
            determined, how = decided, "census"
        strata[c["shipment_id"]] = "determined" if determined else "identifiable_ambiguous"
        rule[c["shipment_id"]] = how
    census = {" + ".join(k) or "(none)": {"identifiable_shipments": len(v), "determined": verdict[k]} for k, v in sorted(groups.items())}
    return strata, rule, census
