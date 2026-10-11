"""scripts/world_demo_session.py against a fake HTTP layer: the order of the calls, the refusals and what is printed.

No backend, no database, no model: FakeBackend answers the same paths the script calls and keeps a small state (clock,
simulator, worker, cases) so the polling loops behave as against a real one.
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "world_demo_session.py"
START = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)
LIVE_FROM = "2026-09-15T13:30:00+00:00"


def module():
    spec = importlib.util.spec_from_file_location("world_demo_session", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


demo = module()


class FakeBackend:
    """The operations API as the script uses it. Each status poll while running advances the clock by `stride` polls."""

    def __init__(self, *, reset_enabled=True, cases=(), investigations=2, stride_seconds=1.0, pages=100, audit_pages=100):
        self.token, self.calls = None, []
        self.reset_enabled, self.confirmation = reset_enabled, "RESET-SESSION-1"
        self.clock = START + timedelta(days=3)          # a used session: the reset puts it back to START
        self.simulator, self.speed, self.worker = "paused", 1, "paused"
        self.seed = [dict(c) for c in cases]            # opened by the monitor once the clock passes their opened_at
        self.cases, self.investigations, self.stride, self.pages = [], investigations, stride_seconds, pages
        self.monitor_pending = 0
        self.refuse = {}                                # (method, path) -> ApiError
        self.frozen = False
        self.session_id, self.audit_pages, self.origin = "DEMO-SESSION-0007", audit_pages, "http://fake.test"

    # The same two methods as the script's Http.
    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body=None):
        return self.request("POST", path, body=body)

    def request(self, method, path, body=None, params=None):
        self.calls.append((method, path, body if method == "POST" else params, self.token if method == "POST" else None))
        if (method, path) in self.refuse:
            raise self.refuse[(method, path)]
        if method == "GET" and path.startswith("/cases/") and path != "/cases/queue":
            return self.case_detail(path[len("/cases/"):])
        return getattr(self, method.lower() + path.replace("/", "_"))(body if method == "POST" else params)

    def case_detail(self, case_id):
        found = next((c for c in self.cases if c["case_id"] == case_id), None)
        if found is None:
            raise demo.ApiError(404, "Case not found")
        return {"case_id": case_id, "shipment_id": found["shipment_id"], "workflow_state": found["workflow_state"],
                "diagnosis": {"summary": f"What was found for {found['shipment_id']}."}, "session_id": self.session_id}

    def get_audit(self, params):
        assert params["limit"] == 100 and params["case_id"]
        events = [{"event_type": kind, "case_id": params["case_id"], "sequence": i}
                  for i, kind in enumerate(("CASE_OPENED", "CASE_CLAIMED", "RECOMMENDATION_READY", "AUTHORITY_DECISION"))]
        start = int(params.get("cursor") or 0)
        end = start + self.audit_pages
        return {"items": events[start:end], "next_cursor": str(end) if end < len(events) else None}

    def get_operations_session(self, _):
        return {"token": "TOKEN-1", "actor_id": "SYN-OPERATOR-LOCAL", "role": "operator", "scope": ["simulation_control"]}

    def status(self):
        return {"as_of": self.clock.isoformat(),
                "worker": {"state": self.worker, "active_case_id": next((c["case_id"] for c in self.cases if c["workflow_state"] == "INVESTIGATING"), None)},
                "session": {"monitor_pending": self.monitor_pending, "session_id": self.session_id},
                "simulator": {"state": self.simulator, "speed": self.speed, "end_at": END.isoformat()},
                "development_reset": {"enabled": self.reset_enabled, "confirmation": self.confirmation if self.reset_enabled else None}}

    def get_simulation_status(self, _):
        if self.simulator == "running" and not self.frozen:
            self.clock = min(self.clock + timedelta(seconds=self.stride * self.speed), END)
            for case in [c for c in self.seed if datetime.fromisoformat(c["opened_at"]) <= self.clock and c not in self.cases]:
                self.cases.append(case)
        elif self.worker == "running":
            # The worker investigates one case at a time: OPEN -> INVESTIGATING -> its final state, a poll each.
            current = next((c for c in self.cases if c["workflow_state"] == "INVESTIGATING"), None)
            if current:
                current["polls"] = current.get("polls", 0) + 1
                if current["polls"] >= self.investigations:
                    current["workflow_state"] = current["final"]
            else:
                waiting = next((c for c in self.cases if c["workflow_state"] in ("OPEN", "REOPENED")), None)
                if waiting:
                    waiting["workflow_state"] = "INVESTIGATING"
        return self.status()

    def post_simulation_reset(self, body):
        if not self.reset_enabled:
            raise demo.ApiError(409, "Development reset is disabled.")
        if body != {"confirmation": self.confirmation}:
            raise demo.ApiError(409, "Development reset needs the confirmation for the current session")
        self.clock, self.simulator, self.worker, self.cases = START, "paused", "paused", []
        self.confirmation, self.session_id = "RESET-SESSION-2", "DEMO-SESSION-0008"
        return {"reset": True}

    def post_worker_start(self, body):
        assert body is None
        self.worker = "running"
        return self.status()

    def post_simulation_start(self, body):
        assert set(body) == {"speed", "replay_mode"} and body["replay_mode"] == "timeline"
        if body["speed"] not in (1, 10, 60, 300, 600, 3600):
            raise demo.ApiError(422, "speed")
        self.simulator, self.speed = "running", body["speed"]
        return self.status()

    def post_simulation_pause(self, body):
        assert body is None
        self.simulator = "paused"
        return self.status()

    def get_cases_queue(self, params):
        assert params["scope"] == "all" and params["limit"] == 100
        start = int(params.get("cursor") or 0)
        rows = [{k: c[k] for k in ("case_id", "shipment_id", "workflow_state")} for c in self.cases]
        end = start + self.pages
        return {"items": rows[start:end], "next_cursor": str(end) if end < len(rows) else None}


def case(number, opened_at, final="AWAITING_APPROVAL"):
    return {"case_id": f"SYN-CASE-{number:06d}", "shipment_id": f"SYN-SHP-{number:06d}", "workflow_state": "OPEN",
            "opened_at": opened_at, "final": final}


CASES = (case(104, "2026-09-14T06:00:00+00:00"), case(165, "2026-09-15T02:00:00+00:00", "HUMAN_REVIEW"),
         case(359, "2026-09-15T13:00:00+00:00", "AWAITING_OUTCOME"),
         case(232, "2026-09-16T09:00:00+00:00"))          # opens after --live-from: not part of the pre-roll


class Run:
    def __init__(self, backend, *argv):
        self.backend, self.lines, self.slept = backend, [], []
        self.ticks = 0
        self.directory = tempfile.TemporaryDirectory()          # every test run exports here, never into the repository
        self.archive = pathlib.Path(self.directory.name) / "sessions"
        self.args = demo.parse(["--live-from", LIVE_FROM, "--archive-dir", str(self.archive), *argv])

    def exports(self):
        return sorted(self.archive.glob("*.json")) if self.archive.exists() else []

    def clock(self):
        self.ticks += 1
        return float(self.ticks)

    def go(self):
        return demo.run(self.backend, self.args, say=self.lines.append, sleep=self.slept.append, clock=self.clock)

    def posts(self):
        return [(path, body) for method, path, body, _ in self.backend.calls if method == "POST"]


class SequenceTests(unittest.TestCase):
    def test_the_whole_sequence_in_order(self):
        backend = FakeBackend(cases=CASES)
        run = Run(backend)
        result = run.go()
        self.assertEqual(run.posts(), [
            ("/simulation/reset", {"confirmation": "RESET-SESSION-1"}),
            ("/worker/start", None),
            ("/simulation/start", {"speed": 600, "replay_mode": "timeline"}),
            ("/simulation/pause", None),
            ("/simulation/start", {"speed": 600, "replay_mode": "timeline"})])
        # The session comes first and its token is on every POST (and only there).
        self.assertEqual(backend.calls[0][:2], ("GET", "/operations/session"))
        self.assertEqual({token for method, _, _, token in backend.calls if method == "POST"}, {"TOKEN-1"})
        # The reset is confirmed with the confirmation read from the status just before it.
        # (Between the two, only the reads of the export of the session about to be reset.)
        reset_at = [c[:2] for c in backend.calls].index(("POST", "/simulation/reset"))
        self.assertEqual(backend.calls[1][:2], ("GET", "/simulation/status"))
        self.assertEqual({c[:2] for c in backend.calls[2:reset_at]}, {("GET", "/cases/queue")})
        self.assertEqual(len(run.exports()), 1)
        # The pre-roll paused at or just after --live-from; the live phase started from there.
        paused = next(line for line in run.lines if line.startswith("pre-roll paused"))
        at = datetime.fromisoformat(paused.split("clock at ")[1])
        self.assertGreaterEqual(at, datetime.fromisoformat(LIVE_FROM))
        self.assertLess(at - datetime.fromisoformat(LIVE_FROM), timedelta(minutes=10))
        # The worker caught up before the queue was printed and before the live phase.
        self.assertEqual({c["workflow_state"] for c in result["cases"]}, {"AWAITING_APPROVAL", "HUMAN_REVIEW", "AWAITING_OUTCOME"})
        self.assertEqual(len(result["cases"]), 3)                # the case that opens after --live-from is not there yet
        text = "\n".join(run.lines)
        self.assertIn("shipment        case id          state", text)
        self.assertIn("SYN-SHP-000104  SYN-CASE-000104  AWAITING_APPROVAL", text)
        self.assertIn("SYN-SHP-000165  SYN-CASE-000165  HUMAN_REVIEW", text)
        self.assertIn("SYN-SHP-000359  SYN-CASE-000359  AWAITING_OUTCOME", text)
        order = [next(i for i, line in enumerate(run.lines) if line.startswith(prefix)) for prefix in
                 ("session reset", "investigation worker started", "pre-roll at speed 600", "pre-roll paused", "worker has caught up",
                  "shipment", "LIVE at speed 600", "live phase started at")]
        self.assertEqual(order, sorted(order))
        self.assertIsNotNone(result["live_started_at"].tzinfo)
        self.assertIn("UTC)", run.lines[-1])
        self.assertEqual((backend.simulator, backend.speed, backend.worker), ("running", 600, "running"))

    def test_no_live_stops_after_the_pre_roll(self):
        backend = FakeBackend(cases=CASES)
        run = Run(backend, "--no-live")
        result = run.go()
        self.assertEqual([path for path, _ in run.posts()], ["/simulation/reset", "/worker/start", "/simulation/start", "/simulation/pause"])
        self.assertIsNone(result["live_started_at"])
        self.assertEqual(backend.simulator, "paused")
        self.assertTrue(run.lines[-1].startswith("--no-live"))
        self.assertFalse(any(line.startswith("LIVE") for line in run.lines))

    def test_the_speeds_are_passed_on(self):
        backend = FakeBackend()
        run = Run(backend, "--preroll-speed", "300", "--live-speed", "300")
        run.go()
        self.assertEqual([body["speed"] for path, body in run.posts() if path == "/simulation/start"], [300, 300])
        self.assertIn("queue: no cases", run.lines)

    def test_the_queue_is_read_to_its_last_page(self):
        backend = FakeBackend(cases=CASES, pages=2)
        run = Run(backend, "--no-live")
        self.assertEqual(len(run.go()["cases"]), 3)
        self.assertTrue(any(method == "GET" and path == "/cases/queue" and params.get("cursor") == "2" for method, path, params, _ in backend.calls))

    def test_it_waits_while_the_monitor_still_has_shipments_to_check(self):
        backend = FakeBackend()
        backend.monitor_pending = 4
        run = Run(backend, "--no-live")
        def sleep(seconds):
            run.slept.append(seconds)
            if backend.simulator == "paused":
                backend.monitor_pending = max(backend.monitor_pending - 2, 0)
        demo.run(backend, run.args, say=run.lines.append, sleep=sleep, clock=run.clock)
        self.assertIn("waiting for the worker: 0 case(s) open or investigating, 4 shipment(s) still to be checked by the monitor", run.lines)
        self.assertEqual(backend.monitor_pending, 0)


class RefusalTests(unittest.TestCase):
    def failed(self, backend, *argv):
        run = Run(backend, *argv)
        with self.assertRaises(demo.Failed) as raised:
            run.go()
        return str(raised.exception), run

    def test_a_backend_without_the_reset_flag_fails_clearly_and_changes_nothing(self):
        message, run = self.failed(FakeBackend(reset_enabled=False))
        self.assertIn("SUHAIL_DEV_RESET=1", message)
        self.assertIn("nothing was changed", message)
        self.assertEqual(run.posts(), [])

    def test_a_refused_reset_says_why_and_stops(self):
        backend = FakeBackend()
        backend.refuse[("POST", "/simulation/reset")] = demo.ApiError(409, "Development reset refused: investigation worker active.")
        message, run = self.failed(backend)
        self.assertIn("HTTP 409", message); self.assertIn("investigation worker active", message)
        self.assertEqual([path for path, _ in run.posts()], ["/simulation/reset"])

    def test_live_from_outside_the_world_is_refused(self):
        message, run = self.failed(FakeBackend(), "--live-from", "2027-01-01T00:00:00+00:00")
        self.assertIn("after the end of this world", message)
        self.assertEqual(run.posts(), [])
        message, run = self.failed(FakeBackend(), "--live-from", "2026-09-01T00:00:00+00:00")
        self.assertIn("not after the start of this world", message)
        self.assertEqual([path for path, _ in run.posts()], ["/simulation/reset"])       # nothing was started

    def test_a_clock_that_does_not_move_pauses_and_fails(self):
        backend = FakeBackend()
        backend.frozen = True
        message, run = self.failed(backend)
        self.assertIn("has not moved", message)
        self.assertEqual(run.posts()[-1], ("/simulation/pause", None))
        self.assertEqual(backend.simulator, "paused")

    def test_a_simulation_paused_by_someone_else_fails(self):
        backend = FakeBackend()
        run = Run(backend)
        def sleep(seconds):
            backend.simulator = "paused"
        with self.assertRaises(demo.Failed) as raised:
            demo.run(backend, run.args, say=run.lines.append, sleep=sleep, clock=run.clock)
        self.assertIn("stopped running during the pre-roll", str(raised.exception))

    def test_a_worker_that_never_catches_up_times_out_with_the_simulation_paused(self):
        backend = FakeBackend(cases=CASES, investigations=10 ** 9)
        message, run = self.failed(backend, "--catchup-timeout", "50")
        self.assertIn("did not catch up within 50 s", message)
        self.assertEqual(backend.simulator, "paused")
        self.assertNotIn(("/simulation/start", {"speed": 600, "replay_mode": "timeline"}), run.posts()[3:])   # never went live

    def test_a_paused_worker_with_open_cases_fails(self):
        backend = FakeBackend(cases=CASES)
        run = Run(backend)
        def sleep(seconds):
            if backend.simulator == "paused":
                backend.worker = "paused"
        with self.assertRaises(demo.Failed) as raised:
            demo.run(backend, run.args, say=run.lines.append, sleep=sleep, clock=run.clock)
        self.assertIn("investigation worker is not running", str(raised.exception))

    def test_a_refused_api_call_names_the_step(self):
        backend = FakeBackend()
        backend.refuse[("POST", "/worker/start")] = demo.ApiError(403, "A local operations session is required")
        message, _ = self.failed(backend)
        self.assertEqual(message, "starting the investigation worker was refused (POST /worker/start: HTTP 403): "
                                  "A local operations session is required")


def used_session(*, states=("AWAITING_APPROVAL", "HUMAN_REVIEW", "RESOLVED"), **options):
    """A backend whose current session already holds investigated cases (what a reset would delete)."""
    backend = FakeBackend(**options)
    backend.cases = [{**case(200 + i, "2026-09-14T06:00:00+00:00"), "workflow_state": state} for i, state in enumerate(states)]
    return backend


class ArchiveTests(unittest.TestCase):
    """Before any reset the current session's cases are exported; a failed export means no reset."""

    def test_the_session_is_exported_before_the_reset_with_every_case_its_detail_and_its_audit(self):
        backend = used_session(cases=CASES, audit_pages=3)
        run = Run(backend)
        result = run.go()
        (path,) = run.exports()
        self.assertEqual(result["archive"], path)
        # The name carries the session id and a UTC timestamp; the session is the one that was reset, not the new one.
        self.assertRegex(path.name, r"^session_DEMO-SESSION-0007_\d{8}T\d{6}Z\.json$")
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((document["schema"], document["session_id"], document["case_count"], document["origin"]),
                         ("demo-session-export-1", "DEMO-SESSION-0007", 3, "http://fake.test"))
        self.assertEqual(document["status"]["session"]["session_id"], "DEMO-SESSION-0007")
        self.assertEqual([row["case_id"] for row in document["queue"]], ["SYN-CASE-000200", "SYN-CASE-000201", "SYN-CASE-000202"])
        self.assertEqual([row["workflow_state"] for row in document["queue"]], ["AWAITING_APPROVAL", "HUMAN_REVIEW", "RESOLVED"])
        for row, exported in zip(document["queue"], document["cases"]):
            self.assertEqual(exported["case_id"], row["case_id"])
            self.assertEqual(exported["detail"]["diagnosis"]["summary"], f"What was found for {row['shipment_id']}.")
            self.assertEqual([e["event_type"] for e in exported["audit"]],                       # both audit pages
                             ["CASE_OPENED", "CASE_CLAIMED", "RECOMMENDATION_READY", "AUTHORITY_DECISION"])
            self.assertEqual({e["case_id"] for e in exported["audit"]}, {row["case_id"]})
        # Every read of the export came before the reset, and the export only reads.
        calls = [(method, path) for method, path, _, _ in backend.calls]
        reset_at = calls.index(("POST", "/simulation/reset"))
        before = calls[:reset_at]
        self.assertEqual([c for c in before if c[0] == "POST"], [])
        for expected in (("GET", "/cases/queue"), ("GET", "/cases/SYN-CASE-000200"), ("GET", "/cases/SYN-CASE-000202"), ("GET", "/audit")):
            self.assertIn(expected, before)
        self.assertEqual(sum(1 for c in before if c == ("GET", "/audit")), 6)                # three cases, two pages each
        said = [i for i, line in enumerate(run.lines) if line.startswith(("session DEMO-SESSION-0007 exported: 3 case(s) to", "session reset"))]
        self.assertEqual(len(said), 2)
        self.assertLess(said[0], said[1])
        self.assertEqual(backend.session_id, "DEMO-SESSION-0008")                             # and then the reset did happen
        self.assertFalse(list(run.archive.glob("*.tmp")))

    def test_a_failed_export_refuses_the_reset(self):
        for what, arrange in (
                ("a case cannot be read", lambda b, r: b.refuse.update({("GET", "/cases/SYN-CASE-000201"): demo.ApiError(500, "read model failed")})),
                ("the audit cannot be read", lambda b, r: b.refuse.update({("GET", "/audit"): demo.ApiError(503, "unavailable")})),
                ("the queue cannot be read", lambda b, r: b.refuse.update({("GET", "/cases/queue"): demo.ApiError(500, "boom")})),
                ("the directory cannot be written", lambda b, r: (r.archive.parent.mkdir(exist_ok=True), r.archive.write_text("a file, not a directory"))),
        ):
            with self.subTest(what):
                backend = used_session()
                run = Run(backend)
                arrange(backend, run)
                with self.assertRaises(demo.Failed) as raised:
                    run.go()
                message = str(raised.exception)
                self.assertIn("the export of the current session failed", message)
                self.assertIn("The session was NOT reset", message)
                self.assertIn("--no-archive", message)
                self.assertEqual(run.posts(), [])                                         # no reset, nothing started
                self.assertEqual((backend.session_id, len(backend.cases)), ("DEMO-SESSION-0007", 3))
                self.assertEqual(run.exports() if run.archive.is_dir() else [], [])      # no partial file under an export's name

    def test_a_file_that_does_not_read_back_refuses_the_reset(self):
        from unittest import mock
        backend = used_session()
        run = Run(backend)
        with mock.patch.object(demo.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(demo.Failed) as raised:
                run.go()
        self.assertIn("the export of the current session failed (PermissionError", str(raised.exception))
        self.assertEqual(run.posts(), [])
        self.assertEqual(run.exports(), [])

    def test_no_archive_must_be_given_explicitly_and_then_resets_without_an_export(self):
        self.assertFalse(demo.parse(["--live-from", LIVE_FROM]).no_archive)
        self.assertTrue(str(demo.parse(["--live-from", LIVE_FROM]).archive_dir).replace("\\", "/").endswith("artifacts/demo/sessions"))
        self.assertEqual(pathlib.Path(demo.parse(["--live-from", LIVE_FROM]).archive_dir), ROOT / "artifacts" / "demo" / "sessions")
        backend = used_session()
        backend.refuse[("GET", "/audit")] = demo.ApiError(503, "unavailable")       # an export would fail; none is attempted
        run = Run(backend, "--no-archive", "--no-live")
        result = run.go()
        self.assertEqual(run.posts()[0], ("/simulation/reset", {"confirmation": "RESET-SESSION-1"}))
        self.assertEqual((run.exports(), result["archive"]), ([], None))
        self.assertIn("--no-archive: the current session is reset without an export", run.lines)
        self.assertFalse([c for c in backend.calls if c[1].startswith("/cases/SYN") or c[1] == "/audit"])

    def test_a_refusal_that_changes_nothing_writes_no_export_either(self):
        backend = used_session(reset_enabled=False)
        run = Run(backend)
        with self.assertRaises(demo.Failed):
            run.go()
        self.assertEqual((run.posts(), run.exports()), ([], []))

    def test_an_empty_session_is_exported_too_and_an_earlier_export_is_never_overwritten(self):
        from datetime import datetime as real
        backend = FakeBackend()
        lines = []
        at = real(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            first = demo.export_session(backend, directory, lines.append, wall=lambda: at)
            second = demo.export_session(backend, directory, lines.append, wall=lambda: at)
            self.assertEqual((first.name, second.name), ("session_DEMO-SESSION-0007_20261011T120000Z.json", "session_DEMO-SESSION-0007_20261011T120000Z_2.json"))
            self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["cases"], [])
            backend.session_id = None
            self.assertEqual(demo.export_session(backend, directory, lines.append, wall=lambda: at).name, "session_no-session_20261011T120000Z.json")
        self.assertEqual(demo.archive_name("a/b\\c:..", at), "session_a_b_c_20261011T120000Z.json")

    def test_export_only_writes_the_export_and_resets_nothing(self):
        backend = used_session()
        with tempfile.TemporaryDirectory() as directory:
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = demo.main(["--export-only", "--archive-dir", directory], api=backend)      # no --live-from needed
            self.assertEqual((code, stderr.getvalue()), (0, ""))
            (path,) = sorted(pathlib.Path(directory).glob("*.json"))
            self.assertRegex(path.name, r"^session_DEMO-SESSION-0007_\d{8}T\d{6}Z\.json$")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["case_count"], 3)
            self.assertIn("exported: 3 case(s)", stdout.getvalue())
        self.assertEqual([c for c in backend.calls if c[0] == "POST"], [])                   # nothing reset, nothing started
        self.assertEqual((backend.session_id, len(backend.cases), backend.simulator, backend.worker), ("DEMO-SESSION-0007", 3, "paused", "paused"))
        self.assertEqual(backend.calls[0][:2], ("GET", "/operations/session"))
        # A failed export-only run says so and exits 2.
        backend.refuse[("GET", "/cases/queue")] = demo.ApiError(500, "boom")
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(demo.main(["--export-only", "--archive-dir", directory], api=backend), 2)
            self.assertIn("FAILED: the export of the current session failed", stderr.getvalue())
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])


class CommandLineTests(unittest.TestCase):
    def parse_error(self, *argv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            demo.parse(list(argv))
        self.assertEqual(raised.exception.code, 2)
        return stderr.getvalue()

    def test_defaults(self):
        args = demo.parse(["--live-from", LIVE_FROM])
        self.assertEqual((args.origin, args.preroll_speed, args.live_speed, args.no_live),
                         ("http://127.0.0.1:8020", 600, 600, False))
        self.assertEqual(args.live_from, datetime(2026, 9, 15, 13, 30, tzinfo=timezone.utc))
        self.assertEqual(demo.parse(["--live-from", "2026-09-15T13:30:00Z"]).live_from, args.live_from)

    def test_refused_arguments(self):
        self.assertIn("--live-from is required (unless --export-only)", self.parse_error())
        self.assertIn("contradict", self.parse_error("--export-only", "--no-archive"))
        self.assertIn("a pre-roll above 600 is not allowed", self.parse_error("--live-from", LIVE_FROM, "--preroll-speed", "3600"))
        self.assertIn("the backend accepts", self.parse_error("--live-from", LIVE_FROM, "--preroll-speed", "120"))
        self.assertIn("invalid choice", self.parse_error("--live-from", LIVE_FROM, "--live-speed", "60"))
        self.assertIn("needs a UTC offset", self.parse_error("--live-from", "2026-09-15T13:30:00"))
        self.assertIn("not an ISO time", self.parse_error("--live-from", "tomorrow"))

    def test_main_reports_a_failure_and_exits_2(self):
        stderr, stdout = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            code = demo.main(["--live-from", LIVE_FROM], api=FakeBackend(reset_enabled=False))
        self.assertEqual(code, 2)
        self.assertTrue(stderr.getvalue().startswith("FAILED: the backend refuses a session reset"))


class BoundaryTests(unittest.TestCase):
    def test_the_script_is_http_only(self):
        source = SCRIPT.read_text(encoding="utf-8")
        imports = [line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))]
        self.assertEqual(sorted(set(imports)), ["argparse", "datetime", "json", "os", "pathlib", "re", "sys", "time", "urllib"])
        for forbidden in ("neo4j", "operations.", "sys.path", "bolt://", "OperationsStore", "truth"):
            self.assertNotIn(forbidden, source)

    def test_the_http_layer_sends_the_token_on_posts_only_and_reads_error_details(self):
        import urllib.error
        from unittest import mock
        sent = []

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): return False

        def urlopen(request, timeout):
            sent.append((request.get_method(), request.full_url, dict(request.header_items()), request.data))
            if request.full_url.endswith("/simulation/reset"):
                raise urllib.error.HTTPError(request.full_url, 409, "Conflict", {}, io.BytesIO(b'{"detail":"Development reset is disabled."}'))
            return Response(b'{"ok": true}')

        api = demo.Http("http://127.0.0.1:8020/")
        api.token = "TOKEN-1"
        with mock.patch.object(demo.urllib.request, "urlopen", urlopen):
            self.assertEqual(api.get("/cases/queue", params={"scope": "all", "limit": 100}), {"ok": True})
            self.assertEqual(api.post("/simulation/start", body={"speed": 600, "replay_mode": "timeline"}), {"ok": True})
            self.assertEqual(api.post("/worker/start"), {"ok": True})
            with self.assertRaises(demo.ApiError) as raised:
                api.post("/simulation/reset", body={"confirmation": "x"})
        self.assertEqual((raised.exception.status, raised.exception.detail), (409, "Development reset is disabled."))
        self.assertEqual(sent[0][:2], ("GET", "http://127.0.0.1:8020/cases/queue?scope=all&limit=100"))
        self.assertNotIn("X-operations-token", sent[0][2])
        self.assertEqual((sent[1][2]["X-operations-token"], sent[1][3]), ("TOKEN-1", b'{"speed": 600, "replay_mode": "timeline"}'))
        self.assertEqual(sent[2][3], b"")                       # a POST with no body sends none
        with mock.patch.object(demo.urllib.request, "urlopen", side_effect=urllib.error.URLError("connection refused")):
            with self.assertRaises(demo.Failed) as raised:
                api.get("/operations/session")
        self.assertIn("no backend answered at http://127.0.0.1:8020", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
