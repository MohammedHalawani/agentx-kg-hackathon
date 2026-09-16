"""One-off backfill: compute a vector embedding for every text-bearing node and write it back
onto the node, then ensure a vector index exists per label. Driven entirely by schema.yaml's
`fulltext:` declarations - same "no per-label code" principle as registry.py / schema.py's
registry_options() and display_props(). Add a `fulltext:` list to a new node in schema.yaml
and it's picked up here with no code change.

This is the app's only WRITE path against the domain graph - deliberately kept out of the
FastAPI backend (which never writes, see backend/main.py's docstring) and run by hand instead.

Excluded on purpose - a data-value judgment call, not a schema.yaml concern:
- Person: names alone aren't the kind of text worth a similarity search over.
- BudgetLine: has no `fulltext:` property in schema.yaml anyway (it's numbers, not prose) -
  listed here explicitly so a future schema.yaml edit can't silently start embedding it.

Requires an embedding-capable model already pulled in Ollama (or any LiteLLM-supported
embedding endpoint - see config.EMBEDDING_MODEL). This script never pulls one itself.

Safe to re-run: a node that already carries `embedding` is skipped unless --force is passed.
NOT yet run against a live database - review before use.

Usage (from chat/):
    uv run python scripts/embed_backfill.py                # every eligible label
    uv run python scripts/embed_backfill.py --label Mandate # just one label
    uv run python scripts/embed_backfill.py --dry-run       # counts only, no model calls, no writes
    uv run python scripts/embed_backfill.py --force         # re-embed nodes that already have one
"""
import argparse
import sys
from pathlib import Path

# chat/ itself on sys.path, so `import config` / `from core import ...` resolve regardless of
# the invocation's cwd - same fix backend/main.py applies for the opposite direction.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import litellm  # noqa: E402
from neo4j import RoutingControl  # noqa: E402

import config  # noqa: E402
from core import schema  # noqa: E402
from core.query_runner import get_driver  # noqa: E402

EXCLUDED_LABELS = {"Person", "BudgetLine"}
BATCH_SIZE = 64


def embeddable_labels() -> list[str]:
    return [label for label in schema.fulltext_labels() if label not in EXCLUDED_LABELS]


def _text_expr(props: list[str]) -> str:
    """A Cypher expression joining a label's fulltext properties into one blob per node, so a
    multi-property label (e.g. ExpectedResult's title_ar + text_ar) embeds as one piece of
    text instead of losing every property but the first."""
    parts = [f"coalesce(n.{p}, '')" for p in props]
    return " + ' ' + ".join(parts) if len(parts) > 1 else parts[0]


def fetch_pending(label: str, key: str, props: list[str], force: bool) -> list[dict]:
    """[{id, text}] for every node of this label with non-empty fulltext content, excluding
    ones that already have an embedding unless --force was passed."""
    text_expr = _text_expr(props)
    skip_embedded = "" if force else "AND n.embedding IS NULL "
    cypher = (
        f"MATCH (n:{label}) "
        f"WITH n, trim({text_expr}) AS text "
        f"WHERE text <> '' {skip_embedded}"
        f"RETURN n.{key} AS id, text"
    )
    records, _, _ = get_driver().execute_query(
        cypher, routing_=RoutingControl.READ, database_=config.NEO4J_DATABASE
    )
    return [dict(r) for r in records]


def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = litellm.embedding(
        model=config.EMBEDDING_MODEL, input=texts, api_base=config.EMBEDDING_API_BASE
    )
    return [row["embedding"] for row in resp.data]


def write_embeddings(label: str, key: str, ids: list, vectors: list[list[float]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        f"MATCH (n:{label} {{{key}: row.id}}) "
        "SET n.embedding = row.vec"
    )
    rows = [{"id": i, "vec": v} for i, v in zip(ids, vectors, strict=True)]
    get_driver().execute_query(
        cypher, parameters_={"rows": rows}, routing_=RoutingControl.WRITE, database_=config.NEO4J_DATABASE
    )


def ensure_vector_index(label: str) -> None:
    index_name = f"{label.lower()}_embedding"
    cypher = (
        f"CREATE VECTOR INDEX {index_name} IF NOT EXISTS "
        f"FOR (n:{label}) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {config.EMBEDDING_DIMENSIONS}, "
        "`vector.similarity_function`: 'cosine'}}"
    )
    get_driver().execute_query(cypher, routing_=RoutingControl.WRITE, database_=config.NEO4J_DATABASE)


def backfill_label(label: str, force: bool, dry_run: bool) -> int:
    key = schema.key_of(label)
    props = schema.fulltext_props(label)
    pending = fetch_pending(label, key, props, force)
    print(f"{label}: {len(pending)} node(s) to embed" + (" (dry run)" if dry_run else ""))
    if dry_run:
        return len(pending)

    for i in range(0, len(pending), BATCH_SIZE):
        chunk = pending[i:i + BATCH_SIZE]
        vectors = embed_texts([row["text"] for row in chunk])
        write_embeddings(label, key, [row["id"] for row in chunk], vectors)

    ensure_vector_index(label)  # idempotent (IF NOT EXISTS) - safe even when pending was empty
    return len(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", help="Only backfill this one label (default: every eligible label)")
    parser.add_argument("--force", action="store_true", help="Re-embed nodes that already have an embedding")
    parser.add_argument("--dry-run", action="store_true", help="Report counts only - no model calls, no writes")
    args = parser.parse_args()

    if args.label:
        if args.label in EXCLUDED_LABELS:
            raise SystemExit(f"{args.label!r} is deliberately excluded (see EXCLUDED_LABELS) - not embedding it.")
        if args.label not in schema.fulltext_labels():
            raise SystemExit(f"{args.label!r} has no `fulltext:` list in schema.yaml; available: {schema.fulltext_labels()}")
        labels = [args.label]
    else:
        labels = embeddable_labels()

    total = sum(backfill_label(label, args.force, args.dry_run) for label in labels)
    verb = "would be embedded" if args.dry_run else "embedded"
    print(f"Done. {total} node(s) {verb} across {len(labels)} label(s).")


if __name__ == "__main__":
    main()
