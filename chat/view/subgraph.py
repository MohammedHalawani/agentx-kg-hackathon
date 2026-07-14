"""A connected, random cross-section of the graph for the Explore -> Graph lens.

Ported from the old project's discover-graph sampler, which turned out to be entirely
schema-agnostic - it seeds on random `(n)` nodes and expands by relationship TYPE (never a
hardcoded label), so it works unchanged against this schema. The one schema-specific hook,
picking a human-readable caption per node, is re-supplied from schema.py's
`caption_props()` (schema.yaml's displayName_ar/_en) instead of the old project's ontology.
"""
from neo4j import Result, RoutingControl

import config
from core import schema
from core.query_runner import get_driver

CAPTION_MAX = 22
MAX_SEEDS = 40
NEIGHBOURS_PER_TYPE = 4  # hop 1: per (relationship type) sample off each seed
NEIGHBOURS_PER_TYPE2 = 2  # hop 2: smaller per-type sample off the hop-1 frontier

# Expand whatever `n` nodes the seed clause bound, two hops deep, with a per-relationship-type
# quota at each hop rather than one flat cap - so a common edge type can't crowd out a rare one.
_EXPAND = (
    "WITH collect(DISTINCT n)[0..$cap] AS seeds\n"
    "UNWIND seeds AS s\n"
    "CALL (s) {\n"
    "  MATCH (s)-[r]-(m)\n"
    "  WITH type(r) AS t, collect({r: r, m: m})[0..$per_type] AS sample\n"
    "  UNWIND sample AS e RETURN e.r AS r, e.m AS m\n"
    "}\n"
    "WITH collect(DISTINCT {a: s, r: r, b: m}) AS hop1, collect(DISTINCT m) AS frontier\n"
    "UNWIND frontier AS f\n"
    "CALL (f) {\n"
    "  MATCH (f)-[r2]-(m2)\n"
    "  WITH type(r2) AS t2, collect({r: r2, m: m2})[0..$per_type2] AS sample2\n"
    "  UNWIND sample2 AS e2 RETURN e2.r AS r2, e2.m AS m2\n"
    "}\n"
    "WITH hop1, collect(DISTINCT {a: f, r: r2, b: m2}) AS hop2\n"
    "UNWIND (hop1 + hop2) AS edge\n"
    "RETURN edge.a AS n, edge.r AS r, edge.b AS m"
)

_DISCOVER_CYPHER = "CYPHER 25\nMATCH (n)\nWITH n ORDER BY rand() LIMIT $cap\n" + _EXPAND


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= CAPTION_MAX else text[: CAPTION_MAX - 1] + "…"


def _caption(labels: list[str], props: dict) -> str:
    prefs = schema.caption_props()
    for label in labels:
        for prop in prefs.get(label, []):
            if props.get(prop) not in (None, ""):
                return _short(str(props[prop]))
    return _short(":".join(labels)) if labels else "?"


def _node_dict(node) -> dict:
    labels = list(node.labels)
    props = {
        k: v
        for k, v in dict(node).items()
        if not (isinstance(v, (bytes, bytearray)) or (isinstance(v, list) and len(v) > 16))
    }
    return {"id": node.element_id, "labels": labels,
            "caption": _caption(labels, props), "properties": props}


def _rel_dict(rel) -> dict:
    return {"id": rel.element_id, "type": rel.type,
            "from": rel.start_node.element_id, "to": rel.end_node.element_id}


def _run(cypher: str, **params) -> dict | None:
    call = {"cap": MAX_SEEDS, "per_type": NEIGHBOURS_PER_TYPE, "per_type2": NEIGHBOURS_PER_TYPE2, **params}
    graph = get_driver().execute_query(
        cypher,
        database_=config.NEO4J_DATABASE,
        routing_=RoutingControl.READ,
        result_transformer_=Result.graph,
        **call,
    )
    if not graph.nodes:
        return None
    return {"nodes": [_node_dict(n) for n in graph.nodes],
            "relationships": [_rel_dict(r) for r in graph.relationships]}


def connected_sample_graph(seeds: int = MAX_SEEDS) -> dict | None:
    """`seeds` random nodes plus their two-hop neighbourhood, so the Explore graph view shows
    linked clusters rather than disconnected points. Not cached - call again for a different
    region of the graph."""
    return _run(_DISCOVER_CYPHER, cap=seeds, per_type=5, per_type2=2)
