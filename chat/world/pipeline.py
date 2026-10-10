"""Build, validate and write a world: the export command's work, usable from tests and scripts."""
from dataclasses import replace
from pathlib import Path
import time

from dataset_v2.contracts import canonical, digest
from world.build import build_world, export_bundle
from world.config import WorldConfig
from world.validate import monitor_replay, run_all, tell_test


def world_digests(build, exports):
    out = {"world_nodes_edges_gold": build.world.hashes(), "truth": digest([build.truth[k] for k in sorted(build.truth)])}
    for split, (imported, items, truth, live_start) in sorted(exports.items()):
        out[f"{split}_v2_manifest"] = digest(imported.manifest())
        out[f"{split}_feed"] = digest(items)
        out[f"{split}_truth"] = digest([truth[k] for k in sorted(truth)])
    out["private_mechanisms"] = digest(sorted((m.mid, m.type, m.subtype, canonical(str(m.params))) for m in build.plan.items.values()))
    return out


def build_and_validate(config: WorldConfig, *, with_heldout=False, determinism=False, replay_splits=None, tell_seed=None):
    """tell_seed: the seed of the second world the pre-run tell test evaluates on (default seed + 1)."""
    timings = {}
    started = time.perf_counter()
    build = build_world(config)
    timings["build"] = round(time.perf_counter() - started, 1)
    splits = ("development", "held_out") if with_heldout else ("development",)
    build.exports = {split: export_bundle(build, split) for split in splits}
    timings["export"] = round(time.perf_counter() - started, 1)
    report = run_all(build, build.exports)
    timings["validation"] = round(time.perf_counter() - started, 1)
    replays = {split: monitor_replay(build, imported, items, truth, live_start) for split, (imported, items, truth, live_start) in build.exports.items()
               if replay_splits is None or split in replay_splits}
    report["monitor_replay_pass"] = all(r["pass"] for r in replays.values())
    report["pass"] = report["pass"] and report["monitor_replay_pass"]
    timings["monitor_replay"] = round(time.perf_counter() - started, 1)
    other = build_world(replace(config, seed=config.seed + 1 if tell_seed is None else tell_seed))
    report["tell_test"] = tell_test(build, other)
    # Addendum B3 is gating: a lookup classifier that beats the rule-code baseline means the generator leaks.
    report["tell_test"]["gates_export"] = True
    report["pass"] = report["pass"] and report["tell_test"]["pass"]
    build.tell_world = other
    timings["tell_test"] = round(time.perf_counter() - started, 1)
    report["digests"] = world_digests(build, build.exports)
    if determinism:
        again = build_world(config)
        again.exports = {split: export_bundle(again, split) for split in splits}
        second = world_digests(again, again.exports)
        report["determinism"] = {"pass": second == report["digests"], "first": report["digests"], "second": second}
        report["pass"] = report["pass"] and report["determinism"]["pass"]
        timings["determinism"] = round(time.perf_counter() - started, 1)
    report["timings_seconds"] = timings
    return build, report, replays


def run_export(config: WorldConfig, output: Path, *, with_heldout=False, eval_dir=None, determinism=False, truth_root=None,
               state_root=None, tell_seed=None):
    from world.export import (_write_json, export_name, replay_summary, report_summary, state_directory, truth_directory, write_bundle,
                              write_state, write_truth)
    output = Path(output)
    name = export_name(output)
    targets = [output] + ([output.with_name(output.name + "-heldout")] if with_heldout else [])
    for target in targets:
        if target.exists():
            raise ValueError(f"Choose a new export directory; {target} exists and exports are immutable")
    for target, what in ((truth_directory(truth_root, config.dataset_id, name), "truth"), (state_directory(state_root, config.dataset_id, name), "state")):
        if target.exists():
            raise ValueError(f"Choose a new {what} root or remove {target}; {what} directories are immutable")
    build, report, replays = build_and_validate(config, with_heldout=with_heldout, determinism=determinism, tell_seed=tell_seed)
    written = {}
    if report["pass"]:
        written["truth"] = write_truth(build, truth_root, replays, build.history_reports, name=name, report=report)
        written["state"] = write_state(build, state_root, name=name)
        written["development"] = write_bundle(build, "development", output, report)
        if with_heldout:
            written["held_out"] = write_bundle(build, "held_out", targets[1], report)
    if eval_dir:
        eval_dir = Path(eval_dir)
        eval_dir.mkdir(parents=True, exist_ok=True)
        _write_json(eval_dir / "validation.json", {**report_summary(report, "development"),
                                                   "held_out_export": ({k: v for k, v in report["exports"]["held_out"].items() if k != "foundation_raw"}
                                                                       if with_heldout else None)})
        _write_json(eval_dir / "monitor_replay.json", replay_summary(replays["development"]))
        if with_heldout:
            _write_json(eval_dir / "monitor_replay_heldout.json", replay_summary(replays["held_out"]))
    failed = sorted(k for k, v in report.items() if isinstance(v, dict) and v.get("pass") is False) + sorted(
        f"{split}.{k}" for split, e in report["exports"].items() for k, v in e.items()
        if isinstance(v, dict) and v.get("pass") is False and k != "foundation_raw")   # foundation_raw: the documented exceptions.
    return {"pass": report["pass"], "failed_sections": failed, "output": str(output.resolve()), "written": written,
            "timings": report["timings_seconds"], "digests": report["digests"], "determinism": report.get("determinism", {}).get("pass")}
