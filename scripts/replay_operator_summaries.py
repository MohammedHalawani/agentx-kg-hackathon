"""Replay saved final fields through the current operator boundary; no model/DB calls."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))
from llm.pipeline import graph


def main():
    bundle = ROOT / "docs/evals/2026-10-08_gpt-oss-v1"
    runtime = json.loads((bundle / "runtime_inputs.json").read_text(encoding="utf-8"))
    records = []
    for case in runtime["cases"]:
        for model in ("20b", "120b"):
            saved = json.loads((bundle / "results" / model / (case["case_id"] + ".json")).read_text(encoding="utf-8"))
            state = {**saved["final"], "context": case["context"]}
            fields = {field: graph._operator_detail(stage, state.get(field), state)
                      for stage, field in (("classify", "classification"), ("recommend", "recommendation"), ("review", "review"))}
            assert fields["classification"]["category"] == state["classification"]["category"]
            assert fields["recommendation"]["action"] == state["recommendation"]["action"]
            assert fields["review"]["verdict"] == state["review"]["verdict"]
            records.append({"case_id": case["case_id"], "model": model, "operator_fields": fields})
    lookup = {(row["case_id"], row["model"]): row["operator_fields"] for row in records}
    assert "budget remains" in lookup["case-05", "20b"]["classification"]["rationale"]
    assert "exact-action matches: 1" in lookup["case-07", "20b"]["recommendation"]["rationale"]
    assert "80%" not in lookup["case-12", "120b"]["recommendation"]["rationale"]
    assert "five" not in lookup["case-15", "120b"]["recommendation"]["rationale"]
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(), "count": len(records),
               "kind": "offline display/persistence regression replay, not a new model benchmark",
               "model_calls": 0, "database_calls": 0,
               "operator_source_sha256": hashlib.sha256((ROOT / "chat/llm/pipeline/operator_output.py").read_bytes()).hexdigest(),
               "limitations": "Original choices/verdicts retained. Internal reasoning, semantic correctness and Arabic display translation are not re-evaluated.",
               "records": records}
    path = ROOT / "docs/agent-runs/2026-10-08_baseline-stabilization-operator-replay.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("count", "kind", "model_calls", "database_calls")}))


if __name__ == "__main__":
    main()
