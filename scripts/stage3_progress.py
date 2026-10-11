"""Write <run dir>/../progress_<run>.json: a small, truth-free progress file for a Stage 3 run that anyone can read.

  uv run python ../scripts/stage3_progress.py ../artifacts/stage3/run1
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def rows(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def main():
    run = Path(sys.argv[1]).resolve()
    settled = rows(run / "settled.jsonl")
    cases = rows(run / "cases.jsonl")
    ledger = rows(run / "ledger.jsonl")
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8")) if (run / "run_manifest.json").exists() else {}
    calls = sum(int(e.get("calls") or 0) for e in ledger if e.get("event") in ("settle", "settled"))
    newest = max((p.stat().st_mtime for p in run.glob("*.jsonl")), default=None)
    out = {"run": str(run), "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "status": manifest.get("status", "running or not started"), "progress": manifest.get("progress"),
           "cases_reached": len(cases), "cases_settled": len(settled),
           "cases_reached_by_world": dict(Counter(str(c.get("world")) for c in cases)),
           "ledger_entries": len(ledger), "calls_settled_in_run_ledger": calls,
           "last_write_utc": datetime.fromtimestamp(newest, timezone.utc).isoformat(timespec="seconds") if newest else None,
           "checkpoint": (json.loads((run / "checkpoint.json").read_text(encoding="utf-8")).get("pass")
                          if (run / "checkpoint.json").exists() else None)}
    target = run.parent / f"progress_{run.name}.json"
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
