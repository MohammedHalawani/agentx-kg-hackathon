"""Command line (from chat/):

  python -m stage3_eval dry-run --fixture --out DIR
      Select over the committed fixture worlds, run every arm in dry-run mode (zero model calls, the backend case
      runner never called) and write the report skeleton.

  python -m stage3_eval select --world E1=TRUTH_DIR [--world E2=TRUTH_DIR] --database E1=DB [--database E2=DB] \
      --freeze-commit FULL_HASH --c-cap N [--r-cap N] --out DIR
      TRUTH_DIR holds truth.jsonl and monitor_replay_rows.jsonl (world.export's <truth-root>/.../<live split>/).

  python -m stage3_eval run --selection DIR/selection.json --out RUN_DIR --wiring MODULE:FUNCTION [--dry-run] [--resume]
      FUNCTION(config, dry_run=...) returns {"arms", "case_source", "capture", "extras_arms", "provenance"} (WIRING.md).
      Run with SUHAIL_EVAL_TRUTH_ROOT unset.

  python -m stage3_eval score --selection DIR/selection.json --run RUN_DIR --world E1=TRUTH_DIR [...] --wiring MODULE:FUNCTION
      FUNCTION(config) returns {"ingestion", "resolver"}. Writes RUN_DIR/scores.jsonl and RUN_DIR/canary.json.

  python -m stage3_eval report --selection DIR/selection.json [--run RUN_DIR]
      Writes report.json and report.md (into RUN_DIR, or beside the selection for a skeleton).

The campaign's model-call ledger (docs/evals/model_call_ledger.json, or --ledger FILE, or SUHAIL_CALL_LEDGER) holds
every real model call made so far against the 4,000 cap. `select` sizes the evaluation from what REMAINS there
(N_main = floor(remaining / (C_cap + R_cap + 2))) and seals that budget; `run` refuses to start if the calls spent
plus the sealed budget would exceed the cap, reserves the budget before the first case and writes what it used at
the end (a run that dies stays counted at its whole budget). The fixture dry run touches no ledger.
"""
import argparse
import importlib
import json
from pathlib import Path
import sys

from stage3_eval.design import EvalConfig

FIXTURE_COMMIT = "f" * 40   # The fixture's stand-in freeze commit; a real selection takes the evaluation freeze commit.


def _campaign(path):
    """The campaign's model-call ledger. Its cap must be the design's (amendment 2): one number, in one place each."""
    from operations.call_ledger import CallLedger
    from stage3_eval.design import CALL_BUDGET
    ledger = CallLedger(path)
    if ledger.cap != CALL_BUDGET:
        raise SystemExit(f"{ledger.path} has cap {ledger.cap}; the design's cap is {CALL_BUDGET}")
    return ledger


def _head_commit():
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent, text=True).strip()
    except Exception:
        return None


def _wiring(spec):
    module, _, func = spec.partition(":")
    return getattr(importlib.import_module(module), func)


def _worlds(pairs):
    from stage3_eval.truth_io import load_replay_rows, load_truth
    out = {}
    for item in pairs or []:
        world, _, path = item.partition("=")
        base = Path(path)
        out[world] = (load_truth(base / "truth.jsonl"), load_replay_rows(base / "monitor_replay_rows.jsonl"))
    return out


def _config(selection_path):
    data = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    return EvalConfig(**data["config"]), data


def _report(selection, run_dir, out_dir):
    from stage3_eval.report import build_report, write_report
    run_dir = Path(run_dir) if run_dir else None
    scores = manifest = canary = None
    if run_dir:
        if (run_dir / "scores.jsonl").exists():
            scores = [json.loads(l) for l in (run_dir / "scores.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        if (run_dir / "run_manifest.json").exists():
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        if (run_dir / "canary.json").exists():
            canary = json.loads((run_dir / "canary.json").read_text(encoding="utf-8"))
    pairs_path = Path(out_dir) / "pairs.json"
    pairs = json.loads(pairs_path.read_text(encoding="utf-8")) if pairs_path.exists() else None
    report = build_report(selection, scores=scores, run_manifest=manifest, canary=canary, pairs=pairs)
    return write_report(run_dir or out_dir, report)


def dry_run_fixture(out):
    from stage3_eval.arms import AgentArm, NoToolsArm, RuleCodeArm, SymptomArm
    from stage3_eval.fixtures.fakes import FixtureCaseSource, refuse, world_dir
    from stage3_eval.runner import run
    from stage3_eval.selection import select
    out = Path(out)
    config = EvalConfig(freeze_commit=FIXTURE_COMMIT, worlds={w: {"dataset_id": f"FIXTURE-{w}", "export": "fixture", "database": None}
                                                             for w in ("E1", "E2")}, notes="committed harness fixture; not a world-1 export")
    worlds = _worlds([f"{w}={world_dir(w) / 'truth'}" for w in ("E1", "E2")])
    summary = select(worlds, config, out)
    arms = {"agent": AgentArm(refuse, config.c_cap, config.r_cap), "notools": NoToolsArm(turn=refuse), "rulecode": RuleCodeArm(), "symptom": SymptomArm()}
    extras = {"cross_shipment_ablation": AgentArm(refuse, config.c_cap, config.r_cap, name="cross_shipment_ablation"),
              "stability_rerun": AgentArm(refuse, config.c_cap, config.r_cap, name="stability_rerun")}
    manifest = run(out / "selection.json", out / "run", arms=arms, case_source=FixtureCaseSource(), config=config, extras_arms=extras,
                   dry_run=True, provenance={"note": "dry run over the committed fixture"})
    selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    report_path = _report(selection, out / "run", out)
    return summary, manifest, report_path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m stage3_eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dry-run")
    d.add_argument("--fixture", action="store_true", required=True)
    d.add_argument("--out", required=True)
    s = sub.add_parser("select")
    s.add_argument("--world", action="append", required=True)
    s.add_argument("--freeze-commit", required=True)
    s.add_argument("--c-cap", type=int, required=True)
    s.add_argument("--r-cap", type=int, default=0)
    s.add_argument("--sampling", default="round_robin_by_mechanism")
    s.add_argument("--database", action="append", help="WORLD=database name the run wiring opens (sealed into the config)")
    s.add_argument("--out", required=True)
    s.add_argument("--ledger", help="campaign model-call ledger (default docs/evals/model_call_ledger.json)")
    r = sub.add_parser("run")
    r.add_argument("--selection", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--wiring", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--ledger", help="campaign model-call ledger (default docs/evals/model_call_ledger.json)")
    sc = sub.add_parser("score")
    sc.add_argument("--selection", required=True)
    sc.add_argument("--run", required=True)
    sc.add_argument("--world", action="append", required=True)
    sc.add_argument("--wiring", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--selection", required=True)
    rp.add_argument("--run")
    args = ap.parse_args(argv)

    if args.cmd == "dry-run":
        summary, manifest, report_path = dry_run_fixture(args.out)
        print(json.dumps({"selection": summary["hashes"], "by_cell": summary["by_cell"], "shortfalls": summary["shortfalls"],
                          "ledger": manifest["ledger"], "counts": manifest["counts"], "extras": manifest["extras"], "report": str(report_path)},
                         indent=1, default=str))
    elif args.cmd == "select":
        from stage3_eval.selection import select
        campaign = _campaign(args.ledger).summary()
        if campaign["remaining"] < 1:
            raise SystemExit(f"no model calls remain in the campaign ledger ({campaign['spent']} of {campaign['cap']} spent or reserved)")
        # The evaluation's budget is what the campaign has left (pilot and development calls already count), not 4,000.
        config = EvalConfig(freeze_commit=args.freeze_commit, c_cap=args.c_cap, r_cap=args.r_cap, sampling=args.sampling,
                            budget=campaign["remaining"],
                            worlds={item.partition("=")[0]: {"database": dict(d.partition("=")[::2] for d in args.database or []).get(item.partition("=")[0])}
                                    for item in args.world})
        summary = select(_worlds(args.world), config, args.out)
        print(json.dumps({"campaign_ledger": campaign, "budget": config.budget, **{k: v for k, v in summary.items() if k != "census"}},
                         indent=1, default=str))
    elif args.cmd == "run":
        from stage3_eval.runner import run
        from operations.call_ledger import LedgerError, LedgerRefused
        config, _ = _config(args.selection)
        campaign = _campaign(args.ledger)
        try:
            campaign.check(0 if args.resume else config.budget)   # before any database is opened; a resume re-holds its own entry
        except (LedgerRefused, LedgerError) as refusal:
            raise SystemExit(f"Refusing to run: {refusal}") from None
        wired = _wiring(args.wiring)(config, dry_run=args.dry_run)
        try:
            manifest = run(args.selection, args.out, arms=wired["arms"], case_source=wired["case_source"], config=config,
                           capture=wired.get("capture"), extras_arms=wired.get("extras_arms"), dry_run=args.dry_run, resume=args.resume,
                           provenance=wired.get("provenance"), campaign=campaign, campaign_commit=_head_commit())
        except (LedgerRefused, LedgerError) as refusal:
            raise SystemExit(f"Refusing to run: {refusal}") from None
        finally:
            if callable(wired.get("close")):
                wired["close"]()
        print(json.dumps({"campaign_ledger": campaign.summary(), **{k: manifest[k] for k in ("status", "counts", "ledger", "extras")}},
                         indent=1, default=str))
    elif args.cmd == "score":
        from stage3_eval.canary import TruthScanner
        from stage3_eval.scoring import score_run
        from stage3_eval.truth_io import truth_vocabulary
        config, selection = _config(args.selection)
        wired = _wiring(args.wiring)(config)
        worlds = {w: truth for w, (truth, _replay) in _worlds(args.world).items()}
        rows = score_run(args.run, selection, worlds, ingestion=wired.get("ingestion"), resolver=wired.get("resolver"))
        scans = {w: TruthScanner(truth_vocabulary(t)).scan_run(args.run) for w, t in worlds.items()}
        verdicts = [s["verdict"] for s in scans.values()]
        canary = {"verdict": "invalid" if "invalid" in verdicts else "incomplete" if "incomplete" in verdicts else "clean", "per_world": scans,
                  "missing_surfaces": sorted({m for s in scans.values() for m in s["missing_surfaces"]})}
        Path(args.run, "canary.json").write_text(json.dumps(canary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"scored_rows": len(rows), "canary": canary["verdict"]}, indent=1))
    elif args.cmd == "report":
        _config(args.selection)
        selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        print(_report(selection, args.run, Path(args.selection).parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
