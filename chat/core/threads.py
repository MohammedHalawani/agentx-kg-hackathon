"""Conversation memory, persisted in Neo4j.

Chat threads and their messages are stored as a small graph - (:ChatThread)-[:HAS_MESSAGE]->
(:ChatMessage) - in a SEPARATE database (config.CHAT_DATABASE) from the domain graph, so chat
history never pollutes the knowledge-graph census or Explore views. Best-effort by design: the
caller treats persistence failures as non-fatal so a memory hiccup never breaks answering.

Concurrent writers on one thread DO happen (stop-then-reask: the aborted turn's worker is still
finishing while the next turn starts). The count-based seq stays collision-free because
`SET t.updated_at` takes a write lock on the thread node, serializing appends per thread.
"""
import json

from neo4j import RoutingControl

import config
from core.query_runner import get_driver

TITLE_MAX = 60
_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    get_driver().execute_query(
        "CREATE CONSTRAINT chat_thread_id IF NOT EXISTS FOR (t:ChatThread) REQUIRE t.id IS UNIQUE",
        database_=config.CHAT_DATABASE,
    )
    _schema_ready = True


# Only a USER message may create the thread (and set its title, once). Any other role appends via
# MATCH, so it no-ops when the thread is gone.
_APPEND_USER = """
CYPHER 25
MERGE (t:ChatThread {id: $id})
  ON CREATE SET t.created_at = datetime()
SET t.updated_at = datetime()
WITH t
CALL (t) { MATCH (t)-[:HAS_MESSAGE]->(m:ChatMessage) RETURN count(m) AS seq }
CREATE (t)-[:HAS_MESSAGE]->(:ChatMessage {
  seq: seq, role: $role, content: $content, artifact_json: $artifact_json, created_at: datetime()
})
WITH t WHERE t.title IS NULL
SET t.title = $title
"""

_APPEND_OTHER = """
CYPHER 25
MATCH (t:ChatThread {id: $id})
SET t.updated_at = datetime()
WITH t
CALL (t) { MATCH (t)-[:HAS_MESSAGE]->(m:ChatMessage) RETURN count(m) AS seq }
CREATE (t)-[:HAS_MESSAGE]->(:ChatMessage {
  seq: seq, role: $role, content: $content, artifact_json: $artifact_json, created_at: datetime()
})
"""


def append_message(thread_id: str, role: str, content: str, artifact: dict | None = None) -> None:
    """Append one ordered message. A user message upserts the thread (title from the first one);
    other roles require the thread to exist and silently no-op otherwise."""
    _ensure_schema()
    params: dict = {
        "id": thread_id, "role": role, "content": content,
        "artifact_json": json.dumps(artifact, default=str) if artifact else None,
    }
    if role == "user":
        params["title"] = content[:TITLE_MAX]
    get_driver().execute_query(
        _APPEND_USER if role == "user" else _APPEND_OTHER,
        database_=config.CHAT_DATABASE,
        **params,
    )


def list_threads(limit: int = 50) -> list[dict]:
    """Recent threads, newest first: id, title, updated_at, message count."""
    records, _, _ = get_driver().execute_query(
        """
        CYPHER 25
        MATCH (t:ChatThread)
        RETURN t.id AS id, coalesce(t.title, 'New chat') AS title,
               toString(t.updated_at) AS updated_at,
               count { (t)-[:HAS_MESSAGE]->() } AS messages
        ORDER BY t.updated_at DESC LIMIT $limit
        """,
        limit=limit, routing_=RoutingControl.READ, database_=config.CHAT_DATABASE,
    )
    return [dict(r) for r in records]


def get_thread(thread_id: str) -> list[dict]:
    """A thread's messages in order (role + content + the artifact an assistant answer carried,
    when one was persisted)."""
    records, _, _ = get_driver().execute_query(
        """
        CYPHER 25
        MATCH (:ChatThread {id: $id})-[:HAS_MESSAGE]->(m:ChatMessage)
        RETURN m.role AS role, m.content AS content, m.artifact_json AS artifact_json
        ORDER BY m.seq
        """,
        id=thread_id, routing_=RoutingControl.READ, database_=config.CHAT_DATABASE,
    )
    messages = []
    for r in records:
        d = dict(r)
        artifact_json = d.pop("artifact_json", None)
        d["artifact"] = json.loads(artifact_json) if artifact_json else None
        messages.append(d)
    return messages


def delete_thread(thread_id: str) -> None:
    get_driver().execute_query(
        "CYPHER 25 MATCH (t:ChatThread {id: $id}) OPTIONAL MATCH (t)-[:HAS_MESSAGE]->(m) DETACH DELETE t, m",
        id=thread_id, database_=config.CHAT_DATABASE,
    )
