"""The evaluation run and the campaign's persistent model-call ledger (operations/call_ledger.py). Since the budget was
lifted (2026-10-11) the ledger's cap is a runaway guard: nothing is sized from it, `select` seals the worst case of
what it selected, and the run refuses to start only if that would cross the guard (or a reserve or stop line the
selection sealed, both off by default), holds its maximum while it runs and writes what it used. Fakes only; every
test has a ledger file of its own."""
import json
import shutil

import pytest

from operations.call_ledger import CallLedger, LedgerRefused
from stage3_eval import design
from stage3_eval.selection import scorer_view
from stage3_eval.__main__ import main
from stage3_eval.arms import AgentArm, NoToolsArm, RuleCodeArm, SymptomArm
from stage3_eval.fixtures.fakes import FixtureCapture, FixtureCaseSource, world_dir
from stage3_eval.runner import run

from .conftest import FakeAgent, build_arms, fixture_worlds, make_config, notools_turn_factory, write_campaign_ledger

WIRED = {}
WIRING = "stage3_eval.tests.test_campaign:fake_wiring"


def fake_wiring(config, *, dry_run=False):
    """A wiring of fakes for the CLI (python -m stage3_eval run --wiring stage3_eval.tests.test_campaign:fake_wiring)."""
    truth = {w: rows for w, (rows, _replay) in fixture_worlds().items()}
    WIRED.update(config=config, dry_run=dry_run, closed=False)
    return {"arms": build_arms(config, FakeAgent(truth), notools_turn_factory()[0]), "case_source": FixtureCaseSource(),
            "capture": FixtureCapture(), "extras_arms": {},
            "provenance": lambda: {"dirty_tree": False, "tree_changed_during_run": False, "evaluated_at_the_end": True},
            "close": lambda: WIRED.update(closed=True)}


def _select(tmp_path, ledger=None, c_cap=12, out="pre", extra=()):
    for w in ("E1", "E2"):
        if not (tmp_path / f"truth_{w}").exists():
            shutil.copytree(world_dir(w) / "truth", tmp_path / f"truth_{w}")
    args = ["select", "--freeze-commit", "d" * 40, "--c-cap", str(c_cap), "--out", str(tmp_path / out), *extra]
    for w in ("E1", "E2"):
        args += ["--world", f"{w}={tmp_path / f'truth_{w}'}"]
    if ledger:
        args += ["--ledger", str(ledger)]
    assert main(args) == 0
    return tmp_path / out / "selection.json"


def _worst_case(selection_path, c_cap):
    """The fixture selection's worst case: 70 cases, the ablation on the eligible main-test cases, stability on all 34."""
    extras = scorer_view(selection_path)["extras"]
    assert len(extras["stability_rerun"]) == 34
    return 70 * (c_cap + 3) + (len(extras["cross_shipment_ablation"]) + 34) * c_cap


def test_select_sizes_the_evaluation_from_the_design_targets_not_from_the_ledger(tmp_path, capsys, campaign_ledger_file):
    selection_path = _select(tmp_path)
    printed = json.loads(capsys.readouterr().out)
    selection = scorer_view(selection_path)
    budget = _worst_case(selection_path, 12)
    assert printed["campaign_ledger"]["spent"] == 173 and printed["budget"] == printed["worst_case_calls"] == budget
    assert selection["config"]["budget"] == budget                     # sealed: the worst case of the selection, extras included
    assert selection["n_main"] == len(selection["cases"]) == 70        # every case the fixture worlds hold, not floor(budget / 14)
    assert sum(selection["allocation"].values()) == 285                # the targets: 160 / 60 / 30 + 10 / 20 + 5
    assert printed["sizing"]["cells"]["E1/identifiable_ambiguous"] == {"target": 160, "available": 34, "selected": 34}
    assert printed["sizing"] == selection["sizing"] and printed["a_run_would_start_at_this_ledger"] is True
    assert "reserve" not in selection["config"] and "stop_at" not in selection["config"] and printed["stop_at"] is None
    assert CallLedger(campaign_ledger_file).spent == 173               # selecting writes nothing to the ledger


def test_the_ledger_sizes_nothing_and_its_cap_need_not_be_the_designs(tmp_path, capsys, monkeypatch):
    """Any cap is accepted (it is a guard, not the design's 4,000), and what the ledger holds changes no case and no
    number of the selection: a full ledger still selects; it is the run that refuses."""
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    files = {}
    for name, spent, cap in (("roomy", 0, 20000), ("other_cap", 1000, 5000), ("full", 4000, 4000)):
        ledger = write_campaign_ledger(tmp_path / f"{name}.json", spent=spent, cap=cap)
        selection_path = _select(tmp_path, ledger, out=name)
        printed = json.loads(capsys.readouterr().out)
        files[name] = (selection_path.read_bytes(), printed["budget"], printed["a_run_would_start_at_this_ledger"])
    assert files["roomy"][0] == files["other_cap"][0] == files["full"][0]
    assert files["roomy"][1:] == (1638, True) and files["other_cap"][1:] == (1638, True) and files["full"][1:] == (1638, False)
    WIRED.clear()
    with pytest.raises(SystemExit, match="Refusing to run: refused: 4000 of 4000"):
        main(["run", "--selection", str(tmp_path / "full" / "selection.json"), "--out", str(tmp_path / "run"), "--wiring", WIRING,
              "--ledger", str(tmp_path / "full.json")])
    assert not WIRED and not (tmp_path / "run").exists()
    # The old stop line is not a limit: at 3,600 calls spent the same run starts (a dry run here), under a guard of 20,000.
    at_the_old_line = write_campaign_ledger(tmp_path / "line.json", spent=3600, cap=20000)
    assert main(["run", "--selection", str(tmp_path / "full" / "selection.json"), "--out", str(tmp_path / "dry"), "--wiring", WIRING,
                 "--ledger", str(at_the_old_line), "--dry-run"]) == 0


def test_the_run_reserves_its_budget_and_writes_what_it_used(tmp_path, selected, worlds, campaign_ledger_file):
    config, sel_dir, _ = selected
    config = make_config()                                             # budget 3600: with 500 spent it would cross this ledger's guard (4,000)
    campaign = CallLedger(write_campaign_ledger(campaign_ledger_file, spent=500))
    arms = build_arms(config, FakeAgent({w: worlds[w][0] for w in worlds}), notools_turn_factory()[0])
    with pytest.raises(LedgerRefused, match="would exceed the cap"):
        run(sel_dir / "selection.json", tmp_path / "refused", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=campaign)
    assert not (tmp_path / "refused").exists() and campaign.spent == 500
    with pytest.raises(LedgerRefused):                                 # a dry run is refused the same way, and writes nothing
        run(sel_dir / "selection.json", tmp_path / "refused", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=campaign,
            dry_run=True)
    assert campaign.spent == 500

    roomy = CallLedger(write_campaign_ledger(tmp_path / "roomy.json", spent=0))
    seen = {}

    class Watching(FakeAgent):
        def __call__(self, case):
            seen.setdefault("held_during_the_run", roomy.spent)
            return super().__call__(case)
    arms = build_arms(config, Watching({w: worlds[w][0] for w in worlds}), notools_turn_factory()[0])
    manifest = run(sel_dir / "selection.json", tmp_path / "run", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=roomy,
                   campaign_commit="e" * 40, provenance=lambda: {"dirty_tree": False, "at_the_end": True})
    assert seen["held_during_the_run"] == 3600                         # the whole budget is held while the run is going
    used = manifest["ledger"]["committed_calls"]
    assert used == 70 * 9 + 70 and roomy.spent == used and roomy.remaining == 4000 - used
    entry = roomy.load()["entries"][-1]
    assert entry["run"] == manifest["campaign_ledger"]["run"] and entry["run"].startswith("stage3 run run selection ")
    assert (entry["calls"], entry["reserved"], entry["commit"], entry["tokens"]) == (used, 3600, "e" * 40, manifest["ledger"]["tokens"])
    assert entry["finished_at"] and manifest["provenance"]["at_the_end"] is True
    # A configuration nobody sealed a budget into is not run.
    with pytest.raises(ValueError):
        run(sel_dir / "selection.json", tmp_path / "unsealed", arms=arms, case_source=FixtureCaseSource(), config=make_config(budget=None))


def test_a_run_that_dies_stays_counted_at_its_whole_budget_and_a_resume_does_not_count_twice(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    campaign = CallLedger(write_campaign_ledger(tmp_path / "ledger.json", spent=0))
    truth = {w: worlds[w][0] for w in worlds}

    class Dies(FakeAgent):
        def __call__(self, case):
            if len(self.seen) == 3:
                raise KeyboardInterrupt
            return super().__call__(case)
    with pytest.raises(KeyboardInterrupt):
        run(sel_dir / "selection.json", tmp_path / "run", arms=build_arms(config, Dies(truth), notools_turn_factory()[0]),
            case_source=FixtureCaseSource(), config=config, campaign=campaign)
    entry = campaign.load()["entries"][-1]
    assert (entry["calls"], entry["finished_at"], campaign.spent) == (3600, None, 3600)
    with pytest.raises(LedgerRefused):                                 # another run of this size would cross the guard meanwhile
        run(sel_dir / "selection.json", tmp_path / "other", arms=build_arms(config, FakeAgent(truth), notools_turn_factory()[0]),
            case_source=FixtureCaseSource(), config=config, campaign=campaign)
    assert not (tmp_path / "other").exists() and campaign.spent == 3600
    manifest = run(sel_dir / "selection.json", tmp_path / "run", arms=build_arms(config, FakeAgent(truth), notools_turn_factory()[0]),
                   case_source=FixtureCaseSource(), config=config, campaign=campaign, resume=True)
    assert len(campaign.load()["entries"]) == 1
    assert campaign.spent == manifest["ledger"]["committed_calls"] == 3 * 9 + 12 + 66 * 9 + 70   # the lost case at its worst case


def test_cli_run_goes_through_the_ledger(tmp_path, capsys, campaign_ledger_file, monkeypatch):
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    write_campaign_ledger(campaign_ledger_file, spent=173, cap=2000)   # a small guard, so the refusal below is in reach
    selection = _select(tmp_path)
    capsys.readouterr()
    assert main(["run", "--selection", str(selection), "--out", str(tmp_path / "dry"), "--wiring", WIRING, "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["ledger"]["settled_calls"] == 0 and printed["campaign_ledger"]["spent"] == 173 and WIRED["dry_run"] and WIRED["closed"]
    assert main(["run", "--selection", str(selection), "--out", str(tmp_path / "run"), "--wiring", WIRING]) == 0
    printed = json.loads(capsys.readouterr().out)
    used = printed["ledger"]["committed_calls"]
    assert used == 70 * 9 + 70 and printed["campaign_ledger"]["spent"] == 173 + used and WIRED["closed"]
    assert printed["ledger"]["budget"] == 1638                          # the run's own ledger holds the selection's sealed worst case
    manifest = json.loads((tmp_path / "run" / "run_manifest.json").read_text())
    assert manifest["provenance"]["evaluated_at_the_end"] and manifest["campaign_ledger"]["calls"] == used
    # The command line enforces isolation, and this test process has the scorer side loaded: flagged, as it must be.
    assert manifest["isolation"]["enforced"] and manifest["status"].startswith("invalid: truth was within reach of the run process")
    # The selection's worst case is 1,568; with the first run's calls in the ledger a second run would cross the guard (2,000).
    WIRED.clear()
    with pytest.raises(SystemExit, match="Refusing to run: refused"):
        main(["run", "--selection", str(selection), "--out", str(tmp_path / "again"), "--wiring", WIRING])
    assert not WIRED and not (tmp_path / "again").exists()            # refused before the wiring opened anything
    assert CallLedger(campaign_ledger_file).spent == 173 + used


def test_select_reserve_is_sealed_and_the_run_respects_it(tmp_path, capsys, campaign_ledger_file, monkeypatch):
    """select --reserve N (off by default): N is sealed in the configuration and changes no size; the run refuses to
    start if the calls spent plus its worst case would go past the ledger's guard less N."""
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    selection_path = _select(tmp_path, c_cap=16, extra=["--reserve", "500"])
    printed = json.loads(capsys.readouterr().out)
    sealed = json.loads(selection_path.read_text())
    budget = _worst_case(selection_path, 16)
    assert (printed["campaign_ledger"]["spent"], printed["budget"], printed["reserve"]) == (173, budget, 500)
    assert (sealed["config"]["budget"], sealed["config"]["reserve"], sealed["config"]["c_cap"]) == (budget, 500, 16)
    assert sealed["n_main"] == 70                                       # the reserve sizes nothing
    assert CallLedger(campaign_ledger_file).spent == 173                # selecting writes nothing to the ledger
    # The reserve is part of what is sealed; a zero reserve is not written.
    config = design.EvalConfig(**sealed["config"])
    assert design.sealed_hash(config) == sealed["sealed_config_hash"] != design.sealed_hash(design.EvalConfig(**{**sealed["config"], "reserve": 0}))
    assert "reserve" not in make_config().as_dict() and make_config(reserve=5).as_dict()["reserve"] == 5
    with pytest.raises(SystemExit):
        main(["select", "--freeze-commit", "d" * 40, "--c-cap", "16", "--reserve", "-1", "--out", str(tmp_path / "pre2"),
              "--world", f"E1={tmp_path / 'truth_E1'}"])
    # The run: spent + worst case exactly at cap - reserve may start; one more call spent and it may not, though the
    # guard itself (4,000 in this test's ledger) would still hold it.
    edge = 4000 - 500 - budget
    write_campaign_ledger(campaign_ledger_file, spent=edge)
    assert main(["run", "--selection", str(selection_path), "--out", str(tmp_path / "dry"), "--wiring", WIRING, "--dry-run"]) == 0
    capsys.readouterr()
    write_campaign_ledger(campaign_ledger_file, spent=edge + 1)
    WIRED.clear()
    with pytest.raises(SystemExit, match="Refusing to run: refused.*500 are set aside by the selection"):
        main(["run", "--selection", str(selection_path), "--out", str(tmp_path / "run"), "--wiring", WIRING])
    assert not WIRED and not (tmp_path / "run").exists() and CallLedger(campaign_ledger_file).spent == edge + 1
    # The same refusal from the run function itself (dry or not), before anything is written.
    arms = build_arms(config, FakeAgent({w: rows for w, (rows, _r) in fixture_worlds().items()}), notools_turn_factory()[0])
    for dry in (False, True):
        with pytest.raises(LedgerRefused, match="would go into that reserve"):
            run(selection_path, tmp_path / "direct", arms=arms, case_source=FixtureCaseSource(), config=config,
                campaign=CallLedger(campaign_ledger_file), dry_run=dry)
    assert not (tmp_path / "direct").exists()
    # A paused run of this selection resumes inside the reserve's limit: its own entry is not counted against it.
    write_campaign_ledger(campaign_ledger_file, spent=edge)
    campaign = CallLedger(campaign_ledger_file)
    first = run(selection_path, tmp_path / "parts", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=campaign, max_cases=2)
    assert first["status"] == "paused" and campaign.spent == edge + 20
    arms = build_arms(config, FakeAgent({w: rows for w, (rows, _r) in fixture_worlds().items()}), notools_turn_factory()[0])
    again = run(selection_path, tmp_path / "parts", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=campaign,
                max_cases=4, resume=True)
    assert again["status"] == "paused" and campaign.spent == edge + 40


def test_a_stop_line_exists_only_when_select_is_given_one(tmp_path, capsys, campaign_ledger_file, monkeypatch):
    """The 3,600 line of the addendum to amendment 3 is lifted: by default nothing is sealed and nothing stops there.
    select --stop-at N seals a line; the run then refuses to start if the calls spent plus its worst case would pass it."""
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    assert (design.CALL_BUDGET, design.STAGE3_STOP_AT) == (4000, 3600)  # historical constants, gating nothing
    default_path = _select(tmp_path, c_cap=16, out="default")
    default = json.loads(default_path.read_text())
    capsys.readouterr()
    selection_path = _select(tmp_path, c_cap=16, extra=["--stop-at", "3600"])
    printed = json.loads(capsys.readouterr().out)
    sealed = json.loads(selection_path.read_text())
    budget = _worst_case(selection_path, 16)
    assert "stop_at" not in default["config"] and (sealed["config"]["stop_at"], printed["stop_at"], printed["budget"]) == (3600, 3600, budget)
    assert [c["key"] for c in sealed["cases"]] == [c["key"] for c in default["cases"]] and sealed["n_main"] == default["n_main"] == 70
    assert sealed["config"]["budget"] == default["config"]["budget"] == budget          # the line sizes nothing
    config = design.EvalConfig(**sealed["config"])
    assert design.sealed_hash(config) == sealed["sealed_config_hash"] != default["sealed_config_hash"]   # the line is part of what is sealed
    with pytest.raises(SystemExit, match="--stop-at"):
        main(["select", "--freeze-commit", "d" * 40, "--c-cap", "16", "--stop-at", "0", "--out", str(tmp_path / "pre2"),
              "--world", f"E1={tmp_path / 'truth_E1'}"])
    assert not (tmp_path / "pre2").exists()
    # Exactly at the line the run may start; one more call spent and it may not (the guard itself would still hold it).
    edge = 3600 - budget
    write_campaign_ledger(campaign_ledger_file, spent=edge)
    assert main(["run", "--selection", str(selection_path), "--out", str(tmp_path / "dry"), "--wiring", WIRING, "--dry-run"]) == 0
    capsys.readouterr()
    write_campaign_ledger(campaign_ledger_file, spent=edge + 1)
    WIRED.clear()
    with pytest.raises(SystemExit, match="Refusing to run: refused.*would pass the stop line"):
        main(["run", "--selection", str(selection_path), "--out", str(tmp_path / "run"), "--wiring", WIRING])
    assert not WIRED and not (tmp_path / "run").exists() and CallLedger(campaign_ledger_file).spent == edge + 1
    arms = build_arms(config, FakeAgent({w: rows for w, (rows, _r) in fixture_worlds().items()}), notools_turn_factory()[0])
    for dry in (False, True):                                           # the run function itself, before anything is written
        with pytest.raises(LedgerRefused, match="would pass the stop line"):
            run(selection_path, tmp_path / "direct", arms=arms, case_source=FixtureCaseSource(), config=config,
                campaign=CallLedger(campaign_ledger_file), dry_run=dry)
    assert not (tmp_path / "direct").exists() and CallLedger(campaign_ledger_file).spent == edge + 1
    # The selection sealed without a line starts at the same ledger: nothing stops at 3,600 by default.
    assert main(["run", "--selection", str(default_path), "--out", str(tmp_path / "dry2"), "--wiring", WIRING, "--dry-run"]) == 0
