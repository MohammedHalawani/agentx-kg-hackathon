"""Fixed pass bars, regressions, validity and the skeleton."""
import json

from stage3_eval.report import build_report, render_markdown


def _selection(n_main_cases=30):
    cases = [{"key": f"E1:S{i}", "world": "E1", "shipment_id": f"S{i}", "stratum": "identifiable_ambiguous", "main_test": True, "order": i}
             for i in range(n_main_cases)]
    cases += [{"key": f"E1:D{i}", "world": "E1", "shipment_id": f"D{i}", "stratum": "determined", "main_test": False, "order": 100 + i} for i in range(10)]
    return {"cases": cases, "allocation": {"E1/identifiable_ambiguous": 160, "E1/determined": 30}, "n_main": 285, "sealed_config_hash": "h" * 64}


def _row(key, arm, correct, stratum="identifiable_ambiguous", category=None):
    category = category or ("correct_supported" if correct and arm == "agent" else "correct_unsupported" if correct else "confident_wrong")
    return {"key": key, "world": "E1", "stratum": stratum, "arm": arm, "category": category, "correct": correct,
            "evidence_grounded": category == "correct_supported", "phase": "main", "knowable_at_t": True, "abstained": False,
            "primary_cause": "A" if correct else "B", "citations": {"cited": 1, "all_valid": True, "resolution_checked": True}}


def _scores(wins, losses, both, neither):
    rows, i = [], 0
    for agent_ok, base_ok, count in ((True, False, wins), (False, True, losses), (True, True, both), (False, False, neither)):
        for _ in range(count):
            key = f"E1:S{i}"
            rows += [_row(key, "agent", agent_ok), _row(key, "rulecode", base_ok), _row(key, "notools", base_ok), _row(key, "symptom", False)]
            i += 1
    return rows


MANIFEST = {"status": "completed", "sealed_config_hash": "h" * 64, "provenance": {"model_calls": {"succeeded": {"m": 100}, "failed": {"m": 2}}}}
CLEAN = {"verdict": "clean", "missing_surfaces": []}


def test_pass_when_significant_with_more_wins():
    r = build_report(_selection(), scores=_scores(14, 2, 10, 4), run_manifest=MANIFEST, canary=CLEAN)
    assert [b["verdict"] for b in r["pass_bars"]] == ["PASS", "PASS"]
    assert r["pass_bars"][0]["result"]["agent_only"] == 14


def test_fail_when_not_significant_or_more_losses():
    r = build_report(_selection(), scores=_scores(6, 5, 10, 9), run_manifest=MANIFEST, canary=CLEAN)
    assert {b["verdict"] for b in r["pass_bars"]} == {"FAIL"}
    r = build_report(_selection(), scores=_scores(2, 14, 10, 4), run_manifest=MANIFEST, canary=CLEAN)
    assert {b["verdict"] for b in r["pass_bars"]} == {"FAIL"}   # significant, but the baseline wins


def test_determined_regression_is_flagged():
    scores = _scores(10, 2, 10, 4) + [x for i in range(10) for x in (_row(f"E1:D{i}", "agent", i < 5, "determined"),
                                                                     _row(f"E1:D{i}", "rulecode", True, "determined"))]
    r = build_report(_selection(), scores=scores, run_manifest=MANIFEST, canary=CLEAN)
    cell = next(c for c in r["cells"] if c["stratum"] == "determined" and c["world"] == "E1")
    assert cell["regression_flag"] is True


def test_honest_uncertainty_is_counted_apart_from_confident_wrong():
    scores = _scores(5, 1, 5, 0)
    scores.append({**_row("E1:S11", "agent", True, category="honest_uncertainty"), "abstained": True, "knowable_at_t": False})
    scores.append({**_row("E1:S12", "agent", False, category="confident_wrong")})
    r = build_report(_selection(), scores=scores, run_manifest=MANIFEST, canary=CLEAN)
    cats = next(c for c in r["cells"] if c["stratum"] == "identifiable_ambiguous" and c["world"] == "E1")["arms"]["agent"]["categories"]
    assert cats["honest_uncertainty"] == 1 and cats["confident_wrong"] == 2


def test_validity_rules():
    assert build_report(_selection(), scores=_scores(5, 1, 5, 0), run_manifest=MANIFEST, canary=CLEAN)["validity"]["verdict"] == "valid"
    bad = {**MANIFEST, "provenance": {"model_calls": {"succeeded": {"m": 90}, "failed": {"m": 10}}}}
    v = build_report(_selection(), scores=_scores(5, 1, 5, 0), run_manifest=bad, canary=CLEAN)["validity"]
    assert v["verdict"] == "invalid" and "provider failures" in v["reasons"][0]
    v = build_report(_selection(), scores=_scores(5, 1, 5, 0), run_manifest=MANIFEST, canary={"verdict": "invalid"})["validity"]
    assert v["verdict"] == "invalid"
    v = build_report(_selection(), scores=_scores(5, 1, 5, 0), run_manifest=MANIFEST, canary={"verdict": "incomplete", "missing_surfaces": ["logs"]})["validity"]
    assert v["verdict"] == "valid pending a complete canary scan"
    v = build_report(_selection(), scores=_scores(5, 1, 5, 0), run_manifest={**MANIFEST, "sealed_config_hash": "x"}, canary=CLEAN)["validity"]
    assert "configuration hash differs from the sealed selection" in v["reasons"]


def test_skeleton_states_planned_sizes_and_mdg():
    r = build_report(_selection(160))
    assert r["dry_run"] and all(b["verdict"] == "not run" for b in r["pass_bars"])
    main = next(c for c in r["cells"] if c["stratum"] == "identifiable_ambiguous" and c["world"] == "E1")
    assert main["selected"] == 160 and 13 <= main["minimum_detectable_gain_points"]["d=0.35"] <= 14
    md = render_markdown(r)
    assert "dry-run skeleton" in md and "Minimum detectable gain" in md
    json.dumps(r)


def test_correct_answers_are_split_into_observation_level_and_mechanism_level_per_arm_and_stratum():
    """A correct answer is observation level when its cause is the code an opening symptom maps to (B_symptom's table),
    mechanism level when no opening symptom maps to it; both counts are reported per arm and per cell."""
    from stage3_eval.report import correct_level
    assert correct_level("MISSED_MILESTONE", ["MILESTONE_OVERDUE"], True) == "observation"
    assert correct_level("HUB_DELAY", ["MILESTONE_OVERDUE"], True) == "mechanism"
    assert correct_level("WRONG_GATE", ["DELIVERY_ATTEMPT_FAILED"], True) == "mechanism"        # the symptom maps to RECIPIENT_UNAVAILABLE
    assert correct_level("INSUFFICIENT_EVIDENCE", ["MILESTONE_OVERDUE"], True) == "abstention"
    assert correct_level("INSUFFICIENT_EVIDENCE", ["EVIDENCE_MISSING"], True) == "observation"  # the same rule: the symptom maps to it
    assert correct_level("MISSED_MILESTONE", ["MILESTONE_OVERDUE"], False) is None

    def row(i, arm, cause, correct, stratum="identifiable_ambiguous", symptoms=("MILESTONE_OVERDUE",), category=None):
        prefix = "S" if stratum == "identifiable_ambiguous" else "D"
        return {**_row(f"E1:{prefix}{i}", arm, correct, stratum, category), "primary_cause": cause, "symptoms": list(symptoms)}
    scores = []
    for i in range(6):                                   # agent: 3 mechanism level, 1 observation level, 1 abstention, 1 wrong
        cause, ok, category = [("HUB_DELAY", True, None), ("HUB_DELAY", True, None), ("ROUTE_DELAY", True, None), ("MISSED_MILESTONE", True, None),
                               ("INSUFFICIENT_EVIDENCE", True, "honest_uncertainty"), ("CUSTODY_GAP", False, None)][i]
        scores.append(row(i, "agent", cause, ok, category=category))
        scores.append(row(i, "symptom", "MISSED_MILESTONE", i == 3))             # B_symptom: right once, at observation level by construction
        scores.append(row(i, "rulecode", "MISSED_MILESTONE", i == 3))
        scores.append(row(i, "notools", "HUB_DELAY", i < 2))                     # right twice, at mechanism level
    for i in range(4):                                   # determined: the symptom's own name gives the cause
        scores.append(row(i, "agent", "WEIGHT_MISMATCH", True, "determined", ("WEIGHT_READ_DIFFERS",)))
        scores.append(row(i, "rulecode", "WEIGHT_MISMATCH", True, "determined", ("WEIGHT_READ_DIFFERS",)))
    scores.append({**row(9, "agent", None, None), "category": "not_run"})        # not scored, not counted
    report = build_report(_selection(), scores=scores, run_manifest=MANIFEST, canary=CLEAN)
    cell = {c["stratum"]: c for c in report["cells"] if c["world"] == "E1"}
    levels = {arm: v["correct_by_level"] for arm, v in cell["identifiable_ambiguous"]["arms"].items()}
    assert levels["agent"] == {"n": 6, "correct": 5, "observation_level": 1, "mechanism_level": 3, "abstention": 1, "mechanism_level_rate": 50.0}
    assert (levels["symptom"]["observation_level"], levels["symptom"]["mechanism_level"]) == (1, 0)
    assert (levels["notools"]["observation_level"], levels["notools"]["mechanism_level"]) == (0, 2)
    for arm, v in cell["identifiable_ambiguous"]["arms"].items():          # the split never changes the correct count
        assert v["correct_by_level"]["correct"] == v["accuracy"]["correct"], arm
    determined = cell["determined"]["arms"]["agent"]["correct_by_level"]
    assert (determined["observation_level"], determined["mechanism_level"], determined["correct"]) == (4, 0, 4)
    md = render_markdown(report)
    assert "## Correct answers by level, per arm and stratum" in md
    assert "| E1 / identifiable_ambiguous | Agent (tools) | 6 | 5 | 1 | 3 | 1 |" in md
    assert "| E1 / determined | Agent (tools) | 4 | 4 | 4 | 0 | 0 |" in md
