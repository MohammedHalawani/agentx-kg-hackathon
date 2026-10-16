"""Decoupled background workers for the operations runtime.

Each worker has its own thread and loop, so a slow model investigation never stalls ingestion,
monitoring or outcome verification:

  ingestion     advances the simulation clock (when the simulator runs) and normalizes delivered
                provider messages through the gateway
  monitor       checks touched and deadline-due shipments against visible evidence; opens cases
  investigation claims the oldest eligible case (FIFO) and runs the agent investigation; one loop, or up to
                four (SUHAIL_INVESTIGATION_WORKERS), named investigation-1 to investigation-4
  execution     hands authorized actions to the execution adapter (the synthetic simulator in development)
  verification  evaluates executed actions against later evidence

Workers coordinate only through the durable ledger (the OpsControl lock serializes claims and
clock updates), never through shared in-memory state. Each keeps a heartbeat for the status API.

The investigation loops share nothing but the store: each claims its own case under its own name (operations.claims),
paces itself, and backs off by itself when its investigation fails. A failure of one never pauses another. Provider
lanes are not theirs: every model call takes whichever lane is free (operations.provider_gate).

Automatic investigation also stops from inside the server (V3.4), never by taking a case from a running worker: the loops
stop claiming, and Auto is paused once no claim is live, when
  - model investigation is on and the inference budget can no longer pay for one more whole investigation
    (SUHAIL_AUTO_BUDGET_HEADROOM_CALLS calls at their maximum size; default the per-case model-call cap), or the
    ledger cannot be read; a case is not claimed just to fail for want of budget and be handed to a person, or
  - SUHAIL_AUTO_MAX_RUNS automatic investigations have been started by this process (a bounded test; unset: no limit).
The reason is in `auto_stop()` and so in /worker/status; an operator who starts Auto again is stopped again while the
reason still holds.
"""
from datetime import datetime, timezone
import logging
import os
import threading
import time

log = logging.getLogger("suhail.workers")

AUTO_MAX_RUNS_ENV = "SUHAIL_AUTO_MAX_RUNS"
HEADROOM_ENV = "SUHAIL_AUTO_BUDGET_HEADROOM_CALLS"


def _positive_int(name):
    try:
        value = int(os.environ.get(name, "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


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
        # One investigation loop per place the store grants (1 to 4). Each has its own pacing and failure state.
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
        # Stopping Auto from inside the server (module docstring): runs started, the limit, and why Auto was stopped.
        self.max_runs = _positive_int(AUTO_MAX_RUNS_ENV)
        self.started_runs = 0
        self._runs_lock = threading.Lock()
        self._auto_stop = None

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
        reason = self._stop_reason()
        if reason:
            self._stop_auto(reason)
            return {"processed": False, "reason": reason}
        with self._runs_lock:      # a place among the runs this process may start, given back if nothing is claimed
            if self.max_runs is not None and self.started_runs >= self.max_runs:
                return {"processed": False, "reason": "auto_max_runs"}
            self.started_runs += 1
        claimed = False
        try:
            result = self.store.process_one(worker_id=name)
            claimed = result.get("reason") not in ("worker_paused", "capacity", "none_eligible")
        except Exception:
            claimed = True         # a claim was made and failed: it counts as a run started
            # The store has already given up this loop's claim (the case is queued again). This loop alone waits
            # before its next claim; the error is recorded by type in its heartbeat (Worker.run).
            self._failures[name] += 1
            self._retry_at[name] = time.monotonic() + min(self.FAILURE_BACKOFF_SECONDS * 2 ** (self._failures[name] - 1),
                                                          self.FAILURE_BACKOFF_MAX_SECONDS)
            raise
        finally:
            if not claimed:
                with self._runs_lock:
                    self.started_runs -= 1
        self._failures[name] = 0
        if result.get("processed"):
            self._last_case[name] = time.monotonic()
        return {"processed": bool(result.get("processed")), "case_id": result.get("case_id"),
                "workflow_state": result.get("workflow_state"), "reason": result.get("reason")}

    def _headroom_calls(self):
        calls = _positive_int(HEADROOM_ENV)
        if calls is None:
            from operations.investigator import model_call_cap
            calls = getattr(self.store, "model_call_cap", None) or model_call_cap()
        return calls

    def _stop_reason(self):
        """Why automatic investigation must not claim another case now, or None."""
        if self.max_runs is not None and self.started_runs >= self.max_runs:
            return "auto_max_runs"
        if getattr(self.store, "agents", None) is None:
            return None          # rules only: no model call, no budget
        from operations import provider_gate
        from operations.inference_safety import InferenceLedger, SafetyRefused
        try:
            enough = InferenceLedger().headroom(self._headroom_calls(), lanes=provider_gate.shared().names)
        except (SafetyRefused, OSError) as error:
            log.warning("Inference budget unreadable (%s); automatic investigation stops", type(error).__name__)
            return "inference_budget_unavailable"
        return None if enough else "inference_budget_exhausted"

    def _stop_auto(self, reason):
        """Record why Auto stops and pause it once no claim is live (store.halt_auto); running investigations finish."""
        if (self._auto_stop or {}).get("reason") != reason:
            log.warning("Automatic investigation stops: %s", reason)
            self._auto_stop = {"reason": reason, "at": datetime.now(timezone.utc).isoformat(), "paused": False,
                               "runs_started": self.started_runs, "max_runs": self.max_runs}
        try:        # called only while Auto is running: an operator may have started it again since the last stop
            if self.store.halt_auto(reason):
                self._auto_stop.update(paused=True, paused_at=datetime.now(timezone.utc).isoformat())
        except Exception as error:
            log.warning("Automatic investigation was not paused (%s); no new case is claimed", type(error).__name__)

    def auto_stop(self):
        """Why the server stopped automatic investigation (None while it has not): reason, when, whether Auto is paused."""
        return dict(self._auto_stop) if self._auto_stop else None

    def provider_status(self):
        """The provider lanes and the inference budget, for /worker/status: lane letters, states and counts; never a key,
        a prompt or a label."""
        from operations import provider_gate
        from operations.inference_safety import InferenceLedger, SafetyRefused
        gate = provider_gate.shared()
        snapshot = gate.snapshot()
        status = {"lanes_configured": provider_gate.lane_count(), "limit": gate.limit, "inflight": snapshot["inflight"],
                  "waiting": snapshot["waiting"], "peak_inflight": snapshot["peak_inflight"], "refused": snapshot["refused"],
                  "lanes": snapshot["lanes"], "calls": gate.activity(), "workers": len(self.investigators),
                  "model_investigation": getattr(self.store, "agents", None) is not None}
        try:
            budget = InferenceLedger().summary(lanes=gate.names)
        except (SafetyRefused, OSError) as error:
            budget = {"available": False, "reason": type(error).__name__}
        else:
            budget["available"] = True
        status["budget"] = budget
        return status

    def execute(self):
        return {"executed": len(self.store.execute_step(limit=10))}

    def verify(self):
        return {"verified": len(self.store.outcome_step(limit=10))}

    def status(self):
        return {name: dict(worker.heartbeat) for name, worker in self.workers.items()}
