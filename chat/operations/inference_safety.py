"""Durable pre-dispatch call/token/cost reservations. No prompts or secrets are stored.

Uses the existing ledger's exclusive-file/atomic-replace convention. A crash, missing
usage, failure or abandoned request keeps its maximum charge. Changing rates or caps
requires an explicitly chosen new ledger; restarting the server never resets spending.
Prices are operator-supplied upper bounds, not provider prices discovered by the app.

Per-lane caps (V3.4). Each provider lane (one provider key, operations.provider_gate) may
have its own call/token/cost cap: SUHAIL_INFERENCE_LANE_MAX_CALLS, _TOKENS, _USD (any one
set turns them on; one left unset is the aggregate's value). A reservation names its lane
when it is made, before dispatch, so a process that dies mid-call has already charged that
lane. A row without a lane (written before lanes were recorded at reservation) counts
against every lane. Lane caps are part of the frozen policy only when they are set, so a
ledger written without them stays valid while they stay unset.
"""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import time
import uuid

LANE_CAPS = ("lane_calls", "lane_tokens", "lane_usd")


class SafetyRefused(RuntimeError):
    pass


class ContextLimitExceeded(SafetyRefused):
    """A request whose conservative input bound exceeds SUHAIL_MAX_INPUT_BYTES. Never dispatched and never charged. It is
    not a provider failure: sending the same request again would be refused the same way (V3.4.1)."""

    def __init__(self, size=None, limit=None):
        super().__init__("Input exceeds the configured conservative token bound")
        self.size, self.limit = size, limit


def positive(name, default=None, *, integer=False):
    try:
        value = Decimal(os.environ.get(name, str(default) if default is not None else ""))
        if not value.is_finite() or value <= 0 or (integer and value != int(value)):
            raise ValueError()
        return int(value) if integer else value
    except (InvalidOperation, ValueError, OverflowError):
        raise SafetyRefused(f"Configure a positive {name} before inference") from None


def output_limit():
    value = positive("SUHAIL_MAX_OUTPUT_TOKENS", 2048, integer=True)
    if value > 8192:
        raise SafetyRefused("SUHAIL_MAX_OUTPUT_TOKENS exceeds the 8192 safety ceiling")
    return value


def input_bound(messages):
    """UTF-8 bytes plus conservative message framing: an upper token bound for this text-only protocol."""
    return len(json.dumps([getattr(m, "content", m) for m in messages], ensure_ascii=False).encode("utf-8")) + 32 * len(messages) + 256


def input_limit():
    """SUHAIL_MAX_INPUT_BYTES, read exactly as Policy.configured reads it, so a caller can check a request before dispatch."""
    return positive("SUHAIL_MAX_INPUT_BYTES", 65536, integer=True)


@dataclass(frozen=True)
class Policy:
    calls: int
    tokens: int
    usd: str
    input_rate: str
    output_rate: str
    max_input_bytes: int
    max_output_tokens: int
    lane_calls: int | None = None
    lane_tokens: int | None = None
    lane_usd: str | None = None

    @classmethod
    def configured(cls):
        calls = positive("SUHAIL_INFERENCE_MAX_CALLS", 100, integer=True)
        tokens = positive("SUHAIL_INFERENCE_MAX_TOKENS", 1000000, integer=True)
        usd = str(positive("SUHAIL_INFERENCE_MAX_USD", "0.50"))
        lanes = (None, None, None)
        if any(os.environ.get(name, "").strip() for name in
               ("SUHAIL_INFERENCE_LANE_MAX_CALLS", "SUHAIL_INFERENCE_LANE_MAX_TOKENS", "SUHAIL_INFERENCE_LANE_MAX_USD")):
            lanes = (positive("SUHAIL_INFERENCE_LANE_MAX_CALLS", calls, integer=True),
                     positive("SUHAIL_INFERENCE_LANE_MAX_TOKENS", tokens, integer=True),
                     str(positive("SUHAIL_INFERENCE_LANE_MAX_USD", usd)))
        return cls(calls, tokens, usd,
                   str(positive("SUHAIL_INPUT_USD_PER_MILLION")),
                   str(positive("SUHAIL_OUTPUT_USD_PER_MILLION")),
                   positive("SUHAIL_MAX_INPUT_BYTES", 65536, integer=True), output_limit(), *lanes)

    @property
    def lane_capped(self):
        return self.lane_calls is not None

    def document(self):
        """The frozen form stored in a ledger: lane caps only when they are set (older ledgers have none)."""
        return {key: value for key, value in asdict(self).items() if key not in LANE_CAPS or value is not None}

    def cost(self, incoming, outgoing):
        return (Decimal(self.input_rate) * incoming + Decimal(self.output_rate) * outgoing) / 1000000


def usage(response):
    data = getattr(response, "usage_metadata", None) or {}
    if not data:
        old = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
        data = {"input_tokens": old.get("prompt_tokens"), "output_tokens": old.get("completion_tokens")}
    pair = data.get("input_tokens"), data.get("output_tokens")
    return pair if all(type(v) is int and v >= 0 for v in pair) else None


def _spent(entries):
    return (sum(e["calls"] for e in entries), sum(e["tokens"] for e in entries),
            sum((Decimal(e["usd"]) for e in entries), Decimal(0)))


class InferenceLedger:
    def __init__(self, policy=None, path=None):
        self.policy = policy or Policy.configured()
        self.path = Path(path or os.environ.get("SUHAIL_INFERENCE_LEDGER") or
                         Path(__file__).resolve().parents[2] / ".runtime/inference-budget.json")

    @contextmanager
    def locked(self, until):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        while True:
            if time.monotonic() >= until:
                raise SafetyRefused("Inference deadline expired waiting for budget ledger")
            try:
                handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except (FileExistsError, PermissionError):
                time.sleep(min(.01, max(0, until - time.monotonic())))
        try:
            yield
        finally:
            os.close(handle)
            os.unlink(lock)

    def load(self):
        if not self.path.exists():
            return {"schema": "inference-budget-1", "policy": self.policy.document(), "entries": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["schema"] != "inference-budget-1" or data["policy"] != self.policy.document():
                raise ValueError()
            ids = set()
            for row in data["entries"]:
                if row["id"] in ids or any(type(row[k]) is not int or row[k] < 0 for k in ("calls", "tokens")):
                    raise ValueError()
                ids.add(row["id"])
                cost = Decimal(row["usd"])
                if not cost.is_finite() or cost < 0:
                    raise ValueError()
            return data
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise SafetyRefused("Inference ledger is invalid or its frozen budget/rates changed") from None

    def _write(self, document, *, until):
        temporary = self.path.with_name(self.path.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        while True:
            try:
                os.replace(temporary, self.path)
                break
            except PermissionError:  # Windows can briefly retain a closed read handle.
                if time.monotonic() >= until:
                    raise SafetyRefused("Inference ledger atomic write unavailable") from None
                time.sleep(min(.01,max(0,until-time.monotonic())))

    def _charge(self, messages):
        # Refuse rather than truncate evidence/context.
        incoming = input_bound(messages)
        if incoming > self.policy.max_input_bytes:
            raise ContextLimitExceeded(incoming, self.policy.max_input_bytes)
        return incoming, incoming + self.policy.max_output_tokens, self.policy.cost(incoming, self.policy.max_output_tokens)

    def _aggregate_fits(self, entries, tokens, cost):
        calls, spent_tokens, usd = _spent(entries)
        return (not any(e["status"] == "provider_limit_breach" for e in entries) and calls + 1 <= self.policy.calls and
                spent_tokens + tokens <= self.policy.tokens and usd + cost <= Decimal(self.policy.usd))

    def _lane_fits(self, entries, lane, tokens, cost):
        if not self.policy.lane_capped or lane is None:
            return True
        calls, spent_tokens, usd = _spent([e for e in entries if e.get("lane") in (None, str(lane))])
        return (calls + 1 <= self.policy.lane_calls and spent_tokens + tokens <= self.policy.lane_tokens and
                usd + cost <= Decimal(self.policy.lane_usd))

    def affordable(self, messages, lanes, until):
        """The lanes (of `lanes`, names) whose own budget can pay for this call at its maximum, checked before a lane is
        taken. Raises SafetyRefused when the input is too large or the aggregate budget cannot pay for it at all.
        Advisory: the reservation checks again under the same lock."""
        _, tokens, cost = self._charge(messages)
        with self.locked(until):
            entries = self.load()["entries"]
        if not self._aggregate_fits(entries, tokens, cost):
            raise SafetyRefused("Aggregate inference call/token/cost reservation refused")
        return [lane for lane in lanes if self._lane_fits(entries, lane, tokens, cost)]

    def reserve(self, messages, labels, until, lane=None):
        # UTF-8 bytes plus conservative message framing is an upper token bound for
        # this text-only protocol. Refuse rather than truncate evidence/context.
        incoming, tokens, cost = self._charge(messages)
        row = {"id": uuid.uuid4().hex, "calls": 1, "tokens": tokens, "usd": str(cost),
               "input_reserved": incoming, "output_reserved": self.policy.max_output_tokens,
               "status": "reserved", "labels": {k: str(v) for k, v in labels.items() if k in ("run_id", "case_id", "role", "worker_id")}}
        if lane is not None:     # the lane (provider key, never the key) this call is sent on: charged from now on
            row["lane"] = str(lane)
        with self.locked(until):
            data = self.load()
            entries = data["entries"]
            if not self._aggregate_fits(entries, tokens, cost):
                raise SafetyRefused("Aggregate inference call/token/cost reservation refused")
            if not self._lane_fits(entries, lane, tokens, cost):
                raise SafetyRefused(f"Lane {lane} inference call/token/cost reservation refused")
            entries.append(row)
            self._write(data,until=until)
        return row["id"]

    def finish(self, key, *, response=None, dispatched=True, abandoned=False, until=None, lane=None):
        # Accounting is bounded too. If a crashed writer left a lock, the durable
        # pre-dispatch maximum remains charged and the result is not trusted.
        until=time.monotonic()+1 if until is None else until
        with self.locked(until):
            data = self.load()
            row = next(e for e in data["entries"] if e["id"] == key)
            if row["status"] in ("abandoned", "not_dispatched"):
                return
            if lane is not None and "lane" not in row:   # which provider key (lane A-D, never the key) carried the call
                row["lane"] = str(lane)
            if abandoned:
                row.update(status="abandoned", calls=1, tokens=row["input_reserved"] + row["output_reserved"],
                           usd=str(self.policy.cost(row["input_reserved"], row["output_reserved"])))
            elif not dispatched:
                row.update(calls=0, tokens=0, usd="0", status="not_dispatched")
            else:
                pair = usage(response)
                if pair and pair[0] <= row["input_reserved"] and pair[1] <= row["output_reserved"]:
                    row.update(tokens=sum(pair), usd=str(self.policy.cost(*pair)), status="usage_confirmed")
                else:
                    row["status"] = "maximum_charged"
                    if pair:  # A provider exceeding its advertised limits halts future dispatch.
                        row.update(tokens=max(row["tokens"], sum(pair)),
                                   usd=str(max(Decimal(row["usd"]), self.policy.cost(*pair))), status="provider_limit_breach")
            self._write(data,until=until)
            if row["status"] == "provider_limit_breach":
                raise SafetyRefused("Provider usage exceeded its reservation")

    def read(self, until):
        """The ledger as it is now, for reporting (the lock bounds a reader during an atomic replace on Windows)."""
        with self.locked(until):
            return self.load()

    def summary(self, lanes=(), until=None):
        """Spending so far against the caps, in total and per lane (names in `lanes`, plus any recorded): counts only,
        never labels, prompts or keys. `unattributed` rows have no lane and count against every lane's cap."""
        data = self.read(time.monotonic() + .5 if until is None else until)
        entries = data["entries"]
        def totals(rows):
            calls, tokens, usd = _spent(rows)
            return {"calls": calls, "tokens": tokens, "usd": str(usd)}
        statuses = {}
        for row in entries:
            statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        names = list(dict.fromkeys([*map(str, lanes), *sorted({e["lane"] for e in entries if e.get("lane")})]))
        return {"path_name": self.path.name, "caps": {"calls": self.policy.calls, "tokens": self.policy.tokens, "usd": self.policy.usd},
                "lane_caps": ({"calls": self.policy.lane_calls, "tokens": self.policy.lane_tokens, "usd": self.policy.lane_usd}
                              if self.policy.lane_capped else None),
                "spent": totals(entries), "statuses": statuses,
                "unattributed": totals([e for e in entries if not e.get("lane")]),
                "lanes": {name: totals([e for e in entries if e.get("lane") == name]) for name in names},
                "breached": any(e["status"] == "provider_limit_breach" for e in entries)}

    def headroom(self, calls, lanes=(), until=None):
        """Whether the budget can still pay for `calls` more calls at their maximum (the largest input allowed plus the
        output limit each): the aggregate, and with lane caps the lanes in `lanes` together (an investigation's calls go
        to whichever lane is free). Used to stop automatic investigation before it claims a case it could not finish."""
        data = self.read(time.monotonic() + .5 if until is None else until)
        entries = data["entries"]
        each_tokens = self.policy.max_input_bytes + self.policy.max_output_tokens
        each_cost = self.policy.cost(self.policy.max_input_bytes, self.policy.max_output_tokens)
        spent_calls, spent_tokens, usd = _spent(entries)
        if (any(e["status"] == "provider_limit_breach" for e in entries) or spent_calls + calls > self.policy.calls
                or spent_tokens + calls * each_tokens > self.policy.tokens or usd + calls * each_cost > Decimal(self.policy.usd)):
            return False
        if not self.policy.lane_capped or not lanes:
            return True
        room = 0
        for lane in lanes:
            lane_calls, lane_tokens, lane_usd = _spent([e for e in entries if e.get("lane") in (None, str(lane))])
            room += max(0, min(self.policy.lane_calls - lane_calls, (self.policy.lane_tokens - lane_tokens) // each_tokens,
                               int((Decimal(self.policy.lane_usd) - lane_usd) / each_cost) if each_cost else self.policy.lane_calls))
        return room >= calls
