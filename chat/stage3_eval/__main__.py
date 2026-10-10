"""Command line (from chat/):

  python -m stage3_eval dry-run --fixture --out DIR
      Select over the committed fixture worlds, run every arm in dry-run mode (zero model calls, the backend case
      runner never called) and write the report skeleton.

  python -m stage3_eval select --world E1=TRUTH_DIR [--world E2=TRUTH_DIR] --database E1=DB [--database E2=DB] \
      --freeze-commit FULL_HASH --c-cap N [--r-cap N] [--reserve N] --out DIR
      TRUTH_DIR holds truth.jsonl and monitor_replay_rows.jsonl (world.export's <truth-root>/.../<live split>/).

  python -m stage3_eval run --selection DIR/selection.json --out RUN_DIR --wiring MODULE:FUNCTION [--extras DIR/extras.json]
      [--dry-run] [--resume] [--max-cases N]
      FUNCTION(config, dry_run=...) returns {"arms", "case_source", "capture", "extras_arms", "provenance"} (WIRING.md).
      Run with SUHAIL_EVAL_TRUTH_ROOT, SUHAIL_SIM_STATE_ROOT and every variable naming TRUTH unset (refused before
      the wiring is built). The run reads selection.json only (key, world, shipment and expected
      opening per case). --extras names the exploratory extras' case lists, which are derived from truth: the file is
      opened only after the last main-test case has run, and without it no extra runs.
      --max-cases N takes the run in parts: it stops before starting case N + 1 of the pre-registered order (cases
      already settled in RUN_DIR count), with manifest status "paused", no extras run and the campaign ledger holding
      the calls committed so far. --resume with a larger N, or none, carries on. N is the only thing the stop reads.
      `score` and `report` work on a paused run; the report is then labelled an interim look over the first N cases.

  python -m stage3_eval score --selection DIR/selection.json --run RUN_DIR --world E1=TRUTH_DIR [...] --wiring MODULE:FUNCTION
      FUNCTION(config) returns {"ingestion", "resolver"}. Writes RUN_DIR/scores.jsonl and RUN_DIR/canary.json.

  python -m stage3_eval report --selection DIR/selection.json [--run RUN_DIR]
      Writes report.json and report.md (into RUN_DIR, or beside the selection for a skeleton).

The campaign's model-call ledger (docs/evals/model_call_ledger.json, or --ledger FILE, or SUHAIL_CALL_LEDGER) holds
every real model call made so far against the 4,000 cap. Stage 3 stops when that ledger reaches 3,600 calls
(design.STAGE3_STOP_AT, addendum to amendment 3). `select` sizes the evaluation from what is left before that line:
it seals budget = min(cap - spent, 3,600 - spent) and N_main = floor(budget / (C_cap + R_cap + 2)); `run` refuses to
start if the calls spent plus the sealed budget would exceed the cap or pass the stop line, reserves the budget before
the first case and writes what it used at the end (a run that dies stays counted at its whole budget). The fixture dry
run touches no ledger.
`select --reserve N` keeps N calls of the campaign out of the evaluation as well: the sealed budget is
min(cap - spent - N, 3,600 - spent), N is sealed in the configuration, and `run` also refuses to start if the calls
spent plus the sealed budget would exceed cap - N.
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
    from stage3_eval.design import CALL_BUDGET, STAGE3_STOP_AT
    if not 0 < STAGE3_STOP_AT <= CALL_BUDGET:
        raise SystemExit(f"the Stage 3 stop line ({STAGE3_STOP_AT}) must lie inside the cap ({CALL_BUDGET})")
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


def _call_wiring(function, config, **context):
    """Call a wiring function with the keyword arguments it declares (dry_run, resume, selection, run_dir): a wiring
    written against the first interface (config, dry_run=...) keeps working."""
    import inspect
    accepted = inspect.signature(function).parameters
    everything = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in accepted.values())
    return function(config, **{k: v for k, v in context.items() if everything or k in accepted})


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


def _scorer_selection(selection_path):
    """Scorer side (score, report): the selection with each case's stratum, the allocation and the extras lists."""
    from stage3_eval.selection import scorer_view
    return scorer_view(selection_path)


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
                   dry_run=True, provenance={"note": "dry run over the committed fixture"}, extras_path=out / "extras.json")
    selection = _scorer_selection(out / "selection.json")
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
    s.add_argument("--reserve", type=int, default=0, metavar="N",
                   help="campaign calls kept out of this evaluation: the sealed budget is at most cap - spent - N, and never "
                        "more than what is left before the Stage 3 stop line (default 0)")
    r = sub.add_parser("run")
    r.add_argument("--selection", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--wiring", required=True)
    r.add_argument("--extras", help="extras.json of the pre-registration (opened only after the main test has finished)")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--max-cases", type=int, metavar="N",
                   help="stop (status paused) before starting case N + 1 of the pre-registered order; continue with --resume")
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
        from stage3_eval.design import STAGE3_STOP_AT, evaluation_budget, worst_case_per_case
        from stage3_eval.selection import select
        campaign = _campaign(args.ledger).summary()
        if args.reserve < 0:
            raise SystemExit("--reserve must be zero or more")
        if campaign["remaining"] - args.reserve < 1:
            raise SystemExit(f"no model calls remain in the campaign ledger ({campaign['spent']} of {campaign['cap']} spent or reserved"
                             + (f", {args.reserve} set aside by --reserve)" if args.reserve else ")"))
        # The evaluation's budget is what the campaign has left before the Stage 3 stop line (pilot and development
        # calls already count), not 4,000: by default, with no --reserve, it already stops at design.STAGE3_STOP_AT.
        budget = evaluation_budget(campaign["spent"], args.reserve, campaign["cap"])
        if budget < 1:
            raise SystemExit(f"the campaign ledger is at the Stage 3 stop line ({campaign['spent']} calls spent or reserved; "
                             f"Stage 3 stops at {STAGE3_STOP_AT})")
        config = EvalConfig(freeze_commit=args.freeze_commit, c_cap=args.c_cap, r_cap=args.r_cap, sampling=args.sampling,
                            budget=budget, reserve=args.reserve,
                            worlds={item.partition("=")[0]: {"database": dict(d.partition("=")[::2] for d in args.database or []).get(item.partition("=")[0])}
                                    for item in args.world})
        summary = select(_worlds(args.world), config, args.out)
        print(json.dumps({"campaign_ledger": campaign, "budget": config.budget, "reserve": config.reserve,
                          "stage3_stop_at": STAGE3_STOP_AT,
                          "worst_case_calls": summary["allocation"]["n_main"] * worst_case_per_case(config.c_cap, config.r_cap),
                          **{k: v for k, v in summary.items() if k != "census"}},
                         indent=1, default=str))
    elif args.cmd == "run":
        from stage3_eval.runner import refuse_into_reserve, refuse_past_stop_line, refuse_truth_environment, run
        try:
            refuse_truth_environment()        # BEFORE the wiring opens a database or anything else is read
        except RuntimeError as refusal:
            raise SystemExit(f"Refusing to run: {refusal}") from None
        if args.max_cases is not None and args.max_cases < 1:
            raise SystemExit("Refusing to run: --max-cases must be 1 or more")
        from operations.call_ledger import LedgerError, LedgerRefused
        config, selection = _config(args.selection)
        campaign = _campaign(args.ledger)
        try:
            campaign.check(0 if args.resume else config.budget)   # before any database is opened; a resume re-holds its own entry
            if not args.resume:
                refuse_past_stop_line(campaign, config)           # Stage 3 stops at design.STAGE3_STOP_AT, reserve or none
                refuse_into_reserve(campaign, config)             # the calls the selection set aside (select --reserve)
        except (LedgerRefused, LedgerError) as refusal:
            raise SystemExit(f"Refusing to run: {refusal}") from None
        wired = _call_wiring(_wiring(args.wiring), config, dry_run=args.dry_run, resume=args.resume, selection=selection)
        try:
            manifest = run(args.selection, args.out, arms=wired["arms"], case_source=wired["case_source"], config=config,
                           capture=wired.get("capture"), extras_arms=wired.get("extras_arms"), dry_run=args.dry_run, resume=args.resume,
                           provenance=wired.get("provenance"), campaign=campaign, campaign_commit=_head_commit(),
                           provider_calls=wired.get("provider_calls"), extras_path=args.extras, enforce_isolation=True,
                           max_cases=args.max_cases)
        except (LedgerRefused, LedgerError) as refusal:
            raise SystemExit(f"Refusing to run: {refusal}") from None
        finally:
            if callable(wired.get("close")):
                wired["close"]()
        print(json.dumps({"campaign_ledger": campaign.summary(), **{k: manifest[k] for k in ("status", "progress", "counts", "ledger", "extras")}},
                         indent=1, default=str))
    elif args.cmd == "score":
        from stage3_eval.canary import TruthScanner
        from stage3_eval.scoring import score_run
        from stage3_eval.truth_io import truth_vocabulary
        config, _run_side = _config(args.selection)
        selection = _scorer_selection(args.selection)
        wired = _call_wiring(_wiring(args.wiring), config, run_dir=args.run)
        worlds = {w: truth for w, (truth, _replay) in _worlds(args.world).items()}
        rows = score_run(args.run, selection, worlds, ingestion=wired.get("ingestion"), resolver=wired.get("resolver"))
        scans = {w: TruthScanner(truth_vocabulary(t)).scan_run(args.run) for w, t in worlds.items()}
        verdicts = [s["verdict"] for s in scans.values()]
        canary = {"verdict": "invalid" if "invalid" in verdicts else "incomplete" if "incomplete" in verdicts else "clean", "per_world": scans,
                  "missing_surfaces": sorted({m for s in scans.values() for m in s["missing_surfaces"]})}
        Path(args.run, "canary.json").write_text(json.dumps(canary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        if callable(wired.get("close")):
            wired["close"]()
        print(json.dumps({"scored_rows": len(rows), "canary": canary["verdict"]}, indent=1))
    elif args.cmd == "report":
        _config(args.selection)
        print(_report(_scorer_selection(args.selection), args.run, Path(args.selection).parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
