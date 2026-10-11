"""The recorded automatic checkpoint of a paused run (`python -m stage3_eval checkpoint`): it reads no truth, passes
on a healthy paused run, and fails on each condition by itself. Fakes only: one good paused run of the fixture is
made once, and every failing case is a copy of it with one thing changed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from operations.call_ledger import CallLedger
from stage3_eval import runner as runner_mod
from stage3_eval.__main__ import main
from stage3_eval.arms import AgentArm
from stage3_eval.checkpoint import DEFAULT_THRESHOLDS, checkpoint, scan_markers, write_checkpoint
from stage3_eval.fixtures.fakes import FixtureCapture, FixtureCaseSource, FixtureDatabase
from stage3_eval.records import from_ops_run
from stage3_eval.runner import run
from stage3_eval.selection import select

from .conftest import FakeAgent, build_arms, fixture_worlds, make_config, notools_turn_factory, read_jsonl, write_campaign_ledger

PAUSE_AT = 40
WIRED = {}


class InTimeAgent(FakeAgent):
    """FakeAgent "retrieves" a case's deciding record whether or not it exists yet. A real investigation cannot: this
    one keeps only what the fixture database held at the snapshot."""

    def __call__(self, case):
        result = super().__call__(case)
        held = FixtureDatabase().ingested(case.world, case.as_of)
        result.retrieved_ids = [i for i in result.retrieved_ids if i in held]
        result.steps = [{**step, "evidence_ids": [i for i in step["evidence_ids"] if i in held]} for step in result.steps]
        return result


def checkpoint_wiring(config, *, run_dir=None):
    """Stands in for scripts.stage3_wiring:build_checkpoint: the fixture database is the evidence resolver."""
    WIRED.update(config=config, run_dir=run_dir, closed=False)
    return {"resolver": FixtureDatabase(), "close": lambda: WIRED.update(closed=True)}


@pytest.fixture(scope="module")
def good(tmp_path_factory):
    """(selection.json, run directory) of a healthy run paused after 40 cases, as a clean run process leaves it: the
    test process has the scorer side loaded, so the manifest's own reading of the loaded modules is stood in for."""
    root = tmp_path_factory.mktemp("checkpoint")
    worlds, config = fixture_worlds(), make_config()
    select(worlds, config, root / "sel")
    truth = {w: worlds[w][0] for w in worlds}
    agent = InTimeAgent(truth)
    turn, notools_calls = notools_turn_factory()
    provider = lambda: 9 * len(agent.seen) + len(notools_calls)
    campaign = CallLedger(write_campaign_ledger(root / "campaign.json", spent=0))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner_mod, "truth_modules_loaded", lambda: [])
        for name in [n for n in os.environ if "TRUTH" in n.upper()]:
            patch.delenv(name)
        manifest = run(root / "sel" / "selection.json", root / "run", arms=build_arms(config, agent, turn), case_source=FixtureCaseSource(),
                       config=config, capture=FixtureCapture(), extras_arms={"stability_rerun": AgentArm(FakeAgent(truth), config.c_cap, name="stability_rerun")},
                       extras_path=root / "sel" / "extras.json", campaign=campaign, provider_calls=provider, max_cases=PAUSE_AT,
                       provenance=lambda: {"model_calls": {"succeeded": {"gpt-oss": provider()}, "failed": {}}, "dirty_tree": False})
    assert manifest["status"] == "paused" and manifest["progress"]["cases_settled"] == PAUSE_AT
    return root / "sel" / "selection.json", root / "run"


def _copy(good, tmp_path):
    selection, run_dir = good
    shutil.copytree(run_dir, tmp_path / "run")
    return selection, tmp_path / "run"


def _rows(path, change):
    rows = read_jsonl(path)
    change(rows)
    Path(path).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _manifest(run_dir, change):
    path = run_dir / "run_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _agent(run_dir, change):
    _rows(run_dir / "results" / "main" / "agent.jsonl", change)


def test_a_healthy_paused_run_passes_and_the_checkpoint_is_recorded(good, tmp_path):
    selection, run_dir = _copy(good, tmp_path)
    document = checkpoint(selection, run_dir, resolver=FixtureDatabase())
    assert document["pass"] is True and document["failed"] == [] and document["reads_truth"] is False
    assert (document["cases_settled"], document["cases_total"], document["run_status"], document["paused"]) == (PAUSE_AT, 70, "paused", True)
    assert document["thresholds"] == DEFAULT_THRESHOLDS == {"degraded_max": 0.15, "cap_hit_max": 0.10, "provider_failures_max": 0.05,
                                                            "citations_all_valid_min": 0.90, "opened_min": 0.90}
    assert document["measures"] == {"degraded_rate": 0.0, "cap_hit_rate": 0.0, "provider_failure_rate": 0.0, "citations_all_valid_share": 1.0,
                                    "opened_share": 1.0, "evidence_after_snapshot_cases": 0, "markers": "clean", "ledger_reconciled": True,
                                    "truth_modules_loaded": []}
    assert [c["name"] for c in document["conditions"]] == ["run_status", "degraded", "cap_hit", "provider_failures", "citations_all_valid", "opened",
                                                           "evidence_after_snapshot", "markers", "reconciled", "truth_modules"]
    assert all(c["ok"] for c in document["conditions"])
    details = document["details"]
    assert details["agent_arm"]["cases_run"] == details["agent_arm"]["concluded"] == PAUSE_AT
    assert details["ledger"]["cases_reconciled"] == PAUSE_AT and details["ledger"]["committed_calls"] == details["ledger"]["campaign_entry_calls"] == 400
    assert details["evidence"]["cases_checked"] == PAUSE_AT and details["markers"]["missing_surfaces"] == []
    assert details["citations"] == {"concluded": PAUSE_AT, "all_valid": PAUSE_AT, "from_the_run_record": 0,
                                    "checked_here_with_the_resolver": PAUSE_AT, "not_checked": 0}
    path = write_checkpoint(document, run_dir / "checkpoint.json")
    assert json.loads(path.read_text(encoding="utf-8"))["pass"] is True
    # No truth vocabulary, stratum or score in what it wrote: the keys of the run-readable selection are all it knows of a case.
    text = path.read_text(encoding="utf-8")
    assert "stratum" not in text and "main_test" not in text and "acceptable" not in text


def _late_record(rows):
    """Give the first case a retrieved record that the fixture database recorded after the case's snapshot."""
    from dataset_v2.contracts import instant
    row = rows[0]
    world = row["case_key"].split(":", 1)[0]
    late = next(i for i, at in sorted(FixtureDatabase().records[world].items()) if instant(at) > instant(row["as_of"]))
    row["retrieved_ids"].append(late)


def _not_opened(run_dir):
    keys = [row["key"] for row in read_jsonl(run_dir / "cases.jsonl")][-5:]
    _rows(run_dir / "cases.jsonl", lambda rows: rows.__delitem__(slice(-5, None)))

    def change(rows):
        for row in rows:
            if row["case_key"] in keys:
                row.update(not_run="case_not_opened_in_run", primary_cause=None, hypotheses=[], retrieved_ids=[], as_of=None)
    _agent(run_dir, change)


def _append(path, obj):
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj) + "\n")


FAILURES = {
    # 7 of 40 agent cases with no valid conclusion: 17.5% > 15%.
    "degraded": lambda run_dir: _agent(run_dir, lambda rows: [r.update(degraded=True, primary_cause=None, hypotheses=[], failure_mode="invalid_model_output")
                                                                for r in rows[:7]]),
    # 5 of 40 at the per-case cap: 12.5% > 10%.
    "cap_hit": lambda run_dir: _agent(run_dir, lambda rows: [r.update(cap_hit=True) for r in rows[:5]]),
    # 40 failed provider calls beside the 400 that succeeded: 9.1% > 5%.
    "provider_failures": lambda run_dir: _manifest(run_dir, lambda m: m["provenance"]["model_calls"].update(failed={"gpt-oss": 40})),
    # The run record's own citation check failed on 5 of 40 concluded cases: 87.5% < 90%.
    "citations_all_valid": lambda run_dir: _agent(run_dir, lambda rows: [r.update(citations_valid=False) for r in rows[:5]]),
    # 5 of the 40 settled cases never opened in the run: 87.5% < 90%.
    "opened": _not_opened,
    "evidence_after_snapshot": lambda run_dir: _agent(run_dir, _late_record),
    "markers": lambda run_dir: _append(next((run_dir / "captured" / "tools").iterdir()), {"text": "tool returned CNRY" + "0A" * 12}),
    "reconciled": lambda run_dir: _append(run_dir / "ledger.jsonl", {"event": "reconcile", "case_key": "E1:X", "phase": "main", "ledger_calls": 10,
                                                                     "provider_calls": 11, "ok": False}),
    "truth_modules": lambda run_dir: _manifest(run_dir, lambda m: m["isolation"].update(truth_modules_loaded=["stage3_eval.scoring"])),
    "run_status": lambda run_dir: _manifest(run_dir, lambda m: m.update(status="stopped: per-case cap violated (E1:X/agent used 13 calls against a cap of 12)")),
}


@pytest.mark.parametrize("condition", sorted(FAILURES))
def test_each_condition_fails_the_checkpoint_by_itself(good, tmp_path, condition):
    selection, run_dir = _copy(good, tmp_path)
    FAILURES[condition](run_dir)
    document = checkpoint(selection, run_dir, resolver=FixtureDatabase())
    assert document["pass"] is False and document["failed"] == [condition]
    assert [c["name"] for c in document["conditions"] if not c["ok"]] == [condition]


def test_an_exhausted_turn_budget_is_degraded_like_any_other_failure(good, tmp_path):
    """Since stage 4 the investigator reports an exhausted turn budget as "turn_budget_exhausted", no longer as
    "invalid_model_output". The checkpoint reads the degraded flag, so the share and the verdict are the same."""
    selection, run_dir = _copy(good, tmp_path)
    kinds = ["turn_budget_exhausted"] * 4 + ["invalid_model_output"] * 3
    _agent(run_dir, lambda rows: [r.update(degraded=True, primary_cause=None, hypotheses=[], failure_mode=kind) for r, kind in zip(rows, kinds)])
    document = checkpoint(selection, run_dir, resolver=FixtureDatabase())
    assert document["pass"] is False and document["failed"] == ["degraded"]
    assert document["details"]["agent_arm"]["degraded"] == 7
    assert document["details"]["agent_arm"]["failure_modes"] == {"invalid_model_output": 3, "turn_budget_exhausted": 4}


def test_other_ways_a_condition_fails_and_nothing_unchecked_passes(good, tmp_path):
    selection, run_dir = good
    # No resolver: the evidence was not checked, and neither were the citations of records that carry no flag of their own.
    blind = checkpoint(selection, run_dir)
    assert blind["failed"] == ["citations_all_valid", "evidence_after_snapshot"] and blind["measures"]["evidence_after_snapshot_cases"] is None
    assert blind["details"]["citations"]["not_checked"] == PAUSE_AT

    def variant(name, change):
        shutil.copytree(run_dir, tmp_path / name)
        change(tmp_path / name)
        return checkpoint(selection, tmp_path / name, resolver=FixtureDatabase())
    # A cited id that was never retrieved (and does not resolve) is an invalid citation, found here with the resolver.
    cited = variant("cited", lambda d: _agent(d, lambda rows: [r["hypotheses"][0]["supporting_evidence_ids"].append("FXT-NOT-RETRIEVED") for r in rows[:5]]))
    assert cited["failed"] == ["citations_all_valid"] and cited["measures"]["citations_all_valid_share"] == 0.875
    # A cited record recorded after the snapshot: an invalid citation (one case of 40, so the share stays above 90%)
    # and, whatever the share, evidence after the snapshot.
    late_cite = variant("late", lambda d: _agent(d, lambda rows: (_late_record(rows), rows[0]["hypotheses"][0]["supporting_evidence_ids"].append(rows[0]["retrieved_ids"][-1]))))
    assert late_cite["failed"] == ["evidence_after_snapshot"] and late_cite["details"]["evidence"]["cases"][0]["cited"] == 1
    assert late_cite["details"]["citations"]["all_valid"] == PAUSE_AT - 1
    # A required surface that was not captured is never "clean".
    no_logs = variant("nologs", lambda d: shutil.rmtree(d / "captured" / "logs"))
    assert no_logs["failed"] == ["markers"] and no_logs["measures"]["markers"] == "incomplete" and scan_markers(tmp_path / "nologs")["missing_surfaces"] == ["logs"]
    # No reconciliation entries at all (a wiring that gave no provider count), a campaign entry that differs, no provider count.
    silent = variant("silent", lambda d: _rows(d / "ledger.jsonl", lambda rows: rows.__setitem__(slice(None), [r for r in rows if r["event"] != "reconcile"])))
    assert silent["failed"] == ["reconciled"] and "no reconciliation" in silent["details"]["ledger"]["problems"][0]
    differs = variant("differs", lambda d: _manifest(d, lambda m: m["campaign_ledger"].update(calls=m["campaign_ledger"]["calls"] + 1)))
    assert differs["failed"] == ["reconciled"]
    uncounted = variant("uncounted", lambda d: _manifest(d, lambda m: m["provenance"].pop("model_calls")))
    assert uncounted["failed"] == ["provider_failures"] and uncounted["measures"]["provider_failure_rate"] is None
    # A manifest with no isolation block proves nothing about the run process.
    unknown = variant("unknown", lambda d: _manifest(d, lambda m: m.pop("isolation")))
    assert unknown["failed"] == ["truth_modules"]
    # Another selection's run, a dry run and a directory with no manifest are not checkpointed.
    other = variant("other", lambda d: _manifest(d, lambda m: m.update(selection_sha256="0" * 64)))
    assert other["failed"] == ["run_status"]
    with pytest.raises(ValueError, match="dry run"):
        variant("dry", lambda d: _manifest(d, lambda m: m.update(dry_run=True)))
    with pytest.raises(ValueError, match="run_manifest.json is missing"):
        checkpoint(selection, tmp_path / "nothing", resolver=FixtureDatabase())


def test_the_thresholds_are_parameters(good, tmp_path):
    selection, run_dir = _copy(good, tmp_path)
    FAILURES["degraded"](run_dir)
    FAILURES["cap_hit"](run_dir)
    assert checkpoint(selection, run_dir, resolver=FixtureDatabase())["failed"] == ["degraded", "cap_hit"]
    loose = checkpoint(selection, run_dir, resolver=FixtureDatabase(), thresholds={"degraded_max": 0.2, "cap_hit_max": 0.125})
    assert loose["pass"] and loose["thresholds"]["degraded_max"] == 0.2 and loose["thresholds"]["opened_min"] == 0.90
    strict = checkpoint(good[0], good[1], resolver=FixtureDatabase(), thresholds={"citations_all_valid_min": 1.0, "opened_min": 1.0, "degraded_max": 0.0})
    assert strict["pass"]
    with pytest.raises(ValueError, match="unknown thresholds"):
        checkpoint(selection, run_dir, thresholds={"degraded": 0.5})


def test_the_command_writes_checkpoint_json_and_exits_0_on_pass_and_3_on_fail(good, tmp_path, capsys, monkeypatch):
    for name in [n for n in os.environ if "TRUTH" in n.upper()] + ["SUHAIL_SIM_STATE_ROOT"]:
        monkeypatch.delenv(name, raising=False)
    selection, run_dir = _copy(good, tmp_path)
    wiring = "stage3_eval.tests.test_checkpoint:checkpoint_wiring"
    assert main(["checkpoint", "--selection", str(selection), "--run", str(run_dir), "--wiring", wiring]) == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
    assert printed["pass"] is written["pass"] is True and printed["cases_settled"] == PAUSE_AT and written["schema"] == "stage3-checkpoint-1"
    assert WIRED["closed"] and WIRED["run_dir"] == str(run_dir) and WIRED["config"].budget == 3600
    FAILURES["cap_hit"](run_dir)
    assert main(["checkpoint", "--selection", str(selection), "--run", str(run_dir), "--wiring", wiring, "--out", str(tmp_path / "second.json")]) == 3
    printed = json.loads(capsys.readouterr().out)
    assert printed["failed"] == ["cap_hit"] and json.loads((tmp_path / "second.json").read_text(encoding="utf-8"))["pass"] is False
    assert json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))["pass"] is True      # --out wrote elsewhere
    # A threshold given on the command line.
    assert main(["checkpoint", "--selection", str(selection), "--run", str(run_dir), "--wiring", wiring, "--max-cap-hit", "0.2",
                 "--out", str(tmp_path / "third.json")]) == 0
    assert json.loads((tmp_path / "third.json").read_text(encoding="utf-8"))["thresholds"]["cap_hit_max"] == 0.2
    capsys.readouterr()
    # Truth within reach: refused before the wiring is built or anything is read, as `run` is.
    WIRED.clear()
    monkeypatch.setenv("SUHAIL_EVAL_TRUTH_ROOT", str(tmp_path))
    with pytest.raises(SystemExit, match="Refusing to checkpoint"):
        main(["checkpoint", "--selection", str(selection), "--run", str(run_dir), "--wiring", wiring, "--out", str(tmp_path / "refused.json")])
    assert not WIRED and not (tmp_path / "refused.json").exists()


def test_a_run_resumes_after_its_checkpoint(good, tmp_path):
    """The sequence: run --max-cases 40, checkpoint, run --resume."""
    selection, run_dir = _copy(good, tmp_path)
    write_checkpoint(checkpoint(selection, run_dir, resolver=FixtureDatabase()), run_dir / "checkpoint.json")
    worlds, config = fixture_worlds(), make_config()
    truth = {w: worlds[w][0] for w in worlds}
    manifest = run(selection, run_dir, arms=build_arms(config, InTimeAgent(truth), notools_turn_factory()[0]), case_source=FixtureCaseSource(),
                   config=config, capture=FixtureCapture(), resume=True)
    assert manifest["status"] == "completed" and manifest["progress"]["cases_settled"] == 70
    assert json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))["cases_settled"] == PAUSE_AT   # the record stays as taken


def test_the_checkpoint_process_loads_no_truth_side_module():
    """Importing the checkpoint (and the command line that runs it) brings in nothing that reads truth."""
    code = ("import sys; import stage3_eval.__main__, stage3_eval.checkpoint; from stage3_eval.runner import truth_modules_loaded; "
            "sys.exit(1 if truth_modules_loaded() else 0)")
    done = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_run_records_own_citation_check_is_lifted_from_the_record():
    def analysis(checks):
        return {"investigation": {"primary_cause": "HUB_DELAY", "hypotheses": [], "degraded": False}, "checks": checks,
                "investigation_log": {"snapshot_as_of": "2026-09-15T10:00:00+00:00", "model_calls_used": 5, "cap_reached": False}}
    lifted = [from_ops_run("E1:S", "S", case={"entity_id": "C"}, runs=[{"recorded_at": "2026-09-15T10:00:00+00:00", "result_json": json.dumps(analysis(c))}]).citations_valid
              for c in ({"citations": {"cited": 2, "valid": 2, "invalid_ids": [], "all_valid": True}},
                        {"citations": {"cited": 2, "valid": 1, "invalid_ids": ["X"], "all_valid": False}}, {}, None)]
    assert lifted == [True, False, None, None]
