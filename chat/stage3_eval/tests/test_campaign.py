"""The evaluation run and the campaign's persistent model-call ledger (operations/call_ledger.py): the budget is what
the campaign has left, the run refuses to start past the cap, holds its maximum while it runs and writes what it
used. Fakes only; every test has a ledger file of its own."""
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


def fake_wiring(config, *, dry_run=False):
    """A wiring of fakes for the CLI (python -m stage3_eval run --wiring stage3_eval.tests.test_campaign:fake_wiring)."""
    truth = {w: rows for w, (rows, _replay) in fixture_worlds().items()}
    WIRED.update(config=config, dry_run=dry_run, closed=False)
    return {"arms": build_arms(config, FakeAgent(truth), notools_turn_factory()[0]), "case_source": FixtureCaseSource(),
            "capture": FixtureCapture(), "extras_arms": {},
            "provenance": lambda: {"dirty_tree": False, "tree_changed_during_run": False, "evaluated_at_the_end": True},
            "close": lambda: WIRED.update(closed=True)}


def _select(tmp_path, ledger=None, c_cap=12):
    for w in ("E1", "E2"):
        if not (tmp_path / f"truth_{w}").exists():
            shutil.copytree(world_dir(w) / "truth", tmp_path / f"truth_{w}")
    args = ["select", "--freeze-commit", "d" * 40, "--c-cap", str(c_cap), "--out", str(tmp_path / "pre")]
    for w in ("E1", "E2"):
        args += ["--world", f"{w}={tmp_path / f'truth_{w}'}"]
    if ledger:
        args += ["--ledger", str(ledger)]
    assert main(args) == 0
    return tmp_path / "pre" / "selection.json"


def test_select_sizes_the_evaluation_from_what_the_campaign_has_left(tmp_path, capsys, campaign_ledger_file):
    selection_path = _select(tmp_path)
    printed = json.loads(capsys.readouterr().out)
    selection = scorer_view(selection_path)
    assert printed["campaign_ledger"]["spent"] == 173 and printed["budget"] == 3427
    assert selection["config"]["budget"] == 3427                       # sealed: the stop line (3,600) minus the 173 already spent
    assert selection["n_main"] == 3427 // (12 + 2) == 244              # not floor(4000 / 14) = 285, nor floor(3827 / 14) = 273
    assert sum(selection["allocation"].values()) == 244
    assert design.n_main(12) == 285                                    # the design's planning number is unchanged
    assert CallLedger(campaign_ledger_file).spent == 173               # selecting writes nothing to the ledger


def test_select_with_another_ledger_and_with_none_left(tmp_path, capsys):
    ledger = write_campaign_ledger(tmp_path / "ledger.json", spent=1000)
    selection = json.loads(_select(tmp_path, ledger).read_text())
    assert selection["config"]["budget"] == 2600 and selection["n_main"] == 2600 // 14   # 3,600 - 1,000, not 4,000 - 1,000
    empty = write_campaign_ledger(tmp_path / "empty.json", spent=4000)
    with pytest.raises(SystemExit, match="no model calls remain"):
        main(["select", "--freeze-commit", "d" * 40, "--c-cap", "12", "--out", str(tmp_path / "pre2"),
              "--world", f"E1={tmp_path / 'truth_E1'}", "--ledger", str(empty)])
    other_cap = write_campaign_ledger(tmp_path / "cap.json", spent=0, cap=5000)
    with pytest.raises(SystemExit, match="the design's cap is 4000"):
        main(["select", "--freeze-commit", "d" * 40, "--c-cap", "12", "--out", str(tmp_path / "pre3"),
              "--world", f"E1={tmp_path / 'truth_E1'}", "--ledger", str(other_cap)])


def test_the_run_reserves_its_budget_and_writes_what_it_used(tmp_path, selected, worlds, campaign_ledger_file):
    config, sel_dir, _ = selected
    config = make_config()                                             # budget 3600: with 173 spent it would pass the stop line
    campaign = CallLedger(campaign_ledger_file)
    arms = build_arms(config, FakeAgent({w: worlds[w][0] for w in worlds}), notools_turn_factory()[0])
    with pytest.raises(LedgerRefused, match="would pass the Stage 3 stop line"):
        run(sel_dir / "selection.json", tmp_path / "refused", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=campaign)
    assert not (tmp_path / "refused").exists() and campaign.spent == 173
    with pytest.raises(LedgerRefused):                                 # a dry run is refused the same way, and writes nothing
        run(sel_dir / "selection.json", tmp_path / "refused", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=campaign,
            dry_run=True)
    assert campaign.spent == 173

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
    with pytest.raises(LedgerRefused):                                 # no other Stage 3 run may start meanwhile
        run(sel_dir / "selection.json", tmp_path / "other", arms=build_arms(config, FakeAgent(truth), notools_turn_factory()[0]),
            case_source=FixtureCaseSource(), config=config, campaign=campaign)
    assert not (tmp_path / "other").exists() and campaign.spent == 3600
    manifest = run(sel_dir / "selection.json", tmp_path / "run", arms=build_arms(config, FakeAgent(truth), notools_turn_factory()[0]),
                   case_source=FixtureCaseSource(), config=config, campaign=campaign, resume=True)
    assert len(campaign.load()["entries"]) == 1
    assert campaign.spent == manifest["ledger"]["committed_calls"] == 3 * 9 + 12 + 66 * 9 + 70   # the lost case at its worst case


def test_cli_run_goes_through_the_ledger(tmp_path, capsys, campaign_ledger_file, monkeypatch):
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    selection = _select(tmp_path)
    capsys.readouterr()
    wiring = "stage3_eval.tests.test_campaign:fake_wiring"
    assert main(["run", "--selection", str(selection), "--out", str(tmp_path / "dry"), "--wiring", wiring, "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["ledger"]["settled_calls"] == 0 and printed["campaign_ledger"]["spent"] == 173 and WIRED["dry_run"] and WIRED["closed"]
    assert main(["run", "--selection", str(selection), "--out", str(tmp_path / "run"), "--wiring", wiring]) == 0
    printed = json.loads(capsys.readouterr().out)
    used = printed["ledger"]["committed_calls"]
    assert used == 70 * 9 + 70 and printed["campaign_ledger"]["spent"] == 173 + used and WIRED["closed"]
    manifest = json.loads((tmp_path / "run" / "run_manifest.json").read_text())
    assert manifest["provenance"]["evaluated_at_the_end"] and manifest["campaign_ledger"]["calls"] == used
    # The command line enforces isolation, and this test process has the scorer side loaded: flagged, as it must be.
    assert manifest["isolation"]["enforced"] and manifest["status"].startswith("invalid: truth was within reach of the run process")
    # The selection was sealed with 3,427; the campaign now has less than that left, so a second run cannot start.
    WIRED.clear()
    with pytest.raises(SystemExit, match="Refusing to run: refused"):
        main(["run", "--selection", str(selection), "--out", str(tmp_path / "again"), "--wiring", wiring])
    assert not WIRED and not (tmp_path / "again").exists()            # refused before the wiring opened anything
    assert CallLedger(campaign_ledger_file).spent == 173 + used


def test_select_reserve_keeps_calls_out_of_the_budget_and_the_run_respects_it(tmp_path, capsys, campaign_ledger_file, monkeypatch):
    """select --reserve N: budget = cap - spent - N when that is below the stop line's own limit, sealed with the
    reserve; run refuses to go into the reserve. (A reserve of 400 or less changes nothing: the line already keeps 400.)"""
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    for w in ("E1", "E2"):
        shutil.copytree(world_dir(w) / "truth", tmp_path / f"truth_{w}")
    args = ["select", "--freeze-commit", "d" * 40, "--c-cap", "16", "--reserve", "500", "--out", str(tmp_path / "pre")]
    for w in ("E1", "E2"):
        args += ["--world", f"{w}={tmp_path / f'truth_{w}'}"]
    assert main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    selection_path = tmp_path / "pre" / "selection.json"
    sealed = json.loads(selection_path.read_text())
    assert (printed["campaign_ledger"]["spent"], printed["budget"], printed["reserve"]) == (173, 3327, 500)   # 4,000 - 173 - 500
    assert (sealed["config"]["budget"], sealed["config"]["reserve"], sealed["config"]["c_cap"]) == (3327, 500, 16)
    assert sealed["n_main"] == 3327 // (16 + 2) == 184 and printed["allocation"]["n_main"] == 184
    assert CallLedger(campaign_ledger_file).spent == 173                # selecting writes nothing to the ledger
    # The reserve is part of what is sealed; a zero reserve is not written, so earlier selections keep their hash.
    config = design.EvalConfig(**sealed["config"])
    assert design.sealed_hash(config) == sealed["sealed_config_hash"] != design.sealed_hash(design.EvalConfig(**{**sealed["config"], "reserve": 0}))
    assert "reserve" not in make_config().as_dict() and make_config(reserve=5).as_dict()["reserve"] == 5
    for bad in ("-1", "3827"):                                          # nothing would be left
        with pytest.raises(SystemExit):
            main(["select", "--freeze-commit", "d" * 40, "--c-cap", "16", "--reserve", bad, "--out", str(tmp_path / "pre2"),
                  "--world", f"E1={tmp_path / 'truth_E1'}"])
    # The run: 173 + 3,327 is exactly cap - reserve, so it may start; one more call spent and it may not.
    wiring = "stage3_eval.tests.test_campaign:fake_wiring"
    assert main(["run", "--selection", str(selection_path), "--out", str(tmp_path / "dry"), "--wiring", wiring, "--dry-run"]) == 0
    capsys.readouterr()
    write_campaign_ledger(campaign_ledger_file, spent=174)              # below the stop line (174 + 3,327 = 3,501), but in the reserve
    WIRED.clear()
    with pytest.raises(SystemExit, match="Refusing to run: refused.*500 are set aside by the selection"):
        main(["run", "--selection", str(selection_path), "--out", str(tmp_path / "run"), "--wiring", wiring])
    assert not WIRED and not (tmp_path / "run").exists() and CallLedger(campaign_ledger_file).spent == 174
    # The same refusal from the run function itself (dry or not), before anything is written.
    arms = build_arms(config, FakeAgent({w: rows for w, (rows, _r) in fixture_worlds().items()}), notools_turn_factory()[0])
    for dry in (False, True):
        with pytest.raises(LedgerRefused, match="would go into that reserve"):
            run(selection_path, tmp_path / "direct", arms=arms, case_source=FixtureCaseSource(), config=config,
                campaign=CallLedger(campaign_ledger_file), dry_run=dry)
    assert not (tmp_path / "direct").exists()
    # A paused run of this selection resumes inside the reserve's limit: its own entry is not counted against it.
    write_campaign_ledger(campaign_ledger_file, spent=173)
    campaign = CallLedger(campaign_ledger_file)
    first = run(selection_path, tmp_path / "parts", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=campaign, max_cases=2)
    assert first["status"] == "paused" and campaign.spent == 173 + 20
    arms = build_arms(config, FakeAgent({w: rows for w, (rows, _r) in fixture_worlds().items()}), notools_turn_factory()[0])
    again = run(selection_path, tmp_path / "parts", arms=arms, case_source=FixtureCaseSource(), config=config, campaign=campaign,
                max_cases=4, resume=True)
    assert again["status"] == "paused" and campaign.spent == 173 + 40


def test_select_stops_at_the_stage3_line_by_default_and_the_run_refuses_to_pass_it(tmp_path, capsys, campaign_ledger_file, monkeypatch):
    """Addendum to amendment 3: Stage 3 stops when the campaign ledger reaches 3,600 (design.STAGE3_STOP_AT). With 173
    spent and C_cap 16, and no --reserve, select seals 3,427 and 190 cases in the cells of the trim order."""
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    assert (design.CALL_BUDGET, design.STAGE3_STOP_AT) == (4000, 3600)
    assert design.evaluation_budget(173) == 3427 and design.evaluation_budget(0) == 3600 and design.evaluation_budget(3600) == 0
    assert design.evaluation_budget(173, reserve=400) == 3427 and design.evaluation_budget(173, reserve=500) == 3327
    selection_path = _select(tmp_path, c_cap=16)
    printed = json.loads(capsys.readouterr().out)
    sealed = json.loads(selection_path.read_text())
    assert (printed["campaign_ledger"]["spent"], printed["campaign_ledger"]["remaining"], printed["stage3_stop_at"]) == (173, 3827, 3600)
    assert printed["budget"] == sealed["config"]["budget"] == 3427      # min(3,827 remaining, 3,600 - 173), not 3,827
    assert "reserve" not in sealed["config"] and sealed["config"]["c_cap"] == 16
    assert sealed["n_main"] == printed["allocation"]["n_main"] == 3427 // (16 + 2) == 190
    cells = printed["allocation"]["cells"]
    assert cells["E1/identifiable_ambiguous"] == 105 and cells["E2/identifiable_ambiguous"] == 40
    assert cells["E1/determined"] + cells["E2/determined"] == 30 and cells["E1/unidentifiable"] + cells["E2/unidentifiable"] == 15
    assert sum(cells.values()) == 190 and scorer_view(selection_path)["allocation"] == cells
    assert printed["worst_case_calls"] == 190 * design.worst_case_per_case(16) == 3420 <= 3427
    assert 173 + printed["worst_case_calls"] <= design.STAGE3_STOP_AT   # the run always finishes inside the line
    # The line is part of what is sealed.
    config = design.EvalConfig(**sealed["config"])
    assert design.sealed_hash(config) == sealed["sealed_config_hash"]
    with monkeypatch.context() as moved:
        moved.setattr(design, "STAGE3_STOP_AT", 3700)
        assert design.sealed_hash(config) != sealed["sealed_config_hash"]
    # Nothing left before the line: select refuses, though the cap itself still has calls.
    at_the_line = write_campaign_ledger(tmp_path / "line.json", spent=3600)
    with pytest.raises(SystemExit, match="Stage 3 stop line"):
        main(["select", "--freeze-commit", "d" * 40, "--c-cap", "16", "--out", str(tmp_path / "pre2"),
              "--world", f"E1={tmp_path / 'truth_E1'}", "--ledger", str(at_the_line)])
    assert not (tmp_path / "pre2").exists()
    # The run: 173 + 3,427 is exactly the line, so it may start; one more call spent and it may not (no reserve is sealed,
    # and the cap itself would still hold it: 174 + 3,427 = 3,601).
    wiring = "stage3_eval.tests.test_campaign:fake_wiring"
    assert main(["run", "--selection", str(selection_path), "--out", str(tmp_path / "dry"), "--wiring", wiring, "--dry-run"]) == 0
    capsys.readouterr()
    write_campaign_ledger(campaign_ledger_file, spent=174)
    WIRED.clear()
    with pytest.raises(SystemExit, match="Refusing to run: refused.*would pass the Stage 3 stop line"):
        main(["run", "--selection", str(selection_path), "--out", str(tmp_path / "run"), "--wiring", wiring])
    assert not WIRED and not (tmp_path / "run").exists() and CallLedger(campaign_ledger_file).spent == 174
    arms = build_arms(config, FakeAgent({w: rows for w, (rows, _r) in fixture_worlds().items()}), notools_turn_factory()[0])
    for dry in (False, True):                                           # the run function itself, before anything is written
        with pytest.raises(LedgerRefused, match="would pass the Stage 3 stop line"):
            run(selection_path, tmp_path / "direct", arms=arms, case_source=FixtureCaseSource(), config=config,
                campaign=CallLedger(campaign_ledger_file), dry_run=dry)
    assert not (tmp_path / "direct").exists() and CallLedger(campaign_ledger_file).spent == 174
