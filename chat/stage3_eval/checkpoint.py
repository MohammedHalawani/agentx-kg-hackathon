"""The recorded automatic checkpoint of a paused run. Run side: it reads NO truth.

The sequence is `run --max-cases 40`, `checkpoint`, `run --resume`. The checkpoint looks at what the first cases left
in the run directory (the manifest, the run's own ledger, the cases, the agent arm's results, the captured surfaces)
and, through an evidence resolver, at when the records the agent retrieved or cited were recorded in the run's
database (read-only). It reads selection.json as the run does (key, world, shipment and expected opening per case)
and nothing from the scorer side: no truth row, no stratum, no extras list, no score. Nothing here is a result of the
evaluation; every measure is about whether the run is healthy enough to carry on.

Conditions (thresholds are parameters; these are the defaults):

  run_status              the run ended this part as "paused" (or "completed") and is the run of this selection
  degraded                agent-arm cases with no valid conclusion                       <= 0.15 of agent cases run
  cap_hit                 agent-arm cases that hit the per-case model-call cap           <= 0.10 of agent cases run
  provider_failures       failed provider calls, over every part of the run              <= 0.05 of provider calls
  citations_all_valid     concluded agent cases whose citations are all valid            >= 0.90 of concluded cases
  opened                  settled cases the run's monitor opened                         >= 0.90 of settled cases
  evidence_after_snapshot agent cases with any retrieved or cited record recorded after the case's snapshot   == 0
  markers                 canary-shaped or mechanism-id-shaped tokens in the captured surfaces: none, every surface present
  reconciled              after every settled case the ledger held at least the provider's count; no cap violation; no
                          open reservation; the campaign entry equals the calls the run's ledger committed
  truth_modules           the run process had no truth-side module loaded and no truth variable set (manifest)

A measure that could not be taken (no resolver, no provider count, no concluded case) fails its condition: the
checkpoint never passes on something it did not check.

Citation validity is the run record's own flag when the record carries one (ArmResult.citations_valid: every cited id
resolves, was retrieved in this investigation and was recorded by the snapshot, as operations.checks computed it);
for a record without the flag the same three things are checked here with the resolver.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from stage3_eval.budget import read_ledger
from stage3_eval.canary import REQUIRED_SURFACES, marker_hits
from stage3_eval.records import ArmResult
from stage3_eval.runner import load_selection

SCHEMA = "stage3-checkpoint-1"
DEFAULT_THRESHOLDS = {"degraded_max": 0.15, "cap_hit_max": 0.10, "provider_failures_max": 0.05, "citations_all_valid_min": 0.90,
                      "opened_min": 0.90}
OK_STATUSES = ("paused", "completed")


def _jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _share(part, whole):
    return round(part / whole, 4) if whole else None


def scan_markers(run_dir):
    """The run step's shape screen (canary.marker_hits: no vocabulary, so no truth) over everything captured so far.
    "clean" only if there is no hit and every required surface has been captured; tokens are counted, never echoed."""
    if marker_hits("CNRY" + "0" * 24 + " W1M-00001") != 2:
        raise RuntimeError("the marker screen failed its positive control")
    root = Path(run_dir) / "captured"
    surfaces, hits = {}, 0
    for surface in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        files = sorted(f for f in surface.rglob("*") if f.is_file())
        found = sum(marker_hits(f.read_text(encoding="utf-8", errors="replace")) for f in files)
        surfaces[surface.name] = {"files": len(files), "hits": found}
        hits += found
    missing = [s for s in REQUIRED_SURFACES if not surfaces.get(s, {}).get("files")]
    return {"verdict": "hits" if hits else "incomplete" if missing else "clean", "hits": hits, "surfaces": surfaces,
            "missing_surfaces": missing, "screen": "canary and mechanism-id shapes (no truth vocabulary)"}


def _provider(manifest):
    """Provider calls over every part of the run (each process counted its own): (succeeded, failed), or None."""
    parts = [s.get("provenance") or {} for s in manifest.get("earlier_segments") or []] + [manifest.get("provenance") or {}]
    counted = [p["model_calls"] for p in parts if isinstance(p.get("model_calls"), dict)]
    if not counted:
        return None
    return (sum(sum((c.get("succeeded") or {}).values()) for c in counted), sum(sum((c.get("failed") or {}).values()) for c in counted))


def _reconciliation(run_dir, manifest, settled_keys):
    events = read_ledger(Path(run_dir) / "ledger.jsonl") if (Path(run_dir) / "ledger.jsonl").exists() else []
    checks = [e for e in events if e.get("event") == "reconcile"]
    main = {e["case_key"] for e in checks if e.get("phase", "main") == "main"}
    failed = [e["case_key"] for e in checks if not e.get("ok")]
    violations = sum(1 for e in events if e.get("event") == "violation")
    ledger = manifest.get("ledger") or {}
    campaign = manifest.get("campaign_ledger")
    problems = []
    if not checks:
        problems.append("the run's ledger holds no reconciliation with the provider's count")
    if sorted(settled_keys - main):
        problems.append(f"{len(settled_keys - main)} settled case(s) were not reconciled with the provider's count")
    if failed:
        problems.append(f"the provider counted more calls than the ledger held after {len(failed)} case(s)")
    if violations or ledger.get("cap_violations"):
        problems.append("a case used more calls than it reserved")
    if ledger.get("open_reservations"):
        problems.append(f"{ledger['open_reservations']} reservation(s) still open")
    if campaign is not None and campaign.get("calls") != ledger.get("committed_calls"):
        problems.append(f"the campaign entry holds {campaign.get('calls')} calls and the run's ledger committed {ledger.get('committed_calls')}")
    last = checks[-1] if checks else {}
    return {"ok": not problems, "problems": problems, "reconcile_entries": len(checks), "cases_reconciled": len(main & settled_keys),
            "committed_calls": ledger.get("committed_calls"), "settled_calls": ledger.get("settled_calls"), "calls_by_arm": ledger.get("calls_by_arm"),
            "recovered_after_crash": ledger.get("recovered_after_crash"), "campaign_entry_calls": (campaign or {}).get("calls"),
            "last_reconciliation": {k: last.get(k) for k in ("case_key", "ledger_calls", "provider_calls", "ok")} if last else None}


def _evidence(rows, resolver):
    """Per agent case, against the resolver: the retrieved or cited ids recorded after the case's snapshot, and (for a
    record that carries no citation flag of its own) whether every cited id was retrieved, resolves and is in time."""
    from dataset_v2.contracts import instant
    after, unresolved, checked, fallback = [], 0, 0, {}
    for r in rows:
        if not r.as_of:
            continue
        world = r.case_key.split(":", 1)[0]
        cited, retrieved = r.cited_ids, {i for i in r.retrieved_ids if isinstance(i, str)}
        ids = sorted(retrieved | set(cited))
        recorded = resolver.recorded_at(world, ids) if ids else {}
        when = instant(r.as_of)
        late = [i for i in ids if i in recorded and instant(str(recorded[i])) > when]
        checked += 1
        unresolved += sum(1 for i in ids if i not in recorded)
        if late:
            after.append({"case_key": r.case_key, "records": len(late), "cited": sum(1 for i in late if i in cited)})
        fallback[r.case_key] = all(i in retrieved and i in recorded and i not in late for i in cited)
    return {"cases_checked": checked, "cases_with_evidence_after_snapshot": len(after), "cases": after[:50],
            "ids_that_did_not_resolve": unresolved}, fallback


def checkpoint(selection_path, run_dir, *, resolver=None, thresholds=None):
    """The checkpoint document of a run directory (not written: write_checkpoint). resolver: recorded_at(world, ids) ->
    {id: recorded_at} over the run's database, read-only (scripts.stage3_wiring:build_checkpoint); without it the
    evidence condition is not checked, and fails. thresholds: overrides of DEFAULT_THRESHOLDS."""
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    unknown = sorted(set(limits) - set(DEFAULT_THRESHOLDS))
    if unknown:
        raise ValueError(f"unknown thresholds: {unknown}")
    run_dir = Path(run_dir)
    selection, selection_sha = load_selection(selection_path)       # the run-readable file, checked as the run checks it
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"{manifest_path} is missing: a checkpoint is taken of a run that has paused (run --max-cases N)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dry_run"):
        raise ValueError("a dry run made no call and investigated nothing; there is nothing to check")
    settled = [row["key"] for row in _jsonl(run_dir / "settled.jsonl")]
    settled_keys = set(settled)
    opened_keys = {row["key"] for row in _jsonl(run_dir / "cases.jsonl")} & settled_keys
    by_key = {}
    for raw in _jsonl(run_dir / "results" / "main" / "agent.jsonl"):
        result = ArmResult.from_dict(raw)
        if result.case_key in settled_keys:
            by_key[result.case_key] = result
    ran = [r for r in by_key.values() if r.not_run is None]
    concluded = [r for r in ran if not r.degraded and r.primary_cause is not None]

    evidence, fallback = (None, {})
    if resolver is not None:
        evidence, fallback = _evidence(ran, resolver)
    flagged = [r for r in concluded if r.citations_valid is not None]
    valid = sum(1 for r in concluded if (r.citations_valid if r.citations_valid is not None else fallback.get(r.case_key, False)))
    unchecked = sum(1 for r in concluded if r.citations_valid is None and r.case_key not in fallback)

    provider = _provider(manifest)
    provider_rate = _share(provider[1], provider[0] + provider[1]) if provider else None
    markers = scan_markers(run_dir)
    reconciliation = _reconciliation(run_dir, manifest, settled_keys)
    isolation = manifest.get("isolation")
    truth_modules = (isolation or {}).get("truth_modules_loaded")
    truth_environment = (isolation or {}).get("truth_environment_set")
    status = manifest.get("status")
    same_run = manifest.get("selection_sha256") == selection_sha and manifest.get("sealed_config_hash") == selection["sealed_config_hash"]

    measures = {
        "degraded_rate": _share(sum(1 for r in ran if r.degraded), len(ran)),
        "cap_hit_rate": _share(sum(1 for r in ran if r.cap_hit), len(ran)),
        "provider_failure_rate": provider_rate,
        "citations_all_valid_share": _share(valid, len(concluded)),
        "opened_share": _share(len(opened_keys), len(settled_keys)),
        "evidence_after_snapshot_cases": evidence["cases_with_evidence_after_snapshot"] if evidence else None,
        "markers": markers["verdict"],
        "ledger_reconciled": reconciliation["ok"],
        "truth_modules_loaded": truth_modules,
    }

    def at_most(value, limit):
        return value is not None and value <= limit

    def at_least(value, limit):
        return value is not None and value >= limit
    conditions = [
        {"name": "run_status", "value": status, "rule": f"one of {list(OK_STATUSES)}, and the run of this selection",
         "ok": status in OK_STATUSES and same_run},
        {"name": "degraded", "value": measures["degraded_rate"], "rule": f"<= {limits['degraded_max']}",
         "ok": at_most(measures["degraded_rate"], limits["degraded_max"])},
        {"name": "cap_hit", "value": measures["cap_hit_rate"], "rule": f"<= {limits['cap_hit_max']}",
         "ok": at_most(measures["cap_hit_rate"], limits["cap_hit_max"])},
        {"name": "provider_failures", "value": provider_rate, "rule": f"<= {limits['provider_failures_max']}",
         "ok": at_most(provider_rate, limits["provider_failures_max"])},
        {"name": "citations_all_valid", "value": measures["citations_all_valid_share"], "rule": f">= {limits['citations_all_valid_min']}",
         "ok": at_least(measures["citations_all_valid_share"], limits["citations_all_valid_min"])},
        {"name": "opened", "value": measures["opened_share"], "rule": f">= {limits['opened_min']}",
         "ok": at_least(measures["opened_share"], limits["opened_min"])},
        {"name": "evidence_after_snapshot", "value": measures["evidence_after_snapshot_cases"], "rule": "== 0",
         "ok": measures["evidence_after_snapshot_cases"] == 0},
        {"name": "markers", "value": markers["verdict"], "rule": "clean", "ok": markers["verdict"] == "clean"},
        {"name": "reconciled", "value": reconciliation["ok"], "rule": "the ledger is reconciled with the provider's count", "ok": reconciliation["ok"]},
        {"name": "truth_modules", "value": truth_modules, "rule": "none loaded, and no truth variable set, in the run process",
         "ok": isolation is not None and truth_modules == [] and not truth_environment},
    ]
    failed = [c["name"] for c in conditions if not c["ok"]]
    progress = manifest.get("progress") or {}
    return {
        "schema": SCHEMA, "taken_at": datetime.now(timezone.utc).isoformat(), "run_dir": str(run_dir), "reads_truth": False,
        "selection_sha256": selection_sha, "sealed_config_hash": selection["sealed_config_hash"], "run_status": status,
        "paused": bool(progress.get("paused")), "cases_settled": len(settled_keys), "cases_total": len(selection["cases"]),
        "last_case_settled": settled[-1] if settled else None, "thresholds": limits, "measures": measures, "conditions": conditions,
        "failed": failed, "pass": not failed,
        "details": {
            "agent_arm": {"cases_run": len(ran), "degraded": sum(1 for r in ran if r.degraded), "cap_hit": sum(1 for r in ran if r.cap_hit),
                          "concluded": len(concluded), "failure_modes": _tally(r.failure_mode for r in ran if r.degraded)},
            "citations": {"concluded": len(concluded), "all_valid": valid, "from_the_run_record": len(flagged),
                          "checked_here_with_the_resolver": len(concluded) - len(flagged) - unchecked, "not_checked": unchecked},
            "opened": {"settled": len(settled_keys), "opened": len(opened_keys)},
            "provider_calls": {"succeeded": provider[0], "failed": provider[1]} if provider else None,
            "evidence": evidence, "markers": markers, "ledger": reconciliation,
            "isolation": {"truth_modules_loaded": truth_modules, "truth_environment_set": truth_environment,
                          "enforced": (isolation or {}).get("enforced")},
            "parts": 1 + len(manifest.get("earlier_segments") or []),
        },
    }


def _tally(values):
    out = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items()))


def write_checkpoint(document, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path
