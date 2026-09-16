"""Shared LLM plumbing for the pipeline's four model-backed stages (extract, classify,
recommend, review).

Every stage needs the same two things - a ChatLiteLLM bound to config.LLM_MODEL, and a JSON
object back - so both live here rather than being re-derived four times.

Why the defensive parsing: these agents run against a LOCAL model (config.LLM_MODEL is
ollama/gemma4 by default), and small local models are markedly less reliable at honouring
"return only JSON" than a hosted frontier model. They routinely wrap output in ```json
fences, prepend a sentence of preamble, or emit trailing prose. Rather than let that crash a
stage, ask_json() strips fences, scans for the first balanced {...} object, and falls back to
a caller-supplied default so one malformed generation degrades that stage instead of failing
the whole run.
"""
import json
import logging
import re
from functools import lru_cache
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_litellm import ChatLiteLLM

import config

log = logging.getLogger("pipeline.llm")

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


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
    for candidate in (m.group(1) for m in _FENCE_RE.finditer(raw)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    span = _first_json_object(raw)
    if span:
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            return None
    return None


def ask_json(system: str, user: str, default: dict[str, Any]) -> dict:
    """Run one prompt and return the parsed JSON object, falling back to `default` (with a
    logged warning) when the model returns something unparseable. The default is always a
    complete, valid shape for the caller's stage, so a downstream node never has to guard
    against half-populated state."""
    resp = model().invoke([SystemMessage(system), HumanMessage(user)])
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    parsed = parse_json(raw)
    if parsed is None:
        log.warning("Unparseable JSON from %s; falling back to default. Raw: %.300s",
                    config.LLM_MODEL, raw)
        return dict(default)
    return {**default, **parsed}  # default fills any key the model omitted
