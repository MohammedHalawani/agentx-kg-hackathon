"""Decoupled background workers for the operations runtime.

Each worker has its own thread and loop, so a slow model investigation never stalls ingestion,
monitoring or outcome verification:

  ingestion     advances the simulation clock (when the simulator runs) and normalizes delivered
                provider messages through the gateway
  monitor       checks touched and deadline-due shipments against visible evidence; opens cases
  investigation claims the oldest eligible case (FIFO) and runs the agent investigation; one loop, or two
                (SUHAIL_INVESTIGATION_WORKERS), named investigation-1 and investigation-2
  execution     hands authorized actions to the execution adapter (the synthetic simulator in development)
  verification  evaluates executed actions against later evidence

Workers coordinate only through the durable ledger (the OpsControl lock serializes claims and
clock updates), never through shared in-memory state. Each keeps a heartbeat for the status API.

Two investigation loops share nothing but the store: each claims its own case under its own name (operations.claims),
paces itself, and backs off by itself when its investigation fails. A failure of one never pauses the other.
"""
from datetime import datetime, timezone
import logging
import os
import threading
import time

log = logging.getLogger("suhail.workers")


class Worker(threading.Thread):
    def __init__(self, name, step, interval):
        super().__init__(name=f"suhail-{name}", daemon=True)
        self.key, self.step, self.interval = name, step, interval
        self.stop_event = threading.Event()
        self.heartbeat = {"state": "starting", "iterations": 0, "last_started_at": None, "last_finished_at": None,
                          "last_result": None, "last_error": None, "busy": False}

    def run(self):
        self.heartbeat["state"] = "running"
        while not self.stop_event.wait(self.interval):
            self.heartbeat.update(busy=True, last_started_at=datetime.now(timezone.utc).isoformat())
            try:
                self.heartbeat["last_result"] = self.step()
                self.heartbeat["last_error"] = None
            except Exception as error:
                # Type only: no provider text, evidence contents or credentials in logs or status.
                self.heartbeat["last_error"] = type(error).__name__
                log.warning("%s worker step failed (%s)", self.key, type(error).__name__)
            finally:
                self.heartbeat.update(busy=False, iterations=self.heartbeat["iterations"] + 1,
                                      last_finished_at=datetime.now(timezone.utc).isoformat())
        self.heartbeat["state"] = "stopped"

    def stop(self):
        self.stop_event.set()


class WorkerPool:
    """Ingestion, monitoring, investigation and verification on independent threads."""

    # After an investigation loop's step fails, that loop waits this long before it claims again, doubling for each
    # failure in a row up to the maximum. Its own wait only: the other loop keeps its pace.
    FAILURE_BACKOFF_SECONDS = 5.0
    FAILURE_BACKOFF_MAX_SECONDS = 60.0

    def __init__(self, store):
        self.store = store
        pace = max(0.0, float(os.environ.get("SUHAIL_WORKER_PACE_SECONDS", "6")))
        self._last_tick = time.monotonic()
        # One investigation loop per place the store grants (1 or 2). Each has its own pacing and failure state.
        self.investigators = [f"investigation-{number}" for number in range(1, max(1, int(getattr(store, "capacity", 1))) + 1)]
        self._last_case = {name: 0.0 for name in self.investigators}
        self._failures = {name: 0 for name in self.investigators}
        self._retry_at = {name: 0.0 for name in self.investigators}
        self.workers = {
            "ingestion": Worker("ingestion", self.ingest, 1.0),
            "monitor": Worker("monitor", self.monitor, 1.0),
            **{name: Worker(name, (lambda name=name: self.investigate(name)), max(1.0, pace / 3)) for name in self.investigators},
            "execution": Worker("execution", self.execute, 2.0),
            "verification": Worker("verification", self.verify, 2.0),
        }
        # The name the single loop had: the same worker as investigation-1, for what still reads it.
        self.workers["investigation"] = self.workers[self.investigators[0]]
        self.pace = pace

    def _threads(self):
        return list(dict.fromkeys(self.workers.values()))       # each worker once, whatever names it has

    def start(self):
        self._prepare()
        for worker in self._threads():
            worker.start()
        return self

    def _prepare(self):
        """Build what the investigation loops share before any of them runs, so two first claims never race to build
        it: the store's reader and, when model investigation is on, the cached model client."""
        try:
            self.store._reader()
            if getattr(self.store, "agents", None) is not None:
                from llm.pipeline import _llm
                _llm.model()
        except Exception as error:      # Type only. The first investigation builds what is missing, under the same locks.
            log.warning("Shared investigation resources were not prepared (%s)", type(error).__name__)

    def stop(self):
        """No new claims, then this pool's own running investigations are given up: their claims are released by their
        own identity (a claim of another process is never touched), which ends their renewal threads; whatever those
        investigations still try to write is refused."""
        for worker in self._threads():
            worker.stop()
        try:
            released = self.store.release_claims(set(self.investigators))
        except Exception as error:
            released = []
            log.warning("Claims were not released at stop (%s); their leases will expire", type(error).__name__)
        return released

    def ingest(self):
        now = time.monotonic()
        elapsed, self._last_tick = min(now - self._last_tick, 10), now
        if self.store.status()["simulator"]["state"] != "running":
            return {"advanced": False}
        result = self.store.tick(seconds=elapsed)
        return {"advanced": True, "events": result["events_replayed"], "as_of": result["as_of"]}

    def monitor(self):
        checked = opened = 0
        while self.store.status()["session"]["monitor_pending"]:
            result = self.store.monitor_step(limit=10)
            checked += result["checked"]
            opened += len(result["opened"])
            if not result["checked"]:
                break
        return {"checked": checked, "opened": opened}

    def investigate(self, name=None):
        """One step of the investigation loop `name` (the first loop when not given)."""
        name = name or self.investigators[0]
        now = time.monotonic()
        # Synthetic presentation pacing between cases; recorded stage timings are never altered.
        if (self.workers[name].stop_event.is_set() or now < self._retry_at[name] or now - self._last_case[name] < self.pace
                or self.store.status()["worker"]["state"] != "running"):
            return {"processed": False}
        try:
            result = self.store.process_one(worker_id=name)
        except Exception:
            # The store has already given up this loop's claim (the case is queued again). This loop alone waits
            # before its next claim; the error is recorded by type in its heartbeat (Worker.run).
            self._failures[name] += 1
            self._retry_at[name] = time.monotonic() + min(self.FAILURE_BACKOFF_SECONDS * 2 ** (self._failures[name] - 1),
                                                          self.FAILURE_BACKOFF_MAX_SECONDS)
            raise
        self._failures[name] = 0
        if result.get("processed"):
            self._last_case[name] = time.monotonic()
        return {"processed": bool(result.get("processed")), "case_id": result.get("case_id"),
                "workflow_state": result.get("workflow_state"), "reason": result.get("reason")}

    def execute(self):
        return {"executed": len(self.store.execute_step(limit=10))}

    def verify(self):
        return {"verified": len(self.store.outcome_step(limit=10))}

    def status(self):
        return {name: dict(worker.heartbeat) for name, worker in self.workers.items()}
