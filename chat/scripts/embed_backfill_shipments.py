"""One-off backfill for the shipment-complaint pipeline's vector search: compute an
embedding for every resolved FailureReason's case_summary and write it back onto the node,
then ensure a vector index exists - the shipment-graph counterpart to embed_backfill.py,
which does the same job for the governance graph's schema.yaml-declared fulltext labels.

Kept as a separate script rather than a --database flag on embed_backfill.py because the
two aren't schema-driven the same way: the governance script walks every fulltext: label in
docs/schema.yaml generically, but the shipment graph has exactly one embeddable property
(FailureReason.case_summary, already concatenated at generation time by
Saudi-Arabia-Regions-Cities-and-Districts/shipment_kg/generate_shipment_kg.py) and only on
the ~150 RESOLVED FailureReason nodes - the ~70 "live" ones have no case_summary and are
never embedded, since they're the queries this pipeline answers, not the precedent it draws
on.

Requires an embedding-capable model already pulled in Ollama (config.EMBEDDING_MODEL) and
the shipment graph already loaded into config.SHIPMENT_DATABASE (see the sibling project's
shipment_kg/shipment_dataset.dump). Never pulls a model or loads the dump itself.

Safe to re-run: a node that already carries `embedding` is skipped unless --force is passed.
NOT yet run against a live database - review before use.

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

import config  # noqa: E402
from core.query_runner import get_driver  # noqa: E402, F401  (used once real queries land)

VECTOR_INDEX_NAME = "failurereason_case_summary_embedding"


def fetch_pending(force: bool) -> list[dict]:
    """[{id, text}] for every resolved FailureReason (has a case_summary) not yet embedded,
    unless --force was passed."""
    ...


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Same LiteLLM embedding call embed_backfill.py makes, against config.EMBEDDING_MODEL."""
    ...


def write_embeddings(ids: list[str], vectors: list[list[float]]) -> None:
    """SET FailureReason.embedding for each id, in config.SHIPMENT_DATABASE."""
    ...


def ensure_vector_index() -> None:
    """CREATE VECTOR INDEX ... IF NOT EXISTS for FailureReason.embedding, sized to
    config.EMBEDDING_DIMENSIONS - same OPTIONS shape embed_backfill.py uses."""
    ...


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="Re-embed nodes that already have an embedding")
    parser.add_argument("--dry-run", action="store_true", help="Report counts only - no model calls, no writes")
    args = parser.parse_args()
    ...


if __name__ == "__main__":
    main()
