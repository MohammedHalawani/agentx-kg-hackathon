"""A run taken in parts (`run --max-cases N`, then `--resume`): it pauses by its case count alone, keeps both ledgers
right, runs no extra while paused, ends with the results an unpaused run has, and reports a paused run as interim.
Fakes only; every part gets fresh arms, as a new process would."""
import json

import pytest

from operations.call_ledger import CallLedger, LedgerRefused
from stage3_eval.__main__ import main
from stage3_eval.arms import AgentArm
from stage3_eval.budget import read_ledger
from stage3_eval.canary import TruthScanner
from stage3_eval.fixtures.fakes import FixtureCapture, FixtureCaseSource, FixtureDatabase
from stage3_eval.report import INTERIM_VERDICT, build_report, render_markdown
from stage3_eval.runner import run
from stage3_eval.scoring import score_run
from stage3_eval.selection import scorer_view
from stage3_eval.truth_io import truth_vocabulary

from .conftest import FakeAgent, build_arms, notools_turn_factory, read_jsonl, write_campaign_ledger


def _part(out, config, sel_dir, worlds, *, campaign=None, calls=9, **kw):
    """One process's worth of a run: fresh fake arms, extras wired and named, the provider's count for this process."""
    truth = {w: worlds[w][0] for w in worlds}
    agent = FakeAgent(truth, calls=calls)
    turn, notools_calls = notools_turn_factory()
    extra = {name: FakeAgent(truth, calls=6) for name in ("cross_shipment_ablation", "stability_rerun")}
    provider = lambda: calls * len(agent.seen) + len(notools_calls) + 6 * sum(len(e.seen) for e in extra.values())
    manifest = run(sel_dir / "selection.json", out, arms=build_arms(config, agent, turn), case_source=FixtureCaseSource(), config=config,
                   capture=FixtureCapture(), extras_arms={name: AgentArm(e, config.c_cap, name=name) for name, e in extra.items()},
                   extras_path=sel_dir / "extras.json", campaign=campaign, provider_calls=provider,
                   provenance={"model_calls": {"succeeded": {"gpt-oss": provider()}, "failed": {}}, "dirty_tree": False, "commit": "e" * 40}, **kw)
    return manifest, agent, extra


def _order(sel_dir):
    return [row["key"] for row in json.loads((sel_dir / "selection.json").read_text())["cases"]]


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_run_pauses_after_n_cases_with_both_ledgers_right_and_no_extras(tmp_path, selected, worlds, monkeypatch):
    import stage3_eval.runner as runner_mod
    config, sel_dir, _ = selected
    campaign = CallLedger(write_campaign_ledger(tmp_path / "campaign.json", spent=173, cap=4200))
    monkeypatch.setattr(runner_mod, "load_extras", lambda *a: pytest.fail("extras.json was opened by a paused run"))
    manifest, agent, extra = _part(tmp_path / "run", config, sel_dir, worlds, campaign=campaign, max_cases=25)
    assert manifest["status"] == "paused"                              # not invalid, not completed
    assert agent.seen == _order(sel_dir)[:25]                          # the first 25 of the pre-registered order, whole cases only
    assert manifest["progress"] == {"paused": True, "cases_settled": 25, "cases_total": 70, "max_cases": 25,
                                    "order": "pre-registered (selection.json)", "stop_rule": "the case count given to the run; no result is read"}
    assert [r["key"] for r in read_jsonl(tmp_path / "run" / "settled.jsonl")] == _order(sel_dir)[:25]
    for arm in ("agent", "notools", "rulecode", "symptom"):            # never mid-case: every arm answered each of the 25
        assert [r["case_key"] for r in read_jsonl(tmp_path / "run" / "results" / "main" / f"{arm}.jsonl")] == _order(sel_dir)[:25]
    # No extras while paused.
    assert manifest["extras"] == {} and not any(e.seen for e in extra.values()) and not (tmp_path / "run" / "results" / "extras").exists()
    # The run's ledger: nothing held for a case that has not started, and what was settled is what was called.
    led = manifest["ledger"]
    assert (led["open_reservations"], led["settled_calls"], led["committed_calls"], led["remaining"]) == (0, 250, 250, 4000 - 250)
    events = read_ledger(tmp_path / "run" / "ledger.jsonl")
    assert sum(e["event"] == "reserve" for e in events) == sum(e["event"] == "settle" for e in events) == 50
    assert events[-1]["event"] == "close" and events[-1]["status"] == "paused" and led["cases_reconciled_with_provider"] == 25
    # The campaign's ledger: the entry is settled at the calls committed so far, so the rest of the budget is free.
    entry = campaign.load()["entries"][-1]
    assert (entry["calls"], entry["reserved"], bool(entry["finished_at"])) == (250, 4000, True) and "status: paused" in entry["note"]
    assert campaign.spent == 173 + 250 and manifest["campaign_ledger"]["calls"] == 250
    # The run-level surfaces are captured as of the pause, so an interim canary scan is complete.
    assert (tmp_path / "run" / "captured" / "logs" / "paused_after_0025.jsonl").exists()
    scan = TruthScanner(truth_vocabulary(worlds["E1"][0])).scan_run(tmp_path / "run")
    assert scan["verdict"] == "clean" and not scan["missing_surfaces"]
    with pytest.raises(ValueError, match="max_cases"):
        _part(tmp_path / "zero", config, sel_dir, worlds, max_cases=0)
    assert not (tmp_path / "zero").exists()


def test_the_stop_reads_the_count_and_nothing_any_case_answered(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    truth = {w: worlds[w][0] for w in worlds}

    class Failing(FakeAgent):                                          # every case an arm error: degraded, settled at the worst case
        def __call__(self, case):
            self.seen.append(case.key)
            raise RuntimeError("provider down")
    seen = {}
    for name, agent in (("usual", FakeAgent(truth)), ("cheap", FakeAgent(truth, calls=1)), ("failing", Failing(truth))):
        manifest = run(sel_dir / "selection.json", tmp_path / name, arms=build_arms(config, agent, notools_turn_factory()[0]),
                       case_source=FixtureCaseSource(), config=config, max_cases=7)
        seen[name] = (manifest["status"], agent.seen, manifest["progress"]["cases_settled"])
    assert seen["usual"] == seen["cheap"] == seen["failing"] == ("paused", _order(sel_dir)[:7], 7)
    # A count at or past the end pauses nothing.
    whole = run(sel_dir / "selection.json", tmp_path / "whole", arms=build_arms(config, FakeAgent(truth), notools_turn_factory()[0]),
                case_source=FixtureCaseSource(), config=config, max_cases=70)
    assert whole["status"] == "completed" and whole["progress"]["paused"] is False


def test_a_paused_run_resumed_to_the_end_equals_an_unpaused_run(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    plain_campaign = CallLedger(write_campaign_ledger(tmp_path / "a.json", spent=0))
    plain, plain_agent, plain_extra = _part(tmp_path / "plain" / "run", config, sel_dir, worlds, campaign=plain_campaign)
    assert plain["status"] == "completed" and plain["earlier_segments"] == []

    campaign = CallLedger(write_campaign_ledger(tmp_path / "b.json", spent=0))
    out = tmp_path / "parts" / "run"
    first, a1, _ = _part(out, config, sel_dir, worlds, campaign=campaign, max_cases=25)
    with pytest.raises(FileExistsError):                               # a paused run is continued only with resume
        _part(out, config, sel_dir, worlds, campaign=campaign, max_cases=40)
    second, a2, x2 = _part(out, config, sel_dir, worlds, campaign=campaign, max_cases=40, resume=True)
    assert second["status"] == "paused" and second["progress"]["cases_settled"] == 40 and campaign.spent == 400
    assert not any(e.seen for e in x2.values())
    same, a_same, _ = _part(out, config, sel_dir, worlds, campaign=campaign, max_cases=40, resume=True)   # the same count again: nothing to do
    assert same["status"] == "paused" and a_same.seen == [] and campaign.spent == 400
    last, a3, x3 = _part(out, config, sel_dir, worlds, campaign=campaign, resume=True)
    assert last["status"] == "completed" and last["progress"] == {**plain["progress"]}
    order = _order(sel_dir)
    assert (a1.seen, a2.seen, a3.seen) == (order[:25], order[25:40], order[40:])   # no case twice, none skipped
    assert [s["status"] for s in last["earlier_segments"]] == ["paused", "paused", "paused"]
    assert [s["cases_settled"] for s in last["earlier_segments"]] == [25, 40, 40]

    # The same results, case files, extras and per-case captured surfaces, line for line.
    for part in ("results", "cases.jsonl", "settled.jsonl", "captured/tools", "captured/api", "captured/receipts", "captured/arm_outputs"):
        a, b = tmp_path / "plain" / "run" / part, out / part
        assert (_files(a) == _files(b)) if a.is_dir() else (a.read_text() == b.read_text()), part
    assert {name: e.seen for name, e in x3.items()} == {name: e.seen for name, e in plain_extra.items()}
    assert last["extras"] == plain["extras"] and last["counts"] == plain["counts"]
    assert last["isolation"] == plain["isolation"]                     # every case screened once
    # The same ledgers.
    keep = ("budget", "settled_calls", "open_reservations", "committed_calls", "remaining", "calls_by_arm", "tokens", "refused",
            "cap_violations", "recovered_after_crash", "cases_reconciled_with_provider")
    assert {k: last["ledger"][k] for k in keep} == {k: plain["ledger"][k] for k in keep}
    assert campaign.spent == plain_campaign.spent == last["ledger"]["committed_calls"]
    assert len(campaign.load()["entries"]) == 1 and campaign.load()["entries"][0]["reserved"] == 4000
    # The same scores and the same report.
    selection = scorer_view(sel_dir / "selection.json")
    truth = {w: worlds[w][0] for w in worlds}
    db = FixtureDatabase()
    reports = {}
    for name, run_dir, manifest in (("plain", tmp_path / "plain" / "run", plain), ("parts", out, last)):
        scores = score_run(run_dir, selection, truth, ingestion=db, resolver=db)
        canary = TruthScanner(truth_vocabulary(truth["E1"])).scan_run(run_dir)
        assert canary["verdict"] == "clean"
        reports[name] = (scores, build_report(selection, scores=scores, run_manifest=manifest, canary=canary))
    assert reports["parts"][0] == reports["plain"][0]
    report = reports["parts"][1]
    assert report["interim"] is None and "INTERIM" not in render_markdown(report)
    assert report["validity"]["verdict"] == "valid" and report["validity"]["parts"] == 4
    for key in ("pass_bars", "cells", "abstention", "versus_rulecode", "usage", "extras"):
        assert report[key] == reports["plain"][1][key], key


def test_resuming_holds_the_whole_budget_again_and_is_refused_if_it_no_longer_fits(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    campaign = CallLedger(write_campaign_ledger(tmp_path / "ledger.json", spent=0))
    _part(tmp_path / "run", config, sel_dir, worlds, campaign=campaign, max_cases=3)
    assert campaign.spent == 30 and campaign.summary()["open_reservations"] == []
    campaign.reserve("something else", 100)                            # the pause freed the rest, and another run took some
    with pytest.raises(LedgerRefused):
        _part(tmp_path / "run", config, sel_dir, worlds, campaign=campaign, resume=True)
    assert campaign.spent == 130 and len(read_jsonl(tmp_path / "run" / "settled.jsonl")) == 3   # nothing ran, nothing changed
    campaign.settle("something else", 0)
    seen = {}

    class Watching(FakeAgent):
        def __call__(self, case):
            seen.setdefault("held", campaign.spent)
            return super().__call__(case)
    truth = {w: worlds[w][0] for w in worlds}
    manifest = run(sel_dir / "selection.json", tmp_path / "run", arms=build_arms(config, Watching(truth), notools_turn_factory()[0]),
                   case_source=FixtureCaseSource(), config=config, campaign=campaign, resume=True, max_cases=5)
    assert seen["held"] == 4000 and manifest["status"] == "paused" and campaign.spent == 50


def test_score_and_report_work_on_a_paused_run_and_the_report_says_interim(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    manifest, _, _ = _part(tmp_path / "run", config, sel_dir, worlds, max_cases=25)
    selection = scorer_view(sel_dir / "selection.json")
    truth = {w: worlds[w][0] for w in worlds}
    db = FixtureDatabase()
    scores = score_run(tmp_path / "run", selection, truth, ingestion=db, resolver=db)
    assert len(scores) == 25 * 4 and {s["phase"] for s in scores} == {"main"}
    canary = TruthScanner(truth_vocabulary(truth["E1"])).scan_run(tmp_path / "run")
    report = build_report(selection, scores=scores, run_manifest=manifest, canary=canary)
    assert report["interim"]["cases_settled"] == 25 and report["interim"]["cases_total"] == 70 and report["interim"]["max_cases"] == 25
    assert {b["verdict"] for b in report["pass_bars"]} <= {INTERIM_VERDICT, "not run"}      # counts, never a pass or a fail
    assert any(b.get("result", {}).get("n") for b in report["pass_bars"])
    assert report["validity"]["verdict"] == "interim: paused after 25 of 70 cases, not a final result (nothing invalid so far)"
    assert report["validity"]["reasons"] == []
    md = render_markdown(report)
    assert md.splitlines()[0] == "# Stage 3 blind evaluation report (INTERIM: first 25 of 70 cases in the pre-registered order)"
    assert "**Interim look over the first 25 of 70 cases in the pre-registered order." in md and "PASS" not in md and "FAIL" not in md
    # Something really wrong is still invalid, interim or not.
    bad = {**manifest, "provenance": {"model_calls": {"succeeded": {"m": 90}, "failed": {"m": 10}}}}
    assert build_report(selection, scores=scores, run_manifest=bad, canary=canary)["validity"]["verdict"] == "invalid"
    # The command line's report on the paused directory (scores and manifest as the commands left them).
    (tmp_path / "run" / "canary.json").write_text(json.dumps(canary, default=str))
    assert main(["report", "--selection", str(sel_dir / "selection.json"), "--run", str(tmp_path / "run")]) == 0
    assert "(INTERIM: first 25 of 70 cases in the pre-registered order)" in (tmp_path / "run" / "report.md").read_text()
    assert json.loads((tmp_path / "run" / "report.json").read_text())["interim"]["cases_settled"] == 25
    # A part that ended as anything but paused stays disclosed and makes the whole run invalid.
    stopped = {**manifest, "status": "completed", "progress": {**manifest["progress"], "paused": False},
               "earlier_segments": [{"status": "stopped: per-case cap violated (x)", "provenance": {}}]}
    v = build_report(selection, scores=scores, run_manifest=stopped, canary=canary)["validity"]
    assert v["verdict"] == "invalid" and "an earlier part of this run did not end as paused" in v["reasons"][0]


def test_cli_max_cases_then_resume(tmp_path, selected, capsys, campaign_ledger_file, monkeypatch):
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    _config, sel_dir, _ = selected
    wiring = "stage3_eval.tests.test_campaign:fake_wiring"
    base = ["run", "--selection", str(sel_dir / "selection.json"), "--out", str(tmp_path / "run"), "--wiring", wiring]
    with pytest.raises(SystemExit, match="--max-cases must be 1 or more"):
        main(base + ["--max-cases", "0"])
    assert not (tmp_path / "run").exists()
    # The fixture selection is sealed with the whole 4,000, so the test's ledger starts empty.
    write_campaign_ledger(campaign_ledger_file, spent=0)
    assert main(base + ["--max-cases", "5"]) == 0
    printed = json.loads(capsys.readouterr().out)
    # This test process has the scorer side loaded, which the command line flags (as it must); the pause is still recorded.
    assert printed["status"].endswith("was: paused") and printed["progress"]["paused"] and printed["progress"]["cases_settled"] == 5
    assert printed["campaign_ledger"]["spent"] == 50 and printed["campaign_ledger"]["open_reservations"] == []
    assert main(base + ["--resume", "--max-cases", "12"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["progress"]["cases_settled"] == 12 and printed["campaign_ledger"]["spent"] == 120
    assert main(base + ["--resume"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["progress"] == {"paused": False, "cases_settled": 70, "cases_total": 70, "max_cases": None,
                                   "order": "pre-registered (selection.json)", "stop_rule": None}
    assert printed["campaign_ledger"]["spent"] == 700 and printed["ledger"]["open_reservations"] == 0
    assert len(read_jsonl(tmp_path / "run" / "results" / "main" / "agent.jsonl")) == 70
