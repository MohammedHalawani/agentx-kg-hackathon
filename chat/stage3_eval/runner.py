"""The run step: every arm over the pre-registered cases, under the budget guard, with nothing truth-side in reach.

It reads only selection.json (checked against its pre-registered sha256 and the sealed configuration hash), asks the
backend's CaseSource for each case's runtime facts, and runs the arms in a fixed order per case: agent first, then
B_notools at the agent's own snapshot (so both arms answer at the same t), then the two free baselines. Each model arm
reserves its worst case in the ledger before it runs and settles with the calls its record reports. Results, the
case facts and everything the runtime produced (captured for the canary scan) are written as the run goes, one
fsynced line at a time.

After the main test, and only with calls left, the exploratory extras run in their fixed order (cross-shipment
ablation, then stability reruns), each case only if its worst case still fits; whatever completes is reported,
never pooled.

The run step refuses to start while SUHAIL_EVAL_TRUTH_ROOT is set in its environment, and imports nothing from the
scorer side (truth_io, strata, selection, scoring; tested). A dry run reserves nothing, calls no model and no
backend case runner, and still writes the ledger plan, the case list and the free baselines.
"""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from stage3_eval.arms import CaseRef
from stage3_eval.budget import BudgetExceeded, BudgetLedger, CapViolation
from stage3_eval.design import EXTRAS_ORDER, EvalConfig, sealed_hash
from stage3_eval.records import ArmResult

TRUTH_ENV = "SUHAIL_EVAL_TRUTH_ROOT"
MAIN_ARM_ORDER = ("agent", "notools", "rulecode", "symptom")


def load_selection(path):
    """selection.json, refused unless it matches the sha256 written beside it at pre-registration."""
    path = Path(path)
    data = path.read_bytes()
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.exists():
        raise ValueError(f"{sidecar} is missing; a selection without its pre-registered hash is not run")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError("selection.json does not match its pre-registered sha256")
    return json.loads(data), actual


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
        for item in items or []:
            self.append(f"captured/{_safe(surface)}/{_safe(label)}.jsonl", item if isinstance(item, (dict, list)) else {"text": str(item)})


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
        resume=False, provenance=None):
    """Run every arm over the selection. arms: {"agent": AgentArm, "notools": NoToolsArm, "rulecode": ..., "symptom": ...};
    extras_arms: {"cross_shipment_ablation": AgentArm (cross-shipment tools disabled), "stability_rerun": AgentArm}.
    Returns the run manifest (also written to <out_dir>/run_manifest.json)."""
    if os.environ.get(TRUTH_ENV):
        raise RuntimeError(f"{TRUTH_ENV} is set: the run step must not be able to find truth labels; unset it for the run")
    selection, selection_sha = load_selection(selection_path)
    if selection["sealed_config_hash"] != sealed_hash(config):
        raise ValueError("the configuration differs from the one the selection was sealed with (amendment 1, H)")
    missing = [a for a in MAIN_ARM_ORDER if a not in arms]
    if missing:
        raise ValueError(f"every arm runs on the same cases; missing: {missing}")
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()) and not resume:
        raise FileExistsError(f"{out} is not empty; every attempt gets its own directory (and is disclosed)")
    writer = RunWriter(out)
    started = datetime.now(timezone.utc).isoformat()
    ledger = BudgetLedger(out / "ledger.jsonl", config.budget, dry_run=dry_run, resume=resume,
                          meta={"selection_sha256": selection_sha, "sealed_config_hash": selection["sealed_config_hash"]})
    done = _previous_results(out, "main") if resume else {}
    written_cases = set()
    if resume and (out / "cases.jsonl").exists():
        written_cases = {json.loads(line)["key"] for line in (out / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    status, counts = "completed", {"cases": 0, "not_opened": 0, "budget_refused": 0, "arm_errors": 0}
    refs, agent_t = {}, {}
    try:
        for row in selection["cases"]:
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
            if ref is not None and capture is not None and not dry_run:
                for surface, items in (capture.capture_case(ref, results) or {}).items():
                    writer.capture(surface, key, items)
        extras = _run_extras(selection, refs, agent_t, extras_arms or {}, ledger, writer, dry_run, counts)
        if capture is not None and not dry_run:
            for surface, items in (capture.capture_run() or {}).items():
                writer.capture(surface, "run", items)
    except CapViolation as exc:
        status, extras = f"stopped: per-case cap violated ({exc})", {}
    ledger.close(status)
    manifest = {"schema": "stage3-run-1", "status": status, "dry_run": dry_run, "started_at": started,
                "finished_at": datetime.now(timezone.utc).isoformat(), "selection_sha256": selection_sha,
                "sealed_config_hash": selection["sealed_config_hash"], "config": config.as_dict(),
                "arms": {k: {"worst_case": v.worst_case(), "uses_model": v.uses_model} for k, v in arms.items()},
                "counts": counts, "extras": extras, "ledger": ledger.summary(), "provenance": provenance or {}}
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return manifest


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
    except Exception as exc:   # one bad case never loses the run; it counts as degraded (wrong)
        counts["arm_errors"] += 1
        result = ArmResult(case_key=case.key, arm=arm.name, shipment_id=case.shipment_id, case_id=case.case_id, as_of=case.as_of,
                           degraded=True, failure_mode=f"arm_error:{type(exc).__name__}", calls_used=None if arm.uses_model else 0)
    if arm.uses_model:
        ledger.settle(rid, result.calls_used, tokens=result.tokens)   # may raise CapViolation (recorded first)
    return result


def _run_extras(selection, refs, agent_t, extras_arms, ledger, writer, dry_run, counts):
    """The exploratory extras, in their fixed order, while each case's worst case still fits. Each extra case is
    investigated AS OF the main agent run's own snapshot (the clock has moved on by then), so the comparison with the
    main run is at the same t; its arm must investigate as of CaseRef.as_of (WIRING.md)."""
    report = {}
    plan_left = ledger.remaining
    for name in EXTRAS_ORDER:
        keys = selection["extras"].get(name, [])
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
            entry["completed"] += result.not_run is None
        report[name] = entry
    return report
