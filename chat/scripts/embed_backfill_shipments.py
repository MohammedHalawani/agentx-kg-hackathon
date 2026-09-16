"""One-off backfill for the shipment-complaint pipeline's vector search: compute an
embedding for every resolved FailureReason's case_summary and write it back onto the node,
then ensure a vector index exists - the shipment-graph counterpart to embed_backfill.py,
which does the same job for the governance graph's schema.yaml-declared fulltext labels.

Kept as a separate script rather than a --database flag on embed_backfill.py because the
two aren't schema-driven the same way: the governance script walks every fulltext: label in
docs/schema.yaml generically, but the shipment graph has exactly one embeddable property
(FailureReason.case_summary, already concatenated at generation time by
shipment_kg/generate_shipment_kg.py) and only on the RESOLVED FailureReason nodes - the
"live" ones have no case_summary and are never embedded, since they're the queries this
pipeline answers, not the precedent it draws on.

Requires an embedding-capable model already pulled in Ollama (config.EMBEDDING_MODEL) and
the shipment graph already loaded into config.SHIPMENT_DATABASE (from
shipment_kg/shipment_dataset.dump). Never pulls a model or loads the dump itself.

Safe to re-run: a node that already carries `embedding` is skipped unless --force is passed.

Usage (from chat/):
    uv run python scripts/embed_backfill_shipments.py                # all resolved cases
    uv run python scripts/embed_backfill_shipments.py --dry-run      # counts only
    uv run python scripts/embed_backfill_shipments.py --force        # re-embed everything
"""
import argparse
import sys
from pathlib import Path

# chat/ itself on sys.path, matching embed_backfill.py's own fix for the same reason.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import litellm  # noqa: E402
from neo4j import RoutingControl  # noqa: E402

import config  # noqa: E402
from core.query_runner import get_driver  # noqa: E402

VECTOR_INDEX_NAME = "failurereason_case_summary"
BATCH_SIZE = 64

# Only the resolved cases carry a case_summary (see shipment_kg/generate_shipment_kg.py) -
# that property being non-null IS the definition of "this case is usable precedent", so it
# is the whole filter here.
_PENDING = """
MATCH (f:FailureReason)
WHERE f.case_summary IS NOT NULL AND trim(f.case_summary) <> ''
  {skip_embedded}
RETURN f.failure_id AS id, f.case_summary AS text
"""

_WRITE = """
UNWIND $rows AS row
MATCH (f:FailureReason {failure_id: row.id})
CALL db.create.setNodeVectorProperty(f, 'embedding', row.vec)
"""

_INDEX = """
CREATE VECTOR INDEX {name} IF NOT EXISTS
FOR (f:FailureReason) ON (f.embedding)
OPTIONS {{indexConfig: {{
  `vector.dimensions`: {dims},
  `vector.similarity_function`: 'cosine'
}}}}
"""


def fetch_pending(force: bool) -> list[dict]:
    """[{id, text}] for every resolved FailureReason not yet embedded (or all of them when
    --force was passed)."""
    cypher = _PENDING.format(skip_embedded="" if force else "AND f.embedding IS NULL")
    records, _, _ = get_driver().execute_query(
        cypher, routing_=RoutingControl.READ, database_=config.SHIPMENT_DATABASE
    )
    return [dict(r) for r in records]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Same LiteLLM embedding call embed_backfill.py makes, against config.EMBEDDING_MODEL."""
    resp = litellm.embedding(
        model=config.EMBEDDING_MODEL, input=texts, api_base=config.EMBEDDING_API_BASE
    )
    return [row["embedding"] for row in resp.data]


def write_embeddings(ids: list[str], vectors: list[list[float]]) -> None:
    """Set FailureReason.embedding for each id, in config.SHIPMENT_DATABASE.

    Uses db.create.setNodeVectorProperty rather than a plain SET so Neo4j stores the value
    in its native vector encoding - a plain SET of a float list reads back fine but is not
    what the vector index expects."""
    rows = [{"id": i, "vec": v} for i, v in zip(ids, vectors, strict=True)]
    get_driver().execute_query(
        _WRITE,
        parameters_={"rows": rows},
        routing_=RoutingControl.WRITE,
        database_=config.SHIPMENT_DATABASE,
    )


def ensure_vector_index() -> None:
    """Idempotent - safe to call even when nothing was embedded this run."""
    get_driver().execute_query(
        _INDEX.format(name=VECTOR_INDEX_NAME, dims=config.EMBEDDING_DIMENSIONS),
        routing_=RoutingControl.WRITE,
        database_=config.SHIPMENT_DATABASE,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--force", action="store_true", help="Re-embed nodes that already have an embedding")
    parser.add_argument("--dry-run", action="store_true", help="Report counts only - no model calls, no writes")
    args = parser.parse_args()

    pending = fetch_pending(args.force)
    print(f"{len(pending)} resolved case(s) to embed" + (" (dry run)" if args.dry_run else ""))
    if args.dry_run:
        return

    for i in range(0, len(pending), BATCH_SIZE):
        chunk = pending[i:i + BATCH_SIZE]
        vectors = embed_texts([row["text"] for row in chunk])
        write_embeddings([row["id"] for row in chunk], vectors)
        print(f"  embedded {i + len(chunk)}/{len(pending)}")

    ensure_vector_index()
    print(f"Done. Vector index {VECTOR_INDEX_NAME!r} ensured on :FailureReason(embedding).")


if __name__ == "__main__":
    main()
