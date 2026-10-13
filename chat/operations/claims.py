"""Ownership of a running investigation: one claim per case, a wall-clock lease, and the test every write passes.

Up to SUHAIL_INVESTIGATION_WORKERS (1 or 2) cases are investigated at once. A case is owned by exactly one claim:

  worker_id       who holds it (an investigation loop, or one operator request)
  claim_id        the unique token of this grant; the run id is derived from it
  claim_epoch     counts every change of ownership of the case and never goes back
  lease           wall-clock UTC. The owner renews it every SUHAIL_CLAIM_HEARTBEAT_SECONDS (15 s); a claim that is not
                  renewed for SUHAIL_CLAIM_LEASE_SECONDS (180 s) has expired. The simulation clock, which can pause or
                  run fast, never expires or extends a lease: it only decides what evidence a run may see.

Every write a running investigation makes (a renewal, a progress event, its result, a recommendation, an authorized
action) is checked in its own transaction, under the OpsControl lock that also serialises grants: the case must still be
INVESTIGATING under the same worker, token, epoch and run, with a lease that has not expired (`lost`). An owner that fails
the check has lost the case for good: it cannot renew, cannot release whoever holds the case now, and nothing it
computed is written. Expiry is final even while nobody else has taken the case.

A claim ends in one of the ways named by END_*. Only the first two are the owner's own doing; a run ended any other
way accepts nothing more from the worker that started it.

The store (operations.store) reads and writes the ledger; this module holds the rules and the in-process handle of a
claim (its renewal thread and its cancel signal). The handle only stops waits early. Nothing is decided from it.
"""
from datetime import datetime, timedelta, timezone
import logging
import math
import os
import threading
import uuid

from dataset_v2.contracts import instant
from operations.lifecycle import OperationsConflict

log = logging.getLogger("suhail.claims")

WORKERS_ENV = "SUHAIL_INVESTIGATION_WORKERS"
LEASE_ENV = "SUHAIL_CLAIM_LEASE_SECONDS"
HEARTBEAT_ENV = "SUHAIL_CLAIM_HEARTBEAT_SECONDS"
WORKER_COUNTS = (1, 2)
DEFAULT_WORKERS = 1
DEFAULT_LEASE_SECONDS = 180.0
LEASE_BOUNDS = (1.0, 3600.0)
DEFAULT_HEARTBEAT_SECONDS = 15.0
# An investigation that is lost (its lease ran out, or its worker failed) is queued again automatically. After this many
# losses in a row a person takes the case: nothing is reviewed, accepted or resolved on its behalf.
MAX_RECOVERIES = 2

END_FINISHED = "OWNER_FINISHED"          # the owner committed its result
END_SNAPSHOT = "SNAPSHOT_RELEASED"       # the owner released the case: its evidence snapshot was superseded
END_EXPIRED = "LEASE_EXPIRED"            # nobody renewed the lease
END_FAILED = "WORKER_FAILED"             # the owner's investigation raised
END_PAUSED = "PAUSE_REVOKED"             # an operator paused automatic investigation
END_STOPPED = "WORKER_STOPPED"           # the worker pool was stopped
OWNER_ENDS = frozenset((END_FINISHED, END_SNAPSHOT))
# What identifies the owner of a case. All four must match for a write to be accepted.
IDENTITY = ("claim_id", "claim_epoch", "worker_id", "last_run_id")
# Cleared when a case is released. claim_epoch stays: it is the case's ownership generation.
OWNERSHIP = ("claim_id", "claim_at", "worker_id", "claim_wall_at", "claim_as_of", "lease_expires_at", "lease_heartbeat_at")


class ClaimLost(OperationsConflict):
    """A write by a worker that no longer owns its case. `reason` is one of case_removed, released, superseded,
    lease_expired, run_closed."""

    def __init__(self, reason):
        super().__init__(f"Worker claim was released or superseded ({reason})")
        self.reason = reason


def _number(value, default):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def investigation_workers(value=None):
    """How many cases may be investigated at once: 1 (the default, and the fallback) or 2. Anything else is 1."""
    text = os.environ.get(WORKERS_ENV, "") if value is None else value
    number = _number(text, DEFAULT_WORKERS)
    return int(number) if number in WORKER_COUNTS else DEFAULT_WORKERS


def lease_seconds(value=None):
    """How long a claim lives without a renewal: the store's setting, else the environment, else 180 s (1 s to 1 h)."""
    text = os.environ.get(LEASE_ENV, "").strip() or DEFAULT_LEASE_SECONDS if value is None else value
    number = _number(text, DEFAULT_LEASE_SECONDS)
    if number <= 0:
        number = DEFAULT_LEASE_SECONDS
    return max(LEASE_BOUNDS[0], min(number, LEASE_BOUNDS[1]))


def heartbeat_seconds(lease, value=None):
    """How often the owner renews: the store's setting, else the environment, else 15 s; never more than a third of
    the lease, so two renewals in a row may fail before the claim is at risk."""
    text = os.environ.get(HEARTBEAT_ENV, "").strip() or DEFAULT_HEARTBEAT_SECONDS if value is None else value
    number = _number(text, DEFAULT_HEARTBEAT_SECONDS)
    if number <= 0:
        number = DEFAULT_HEARTBEAT_SECONDS
    return min(number, lease / 3)


def wall_now():
    return datetime.now(timezone.utc)


def operator_worker():
    """The owner name of one operator request (a manual step, a named case, a re-analysis): unique per request."""
    return "manual-" + uuid.uuid4().hex[:8]


def expires_at(now, lease):
    return (now + timedelta(seconds=lease)).isoformat()


def expired(case, now):
    """A claim with no lease on record (written before leases existed) counts as expired."""
    lease = case.get("lease_expires_at")
    return not lease or instant(str(lease)) <= now


def live(case, now):
    return case.get("workflow_state") == "INVESTIGATING" and bool(case.get("claim_id")) and not expired(case, now)


def lost(case, claimed, now):
    """Why `claimed` no longer owns `case` (the case as it is in the ledger now), or None while it does."""
    if not case:
        return "case_removed"
    if case.get("workflow_state") != "INVESTIGATING" or not case.get("claim_id"):
        return "released"
    if any(case.get(key) != claimed.get(key) for key in IDENTITY):
        return "superseded"
    if expired(case, now):
        return "lease_expired"
    return None


def closed_by_owner(run, claimed):
    """Whether `run` is the claim's own run, ended by its owner: the only run that accepts that worker's last events."""
    return (bool(run) and run.get("end_reason") in OWNER_ENDS and run.get("entity_id") == claimed.get("last_run_id")
            and all(run.get(key) == claimed.get(key) for key in ("claim_id", "claim_epoch", "worker_id")))


def release(case, *, revoked=True):
    """Take ownership off a case record. revoked: the case was taken from its owner (expiry, failure, pause, stop), so
    the epoch moves on at once and whatever that owner still holds is out of date before anyone else is granted the
    case. An owner ending its own claim leaves the epoch as it is; the next grant advances it."""
    case.update({key: None for key in OWNERSHIP})
    if revoked:
        case["claim_epoch"] = (case.get("claim_epoch") or 0) + 1
    return case


class Handle:
    """One live claim inside this process: the claimed case as granted, a cancel signal and its renewal thread.

    `cancelled` is set when the claim is known to be lost or is being given up (a failed renewal, a pause, a stop). It
    ends waits early (operations.provider_gate); every write is still checked against the ledger."""

    def __init__(self, claimed):
        self.claimed = claimed
        self.cancelled = threading.Event()
        self.stopped = threading.Event()
        self.thread = None

    def start(self, renew, interval):
        """Renew every `interval` seconds until stopped. A renewal that finds the claim lost cancels the handle and
        ends; any other failure is retried at the next beat (the lease runs out if it keeps failing)."""
        def beat():
            while not self.stopped.wait(interval):
                try:
                    renew(self.claimed)
                except ClaimLost as error:
                    log.warning("Claim on %s lost (%s); its worker stops at its next write", self.claimed["entity_id"], error.reason)
                    self.cancelled.set()
                    return
                except Exception as error:       # Type only: no driver text in logs.
                    log.warning("Claim renewal for %s failed (%s); retrying", self.claimed["entity_id"], type(error).__name__)
        self.thread = threading.Thread(target=beat, name="suhail-claim-" + str(self.claimed.get("worker_id")), daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.stopped.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(2)
