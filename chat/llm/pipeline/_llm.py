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
import json
import logging
import math
import re
from copy import deepcopy
from functools import lru_cache
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_litellm import ChatLiteLLM

import config

log = logging.getLogger("pipeline.llm")

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


@lru_cache(maxsize=1)
def model() -> ChatLiteLLM:
    """One shared, memoized chat model for every pipeline stage - same construction
    chat/llm/agent.py uses, minus streaming (no stage streams; the pipeline reports
    per-stage, not per-token). temperature=0 because every stage is a judgement that should
    be reproducible for the same input, not a creative generation."""
    return ChatLiteLLM(
        model=config.LLM_MODEL,
        api_key=config.LLM_API_KEY,
        api_base=config.LLM_API_BASE,
        temperature=0,
        # A hung provider call must surface as a failure the caller can route, never block forever.
        request_timeout=config.LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )


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


def ask_json(system: str, user: str, default: dict[str, Any]) -> dict:
    """Run one prompt and return the parsed JSON object, falling back to `default` (with a
    logged warning) when the model returns something unparseable. The default is always a
    complete, valid shape for the caller's stage, so a downstream node never has to guard
    against half-populated state."""
    resp = model().invoke([SystemMessage(system), HumanMessage(user)])
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
