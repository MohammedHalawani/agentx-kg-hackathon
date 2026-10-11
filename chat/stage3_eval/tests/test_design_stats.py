"""The frozen design constants and the statistics."""
import dataclasses

import pytest

from stage3_eval import design
from stage3_eval.selection import allocate
from stage3_eval.stats import mcnemar_exact, mcnemar_power, minimum_detectable_gain, paired_difference_interval, percentile, wilson


def test_the_design_commits_name_every_amendment_and_the_cap_is_sealed_not_planned():
    import subprocess
    from pathlib import Path
    assert design.DESIGN_COMMITS == {"frozen": "b1d331f", "amendment_1": "001bcbf", "amendment_2": "ac6f857", "addendum_2": "7af0d5c",
                                     "amendment_3": "15514ac", "addendum_3": "6f0ed49"}
    root = Path(__file__).resolve().parents[3]
    try:
        touched = subprocess.check_output(["git", "log", "--format=%h", "--abbrev=7", "--", design.DESIGN_DOCUMENT], cwd=root, text=True).split()
    except Exception:
        touched = None                                  # no git history here (an export of the tree): the names above stand
    if touched:
        assert set(design.DESIGN_COMMITS.values()) <= set(touched)   # each is a commit of the design document
    # Amendment 3: C_cap 16 and the budget left before the stop line, both sealed at selection; 12 is only the planning value.
    assert design.C_CAP_PLANNING == 12 and design.worst_case_per_case(16) == 18
    assert design.n_main(16, budget=design.evaluation_budget(173)) == 190
    assert allocate(16, budget=design.evaluation_budget(173))["cells"][design.MAIN_TEST_CELL] == 105


def test_the_lifted_budget_gates_nothing_and_the_worst_case_is_arithmetic(monkeypatch):
    """2026-10-11: the 4,000 cap and the 3,600 stop line stay as historical constants; neither is part of what is
    sealed, a configuration has no budget until `select` seals one, and a stop line exists only when one is given."""
    assert (design.CALL_BUDGET, design.STAGE3_STOP_AT, design.STABILITY_MAX) == (4000, 3600, 40)
    assert sum(design.ALLOCATION_AT_PLANNING.values()) == 285
    config = design.EvalConfig(freeze_commit="a" * 40)
    assert config.budget is None and config.stop_at is None and "stop_at" not in config.as_dict() and "reserve" not in config.as_dict()
    sealed = design.sealed_hash(config)
    monkeypatch.setattr(design, "STAGE3_STOP_AT", 1)
    monkeypatch.setattr(design, "CALL_BUDGET", 1)
    assert design.sealed_hash(config) == sealed
    assert design.sealed_hash(dataclasses.replace(config, stop_at=3600)) != sealed
    assert dataclasses.replace(config, stop_at=3600).as_dict()["stop_at"] == 3600
    # 285 cases at C_cap 16, the ablation on 100 of them and the stability rerun on 40.
    assert design.worst_case_calls(285, 100, 40, 16) == {"main": 285 * 18, "cross_shipment_ablation": 1600, "stability_rerun": 640,
                                                         "total": 285 * 18 + 1600 + 640}
    assert design.worst_case_calls(10, 0, 0, 12, r_cap=2)["total"] == 10 * 16
    with pytest.raises(ValueError):
        design.worst_case_calls(1, 0, 0, 0)


def test_n_main_and_planning_allocation_match_amendment_2():
    assert design.n_main(12) == 285
    assert design.n_main(12, r_cap=2) == 250            # addendum item 1: R_cap joins the denominator
    a = allocate(12)
    assert a["n_main"] == 285 and a["cells"] == design.ALLOCATION_AT_PLANNING and not a["notes"]


def test_shrink_order_removes_unidentifiable_then_determined_then_e2_then_e1():
    a = allocate(14)                                    # N_main = 250: 35 fewer cases
    c = a["cells"]
    assert sum(c.values()) == 250
    assert c[("E1", "unidentifiable")] + c[("E2", "unidentifiable")] == 15
    assert c[("E1", "determined")] + c[("E2", "determined")] == 30
    assert c[("E2", "identifiable_ambiguous")] == 45 and c[("E1", "identifiable_ambiguous")] == 160
    b = allocate(20)                                    # N_main = 181: E2 at its floor of 40, then E1 shrinks
    assert b["cells"][("E2", "identifiable_ambiguous")] == 40
    assert b["cells"][("E1", "identifiable_ambiguous")] == 181 - 15 - 30 - 40
    assert b["notes"], "E1 below 150 must be stated"


def test_the_historical_worst_case_plan_always_fitted_the_old_cap():
    for c_cap in range(4, 30):
        for r_cap in (0, 2, 4):
            total = sum(allocate(c_cap, r_cap)["cells"].values())
            assert total * design.worst_case_per_case(c_cap, r_cap) <= design.CALL_BUDGET


def test_eval_seed_is_derived_from_the_full_freeze_commit():
    commit = "0123456789abcdef0123456789abcdef01234567"
    assert design.eval_seed(commit, 1) == int(__import__("hashlib").sha256(f"{commit}:1".encode()).hexdigest()[:8], 16)
    assert design.eval_seed(commit, 1) != design.eval_seed(commit, 2)
    with pytest.raises(ValueError):
        design.eval_seed("abc1234", 1)
    with pytest.raises(ValueError):
        design.eval_seed(commit, 3)


def test_sealed_hash_moves_with_any_frozen_value(monkeypatch):
    config = design.EvalConfig(freeze_commit="a" * 40)
    h = design.sealed_hash(config)
    assert h == design.sealed_hash(design.EvalConfig(freeze_commit="a" * 40))
    assert h != design.sealed_hash(dataclasses.replace(config, c_cap=13))
    monkeypatch.setitem(design.SYMPTOM_CAUSE, "DELIVERY_ATTEMPT_FAILED", "ADDRESS_CONFLICT")
    assert h != design.sealed_hash(config)


def test_baseline_tables_cover_every_monitor_symptom_and_amendment_c_order():
    from operations.store import SYMPTOMS
    assert set(SYMPTOMS.values()) == set(design.SYMPTOM_CAUSE)
    assert design.RULECODE_ORDER[0] == "CONFLICTING_CUSTODY" and design.RULECODE_ORDER[-1] == "MISSED_MILESTONE"
    assert len(design.RULECODE_ORDER) == 14


def test_wilson_known_values():
    lo, hi = wilson(26, 41)
    assert round(lo, 3) == 0.481 and round(hi, 3) == 0.764
    assert wilson(0, 0) == (None, None)
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0.27 < hi < 0.28


def test_mcnemar_exact():
    assert round(mcnemar_exact(10, 2), 4) == 0.0386
    assert mcnemar_exact(2, 10) == mcnemar_exact(10, 2)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0


def test_paired_difference_interval_contains_the_difference():
    d, lo, hi = paired_difference_interval(12, 9, 2, 21)
    assert round(d, 4) == 0.1591 and lo < d < hi and -1 <= lo and hi <= 1
    d, lo, hi = paired_difference_interval(10, 0, 0, 10)
    assert d == 0 and lo <= 0 <= hi


def test_power_grows_with_gain_and_mdg_matches_the_design_order_of_magnitude():
    assert mcnemar_power(160, 0.4, 0.05) < mcnemar_power(160, 0.4, 0.10) < mcnemar_power(160, 0.4, 0.15)
    # Amendment 2 states about 13 to 14 points for 160 cases; the exact calculation gives 13.5 (d=0.35) to 15.3 (d=0.45).
    assert 0.12 <= minimum_detectable_gain(160, 0.35) <= 0.14
    assert 0.14 <= minimum_detectable_gain(160, 0.45) <= 0.16
    # E2, 60 cases: "about 22 points".
    assert 0.20 <= minimum_detectable_gain(60, 0.35) <= 0.26
    assert minimum_detectable_gain(5, 0.35) is None


def test_percentile_nearest_rank():
    assert percentile([1, 2, 3, 4], 50) == 2 and percentile([1, 2, 3, 4], 99) == 4 and percentile([], 50) is None
