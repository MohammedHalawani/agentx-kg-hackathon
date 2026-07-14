"""FastAPI backend for the steering-committee governance chat + dashboard + filter + map app.

Three independent data paths, none of which generate Cypher on the fly:
- /chat streams the two-tool LLM agent (chat/llm/agent.py) over SSE.
- /dashboard and /filter/* run frozen, pre-vetted queries from docs/queries.txt
  (chat/core/queries.py + query_runner.py) - no LLM involved.
- /incidents and /track-status parse the three map CSVs directly (chat/core/csv_data.py) -
  no Neo4j involved.
"""
import asyncio
import json
import logging
import sys
import threading
from collections import OrderedDict
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

# reuse the chat package (agent, queries, registry, csv_data) without copying it
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "chat"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from neo4j.exceptions import ServiceUnavailable
from pydantic import BaseModel, Field

import config
from core import csv_data, queries, query_runner, registry, threads
from llm.agent import stream_agent
from view import subgraph

log = logging.getLogger("steerco-kg")
app = FastAPI(title="Steering-Committee Governance KG")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(max_length=4000)
    history: list[Turn] = Field(default_factory=list, max_length=20)
    thread_id: str | None = Field(default=None, max_length=64)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


class _SafeJSON(JSONResponse):
    # node/row properties can hold neo4j temporal values the default encoder rejects
    def render(self, content: object) -> bytes:
        return json.dumps(content, default=str).encode("utf-8")


def _remember(thread_id: str | None, role: str, content: str, artifact: dict | None = None) -> None:
    if not thread_id:
        return
    try:
        threads.append_message(thread_id, role, content, artifact)
    except Exception:
        log.exception("failed to persist chat message to memory")


# Answer cache: the exact same question returns its previous answer + artifact, skipping the
# agent. Keyed on the trimmed question text alone - in-process only, lost on restart.
_ANSWER_CACHE_MAX = 128
_answer_cache: "OrderedDict[str, dict]" = OrderedDict()
_answer_cache_lock = threading.Lock()


def _cache_get(message: str) -> dict | None:
    key = message.strip()
    with _answer_cache_lock:
        hit = _answer_cache.get(key)
        if hit is not None:
            _answer_cache.move_to_end(key)
        return hit


def _cache_put(message: str, answer: str, artifact: dict | None) -> None:
    key = message.strip()
    with _answer_cache_lock:
        _answer_cache[key] = {"answer": answer, "artifact": artifact}
        _answer_cache.move_to_end(key)
        while len(_answer_cache) > _ANSWER_CACHE_MAX:
            _answer_cache.popitem(last=False)


async def _stream(req: ChatRequest) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    DONE = object()
    history = [(t.role, t.content) for t in req.history]
    parts: list[str] = []
    last_artifact: dict | None = None

    def produce() -> None:
        nonlocal last_artifact
        _remember(req.thread_id, "user", req.message)

        cached = _cache_get(req.message)
        if cached is not None:
            loop.call_soon_threadsafe(queue.put_nowait, ("token", cached["answer"]))
            if cached["artifact"] is not None:
                loop.call_soon_threadsafe(queue.put_nowait, ("artifact", cached["artifact"]))
            _remember(req.thread_id, "assistant", cached["answer"], cached["artifact"])
            loop.call_soon_threadsafe(queue.put_nowait, DONE)
            return

        errored = False
        try:
            for kind, payload in stream_agent(req.message, history):
                if kind == "token":
                    parts.append(payload)
                if kind == "artifact":
                    last_artifact = payload or None
                    item = ("artifact", last_artifact)
                else:
                    item = (kind, payload)
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except ServiceUnavailable:
            errored = True
            loop.call_soon_threadsafe(
                queue.put_nowait, ("error", "The graph database isn't reachable right now.")
            )
        except Exception:
            errored = True
            log.exception("chat request failed")
            loop.call_soon_threadsafe(
                queue.put_nowait, ("error", "Something went wrong answering that. Please try again.")
            )
        finally:
            if parts:
                answer = "".join(parts)
                if not errored:
                    _cache_put(req.message, answer, last_artifact)
                _remember(req.thread_id, "assistant", answer, last_artifact)
            loop.call_soon_threadsafe(queue.put_nowait, DONE)

    worker = asyncio.create_task(asyncio.to_thread(produce))
    try:
        while True:
            item = await queue.get()
            if item is DONE:
                break
            kind, payload = item
            if kind == "token":
                yield _sse("text", {"text": payload})
            elif kind == "reasoning":
                yield _sse("reasoning", {"text": payload})
            elif kind == "step":
                yield _sse("step", payload)
            elif kind == "artifact":
                yield _sse("artifact", payload or {"tool": None})
            elif kind == "error":
                yield _sse("error", {"message": payload})
        yield _sse("done", {})
    finally:
        await worker


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/samples")
def samples() -> dict:
    """Discovery chips for the chat - just the one conversational query plus the map
    lookup, since chat is deliberately small (see llm/agent.py)."""
    return {"groups": [{"label": "Ask", "questions": [
        "Which people are given mandates but rarely attend the meetings where they're issued?",
        "Show me the visual status on the map",
    ]}]}


@app.get("/meta")
def meta() -> dict:
    return {"counts": None, "scope": "Steering-committee mandate & governance tracking"}


# --- Dashboard: every query, live for the param-free ones, a shortcut card for the rest ------

@app.get("/dashboard")
def dashboard() -> Response:
    tiles = []
    for qid in queries.dashboard_ids():
        q = queries.get(qid)
        if q.needs_params:
            tiles.append({
                "id": qid, "title": q.title, "question": q.question_en,
                "live": False, "params": q.params,
            })
        else:
            tiles.append({
                "id": qid, "title": q.title, "question": q.question_en,
                "live": True, "rows": query_runner.run(qid),
            })
    return _SafeJSON({"tiles": tiles})


# --- Filter tab: every query, as a card; params rendered from their derived kind ------------

@app.get("/filter/catalog")
def filter_catalog() -> dict:
    return {"queries": [
        {
            "id": q.id,
            "title": q.title,
            "question_en": q.question_en,
            "question_ar": q.question_ar,
            "params": [queries.param_meta(p) for p in q.params],
        }
        for q in queries.catalog().values()
    ]}


@app.get("/filter/{qid}")
def run_filter(qid: str, request: Request) -> Response:
    try:
        q = queries.get(qid)
    except KeyError:
        raise HTTPException(404, f"Unknown query id {qid!r}")
    params = {p: (request.query_params.get(p) or None) for p in q.params}
    rows = query_runner.run(qid, params)
    return _SafeJSON({"rows": rows})


@app.get("/registry/{label}")
def registry_lookup(label: str, q: str | None = None) -> Response:
    try:
        return _SafeJSON({"options": registry.registry_options(label, q=q)})
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# --- Explore: Graph and Schema lenses -------------------------------------------------------

@app.get("/graph")
def graph() -> Response:
    """A fresh, connected cross-section of the domain graph for the Explore graph view."""
    return _SafeJSON(subgraph.connected_sample_graph() or {"nodes": [], "relationships": []})


@app.get("/schema")
def schema_view() -> dict:
    """The data model as a graph for the Schema view."""
    return query_runner.schema_graph()


# --- Map: parsed straight from CSV, independent of Neo4j ------------------------------------

@app.get("/incidents")
def incidents() -> dict:
    return {"incidents": csv_data.incidents()}


@app.get("/track-status")
def track_status() -> dict:
    return {"trackStatus": csv_data.track_status()}


# --- conversation memory (persisted in Neo4j; see core.threads) ----------------------------

@app.get("/threads")
def threads_list() -> Response:
    return _SafeJSON({"threads": threads.list_threads()})


@app.get("/threads/{thread_id}")
def thread_get(thread_id: str) -> Response:
    return _SafeJSON({"messages": threads.get_thread(thread_id)})


@app.delete("/threads/{thread_id}")
def thread_delete(thread_id: str) -> dict:
    threads.delete_thread(thread_id)
    return {"ok": True}


# Photos referenced by the track-status CSV (picture_1/picture_2) live under PHOTOS_DIR;
# the graph is never involved. Mounted read-only, before the SPA catch-all.
if config.PHOTOS_DIR and Path(config.PHOTOS_DIR).is_dir():
    app.mount("/photos", StaticFiles(directory=config.PHOTOS_DIR), name="photos")

# Production is the only mode: the backend serves the built frontend from the SAME origin.
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
