"""Execute a frozen catalog query (see queries.py) with bound parameters.

There is no Cypher generation anywhere in this app, so there is no repair loop and no
write-keyword blocklist to maintain — every query that can ever run was hand-written and
reviewed in docs/queries.txt. RoutingControl.READ is still used as normal good practice,
not as the safety boundary (a dedicated read-only DB role is the real one - see the old
project's README for that caveat, which still applies).
"""
from functools import lru_cache

from neo4j import Driver, GraphDatabase, RoutingControl

import config
from core import queries


@lru_cache(maxsize=1)
def get_driver() -> Driver:
    driver = GraphDatabase.driver(
        config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD)
    )
    driver.verify_connectivity()
    return driver


def run(qid: str, params: dict | None = None) -> list[dict]:
    """Run one catalog query by id with the given bound params (missing optional params
    should be passed as None - Q64's filters are all written `$x IS NULL OR ...`)."""
    q = queries.get(qid)
    records, _, _ = get_driver().execute_query(
        q.cypher,
        parameters_=params or {},
        routing_=RoutingControl.READ,
        database_=config.NEO4J_DATABASE,
    )
    return [dict(r) for r in records]


SCHEMA_CYPHER = "CALL db.schema.visualization() YIELD nodes, relationships RETURN nodes, relationships"


def schema_graph() -> dict:
    """The data model as a graph (labels + relationship types) for the Schema view - reads
    Neo4j's own live schema, not docs/schema.yaml, so it can never drift from the real DB."""
    records, _, _ = get_driver().execute_query(
        SCHEMA_CYPHER, routing_=RoutingControl.READ, database_=config.NEO4J_DATABASE
    )
    if not records:
        return {"nodes": [], "relationships": []}
    row = records[0]
    nodes = []
    for n in row["nodes"]:
        name = dict(n).get("name") or (next(iter(n.labels), None) if n.labels else "?")
        nodes.append({"id": n.element_id, "labels": [name], "caption": name, "properties": {}})
    rels = [
        {"id": r.element_id, "type": r.type,
         "from": r.start_node.element_id, "to": r.end_node.element_id}
        for r in row["relationships"]
    ]
    return {"nodes": nodes, "relationships": rels}
