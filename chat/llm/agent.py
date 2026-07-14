"""LangGraph ReAct agent with exactly two tools - neither writes or generates Cypher.

`mandates_vs_attendance` runs one frozen, pre-vetted query (Q32) from the catalog.
`show_on_map` is the "let me see for myself" tool: it never answers a specific question,
it just plots the current incidents/track-status points (with photos where the layer has
them) so the user can look at the raw situation directly. Everything else the graph could
answer lives on the Dashboard or the Filter tab instead - this is deliberately a small,
forward-looking showcase of natural-language querying, not the main interface.
"""
import json
import logging
from functools import lru_cache
from time import perf_counter

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM
from langgraph.prebuilt import create_react_agent

import config
from core import csv_data, query_runner

_SYSTEM = (
    "You answer questions about a steering-committee governance graph (mandates, tracks, "
    "committees, people, budgets) and about field data plotted on a map (incidents, "
    "track-status visits with real photos). You have exactly two tools; most questions "
    "about the graph are NOT answerable here - they live on the Dashboard or the Filter "
    "tab in this app, so say that plainly rather than guessing or inventing a query.\n\n"
    "Tools:\n"
    "- mandates_vs_attendance(): the one analytical question this chat can answer - which "
    "people are given mandates but rarely attend the meetings where those mandates are "
    "issued. Call this ONLY when the question matches that, not for any other mandate "
    "question.\n"
    "- show_on_map(layer): call this when the user wants to visually inspect the current "
    "situation for themselves rather than get a computed answer - e.g. 'show me the visual "
    "status', 'let me see what's happening', 'show me the data points on a map', 'where are "
    "the field visits'. Pass layer='incidents', 'track_status', or 'both' depending on what "
    "they asked to see; default to 'both' when unclear.\n\n"
    "Give a grounded, informative answer (2-4 sentences) using only values the tools "
    "returned, no speculation. Write for a non-technical reader: plain business language, "
    "no database jargon. If neither tool fits the question, say this chat only handles the "
    "attendance/mandate pattern and visual map lookups, and point to the Dashboard or "
    "Filter tab for anything else."
)


@tool(response_format="content_and_artifact")
def mandates_vs_attendance():
    """Which people are given mandates but rarely attend the meetings where those mandates
    are issued - the one fixed analytical question this chat can answer (catalog id Q32)."""
    rows = query_runner.run("Q32")
    sample = json.dumps(rows[:30], default=str)
    more = f" (showing first 30 of {len(rows)})" if len(rows) > 30 else ""
    summary = f"{len(rows)} row(s){more}: {sample}"
    return summary, {"tool": "mandates_vs_attendance", "rows": rows}


@tool(response_format="content_and_artifact")
def show_on_map(layer: str = "both"):
    """Plot the current incidents and/or track-status visits (with real photos where the
    layer has them) so the user can see the raw situation themselves. layer is one of
    'incidents', 'track_status', or 'both'."""
    points: list[dict] = []
    if layer in ("incidents", "both"):
        points += csv_data.incidents()
    if layer in ("track_status", "both"):
        points += csv_data.track_status()
    note = f" {len(points)} mapped." if points else " No data points found."
    summary = f"Showing {layer} on the map.{note}"
    return summary, {"tool": "show_on_map", "incidents": points}


# memoize the single agent graph - it is expensive to construct and is reused per request
@lru_cache(maxsize=1)
def _agent():
    model = ChatLiteLLM(
        model=config.LLM_MODEL,
        api_key=config.LLM_API_KEY,
        api_base=config.LLM_API_BASE,
        temperature=0,
        streaming=True,
    )
    return create_react_agent(model, [mandates_vs_attendance, show_on_map], prompt=_SYSTEM)


class _LLMTimer(BaseCallbackHandler):
    """Sum wall time across the run's model calls, for the timing panel."""

    def __init__(self) -> None:
        self.llm_ms = 0.0
        self._start: dict = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs) -> None:
        self._start[run_id] = perf_counter()

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        self._start[run_id] = perf_counter()

    def _end(self, run_id) -> None:
        t = self._start.pop(run_id, None)
        if t is not None:
            self.llm_ms += (perf_counter() - t) * 1000

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        self._end(run_id)

    def on_llm_error(self, error, *, run_id, **kwargs) -> None:
        self._end(run_id)


def _trace(messages: list) -> list[dict]:
    steps = []
    for m in messages:
        for call in getattr(m, "tool_calls", None) or []:
            steps.append({"tool": call["name"], "args": call["args"]})
    return steps


HISTORY_TOKEN_BUDGET = 1500


def _prior(history: list[tuple[str, str]] | None) -> list:
    msgs = [
        AIMessage(text) if role == "assistant" else HumanMessage(text)
        for role, text in (history or [])
    ]
    return trim_messages(
        msgs,
        strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=HISTORY_TOKEN_BUDGET,
        start_on="human",
        include_system=False,
    )


def _this_turn(messages: list) -> list:
    last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    return messages[last_human:]


def _answer_of(turn: list) -> str:
    return next(
        (m.content for m in reversed(turn) if isinstance(m, AIMessage) and m.content),
        "I couldn't find an answer.",
    )


def _finalize(turn: list, timer: "_LLMTimer", usage: UsageMetadataCallbackHandler, total_ms: int) -> dict:
    artifact = next(
        (m.artifact for m in reversed(turn)
         if isinstance(m, ToolMessage) and getattr(m, "artifact", None)),
        None,
    )
    if not artifact:
        return {}
    artifact["trace"] = json.dumps(_trace(turn), indent=2)
    t = artifact.setdefault("timing", {})
    t["total_ms"] = total_ms
    t["agent_llm_ms"] = round(timer.llm_ms)
    t["llm_tokens"] = sum(u.get("total_tokens", 0) for u in usage.usage_metadata.values())
    return artifact


_TOOL_STEPS = {
    "mandates_vs_attendance": "Checking mandate/attendance pattern",
    "show_on_map": "Finding locations to map",
}


def _step_of(tool_call: dict) -> dict:
    name = tool_call.get("name", "")
    args = tool_call.get("args") or {}
    parts = [", ".join(map(str, v)) if isinstance(v, list) else str(v)
             for v in args.values() if v not in (None, "", [], {})]
    return {"tool": name, "label": _TOOL_STEPS.get(name, name), "detail": " · ".join(parts)}


def _reasoning_delta(msg) -> str:
    extra = getattr(msg, "additional_kwargs", None) or {}
    rc = extra.get("reasoning_content") or extra.get("reasoning")
    return rc if isinstance(rc, str) else ""


def stream_agent(question: str, history: list[tuple[str, str]] | None = None):
    """Generator: yields ('step', {...}) as the agent calls each tool, ('token', str) for
    the answer as the model writes it, then ('artifact', extras) at the end."""
    timer, usage = _LLMTimer(), UsageMetadataCallbackHandler()
    t0 = perf_counter()
    final_state, streamed = None, ""
    for mode, chunk in _agent().stream(
        {"messages": _prior(history) + [HumanMessage(question)]},
        config={"callbacks": [timer, usage]},
        stream_mode=["messages", "updates", "values"],
    ):
        if mode == "messages":
            msg, meta = chunk
            if meta.get("langgraph_node") == "agent" and isinstance(msg, AIMessageChunk):
                reasoning = _reasoning_delta(msg)
                if reasoning:
                    yield ("reasoning", reasoning)
                text = msg.content if isinstance(msg.content, str) else ""
                if text:
                    streamed += text
                    yield ("token", text)
        elif mode == "updates":
            for node, update in (chunk or {}).items():
                if node != "agent" or not isinstance(update, dict):
                    continue
                for m in update.get("messages", []):
                    for tool_call in getattr(m, "tool_calls", None) or []:
                        yield ("step", _step_of(tool_call))
        else:
            final_state = chunk
    total_ms = round((perf_counter() - t0) * 1000)
    turn = _this_turn(final_state["messages"]) if final_state else []
    if not streamed:
        yield ("token", _answer_of(turn))
    yield ("artifact", _finalize(turn, timer, usage, total_ms))


def run_agent(question: str, history: list[tuple[str, str]] | None = None) -> tuple[str, dict]:
    """Non-streaming variant, stateless when history is omitted - used by tests/evals."""
    timer, usage = _LLMTimer(), UsageMetadataCallbackHandler()
    t0 = perf_counter()
    result = _agent().invoke(
        {"messages": _prior(history) + [HumanMessage(question)]},
        config={"callbacks": [timer, usage]},
    )
    total_ms = round((perf_counter() - t0) * 1000)
    turn = _this_turn(result["messages"])
    return _answer_of(turn), _finalize(turn, timer, usage, total_ms)
