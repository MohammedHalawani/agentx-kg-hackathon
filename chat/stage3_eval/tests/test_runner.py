"""The run step end to end over the fixture: dry run, a full fake run, the budget guard, cap violations, crash and
resume, and the refusals that keep truth out of reach."""
import json

import pytest

from stage3_eval.__main__ import dry_run_fixture
from stage3_eval.arms import AgentArm, NoToolsArm, RuleCodeArm, SymptomArm
from stage3_eval.budget import read_ledger
from stage3_eval.canary import TruthScanner
from stage3_eval.fixtures.fakes import FixtureCaseSource, FixtureCapture, FixtureDatabase
from stage3_eval.report import build_report, render_markdown
from stage3_eval.runner import run
from stage3_eval.scoring import score_run
from stage3_eval.truth_io import truth_vocabulary

from .conftest import FakeAgent, build_arms, make_config, notools_turn_factory, read_jsonl


class Exploding:
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise AssertionError("called during a dry run")


def test_dry_run_over_the_fixture_spends_zero_calls(tmp_path):
    summary, manifest, report_path = dry_run_fixture(tmp_path / "dry")
    out = tmp_path / "dry"
    for name in ("selection.json", "selection.json.sha256", "pairs.json", "strata.json"):
        assert (out / name).exists()
    ledger = read_ledger(out / "run" / "ledger.jsonl")
    assert manifest["ledger"]["settled_calls"] == 0 and manifest["ledger"]["committed_calls"] == 0
    assert not [e for e in ledger if e["event"] in ("reserve", "settle")]
    plans = [e for e in ledger if e["event"] == "plan"]
    assert sum(e["calls"] for e in plans) == manifest["ledger"]["planned_calls"] == 70 * (12 + 2)
    results = read_jsonl(out / "run" / "results" / "main" / "agent.jsonl")
    assert len(results) == 70 and all(r["not_run"] == "dry_run" for r in results)
    assert all(r["not_run"] is None for r in read_jsonl(out / "run" / "results" / "main" / "rulecode.jsonl"))
    text = report_path.read_text()
    assert "dry-run skeleton" in text and "**not run**" in text and "No model call was made" in text


def test_dry_run_never_calls_the_model_or_case_runner(tmp_path, selected):
    config, sel_dir, _ = selected
    agent, turn = Exploding(), Exploding()
    arms = {"agent": AgentArm(agent, config.c_cap), "notools": NoToolsArm(turn=turn), "rulecode": RuleCodeArm(), "symptom": SymptomArm()}
    manifest = run(sel_dir / "selection.json", tmp_path / "run", arms=arms, case_source=FixtureCaseSource(), config=config, dry_run=True)
    assert agent.calls == 0 and turn.calls == 0 and manifest["counts"]["arm_errors"] == 0


def _full_run(tmp_path, config, sel_dir, worlds, *, agent=None, budget_note=None):
    truth = {w: worlds[w][0] for w in worlds}
    agent = agent or FakeAgent(truth)
    turn, calls = notools_turn_factory("MISSED_MILESTONE")
    extras = {"cross_shipment_ablation": AgentArm(FakeAgent(truth, calls=6), config.c_cap, name="cross_shipment_ablation"),
              "stability_rerun": AgentArm(FakeAgent(truth, calls=6), config.c_cap, name="stability_rerun")}
    manifest = run(sel_dir / "selection.json", tmp_path / "run", arms=build_arms(config, agent, turn), case_source=FixtureCaseSource(),
                   config=config, capture=FixtureCapture(), extras_arms=extras,
                   provenance={"model_calls": {"succeeded": {"gpt-oss": 700}, "failed": {}}, "dirty_tree": False})
    return manifest, agent, calls


def test_full_fake_run_scores_and_reports(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    manifest, agent, notools_calls = _full_run(tmp_path, config, sel_dir, worlds)
    assert manifest["status"] == "completed" and manifest["counts"]["cases"] == 70
    led = manifest["ledger"]
    assert led["calls_by_arm"]["agent"] == 70 * 9 and led["calls_by_arm"]["notools"] == 70
    assert led["settled_calls"] <= config.budget and led["open_reservations"] == 0
    # B_notools answered at the agent's own snapshot.
    agent_rows = {r["case_key"]: r for r in read_jsonl(tmp_path / "run" / "results" / "main" / "agent.jsonl")}
    for r in read_jsonl(tmp_path / "run" / "results" / "main" / "notools.jsonl"):
        assert r["as_of"] == agent_rows[r["case_key"]]["as_of"]
    selection = json.loads((sel_dir / "selection.json").read_text())
    truth = {w: worlds[w][0] for w in worlds}
    db = FixtureDatabase()
    scores = score_run(tmp_path / "run", selection, truth, ingestion=db, resolver=db)
    main = [s for s in scores if s["phase"] == "main"]
    assert len(main) == 70 * 4
    cats = {s["category"] for s in main if s["arm"] == "agent"}
    assert {"correct_supported", "confident_wrong", "honest_uncertainty", "insufficient_when_knowable"} <= cats
    assert not [s for s in main if s["category"] == "unsafe_or_fabricated"]
    canary = TruthScanner(truth_vocabulary(truth["E1"])).scan_run(tmp_path / "run")
    assert canary["verdict"] == "clean" and not canary["missing_surfaces"]
    pairs = json.loads((sel_dir / "pairs.json").read_text())
    report = build_report(selection, scores=scores, run_manifest=manifest, canary=canary, pairs=pairs)
    assert report["validity"]["verdict"] == "valid"
    assert {b["verdict"] for b in report["pass_bars"]} <= {"PASS", "FAIL"}
    main_cell = next(c for c in report["cells"] if (c["world"], c["stratum"]) == ("E1", "identifiable_ambiguous"))
    agent_cats = main_cell["arms"]["agent"]["categories"]
    assert agent_cats["honest_uncertainty"] + agent_cats["confident_wrong"] + agent_cats["correct_supported"] + \
        agent_cats["correct_unsupported"] + agent_cats["insufficient_when_knowable"] + agent_cats["degraded"] + agent_cats["unsafe_or_fabricated"] == 34
    assert report["extras"]["stability_rerun"]["n"] > 0 and "cross_shipment_ablation" in report["extras"]
    md = render_markdown(report)
    assert "Arms side by side" in md and "honest uncertainty is never pooled" in md


def test_budget_guard_refuses_cases_that_would_cross_the_cap(tmp_path, selected, worlds, monkeypatch):
    """The sizing rule makes the main test fit by construction, so the guard is exercised with a ledger that has only
    100 calls left (as after earlier attempts or crash recoveries)."""
    import stage3_eval.runner as runner_mod
    config, sel_dir, _ = selected
    real = runner_mod.BudgetLedger
    monkeypatch.setattr(runner_mod, "BudgetLedger", lambda path, budget, **kw: real(path, 100, **kw))
    manifest, agent, _ = _full_run(tmp_path, config, sel_dir, worlds)
    led = manifest["ledger"]
    assert led["committed_calls"] <= 100 and manifest["counts"]["budget_refused"] > 0
    refused = [r for r in read_jsonl(tmp_path / "run" / "results" / "main" / "agent.jsonl") if r["not_run"] == "budget_refused"]
    assert refused and all(r["case_key"] not in agent.seen for r in refused)   # refused before anything was called


def test_cap_violation_stops_the_run(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    agent = FakeAgent({w: worlds[w][0] for w in worlds}, calls=13)    # one more than C_cap
    manifest, _, _ = _full_run(tmp_path, config, sel_dir, worlds, agent=agent)
    assert manifest["status"].startswith("stopped: per-case cap violated") and manifest["ledger"]["cap_violations"] == 1
    assert len(agent.seen) == 1


def test_crash_then_resume_never_spends_twice(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    truth = {w: worlds[w][0] for w in worlds}

    class Crashing(FakeAgent):
        def __call__(self, case):
            if len(self.seen) == 3:
                self.seen.append(case.key)
                raise KeyboardInterrupt   # the process dies mid-case (not an ordinary arm error)
            return super().__call__(case)
    crashing = Crashing(truth)
    turn, _ = notools_turn_factory()
    with pytest.raises(KeyboardInterrupt):
        run(sel_dir / "selection.json", tmp_path / "run", arms=build_arms(config, crashing, turn), case_source=FixtureCaseSource(), config=config)
    with pytest.raises(FileExistsError):
        run(sel_dir / "selection.json", tmp_path / "run", arms=build_arms(config, FakeAgent(truth), turn), case_source=FixtureCaseSource(), config=config)
    again = FakeAgent(truth)
    manifest = run(sel_dir / "selection.json", tmp_path / "run", arms=build_arms(config, again, turn), case_source=FixtureCaseSource(),
                   config=config, resume=True)
    assert manifest["ledger"]["recovered_after_crash"] == 1
    lost = crashing.seen[3]
    assert lost not in again.seen and not set(crashing.seen[:3]) & set(again.seen)
    agent_rows = read_jsonl(tmp_path / "run" / "results" / "main" / "agent.jsonl")
    assert len({r["case_key"] for r in agent_rows}) == 70
    assert next(r for r in agent_rows if r["case_key"] == lost)["failure_mode"] == "result_lost_in_crash"
    assert manifest["ledger"]["calls_by_arm"]["agent"] == 3 * 9 + 12 + 66 * 9   # the lost case at its worst case


def test_run_refuses_truth_env_tampered_selection_and_changed_config(tmp_path, selected, worlds, monkeypatch):
    config, sel_dir, _ = selected
    arms = build_arms(config, FakeAgent({w: worlds[w][0] for w in worlds}), notools_turn_factory()[0])
    monkeypatch.setenv("SUHAIL_EVAL_TRUTH_ROOT", "/somewhere")
    with pytest.raises(RuntimeError, match="must not be able to find truth"):
        run(sel_dir / "selection.json", tmp_path / "a", arms=arms, case_source=FixtureCaseSource(), config=config)
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT")
    with pytest.raises(ValueError, match="sealed"):
        run(sel_dir / "selection.json", tmp_path / "b", arms=arms, case_source=FixtureCaseSource(), config=make_config(c_cap=13))
    path = sel_dir / "selection.json"
    path.write_text(path.read_text().replace('"order": 0', '"order": 99'))
    with pytest.raises(ValueError, match="pre-registered sha256"):
        run(path, tmp_path / "c", arms=arms, case_source=FixtureCaseSource(), config=config)


def test_missing_arm_and_unopened_cases(tmp_path, selected, worlds):
    config, sel_dir, _ = selected
    arms = build_arms(config, FakeAgent({w: worlds[w][0] for w in worlds}), notools_turn_factory()[0])
    with pytest.raises(ValueError, match="missing"):
        run(sel_dir / "selection.json", tmp_path / "a", arms={k: v for k, v in arms.items() if k != "notools"}, case_source=FixtureCaseSource(), config=config)

    class NoCases:
        def case_ref(self, world, sid):
            return None
    manifest = run(sel_dir / "selection.json", tmp_path / "b", arms=arms, case_source=NoCases(), config=config)
    assert manifest["counts"]["not_opened"] == 70 and manifest["ledger"]["settled_calls"] == 0


def test_cli_select_then_report_skeleton(tmp_path, capsys):
    import shutil
    from stage3_eval.__main__ import main
    from stage3_eval.fixtures.fakes import world_dir
    for w in ("E1", "E2"):
        shutil.copytree(world_dir(w) / "truth", tmp_path / f"truth_{w}" / "development")
    args = ["select", "--freeze-commit", "c" * 40, "--c-cap", "12", "--out", str(tmp_path / "pre")]
    for w in ("E1", "E2"):
        args += ["--world", f"{w}={tmp_path / f'truth_{w}' / 'development'}", "--database", f"{w}=shipments-v2-world-{w.lower()}"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["selected"] == 70
    sealed = json.loads((tmp_path / "pre" / "selection.json").read_text())["config"]["worlds"]
    assert sealed == {"E1": {"database": "shipments-v2-world-e1"}, "E2": {"database": "shipments-v2-world-e2"}}
    assert main(["report", "--selection", str(tmp_path / "pre" / "selection.json")]) == 0
    assert "dry-run skeleton" in (tmp_path / "pre" / "report.md").read_text()


def test_selection_hash_is_the_same_whatever_the_line_endings(tmp_path, selected):
    """The pre-registered files are written with LF on every platform, and a checkout that turned them into CRLF
    (Git's line-ending conversion on Windows) still verifies; a change of content still does not."""
    import hashlib
    from stage3_eval.runner import load_selection
    _config, sel_dir, summary = selected
    for name in ("selection.json", "pairs.json", "strata.json"):
        data = (sel_dir / name).read_bytes()
        assert b"\r" not in data and b"\r" not in (sel_dir / f"{name}.sha256").read_bytes()
        assert (sel_dir / f"{name}.sha256").read_text().split()[0] == hashlib.sha256(data).hexdigest()   # as sha256sum reads it
    _document, digest = load_selection(sel_dir / "selection.json")
    assert digest == summary["hashes"]["selection"]
    path = sel_dir / "selection.json"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    sidecar = sel_dir / "selection.json.sha256"
    sidecar.write_bytes(sidecar.read_bytes().replace(b"\n", b"\r\n"))
    assert load_selection(path)[1] == digest
    path.write_bytes(path.read_bytes().replace(b'"order": 0', b'"order": 9'))
    with pytest.raises(ValueError, match="pre-registered sha256"):
        load_selection(path)
