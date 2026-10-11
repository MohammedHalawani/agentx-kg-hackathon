"""The hard call-budget guard and its usage ledger (amendment 2 and its addendum).

Every model arm case first RESERVES its worst case (C_cap + R_cap for the agent arm, 3 for B_notools); a reservation
that would take committed calls past the budget is refused before anything is called. After the case the
reservation is SETTLED with the calls the run record reports (the agent arm's one per-case counter; this ledger never
counts the agent's calls a second way). A settle above the reservation means the per-case cap was broken: the ledger
records a violation and stops the run.

The ledger is an append-only JSON-lines file, flushed and fsynced after every entry, so a crash cannot lose the count.
On resume, a reservation that was never settled is counted at its full worst case (its calls may have been made), and
the recovery is written into the ledger. In dry-run mode nothing is reserved against the budget: the ledger records the
plan (what each case would reserve) and checks that the plan fits, and spends zero calls.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path


class BudgetExceeded(RuntimeError):
    """A reservation would exceed the budget; nothing was called."""


class CapViolation(RuntimeError):
    """A case reported more calls than it reserved: the per-case cap did not hold."""


class RunStopped(RuntimeError):
    """The run cannot go on without breaking a guarantee (the backend's cap is not the sealed one, the provider counted
    more calls than the ledger holds, truth vocabulary reached a runtime surface). Never swallowed as an arm error."""


class BudgetLedger:
    def __init__(self, path, budget, *, dry_run=False, resume=False, meta=None):
        self.path = Path(path)
        self.budget = int(budget)
        self.dry_run = dry_run
        self.settled = 0
        self.planned = 0
        self.tokens = 0
        self.open = {}          # reservation id -> (case_key, arm, calls)
        self.done = set()       # (case_key, arm) settled
        self.by_arm = {}
        self.refused = 0
        self.violations = []
        self.recovered = 0
        self.reconciled = 0     # cases after which the ledger was compared with the provider's own count
        self.provider_calls = None
        self.seq = 0
        if self.path.exists():
            if not resume:
                raise FileExistsError(f"{self.path} exists; a run's ledger is never overwritten (resume explicitly)")
            self._replay()
            for rid, (case_key, arm, calls) in sorted(self.open.items()):
                # Counted at its worst case: the calls may have been made before the crash.
                self._write({"event": "crash_recovery", "reservation": rid, "case_key": case_key, "arm": arm, "calls": calls})
                self._settle_state(rid, calls, 0)
                self.recovered += 1
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write({"event": "open", "budget": self.budget, "dry_run": dry_run, **(meta or {})})

    # ------------------------------------------------------------------ persistence
    def _write(self, entry):
        self.seq += 1
        entry = {"seq": self.seq, "at": datetime.now(timezone.utc).isoformat(), **entry}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _replay(self):
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                e = json.loads(line)
                self.seq = max(self.seq, e.get("seq", 0))
                kind = e["event"]
                if kind == "open":
                    if e["budget"] != self.budget or bool(e.get("dry_run")) != self.dry_run:
                        raise ValueError("resume must use the same budget and mode as the ledger it continues")
                elif kind == "reserve":
                    self.open[e["reservation"]] = (e["case_key"], e["arm"], e["calls"])
                elif kind in ("settle", "crash_recovery"):
                    self._settle_state(e["reservation"], e["calls"], e.get("tokens") or 0)
                elif kind == "plan":
                    self.planned += e["calls"]
                elif kind == "refused":
                    self.refused += 1
                elif kind == "violation":
                    self.violations.append(e)
                elif kind == "reconcile":
                    self.reconciled += 1

    def _settle_state(self, rid, calls, tokens):
        case_key, arm, _reserved = self.open.pop(rid)
        self.settled += calls
        self.tokens += tokens
        self.by_arm[arm] = self.by_arm.get(arm, 0) + calls
        self.done.add((case_key, arm))

    # ------------------------------------------------------------------ the guard
    @property
    def committed(self):
        """Calls spent or held: settled calls plus every open reservation at its worst case."""
        return self.settled + sum(c for _, _, c in self.open.values())

    @property
    def remaining(self):
        return self.budget - (self.planned if self.dry_run else self.committed)

    def reserve(self, case_key, arm, calls):
        """Hold `calls` for one arm of one case, or refuse (BudgetExceeded) before anything is called."""
        calls = int(calls)
        if calls < 0:
            raise ValueError("a reservation cannot be negative")
        if self.dry_run:
            if self.planned + calls > self.budget:
                self._write({"event": "refused", "case_key": case_key, "arm": arm, "calls": calls, "dry_run": True})
                self.refused += 1
                raise BudgetExceeded(f"plan would exceed the budget at {case_key}/{arm}")
            self.planned += calls
            self._write({"event": "plan", "case_key": case_key, "arm": arm, "calls": calls})
            return None
        if self.committed + calls > self.budget:
            self._write({"event": "refused", "case_key": case_key, "arm": arm, "calls": calls, "committed": self.committed})
            self.refused += 1
            raise BudgetExceeded(f"{case_key}/{arm} needs {calls} calls; {self.remaining} remain of {self.budget}")
        rid = f"r{self.seq + 1}"
        self.open[rid] = (case_key, arm, calls)
        self._write({"event": "reserve", "reservation": rid, "case_key": case_key, "arm": arm, "calls": calls})
        return rid

    def settle(self, rid, calls_used, *, tokens=None, source="run_record"):
        """Record what the case actually used. Raises CapViolation (after recording it) if above the reservation."""
        if rid is None:     # dry run
            return
        case_key, arm, reserved = self.open[rid]
        if calls_used is None:
            calls_used, source = reserved, "reserved_worst_case (the run record carried no call count)"
        calls_used = int(calls_used)
        if calls_used > reserved:
            entry = {"event": "violation", "reservation": rid, "case_key": case_key, "arm": arm, "reserved": reserved, "calls": calls_used}
            self._write(entry)
            self.violations.append(entry)
            self._write({"event": "settle", "reservation": rid, "case_key": case_key, "arm": arm, "calls": calls_used,
                         "tokens": tokens, "source": source})
            self._settle_state(rid, calls_used, tokens or 0)
            raise CapViolation(f"{case_key}/{arm} used {calls_used} calls against a cap of {reserved}")
        self._write({"event": "settle", "reservation": rid, "case_key": case_key, "arm": arm, "calls": calls_used,
                     "tokens": tokens, "source": source})
        self._settle_state(rid, calls_used, tokens or 0)

    def reconcile(self, case_key, provider_calls, ledger_calls, *, phase="main"):
        """After a case: write the calls this ledger holds for this process beside the calls the provider's callbacks
        counted in it. The ledger is the larger or equal one by construction (a case with no readable count is settled
        at its worst case); a provider count above it means calls were made that no reservation covered, and the run
        stops (RunStopped, after the entry is written)."""
        provider_calls, ledger_calls = int(provider_calls), int(ledger_calls)
        ok = provider_calls <= ledger_calls
        self._write({"event": "reconcile", "case_key": case_key, "phase": phase, "ledger_calls": ledger_calls,
                     "provider_calls": provider_calls, "ok": ok})
        self.reconciled += 1
        self.provider_calls = provider_calls
        if not ok:
            raise RunStopped(f"after {case_key} the provider counted {provider_calls} calls and the ledger holds {ledger_calls}")

    def close(self, status):
        self._write({"event": "close", "status": status, **self.summary()})

    def summary(self):
        return {"budget": self.budget, "dry_run": self.dry_run, "settled_calls": self.settled, "open_reservations": len(self.open),
                "committed_calls": self.committed, "planned_calls": self.planned, "remaining": self.remaining,
                "calls_by_arm": dict(sorted(self.by_arm.items())), "tokens": self.tokens, "refused": self.refused,
                "cap_violations": len(self.violations), "recovered_after_crash": self.recovered,
                "cases_reconciled_with_provider": self.reconciled, "provider_calls_at_last_reconciliation": self.provider_calls}


def read_ledger(path):
    with Path(path).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
