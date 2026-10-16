"""A limit on how many provider calls this process has in flight at once (SUHAIL_PROVIDER_MAX_INFLIGHT, 1 to 4).

Every model call made through llm.pipeline._llm.invoke takes a permit first and gives it back when the underlying
provider call has really ended:

  - A caller that stops waiting at its deadline does NOT free its slot. The abandoned request is still open at the
    provider, so its permit stays taken until that request returns or fails; its late answer is discarded.
  - A retry takes a permit like any other call. While an abandoned call still holds the only slot, the retry waits, and
    fails as a provider failure if the slot does not come free in time. Capacity is never exceeded to make room for it.
  - Waiting is bounded (the caller's own deadline), ends early when the caller's claim is cancelled, and happens on the
    calling thread: no thread is created to wait, and at most MAX_WAITERS callers wait at once (more are refused at once).
    Waiting callers are served in the order they asked.
  - A permit is released exactly once, whatever the call does.

This is a limit inside one process. It says nothing about other clients of the same provider account, and overlapping
calls here are overlapping open requests, not proof that the provider ran them at the same time.

Lanes. Each slot is a lane bound to one provider key, and a lane holds at most one call. Lanes are named A to D after
the setting their key comes from (config.LLM_API_KEY, LLM_API_KEY2, LLM_API_KEY3, LLM_API_KEY4); only DISTINCT keys
make lanes (a key given twice is one lane, named after its first setting), and SUHAIL_PROVIDER_LANE_<B|C|D>=off leaves
one out. A provider plan that allows one request in flight per account is therefore never asked for two on the same
key: the shared gate's limit is SUHAIL_PROVIDER_MAX_INFLIGHT capped by the number of distinct enabled keys, so a limit
of 4 with two keys stays 2. Lanes are a shared pool: a caller gets whichever lane is free, no worker owns one. A permit
carries its lane; the call uses that lane's key, and an abandoned call keeps its lane (and key) until it really ends.
Keys are never logged or reported: lanes are named by letter only.

Lane health. A provider answer that says a key may not be used takes its lane out of service; the failed call is NOT
re-sent on another lane, and the last lane in service is never taken out (one-lane operation keeps the behaviour it
always had: that call fails, nothing else).
  - authentication or permission refused: the lane is disabled until an operator enables it again (`enable`) or the
    process restarts; a key that is refused does not start working by waiting.
  - rate or plan limit: the lane cools down for SUHAIL_PROVIDER_LANE_COOLDOWN_SECONDS (60 s), doubling for each limit
    in a row up to 15 minutes, and then takes calls again. Nothing is retried for it: the next call is a new call of
    its caller. MAX_RATE_LIMIT_STRIKES limits in a row without a successful call on the lane disable it like a refused key.
Every state is in `lanes_snapshot()` (and so in /worker/status).

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
LIMITS = (1, 2, 3, 4)
DEFAULT_LIMIT = 1
MAX_WAITERS = 8
POLL_SECONDS = 0.05        # how soon a waiting caller notices that its claim was cancelled
RECENT = 200
LABELS = ("role", "case_id", "run_id", "worker_id")
LANE_NAMES = ("A", "B", "C", "D")    # the lanes of config.LLM_API_KEY, LLM_API_KEY2, LLM_API_KEY3, LLM_API_KEY4 (never a key)
KEY_SETTINGS = ("LLM_API_KEY", "LLM_API_KEY2", "LLM_API_KEY3", "LLM_API_KEY4")
LANE_B_ENV = "SUHAIL_PROVIDER_LANE_B"   # "off" (or 0/false/no) leaves lane B out; likewise _C and _D. Lane A is always on.
# A provider answer that says this key may not be used takes the lane out of service (Lane health above). The failed call
# is NOT re-sent on another lane (no account switching).
KEY_FAULTS = ("AuthenticationError", "PermissionDeniedError")
RATE_FAULTS = ("RateLimitError",)
LANE_FAULTS = KEY_FAULTS + RATE_FAULTS
COOLDOWN_ENV = "SUHAIL_PROVIDER_LANE_COOLDOWN_SECONDS"
DEFAULT_COOLDOWN_SECONDS = 60.0
COOLDOWN_BOUNDS = (1.0, 3600.0)
COOLDOWN_MAX_SECONDS = 900.0
MAX_RATE_LIMIT_STRIKES = 3

_scope = contextvars.ContextVar("suhail_provider_scope", default=None)


class CapacityUnavailable(TimeoutError):
    """No permit was granted. `reason`: timeout (the wait ran out), cancelled (the caller's claim is gone),
    queue_full (too many callers are already waiting) or lane_disabled (the lane asked for is out of service, or every
    lane the caller may use is disabled)."""

    def __init__(self, reason):
        super().__init__(f"no provider capacity ({reason})")
        self.reason = reason


def max_inflight(value=None):
    """The limit: the given value, else the environment, else 1. Only 1 to 4 are allowed; anything else is 1."""
    text = os.environ.get(MAX_INFLIGHT_ENV, "") if value is None else value
    try:
        number = float(str(text).strip())
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return int(number) if math.isfinite(number) and number in LIMITS else DEFAULT_LIMIT


def cooldown_seconds(value=None):
    """The first cooldown of a rate-limited lane (SUHAIL_PROVIDER_LANE_COOLDOWN_SECONDS, default 60 s, 1 s to 1 h)."""
    text = os.environ.get(COOLDOWN_ENV, "") if value is None else value
    try:
        number = float(str(text).strip() or DEFAULT_COOLDOWN_SECONDS)
    except (TypeError, ValueError):
        number = DEFAULT_COOLDOWN_SECONDS
    if not math.isfinite(number):
        number = DEFAULT_COOLDOWN_SECONDS
    return max(COOLDOWN_BOUNDS[0], min(number, COOLDOWN_BOUNDS[1]))


def _switched_off(name):
    return os.environ.get(f"SUHAIL_PROVIDER_LANE_{name}", "").strip().lower() in ("off", "0", "false", "no")


def provider_lanes():
    """The names of the lanes the configured keys make, in order: one per DISTINCT key (named after the first setting
    that holds it), without the lanes switched off. At least ["A"]. Values are compared, never logged or returned."""
    try:
        import config
    except Exception:                       # no configuration (an isolated test): one lane
        return ["A"]
    seen, names = set(), []
    for name, setting in zip(LANE_NAMES, KEY_SETTINGS):
        key = getattr(config, setting, None)
        if not key or key in seen:
            continue
        seen.add(key)                       # a lane switched off keeps its key: that key cannot come back as another lane
        if name != "A" and _switched_off(name):
            continue
        names.append(name)
    return names or ["A"]


def lane_key(name):
    """The provider key of the lane named `name` (lane A's key for a name without a key of its own)."""
    import config
    setting = KEY_SETTINGS[LANE_NAMES.index(name)] if name in LANE_NAMES else KEY_SETTINGS[0]
    return getattr(config, setting, None) or config.LLM_API_KEY


def lane_count():
    """How many lanes the configured keys make (distinct enabled keys, at least 1)."""
    return len(provider_lanes())


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
    """One slot of the gate, held by one underlying provider call. `lane` is the slot's number (0 to limit-1), `name`
    its letter (the key setting it uses)."""

    def __init__(self, gate, record):
        self.gate, self.record = gate, record
        self.lane = record["lane"]
        self.name = gate.names[self.lane]
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
    def __init__(self, limit=None, *, names=None, max_waiters=MAX_WAITERS, clock=time.monotonic, cooldown=None):
        """limit: how many lanes (1 to 4). names: their letters (default A, B, ...); fewer names than the limit lowers it.
        cooldown: the first cooldown of a rate-limited lane (default SUHAIL_PROVIDER_LANE_COOLDOWN_SECONDS)."""
        self.limit, self.max_waiters, self.clock = max_inflight(limit), max_waiters, clock
        self.names = tuple(names or LANE_NAMES)[:self.limit]
        self.limit = len(self.names)
        self.cooldown = cooldown_seconds() if cooldown is None else float(cooldown)
        self.condition = threading.Condition()
        self.inflight = self.peak = self.granted = self.released = self.refused = 0
        self.busy = [False] * self.limit        # one call at most per lane
        self.disabled = [None] * self.limit     # why a lane is out of service until it is enabled again, or None
        self.cooling = [None] * self.limit      # (until, reason) while a rate-limited lane cools down, or None
        self.strikes = [0] * self.limit         # rate limits in a row without a successful call
        self.faults = [None] * self.limit       # the last fault of each lane: {"fault", "at", "action"}
        self.outcomes = [None] * self.limit     # the outcome of each lane's last call
        self.lane_granted = [0] * self.limit
        self.queue = deque()                    # the callers waiting, in the order they asked
        self.asking = {}                        # ticket -> (labels, wall time asked) of each waiting caller, for status
        self.sequence = itertools.count(1)
        self.recent = deque(maxlen=RECENT)      # the last calls, for measurement: ids and times only

    @property
    def waiting(self):
        return len(self.queue)

    def _cool(self, i):
        """Whether lane i is cooling down now (a cooldown that has run out is cleared here)."""
        if self.cooling[i] is not None and self.clock() >= self.cooling[i][0]:
            self.cooling[i] = None
            log.info("provider lane %s cooldown ended; the lane takes calls again", self.names[i])
        return self.cooling[i] is not None

    def _in_service(self, i):
        return self.disabled[i] is None and not self._cool(i)

    def _free(self, lanes):
        """A lane this caller may take now, else None: of the free lanes in service among `lanes`, the one that has
        carried the fewest calls (the first on a tie), so the calls spread over every key instead of piling onto lane A."""
        free = [i for i in lanes if not self.busy[i] and self._in_service(i)]
        return min(free, key=lambda i: (self.lane_granted[i], i)) if free else None

    def _lanes(self, lane, lanes):
        if lane is not None:
            return (lane,) if 0 <= lane < self.limit else ()
        if lanes is None:
            return tuple(range(self.limit))
        wanted = set(lanes)
        return tuple(i for i in range(self.limit) if i in wanted)

    def _last_in_service(self, lane):
        return all(not self._in_service(i) for i in range(self.limit) if i != lane)

    def disable(self, lane, reason):
        """Take a lane out of service until `enable` (a call in flight on it finishes normally). Never the last lane in
        service. Returns whether the lane was taken out."""
        with self.condition:
            if self.disabled[lane] is not None or self._last_in_service(lane):
                return False
            self.disabled[lane], self.cooling[lane] = reason, None
            self.condition.notify_all()
        log.warning("provider lane %s taken out of service reason=%s; continuing on the remaining lanes", self.names[lane], reason)
        return True

    def enable(self, lane):
        """Put a lane back in service (an operator's decision, e.g. after a refused key was replaced). Returns whether it
        was out of service."""
        with self.condition:
            was = self.disabled[lane] is not None or self.cooling[lane] is not None
            self.disabled[lane], self.cooling[lane], self.strikes[lane] = None, None, 0
            self.condition.notify_all()
        if was:
            log.warning("provider lane %s put back in service by an operator", self.names[lane])
        return was

    def fault(self, lane, error):
        """A provider answer on `lane` saying its key may not be used now (`error`: the exception's type name).
        Returns what was done: disabled, cooling, kept (the last lane in service stays in service) or ignored."""
        at, seconds = datetime.now(timezone.utc).isoformat(), 0.0
        with self.condition:
            if error in KEY_FAULTS:
                action = "kept" if self._last_in_service(lane) else "disabled"
            elif error in RATE_FAULTS:
                self.strikes[lane] += 1
                if self._last_in_service(lane):
                    action = "kept"
                elif self.strikes[lane] >= MAX_RATE_LIMIT_STRIKES:
                    action, error = "disabled", f"{error} x{self.strikes[lane]}"
                else:
                    action = "cooling"
                    seconds = min(self.cooldown * 2 ** (self.strikes[lane] - 1), max(self.cooldown, COOLDOWN_MAX_SECONDS))
                    self.cooling[lane] = (self.clock() + seconds, error)
            else:
                return "ignored"
            if action == "disabled":
                self.disabled[lane], self.cooling[lane] = error, None
            self.faults[lane] = {"fault": error, "at": at, "action": action}
            self.condition.notify_all()
        if action == "kept":
            log.warning("provider lane %s answered %s; it is the last lane in service and stays in service", self.names[lane], error)
        elif action == "cooling":
            log.warning("provider lane %s answered %s; cooling down %.0fs (%d in a row); continuing on the remaining lanes",
                        self.names[lane], error, seconds, self.strikes[lane])
        else:
            log.warning("provider lane %s taken out of service reason=%s; continuing on the remaining lanes", self.names[lane], error)
        return action

    def acquire(self, wait, *, cancel=None, labels=None, lane=None, lanes=None):
        """Take a slot, waiting at most `wait` seconds on the calling thread. Raises CapacityUnavailable.
        Waiting callers are served in the order they asked, so a caller that calls again at once (an investigation's
        next turn) cannot keep another (narration, an operator's question) waiting behind it indefinitely.
        lane: only this lane (a per-key check); the product's callers leave it None and get whichever lane is free.
        lanes: only these lanes (those whose own budget can still pay for the call); None: every lane."""
        asked = self.clock()
        allowed = self._lanes(lane, lanes)
        with self.condition:
            try:
                if cancel is not None and cancel.is_set():
                    raise CapacityUnavailable("cancelled")
                if lane is not None and not (allowed and self._in_service(lane)):
                    raise CapacityUnavailable("lane_disabled")
                if not allowed or all(self.disabled[i] is not None for i in allowed):
                    raise CapacityUnavailable("lane_disabled")
                if self._free(allowed) is None or self.queue:
                    if len(self.queue) >= self.max_waiters:
                        raise CapacityUnavailable("queue_full")
                    ticket = object()
                    self.queue.append(ticket)
                    self.asking[ticket] = ({key: (labels or {}).get(key) for key in LABELS}, datetime.now(timezone.utc).isoformat())
                    try:
                        while self._free(allowed) is None or self.queue[0] is not ticket:
                            remaining = wait - (self.clock() - asked)
                            if cancel is not None and cancel.is_set():
                                raise CapacityUnavailable("cancelled")
                            if remaining <= 0:
                                raise CapacityUnavailable("timeout")
                            if lane is not None and self.disabled[lane] is not None:
                                raise CapacityUnavailable("lane_disabled")
                            if all(self.disabled[i] is not None for i in allowed):
                                raise CapacityUnavailable("lane_disabled")
                            self.condition.wait(min(remaining, POLL_SECONDS))
                    finally:
                        self.queue.remove(ticket)
                        self.asking.pop(ticket, None)
                        self.condition.notify_all()     # whoever is first now looks again
            except CapacityUnavailable as error:
                self.refused += 1
                log.warning("provider call refused reason=%s %s inflight=%d/%d waiting=%d", error.reason, self._ids(labels),
                            self.inflight, self.limit, self.waiting)
                raise
            lane = self._free(allowed)
            self.busy[lane] = True
            self.lane_granted[lane] += 1
            self.inflight += 1
            self.granted += 1
            self.peak = max(self.peak, self.inflight)
            record = {"request_id": f"call-{next(self.sequence):06d}", "lane": lane, **{key: (labels or {}).get(key) for key in LABELS},
                      "thread": threading.current_thread().name, "waited_seconds": round(self.clock() - asked, 3),
                      "started_at": datetime.now(timezone.utc).isoformat(), "started": self.clock(), "finished_at": None,
                      "seconds": None, "outcome": None, "abandoned": False, "inflight_at_start": self.inflight}
            self.recent.append(record)
        log.info("provider call start request=%s lane=%s %s waited=%.3fs inflight=%d/%d at=%s", record["request_id"],
                 self.names[lane], self._ids(record), record["waited_seconds"], record["inflight_at_start"], self.limit, record["started_at"])
        return Permit(self, record)

    def _release(self, record, outcome):
        with self.condition:
            self.inflight -= 1
            self.released += 1
            self.busy[record["lane"]] = False
            self.outcomes[record["lane"]] = outcome
            if outcome == "ok":
                self.strikes[record["lane"]] = 0      # a lane that answers again has no rate limits in a row
            record.update(finished_at=datetime.now(timezone.utc).isoformat(), seconds=round(self.clock() - record["started"], 3),
                          outcome=outcome)
            self.condition.notify_all()
        log.info("provider call end request=%s lane=%s %s outcome=%s seconds=%.3f answer_discarded=%s at=%s", record["request_id"],
                 self.names[record["lane"]], self._ids(record), outcome, record["seconds"], record["abandoned"], record["finished_at"])

    @staticmethod
    def _ids(labels):
        return " ".join(f"{key.removesuffix('_id')}={(labels or {}).get(key) or '-'}" for key in LABELS)

    def _lane_state(self, i):
        """disabled, cooling, busy or ready (with the condition held)."""
        if self.disabled[i] is not None:
            return "disabled"
        if self._cool(i):
            return "cooling"
        return "busy" if self.busy[i] else "ready"

    def lanes_snapshot(self):
        """Each lane's state, for the status API; never a key. `disabled`: why the lane is out of service now (a disabled
        lane's fault, or a cooling lane's rate limit), else None."""
        with self.condition:
            now = self.clock()
            return [{"lane": self.names[i], "state": self._lane_state(i), "busy": self.busy[i], "granted": self.lane_granted[i],
                     "disabled": self.disabled[i] if self.disabled[i] is not None else (self.cooling[i][1] if self.cooling[i] else None),
                     "cooling_seconds_left": round(max(0.0, self.cooling[i][0] - now), 1) if self.cooling[i] else None,
                     "rate_limits_in_a_row": self.strikes[i], "last_fault": dict(self.faults[i]) if self.faults[i] else None,
                     "last_outcome": self.outcomes[i]} for i in range(self.limit)]

    def activity(self):
        """Who has a call in flight on which lane, and who is waiting for a lane, now: labels (role, case, run, worker),
        lane letters and wall times only. A worker shown here is really in a provider call or really waiting for one."""
        with self.condition:
            in_flight = [{**{key: record[key] for key in LABELS}, "lane": self.names[record["lane"]], "since": record["started_at"],
                          "abandoned": record["abandoned"]} for record in self.recent if record["finished_at"] is None]
            waiting = [{**self.asking[ticket][0], "since": self.asking[ticket][1]} for ticket in self.queue if ticket in self.asking]
        return {"in_flight": in_flight, "waiting": waiting}

    def snapshot(self):
        """Counters and the recent calls (ids, times and outcomes; no content)."""
        lanes = self.lanes_snapshot()
        with self.condition:
            return {"limit": self.limit, "inflight": self.inflight, "waiting": self.waiting, "peak_inflight": self.peak,
                    "lanes": lanes, "granted": self.granted, "released": self.released, "refused": self.refused,
                    "calls": [{key: value for key, value in record.items() if key != "started"} for record in self.recent]}


_shared = None
_shared_lock = threading.Lock()


def shared():
    """The process's one gate, built from the environment at its first use: SUHAIL_PROVIDER_MAX_INFLIGHT, capped by the
    number of distinct enabled provider keys (one call in flight per key), on the first lanes those keys make."""
    global _shared
    with _shared_lock:
        if _shared is None:
            requested, lanes = max_inflight(), provider_lanes()
            if requested > len(lanes):
                log.warning("provider limit %d requested but %d distinct provider key(s) configured; limit %d",
                            requested, len(lanes), len(lanes))
            _shared = ProviderGate(min(requested, len(lanes)), names=lanes)
            log.info("provider lanes in use: %s (limit %d of %d distinct enabled key(s))", ",".join(_shared.names),
                     _shared.limit, len(lanes))
        return _shared


def use(gate):
    """Replace the process's gate (a test, or a measurement harness). Returns the one it replaced; None rebuilds it from
    the environment at the next use. Calls in flight keep the gate they started on."""
    global _shared
    with _shared_lock:
        previous, _shared = _shared, gate
        return previous
