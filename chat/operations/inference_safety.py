"""Durable pre-dispatch call/token/cost reservations. No prompts or secrets are stored.

Uses the existing ledger's exclusive-file/atomic-replace convention. A crash, missing
usage, failure or abandoned request keeps its maximum charge. Changing rates or caps
requires an explicitly chosen new ledger; restarting the server never resets spending.
Prices are operator-supplied upper bounds, not provider prices discovered by the app.
"""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import time
import uuid

class SafetyRefused(RuntimeError):
    pass


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


@dataclass(frozen=True)
class Policy:
    calls: int
    tokens: int
    usd: str
    input_rate: str
    output_rate: str
    max_input_bytes: int
    max_output_tokens: int

    @classmethod
    def configured(cls):
        return cls(positive("SUHAIL_INFERENCE_MAX_CALLS", 100, integer=True),
                   positive("SUHAIL_INFERENCE_MAX_TOKENS", 1000000, integer=True),
                   str(positive("SUHAIL_INFERENCE_MAX_USD", "0.50")),
                   str(positive("SUHAIL_INPUT_USD_PER_MILLION")),
                   str(positive("SUHAIL_OUTPUT_USD_PER_MILLION")),
                   positive("SUHAIL_MAX_INPUT_BYTES", 65536, integer=True), output_limit())

    def cost(self, incoming, outgoing):
        return (Decimal(self.input_rate) * incoming + Decimal(self.output_rate) * outgoing) / 1000000


def usage(response):
    data = getattr(response, "usage_metadata", None) or {}
    if not data:
        old = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
        data = {"input_tokens": old.get("prompt_tokens"), "output_tokens": old.get("completion_tokens")}
    pair = data.get("input_tokens"), data.get("output_tokens")
    return pair if all(type(v) is int and v >= 0 for v in pair) else None


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
            return {"schema": "inference-budget-1", "policy": asdict(self.policy), "entries": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["schema"] != "inference-budget-1" or data["policy"] != asdict(self.policy):
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

    def reserve(self, messages, labels, until):
        # UTF-8 bytes plus conservative message framing is an upper token bound for
        # this text-only protocol. Refuse rather than truncate evidence/context.
        incoming = len(json.dumps([getattr(m, "content", m) for m in messages], ensure_ascii=False).encode("utf-8")) + 32 * len(messages) + 256
        if incoming > self.policy.max_input_bytes:
            raise SafetyRefused("Input exceeds the configured conservative token bound")
        tokens = incoming + self.policy.max_output_tokens
        cost = self.policy.cost(incoming, self.policy.max_output_tokens)
        row = {"id": uuid.uuid4().hex, "calls": 1, "tokens": tokens, "usd": str(cost),
               "input_reserved": incoming, "output_reserved": self.policy.max_output_tokens,
               "status": "reserved", "labels": {k: str(v) for k, v in labels.items() if k in ("run_id", "case_id", "role", "worker_id")}}
        with self.locked(until):
            data = self.load()
            entries = data["entries"]
            if (any(e["status"] == "provider_limit_breach" for e in entries) or
                sum(e["calls"] for e in entries) + 1 > self.policy.calls or
                sum(e["tokens"] for e in entries) + tokens > self.policy.tokens or
                sum((Decimal(e["usd"]) for e in entries), Decimal(0)) + cost > Decimal(self.policy.usd)):
                raise SafetyRefused("Aggregate inference call/token/cost reservation refused")
            entries.append(row)
            self._write(data,until=until)
        return row["id"]

    def finish(self, key, *, response=None, dispatched=True, abandoned=False, until=None):
        # Accounting is bounded too. If a crashed writer left a lock, the durable
        # pre-dispatch maximum remains charged and the result is not trusted.
        until=time.monotonic()+1 if until is None else until
        with self.locked(until):
            data = self.load()
            row = next(e for e in data["entries"] if e["id"] == key)
            if row["status"] in ("abandoned", "not_dispatched"):
                return
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
