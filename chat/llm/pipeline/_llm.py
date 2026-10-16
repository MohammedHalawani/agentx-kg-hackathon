"""Shared LLM plumbing for the pipeline's four model-backed stages (extract, classify,
recommend, review).

Every stage needs the same two things - a ChatLiteLLM bound to config.LLM_MODEL, and a JSON
object back - so both live here rather than being re-derived four times.

Why the defensive parsing: LiteLLM routes to the configured local or hosted model, including
Ollama Cloud GPT-OSS. Providers can return final content as blocks, wrap output in ```json
fences, prepend a sentence of preamble, or emit trailing prose. Rather than let that crash a
stage, ask_json() strips fences, scans for the first balanced {...} object, and falls back to
a caller-supplied default so one malformed generation degrades that stage instead of failing
the whole run.
"""
import contextvars
import json
import logging
import math
import os
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_litellm import ChatLiteLLM

import config
from operations import provider_gate

log = logging.getLogger("pipeline.llm")
transport = logging.getLogger("suhail.provider.transport")
context_log = logging.getLogger("suhail.context")   # input-limit decisions: sizes, roles and ids only (V3.4.1)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_PRIVATE_TAG_RE = re.compile(
    r"<(think|thinking|reasoning|analysis)\b[^>]*>.*?(?:</\1\s*>|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_PRIVATE_LABEL_RE = re.compile(
    r"(?:\A|\n)\s*(?:analysis|reasoning|thinking)\s*:\s*.*?"
    r"(?:(?:\n)\s*(?:final|answer)\s*:\s*|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_PRIVATE_TYPES = frozenset({"analysis", "reasoning", "thinking", "redacted_thinking"})
_HARMONY_ALIASES = {"start": "im_start", "channel": "meta_sep", "message": "im_sep",
                    "end": "im_end", "return": "fim_suffix", "call": "ghissue",
                    "constrain": "meta_start"}


def _harmony_final_text(text: str) -> str:
    """Read only final assistant messages from a serialized channel transcript.

    Accept the original im_* tokens, current named aliases and the bracket shorthand.
    A partial channel header is supported, but identified user/tool/recipient messages
    cannot become an operator answer. Recognized incomplete transcripts fail closed.
    """
    text = re.sub(
        r"<\|(im_start|meta_sep|im_sep|im_end|fim_suffix|ghissue|ghreview|meta_start|"
        r"start|channel|message|end|return|call|constrain)\|>",
        lambda m: "[" + _HARMONY_ALIASES.get(m.group(1), m.group(1)) + "]", text)
    if not any(token in text for token in ("[im_start]", "[meta_sep]", "[im_sep]")):
        return text
    finals = []
    for match in re.finditer(
        r"(?:\A(?:\[im_start\])?|\[im_start\])(?P<header>[^\n]*?)\[im_sep\]"
        r"(?P<body>[\s\S]*?)(?=\[im_end\]|\[im_start\]|\[fim_suffix\]|\[ghissue\]|\Z)", text):
        header = match.group("header")
        if "[meta_sep]" not in header:
            continue
        role, channel = header.split("[meta_sep]", 1)
        if role.strip() not in ("", "assistant"):
            continue
        if not re.fullmatch(r"final(?:\[meta_start\][^\[]*)?\s*", channel.strip()):
            continue
        finals.append(match.group("body"))
    return "".join(finals)


def final_text(text: str) -> str:
    """Remove explicitly marked private reasoning; incomplete private sections fail closed.

    Untagged final prose remains intact. This intentionally does not guess whether ordinary
    sentences are reasoning: providers must separate private and final content.
    """
    text = _harmony_final_text(text)
    text = _PRIVATE_TAG_RE.sub("", text)
    # An orphan closing tag indicates a private prefix whose opening tag was omitted.
    text = re.sub(r"\A.*?</(?:think|thinking|reasoning|analysis)\s*>", "", text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = _PRIVATE_LABEL_RE.sub("", text)
    return text.strip()


def message_text(content: Any) -> str:
    """Extract final text only from supported provider shapes; never stringify blocks."""
    if isinstance(content, str):
        return final_text(content)
    if isinstance(content, list):
        return final_text("".join(_content_text(block) for block in content))
    return final_text(_content_text(content))


def _content_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""
    kind = block.get("type")
    if kind is not None and not isinstance(kind, str):
        return ""
    kind = kind.lower() if kind else None
    if kind in _PRIVATE_TYPES or block.get("channel") not in (None, "final"):
        return ""
    if block.get("role") not in (None, "assistant"):
        return ""
    if kind == "message" or (kind is None and "content" in block):
        content = block.get("content")
        return "".join(_content_text(part) for part in content) if isinstance(content, list) else _content_text(content)
    if kind not in (None, "text", "output_text"):
        return ""
    value = block.get("text")
    if isinstance(value, dict):  # OpenAI assistants text.value shape
        value = value.get("value")
    return value if isinstance(value, str) else ""


_model_lock = threading.Lock()


def model(lane: int = 0) -> ChatLiteLLM:
    """One shared, memoized chat model per provider lane for every pipeline stage - same construction
    chat/llm/agent.py uses, minus streaming (no stage streams; the pipeline reports
    per-stage, not per-token). temperature=0 because every stage is a judgement that should
    be reproducible for the same input, not a creative generation.

    Built once, under a lock: two investigations that start together get the same client, never two. The client holds
    configuration only; each call's messages, parameters and callbacks are its own.

    lane: the provider lane (operations.provider_gate), by letter (A to D) or by its place among the configured lanes
    (0 is lane A). Each lane's client uses that lane's key; everything else about the clients is identical."""
    name = lane if isinstance(lane, str) else _lane_name(lane)
    with _model_lock:
        if name not in _clients:
            _clients[name] = _build_model(name)
        return _clients[name]


def _lane_name(index: int) -> str:
    lanes = provider_gate.provider_lanes()
    return lanes[index] if 0 <= index < len(lanes) else lanes[0]


_clients = {}


def _clear_clients():
    with _model_lock:
        _clients.clear()


def lane_key(lane):
    """The provider key of a lane, by letter or by its place among the configured lanes (distinct keys only: a place
    with no distinct key of its own is lane A's key)."""
    return provider_gate.lane_key(lane if isinstance(lane, str) else _lane_name(lane))


def _build_model(lane="A") -> ChatLiteLLM:
    from operations.inference_safety import output_limit
    return ChatLiteLLM(
        model=config.LLM_MODEL,
        api_key=lane_key(lane),
        api_base=config.LLM_API_BASE,
        temperature=0,
        # A hung provider call must surface as a failure the caller can route, never block forever.
        request_timeout=config.LLM_TIMEOUT_SECONDS,
        max_retries=0,
        # ChatLiteLLM's wrapper retry field is not forwarded to LiteLLM's OpenAI
        # transport. Disable SDK retries there too: only the caller owns attempts.
        model_kwargs={"max_retries": 0},
        max_tokens=output_limit(),
    )


model.cache_clear = _clear_clients      # as when model() itself was the cached function


# The wall-clock limit of ONE live model call (an investigator turn, a reviewer call, the no-tools baseline's call).
# request_timeout above is handed to the HTTP client, where it bounds the connection and each wait for more bytes; a
# provider that keeps the connection alive can therefore hold a call far longer than that (a 210 s call was recorded
# with the 120 s setting). `invoke(messages, deadline=...)` is the limit that actually applies: the caller stops
# waiting at the deadline and gets ModelCallTimeout, a TimeoutError, which every caller already treats as a provider
# failure (one retry, then the role fails closed).
# Default 60 s: the measured median is under 6 s per call and a slow provider reaches about 30 s, so 60 s is twice the
# slowest healthy call and still ends a stalled one before a person watching gives up. Set
# SUHAIL_MODEL_CALL_TIMEOUT_SECONDS to change it (5 to 1800 s; anything unreadable is the default).
CALL_TIMEOUT_ENV = "SUHAIL_MODEL_CALL_TIMEOUT_SECONDS"
DEFAULT_CALL_TIMEOUT_SECONDS = 60.0
CALL_TIMEOUT_BOUNDS = (5.0, 1800.0)


class ModelCallTimeout(TimeoutError):
    """One model call did not return within its wall-clock deadline."""


def call_timeout() -> float:
    """The per-call deadline of the live investigator and reviewer calls, in seconds (SUHAIL_MODEL_CALL_TIMEOUT_SECONDS)."""
    try:
        value = float(os.environ.get(CALL_TIMEOUT_ENV, "").strip() or DEFAULT_CALL_TIMEOUT_SECONDS)
    except ValueError:
        value = DEFAULT_CALL_TIMEOUT_SECONDS
    if not math.isfinite(value):
        value = DEFAULT_CALL_TIMEOUT_SECONDS
    return max(CALL_TIMEOUT_BOUNDS[0], min(value, CALL_TIMEOUT_BOUNDS[1]))


class ProviderCapacityTimeout(ModelCallTimeout):
    """No provider slot came free for this call (operations.provider_gate): the limit on calls in flight was reached and
    stayed reached for as long as the call may wait, or the caller's claim was cancelled while it waited. The provider
    was not called. A TimeoutError like ModelCallTimeout, so every caller treats it as the provider failure it is."""


def invoke(messages, *, deadline: float | None = None, client=None, entry: str = "invoke", lane: int | None = None):
    """One provider call. With `deadline` (seconds) the call is abandoned when it has not returned by then and
    ModelCallTimeout is raised. Without an explicit deadline the configured call deadline still applies.
    client: the chat model to call (default: the shared model()). entry: which function made the call, for the log.

    The call runs on its own thread so the wait can end at the deadline whatever the HTTP client is doing. The
    remaining interval, capped by request_timeout, reaches the HTTP client too. An abandoned call cannot be cancelled: if the provider
    still answers, the answer is discarded (the provider's own call count still includes it, as it does a failed call).

    Every call, with or without a deadline, first takes a slot of the process's provider gate
    (SUHAIL_PROVIDER_MAX_INFLIGHT) and holds it until the underlying call has ended. An abandoned call therefore keeps
    its slot after its caller has given up, and a retry cannot start beside it: it waits for a slot, for at most its own
    deadline (the default call timeout when it has none), and raises ProviderCapacityTimeout when none comes free.

    The slot is a lane bound to one provider key (operations.provider_gate); the call uses that lane's own client.
    lane: only that lane (a per-key check); the product leaves it None. A provider answer that forbids the key
    (authentication, permission, rate/plan limit) takes the lane out of service or cools it down; the call is not
    re-sent elsewhere.

    Budget (operations.inference_safety): the input size and the aggregate budget are checked before a lane is taken,
    only lanes whose own budget can pay are asked for, and the call is reserved ON ITS LANE before it is dispatched, so
    a process that dies mid-call has already charged the right key."""
    from operations.inference_safety import ContextLimitExceeded, InferenceLedger, SafetyRefused, input_bound
    # One deadline begins before budget reservation/admission. HTTP execution receives
    # only what remains; it cannot spend a second full timeout after waiting.
    until = time.monotonic() + (call_timeout() if deadline is None else deadline)
    ledger = InferenceLedger()
    labels, cancel = provider_gate.current()
    if not labels.get("role"):
        # The investigation path makes the investigator's turns through invoke and its review through ask_json.
        labels["role"] = ("investigator" if entry == "invoke" else "reviewer") if labels.get("run_id") else entry
    size = input_bound(messages)
    if size > ledger.policy.max_input_bytes:
        # Not dispatched, not charged, and not a provider failure (V3.4.1). Sizes and labels only; never the prompt.
        context_log.warning("context limit: request not dispatched role=%s case=%s run=%s bytes=%d bound=%d",
                            labels.get("role"), labels.get("case_id", "-"), labels.get("run_id", "-"), size,
                            ledger.policy.max_input_bytes)
        raise ContextLimitExceeded(size, ledger.policy.max_input_bytes)
    gate = provider_gate.shared()
    names = tuple(getattr(gate, "names", provider_gate.LANE_NAMES[:getattr(gate, "limit", 1)]))
    lanes = None
    if callable(getattr(type(ledger), "affordable", None)):     # the real ledger (a test may stand in a double)
        wanted = list(names) if lane is None else list(names[lane:lane + 1])
        affordable = set(ledger.affordable(messages, wanted, until))
        lanes = [i for i, name in enumerate(names) if name in affordable]
        if not lanes:
            raise SafetyRefused("Per-lane inference call/token/cost reservation refused on every lane")
    try:
        permit = gate.acquire(max(0, until - time.monotonic()), cancel=cancel, labels=labels, lane=lane,
                              **({} if lanes is None else {"lanes": lanes}))
    except provider_gate.CapacityUnavailable as error:
        raise ProviderCapacityTimeout(f"no provider slot for the call ({error.reason})") from None
    lane = getattr(permit, "lane", 0)
    lane_name = getattr(permit, "name", None) or provider_gate.LANE_NAMES[lane]
    try:
        reservation = ledger.reserve(messages, labels, until, lane=lane_name)
    except BaseException:
        permit.release("not_started")
        raise
    def not_dispatched():
        try:
            ledger.finish(reservation,dispatched=False,until=until)
        except (SafetyRefused,OSError):
            # The conservative reservation remains charged. Cleanup cannot add a
            # second wait or strand a provider slot when no request was dispatched.
            log.warning("Undispatched inference reservation retained; budget reconciliation required")
    if time.monotonic() >= until or (cancel is not None and cancel.is_set()):
        try:
            not_dispatched()
        finally:
            permit.release("not_started")
        raise ProviderCapacityTimeout("no time or claim remains for inference")
    try:
        # The shared client of lane A (what a caller such as translation passes explicitly) means "the shared model":
        # it is replaced by the shared client of the lane this call was given. Any other client is used as given.
        default = client is None or client is _clients.get("A")
        chat = (model(lane_name) if lane_name != "A" else model()) if default else client
    except BaseException:
        try:
            not_dispatched()
        finally:
            permit.release("not_started")
        raise
    outcome = {}
    request_id = getattr(permit, "record", {}).get("request_id", "-")
    abandoned = threading.Event()
    context = contextvars.copy_context()      # callbacks and tracing of the calling thread apply to the call

    def call():
        result = "ok"
        try:
            remaining = until - time.monotonic()
            if remaining <= 0:
                not_dispatched()
                raise ProviderCapacityTimeout("deadline expired before HTTP dispatch")
            # Transport record: the moments the HTTP request is handed to the client and comes back, per lane. Ids,
            # lane and wall times only; never a prompt, a reply or a key.
            transport.info("provider transport dispatch request=%s lane=%s at=%s mono=%.3f", request_id, lane_name,
                           datetime.now(timezone.utc).isoformat(), time.monotonic())
            outcome["sent"] = True
            outcome["response"] = context.run(chat.invoke, messages, timeout=min(remaining,config.LLM_TIMEOUT_SECONDS),
                                              max_tokens=ledger.policy.max_output_tokens)
        except BaseException as error:        # delivered to the caller below, on its own thread
            outcome["error"], result = error, type(error).__name__
            if result in provider_gate.LANE_FAULTS and hasattr(getattr(permit, "gate", None), "fault"):
                permit.gate.fault(lane, result)
        finally:
            if outcome.get("sent"):
                transport.info("provider transport return request=%s lane=%s outcome=%s at=%s mono=%.3f", request_id, lane_name,
                               result, datetime.now(timezone.utc).isoformat(), time.monotonic())
            try:
                ledger.finish(reservation, response=outcome.get("response"), abandoned=abandoned.is_set(), lane=lane_name)
            except BaseException as error:
                outcome["error"] = error  # No trusted result if accounting failed.
            finally:
                permit.release(result)       # only when the underlying call ended, however late

    thread = threading.Thread(target=call, name="model-call", daemon=True)
    try:
        thread.start()
    except BaseException:
        try:
            not_dispatched()
        finally:
            permit.release("not_started")
        raise
    thread.join(max(0, until - time.monotonic()))
    if thread.is_alive():
        abandoned.set()
        permit.abandon()                      # the slot stays taken until the provider call itself ends
        log.warning("Model call abandoned at its shared deadline (%s)", CALL_TIMEOUT_ENV)
        raise ModelCallTimeout("model call exceeded its admission-plus-inference deadline")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["response"]


def _first_json_object(text: str) -> str | None:
    """Scan for the first balanced {...} span, respecting strings/escapes so a brace inside
    a quoted Arabic description doesn't end the object early."""
    start = text.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def parse_json(raw: str) -> dict | None:
    """Best-effort dict out of a model response. Returns None when nothing parses."""
    raw = final_text(raw)
    for candidate in (m.group(1) for m in _FENCE_RE.finditer(raw)):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return None
    except json.JSONDecodeError:
        pass
    span = _first_json_object(raw)
    if span:
        try:
            parsed = json.loads(span)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def ask_json(system: str, user: str, default: dict[str, Any], *, deadline: float | None = None) -> dict:
    """Run one prompt and return the parsed JSON object, falling back to `default` (with a
    logged warning) when the model returns something unparseable. The default is always a
    complete, valid shape for the caller's stage, so a downstream node never has to guard
    against half-populated state. deadline: the call's wall-clock limit in seconds (see invoke)."""
    resp = invoke([SystemMessage(system), HumanMessage(user)], deadline=deadline, entry="ask_json")
    from operations.latency import note_usage   # token counts for the caller's timing record; measurement only
    note_usage(resp)
    raw = message_text(getattr(resp, "content", None))
    parsed = parse_json(raw)
    if parsed is None:
        log.warning("Unparseable final JSON from %s; falling back to default", config.LLM_MODEL)
        return deepcopy(default)
    # The stage's default is its application schema. Extra provider/private fields cannot
    # enter pipeline state, SSE, writeback, or later prompts. Reject wrong-shaped values.
    result = deepcopy(default)
    for key, fallback in default.items():
        value = parsed.get(key, fallback)
        if isinstance(fallback, str) or fallback is None:
            if isinstance(value, str):
                safe = final_text(value)
                result[key] = safe if safe else fallback
            elif value is None and fallback is None:
                result[key] = None
        elif isinstance(fallback, (int, float)) and not isinstance(fallback, bool):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                result[key] = value
        elif isinstance(fallback, list) and isinstance(value, list):
            result[key] = [final_text(item) for item in value if isinstance(item, str) and final_text(item)]
    return result
