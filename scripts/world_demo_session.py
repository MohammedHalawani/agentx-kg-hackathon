"""Seed a live demo session on a RUNNING backend, over HTTP only.

  cd chat
  uv run python ../scripts/world_demo_session.py --live-from 2026-09-15T13:30:00+00:00
        [--origin http://127.0.0.1:8020] [--preroll-speed 600] [--live-speed 600|300|60|10] [--no-live]
        [--archive-dir artifacts/demo/sessions] [--no-archive]
  uv run python ../scripts/world_demo_session.py --export-only [--archive-dir DIR]

What it does, in order (every step is an ordinary call of the operations API, as the UI would make it):
1. GET  /operations/session            the local operator token (sent as X-Operations-Token on every POST).
2. GET  /simulation/status, then the EXPORT of the current session, then POST /simulation/reset with
   status.development_reset.confirmation. The backend must have been started with SUHAIL_DEV_RESET=1; otherwise the
   script stops here and says so. The reset deletes that backend's operations ledger (cases, runs, decisions) and
   puts the clock back to the start of the world, so before it the current session's cases are written to a file:
   the queue (GET /cases/queue?scope=all, every page), and for each case GET /cases/{id} and its audit trail
   (GET /audit?case_id=..., every page). The file is <archive dir>/session_<session id>_<UTC time>.json, the archive
   directory being --archive-dir (default artifacts/demo/sessions under the repository root). If the export fails
   for any reason the session is NOT reset and the script stops. --no-archive skips the export, and must be given
   explicitly. --export-only writes the export and does nothing else (no reset, nothing started; --live-from is
   not needed).
3. POST /worker/start                  automatic investigation of the open cases, oldest first.
4. Pre-roll: POST /simulation/start at --preroll-speed (default 600, never above 600), then GET /simulation/status is
   polled until the clock (as_of) reaches --live-from, then POST /simulation/pause. The clock is advanced by the
   backend's ingestion worker in steps, so it stops a little after --live-from (the pause time is printed).
5. Waits until the worker has caught up: no case in GET /cases/queue?scope=all is OPEN, REOPENED or INVESTIGATING, the
   monitor has nothing pending and the worker holds no case.
6. Prints the queue: shipment, case id, state.
7. Unless --no-live: POST /simulation/start at --live-speed (10, 60, 300 or 600, default 600) and prints the wall-clock time
   the live phase started.

This script talks to the backend and to nothing else. It imports no project module, opens no database and makes no
model call itself; the backend's worker makes the model calls of the cases it investigates during the pre-roll, under
that backend's own settings (SUHAIL_MODEL_CALL_CAP, SUHAIL_DEMO_SHIPMENTS, ...). See docs/api/demo-lifecycle.md.

Exit status: 0 done; 2 a refused or failed step (the message says which and why).
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DEFAULT_ORIGIN = "http://127.0.0.1:8020"
TOKEN_HEADER = "X-Operations-Token"
MAX_PREROLL_SPEED = 600
PREROLL_SPEEDS = (1, 10, 60, 300, 600)
LIVE_SPEEDS = (10, 60, 300, 600)   # 10 and 60 for a manual walkthrough: an answer due in an hour arrives in minutes, and the world lasts hours
PENDING_STATES = ("OPEN", "REOPENED", "INVESTIGATING")   # waiting for, or in, an investigation
PAGE = 100
ARCHIVE_SCHEMA = "demo-session-export-1"
DEFAULT_ARCHIVE_DIR = pathlib.Path(__file__).resolve().parents[1] / "artifacts" / "demo" / "sessions"


class Failed(Exception):
    """A step that was refused or could not be completed; the text is what the operator is told."""


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


class Http:
    """The backend's HTTP API. The only thing this script talks to."""

    def __init__(self, origin, timeout=60):
        self.origin, self.timeout, self.token = origin.rstrip("/"), timeout, None

    def request(self, method, path, body=None, params=None):
        url = self.origin + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Accept": "application/json"}
        data = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            if self.token:
                headers[TOKEN_HEADER] = self.token
            data = json.dumps(body).encode("utf-8") if body is not None else b""
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(text).get("detail", text)
            except (ValueError, AttributeError):
                detail = text
            raise ApiError(error.code, detail) from None
        except (urllib.error.URLError, OSError) as error:
            raise Failed(f"no backend answered at {self.origin} ({getattr(error, 'reason', error)}). Start it first; this script "
                         "never starts one.") from None

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body=None):
        return self.request("POST", path, body=body)


def instant(text):
    """An ISO time with an offset, as an aware datetime."""
    value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("the time needs a UTC offset, for example 2026-09-15T13:30:00+00:00")
    return value


def step(api, method, path, what, **arguments):
    """One API call; a refusal becomes a Failed that names the step."""
    try:
        return getattr(api, method)(path, **arguments)
    except ApiError as error:
        raise Failed(f"{what} was refused ({method.upper()} {path}: HTTP {error.status}): {error.detail}") from None


def open_session(api):
    session = step(api, "get", "/operations/session", "the operations session")
    token = (session or {}).get("token")
    if not token:
        raise Failed("GET /operations/session returned no token")
    api.token = token
    return session


def queue(api):
    """Every case of GET /cases/queue?scope=all, all pages."""
    items, cursor = [], None
    while True:
        params = {"scope": "all", "limit": PAGE, **({"cursor": cursor} if cursor else {})}
        page = step(api, "get", "/cases/queue", "reading the queue", params=params)
        items.extend(page.get("items") or [])
        cursor = page.get("next_cursor")
        if not cursor:
            return items


def audit_trail(api, case_id):
    """Every audit entry of one case (GET /audit?case_id=...), all pages."""
    items, cursor = [], None
    while True:
        params = {"case_id": case_id, "limit": PAGE, **({"cursor": cursor} if cursor else {})}
        page = step(api, "get", "/audit", f"reading the audit trail of {case_id}", params=params)
        items.extend(page.get("items") or [])
        cursor = page.get("next_cursor")
        if not cursor:
            return items


def archive_name(session_id, at):
    """session_<session id>_<UTC time>.json: the session id as the backend gives it (unsafe characters replaced)."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(session_id or "")).strip("._") or "no-session"
    return f"session_{safe}_{at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"


def export_session(api, archive_dir, say, *, status=None, wall=lambda: datetime.now(timezone.utc)):
    """Write the current session's cases to a file and return its path: the status, the queue, and for each case its
    detail (GET /cases/{id}) and its audit trail. Reads only. Any failure (a refused or failed call, a case that
    cannot be read, a file that cannot be written or does not read back whole) is a Failed: no partial file is left
    under the final name, and the caller must not reset."""
    try:
        status = status or step(api, "get", "/simulation/status", "reading the status")
        session_id = (status.get("session") or {}).get("session_id")
        listed = queue(api)
        cases = []
        for row in listed:
            case_id = row.get("case_id")
            if not case_id:
                raise Failed("a queue row has no case_id")
            detail = step(api, "get", "/cases/" + urllib.parse.quote(str(case_id), safe=""), f"reading case {case_id}")
            cases.append({"case_id": case_id, "detail": detail, "audit": audit_trail(api, case_id)})
        at = wall()
        document = {"schema": ARCHIVE_SCHEMA, "exported_at": at.astimezone(timezone.utc).isoformat(timespec="seconds"),
                    "origin": getattr(api, "origin", None), "session_id": session_id, "status": status,
                    "case_count": len(cases), "queue": listed, "cases": cases}
        directory = pathlib.Path(archive_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / archive_name(session_id, at)
        number = 1
        while path.exists():                      # never over an earlier export
            number += 1
            path = directory / archive_name(session_id, at).replace(".json", f"_{number}.json")
        temporary = path.with_name(path.name + ".tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        written = json.loads(temporary.read_text(encoding="utf-8"))
        if written.get("case_count") != len(cases) or len(written.get("cases") or []) != len(cases):
            raise Failed("the export did not read back whole")
        os.replace(temporary, path)
    except Failed as error:
        raise Failed(f"the export of the current session failed: {error}") from None
    except (OSError, ValueError, TypeError, AttributeError) as error:
        raise Failed(f"the export of the current session failed ({type(error).__name__}: {error})") from None
    say(f"session {session_id or '(none)'} exported: {len(cases)} case(s) to {path}")
    return path


def reset(api, live_from, say, *, archive=None):
    """archive(status): called after every refusal that changes nothing and immediately before the reset is posted;
    if it raises, nothing is reset."""
    status = step(api, "get", "/simulation/status", "reading the status")
    development = status.get("development_reset") or {}
    if not development.get("enabled") or not development.get("confirmation"):
        raise Failed("the backend refuses a session reset: it was not started with SUHAIL_DEV_RESET=1 "
                     "(GET /simulation/status: development_reset.enabled is false). Restart it with that variable; nothing was changed.")
    end_at = (status.get("simulator") or {}).get("end_at")
    if end_at and live_from > instant(end_at):
        raise Failed(f"--live-from {live_from.isoformat()} is after the end of this world ({end_at}); nothing was changed.")
    if archive is not None:
        try:
            archive(status)
        except Failed as error:
            raise Failed(f"{error}. The session was NOT reset and nothing was changed. Fix the cause and run this again, or pass "
                         "--no-archive to reset without an export (the session's cases are then lost).") from None
    try:
        api.post("/simulation/reset", body={"confirmation": development["confirmation"]})
    except ApiError as error:
        raise Failed(f"the session reset was refused (POST /simulation/reset: HTTP {error.status}): {error.detail} "
                     "If an investigation is running, wait for it or pause the worker (POST /worker/pause), then run this again.") from None
    status = step(api, "get", "/simulation/status", "reading the status")
    if instant(status["as_of"]) >= live_from:
        raise Failed(f"--live-from {live_from.isoformat()} is not after the start of this world ({status['as_of']}); "
                     "the session was reset and is paused at the start.")
    say(f"session reset; clock at {status['as_of']}")
    return status


def preroll(api, live_from, speed, say, *, sleep=time.sleep, poll=1.0, stall=180.0, clock=time.monotonic):
    """Run the clock to live_from at `speed`, then pause. Returns the status after the pause."""
    step(api, "post", "/simulation/start", "starting the pre-roll", body={"speed": speed, "replay_mode": "timeline"})
    say(f"pre-roll at speed {speed} until {live_from.isoformat()}")
    seen, moved_at = None, clock()
    try:
        while True:
            status = step(api, "get", "/simulation/status", "reading the status")
            now = instant(status["as_of"])
            if now >= live_from:
                break
            simulator = status.get("simulator") or {}
            if simulator.get("end_at") and now >= instant(simulator["end_at"]):
                raise Failed(f"the world ended at {status['as_of']} before --live-from was reached")
            if str(simulator.get("state", "")).lower() != "running":
                raise Failed(f"the simulation stopped running during the pre-roll (state {simulator.get('state')!r} at {status['as_of']}); "
                             "something else paused it")
            if now != seen:
                seen, moved_at = now, clock()
            elif clock() - moved_at > stall:
                raise Failed(f"the clock has not moved from {status['as_of']} for {int(stall)} s; is the backend's ingestion worker running?")
            sleep(poll)
    except BaseException:
        # Whatever happened (a failure, Ctrl-C), do not leave the clock running at pre-roll speed.
        try:
            api.post("/simulation/pause")
        except (ApiError, Failed):
            pass
        raise
    step(api, "post", "/simulation/pause", "pausing the pre-roll")
    status = step(api, "get", "/simulation/status", "reading the status")
    say(f"pre-roll paused; clock at {status['as_of']}")
    return status


def wait_for_worker(api, say, *, sleep=time.sleep, poll=2.0, timeout=3600.0, clock=time.monotonic):
    """Until nothing waits for, or is in, an investigation. Returns the queue."""
    started, last = clock(), None
    while True:
        status = step(api, "get", "/simulation/status", "reading the status")
        cases = queue(api)
        pending = [c for c in cases if c.get("workflow_state") in PENDING_STATES]
        monitor = (status.get("session") or {}).get("monitor_pending") or 0
        active = (status.get("worker") or {}).get("active_case_id")
        if not pending and not monitor and not active:
            say(f"worker has caught up: {len(cases)} case(s), none waiting for investigation")
            return cases
        if str((status.get("worker") or {}).get("state", "")).lower() != "running":
            raise Failed(f"the investigation worker is not running (state {(status.get('worker') or {}).get('state')!r}) "
                         f"while {len(pending)} case(s) wait; something else paused it")
        progress = (len(pending), monitor)
        if progress != last:
            say(f"waiting for the worker: {len(pending)} case(s) open or investigating, {monitor} shipment(s) still to be checked by the monitor")
            last = progress
        if clock() - started > timeout:
            raise Failed(f"the worker did not catch up within {int(timeout)} s: {len(pending)} case(s) still open or investigating. "
                         "The simulation is paused; nothing else was changed.")
        sleep(poll)


def queue_lines(cases):
    rows = sorted(((str(c.get("shipment_id")), str(c.get("case_id")), str(c.get("workflow_state"))) for c in cases))
    if not rows:
        return ["queue: no cases"]
    widths = [max(len(r[i]) for r in [("shipment", "case id", "state"), *rows]) for i in range(3)]
    line = lambda r: "  ".join(value.ljust(widths[i]) for i, value in enumerate(r)).rstrip()
    return [line(("shipment", "case id", "state")), *map(line, rows)]


def go_live(api, speed, say, *, wall=lambda: datetime.now(timezone.utc)):
    status = step(api, "post", "/simulation/start", "starting the live phase", body={"speed": speed, "replay_mode": "timeline"})
    started = wall()
    say(f"LIVE at speed {speed} from simulation time {(status or {}).get('as_of')}")
    say(f"live phase started at {started.astimezone().isoformat(timespec='seconds')} local "
        f"({started.astimezone(timezone.utc).isoformat(timespec='seconds')} UTC)")
    return started


def run(api, args, say=print, **timing):
    """The whole sequence. `timing` (sleep, clock) is for tests."""
    live_from = args.live_from
    open_session(api)
    if args.export_only:
        return {"cases": None, "live_started_at": None, "archive": export_session(api, args.archive_dir, say)}
    exported = {}
    if args.no_archive:
        say("--no-archive: the current session is reset without an export")
        archive = None
    else:
        archive = lambda status: exported.update(path=export_session(api, args.archive_dir, say, status=status))
    reset(api, live_from, say, archive=archive)
    if args.manual:
        # Auto stays OFF: the worker is never started, so every case the monitor opens waits as OPEN until an operator
        # starts its investigation (POST /cases/{case_id}/investigate, the interface's own button).
        step(api, "post", "/worker/pause", "keeping the investigation worker paused")
        say("--manual: the investigation worker stays paused; cases wait for an operator to start each investigation")
        preroll(api, live_from, args.preroll_speed, say, poll=args.poll_seconds, **timing)
        cases = queue(api)
    else:
        step(api, "post", "/worker/start", "starting the investigation worker")
        say("investigation worker started")
        preroll(api, live_from, args.preroll_speed, say, poll=args.poll_seconds, **timing)
        cases = wait_for_worker(api, say, poll=max(args.poll_seconds, 0), timeout=args.catchup_timeout, **timing)
    for line in queue_lines(cases):
        say(line)
    if args.no_live:
        say("--no-live: stopped after the pre-roll; the simulation is paused and the worker is " + ("paused" if args.manual else "running"))
        return {"cases": cases, "live_started_at": None, "archive": exported.get("path")}
    return {"cases": cases, "live_started_at": go_live(api, args.live_speed, say), "archive": exported.get("path")}


def parse(argv=None):
    def live_from(text):
        try:
            return instant(text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"not an ISO time with an offset: {text!r} ({error})") from None

    def preroll_speed(text):
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
        if value > MAX_PREROLL_SPEED:
            raise argparse.ArgumentTypeError(f"refused: a pre-roll above {MAX_PREROLL_SPEED} is not allowed (got {value})")
        if value not in PREROLL_SPEEDS:
            raise argparse.ArgumentTypeError(f"the backend accepts {', '.join(map(str, PREROLL_SPEEDS))} (got {value})")
        return value

    parser = argparse.ArgumentParser(description="Seed a live demo session on a running backend, over HTTP only.")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN, help=f"the running backend (default {DEFAULT_ORIGIN})")
    parser.add_argument("--live-from", type=live_from, metavar="ISO_TIME",
                        help="simulation time at which the live phase starts, e.g. 2026-09-15T13:30:00+00:00 (required unless --export-only)")
    parser.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR), metavar="DIR",
                        help="where the current session's cases are exported before the reset (default artifacts/demo/sessions "
                             "under the repository root)")
    parser.add_argument("--no-archive", action="store_true",
                        help="reset WITHOUT exporting the current session's cases first (they are lost)")
    parser.add_argument("--export-only", action="store_true", help="export the current session's cases and do nothing else (no reset)")
    parser.add_argument("--preroll-speed", type=preroll_speed, default=600, help="speed of the pre-roll (default 600; never above 600)")
    parser.add_argument("--live-speed", type=int, choices=LIVE_SPEEDS, default=600, help="speed of the live phase (default 600; 60 suits a manual walkthrough)")
    parser.add_argument("--no-live", action="store_true", help="stop after the pre-roll (the simulation stays paused)")
    parser.add_argument("--manual", action="store_true",
                        help="leave automatic investigation OFF: the worker is never started and every case waits for an operator to start it")
    parser.add_argument("--poll-seconds", type=float, default=1.0, help="seconds between status polls (default 1)")
    parser.add_argument("--catchup-timeout", type=float, default=3600.0,
                        help="how long to wait for the worker to finish the pre-roll's cases, in seconds (default 3600)")
    args = parser.parse_args(argv)
    if args.export_only and args.no_archive:
        parser.error("--export-only and --no-archive contradict each other")
    if not args.export_only and args.live_from is None:
        parser.error("--live-from is required (unless --export-only)")
    return args


def main(argv=None, api=None):
    args = parse(argv)
    try:
        run(api or Http(args.origin), args)
    except Failed as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
