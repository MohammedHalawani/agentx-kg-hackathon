"""The Stage 3 report: fixed pass bars, minimum detectable gains, per-category counts and the arms side by side.

Everything a bar depends on is in design.py and was fixed before any case existed; nothing here chooses a threshold
after seeing results. Without scores (a dry run) the same report is written as a skeleton: planned cell sizes, the
budget plan, the bars and the minimum detectable gains at the planned sizes, with every result marked "not run".

Correct answers are also split by level, per arm and per cell, and never pooled back silently:
- observation level: the answer's cause is the code an opening symptom maps to (design.SYMPTOM_CAUSE), that is, what
  B_symptom reads off the alert's own name. Getting it right needs no investigation.
- mechanism level: a correct specific cause that no opening symptom maps to: it had to come from somewhere else.
- abstention: a correct INSUFFICIENT_EVIDENCE or UNKNOWN on a case not knowable at t (unless an opening symptom maps
  to that code, which is observation level by the same rule).
The three add up to the cell's correct count. The pass bars are unchanged: they stay on plain accuracy.

A run paused by its case count (`run --max-cases N`) is reported as an interim look: the title and a paragraph say
how many cases of the pre-registered order it covers and of how many, the pass bars show their counts with no
verdict (the fixed test is on the whole sample), and the validity verdict says interim.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path

from stage3_eval.design import (ABSTAIN, CATEGORIES, DESCRIPTIVE_CELLS, DISCORDANCE_PLANNING, HISTORY_ONLY, MAIN_TEST_CELL,
                                PASS_BARS, PROVIDER_FAILURE_LIMIT, RELEASE_BAR, STRATA, SYMPTOM_CAUSE, WORLDS)
from stage3_eval.stats import mcnemar_exact, minimum_detectable_gain, paired_difference_interval, percentile, wilson

ARM_LABELS = {"agent": "Agent (tools)", "notools": "B_notools", "rulecode": "B_rulecode", "symptom": "B_symptom"}
CORRECT_LEVELS = ("observation", "mechanism", "abstention")


def correct_level(primary_cause, opening_symptoms, correct):
    """The level of a correct answer (None for an answer that is not correct): "observation" when its cause is the
    code an opening symptom maps to, else "abstention" for a correct abstention, else "mechanism"."""
    if not correct:
        return None
    if primary_cause in {SYMPTOM_CAUSE.get(s) for s in opening_symptoms or ()}:
        return "observation"
    return "abstention" if primary_cause in ABSTAIN else "mechanism"


def _levels(rows):
    scored = [r for r in rows if r.get("category") not in (None, "not_run")]
    found = Counter(correct_level(r.get("primary_cause"), r.get("symptoms"), r.get("correct")) for r in scored)
    out = {f"{level}_level" if level != "abstention" else "abstention": found.get(level, 0) for level in CORRECT_LEVELS}
    return {"n": len(scored), "correct": sum(out.values()), **out,
            "mechanism_level_rate": _pct(out["mechanism_level"] / len(scored)) if scored else None}


def _pct(x):
    return None if x is None else round(100 * x, 1)


def _acc(rows, field="correct"):
    scored = [r for r in rows if r.get("category") not in (None, "not_run")]
    k = sum(1 for r in scored if r.get(field))
    lo, hi = wilson(k, len(scored))
    return {"n": len(scored), "correct": k, "rate": _pct(k / len(scored)) if scored else None, "wilson95": [_pct(lo), _pct(hi)]}


def _categories(rows):
    c = Counter(r["category"] for r in rows if r.get("category") not in (None, "not_run"))
    return {k: c.get(k, 0) for k in CATEGORIES}


def _paired(rows_a, rows_b):
    a = {r["key"]: r for r in rows_a if r.get("category") not in (None, "not_run")}
    b = {r["key"]: r for r in rows_b if r.get("category") not in (None, "not_run")}
    keys = sorted(set(a) & set(b))
    both = sum(1 for k in keys if a[k]["correct"] and b[k]["correct"])
    wins = sum(1 for k in keys if a[k]["correct"] and not b[k]["correct"])
    losses = sum(1 for k in keys if not a[k]["correct"] and b[k]["correct"])
    neither = len(keys) - both - wins - losses
    diff, lo, hi = paired_difference_interval(both, wins, losses, neither)
    return {"n": len(keys), "both_correct": both, "agent_only": wins, "baseline_only": losses, "neither": neither,
            "mcnemar_p": round(mcnemar_exact(wins, losses), 4) if keys else None,
            "difference_points": _pct(diff), "difference_95": [_pct(lo), _pct(hi)],
            "discordance": round((wins + losses) / len(keys), 3) if keys else None}


def _mdg(n, observed=None):
    """In points; "undetectable" when no gain up to the discordance itself reaches 80% power at this n."""
    def one(d):
        g = minimum_detectable_gain(n, d)
        return "undetectable" if g is None else _pct(g)
    out = {f"d={d}": one(d) for d in DISCORDANCE_PLANNING} if n else {}
    if n and observed:
        out["observed_discordance"] = one(observed)
    return out


def _cell_rows(scores, world, stratum, arm):
    return [r for r in scores if r["world"] == world and r["stratum"] == stratum and r["arm"] == arm and r.get("phase", "main") == "main"]


INTERIM_VERDICT = "interim (no verdict)"


def interim_look(run_manifest):
    """None, or what an interim report must state: the run was paused by its case count after the first N cases of
    the pre-registered order, of how many."""
    progress = (run_manifest or {}).get("progress") or {}
    if not progress.get("paused"):
        return None
    n, total = progress.get("cases_settled"), progress.get("cases_total")
    return {"cases_settled": n, "cases_total": total, "max_cases": progress.get("max_cases"),
            "statement": f"Interim look over the first {n} of {total} cases in the pre-registered order. The run was paused by the case "
                         "count given on its command line (no result was read to decide the stop), no extra has run, and "
                         "this is not the evaluation's result: the pass bars are tested once, on the whole sample."}


def build_report(selection, *, scores=None, run_manifest=None, ledger_summary=None, canary=None, pairs=None):
    scores = scores or []
    dry = not scores
    interim = interim_look(run_manifest)
    alloc = selection["allocation"]
    planned = defaultdict(int)
    for c in selection["cases"]:
        planned[(c["world"], c["stratum"])] += 1
    cells = []
    for world in WORLDS:
        for stratum in STRATA:
            cell = {"world": world, "stratum": stratum, "allocated": alloc.get(f"{world}/{stratum}", 0), "selected": planned[(world, stratum)],
                    "role": "main test (the only pass or fail)" if (world, stratum) == MAIN_TEST_CELL else DESCRIPTIVE_CELLS.get((world, stratum), "")}
            if not dry:
                arms = {arm: _cell_rows(scores, world, stratum, arm) for arm in ARM_LABELS}
                cell["arms"] = {arm: {"accuracy": _acc(rows), "evidence_grounded": _acc(rows, "evidence_grounded"), "correct_by_level": _levels(rows),
                                      "categories": _categories(rows), "not_run": Counter(r.get("not_run") for r in rows if r.get("category") == "not_run")}
                                for arm, rows in arms.items()}
                cell["paired"] = {b: _paired(arms["agent"], arms[b]) for b in ("rulecode", "notools", "symptom")}
                cell["minimum_detectable_gain_points"] = _mdg(cell["paired"]["rulecode"]["n"], cell["paired"]["rulecode"]["discordance"])
                if stratum == "determined":
                    a, b = cell["arms"]["agent"]["accuracy"]["rate"], cell["arms"]["rulecode"]["accuracy"]["rate"]
                    cell["regression_flag"] = (a is not None and b is not None and a < b)
                wrong_by_conf = Counter(r.get("confidence") for r in arms["agent"] if r.get("category") == "confident_wrong")
                cell["agent_confident_wrong_by_confidence"] = dict(wrong_by_conf)
            else:
                cell["minimum_detectable_gain_points"] = _mdg(cell["selected"])
            cells.append(cell)
    bars = []
    for bar in PASS_BARS:
        world, stratum = bar["cell"]
        entry = {**{k: v for k, v in bar.items() if k != "cell"}, "cell": f"{world}/{stratum}"}
        if dry:
            entry["verdict"] = "not run"
        else:
            p = next(c for c in cells if (c["world"], c["stratum"]) == bar["cell"])["paired"][bar["baseline"]]
            entry["result"] = p
            if not p["n"]:
                entry["verdict"] = "not run"
            elif interim:
                entry["verdict"] = INTERIM_VERDICT      # the counts are shown; the fixed test is on the whole sample
            else:
                entry["verdict"] = "PASS" if (p["mcnemar_p"] < bar["alpha"] and p["agent_only"] > p["baseline_only"]) else "FAIL"
        bars.append(entry)
    report = {"schema": "stage3-report-1", "dry_run": dry, "interim": interim, "selection_n": len(selection["cases"]), "n_main": selection.get("n_main"),
              "sealed_config_hash": selection["sealed_config_hash"], "pass_bars": bars, "cells": cells, "release_bar": RELEASE_BAR,
              "history": HISTORY_ONLY, "ledger": ledger_summary or (run_manifest or {}).get("ledger"), "canary": canary,
              "validity": _validity(selection, run_manifest, canary, scores)}
    if not dry:
        main = [r for r in scores if r.get("phase", "main") == "main"]
        report.update(_details(main, pairs))
        report["extras"] = _extras(scores, run_manifest)
    return report


def _validity(selection, manifest, canary, scores):
    """Amendment 1, H: provider failures over 5% of calls, a crash, a sealed-hash mismatch, a canary or vocabulary hit."""
    if not manifest:
        return {"verdict": "not run"}
    reasons = []
    # A run taken in parts (paused and resumed) is judged over every part: each process counted its own model calls.
    earlier = manifest.get("earlier_segments") or []
    provs = [s.get("provenance") or {} for s in earlier] + [manifest.get("provenance") or {}]
    ok = sum(sum(((p.get("model_calls") or {}).get("succeeded") or {}).values()) for p in provs)
    failed = sum(sum(((p.get("model_calls") or {}).get("failed") or {}).values()) for p in provs)
    rate = failed / (ok + failed) if (ok + failed) else None
    interim = interim_look(manifest)
    if rate is not None and rate > PROVIDER_FAILURE_LIMIT:
        reasons.append(f"provider failures {round(100 * rate, 1)}% of calls (limit {int(100 * PROVIDER_FAILURE_LIMIT)}%)")
    if manifest.get("status") != "completed" and not (interim and manifest.get("status") == "paused"):
        reasons.append(f"run did not complete: {manifest.get('status')}")
    not_paused = [str(s.get("status")) for s in earlier if s.get("status") != "paused"]
    if not_paused:
        reasons.append(f"an earlier part of this run did not end as paused: {'; '.join(not_paused)}")
    if manifest.get("sealed_config_hash") != selection["sealed_config_hash"]:
        reasons.append("configuration hash differs from the sealed selection")
    if any(p.get("dirty_tree") or p.get("tree_changed_during_run") for p in provs):
        reasons.append("code tree dirty or changed during the run")
    if canary and canary.get("verdict") == "invalid":
        reasons.append("canary or truth vocabulary found in a runtime surface")
    if any(r.get("unsafe_reasons") and "truth vocabulary in the output" in r["unsafe_reasons"] for r in scores):
        reasons.append("truth vocabulary in an arm's output")
    if manifest.get("dry_run"):
        return {"verdict": "dry run (no calls; nothing to validate)", "reasons": reasons}
    incomplete = canary is None or canary.get("verdict") == "incomplete"
    verdict = "invalid" if reasons else ("valid pending a complete canary scan" if incomplete else "valid")
    out = {"verdict": verdict, "reasons": reasons, "provider_failure_rate": _pct(rate),
           "canary_missing_surfaces": (canary or {}).get("missing_surfaces")}
    if interim and not reasons:
        out["verdict"] = (f"interim: paused after {interim['cases_settled']} of {interim['cases_total']} cases, not a final result"
                          + (" (canary scan not complete)" if incomplete else " (nothing invalid so far)"))
    if earlier:
        # Disclosed, not judged here: a commit made between two parts (the interim report itself, say) changes this.
        out["parts"] = len(provs)
        out["commits_across_parts"] = sorted({str(p["commit"]) for p in provs if p.get("commit")})
    return out


def _details(scores, pairs):
    agent = [r for r in scores if r["arm"] == "agent" and r.get("category") != "not_run"]
    rule = {r["key"]: r for r in scores if r["arm"] == "rulecode" and r.get("category") != "not_run"}
    out = {}
    # Abstention (amendment 1, E), every scored agent case.
    unknowable = [r for r in agent if not r["knowable_at_t"]]
    abstained = [r for r in agent if r["abstained"]]
    answered = [r for r in agent if not r["abstained"] and r["category"] != "degraded"]
    auto = lambda r: any(str(e.get("authority") or "").startswith("AUTO") for e in r.get("executions") or [])
    out["abstention"] = {
        "coverage": _pct(len(answered) / len(agent)) if agent else None,
        "abstention_rate": _pct(len(abstained) / len(agent)) if agent else None,
        "accuracy_when_answering": _acc(answered),
        "insufficient_precision": _pct(sum(1 for r in abstained if not r["knowable_at_t"]) / len(abstained)) if abstained else None,
        "insufficient_recall": _pct(sum(1 for r in unknowable if r["abstained"]) / len(unknowable)) if unknowable else None,
        "unknowable_escalated_without_automatic_action": sum(1 for r in unknowable if r["abstained"] and not auto(r)),
        "unknowable_with_automatic_action": sum(1 for r in unknowable if auto(r)),
        "unknowable_cases": len(unknowable)}
    # Agreement with B_rulecode and accuracy where the agent departs (amendment 1, I).
    paired = [(r, rule[r["key"]]) for r in agent if r["key"] in rule]
    depart = [r for r, b in paired if r["primary_cause"] != b["primary_cause"]]
    out["versus_rulecode"] = {"agreement": _pct(1 - len(depart) / len(paired)) if paired else None, "departures": len(depart),
                              "accuracy_on_departures": _acc(depart)}
    # Symptom-name dependence (section 4).
    out["symptom_name_dependence"] = {"opening_symptom_names_an_acceptable_cause": _acc([r for r in agent if r.get("symptom_names_acceptable") is True]),
                                      "no_opening_symptom_names_one": _acc([r for r in agent if r.get("symptom_names_acceptable") is False])}
    # Citations (section 4).
    with_cites = [r for r in agent if (r.get("citations") or {}).get("cited")]
    out["citations"] = {"conclusions_citing": len(with_cites), "conclusions_without_citations": len(agent) - len(with_cites),
                        "all_citations_valid": _pct(sum(1 for r in with_cites if r["citations"]["all_valid"]) / len(with_cites)) if with_cites else None,
                        "resolution_checked": all(r["citations"].get("resolution_checked") for r in with_cites) if with_cites else None,
                        "evidence_grounded_accuracy": _acc(agent, "evidence_grounded")}
    # Reviewer verdict against correctness (section 7).
    out["reviewer"] = {f"{v}/{'correct' if c else 'wrong'}": n for (v, c), n in sorted(Counter((r.get("review_verdict"), r["correct"]) for r in agent).items(), key=str)}
    # Cause sets (section 1).
    rec = [r["cause_set_recall"] for r in agent if r.get("cause_set_recall") is not None]
    pre = [r["cause_set_precision"] for r in agent if r.get("cause_set_precision") is not None]
    out["cause_sets"] = {"mean_recall": _pct(sum(rec) / len(rec)) if rec else None, "mean_precision": _pct(sum(pre) / len(pre)) if pre else None}
    # Per mechanism (scorer side) for agent and B_rulecode.
    per = defaultdict(lambda: {"agent": [0, 0], "rulecode": [0, 0]})
    for r in scores:
        if r["arm"] in ("agent", "rulecode") and r.get("category") != "not_run":
            for m in r.get("mechanism_types") or []:
                per[m][r["arm"]][0] += bool(r["correct"])
                per[m][r["arm"]][1] += 1
    out["per_mechanism"] = {m: {a: f"{v[0]}/{v[1]}" for a, v in d.items()} for m, d in sorted(per.items())}
    # Matched pairs (amendment 1, J).
    if pairs:
        by_key = {r["key"]: r for r in agent}
        result = defaultdict(lambda: {"pairs": 0, "scored": 0, "hit": 0})
        for p in pairs.get("pairs", []):
            a, b = (by_key.get(k) for k in p["cases"])
            entry = result[p["kind"]]
            entry["pairs"] += 1
            if a and b:
                entry["scored"] += 1
                if p["kind"] == "same_symptoms_different_cause":
                    entry["hit"] += bool(a["correct"] and b["correct"] and a["primary_cause"] != b["primary_cause"])
                else:
                    entry["hit"] += bool(a["correct"] and b["correct"])
        out["matched_pairs"] = {k: {**v, "meaning": "both correct and different" if k.startswith("same_symptoms") else "both correct (consistency)"}
                                for k, v in result.items()}
    # Usage, latency, reliability (section 7; amendment 1, K).
    calls = [r["calls_used"] for r in agent if r.get("calls_used") is not None]
    walls = [r["wall_seconds"] for r in agent if r.get("wall_seconds") is not None]
    tools = [s for r in agent for s in r.get("tool_seconds") or []]
    out["usage"] = {"agent_calls_per_case": {"p50": percentile(calls, 50), "p90": percentile(calls, 90), "max": max(calls) if calls else None},
                    "agent_tokens": sum(r.get("tokens") or 0 for r in agent),
                    "investigation_seconds": {f"p{q}": percentile(walls, q) for q in (50, 90, 99)},
                    "tool_query_seconds": {f"p{q}": percentile(tools, q) for q in (50, 95)},
                    "cap_hits": sum(1 for r in agent if r.get("cap_hit")), "degraded": sum(1 for r in agent if r["category"] == "degraded"),
                    "notools_degraded": sum(1 for r in scores if r["arm"] == "notools" and r.get("category") == "degraded")}
    # Outcomes (amendment 1, K) as far as the run's records carry them.
    executions = [(r, e) for r in agent for e in r.get("executions") or []]
    auto_exec = [(r, e) for r, e in executions if str(e.get("authority") or "").startswith("AUTO")]
    resolved = [r for r in agent if r.get("final_state") == "RESOLVED"]
    out["outcomes"] = {"automatic_executions": len(auto_exec), "wrong_automatic_actions": sum(1 for r, _ in auto_exec if not r["correct"]),
                       "closures": len(resolved), "closures_on_wrong_diagnosis": sum(1 for r in resolved if not r["correct"]),
                       "premature_closures": "needs re-detection records within 24 simulated hours (Stage 4 run data)",
                       "verifier_verdicts_against_truth": "needs Stage 4 outcome records",
                       "human_interventions_per_case": _pct(sum(1 for r in agent if r.get("final_state") in ("ESCALATED", "AWAITING_APPROVAL", "HUMAN_REVIEW")) / len(agent)) if agent else None}
    out["stratum_moved_at_t"] = sum(1 for r in agent if r.get("stratum_moved"))
    return out


def _extras(scores, manifest):
    extras = [r for r in scores if r.get("phase") == "extras"]
    agent = {r["key"]: r for r in scores if r["arm"] == "agent" and r.get("phase", "main") == "main" and r.get("category") != "not_run"}
    out = {"note": "exploratory: fixed order, no pass or fail, never pooled into the E1 test", "run": (manifest or {}).get("extras")}
    abl = [r for r in extras if r["arm"] == "cross_shipment_ablation" and r.get("category") != "not_run"]
    if abl:
        out["cross_shipment_ablation"] = _paired([agent[r["key"]] for r in abl if r["key"] in agent], abl)
    stab = [r for r in extras if r["arm"] == "stability_rerun" and r.get("category") != "not_run" and r["key"] in agent]
    if stab:
        out["stability_rerun"] = {"n": len(stab), "same_primary": sum(1 for r in stab if r["primary_cause"] == agent[r["key"]]["primary_cause"]),
                                  "same_correctness": sum(1 for r in stab if r["correct"] == agent[r["key"]]["correct"])}
    return out


# ------------------------------------------------------------------------------------------------------ markdown
def _fmt_acc(a):
    if not a or not a["n"]:
        return "not run"
    return f"{a['correct']}/{a['n']} ({a['rate']}%, {a['wilson95'][0]}-{a['wilson95'][1]})"


def render_markdown(report):
    interim = report.get("interim")
    title = "# Stage 3 blind evaluation report"
    if interim:
        title += f" (INTERIM: first {interim['cases_settled']} of {interim['cases_total']} cases in the pre-registered order)"
    lines = [title + (" (dry-run skeleton)" if report["dry_run"] else ""), "",
             "All data is synthetic. Nothing here describes real SPL operations.", "",
             *([f"**{interim['statement']}**", ""] if interim else []),
             f"Sealed configuration: `{report['sealed_config_hash'][:16]}`. Cases selected: {report['selection_n']} (N_main {report['n_main']}).", ""]
    lines += ["## Pass bars (fixed before any case existed)", "", "| Bar | Cell | Test | Verdict | Agent only / baseline only | p |", "|---|---|---|---|---|---|"]
    for b in report["pass_bars"]:
        r = b.get("result") or {}
        lines.append(f"| {b['id']} | {b['cell']} | {b['test']}, alpha {b['alpha']}, {b['also_requires']} | **{b['verdict']}** | "
                     f"{r.get('agent_only', '-')} / {r.get('baseline_only', '-')} | {r.get('mcnemar_p', '-')} |")
    lines += ["", f"Release bar: {report['release_bar']}.", f"History: {report['history']}.", "",
              "## Cells and minimum detectable gain", "",
              "Minimum detectable gain: exact two-sided McNemar, alpha 0.05, 80% power, in points, at the cell's size.", "",
              "| World / stratum | Role | Allocated | Selected | MDG at d=0.35 | MDG at d=0.45 | MDG at observed d |", "|---|---|---|---|---|---|---|"]
    for c in report["cells"]:
        m = c["minimum_detectable_gain_points"]
        lines.append(f"| {c['world']} / {c['stratum']} | {c['role']} | {c['allocated']} | {c['selected']} | {m.get('d=0.35', '-')} | "
                     f"{m.get('d=0.45', '-')} | {m.get('observed_discordance', '-')} |")
    if not report["dry_run"]:
        lines += ["", "## Arms side by side (plain accuracy; Wilson 95%)", "", "| World / stratum | " + " | ".join(ARM_LABELS.values()) + " |",
                  "|---|" + "---|" * len(ARM_LABELS)]
        for c in report["cells"]:
            lines.append(f"| {c['world']} / {c['stratum']} | " + " | ".join(_fmt_acc(c["arms"][a]["accuracy"]) for a in ARM_LABELS) + " |")
        lines += ["", "## Correct answers by level, per arm and stratum", "",
                  "Observation level: the cause is the code an opening symptom maps to (what the alert's own name gives). Mechanism level: "
                  "a correct specific cause that no opening symptom maps to. Abstention: a correct INSUFFICIENT_EVIDENCE or UNKNOWN. "
                  "The three add up to the correct count; the pass bars stay on plain accuracy.", "",
                  "| World / stratum | Arm | Scored | Correct | Observation level | Mechanism level | Abstention |", "|---|---|---|---|---|---|---|"]
        for c in report["cells"]:
            for a in ARM_LABELS:
                v = c["arms"][a].get("correct_by_level") or {}
                if v.get("n"):
                    lines.append(f"| {c['world']} / {c['stratum']} | {ARM_LABELS[a]} | {v['n']} | {v['correct']} | {v['observation_level']} | "
                                 f"{v['mechanism_level']} | {v['abstention']} |")
        lines += ["", "## Answer categories per arm (honest uncertainty is never pooled with confident wrong answers)", ""]
        lines += ["| World / stratum | Arm | " + " | ".join(CATEGORIES) + " |", "|---|---|" + "---|" * len(CATEGORIES)]
        for c in report["cells"]:
            for a in ARM_LABELS:
                cats = c["arms"][a]["categories"]
                if sum(cats.values()):
                    lines.append(f"| {c['world']} / {c['stratum']} | {ARM_LABELS[a]} | " + " | ".join(str(cats[k]) for k in CATEGORIES) + " |")
        flags = [f"{c['world']}/{c['stratum']}" for c in report["cells"] if c.get("regression_flag")]
        lines += ["", f"Determined-stratum regressions against B_rulecode: {', '.join(flags) if flags else 'none'}."]
        for section in ("abstention", "versus_rulecode", "symptom_name_dependence", "citations", "reviewer", "cause_sets", "matched_pairs",
                        "usage", "outcomes", "per_mechanism", "extras"):
            if section in report:
                lines += ["", f"## {section.replace('_', ' ').capitalize()}", "", "```", json.dumps(report[section], indent=1, sort_keys=True, default=str), "```"]
        lines += ["", f"Cases whose knowability at t differs from the pre-registered stratum: {report.get('stratum_moved_at_t')}."]
    else:
        lines += ["", "## Results", "", "Not run: this is a dry run. No model call was made."]
    lines += ["", "## Budget ledger", "", "```", json.dumps(report["ledger"], indent=1, sort_keys=True, default=str), "```",
              "", "## Run validity (amendment 1, H)", "", "```", json.dumps(report["validity"], indent=1, sort_keys=True, default=str), "```"]
    if report.get("canary"):
        lines += ["", "## Canary scan", "", "```", json.dumps(report["canary"], indent=1, sort_keys=True, default=str), "```"]
    return "\n".join(lines) + "\n"


def write_report(out_dir, report):
    out_dir = Path(out_dir)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return out_dir / "report.md"
