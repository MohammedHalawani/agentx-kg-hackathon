"""scripts/world_demo_session.py against a fake HTTP layer: the order of the calls, the refusals and what is printed.

No backend, no database, no model: FakeBackend answers the same paths the script calls and keeps a small state (clock,
simulator, worker, cases) so the polling loops behave as against a real one.
"""
import contextlib
import importlib.util
import io
import pathlib
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

    def __init__(self, *, reset_enabled=True, cases=(), investigations=2, stride_seconds=1.0, pages=100):
        self.token, self.calls = None, []
        self.reset_enabled, self.confirmation = reset_enabled, "RESET-SESSION-1"
        self.clock = START + timedelta(days=3)          # a used session: the reset puts it back to START
        self.simulator, self.speed, self.worker = "paused", 1, "paused"
        self.seed = [dict(c) for c in cases]            # opened by the monitor once the clock passes their opened_at
        self.cases, self.investigations, self.stride, self.pages = [], investigations, stride_seconds, pages
        self.monitor_pending = 0
        self.refuse = {}                                # (method, path) -> ApiError
        self.frozen = False

    # The same two methods as the script's Http.
    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body=None):
        return self.request("POST", path, body=body)

    def request(self, method, path, body=None, params=None):
        self.calls.append((method, path, body if method == "POST" else params, self.token if method == "POST" else None))
        if (method, path) in self.refuse:
            raise self.refuse[(method, path)]
        return getattr(self, method.lower() + path.replace("/", "_"))(body if method == "POST" else params)

    def get_operations_session(self, _):
        return {"token": "TOKEN-1", "actor_id": "SYN-OPERATOR-LOCAL", "role": "operator", "scope": ["simulation_control"]}

    def status(self):
        return {"as_of": self.clock.isoformat(),
                "worker": {"state": self.worker, "active_case_id": next((c["case_id"] for c in self.cases if c["workflow_state"] == "INVESTIGATING"), None)},
                "session": {"monitor_pending": self.monitor_pending},
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
        self.confirmation = "RESET-SESSION-2"
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
        self.args = demo.parse(["--live-from", LIVE_FROM, *argv])

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
        self.assertEqual([c[:2] for c in backend.calls[1:3]], [("GET", "/simulation/status"), ("POST", "/simulation/reset")])
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
        self.assertIn("--live-from", self.parse_error())
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
        self.assertEqual(sorted(set(imports)), ["argparse", "datetime", "json", "sys", "time", "urllib"])
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
