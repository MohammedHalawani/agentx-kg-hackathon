"""The post hoc completion (`rerun-failed`): exactly the provider-failed cases of a finished run, in the pre-registered
order, into a new directory, through the campaign ledger, with the source run untouched; and the union report."""
import hashlib
import json
from pathlib import Path

import pytest

from stage3_eval import completion
from stage3_eval.__main__ import main
from stage3_eval.arms import AgentArm, NoToolsArm
from stage3_eval.budget import read_ledger
from stage3_eval.fixtures.fakes import FixtureCaseSource, FixtureCapture, FixtureDatabase
from stage3_eval.records import ArmResult
from stage3_eval.report import build_report, render_markdown
from stage3_eval.runner import load_selection, run
from stage3_eval.scoring import score_run
from stage3_eval.selection import scorer_view

from .conftest import FakeAgent, build_arms, fixture_worlds, notools_turn_factory, read_jsonl, write_campaign_ledger

QUOTA_AFTER = 6          # the provider's quota runs out after this many E2 cases


def tree_hash(root):
    """Every file of a directory, by relative path and content."""
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


class Quota:
    """A provider that stops answering part way through E2, shared by the agent and the no-tools model of one run.
    Two E2 cases before that end degraded for other reasons (invalid output, the cap), and one has an agent answer but
    a no-tools provider failure."""

    def __init__(self, truth, order):
        self.inner, self.out, self.seen = FakeAgent(truth), False, []
        e2 = [key for key in order if key.startswith("E2:")]
        self.invalid, self.capped, self.notools_only = e2[1], e2[2], e2[3]
        self.failing = set(e2[QUOTA_AFTER:])
        self.fail_notools = False

    def agent(self, case):
        self.seen.append(case.key)
        self.fail_notools = case.key in self.failing or case.key == self.notools_only
        if case.key in self.failing:
            return ArmResult(case_key=case.key, arm="agent", shipment_id=case.shipment_id, case_id=case.case_id, as_of=case.as_of, degraded=True,
                             failure_mode="model_unavailable", validation_error="model call failed (RateLimitError)", calls_used=2)
        if case.key in (self.invalid, self.capped):
            mode = "invalid_model_output" if case.key == self.invalid else "model_call_cap"
            return ArmResult(case_key=case.key, arm="agent", shipment_id=case.shipment_id, case_id=case.case_id, as_of=case.as_of, degraded=True,
                             failure_mode=mode, calls_used=5, cap_hit=mode == "model_call_cap")
        return self.inner(case)

    def notools(self, messages):
        if self.fail_notools:
            raise TimeoutError("quota")
        return notools_turn_factory()[0](messages)


@pytest.fixture
def finished(tmp_path, selected):
    """A finished run whose provider ran out of quota part way through E2, with its selection."""
    config, sel_dir, _ = selected
    truth = {w: rows for w, (rows, _replay) in fixture_worlds().items()}
    selection, _sha = load_selection(sel_dir / "selection.json")
    order = [row["key"] for row in selection["cases"]]
    quota = Quota(truth, order)
    arms = {**build_arms(config, quota.agent, quota.notools)}
    manifest = run(sel_dir / "selection.json", tmp_path / "run1", arms=arms, case_source=FixtureCaseSource(), config=config,
                   capture=FixtureCapture(), provenance={"model_calls": {"succeeded": {"gpt-oss": 500}, "failed": {}}, "dirty_tree": False})
    assert manifest["status"] == "completed"
    return {"config": config, "sel_dir": sel_dir, "selection": selection, "order": order, "quota": quota, "truth": truth,
            "run": tmp_path / "run1", "tmp": tmp_path}


def completion_arms(config, truth, calls=None):
    """The provider is back: the agent and the no-tools model answer."""
    agent = FakeAgent(truth)
    turn, seen = notools_turn_factory()
    return {"agent": AgentArm(agent, config.c_cap, config.r_cap), "notools": NoToolsArm(turn=turn)}, agent, seen


def test_the_plan_is_exactly_the_provider_failed_cases_in_the_pre_registered_order(finished):
    f, quota = finished, finished["quota"]
    todo = completion.plan(f["selection"], f["run"], world="E2")
    expected = [k for k in f["order"] if k in quota.failing or k == quota.notools_only]
    assert todo["keys"] == expected and len(expected) == len([k for k in f["order"] if k.startswith("E2:")]) - QUOTA_AFTER + 1
    assert todo["by_world"] == {"E2": len(expected)} and todo["failed_in_other_worlds"] == 0
    # A result that holds an answer is never re-run: not an invalid one, not a capped one, not a wrong one.
    assert quota.invalid not in todo["keys"] and quota.capped not in todo["keys"] and not [k for k in todo["keys"] if k.startswith("E1:")]
    assert todo["failed_arms"][quota.notools_only] == ["notools"] and todo["failed_arms"][expected[-1]] == ["agent", "notools"]
    # The snapshot of each is the one the source run recorded.
    recorded = {r["key"]: r["as_of"] for r in read_jsonl(f["run"] / "cases.jsonl")}
    assert todo["as_of"] == {k: recorded[k] for k in expected}
    # By arm, and by world.
    assert completion.plan(f["selection"], f["run"], arms=("agent",), world="E2")["keys"] == [k for k in f["order"] if k in quota.failing]
    assert completion.plan(f["selection"], f["run"], world="E1")["keys"] == []
    assert completion.plan(f["selection"], f["run"], world="E1")["failed_in_other_worlds"] == len(expected)
    with pytest.raises(ValueError, match="model arms only"):
        completion.plan(f["selection"], f["run"], arms=("rulecode",))


def test_the_completion_runs_only_those_cases_into_a_new_directory_through_the_ledger(finished, campaign_ledger_file):
    from operations.call_ledger import CallLedger
    f, quota = finished, finished["quota"]
    config = f["config"]
    before = tree_hash(f["run"])
    todo = completion.plan(f["selection"], f["run"], world="E2")
    n = len(todo["keys"])
    arms, agent, notools_seen = completion_arms(config, f["truth"])
    campaign = CallLedger(campaign_ledger_file)
    provider = {"calls": 0}
    held = []

    def counted(case, inner=arms["agent"].run_case):
        held.append(campaign.entry(f"stage3 completion done of run1 selection {load_selection(f['sel_dir'] / 'selection.json')[1][:12]}"))
        provider["calls"] += 9 + 1                      # the agent's nine and the no-tools call that follows it
        return inner(case)
    arms["agent"] = AgentArm(counted, config.c_cap, config.r_cap)
    manifest = completion.rerun_failed(f["sel_dir"] / "selection.json", f["run"], f["tmp"] / "done", arms=arms, config=config, world="E2",
                                       capture=FixtureCapture(), campaign=campaign, campaign_commit="c" * 40,
                                       provider_calls=lambda: provider["calls"], provenance={"dirty_tree": False})
    out = f["tmp"] / "done"
    assert manifest["status"] == "completed" and manifest["progress"]["cases_total"] == n == manifest["progress"]["cases_settled"]
    # The source run directory is exactly as it was.
    assert tree_hash(f["run"]) == before
    # Only the listed cases ran, in the pre-registered order, and only the model arms.
    assert agent.seen == todo["keys"] and len(notools_seen) == n
    assert sorted(p.name for p in (out / "results" / "main").iterdir()) == ["agent.jsonl", "notools.jsonl"]
    assert [r["key"] for r in read_jsonl(out / "settled.jsonl")] == todo["keys"] == [r["key"] for r in read_jsonl(out / "cases.jsonl")]
    # Each as of its original snapshot time, with its original case id and opening facts.
    original = {r["key"]: r for r in read_jsonl(f["run"] / "cases.jsonl")}
    for row in read_jsonl(out / "cases.jsonl"):
        assert row == original[row["key"]]
    for arm in ("agent", "notools"):
        rows = read_jsonl(out / "results" / "main" / f"{arm}.jsonl")
        assert [r["case_key"] for r in rows] == todo["keys"]
        assert all(r["as_of"] == original[r["case_key"]]["as_of"] and not r["degraded"] for r in rows)
    # The ledger: the worst case of these cases only is the run's budget and what the campaign held while it ran;
    # every case is reconciled with the provider's count; the entry is settled at what was used.
    worst = n * (config.c_cap + 3)
    assert manifest["ledger"]["budget"] == worst == manifest["completion"]["worst_case_calls"]["total"] < config.budget
    assert manifest["completion"]["worst_case_calls"]["per_case"] == config.c_cap + 3
    assert held[0]["calls"] == worst and held[0]["finished_at"] is None
    used = n * 9 + n
    assert manifest["ledger"]["committed_calls"] == used == manifest["campaign_ledger"]["calls"]
    assert manifest["ledger"]["cases_reconciled_with_provider"] == n and manifest["ledger"]["provider_calls_at_last_reconciliation"] == used
    assert campaign.spent == 173 + used and campaign.summary()["open_reservations"] == []
    events = read_ledger(out / "ledger.jsonl")
    assert sum(1 for e in events if e["event"] == "reserve") == 2 * n and not [e for e in events if e["event"] == "reserve" and e["calls"] > config.c_cap]
    # The manifest says what this is.
    record = manifest["completion"]
    assert record["post_hoc"] is True and record["label"] == "completed post hoc after a provider quota failure" == completion.LABEL
    assert record["source_run"] == str(f["run"].resolve()) and record["case_keys"] == todo["keys"] and record["arms_rerun"] == ["agent", "notools"]
    assert record["source_modified"] is False and record["worlds"] == {"E2": n} and record["kept_from_source"] == ["rulecode", "symptom"]
    assert record["original_as_of"] == todo["as_of"] and record["source_status"] == "completed"
    assert record["notools_arm"] == {"max_calls": 3, "sealed_max_calls": 3, "is_the_sealed_arm": True}
    assert manifest["selection_sha256"] == json.loads((f["run"] / "run_manifest.json").read_text())["selection_sha256"]
    assert json.loads((out / "run_manifest.json").read_text())["completion"]["case_keys"] == todo["keys"]
    # The captured surfaces and the marker screen are the run's.
    assert manifest["isolation"]["cases_screened_for_truth_markers"] == n
    for surface in ("tools", "api", "receipts", "graph", "logs", "arm_outputs"):
        assert any((out / "captured" / surface).iterdir()), surface


def test_one_arm_only_and_a_pause_and_resume(finished, campaign_ledger_file):
    f = finished
    config = f["config"]
    todo = completion.plan(f["selection"], f["run"], arms=("agent",), world="E2")
    arms, agent, notools_seen = completion_arms(config, f["truth"])
    arguments = dict(arms=arms, config=config, world="E2", rerun_arms=("agent",), capture=FixtureCapture())
    paused = completion.rerun_failed(f["sel_dir"] / "selection.json", f["run"], f["tmp"] / "agent_only", max_cases=2, **arguments)
    assert paused["status"] == "paused" and agent.seen == todo["keys"][:2] and paused["ledger"]["budget"] == len(todo["keys"]) * config.c_cap
    manifest = completion.rerun_failed(f["sel_dir"] / "selection.json", f["run"], f["tmp"] / "agent_only", resume=True, **arguments)
    assert manifest["status"] == "completed" and agent.seen == todo["keys"] and not notools_seen
    assert manifest["completion"]["arms_rerun"] == ["agent"] and manifest["completion"]["kept_from_source"] == ["notools", "rulecode", "symptom"]
    assert "notools_arm" not in manifest["completion"] and list(manifest["arms"]) == ["agent"]
    assert sorted(p.name for p in (f["tmp"] / "agent_only" / "results" / "main").iterdir()) == ["agent.jsonl"]
    assert len(read_jsonl(f["tmp"] / "agent_only" / "results" / "main" / "agent.jsonl")) == len(todo["keys"])


def test_a_case_that_would_be_investigated_at_another_time_stops_the_run_before_any_call(finished):
    from dataclasses import replace
    f = finished
    config = f["config"]
    arms, agent, notools_seen = completion_arms(config, f["truth"])

    class Drifted(completion.RecordedCaseSource):
        def case_ref(self, world, shipment_id):
            ref = super().case_ref(world, shipment_id)
            return replace(ref, as_of="2026-09-20T00:00:00+00:00")
    manifest = completion.rerun_failed(f["sel_dir"] / "selection.json", f["run"], f["tmp"] / "drift", arms=arms, config=config, world="E2",
                                       case_source=Drifted(f["run"]))
    assert manifest["status"].startswith("stopped:") and "not its original snapshot" in manifest["status"]
    assert not agent.seen and not notools_seen and manifest["ledger"]["committed_calls"] == 0

    # The agent's own record must carry that snapshot too.
    def late(case, inner=FakeAgent(f["truth"])):
        result = inner(case)
        result.as_of = "2026-09-20T00:00:00+00:00"
        return result
    arms["agent"] = AgentArm(late, config.c_cap, config.r_cap)
    manifest = completion.rerun_failed(f["sel_dir"] / "selection.json", f["run"], f["tmp"] / "late", arms=arms, config=config, world="E2")
    assert manifest["status"].startswith("stopped:") and "the agent's snapshot" in manifest["status"]
    assert len(read_jsonl(f["tmp"] / "late" / "results" / "main" / "agent.jsonl")) == 1


def test_what_a_completion_refuses(finished, tmp_path, campaign_ledger_file):
    from operations.call_ledger import CallLedger, LedgerRefused
    f = finished
    config = f["config"]
    arms, agent, _seen = completion_arms(config, f["truth"])
    selection_path = f["sel_dir"] / "selection.json"
    before = tree_hash(f["run"])
    with pytest.raises(ValueError, match="never into the run it completes"):
        completion.rerun_failed(selection_path, f["run"], f["run"] / "completion", arms=arms, config=config, world="E2")
    with pytest.raises(ValueError, match="never into the run it completes"):
        completion.rerun_failed(selection_path, f["run"], f["run"], arms=arms, config=config, world="E2")
    with pytest.raises(ValueError, match="nothing to complete"):
        completion.rerun_failed(selection_path, f["run"], tmp_path / "e1", arms=arms, config=config, world="E1")
    # A campaign ledger with no room for the worst case of these cases: refused before anything is written or called.
    n = len(completion.plan(f["selection"], f["run"], world="E2")["keys"])
    tight = CallLedger(write_campaign_ledger(tmp_path / "tight.json", spent=100, cap=100 + n * (config.c_cap + 3) - 1))
    with pytest.raises(LedgerRefused):
        completion.rerun_failed(selection_path, f["run"], tmp_path / "tight", arms=arms, config=config, world="E2", campaign=tight)
    assert tight.spent == 100 and not (tmp_path / "tight").exists() and not agent.seen
    # A run of another selection, and a completion of a completion.
    manifest_path = f["run"] / "run_manifest.json"
    original = manifest_path.read_text(encoding="utf-8")
    other = tmp_path / "other_run"
    (other / "results" / "main").mkdir(parents=True)
    (other / "run_manifest.json").write_text(json.dumps({**json.loads(original), "selection_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="not a run of this selection"):
        completion.rerun_failed(selection_path, other, tmp_path / "x", arms=arms, config=config, world="E2")
    done = completion.rerun_failed(selection_path, f["run"], tmp_path / "done", arms=arms, config=config, world="E2")
    assert done["status"] == "completed"
    with pytest.raises(ValueError, match="is itself a completion"):
        completion.rerun_failed(selection_path, tmp_path / "done", tmp_path / "again", arms=arms, config=config, world="E2")
    with pytest.raises(FileExistsError):           # every attempt gets its own directory
        completion.rerun_failed(selection_path, f["run"], tmp_path / "done", arms=arms, config=config, world="E2")
    assert tree_hash(f["run"]) == before


def _scored(f, out):
    """Score the source run and its completion, each in its own directory, as `score` does."""
    selection = scorer_view(f["sel_dir"] / "selection.json")
    db = FixtureDatabase()
    scores = score_run(f["run"], selection, f["truth"], ingestion=db, resolver=db)
    done = score_run(out, selection, f["truth"], ingestion=db, resolver=db)
    return selection, scores, done


def test_the_union_report_completes_e2_labels_it_and_leaves_e1_exactly_as_scored(finished):
    f, quota = finished, finished["quota"]
    config = f["config"]
    arms, _agent, _seen = completion_arms(config, f["truth"])
    out = f["tmp"] / "done"
    done_manifest = completion.rerun_failed(f["sel_dir"] / "selection.json", f["run"], out, arms=arms, config=config, world="E2",
                                            capture=FixtureCapture(), provenance={"dirty_tree": False})
    selection, scores, done_scores = _scored(f, out)
    keys = done_manifest["completion"]["case_keys"]
    assert {r["key"] for r in done_scores} == set(keys) and {r["arm"] for r in done_scores} == {"agent", "notools"}
    manifest = json.loads((f["run"] / "run_manifest.json").read_text(encoding="utf-8"))
    plain = build_report(selection, scores=scores, run_manifest=manifest)
    union = build_report(selection, scores=scores, run_manifest=manifest, completion={"manifest": done_manifest, "scores": done_scores, "canary": None})
    cells = lambda report, world: [c for c in report["cells"] if c["world"] == world]
    # E1 exactly as scored from the original run, cell for cell, and the pass bars (E1) with it.
    assert json.dumps(cells(union, "E1"), sort_keys=True, default=str) == json.dumps(cells(plain, "E1"), sort_keys=True, default=str)
    assert union["pass_bars"] == plain["pass_bars"] and not [c for c in cells(union, "E1") if "post_hoc" in c]
    # E2 from the union, every cell labelled, the re-run cases counted per cell.
    strata = {c["key"]: c["stratum"] for c in selection["cases"]}
    for cell in cells(union, "E2"):
        expected = sum(1 for k in keys if strata[k] == cell["stratum"])
        assert cell["post_hoc"] == {"label": "completed post hoc after a provider quota failure", "cases_rerun": expected,
                                    "arms_rerun": ["agent", "notools"], "cases_from_the_original_run": cell["selected"] - expected}
    degraded = lambda report, arm: sum(c["arms"][arm]["categories"]["degraded"] for c in cells(report, "E2"))
    scored = lambda report, arm: sum(c["arms"][arm]["accuracy"]["n"] for c in cells(report, "E2"))
    assert degraded(plain, "agent") == len(quota.failing) + 2 and degraded(union, "agent") == 2      # the invalid and the capped one stay
    assert degraded(plain, "notools") == len(quota.failing) + 1 and degraded(union, "notools") == 0
    assert scored(union, "agent") == scored(plain, "agent") and scored(union, "rulecode") == scored(plain, "rulecode")
    for arm in ("rulecode", "symptom"):                # kept from the source run
        assert [c["arms"][arm] for c in cells(union, "E2")] == [c["arms"][arm] for c in cells(plain, "E2")]
    # The original non-failed E2 results are the source run's own rows.
    from stage3_eval.report import union_scores
    rows, counts = union_scores(scores, done_scores, done_manifest)
    assert counts == {"listed_cases": len(keys), "arms_rerun": ["agent", "notools"], "results_replaced": 2 * len(keys),
                      "results_listed": 2 * len(keys), "results_not_completed": 0}
    assert len(rows) == len(scores)
    kept = [r for r in rows if not r.get("post_hoc_completion")]
    assert all(r in scores for r in kept) and len(kept) == len(scores) - 2 * len(keys)
    assert {(r["key"], r["arm"]) for r in rows if r.get("post_hoc_completion")} == {(k, a) for k in keys for a in ("agent", "notools")}
    # Said in the report, at the top and on every E2 line.
    info = union["post_hoc_completion"]
    assert info["label"] == completion.LABEL and info["worlds"] == ["E2"] and info["cases_rerun"] == len(keys) and info["case_keys"] == keys
    assert "The cells of E1 are exactly as scored from the original run." in info["statement"]
    assert info["completion_run"]["status"] == "completed" and "post_hoc_completion" not in plain
    md = render_markdown(union)
    assert "**E2: completed post hoc after a provider quota failure.**" in md
    assert "| E2 / identifiable_ambiguous (completed post hoc after a provider quota failure:" in md
    assert "| E1 / identifiable_ambiguous |" in md and "E1 / identifiable_ambiguous (completed" not in md
    assert "post hoc" not in render_markdown(plain)


def test_a_completion_that_did_not_finish_leaves_the_rest_as_the_source_run_scored_it(finished):
    f = finished
    config = f["config"]
    arms, _agent, _seen = completion_arms(config, f["truth"])
    out = f["tmp"] / "part"
    done_manifest = completion.rerun_failed(f["sel_dir"] / "selection.json", f["run"], out, arms=arms, config=config, world="E2", max_cases=3)
    selection, scores, done_scores = _scored(f, out)
    from stage3_eval.report import union_scores
    rows, counts = union_scores(scores, done_scores, done_manifest)
    listed = len(done_manifest["completion"]["case_keys"])
    assert counts["results_replaced"] == 6 and counts["results_not_completed"] == 2 * listed - 6
    assert sum(1 for r in rows if r["arm"] == "agent" and r.get("failure_mode") == "model_unavailable") == listed - 3


def test_the_command_line_lists_runs_and_reports(finished, capsys, campaign_ledger_file, monkeypatch):
    f = finished
    monkeypatch.delenv("SUHAIL_EVAL_TRUTH_ROOT", raising=False)
    selection_path, run_dir, out = str(f["sel_dir"] / "selection.json"), str(f["run"]), f["tmp"] / "cli"
    before = tree_hash(f["run"])
    todo = completion.plan(f["selection"], f["run"], world="E2")
    capsys.readouterr()
    # The dry mode: the list and its worst case; no wiring, no directory, no ledger entry.
    assert main(["rerun-failed", "--selection", selection_path, "--run", run_dir, "--world", "E2", "--dry-run"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["dry_run"] and listed["cases"] == len(todo["keys"]) and listed["case_keys"] == todo["keys"] and listed["by_world"] == {"E2": listed["cases"]}
    assert listed["worst_case_calls"] == {"per_arm": {"agent": 12, "notools": 3}, "per_case": 15, "total": 15 * listed["cases"]}
    assert not out.exists() and json.loads(Path(campaign_ledger_file).read_text())["entries"][0]["calls"] == 173
    assert main(["rerun-failed", "--selection", selection_path, "--run", run_dir, "--world", "E2", "--arm", "agent", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["worst_case_calls"]["per_case"] == 12
    for bad in (["--world", "E3"], ["--world", "E2", "--arm", "rulecode"], ["--world", "E2"]):      # the last: no --out, no --wiring
        with pytest.raises(SystemExit):
            main(["rerun-failed", "--selection", selection_path, "--run", run_dir, *bad])
    with pytest.raises(SystemExit, match="nothing to complete"):
        main(["rerun-failed", "--selection", selection_path, "--run", run_dir, "--world", "E1", "--out", str(out), "--wiring", WIRING])
    capsys.readouterr()
    # The run, through a wiring that is told the source run and the cases.
    assert main(["rerun-failed", "--selection", selection_path, "--run", run_dir, "--world", "E2", "--out", str(out), "--wiring", WIRING]) == 0
    printed = json.loads(capsys.readouterr().out)
    # (A test process has the scorer's modules loaded, which the command line's isolation check reports; nothing else is wrong.)
    assert printed["status"].endswith("completed") and printed["completion"]["case_keys"] == todo["keys"] == TOLD["keys"]
    assert TOLD["source_run"] == str(f["run"].resolve()) and TOLD["original_as_of"] == todo["as_of"] and TOLD["closed"]
    assert printed["campaign_ledger"]["spent"] == 173 + printed["ledger"]["committed_calls"]
    # Score each directory, then the union report: written with the completion, never into the source run.
    selection, scores, done_scores = _scored(f, out)
    scored_source = tree_hash(f["run"])
    assert main(["report", "--selection", selection_path, "--run", run_dir, "--completion", str(out)]) == 0
    assert Path(capsys.readouterr().out.strip()) == out / "report.md"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["post_hoc_completion"]["label"] == completion.LABEL and "completed post hoc after a provider quota failure" in (out / "report.md").read_text(encoding="utf-8")
    assert tree_hash(f["run"]) == scored_source and not (f["run"] / "report.json").exists()
    with pytest.raises(SystemExit, match="not a completion"):
        main(["report", "--selection", selection_path, "--run", run_dir, "--completion", run_dir])
    (f["run"] / "scores.jsonl").unlink()            # put the source run back as the run left it
    assert tree_hash(f["run"]) == before


TOLD = {}
WIRING = "stage3_eval.tests.test_completion:fake_completion_wiring"


def fake_completion_wiring(config, *, dry_run=False, resume=False, selection=None, source_run=None, keys=(), original_as_of=None):
    """A wiring of fakes for `rerun-failed`: no case source, so the harness reads the cases from the source run."""
    truth = {w: rows for w, (rows, _replay) in fixture_worlds().items()}
    arms, _agent, _seen = completion_arms(config, truth)
    TOLD.update(source_run=source_run, keys=list(keys), original_as_of=dict(original_as_of or {}), closed=False)
    return {"arms": arms, "capture": FixtureCapture(), "provenance": lambda: {"dirty_tree": False, "tree_changed_during_run": False},
            "close": lambda: TOLD.update(closed=True)}


def test_the_real_run_directory_if_it_is_there_gives_52_cases_all_in_e2():
    """Read-only check of the selection logic against the first evaluation run's records (skipped where they are not)."""
    run_dir = Path("C:/Projects/demo/artifacts/stage3/run1")
    selection_path = Path("C:/Projects/demo/docs/evals/2026-10-11_stage3/preregistration/selection.json")
    if not (run_dir / "results" / "main" / "agent.jsonl").exists() or not selection_path.exists():
        pytest.skip("the first evaluation run's records are not on this machine")
    selection, _sha = load_selection(selection_path)
    todo = completion.plan(selection, run_dir, world="E2")
    assert len(todo["keys"]) == 52 and todo["by_world"] == {"E2": 52} and todo["failed_in_other_worlds"] == 0
    assert completion.plan(selection, run_dir)["keys"] == todo["keys"] and completion.plan(selection, run_dir, world="E1")["keys"] == []
    order = [row["key"] for row in selection["cases"]]
    assert todo["keys"] == order[-52:]              # the quota ran out for the last 52 cases of the pre-registered order
    assert all(arms == ["agent", "notools"] for arms in todo["failed_arms"].values())
