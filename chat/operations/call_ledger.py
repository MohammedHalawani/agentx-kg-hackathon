"""One persistent model-call ledger for the evaluation campaign.

The ledger's `cap` is a runaway guard, not a budget: the 4,000-call allowance it once held was lifted (2026-10-11),
and the number in the file is now only the line no run may cross by accident (20,000 in the committed file; change
it there, with a note). What stays is the accounting: every real call is entered, a run holds its worst case while it
is going, and a crashed run stays counted at that worst case.

Every run that makes real model calls (the pilot, its re-runs, the Stage 3 evaluation run) goes through this file:

    ledger = CallLedger()                      # docs/evals/model_call_ledger.json, or SUHAIL_CALL_LEDGER
    ledger.reserve(run, maximum, commit=...)   # refused (LedgerRefused) if spent + maximum would cross the guard
    ...the run, under its own cap of `maximum` calls...
    ledger.settle(run, calls, tokens=...)      # what it actually used

The file is committed JSON: {"schema", "campaign", "cap", "entries": [{run, started_at, finished_at, commit, calls,
tokens, note, reserved}]}. An entry's `calls` is what counts against the cap. A reservation writes the run's own
maximum there with `finished_at: null`; settling replaces it with the calls actually made. A run that crashes never
settles, so it stays counted at its worst case until a person corrects the entry by hand, with a note.

`spent` is the sum of `calls`; `remaining` is cap - spent. The file is rewritten atomically (temporary file, fsync,
replace) under a lock file, so two runs cannot both take the last calls. Standard library only; no model, no database.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

SCHEMA = "model-call-ledger-1"
CAMPAIGN_CAP = 20000   # The guard a new ledger file starts with; the file's own "cap" is what is enforced.
LEDGER_ENV = "SUHAIL_CALL_LEDGER"
# Relative to the repository root; git status checks leave this file out, because a run rewrites it by design.
LEDGER_RELATIVE = "docs/evals/model_call_ledger.json"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / LEDGER_RELATIVE


class LedgerRefused(RuntimeError):
    """The run may not start: its maximum does not fit in what is left of the campaign cap. Nothing was called."""


class LedgerError(RuntimeError):
    """The ledger file is missing, malformed or does not hold the entry asked for."""


def ledger_path(path=None):
    return Path(path or os.environ.get(LEDGER_ENV) or DEFAULT_PATH)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _count(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LedgerError(f"{what} must be a whole number of calls, zero or more")
    return value


def validate(document):
    """The ledger document, checked. Raises LedgerError on anything a run could miscount from."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise LedgerError(f"not a {SCHEMA} file")
    _count(document.get("cap"), "cap")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise LedgerError("entries must be a list")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("run"), str) or not entry["run"]:
            raise LedgerError("every entry needs a run name")
        if entry["run"] in seen:
            raise LedgerError(f"run {entry['run']} is entered twice")
        seen.add(entry["run"])
        _count(entry.get("calls"), f"calls of {entry['run']}")
    return document


class CallLedger:
    def __init__(self, path=None):
        self.path = ledger_path(path)

    # ------------------------------------------------------------------ reading
    def load(self):
        try:
            return validate(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise LedgerError(f"{self.path} is missing; a run that makes model calls needs the campaign ledger") from None
        except json.JSONDecodeError as error:
            raise LedgerError(f"{self.path} is not valid JSON ({error})") from None

    @property
    def cap(self):
        return self.load()["cap"]

    @property
    def spent(self):
        """Calls counted against the cap: settled runs at what they used, unfinished runs at their maximum."""
        return sum(entry["calls"] for entry in self.load()["entries"])

    @property
    def remaining(self):
        document = self.load()
        return document["cap"] - sum(entry["calls"] for entry in document["entries"])

    def entry(self, run):
        return next((dict(e) for e in self.load()["entries"] if e["run"] == run), None)

    def summary(self):
        document = self.load()
        spent = sum(e["calls"] for e in document["entries"])
        return {"path": str(self.path), "cap": document["cap"], "spent": spent, "remaining": document["cap"] - spent,
                "runs": len(document["entries"]), "open_reservations": [e["run"] for e in document["entries"] if not e.get("finished_at")]}

    def check(self, maximum):
        """Raise LedgerRefused if a run of at most `maximum` calls would not fit; returns what remains. Writes nothing."""
        maximum = _count(maximum, "a run's maximum")
        document = self.load()
        spent = sum(e["calls"] for e in document["entries"])
        if spent + maximum > document["cap"]:
            raise LedgerRefused(f"refused: {spent} of {document['cap']} campaign model calls are spent or reserved; "
                                f"a run of up to {maximum} calls would exceed the cap ({document['cap'] - spent} remain)")
        return document["cap"] - spent

    # ------------------------------------------------------------------ writing
    @contextmanager
    def _locked(self):
        lock = self.path.with_name(self.path.name + ".lock")
        deadline = time.monotonic() + 30
        while True:
            try:
                handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise LedgerError(f"{lock} is held; another run is writing the ledger (remove it if that run is gone)") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            os.close(handle)
            os.unlink(lock)

    def _write(self, document):
        validate(document)
        temporary = self.path.with_name(self.path.name + ".tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Windows may briefly deny replacement while a closed file is still held
        # by a filesystem observer. Keep the sealed temporary file and our lock;
        # never publish a partial write or release a reservation to make it pass.
        replace_until = time.monotonic() + 1.0
        while True:
            try:
                os.replace(temporary, self.path)
                break
            except PermissionError:
                if time.monotonic() >= replace_until:
                    raise LedgerError("Atomic ledger replacement unavailable; the previous document is unchanged") from None
                time.sleep(0.01)

    def reserve(self, run, maximum, *, commit=None, note="", resume=False):
        """Hold `maximum` calls for `run` before it starts, or refuse (LedgerRefused) and write nothing.

        A run name is entered once. With resume=True an existing entry of that name is taken up again (a crashed run
        continuing in the same place): it is counted at `maximum` again, never added a second time."""
        maximum = _count(maximum, "a run's maximum")
        with self._locked():
            document = self.load()
            existing = next((e for e in document["entries"] if e["run"] == run), None)
            if existing is not None and not resume:
                raise LedgerError(f"run {run} is already in the ledger; every run has its own name")
            others = sum(e["calls"] for e in document["entries"] if e is not existing)
            if others + maximum > document["cap"]:
                raise LedgerRefused(f"refused: {others} of {document['cap']} campaign model calls are spent or reserved; "
                                    f"{run} may use up to {maximum} and would exceed the cap ({document['cap'] - others} remain)")
            if existing is None:
                existing = {"run": run, "started_at": _now(), "finished_at": None, "commit": commit, "calls": maximum, "tokens": None,
                            "note": note, "reserved": maximum}
                document["entries"].append(existing)
            else:
                existing.update(finished_at=None, calls=maximum, reserved=maximum,
                                note="; ".join(p for p in (existing.get("note"), f"resumed {_now()}") if p))
            self._write(document)
            return dict(existing)

    def settle(self, run, calls, *, tokens=None, note=None):
        """Replace the reservation of `run` with the calls it actually made. A count above the reservation is recorded
        as it is (the ledger tells the truth) and marked."""
        calls = _count(calls, "calls")
        with self._locked():
            document = self.load()
            entry = next((e for e in document["entries"] if e["run"] == run), None)
            if entry is None:
                raise LedgerError(f"run {run} has no reservation in the ledger")
            entry.update(finished_at=_now(), calls=calls, tokens=tokens)
            if note:
                entry["note"] = "; ".join(p for p in (entry.get("note"), note) if p)
            if entry.get("reserved") is not None and calls > entry["reserved"]:
                entry["over_reservation"] = True
            self._write(document)
            return dict(entry)


@contextmanager
def reserved_run(run, maximum, *, commit=None, note="", path=None, resume=False):
    """Reserve `maximum` calls for the body, which reports what it used by calling the yielded function once:

        with reserved_run("pilot ...", 144, commit=commit) as used:
            ...
            used(calls, tokens)

    Refused before the body if the maximum does not fit. If the body raises, or never reports, the reservation stays
    counted at its maximum (the calls may have been made)."""
    ledger = CallLedger(path)
    ledger.reserve(run, maximum, commit=commit, note=note, resume=resume)
    report = {}

    def used(calls, tokens=None, note=None):
        report.update(calls=calls, tokens=tokens, note=note)

    yield used
    if report:
        ledger.settle(run, report["calls"], tokens=report["tokens"], note=report["note"])
