"""Hybrid retrieval over the shipment graph (config.SHIPMENT_DATABASE): a vector path and a
graph path, fused by reciprocal-rank-fusion into the contextual subgraph the classifier
reasons over.

vector_search    - KNN over the embedding on every RESOLVED FailureReason's case_summary
                   (built by scripts/embed_backfill_shipments.py). Finds cases that *read*
                   like this one.
graph_traversal  - a walk from whatever extract.py resolved to a real node, out through
                   HAS_EVENT / CAUSED_BY / RESOLVES_WITH / HAD_OUTCOME. Finds cases that are
                   *structurally* related (same courier, same district, same failure shape)
                   even when their wording doesn't match.

Both are frozen, parameterized Cypher - the same no-generated-Cypher rule the rest of this
app follows (see core/query_runner.py). The only thing an LLM decides is which extracted
entity seeds the traversal, never the query text.

Note that the "Vector DB" and "Graph DB" boxes in the architecture diagram are the SAME
Neo4j database here: Neo4j 5's native vector index means the KNN lookup and the graph walk
hit one store, so a retrieved case never has to be re-joined across two systems.
"""
import logging

import litellm
from neo4j import RoutingControl

import config
from core.query_runner import get_driver
from llm.pipeline.state import ExtractedComplaint, RetrievedContext

log = logging.getLogger("pipeline.retrieve")

RRF_K = 60          # standard RRF damping constant
VECTOR_TOP_K = 10
GRAPH_TOP_K = 10

# --- vector path -----------------------------------------------------------------------
# Returns the full precedent chain, not just the matched node: a similar case is only useful
# if you can also see what was DONE about it and whether that worked.
_VECTOR = """
CALL db.index.vector.queryNodes($index, $k, $embedding)
YIELD node AS f, score
MATCH (f)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
RETURN f.failure_id    AS failure_id,
       f.category      AS category,
       f.description   AS description,
       f.city          AS city,
       f.district      AS district,
       f.courier       AS courier,
       f.case_summary  AS case_summary,
       r.resolution_id AS resolution_id,
       r.action        AS action,
       o.success       AS success,
       o.notes         AS outcome_notes,
       score           AS score
ORDER BY score DESC
"""

# --- graph path ------------------------------------------------------------------------
# Seeded by whatever the extractor resolved. Every clause is `$x IS NULL OR ...` so one query
# serves all seed combinations (the same convention Q64 uses in docs/queries.txt).
_GRAPH = """
MATCH (f:FailureReason)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
WHERE ($courier  IS NULL OR f.courier  = $courier)
  AND ($city     IS NULL OR f.city     = $city)
  AND ($district IS NULL OR f.district = $district)
  AND ($category IS NULL OR f.category = $category)
RETURN f.failure_id    AS failure_id,
       f.category      AS category,
       f.description   AS description,
       f.city          AS city,
       f.district      AS district,
       f.courier       AS courier,
       f.case_summary  AS case_summary,
       r.resolution_id AS resolution_id,
       r.action        AS action,
       o.success       AS success,
       o.notes         AS outcome_notes
LIMIT $k
"""

# --- the complaint's own shipment -------------------------------------------------------
# The "original evidence" the reviewer validates against: what actually happened to THIS
# shipment, the policy governing it (SLA + retry limit), and its unresolved FailureReason.
_LOCAL = """
MATCH (s:Shipment)
WHERE ($shipment_id IS NULL OR s.shipment_id = $shipment_id)
  AND ($tracking_id IS NULL OR s.tracking_id = $tracking_id)
WITH s LIMIT 1
OPTIONAL MATCH (s)-[:ASSIGNED_TO]->(c:Courier)
OPTIONAL MATCH (s)-[:GOVERNED_BY]->(p:Policy)
OPTIONAL MATCH (s)-[:DELIVERED_TO]->(a:Address)
OPTIONAL MATCH (s)-[:HAS_EVENT]->(e:Event)
OPTIONAL MATCH (s)-[:HAS_EVENT]->()-[:CAUSED_BY]->(lf:FailureReason)
  WHERE NOT (lf)-[:RESOLVES_WITH]->()
RETURN s {.shipment_id, .tracking_id, .order_id, .carrier, .status}  AS shipment,
       c {.courier_id, .name}                                        AS courier,
       p {.policy_id, .name, .sla_days, .retry_limit}                AS policy,
       collect(DISTINCT a {.address_id, .full_address, .district, .city,
                           .lat, .lng, .version})                    AS addresses,
       collect(DISTINCT e {.event_id, .event_type, .timestamp})      AS events,
       head(collect(DISTINCT lf {.failure_id, .category, .description,
                                 .city, .district, .courier, .timestamp})) AS live_failure
"""


def _embed(text: str) -> list[float]:
    resp = litellm.embedding(
        model=config.EMBEDDING_MODEL, input=[text], api_base=config.EMBEDDING_API_BASE
    )
    return resp.data[0]["embedding"]


def _read(cypher: str, params: dict) -> list[dict]:
    records, _, _ = get_driver().execute_query(
        cypher, parameters_=params,
        routing_=RoutingControl.READ, database_=config.SHIPMENT_DATABASE,
    )
    return [dict(r) for r in records]


def vector_search(query_text: str, k: int = VECTOR_TOP_K) -> list[dict]:
    """Top-k resolved cases by cosine similarity to query_text, each with the action taken
    and whether it worked.

    Returns [] with a warning rather than raising if the vector index hasn't been built yet
    or the embedding endpoint is down - a graph-only run is degraded but still useful, and
    this is the single most likely thing to be unconfigured on a fresh checkout."""
    from scripts.embed_backfill_shipments import VECTOR_INDEX_NAME
    try:
        return _read(_VECTOR, {"index": VECTOR_INDEX_NAME, "k": k, "embedding": _embed(query_text)})
    except Exception as exc:
        log.warning("vector_search unavailable (%s: %s) - continuing graph-only",
                    type(exc).__name__, exc)
        return []


def graph_traversal(extracted: ExtractedComplaint, k: int = GRAPH_TOP_K) -> list[dict]:
    """Resolved cases sharing this complaint's courier / city / district / category."""
    return _read(_GRAPH, {
        "courier": extracted.get("courier"),
        "city": extracted.get("city"),
        "district": extracted.get("district"),
        "category": extracted.get("category_hint"),
        "k": k,
    })


def local_subgraph(extracted: ExtractedComplaint) -> dict:
    """What actually happened to THIS shipment - the evidence the reviewer checks against.
    Empty dict when the complaint named no resolvable shipment."""
    if not (extracted.get("shipment_id") or extracted.get("tracking_id")):
        return {}
    rows = _read(_LOCAL, {
        "shipment_id": extracted.get("shipment_id"),
        "tracking_id": extracted.get("tracking_id"),
    })
    return rows[0] if rows else {}


def fuse_rrf(*ranked_lists: list[dict], k: int = RRF_K) -> list[dict]:
    """Reciprocal-rank-fusion: score(d) = sum over lists of 1 / (k + rank).

    Fuses on failure_id, so a case surfacing in BOTH the vector and graph paths is boosted
    rather than duplicated - which is the whole reason for running two retrievers instead of
    picking one.
    """
    scores: dict[str, float] = {}
    merged: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, row in enumerate(ranked, start=1):
            fid = row.get("failure_id")
            if not fid:
                continue
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (k + rank)
            merged.setdefault(fid, row)
    out = []
    for fid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        row = dict(merged[fid])
        row["rrf_score"] = round(score, 6)
        out.append(row)
    return out


def retrieve_context(extracted: ExtractedComplaint, top_k: int = 5) -> RetrievedContext:
    """The entry point graph.py's retrieve node calls: run both paths, fuse them, and attach
    the complaint's own shipment evidence."""
    vector_hits = vector_search(extracted["raw_text"])
    graph_hits = graph_traversal(extracted)
    fused = fuse_rrf(vector_hits, graph_hits)[:top_k]
    local = local_subgraph(extracted)
    log.info("retrieved %d vector + %d graph -> %d fused",
             len(vector_hits), len(graph_hits), len(fused))
    live = (local.get("live_failure") or {}) if local else {}
    return {
        "similar_cases": fused,
        "local_subgraph": local,
        "live_failure_id": live.get("failure_id"),
    }
