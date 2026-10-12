"""Seed a recording take on a running backend, over HTTP only: the same starting point every time.

  cd chat && uv run python ../scripts/showcase_seed.py --video A [--origin http://127.0.0.1:8022] [--archive-dir DIR]

It archives the current session, resets it, runs the simulated clock to shortly before the chosen shipment's case
opens (fast first, then at speed 60 so the stopping point is exact), lets the investigation worker finish the cases
that opened on the way, and then leaves the clock PAUSED and automatic investigation OFF. A take starts by switching
both on; the chosen shipment's case opens within the first seconds and is the oldest case waiting, so it is the first
one investigated.

Nothing here writes a case, an investigation result, an action or an outcome: those come from the backend's own
monitor, investigator, policy, simulator and verifier once the clock runs. The shipments are ordinary shipments of the
synthetic world; which ones the monitor may open is the backend's SUHAIL_DEMO_SHIPMENTS list (printed below for each
video), set when the backend is started.
"""
import argparse
import sys
import time
from datetime import timedelta

from world_demo_session import ApiError, Failed, Http, export_session, instant, open_session, preroll, queue, queue_lines, reset, step, wait_for_worker

# ready_at: where the clock is left. The case of `shipment` opens a few simulated minutes later.
VIDEOS = {
    "A": {"shipment": "SYN-SHP-000304", "ready_at": "2026-09-16T07:20:00+00:00",
          "shipments": "SYN-SHP-000304,SYN-SHP-000269,SYN-SHP-000121,SYN-SHP-000599"},
    "B": {"shipment": "SYN-SHP-000443", "ready_at": "2026-09-19T08:38:00+00:00",
          "shipments": "SYN-SHP-000443,SYN-SHP-000050,SYN-SHP-000042,SYN-SHP-000460"},
}
COARSE_MARGIN = timedelta(hours=2, minutes=20)   # The fast pre-roll stops this long before ready_at (it overshoots by up to ~1.5 h).
FINE_SPEED = 60


def fine_step(api, until, say, *, sleep=time.sleep, poll=0.25):
    """Run the clock at speed 60 to `until`, then pause: lands within a simulated minute."""
    status = step(api, "get", "/simulation/status", "reading the status")
    if instant(status["as_of"]) >= until:
        raise Failed(f"the fast pre-roll overshot: the clock is at {status['as_of']}, after {until.isoformat()}")
    step(api, "post", "/simulation/start", "starting the fine step", body={"speed": FINE_SPEED, "replay_mode": "timeline"})
    try:
        while instant(step(api, "get", "/simulation/status", "reading the status")["as_of"]) < until:
            sleep(poll)
    finally:
        try:
            api.post("/simulation/pause")
        except (ApiError, Failed):
            pass
    status = step(api, "get", "/simulation/status", "reading the status")
    say(f"clock paused at {status['as_of']}")
    return status


def run(api, video, archive_dir, say=print, ready_at=None):
    plan = VIDEOS[video]
    ready = instant(ready_at or plan["ready_at"])
    open_session(api)
    exported = {}
    reset(api, ready, say, archive=lambda status: exported.update(path=export_session(api, archive_dir, say, status=status)))
    step(api, "post", "/worker/start", "starting the investigation worker")
    preroll(api, ready - COARSE_MARGIN, 600, say)
    fine_step(api, ready, say)
    cases = wait_for_worker(api, say)            # Cases that opened on the way are investigated at the paused clock.
    step(api, "post", "/worker/pause", "switching automatic investigation off")
    for line in queue_lines(cases):
        say(line)
    if any(str(c.get("shipment_id")) == plan["shipment"] for c in queue(api)):
        raise Failed(f"the case of {plan['shipment']} opened before the starting point; use an earlier --ready-at")
    status = step(api, "get", "/simulation/status", "reading the status")
    say(f"READY for video {video}: session {(status.get('session') or {}).get('session_id')}, clock paused at {status['as_of']}, "
        f"automatic investigation off. Start the clock at speed {FINE_SPEED} and switch Auto on; {plan['shipment']} opens within the first seconds.")
    return {"archive": exported.get("path"), "status": status}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Seed a recording take on a running backend, over HTTP only.")
    parser.add_argument("--video", choices=sorted(VIDEOS), required=True)
    parser.add_argument("--origin", default="http://127.0.0.1:8022")
    parser.add_argument("--archive-dir", default="../artifacts/demo/ux-test-ledger")
    parser.add_argument("--ready-at", help="override the simulated time the clock is left at")
    args = parser.parse_args(argv)
    print(f"video {args.video}: the backend must have been started with SUHAIL_DEMO_SHIPMENTS={VIDEOS[args.video]['shipments']}")
    try:
        run(Http(args.origin), args.video, args.archive_dir, ready_at=args.ready_at)
    except Failed as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
