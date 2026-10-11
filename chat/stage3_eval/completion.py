"""A post hoc completion: re-running only the cases of a finished run that a PROVIDER FAILURE left without an answer.

Run side: nothing here reads truth, and this module imports nothing from the scorer (tested with the runner's).

What it is for. A run whose model provider ran out of quota part way leaves cases whose agent or no-tools result is
degraded with failure_mode "model_unavailable": the model was never asked, or never answered. Those results say
nothing about the system under test. `rerun_failed` selects exactly those cases, in the pre-registered order, and runs
only them into a NEW run directory:

- the selection is the pre-registered one (same sha256, same sealed configuration), read as `run` reads it;
- the source run directory is only read: its results (which cases failed, in which arm), its cases.jsonl (each
  case's id, snapshot time, symptoms, rule codes and opening evidence, as the source run recorded them) and its
  manifest. Nothing is written to it;
- each case is re-run as of its ORIGINAL snapshot time (cases.jsonl `as_of`): the case source hands that time to the
  arms, and a case that would be investigated at any other time stops the run;
- the campaign ledger is used as by `run`: the worst case of the listed cases and arms only is reserved, every case
  is reconciled with the provider's count, and the entry is settled at what was used;
- the manifest records the source run, the list of re-run case keys, the arms and that this is a post hoc completion.

Only the model arms are re-run (agent, notools, or one of them). The free baselines read nothing but the case's
recorded opening facts and are kept from the source run.

Selecting on failure_mode is selecting on the provider's failure, not on any answer: no result that holds an answer
(right, wrong, invalid or capped) is ever re-run. It is still a deviation from the pre-registered single pass, so
every number that rests on it carries LABEL, and the cell it completes is reported apart (report.py).
"""
import json
from pathlib import Path

from stage3_eval.arms import CaseRef

PROVIDER_FAILURE = "model_unavailable"       # operations.investigator.failure_mode of a provider (transport) failure
LABEL = "completed post hoc after a provider quota failure"
MODEL_ARMS = ("agent", "notools")
KIND = "post_hoc_completion"


def _read_jsonl(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def provider_failed(run_dir, arms=MODEL_ARMS):
    """{case key: [arms whose main result in the run is a provider failure]}. A case's last result line per arm counts
    (a resumed run never rewrites one, but the last is what `run --resume` itself reads)."""
    failed = {}
    for arm in arms:
        last = {}
        for row in _read_jsonl(Path(run_dir) / "results" / "main" / f"{arm}.jsonl"):
            last[row["case_key"]] = row
        for key, row in last.items():
            if row.get("failure_mode") == PROVIDER_FAILURE and row.get("not_run") is None:
                failed.setdefault(key, []).append(arm)
    return failed


def plan(selection, run_dir, *, arms=MODEL_ARMS, world=None):
    """Which cases a completion of `run_dir` would re-run: the selection's cases, in its order, whose result in one of
    `arms` is a provider failure (and, with `world`, of that world only). Reads the run directory; writes nothing.
    selection: the run-readable selection document."""
    arms = tuple(a for a in MODEL_ARMS if a in arms)
    if not arms:
        raise ValueError(f"a completion re-runs model arms only: {', '.join(MODEL_ARMS)}")
    failed = provider_failed(run_dir, arms)
    known = {row["key"] for row in selection["cases"]}
    if set(failed) - known:
        raise ValueError(f"{len(set(failed) - known)} failed case(s) of {run_dir} are not in this selection; it is not the run's selection")
    recorded = {row["key"]: row for row in _read_jsonl(Path(run_dir) / "cases.jsonl")}
    rows = [row for row in selection["cases"] if row["key"] in failed and (world is None or row["world"] == world)]
    missing = [row["key"] for row in rows if not (recorded.get(row["key"]) or {}).get("as_of")]
    if missing:
        raise ValueError(f"{len(missing)} failed case(s) have no recorded snapshot time in {run_dir}/cases.jsonl: {missing[:5]}")
    by_world = {}
    for row in rows:
        by_world[row["world"]] = by_world.get(row["world"], 0) + 1
    return {"keys": [row["key"] for row in rows], "arms": list(arms), "by_world": dict(sorted(by_world.items())),
            "failed_arms": {row["key"]: failed[row["key"]] for row in rows},
            "as_of": {row["key"]: recorded[row["key"]]["as_of"] for row in rows},
            "failed_in_other_worlds": sum(1 for row in selection["cases"] if row["key"] in failed) - len(rows)}


class RecordedCaseSource:
    """The cases as the source run recorded them (cases.jsonl): the case's id, its snapshot time and its opening
    facts. Nothing is opened and no clock moves: a completion re-runs each case as of the time it was first given."""

    def __init__(self, run_dir):
        self.cases = {(row["world"], row["shipment_id"]): row for row in _read_jsonl(Path(run_dir) / "cases.jsonl")}

    def case_ref(self, world, shipment_id):
        row = self.cases.get((world, shipment_id))
        if row is None:
            return None
        return CaseRef(key=row["key"], world=world, shipment_id=shipment_id, case_id=row.get("case_id"), as_of=row.get("as_of"),
                       symptoms=tuple(row.get("symptoms") or ()), rule_codes=tuple(row.get("rule_codes") or ()),
                       opening_evidence_ids=tuple(row.get("opening_evidence_ids") or ()))


def worst_case(plan_, arms):
    """The most a completion can spend: every listed case at the worst case of every arm it re-runs."""
    per_case = sum(arms[name].worst_case() for name in plan_["arms"])
    return {"per_case": per_case, "cases": len(plan_["keys"]), "total": per_case * len(plan_["keys"])}


def rerun_failed(selection_path, source_run, out_dir, *, arms, config, rerun_arms=MODEL_ARMS, world=None, case_source=None,
                 capture=None, dry_run=False, resume=False, provenance=None, campaign=None, campaign_commit=None,
                 provider_calls=None, enforce_isolation=False, max_cases=None):
    """Re-run the provider-failed cases of `source_run` into `out_dir` (a new directory; never the source run's).
    arms: {"agent": ..., "notools": ...} as for `run` (only `rerun_arms` are needed and run). case_source: where a
    case's facts come from; by default the source run's own record of them (RecordedCaseSource). A wiring that
    replays the feed instead gives its own, and each case must then open at its original snapshot time or the run
    stops. Everything else is `run`'s. Returns the manifest (also <out_dir>/run_manifest.json)."""
    from stage3_eval.design import sealed_notools_max_calls
    from stage3_eval.runner import load_selection, refuse_truth_environment, run
    refuse_truth_environment()
    source, out = Path(source_run).resolve(), Path(out_dir).resolve()
    if out == source or source in out.parents:
        raise ValueError("a completion is written to a new run directory, never into the run it completes")
    selection, selection_sha = load_selection(selection_path)
    manifest_path = source / "run_manifest.json"
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if source_manifest.get("selection_sha256") != selection_sha:
        raise ValueError(f"{source} is not a run of this selection (its manifest names another selection, or it has no manifest)")
    if source_manifest.get("completion"):
        raise ValueError(f"{source} is itself a completion; complete the run it names ({source_manifest['completion'].get('source_run')})")
    todo = plan(selection, source, arms=rerun_arms, world=world)
    if not todo["keys"]:
        raise ValueError(f"no case of {source} has a provider-failed result in {', '.join(todo['arms'])}"
                         + (f" in {world}" if world else "") + "; there is nothing to complete")
    for name in todo["arms"]:
        if name not in arms:
            raise ValueError(f"the wiring gives no {name} arm")
    worst = worst_case(todo, arms)
    sealed_notools = sealed_notools_max_calls(selection["sealed_config_hash"], config)
    record = {"kind": KIND, "post_hoc": True, "label": LABEL,
              "reason": f"provider failure (failure_mode {PROVIDER_FAILURE}) in the source run; no result holding an answer is re-run",
              "source_run": str(source), "source_run_name": source.name, "source_status": source_manifest.get("status"),
              "source_selection_sha256": source_manifest.get("selection_sha256"), "source_modified": False,
              "world": world, "worlds": todo["by_world"], "arms_rerun": todo["arms"], "case_keys": todo["keys"],
              "failed_arms_in_source": todo["failed_arms"], "provider_failed_cases_left_out_by_world": todo["failed_in_other_worlds"],
              "snapshot": "each case is investigated as of its original snapshot time (the source run's cases.jsonl as_of)",
              "original_as_of": todo["as_of"], "worst_case_calls": worst,
              "kept_from_source": [a for a in ("agent", "notools", "rulecode", "symptom") if a not in todo["arms"]]}
    if "notools" in todo["arms"]:
        used = arms["notools"].worst_case()
        record["notools_arm"] = {"max_calls": used, "sealed_max_calls": sealed_notools, "is_the_sealed_arm": used == sealed_notools,
                                 **({} if used == sealed_notools else {"note": "the no-tools results of this completion come from the "
                                     "corrected arm; the source run's come from the arm as it was sealed, so the two are not the same arm"})}
    return run(selection_path, out, arms=arms, case_source=case_source or RecordedCaseSource(source), config=config, capture=capture,
               dry_run=dry_run, resume=resume, provenance=provenance, campaign=campaign, campaign_commit=campaign_commit,
               provider_calls=provider_calls, enforce_isolation=enforce_isolation, max_cases=max_cases,
               only_keys=todo["keys"], arm_names=todo["arms"], budget=worst["total"],
               campaign_run=f"stage3 completion {out.name} of {source.name} selection {selection_sha[:12]}",
               expected_as_of=todo["as_of"], manifest_extra={"completion": record})
