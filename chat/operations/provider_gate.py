"""A limit on how many provider calls this process has in flight at once (SUHAIL_PROVIDER_MAX_INFLIGHT, 1 or 2).

Every model call made through llm.pipeline._llm.invoke takes a permit first and gives it back when the underlying
provider call has really ended:

  - A caller that stops waiting at its deadline does NOT free its slot. The abandoned request is still open at the
    provider, so its permit stays taken until that request returns or fails; its late answer is discarded.
  - A retry takes a permit like any other call. While an abandoned call still holds the only slot, the retry waits, and
    fails as a provider failure if the slot does not come free in time. Capacity is never exceeded to make room for it.
  - Waiting is bounded (the caller's own deadline), ends early when the caller's claim is cancelled, and happens on the
    calling thread: no thread is created to wait, and at most MAX_WAITERS callers wait at once (more are refused at once).
  - A permit is released exactly once, whatever the call does.

This is a limit inside one process. It says nothing about other clients of the same provider account, and overlapping
calls here are overlapping open requests, not proof that the provider ran them at the same time.

`scope` labels the calls made inside it (case, run, worker, role) for the log and carries the claim's cancel signal.
The log has one line when a call starts and one when it ends: request id, role, ids, how long it waited, wall times and
the outcome. Never a prompt, a reply or a credential.
"""
import contextlib
import contextvars
import itertools
import logging
import math
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger("suhail.provider")

MAX_INFLIGHT_ENV = "SUHAIL_PROVIDER_MAX_INFLIGHT"
LIMITS = (1, 2)
DEFAULT_LIMIT = 1
MAX_WAITERS = 8
POLL_SECONDS = 0.05        # how soon a waiting caller notices that its claim was cancelled
RECENT = 200
LABELS = ("role", "case_id", "run_id", "worker_id")

_scope = contextvars.ContextVar("suhail_provider_scope", default=None)


class CapacityUnavailable(TimeoutError):
    """No permit was granted. `reason`: timeout (the wait ran out), cancelled (the caller's claim is gone) or
    queue_full (too many callers are already waiting)."""

    def __init__(self, reason):
        super().__init__(f"no provider capacity ({reason})")
        self.reason = reason


def max_inflight(value=None):
    """The limit: the given value, else the environment, else 1. Only 1 and 2 are allowed; anything else is 1."""
    text = os.environ.get(MAX_INFLIGHT_ENV, "") if value is None else value
    try:
        number = float(str(text).strip())
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return int(number) if math.isfinite(number) and number in LIMITS else DEFAULT_LIMIT


@contextlib.contextmanager
def scope(*, cancel=None, **labels):
    """Label the provider calls made inside this block and, with `cancel` (a threading.Event), end their waits when it
    is set. Nested scopes add to the outer one. Context variables follow the call onto its own thread."""
    merged = {**(_scope.get() or {}), **{key: value for key, value in labels.items() if key in LABELS and value is not None}}
    if cancel is not None:
        merged["cancel"] = cancel
    token = _scope.set(merged)
    try:
        yield
    finally:
        _scope.reset(token)


def current():
    """(labels, cancel signal or None) of the calling context."""
    labels = dict(_scope.get() or {})
    return labels, labels.pop("cancel", None)


class Permit:
    """One slot of the gate, held by one underlying provider call."""

    def __init__(self, gate, record):
        self.gate, self.record = gate, record
        self._lock, self._released = threading.Lock(), False

    def abandon(self):
        """The caller stopped waiting for this call. The slot stays taken until the call itself ends."""
        self.record["abandoned"] = True

    def release(self, outcome="ok"):
        """Give the slot back. Only the first call does anything; returns whether this one did."""
        with self._lock:
            if self._released:
                return False
            self._released = True
        self.gate._release(self.record, outcome)
        return True


class ProviderGate:
    def __init__(self, limit=None, *, max_waiters=MAX_WAITERS, clock=time.monotonic):
        self.limit, self.max_waiters, self.clock = max_inflight(limit), max_waiters, clock
        self.condition = threading.Condition()
        self.inflight = self.waiting = self.peak = self.granted = self.released = self.refused = 0
        self.sequence = itertools.count(1)
        self.recent = deque(maxlen=RECENT)      # the last calls, for measurement: ids and times only

    def acquire(self, wait, *, cancel=None, labels=None):
        """Take a slot, waiting at most `wait` seconds on the calling thread. Raises CapacityUnavailable."""
        asked = self.clock()
        with self.condition:
            try:
                if cancel is not None and cancel.is_set():
                    raise CapacityUnavailable("cancelled")
                if self.inflight >= self.limit:
                    if self.waiting >= self.max_waiters:
                        raise CapacityUnavailable("queue_full")
                    self.waiting += 1
                    try:
                        while self.inflight >= self.limit:
                            remaining = wait - (self.clock() - asked)
                            if cancel is not None and cancel.is_set():
                                raise CapacityUnavailable("cancelled")
                            if remaining <= 0:
                                raise CapacityUnavailable("timeout")
                            self.condition.wait(min(remaining, POLL_SECONDS))
                    finally:
                        self.waiting -= 1
            except CapacityUnavailable as error:
                self.refused += 1
                log.warning("provider call refused reason=%s %s inflight=%d/%d waiting=%d", error.reason, self._ids(labels),
                            self.inflight, self.limit, self.waiting)
                raise
            self.inflight += 1
            self.granted += 1
            self.peak = max(self.peak, self.inflight)
            record = {"request_id": f"call-{next(self.sequence):06d}", **{key: (labels or {}).get(key) for key in LABELS},
                      "thread": threading.current_thread().name, "waited_seconds": round(self.clock() - asked, 3),
                      "started_at": datetime.now(timezone.utc).isoformat(), "started": self.clock(), "finished_at": None,
                      "seconds": None, "outcome": None, "abandoned": False, "inflight_at_start": self.inflight}
            self.recent.append(record)
        log.info("provider call start request=%s %s waited=%.3fs inflight=%d/%d at=%s", record["request_id"], self._ids(record),
                 record["waited_seconds"], record["inflight_at_start"], self.limit, record["started_at"])
        return Permit(self, record)

    def _release(self, record, outcome):
        with self.condition:
            self.inflight -= 1
            self.released += 1
            record.update(finished_at=datetime.now(timezone.utc).isoformat(), seconds=round(self.clock() - record["started"], 3),
                          outcome=outcome)
            self.condition.notify()
        log.info("provider call end request=%s %s outcome=%s seconds=%.3f answer_discarded=%s at=%s", record["request_id"],
                 self._ids(record), outcome, record["seconds"], record["abandoned"], record["finished_at"])

    @staticmethod
    def _ids(labels):
        return " ".join(f"{key.removesuffix('_id')}={(labels or {}).get(key) or '-'}" for key in LABELS)

    def snapshot(self):
        """Counters and the recent calls (ids, times and outcomes; no content)."""
        with self.condition:
            return {"limit": self.limit, "inflight": self.inflight, "waiting": self.waiting, "peak_inflight": self.peak,
                    "granted": self.granted, "released": self.released, "refused": self.refused,
                    "calls": [{key: value for key, value in record.items() if key != "started"} for record in self.recent]}


_shared = None
_shared_lock = threading.Lock()


def shared():
    """The process's one gate, built from the environment at its first use."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = ProviderGate()
        return _shared


def use(gate):
    """Replace the process's gate (a test, or a measurement harness). Returns the one it replaced; None rebuilds it from
    the environment at the next use. Calls in flight keep the gate they started on."""
    global _shared
    with _shared_lock:
        previous, _shared = _shared, gate
        return previous
