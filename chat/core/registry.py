"""Generic dropdown-option lookup for any `registry: true` node label in schema.yaml.

One function serves every registry (Track, Committee, Person, Entity, ...) instead of one
hand-written query per label - add a node or rename a display property in schema.yaml and
this picks it up with no code change, same principle as the old project's
`seed_properties()` / `label_descriptions()`.
"""
from neo4j import RoutingControl

import config
from core import schema
from core.query_runner import get_driver

# Person is the one large registry; the rest are small enough for a plain dropdown with
# no search. Keep this list to labels that actually need the arabic fulltext search-as-you-type
# treatment on the Filter tab, rather than a full list.
SEARCHABLE = {"Person"}


def _mandate_options(q: str | None, limit: int) -> list[dict]:
    """Mandate isn't `registry: true` (schema.yaml calls it a fact record you filter into,
    not pick from a list) - but Q15/Q51 take a mandate `code` param with nothing in the UI
    to tell a user which codes exist, so give the Filter tab a dropdown anyway. Kept
    separate from registry_options()'s generic path since Mandate has no displayName_*
    property to show - the label here is built from mandateCode + a snippet of text_ar."""
    where = ""
    params: dict = {}
    if q:
        where = "WHERE m.mandateCode CONTAINS $q OR m.text_ar CONTAINS $q"
        params["q"] = q
    cypher = (
        f"MATCH (m:Mandate) {where} "
        "RETURN m.mandateCode AS id, "
        "m.mandateCode + ' — ' + left(coalesce(m.text_ar, ''), 60) AS displayName_ar "
        "ORDER BY m.mandateCode LIMIT $limit"
    )
    params["limit"] = limit
    records, _, _ = get_driver().execute_query(
        cypher, parameters_=params, routing_=RoutingControl.READ, database_=config.NEO4J_DATABASE
    )
    return [dict(r) for r in records]


def registry_options(label: str, q: str | None = None, limit: int = 200) -> list[dict]:
    """[{id, displayName_ar, displayName_en, ...}] for one registry label, sorted by its
    first display property. `q` does a CONTAINS filter on the display props (used for the
    Person search-as-you-type box); ignored for labels not in SEARCHABLE.
    """
    if label == "Mandate":
        return _mandate_options(q, limit)
    if not schema.is_registry_label(label):
        raise ValueError(f"{label!r} is not a registry: true node (see schema.yaml)")
    key = schema.key_of(label)
    display = schema.display_props(label)
    if not display:
        raise ValueError(f"{label!r} has no displayName_* property to show in a dropdown")

    return_cols = ", ".join(f"n.{p} AS {p}" for p in display)
    where = ""
    params: dict = {}
    if q and label in SEARCHABLE:
        conditions = " OR ".join(f"n.{p} CONTAINS $q" for p in display)
        where = f"WHERE {conditions}"
        params["q"] = q

    cypher = (
        f"MATCH (n:{label}) {where} "
        f"RETURN n.{key} AS id, {return_cols} "
        f"ORDER BY n.{display[0]} LIMIT $limit"
    )
    params["limit"] = limit
    records, _, _ = get_driver().execute_query(
        cypher,
        parameters_=params,
        routing_=RoutingControl.READ,
        database_=config.NEO4J_DATABASE,
    )
    return [dict(r) for r in records]
