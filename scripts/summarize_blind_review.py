"""Validate complete blinded editorial scores before revealing model aliases."""
import argparse
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DIMENSIONS = ("factual_fidelity", "evidence_concision", "action_review_consistency",
              "language_clarity", "uncertainty_lifecycle")
MODELS = ("openai/gpt-oss:20b", "openai/gpt-oss:120b")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    directory = args.bundle / "quality-review"
    cases = {case["case_id"]: case for case in read(args.bundle / "runtime_inputs.json")["cases"]}
    records, preferences, reviewers = {}, {}, []
    for filename in ("blind-scores-01-15.json", "blind-scores-16-30.json"):
        packet = read(directory / filename)
        reviewers.append({"source": filename, "review_type": packet["review_type"],
                          "model_blinding": packet["model_blinding"]})
        for record in packet["records"]:
            identity = (record["case_id"], record["alias"])
            assert identity not in records and identity[0] in cases and identity[1] in ("A", "B"), identity
            assert record["complaint_language"] == cases[identity[0]]["language"], identity
            assert record["prose_target"] is None, identity
            values = [record["scores"][dimension] for dimension in DIMENSIONS]
            assert all(value is None or type(value) is int and 0 <= value <= 2 for value in values), identity
            total = sum(values) if None not in values else None
            assert record["total"] == total, identity
            ready = (not record["critical_flags"] and all(record["scores"][key] == 2 for key in
                     ("factual_fidelity", "action_review_consistency", "uncertainty_lifecycle"))
                     and record["scores"]["language_clarity"] in (1, 2) and total is not None and total >= 8)
            assert record["ready_to_show"] == ready, identity
            records[identity] = record
        for preference in packet["preferences"]:
            identity = preference["case_id"]
            assert identity not in preferences and identity in cases, identity
            assert preference["preference"] in ("A", "B", "tie"), identity
            preferences[identity] = preference
    assert set(records) == {(case_id, alias) for case_id in cases for alias in ("A", "B")}, "Incomplete paired scores"
    assert set(preferences) == set(cases), "Incomplete preferences"
    # Do not reveal identities until both complete score packets pass the rubric contract.
    key = read(directory / "model-key.json")
    comparison = read(args.bundle / "comparison.json")
    assert set(key) == set(cases) and set(comparison["models"]) == set(MODELS)
    assert all(set(aliases) == {"A", "B"} and set(aliases.values()) == set(MODELS)
               for aliases in key.values()), "Alias/model mapping must be bijective per case"
    summaries = {}
    for model in MODELS:
        selected = [record for identity, record in records.items() if key[identity[0]][identity[1]] == model]
        assert len(selected) == 30 and comparison["models"][model]["completed_cases"] == 30
        dims = {}
        for dimension in DIMENSIONS:
            values = [record["scores"][dimension] for record in selected if record["scores"][dimension] is not None]
            dims[dimension] = {"assessed": len(values), "not_assessable": 30 - len(values),
                               "mean": round(statistics.mean(values), 3) if values else None,
                               "score_distribution": dict(Counter(values)), "below_two": sum(value < 2 for value in values)}
        totals = [record["total"] for record in selected if record["total"] is not None]
        language_summaries = {}
        for language in ("ar", "en"):
            group = [record for record in selected if record["complaint_language"] == language]
            assessed = [record["scores"]["language_clarity"] for record in group
                        if record["scores"]["language_clarity"] is not None]
            language_summaries[language] = {"n": len(group), "assessed": len(assessed),
                "not_assessable": len(group) - len(assessed),
                "mean_language_clarity": round(statistics.mean(assessed), 3) if assessed else None,
                "ready_to_show": sum(record["ready_to_show"] for record in group)}
        summaries[model] = {"reviewed": 30, "dimensions": dims,
                            "mean_total": round(statistics.mean(totals), 3) if totals else None,
                            "total_assessed": len(totals), "total_not_assessable": 30 - len(totals),
                            "ready_to_show": sum(record["ready_to_show"] for record in selected),
                            "critical_flag_cases": sum(bool(record["critical_flags"]) for record in selected),
                            "critical_flags": dict(Counter(flag for record in selected for flag in record["critical_flags"])),
                            "native_prose_languages": dict(Counter(record["native_prose_language"] for record in selected)),
                            "by_complaint_language": language_summaries}
    preferred = Counter("tie" if value["preference"] == "tie" else key[case_id][value["preference"]]
                        for case_id, value in preferences.items())
    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "reviewers": reviewers,
              "scope": "60 outputs / 30 paired synthetic cases; model-blind AI editorial review, not independent human/SPL gold",
              "models": summaries, "paired_preferences": dict(preferred),
              "false_acceptance_rate": None, "false_rejection_rate": None,
              "limitations": ["Two agent reviewers split the cases; each reviewed both aliases on the same case.",
                              "No output language required; English prompts and Arabic actions are not a prose target.",
                              "Ready-to-show is an editorial threshold, not a safety or correctness guarantee.",
                              "Critical flags can concern blocked or earlier proposals, not executed actions."]}
    (directory / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Blinded operator-output quality review", "", result["scope"], "",
             "Scores were finalized before revealing the per-case model aliases. Five dimensions use 0–2; total is 0–10.", "",
             "| Model | Mean total | Ready to show | Cases with critical flags | Paired preference wins |",
             "|---|---:|---:|---:|---:|"]
    for model, summary in summaries.items():
        lines.append(f"| {model} | {summary['mean_total']} | {summary['ready_to_show']}/30 | {summary['critical_flag_cases']}/30 | {preferred[model]}/30 |")
    lines.extend(["", f"Tied preferences: {preferred['tie']}/30.", "",
                  "| Dimension | 20B mean / below-two cases | 120B mean / below-two cases |", "|---|---:|---:|"])
    for dimension in DIMENSIONS:
        cells = [f"{summary['dimensions'][dimension]['mean']} / {summary['dimensions'][dimension]['below_two']}"
                 for summary in (summaries[model] for model in MODELS)]
        lines.append(f"| {dimension} | " + " | ".join(cells) + " |")
    lines.extend(["", *[f"- {limitation}" for limitation in result["limitations"]]])
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"validated_outputs": len(records), "paired_preferences": dict(preferred), "models": summaries}))


if __name__ == "__main__":
    main()
