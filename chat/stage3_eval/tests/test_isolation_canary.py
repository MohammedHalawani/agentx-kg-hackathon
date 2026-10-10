"""Truth stays out of the run step, and the canary scan proves it can see a planted marker."""
import ast
import json
from pathlib import Path

import pytest

from stage3_eval.canary import TruthScanner
from stage3_eval.truth_io import truth_vocabulary

PKG = Path(__file__).resolve().parents[1]
RUN_SIDE = ("runner.py", "arms.py", "records.py", "budget.py", "interfaces.py", "canary.py", "design.py", "stats.py", "fixtures/fakes.py")
SCORER_SIDE = {"stage3_eval.truth_io", "stage3_eval.strata", "stage3_eval.selection", "stage3_eval.scoring", "world", "world.truth",
               "world.export", "world.mechanisms"}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


@pytest.mark.parametrize("name", RUN_SIDE)
def test_run_side_modules_import_nothing_truth_side(name):
    imported = _imports(PKG / name)
    assert not imported & SCORER_SIDE, f"{name} imports {imported & SCORER_SIDE}"
    assert not any(m == "world" or m.startswith("world.") for m in imported)


def test_fixture_fakes_read_runtime_files_only():
    text = (PKG / "fixtures" / "fakes.py").read_text()
    assert '"truth"' not in text and "truth.jsonl" not in text


def test_runtime_fixture_files_carry_no_truth(worlds):
    for world in ("E1", "E2"):
        vocab = truth_vocabulary(worlds[world][0])
        for f in (PKG / "fixtures" / f"world_{world.lower()}" / "runtime").iterdir():
            text = f.read_text()
            assert vocab["canary"] not in text and not any(i in text for i in vocab["mechanism_ids"])
            assert not any(n in text for n in vocab["mechanism_names"])


def _scanner(worlds):
    return TruthScanner(truth_vocabulary(worlds["E1"][0]))


def test_scanner_controls(worlds):
    s = _scanner(worlds)
    assert s.self_test()
    assert s.hits_in("parcel left at wrong building; MISDELIVERY suspected") and not s.hits_in("MISDELIVERY", include_names=False)


def _surface(run, surface, text):
    d = run / "captured" / surface
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.jsonl").write_text(json.dumps({"text": text}) + "\n")


def test_scan_verdicts(tmp_path, worlds):
    s = _scanner(worlds)
    run = tmp_path / "run"
    for surface in ("graph", "tools", "api", "receipts"):
        _surface(run, surface, "clean MILESTONE_OVERDUE WRONG_GATE")
    assert s.scan_run(run)["verdict"] == "incomplete"          # logs not captured: never "clean"
    _surface(run, "logs", "clean")
    assert s.scan_run(run)["verdict"] == "clean"
    _surface(run, "arm_outputs", "the model wrote MISDELIVERY in prose")
    assert s.scan_run(run)["verdict"] == "clean"               # model prose may coincide with a mechanism name
    _surface(run, "tools", "tool returned " + worlds["E1"][0]["FXT-SHP-E1-0001"]["canary"])
    result = s.scan_run(run)
    assert result["verdict"] == "invalid" and result["hits_by_kind"] == {"canary": 1}
    assert worlds["E1"][0]["FXT-SHP-E1-0001"]["canary"] not in json.dumps(result)   # tokens are counted, never echoed
    _surface(run, "graph", "node property FACILITY_BACKLOG")
    assert s.scan_run(run)["hits_by_kind"].get("mechanism_name") == 1
