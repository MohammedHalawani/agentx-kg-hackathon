"""The stratum script, the S5 split it must reproduce, and the pre-registered selection."""
import json
from collections import defaultdict
from pathlib import Path

import pytest

from stage3_eval.selection import scorer_view, select
from stage3_eval.strata import assign_strata, determined_symptom_sets, opened_cases
from stage3_eval.truth_io import load_truth, truth_vocabulary

from .conftest import make_config

REPO = Path(__file__).resolve().parents[3]


def test_reproduces_the_stage0_s5_split_19_determined_22_ambiguous():
    """Amendment 1, F: the stratum rule reproduces a named S5 split. Stage 0's parameters: eventual labels over the
    600-shipment world's replica, any support, determined when one label is acceptable for every shipment."""
    replica = json.loads((REPO / "docs/assessments/2026-10-10_stage0/data/replica.json").read_text())["shipments"]
    cases = json.loads((REPO / "docs/evals/2026-10-09_s5/final/pipeline.json").read_text())["cases"]
    groups = defaultdict(list)
    for v in replica.values():
        first = next((x for x in v["timeline"] if x[2]), None)
        if first:
            groups[tuple(first[2])].append(frozenset(v["acceptable"]))
    verdict = determined_symptom_sets(groups, min_support=1)
    determined = sum(1 for c in cases if verdict.get(tuple(c["opening_symptoms"])))
    assert (determined, len(cases) - determined) == (19, 22)
    # The stratum script's own support rule (5) moves only sets seen fewer than 5 times to the fallback.
    strict = determined_symptom_sets(groups, min_support=5)
    assert all(strict[k] in (verdict[k], None) for k in groups)


def test_fixture_strata(worlds):
    truth, replay = worlds["E1"]
    cases, healthy = opened_cases(truth, replay)
    strata, rule, census = assign_strata(cases)
    counts = defaultdict(int)
    for s in strata.values():
        counts[s] += 1
    assert dict(counts) == {"identifiable_ambiguous": 34, "determined": 11, "unidentifiable": 5}
    assert len(healthy) == 2                                     # opened on healthy shipments: not evaluation cases
    assert census["MILESTONE_OVERDUE"]["determined"] is False    # HUB_DELAY, ROUTE_DELAY and ADDRESS_CONFLICT share it
    assert census["WEIGHT_READ_DIFFERS"]["determined"] is True


def test_small_census_falls_back_to_the_generator_map():
    base = {"identifiable": True, "mechanism_types": ("X",)}
    cases = [{**base, "shipment_id": "a", "symptoms": ("S",), "acceptable": frozenset({"A"}), "shared_with_other_causes": False},
             {**base, "shipment_id": "b", "symptoms": ("T",), "acceptable": frozenset({"B"}), "shared_with_other_causes": True}]
    strata, rule, _ = assign_strata(cases)
    assert strata == {"a": "determined", "b": "identifiable_ambiguous"}
    assert rule["a"].startswith("generator map")


def test_selection_is_deterministic_runtime_safe_and_written_once(tmp_path, worlds):
    config = make_config()
    a = select(worlds, config, tmp_path / "a")
    b = select(worlds, config, tmp_path / "b")
    assert a["hashes"] == b["hashes"]
    c = select(worlds, make_config(freeze_commit="b" * 40), tmp_path / "c")
    assert c["hashes"]["selection"] != a["hashes"]["selection"]
    text = (tmp_path / "a" / "selection.json").read_text()
    for world in ("E1", "E2"):
        vocab = truth_vocabulary(worlds[world][0])
        assert vocab["canary"] not in text and not any(i in text for i in vocab["mechanism_ids"])
        assert not any(f'"{n}"' in text for n in vocab["mechanism_names"])
    for forbidden in ('"acceptable', '"cause', '"label', '"canary', '"truth'):
        assert forbidden not in text
    for name in ("selection_scorer.json", "extras.json"):
        assert (tmp_path / "a" / f"{name}.sha256").read_text().split()[0] == a["hashes"][name.removesuffix(".json")]
    assert (tmp_path / "a" / "selection.json.sha256").read_text().split()[0] == a["hashes"]["selection"]
    with pytest.raises(FileExistsError):
        select(worlds, config, tmp_path / "a")


def test_the_run_readable_selection_carries_nothing_derived_from_truth(tmp_path, worlds):
    """Gate fix 4: the stratum, the main-test flag and the extras lists are derived from truth. They are written to the
    scorer-side files only, and the runtime screen refuses a run-readable document that carries any of them."""
    from stage3_eval import selection as sel_mod
    from stage3_eval.design import RUN_CASE_KEYS, runtime_selection_problem
    from stage3_eval.runner import load_selection
    select(worlds, make_config(), tmp_path / "s")
    run_side = json.loads((tmp_path / "s" / "selection.json").read_text())
    assert set(run_side) == {"schema", "sealed_config_hash", "config", "n_main", "cases", "unit"}
    assert all(set(row) == {"order", "key", "world", "shipment_id", "expected_opened_at"} for row in run_side["cases"])
    assert all(set(row) == set(RUN_CASE_KEYS) for row in run_side["cases"])   # the screen permits what select writes, and no more
    for runtime_only in ("case_id", "as_of"):                                # the backend's to give once a case is opened
        assert runtime_only not in RUN_CASE_KEYS
        carried = {**run_side, "cases": [{**run_side["cases"][0], runtime_only: "x"}, *run_side["cases"][1:]]}
        assert "fields the run step must not read" in runtime_selection_problem(carried)
        with pytest.raises(ValueError, match="truth-side field"):
            sel_mod._check_runtime_safe(carried, truth_vocabulary(worlds["E1"][0]))
    text = (tmp_path / "s" / "selection.json").read_text()
    for name in ("stratum", "main_test", "cross_shipment_ablation", "stability_rerun", "extras", "allocation", "identifiable_ambiguous",
                 "determined"):
        assert name not in text, name
    # The scorer side holds them, bound to this selection by its hash.
    scorer = json.loads((tmp_path / "s" / "selection_scorer.json").read_text())
    extras = json.loads((tmp_path / "s" / "extras.json").read_text())
    digest = (tmp_path / "s" / "selection.json.sha256").read_text().split()[0]
    assert scorer["selection_sha256"] == extras["selection_sha256"] == digest
    assert {row["stratum"] for row in scorer["cases"]} == {"identifiable_ambiguous", "determined", "unidentifiable"}
    assert extras["extras"]["cross_shipment_ablation"] and extras["extras"]["stability_rerun"]
    view = scorer_view(tmp_path / "s" / "selection.json")
    assert [row["key"] for row in view["cases"]] == [row["key"] for row in run_side["cases"]] and view["allocation"] == scorer["allocation"]
    # The screen: each truth-derived name is refused, on a case row, at the top level and nested.
    vocabulary = truth_vocabulary(worlds["E1"][0])
    sel_mod._check_runtime_safe(run_side, vocabulary)
    for bad in ({**run_side, "cases": [{**run_side["cases"][0], "stratum": "determined"}]},
                {**run_side, "cases": [{**run_side["cases"][0], "main_test": True}]},
                {**run_side, "extras": {"cross_shipment_ablation": []}},
                {**run_side, "allocation": {}},
                {**run_side, "config": {**run_side["config"], "notes": {"cross_shipment_ablation": ["E1:X"]}}}):
        assert runtime_selection_problem(bad)
        with pytest.raises(ValueError, match="truth-side field"):
            sel_mod._check_runtime_safe(bad, vocabulary)
    # The run step refuses such a file even when its hash matches (an old-format or hand-made selection).
    old = tmp_path / "old"
    old.mkdir()
    sel_mod._write_once(old / "selection.json", view)
    with pytest.raises(ValueError, match="not a run-readable selection"):
        load_selection(old / "selection.json")
    # A scorer-side file from another selection is refused.
    select(worlds, make_config(freeze_commit="b" * 40), tmp_path / "t")
    for name in ("extras.json", "extras.json.sha256"):
        (tmp_path / "t" / name).write_bytes((tmp_path / "s" / name).read_bytes())
    with pytest.raises(ValueError, match="not written for this selection"):
        scorer_view(tmp_path / "t" / "selection.json")


def test_selection_reports_shortfalls_and_covers_mechanisms(tmp_path, worlds):
    summary = select(worlds, make_config(), tmp_path / "s")
    short = {(s["world"], s["stratum"]): s for s in summary["shortfalls"]}
    assert short[("E1", "identifiable_ambiguous")] == {"world": "E1", "stratum": "identifiable_ambiguous", "allocated": 160, "available": 34}
    sel = scorer_view(tmp_path / "s" / "selection.json")
    assert sum(c["main_test"] for c in sel["cases"]) == 34
    # World by world, by expected opening: the replay clock only moves forward.
    order = [(c["world"], c["expected_opened_at"]) for c in sel["cases"]]
    assert order == sorted(order, key=lambda x: (("E1", "E2").index(x[0]), x[1]))
    with pytest.raises(ValueError, match="full freeze commit"):
        select(worlds, make_config(freeze_commit="abc1234"), tmp_path / "short")
    assert len({c["key"] for c in sel["cases"]}) == len(sel["cases"])
    # Cross-shipment ablation candidates come only from the main test.
    main = {c["key"] for c in sel["cases"] if c["main_test"]}
    assert set(sel["extras"]["cross_shipment_ablation"]) <= main and sel["extras"]["cross_shipment_ablation"]


def test_selection_is_sized_from_the_targets_and_the_world_and_seals_its_own_worst_case(tmp_path, worlds, monkeypatch):
    """Sizing: each cell takes its target or every case the world holds in it (target, available and selected recorded
    in the summary and the scorer file; a short cell is never an error). A budget left unset is sealed as the worst
    case of the selection, extras included. The stability list is a seeded draw of the main-test cell."""
    from stage3_eval import design, selection as sel_mod
    from stage3_eval.runner import load_selection
    summary = select(worlds, make_config(budget=None, c_cap=16), tmp_path / "s")
    run_side, _sha = load_selection(tmp_path / "s" / "selection.json")
    scorer_side = json.loads((tmp_path / "s" / "selection_scorer.json").read_text())
    extras = json.loads((tmp_path / "s" / "extras.json").read_text())["extras"]
    sizing = summary["sizing"]
    assert scorer_side["sizing"] == sizing == scorer_view(tmp_path / "s" / "selection.json")["sizing"]
    assert summary["allocation"]["target"] == sizing["n_target"] == 285 and scorer_side["allocation"]["E1/identifiable_ambiguous"] == 160
    assert sizing["cells"]["E1/identifiable_ambiguous"] == {"target": 160, "available": 34, "selected": 34}
    for cell in sizing["cells"].values():
        assert cell["selected"] == min(cell["target"], cell["available"])
    assert sum(c["selected"] for c in sizing["cells"].values()) == sizing["n_selected"] == run_side["n_main"] == len(run_side["cases"]) == 70
    assert summary["allocation"]["notes"]                              # the main test below 150 is stated, not refused
    ablation, stability = len(extras["cross_shipment_ablation"]), len(extras["stability_rerun"])
    assert stability == 34 and sizing["extras"] == {"cross_shipment_ablation": ablation, "stability_rerun": 34, "stability_max": 40}
    worst = {"main": 70 * (16 + 3), "cross_shipment_ablation": ablation * 16, "stability_rerun": 34 * 16}
    assert sizing["worst_case_calls"] == {**worst, "total": sum(worst.values())} == design.worst_case_calls(70, ablation, 34, 16)
    assert run_side["config"]["budget"] == summary["budget"] == sizing["sealed_budget"] == sum(worst.values())
    sealed = design.EvalConfig(**summary["config"])
    assert run_side["sealed_config_hash"] == design.sealed_hash(sealed) and "stop_at" not in run_side["config"]
    # The same cases as with a budget given by hand: no budget, ledger or cap changes who is drawn.
    select(worlds, make_config(budget=123456, c_cap=7), tmp_path / "other")
    assert [c["key"] for c in json.loads((tmp_path / "other" / "selection.json").read_text())["cases"]] == [c["key"] for c in run_side["cases"]]
    assert json.loads((tmp_path / "other" / "selection.json").read_text())["config"]["budget"] == 123456
    # One world only: the missing world's cells are recorded as empty, and nothing fails.
    alone = select({"E1": worlds["E1"]}, make_config(budget=None), tmp_path / "alone")
    assert alone["sizing"]["cells"]["E2/determined"] == {"target": 10, "available": 0, "selected": 0}
    # The stability rerun: a seeded draw of design.STABILITY_MAX main-test cases, in run order.
    monkeypatch.setattr(sel_mod, "STABILITY_MAX", 10)
    drawn = []
    for name in ("d1", "d2"):
        select(worlds, make_config(), tmp_path / name)
        drawn.append(json.loads((tmp_path / name / "extras.json").read_text())["extras"]["stability_rerun"])
    main = [c["key"] for c in scorer_view(tmp_path / "d1" / "selection.json")["cases"] if c["main_test"]]
    assert drawn[0] == drawn[1] and len(drawn[0]) == 10 and drawn[0] == [k for k in main if k in set(drawn[0])] and drawn[0] != main[:10]
    assert [c["key"] for c in json.loads((tmp_path / "d1" / "selection.json").read_text())["cases"]] == [c["key"] for c in run_side["cases"]]


def test_round_robin_draw_spreads_over_mechanisms_when_the_cell_is_small(tmp_path, worlds, monkeypatch):
    from stage3_eval import selection as sel_mod
    monkeypatch.setitem(sel_mod.ALLOCATION_AT_PLANNING, ("E1", "identifiable_ambiguous"), 7)
    summary = select({"E1": worlds["E1"]}, make_config(), tmp_path / "r")
    sel = scorer_view(tmp_path / "r" / "selection.json")
    truth = worlds["E1"][0]
    types = {truth[c["shipment_id"]]["mechanisms"][0]["type"] for c in sel["cases"] if c["main_test"]}
    assert summary["by_cell"]["E1/identifiable_ambiguous"] == 7 and len(types) == 7


def test_pairs_do_not_overlap(tmp_path, worlds):
    select(worlds, make_config(), tmp_path / "p")
    pairs = json.loads((tmp_path / "p" / "pairs.json").read_text())["pairs"]
    keys = [k for p in pairs for k in p["cases"]]
    assert pairs and len(keys) == len(set(keys))
    assert {p["kind"] for p in pairs} <= {"same_symptoms_different_cause", "same_cause_different_symptoms"}


def test_truth_inside_the_repository_is_refused_unless_fixture(tmp_path):
    here = Path(__file__).resolve().parent / "_not_fixture_truth.jsonl"
    try:
        here.write_text(json.dumps({"shipment_id": "S", "canary": "CNRY" + "A" * 24, "dataset_id": "REAL-1"}) + "\n")
        with pytest.raises(ValueError, match="inside the repository"):
            load_truth(here)
    finally:
        here.unlink()
    outside = tmp_path / "truth.jsonl"
    outside.write_text(json.dumps({"shipment_id": "S", "canary": "CNRY" + "A" * 24}) + "\n")
    assert load_truth(outside)["S"]["canary"].startswith("CNRY")
    outside.write_text(json.dumps({"shipment_id": "S", "canary": "nope"}) + "\n")
    with pytest.raises(ValueError, match="canary"):
        load_truth(outside)


def test_the_committed_exclusion_list_is_read_and_a_bad_one_stops_the_selection(tmp_path):
    from stage3_eval.exclusions import excluded_for, excluded_in, load_exclusions
    by_dataset, sources = load_exclusions()
    listed = by_dataset["DEMO-SUHAIL-WORLD-1"]
    assert len(listed) == 12 and "DEMO-SHP-000019" in listed
    assert sources[0]["file"] == "docs/evals/2026-10-10_world1_pilot/excluded_shipments.json" and sources[0]["shipments"] == 12
    assert len(sources[0]["sha256"]) == 64 and sources[0]["dataset_id"] == "DEMO-SUHAIL-WORLD-1"
    assert excluded_in(by_dataset, "DEMO-SUHAIL-WORLD-1", ["DEMO-SHP-000019", "DEMO-SHP-000020"]) == ["DEMO-SHP-000019"]
    assert excluded_in(by_dataset, "DEMO-SUHAIL-WORLD-2", ["DEMO-SHP-000019"]) == []          # another dataset: not affected
    assert excluded_for(by_dataset, [], ["DEMO-SHP-000019"]) == ["DEMO-SHP-000019"]           # dataset unknown: the safe side
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"dataset_id": "X", "shipments": ["A"]}))
    with pytest.raises(ValueError, match="not an exclusion list"):
        load_exclusions([str(bad)])
    with pytest.raises(FileNotFoundError):                    # a list that cannot be read stops the selection
        load_exclusions([str(tmp_path / "missing.json")])


def test_an_excluded_shipment_is_never_drawn_for_its_dataset(tmp_path, worlds):
    """The harness case source honours the exclusion list: a listed shipment of the world's dataset is not selected
    (and not in an extras list or a pair); the same id in another dataset is untouched; the strata do not move."""
    config = make_config()
    plain = select(worlds, config, tmp_path / "plain")
    before = scorer_view(tmp_path / "plain" / "selection.json")
    assert plain["exclusions"]["by_world"]["E1"] == {"dataset_ids": ["FIXTURE-E1"], "opened_cases_excluded": []}   # the committed list names another dataset
    barred = [c["shipment_id"] for c in before["cases"] if c["world"] == "E1" and c["main_test"]][:3]
    lists = ({"FIXTURE-E1": frozenset(barred)}, [{"file": "test", "sha256": "0" * 64, "dataset_id": "FIXTURE-E1", "shipments": 3}])
    summary = select(worlds, config, tmp_path / "barred", exclusions=lists)
    after = scorer_view(tmp_path / "barred" / "selection.json")
    chosen = {c["shipment_id"] for c in after["cases"] if c["world"] == "E1"}
    assert not chosen & set(barred) and summary["exclusions"]["by_world"]["E1"]["opened_cases_excluded"] == sorted(barred)
    text = "".join((tmp_path / "barred" / name).read_text() for name in ("selection.json", "extras.json", "pairs.json"))
    assert not any(sid in text for sid in barred)
    recorded = json.loads((tmp_path / "barred" / "selection_scorer.json").read_text())["exclusions"]
    assert recorded["sources"] == lists[1] and recorded["by_world"]["E1"]["opened_cases_excluded"] == sorted(barred)
    assert summary["by_cell"]["E1/identifiable_ambiguous"] == 34 - 3
    assert json.loads((tmp_path / "barred" / "strata.json").read_text())["census"] == json.loads((tmp_path / "plain" / "strata.json").read_text())["census"]
    other = select(worlds, config, tmp_path / "other", exclusions=({"ANOTHER-DATASET": frozenset(barred)}, []))
    assert other["hashes"]["selection"] == plain["hashes"]["selection"]
