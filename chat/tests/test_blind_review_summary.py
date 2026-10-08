"""Published model columns must survive sorted JSON and incomplete rubric scores."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = ("factual_fidelity", "evidence_concision", "action_review_consistency", "language_clarity", "uncertainty_lifecycle")
MODELS = ("openai/gpt-oss:20b", "openai/gpt-oss:120b")


class SummaryTests(unittest.TestCase):
    def fixture(self, directory, null_arabic=False, duplicate_key=False):
        review = directory / "quality-review"
        review.mkdir()
        cases, records, key = [], [], {}
        for index in range(1, 31):
            case_id, language = f"case-{index:02}", "ar" if index <= 18 else "en"
            cases.append({"case_id": case_id, "language": language})
            key[case_id] = {"A": MODELS[0], "B": MODELS[1]}
            for alias, score in (("A", 2), ("B", 1)):
                values = {dimension: None if null_arabic and language == "ar" else score for dimension in DIMENSIONS}
                records.append({"case_id": case_id, "alias": alias, "complaint_language": language,
                    "prose_target": None, "scores": values, "total": None if None in values.values() else 5*score,
                    "ready_to_show": score == 2 and not (null_arabic and language == "ar"),
                    "critical_flags": [], "native_prose_language": "en"})
        if duplicate_key:
            key["case-01"]["B"] = MODELS[0]
        files = {"runtime_inputs.json": {"cases": cases}, "comparison.json": {
                    "models": {model: {"completed_cases": 30} for model in reversed(MODELS)}}}
        for name, data in files.items():
            (directory / name).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        (review / "model-key.json").write_text(json.dumps(key), encoding="utf-8")
        for name, start, stop in (("blind-scores-01-15.json", 0, 15), ("blind-scores-16-30.json", 15, 30)):
            packet = {"review_type": "fixture", "model_blinding": "fixture",
                "records": records[2*start:2*stop], "preferences": [
                    {"case_id": case["case_id"], "preference": "A"} for case in cases[start:stop]]}
            (review / name).write_text(json.dumps(packet), encoding="utf-8")

    def run_summary(self, directory):
        return subprocess.run([sys.executable, str(ROOT / "scripts/summarize_blind_review.py"), str(directory)],
                              capture_output=True, text=True)

    def test_sorted_model_keys_do_not_swap_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            result = self.run_summary(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (directory / "quality-review/summary.md").read_text(encoding="utf-8")
            self.assertIn("| factual_fidelity | 2 / 0 | 1 / 30 |", text)
            data = json.loads((directory / "quality-review/summary.json").read_text(encoding="utf-8"))
            self.assertEqual(data["models"][MODELS[0]]["mean_total"], 10)
            self.assertEqual(data["models"][MODELS[1]]["mean_total"], 5)

    def test_unassessable_language_has_null_mean_and_explicit_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory, null_arabic=True)
            result = self.run_summary(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((directory / "quality-review/summary.json").read_text(encoding="utf-8"))
            group = data["models"][MODELS[0]]["by_complaint_language"]["ar"]
            self.assertEqual(group["not_assessable"], 18)
            self.assertIsNone(group["mean_language_clarity"])

    def test_nonbijective_model_key_refuses_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory, duplicate_key=True)
            self.assertNotEqual(self.run_summary(directory).returncode, 0)
            self.assertFalse((directory / "quality-review/summary.json").exists())
