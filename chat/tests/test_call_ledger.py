"""The campaign's persistent model-call ledger (operations/call_ledger.py) and the runs that go through it.

No model call, no database: the pilot's replay is replaced by a stand-in that reports a call count, and every test
writes to a ledger file of its own. The committed ledger is only read (its seed entries are checked against the
pilot's results files).
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from operations.call_ledger import (CAMPAIGN_CAP, DEFAULT_PATH, LEDGER_ENV, LEDGER_RELATIVE, SCHEMA, CallLedger, LedgerError,
                                    LedgerRefused, ledger_path, reserved_run)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import world_pilot            # noqa: E402
import world_pilot_rerun      # noqa: E402

PILOT_DIR = ROOT / "docs" / "evals" / "2026-10-10_world1_pilot"


def write_ledger(directory, entries=(), cap=4000):   # A test ledger with a small guard of its own.
    path = Path(directory) / "ledger.json"
    path.write_text(json.dumps({"schema": SCHEMA, "campaign": "test", "cap": cap, "entries": list(entries)}), encoding="utf-8")
    return path


def spent_entry(calls, run="earlier"):
    return {"run": run, "started_at": "2026-10-10T00:00:00+00:00", "finished_at": "2026-10-10T01:00:00+00:00", "commit": "c" * 40,
            "calls": calls, "tokens": 0, "note": "", "reserved": calls}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_transient_windows_sharing_violation_keeps_atomic_counts_without_duplicating_entries(self):
        path=write_ledger(self.directory.name)
        ledger=CallLedger(path)
        original=os.replace
        attempts=[]
        def sharing_then_replace(*args):
            attempts.append(True)
            if len(attempts)==1:raise PermissionError("synthetic Windows sharing violation")
            return original(*args)
        with mock.patch("operations.call_ledger.os.replace",side_effect=sharing_then_replace):
            ledger.reserve("synthetic-run",1)
            ledger.settle("synthetic-run",2)
        self.assertEqual(len(ledger.load()["entries"]),1)
        self.assertEqual(ledger.spent,2)
        self.assertTrue(ledger.entry("synthetic-run")["over_reservation"])
        self.assertGreaterEqual(len(attempts),3)

    def test_persistent_sharing_failure_keeps_the_maximum_reservation_and_fails_closed(self):
        path=write_ledger(self.directory.name)
        ledger=CallLedger(path);ledger.reserve("synthetic-run",4)
        with mock.patch("operations.call_ledger.os.replace",side_effect=PermissionError("synthetic sharing violation")):
            with self.assertRaises(LedgerError):ledger.settle("synthetic-run",1)
        self.assertEqual(ledger.spent,4)
        self.assertIsNone(ledger.entry("synthetic-run")["finished_at"])
        self.assertFalse(path.with_name(path.name+".lock").exists())

    def test_the_committed_ledger_holds_the_two_runs_already_made(self):
        self.assertEqual(DEFAULT_PATH, ROOT / LEDGER_RELATIVE)
        ledger = CallLedger(DEFAULT_PATH)
        document = ledger.load()
        # The cap is a runaway guard since the budget was lifted (2026-10-11), and the file says so.
        self.assertEqual((document["schema"], document["cap"]), (SCHEMA, CAMPAIGN_CAP))
        self.assertEqual(CAMPAIGN_CAP, 20000)
        self.assertIn("guard, not an allowance", document["note"])
        by_file = {name: next(e for e in document["entries"] if f"/{name})" in e["run"]) for name in ("pilot.json", "rerun.json")}
        for name, entry in by_file.items():
            provenance = json.loads((PILOT_DIR / name).read_text(encoding="utf-8"))["provenance"]
            self.assertEqual(entry["calls"], provenance["model_calls_total"])
            self.assertEqual(entry["tokens"], provenance["model_calls"]["total_tokens"])
            self.assertEqual((entry["commit"], entry["started_at"], entry["finished_at"]),
                             (provenance["commit"], provenance["started_at"], provenance["finished_at"]))
            self.assertEqual(set(entry) >= {"run", "started_at", "finished_at", "commit", "calls", "tokens", "note"}, True)
        self.assertEqual((by_file["pilot.json"]["calls"], by_file["pilot.json"]["tokens"]), (111, 985609))
        self.assertEqual((by_file["rerun.json"]["calls"], by_file["rerun.json"]["tokens"]), (62, 687366))
        self.assertGreaterEqual(ledger.spent, 173)
        self.assertEqual(ledger.remaining, 20000 - ledger.spent)

    def test_runs_add_up_and_a_run_that_would_cross_the_cap_is_refused_before_anything_is_written(self):
        path = write_ledger(self.directory.name, [spent_entry(111, "pilot"), spent_entry(62, "rerun")], cap=400)
        ledger = CallLedger(path)
        self.assertEqual((ledger.spent, ledger.remaining), (173, 227))
        held = ledger.reserve("run A", 144, commit="a" * 40, note="first")
        self.assertEqual((held["calls"], held["reserved"], held["finished_at"]), (144, 144, None))
        self.assertEqual((ledger.spent, ledger.remaining), (317, 83))          # the reservation counts at its maximum
        before = path.read_bytes()
        with self.assertRaisesRegex(LedgerRefused, "would exceed the cap"):
            ledger.reserve("run B", 84)
        with self.assertRaises(LedgerRefused):
            ledger.check(84)
        self.assertEqual(path.read_bytes(), before)                            # a refusal writes nothing
        self.assertEqual(ledger.check(83), 83)
        settled = ledger.settle("run A", 100, tokens=12345)
        self.assertEqual((settled["calls"], settled["tokens"], settled["reserved"]), (100, 12345, 144))
        self.assertIsNotNone(settled["finished_at"])
        self.assertEqual((ledger.spent, ledger.remaining), (273, 127))         # what it used, not what it held
        ledger.reserve("run B", 127)                                           # exactly what is left fits
        self.assertEqual(ledger.remaining, 0)
        with self.assertRaises(LedgerRefused):
            ledger.reserve("run C", 1)
        self.assertEqual([e["run"] for e in ledger.load()["entries"]], ["pilot", "rerun", "run A", "run B"])
        self.assertEqual(ledger.summary()["open_reservations"], ["run B"])

    def test_a_run_that_dies_stays_counted_at_its_maximum(self):
        path = write_ledger(self.directory.name, [spent_entry(173)], cap=400)
        with self.assertRaises(RuntimeError):
            with reserved_run("crashes", 144, commit="a" * 40, path=path) as used:
                raise RuntimeError("the process died mid-run")
        ledger = CallLedger(path)
        entry = ledger.entry("crashes")
        self.assertEqual((entry["calls"], entry["finished_at"], ledger.spent), (144, None, 317))
        with reserved_run("never reports", 20, path=path):
            pass
        self.assertEqual((ledger.entry("never reports")["calls"], ledger.spent), (20, 337))
        with reserved_run("finishes", 60, path=path) as used:
            used(41, 9000)
        self.assertEqual((ledger.entry("finishes")["calls"], ledger.entry("finishes")["tokens"], ledger.spent), (41, 9000, 378))
        with self.assertRaises(LedgerRefused):        # 22 remain: the body never runs
            with reserved_run("too big", 23, path=path):
                self.fail("a refused run must not start")

    def test_a_run_name_is_entered_once_and_a_resume_never_counts_twice(self):
        path = write_ledger(self.directory.name, [spent_entry(100)], cap=400)
        ledger = CallLedger(path)
        ledger.reserve("stage3", 250)
        with self.assertRaisesRegex(LedgerError, "already in the ledger"):
            ledger.reserve("stage3", 250)
        self.assertEqual(ledger.spent, 350)
        ledger.reserve("stage3", 250, resume=True)                             # taken up again: still 250, not 500
        self.assertEqual(ledger.spent, 350)
        ledger.settle("stage3", 200)
        ledger.reserve("stage3", 250, resume=True)                             # a settled run reopened holds its maximum again
        self.assertEqual((ledger.spent, ledger.entry("stage3")["finished_at"]), (350, None))
        with self.assertRaises(LedgerRefused):
            ledger.reserve("stage3", 301, resume=True)
        with self.assertRaisesRegex(LedgerError, "no reservation"):
            ledger.settle("unknown", 1)

    def test_a_count_above_the_reservation_is_recorded_as_it_is_and_marked(self):
        path = write_ledger(self.directory.name, cap=100)
        ledger = CallLedger(path)
        ledger.reserve("over", 10)
        entry = ledger.settle("over", 13)
        self.assertEqual((entry["calls"], entry["over_reservation"], ledger.spent), (13, True, 13))

    def test_a_missing_or_malformed_ledger_stops_the_run(self):
        missing = CallLedger(Path(self.directory.name) / "none.json")
        with self.assertRaisesRegex(LedgerError, "missing"):
            missing.check(1)
        bad = Path(self.directory.name) / "bad.json"
        for text in ("{", json.dumps({"schema": "other", "cap": 1, "entries": []}), json.dumps({"schema": SCHEMA, "cap": 10, "entries": [{"run": "a", "calls": -1}]}),
                     json.dumps({"schema": SCHEMA, "cap": 10, "entries": [{"run": "a", "calls": 1}, {"run": "a", "calls": 1}]}),
                     json.dumps({"schema": SCHEMA, "cap": 10, "entries": [{"run": "a", "calls": "3"}]})):
            bad.write_text(text, encoding="utf-8")
            with self.assertRaises(LedgerError):
                CallLedger(bad).reserve("x", 1)
        with self.assertRaises(LedgerError):
            CallLedger(write_ledger(self.directory.name)).reserve("x", -1)

    def test_the_path_comes_from_the_argument_then_the_environment_then_the_committed_file(self):
        with mock.patch.dict(os.environ, {LEDGER_ENV: "from-env.json"}):
            self.assertEqual(ledger_path("given.json"), Path("given.json"))
            self.assertEqual(ledger_path(), Path("from-env.json"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(LEDGER_ENV, None)
            self.assertEqual(ledger_path(), DEFAULT_PATH)

    def test_the_file_is_written_whole_with_lf_and_no_leftovers(self):
        path = write_ledger(self.directory.name)
        ledger = CallLedger(path)
        ledger.reserve("a", 5)
        ledger.settle("a", 3)
        self.assertNotIn(b"\r", path.read_bytes())
        self.assertEqual(sorted(p.name for p in Path(self.directory.name).iterdir()), ["ledger.json"])


class PilotThroughTheLedgerTests(unittest.TestCase):
    """scripts/world_pilot.py and scripts/world_pilot_rerun.py: refused at the cap, reserved at start, settled at the end."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name) / "pilot.json"
        clean = {k: v for k, v in os.environ.items() if "TRUTH" not in k.upper() and k != "SUHAIL_SIM_STATE_ROOT"}
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_replay(self, calls, fail=False):
        def run_pilot(driver, database, **settings):
            if fail:
                raise RuntimeError("the replay died")
            return {"schema": world_pilot.RESULT_SCHEMA, "manifest_hash": "0" * 64, "cases": [], "time_correct_check": {"pass": True},
                    "replay": {"stop_reason": "max_cases_reached", "model_calls_by_case_counters": calls, "world_truth_imported": False,
                               "truth_environment_set": []}}
        return run_pilot

    def run_main(self, ledger, *, calls=0, fail=False, max_calls=144):
        class Driver:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        with mock.patch.object(world_pilot, "run_pilot", self.fake_replay(calls, fail)), \
                mock.patch.object(world_pilot, "record_model_calls", lambda: None), \
                mock.patch.object(world_pilot, "provider_calls", lambda: 0), \
                mock.patch("neo4j.GraphDatabase.driver", lambda *a, **k: Driver()):
            world_pilot.main(["--out", str(self.out), "--allow-dirty", "--ledger", str(ledger), "--max-calls", str(max_calls)])

    def test_the_pilot_refuses_to_start_when_its_maximum_does_not_fit(self):
        ledger = write_ledger(self.directory.name, [spent_entry(3900)])
        before = ledger.read_bytes()

        def no_run(*a, **k):
            self.fail("a refused pilot must not open a database or run")
        with mock.patch.object(world_pilot, "run_pilot", no_run), mock.patch("neo4j.GraphDatabase.driver", no_run):
            with self.assertRaisesRegex(SystemExit, "Refusing to run: refused: 3900 of 4000"):
                world_pilot.main(["--out", str(self.out), "--allow-dirty", "--ledger", str(ledger), "--max-calls", "144"])
        self.assertEqual(ledger.read_bytes(), before)
        self.assertFalse(self.out.exists())

    def test_the_pilot_reserves_its_maximum_and_writes_what_it_used(self):
        ledger = write_ledger(self.directory.name, [spent_entry(173)])
        self.run_main(ledger, calls=97)
        book = CallLedger(ledger)
        entry = book.load()["entries"][-1]
        self.assertTrue(entry["run"].startswith("world_pilot pilot.json "))
        self.assertEqual((entry["calls"], entry["reserved"], book.spent, book.remaining), (97, 144, 270, 3730))
        self.assertIsNotNone(entry["finished_at"])
        self.assertEqual(len(entry["commit"]), 40)
        self.assertTrue(self.out.exists())
        # A second run adds to the same ledger; a third that would cross the cap is refused.
        self.out = Path(self.directory.name) / "pilot2.json"
        self.run_main(ledger, calls=144)
        self.assertEqual(book.spent, 414)
        self.out = Path(self.directory.name) / "pilot3.json"
        with self.assertRaisesRegex(SystemExit, "Refusing to run"):
            self.run_main(ledger, calls=1, max_calls=3587)
        self.assertEqual((book.spent, len(book.load()["entries"])), (414, 3))

    def test_a_pilot_that_dies_stays_counted_at_its_maximum(self):
        ledger = write_ledger(self.directory.name, [spent_entry(173)])
        with self.assertRaisesRegex(RuntimeError, "the replay died"):
            self.run_main(ledger, fail=True)
        book = CallLedger(ledger)
        entry = book.load()["entries"][-1]
        self.assertEqual((entry["calls"], entry["finished_at"], book.spent), (144, None, 317))

    def test_the_rerun_refuses_at_the_cap_before_reading_anything_else(self):
        ledger = write_ledger(self.directory.name, [spent_entry(3950)])
        before = ledger.read_bytes()
        with self.assertRaisesRegex(SystemExit, "Refusing to run: refused: 3950 of 4000"):
            world_pilot_rerun.main(["no-such-results.json", "--cases", "1", "--out", str(self.out), "--ledger", str(ledger)])
        self.assertEqual(ledger.read_bytes(), before)

    def test_the_rerun_reserves_and_settles_through_the_pilots_helpers(self):
        source = Path(world_pilot_rerun.__file__).read_text(encoding="utf-8")
        for needed in ("pilot.campaign_ledger(args.ledger, args.max_calls)", "pilot.reserve_calls(ledger, run_name, args.max_calls",
                       "ledger.settle(run_name, spent()"):
            self.assertIn(needed, source)
        self.assertLess(source.index("pilot.reserve_calls("), source.index("store.process_one("))
        self.assertLess(source.index("store.process_one("), source.index("ledger.settle("))

    def test_the_rerun_records_itself_and_not_the_pilot(self):
        """The record slips of the first re-run: its file named the pilot's script and carried the pilot's settings
        (max_calls 144, not 72), had no executions_dispatched and no end-of-run truth record."""
        import inspect
        first = {"schema": world_pilot.RESULT_SCHEMA, "synthetic": True, "database": "shipments-v2-world-x", "dataset_id": "DEMO-X",
                 "manifest_hash": "0" * 64, "session_id": "DEMO-SESSION-1",
                 "settings": {"per_alert": 2, "max_cases": 12, "max_calls": 144, "per_case_model_call_cap": 12, "execution_adapter": "none",
                              "disabled_tools": []}}
        document = world_pilot_rerun.rerun_document(
            first, [{"pilot_case": 4, "executions_dispatched": 1}], results="pilot.json", numbers=[4, 5], max_calls=72, per_case_cap=12,
            provenance={"script": world_pilot_rerun.SCRIPT}, isolation={"truth_environment_set": [], "world_truth_imported": False})
        self.assertEqual(document["settings"], {"script": "scripts/world_pilot_rerun.py", "max_calls": 72, "per_case_model_call_cap": 12,
                                                "pilot_cases": [4, 5], "execution_adapter": "none", "disabled_tools": []})
        self.assertEqual(document["pilot_settings"]["max_calls"], 144)            # kept, and named as the pilot's
        self.assertEqual(document["isolation"], {"truth_environment_set": [], "world_truth_imported": False})
        self.assertEqual((document["session_id"], document["rerun_of"], document["cases"][0]["executions_dispatched"]),
                         ("DEMO-SESSION-1", "pilot.json", 1))
        # The provenance names the script that ran: the pilot's function takes it, and the re-run passes its own.
        self.assertEqual(inspect.signature(world_pilot.provenance).parameters["script"].default, "scripts/world_pilot.py")
        source = Path(world_pilot_rerun.__file__).read_text(encoding="utf-8")
        self.assertIn("script=SCRIPT", source)
        self.assertIn("executed = store.execute_step(limit=5)", source)
        self.assertIn("executions_dispatched=len(executed) if isinstance(executed, list) else None", source)
        # The truth record is taken after the last investigation and before anything is written.
        self.assertLess(source.index("store.process_one("), source.index("pilot.truth_module_loaded()"))
        self.assertLess(source.index("pilot.truth_module_loaded()"), source.index("write_text("))
        self.assertIn("no results were written", source)

    def test_the_dirty_tree_check_leaves_the_ledger_file_out(self):
        calls = []

        def fake_git(command, **kwargs):
            calls.append(command)
            return "a" * 40 + "\n" if "rev-parse" in command else ""
        with mock.patch.object(world_pilot.subprocess, "check_output", fake_git):
            self.assertEqual(world_pilot.git_state(), ("a" * 40, False))
        status = next(c for c in calls if "status" in c)
        self.assertIn(f":(exclude){LEDGER_RELATIVE}", status)


if __name__ == "__main__":
    unittest.main()
