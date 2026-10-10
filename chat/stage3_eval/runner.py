"""The run step: every arm over the pre-registered cases, under the budget guard, with nothing truth-side in reach.

It reads only selection.json (checked against its pre-registered sha256 and the sealed configuration hash, and
refused if it carries anything but each case's key, world, shipment and expected opening), asks the
backend's CaseSource for each case's runtime facts, and runs the arms in a fixed order per case: agent first, then
B_notools at the agent's own snapshot (so both arms answer at the same t), then the two free baselines. Each model arm
reserves its worst case in the ledger before it runs and settles with the calls its record reports. Results, the
case facts and everything the runtime produced (captured for the canary scan) are written as the run goes, one
fsynced line at a time.

After the main test, and only with calls left and extras.json named, the exploratory extras run in their fixed order (cross-shipment
ablation, then stability reruns), each case only if its worst case still fits; whatever completes is reported,
never pooled.

The run step refuses to start while any variable that points at truth or at the simulator's private state is set
(any set variable whose name contains TRUTH, plus SUHAIL_SIM_STATE_ROOT: the pilot's guard; the command line checks
it before the wiring opens a database), and imports nothing from the scorer side (truth_io, strata, selection,
scoring; tested). When the run ends its manifest records whether such a variable is set and whether a truth-side
module is loaded in the process; from the command line either makes the run invalid. After each case its captured
surfaces and its arms' outputs are screened for canary-shaped and mechanism-id-shaped tokens, and a hit stops the run. A dry run reserves nothing, calls no model and no
backend case runner, and still writes the ledger plan, the case list and the free baselines.

A run can be taken in parts (max_cases, `--max-cases N` on the command line): it stops before starting case N + 1 of
the pre-registered order, counting every case settled in this run directory, whatever any case answered. Such a run
is "paused": no reservation is open, the campaign ledger holds the calls committed so far, no extra has run, and
`--resume` (with a larger N, or none) carries on from case N + 1. Each settled case is one line of settled.jsonl, so
a resumed run neither captures nor reconciles it a second time.
"""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from stage3_eval.arms import CaseRef
from stage3_eval.budget import BudgetExceeded, BudgetLedger, CapViolation, RunStopped
from stage3_eval.canary import marker_hits
from stage3_eval.design import EXTRAS_ORDER, EvalConfig, canonical_bytes, runtime_selection_problem, sealed_hash
from stage3_eval.records import ArmResult

TRUTH_ENV = "SUHAIL_EVAL_TRUTH_ROOT"
TRUTH_ENVIRONMENT = (TRUTH_ENV, "SUHAIL_SIM_STATE_ROOT")
# Modules that read or hold truth: the world's label module and this package's scorer side.
TRUTH_MODULES = ("world.truth", "stage3_eval.truth_io", "stage3_eval.strata", "stage3_eval.selection", "stage3_eval.scoring")
MAIN_ARM_ORDER = ("agent", "notools", "rulecode", "symptom")


def truth_environment():
    """Names of set environment variables that point at truth labels or the simulator's private state (the pilot's
    rule: the two known names, and any name containing TRUTH)."""
    return sorted(name for name, value in os.environ.items() if value and (name in TRUTH_ENVIRONMENT or "TRUTH" in name.upper()))


def refuse_truth_environment():
    names = truth_environment()
    if names:
        raise RuntimeError(f"{', '.join(names)} set: the run step must not be able to find truth labels or the simulator's private "
                           "state; unset for the run")


def truth_modules_loaded():
    return sorted(name for name in sys.modules if any(name == m or name.startswith(m + ".") for m in TRUTH_MODULES))


def load_selection(path):
    """selection.json, refused unless it matches the sha256 written beside it at pre-registration and carries only
    what the run step may read: a file with a stratum, a main-test flag, an extras list or any other truth-derived
    field is refused, whatever its hash says."""
    path = Path(path)
    data = path.read_bytes()
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.exists():
        raise ValueError(f"{sidecar} is missing; a selection without its pre-registered hash is not run")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(canonical_bytes(data)).hexdigest()   # line endings normalised: the same on every checkout
    if actual != expected:
        raise ValueError("selection.json does not match its pre-registered sha256")
    document = json.loads(data)
    problem = runtime_selection_problem(document)
    if problem:
        raise ValueError(f"{path.name} is not a run-readable selection ({problem}); the run step reads only key, world, shipment and "
                         "expected opening per case")
    return document, actual


def load_extras(path, selection_sha):
    """The extras lists (scorer-side file extras.json), read only once the main test has finished: {name: [case keys]}.
    Refused unless it matches its own pre-registered sha256 and was written for this selection."""
    path = Path(path)
    data = path.read_bytes()
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.exists() or hashlib.sha256(canonical_bytes(data)).hexdigest() != sidecar.read_text(encoding="utf-8").split()[0]:
        raise ValueError(f"{path.name} does not match its pre-registered sha256")
    document = json.loads(data)
    if document.get("selection_sha256") != selection_sha:
        raise ValueError(f"{path.name} was not written for this selection")
    return {name: list(document.get("extras", {}).get(name, [])) for name in EXTRAS_ORDER}


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


class RunWriter:
    def __init__(self, out_dir):
        self.out = Path(out_dir)
        (self.out / "results").mkdir(parents=True, exist_ok=True)
        (self.out / "captured").mkdir(parents=True, exist_ok=True)

    def append(self, relative, obj):
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def result(self, result: ArmResult, phase="main"):
        self.append(f"results/{phase}/{result.arm}.jsonl", result.to_dict())
        self.append(f"captured/arm_outputs/{phase}_{result.arm}.jsonl", result.to_dict())

    def capture(self, surface, label, items):
        """Write the items of one surface and return how many canary-shaped or mechanism-id-shaped tokens they hold."""
        hits = 0
        for item in items or []:
            self.append(f"captured/{_safe(surface)}/{_safe(label)}.jsonl", item if isinstance(item, (dict, list)) else {"text": str(item)})
            hits += marker_hits(item)
        return hits


def _not_run(case_ref, key, world, sid, arm, reason):
    return ArmResult(case_key=key, arm=arm, shipment_id=sid, case_id=case_ref.case_id if case_ref else None,
                     as_of=case_ref.as_of if case_ref else None, not_run=reason)


def _previous_results(out_dir, phase):
    found = {}
    root = Path(out_dir) / "results" / phase
    for f in root.glob("*.jsonl") if root.exists() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = ArmResult.from_dict(json.loads(line))
                found[(r.case_key, r.arm)] = r
    return found


def run(selection_path, out_dir, *, arms, case_source, config: EvalConfig, capture=None, extras_arms=None, dry_run=False,
        resume=False, provenance=None, campaign=None, campaign_commit=None, provider_calls=None, extras_path=None,
        enforce_isolation=False, max_cases=None):
    """Run every arm over the selection. arms: {"agent": AgentArm, "notools": NoToolsArm, "rulecode": ..., "symptom": ...};
    extras_arms: {"cross_shipment_ablation": AgentArm (cross-shipment tools disabled), "stability_rerun": AgentArm}.
    provenance: a dict, or a callable returning one, called when the run has finished (so it can report the model calls
    the provider counted and whether the code tree changed during the run).
    campaign: the campaign's persistent model-call ledger (operations.call_ledger.CallLedger). The run's own maximum
    is config.budget: the run refuses to start if the calls already spent in the campaign plus that maximum would
    exceed the campaign cap, reserves the maximum before the first case and writes the calls it actually committed
    at the end. A run that dies leaves its reservation counted at the maximum. A dry run checks and writes nothing.
    extras_path: extras.json of the pre-registration. The lists in it are derived from truth (which cases are in the
    main test, which have a cross-shipment mechanism), so the file is opened only after the last main-test case has
    run; without it no extra runs.
    provider_calls: a callable returning the model calls the provider's own callbacks have counted in this process
    (completed and failed). After every case, and after every extra, that count and the ledger's are written to the
    ledger, and the run stops if the provider counted more than the ledger holds.
    enforce_isolation: the command line sets it. The manifest always records the truth variables set and the truth-side
    modules loaded when the run ends; with this flag a loaded truth-side module makes the run invalid (a test process
    has them loaded for its own scoring, so the flag is off by default). A truth variable set at the end always does.
    max_cases: stop before starting case max_cases + 1 of the selection's order (cases settled by earlier attempts in
    this directory count). The stop reads nothing but that number and the position in the order. The run then ends
    with status "paused": no extra runs, the run-level surfaces are captured as of the pause, and the campaign entry
    is settled at the calls committed so far (a resume reserves the run's maximum again).
    Returns the run manifest (also written to <out_dir>/run_manifest.json)."""
    refuse_truth_environment()
    selection, selection_sha = load_selection(selection_path)
    if selection["sealed_config_hash"] != sealed_hash(config):
        raise ValueError("the configuration differs from the one the selection was sealed with (amendment 1, H)")
    if max_cases is not None and (isinstance(max_cases, bool) or not isinstance(max_cases, int) or max_cases < 1):
        raise ValueError("max_cases must be a whole number of cases, one or more")
    missing = [a for a in MAIN_ARM_ORDER if a not in arms]
    if missing:
        raise ValueError(f"every arm runs on the same cases; missing: {missing}")
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()) and not resume:
        raise FileExistsError(f"{out} is not empty; every attempt gets its own directory (and is disclosed)")
    # What the earlier attempts in this directory left: their manifest (kept as an earlier segment of this run) and
    # the cases they settled. Read before anything is written.
    earlier_manifest = None
    if resume and (out / "run_manifest.json").exists():
        earlier_manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    settled_before = []
    if resume and (out / "settled.jsonl").exists():
        settled_before = [json.loads(line) for line in (out / "settled.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    settled_keys = {row["key"] for row in settled_before}
    campaign_run = f"stage3 run {out.name} selection {selection_sha[:12]}"
    if campaign is not None:
        if dry_run:
            campaign.check(config.budget)        # LedgerRefused if it would not fit; nothing is written
        else:
            campaign.reserve(campaign_run, config.budget, commit=campaign_commit, resume=resume,
                             note=f"stage3_eval run in {out.name}; own cap {config.budget} (sealed in the selection)")
    writer = RunWriter(out)
    started = datetime.now(timezone.utc).isoformat()
    ledger = BudgetLedger(out / "ledger.jsonl", config.budget, dry_run=dry_run, resume=resume,
                          meta={"selection_sha256": selection_sha, "sealed_config_hash": selection["sealed_config_hash"]})
    done = _previous_results(out, "main") if resume else {}
    written_cases = set()
    if resume and (out / "cases.jsonl").exists():
        written_cases = {json.loads(line)["key"] for line in (out / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    status, counts = "completed", {"cases": 0, "not_opened": 0, "budget_refused": 0, "arm_errors": 0}
    screened = {"cases_screened_for_truth_markers": sum(1 for row in settled_before if row.get("screened")), "run_level_marker_hits": 0}
    refs, agent_t = {}, {}
    total, settled_count, paused = len(selection["cases"]), 0, False
    # The provider's count starts at this process; so does the ledger's side of the comparison (a resumed ledger already
    # holds the earlier attempt's calls, crash recoveries included).
    reconcile = None
    if provider_calls is not None and not dry_run:
        base_ledger, base_provider = ledger.committed, int(provider_calls())
        reconcile = lambda key, phase="main": ledger.reconcile(key, int(provider_calls()) - base_provider, ledger.committed - base_ledger, phase=phase)
    try:
        for index, row in enumerate(selection["cases"]):
            if max_cases is not None and index >= max_cases:
                # The only stopping rule: the count given by the caller. Before the next case is asked for, so the
                # backend's clock has not moved towards it and nothing is reserved for it.
                paused = True
                break
            key, world, sid = row["key"], row["world"], row["shipment_id"]
            counts["cases"] += 1
            ref = case_source.case_ref(world, sid)
            if ref is not None:
                ref = replace(ref, key=key, world=world, shipment_id=sid)
                refs[key] = ref
                if key not in written_cases:
                    writer.append("cases.jsonl", {"key": key, "world": world, "shipment_id": sid, "case_id": ref.case_id, "as_of": ref.as_of,
                                                  "symptoms": list(ref.symptoms), "rule_codes": list(ref.rule_codes),
                                                  "opening_evidence_ids": list(ref.opening_evidence_ids)})
            else:
                counts["not_opened"] += 1
            results = {}
            for name in MAIN_ARM_ORDER:
                if (key, name) in done:
                    results[name] = done[(key, name)]
                    # What an earlier attempt counted for this case stays counted.
                    counts["budget_refused"] += done[(key, name)].not_run == "budget_refused"
                    counts["arm_errors"] += str(done[(key, name)].failure_mode or "").startswith("arm_error:")
                    continue
                arm = arms[name]
                if (key, name) in ledger.done:
                    # Settled (or recovered at its worst case) before a crash, but its result line was lost: never rerun
                    # (that would spend twice); it counts as degraded, i.e. wrong.
                    result = _not_run(ref, key, world, sid, name, None)
                    result.degraded, result.failure_mode = True, "result_lost_in_crash"
                elif ref is None:
                    result = _not_run(None, key, world, sid, name, "case_not_opened_in_run")
                else:
                    case_for_arm = ref
                    if name != "agent" and results.get("agent") and results["agent"].as_of:
                        case_for_arm = replace(ref, as_of=results["agent"].as_of)   # same snapshot as the agent
                    result = _run_arm(arm, case_for_arm, ledger, dry_run, counts)
                results[name] = result
                writer.result(result)
            if results.get("agent") is not None and results["agent"].as_of:
                agent_t[key] = results["agent"].as_of
            was_screened = ref is not None and not dry_run
            if was_screened and key not in settled_keys:
                # Screened as the run goes (shapes only; the scorer's scan with the vocabulary is the verdict): a canary
                # or a mechanism id in anything this case was shown or produced stops the run here, after it is written.
                found = {"arm_outputs": sum(marker_hits(r.to_dict()) for r in results.values())}
                for surface, items in ((capture.capture_case(ref, results) or {}) if capture is not None else {}).items():
                    found[surface] = found.get(surface, 0) + writer.capture(surface, key, items)
                screened["cases_screened_for_truth_markers"] += 1
                found = {surface: n for surface, n in sorted(found.items()) if n}
                if found:
                    raise RunStopped(f"truth marker in the captured surfaces of {key} (hits by surface: {found})")
            if key not in settled_keys:
                if reconcile is not None:
                    reconcile(key)
                writer.append("settled.jsonl", {"order": index, "key": key, "screened": was_screened})
                settled_keys.add(key)
            settled_count += 1
        if paused:
            # No extras: their lists are opened only after the last main-test case, and that case has not run.
            status, extras = "paused", {}
        else:
            # Only now: every main-test arm has answered, so nothing in the extras lists can reach the main test.
            extras_plan = load_extras(extras_path, selection_sha) if extras_path else {}
            extras = _run_extras(extras_plan, refs, agent_t, extras_arms or {}, ledger, writer, dry_run, counts, reconcile)
        if capture is not None and not dry_run:
            # A pause captures the run-level surfaces too (this process's log lines exist nowhere else), under its own
            # label, so an interim scan covers everything served so far.
            label = f"paused_after_{settled_count:04d}" if paused else "run"
            for surface, items in (capture.capture_run() or {}).items():
                screened["run_level_marker_hits"] += writer.capture(surface, label, items)
            if screened["run_level_marker_hits"]:
                status = f"invalid: {screened['run_level_marker_hits']} truth markers in the run-level captured surfaces"
    except CapViolation as exc:
        status, extras = f"stopped: per-case cap violated ({exc})", {}
    except RunStopped as exc:
        status, extras = f"stopped: {exc}", {}
    isolation = {"truth_environment_set": truth_environment(), "truth_modules_loaded": truth_modules_loaded(),
                 "enforced": bool(enforce_isolation), **screened}
    if isolation["truth_environment_set"] or (enforce_isolation and isolation["truth_modules_loaded"]):
        status = (f"invalid: truth was within reach of the run process (variables {isolation['truth_environment_set']}, "
                  f"modules {isolation['truth_modules_loaded']}); was: {status}")
    ledger.close(status)
    manifest = {"schema": "stage3-run-1", "status": status, "dry_run": dry_run, "started_at": started,
                "finished_at": datetime.now(timezone.utc).isoformat(), "selection_sha256": selection_sha,
                "sealed_config_hash": selection["sealed_config_hash"], "config": config.as_dict(),
                "arms": {k: {"worst_case": v.worst_case(), "uses_model": v.uses_model} for k, v in arms.items()},
                "counts": counts, "extras": extras, "ledger": ledger.summary(), "isolation": isolation,
                "progress": {"paused": paused, "cases_settled": settled_count, "cases_total": total, "max_cases": max_cases,
                             "order": "pre-registered (selection.json)",
                             "stop_rule": "the case count given to the run; no result is read" if max_cases is not None else None},
                "earlier_segments": _earlier_segments(earlier_manifest),
                "provenance": (provenance() if callable(provenance) else provenance) or {}}
    if campaign is not None and not dry_run:
        # Committed, not only settled: a reservation still open here (there is none on a clean finish) counts in full.
        settled = campaign.settle(campaign_run, ledger.committed, tokens=ledger.tokens, note=f"status: {status}")
        manifest["campaign_ledger"] = {"run": campaign_run, "calls": settled["calls"], "reserved": settled.get("reserved")}
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return manifest


def _earlier_segments(manifest):
    """The attempts this run directory already held, oldest first: what each ended as and its own provenance (the
    model calls its process counted), so a run taken in parts is validated over all of them."""
    if not manifest:
        return []
    progress = manifest.get("progress") or {}
    return list(manifest.get("earlier_segments") or []) + [{
        "status": manifest.get("status"), "started_at": manifest.get("started_at"), "finished_at": manifest.get("finished_at"),
        "cases_settled": progress.get("cases_settled"), "max_cases": progress.get("max_cases"),
        "committed_calls": (manifest.get("ledger") or {}).get("committed_calls"), "provenance": manifest.get("provenance") or {}}]


def _whole(value, name):
    """None, or the value as a whole non-negative number; anything else raises."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a whole non-negative number, not {type(value).__name__}")
    return value


def _run_arm(arm, case: CaseRef, ledger, dry_run, counts):
    worst = arm.worst_case()
    if arm.uses_model:
        try:
            rid = ledger.reserve(case.key, arm.name, worst)
        except BudgetExceeded:
            counts["budget_refused"] += 1
            return _not_run(case, case.key, case.world, case.shipment_id, arm.name, "budget_refused")
        if dry_run:
            return _not_run(case, case.key, case.world, case.shipment_id, arm.name, "dry_run")
    try:
        result = arm.run(case)
        if arm.uses_model:
            # Inside the guard: a count the ledger cannot read (the counter object, a string, a negative number) is an
            # arm error like any other, so it can never abort the run with this reservation still open.
            result.calls_used = _whole(result.calls_used, "calls_used")
            result.tokens = _whole(result.tokens, "tokens")
    except RunStopped:         # not an arm error: the reservation stays open, counted at its worst case
        raise
    except Exception as exc:   # one bad case never loses the run; it counts as degraded (wrong)
        counts["arm_errors"] += 1
        result = ArmResult(case_key=case.key, arm=arm.name, shipment_id=case.shipment_id, case_id=case.case_id, as_of=case.as_of,
                           degraded=True, failure_mode=f"arm_error:{type(exc).__name__}", calls_used=None if arm.uses_model else 0)
    if arm.uses_model:
        ledger.settle(rid, result.calls_used, tokens=result.tokens)   # may raise CapViolation (recorded first)
    return result


def _run_extras(plan, refs, agent_t, extras_arms, ledger, writer, dry_run, counts, reconcile=None):
    """The exploratory extras, in their fixed order, while each case's worst case still fits. Each extra case is
    investigated AS OF the main agent run's own snapshot (the clock has moved on by then), so the comparison with the
    main run is at the same t; its arm must investigate as of CaseRef.as_of (WIRING.md)."""
    report = {}
    plan_left = ledger.remaining
    for name in EXTRAS_ORDER:
        keys = plan.get(name, [])
        arm = extras_arms.get(name)
        entry = {"listed": len(keys), "completed": 0, "stopped_for_budget": False, "available": arm is not None}
        if arm is None or not keys:
            report[name] = entry
            continue
        if dry_run:
            fit = min(len(keys), max(0, plan_left) // max(1, arm.worst_case()))
            plan_left -= fit * arm.worst_case()
            entry["would_fit_by_worst_case"] = fit
            report[name] = entry
            continue
        for key in keys:
            ref = refs.get(key)
            if ref is None or key not in agent_t:
                continue
            ref = replace(ref, as_of=agent_t[key])
            if ledger.remaining < arm.worst_case():
                entry["stopped_for_budget"] = True
                break
            result = _run_arm(arm, ref, ledger, dry_run, counts)
            result.arm = name
            writer.result(result, phase="extras")
            if reconcile is not None:
                reconcile(key, f"extras:{name}")
            entry["completed"] += result.not_run is None
        report[name] = entry
    return report
