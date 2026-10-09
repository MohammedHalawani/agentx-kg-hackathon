"""Decoupled background workers for the operations runtime.

Each worker has its own thread and loop, so a slow model investigation never stalls ingestion,
monitoring or outcome verification:

  ingestion     advances the simulation clock (when the simulator runs) and normalizes delivered
                provider messages through the gateway
  monitor       checks touched and deadline-due shipments against visible evidence; opens cases
  investigation claims the oldest eligible case (FIFO) and runs the agent investigation
  execution     hands authorized actions to the execution adapter (the synthetic simulator in development)
  verification  evaluates executed actions against later evidence

Workers coordinate only through the durable ledger (the OpsControl lock serializes claims and
clock updates), never through shared in-memory state. Each keeps a heartbeat for the status API.
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

    def __init__(self, store):
        self.store = store
        pace = max(0.0, float(os.environ.get("SUHAIL_WORKER_PACE_SECONDS", "6")))
        self._last_tick = time.monotonic()
        self._last_case = 0.0
        self.workers = {
            "ingestion": Worker("ingestion", self.ingest, 1.0),
            "monitor": Worker("monitor", self.monitor, 1.0),
            "investigation": Worker("investigation", self.investigate, max(1.0, pace / 3)),
            "execution": Worker("execution", self.execute, 2.0),
            "verification": Worker("verification", self.verify, 2.0),
        }
        self.pace = pace

    def start(self):
        for worker in self.workers.values():
            worker.start()
        return self

    def stop(self):
        for worker in self.workers.values():
            worker.stop()

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

    def investigate(self):
        # Synthetic presentation pacing between cases; recorded stage timings are never altered.
        if self.store.status()["worker"]["state"] != "running" or time.monotonic() - self._last_case < self.pace:
            return {"processed": False}
        result = self.store.process_one()
        if result.get("processed"):
            self._last_case = time.monotonic()
        return {"processed": bool(result.get("processed")), "case_id": result.get("case_id"),
                "workflow_state": result.get("workflow_state")}

    def execute(self):
        return {"executed": len(self.store.execute_step(limit=10))}

    def verify(self):
        return {"verified": len(self.store.outcome_step(limit=10))}

    def status(self):
        return {name: dict(worker.heartbeat) for name, worker in self.workers.items()}
