"""Undo the agent's work on the shipment graph, returning it to the seeded 165/75 split.

Every executed case permanently consumes an open one: acceptance writes a
(FailureReason)-[:RESOLVES_WITH]->(Resolution)-[:HAD_OUTCOME]->(Outcome) chain, and that
failure then drops out of the intake worklist for good. Demoing or testing therefore drains
the queue, and there was no way back short of restoring shipment_dataset.dump by hand and
re-running the embedding backfill over all 165 cases.

This is the cheap way back. Rather than reloading the dump, it deletes only what the pipeline
itself wrote - every Resolution stamped source='agent_pipeline', and the Outcome hanging off
it. The seeded history has no such stamp, so it cannot be touched by this script even if the
two are interleaved. Nothing else in the graph is modified: no shipment, event, courier or
address is deleted, and the 165 seeded embeddings survive, so there is no need to re-embed
afterwards.

The one thing it cannot undo is case_summary, which writeback stamps onto a failure it
resolves. That is left in place deliberately - it is derived from the failure's own fields,
so it is correct regardless of who resolved it, and a re-run would rewrite it identically.

Usage (from chat/):
    uv run python scripts/reset_shipment_graph.py            # show what would be removed
    uv run python scripts/reset_shipment_graph.py --yes      # actually remove it
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neo4j import RoutingControl  # noqa: E402

import config  # noqa: E402
from core.query_runner import get_driver  # noqa: E402

# Anchored on the source stamp, never on a timestamp or a count: the seeded resolutions carry
# no `source`, so this can only ever match rows the pipeline created.
_COUNT = """
MATCH (r:Resolution {source: 'agent_pipeline'})
OPTIONAL MATCH (r)-[:HAD_OUTCOME]->(o:Outcome)
RETURN count(DISTINCT r) AS resolutions, count(DISTINCT o) AS outcomes
"""

_PREVIEW = """
MATCH (f:FailureReason)-[:RESOLVES_WITH]->(r:Resolution {source: 'agent_pipeline'})
RETURN f.failure_id AS failure_id, r.resolution_id AS resolution_id,
       r.action AS action, r.timestamp AS timestamp
ORDER BY r.timestamp
"""

_DELETE = """
MATCH (r:Resolution {source: 'agent_pipeline'})
OPTIONAL MATCH (r)-[:HAD_OUTCOME]->(o:Outcome)
DETACH DELETE r, o
"""

_COVERAGE = """
MATCH (f:FailureReason)
RETURN sum(CASE WHEN (f)-[:RESOLVES_WITH]->() THEN 1 ELSE 0 END) AS resolved,
       sum(CASE WHEN (f)-[:RESOLVES_WITH]->() THEN 0 ELSE 1 END) AS open
"""


def _run(cypher: str, write: bool = False) -> list[dict]:
    return get_driver().execute_query(
        cypher,
        routing_=RoutingControl.WRITE if write else RoutingControl.READ,
        database_=config.SHIPMENT_DATABASE,
        result_transformer_=lambda res: [r.data() for r in res],
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true",
                    help="perform the deletion; without it the script only reports")
    args = ap.parse_args()

    counts = _run(_COUNT)[0]
    before = _run(_COVERAGE)[0]
    print(f"Database: {config.SHIPMENT_DATABASE}")
    print(f"Currently {before['resolved']} resolved / {before['open']} open.")
    print(f"Written by the agent: {counts['resolutions']} resolution(s), {counts['outcomes']} outcome(s).")

    if not counts["resolutions"]:
        print("\nNothing to undo - the graph is already in its seeded state.")
        return

    print("\nWould remove:")
    for row in _run(_PREVIEW):
        print(f"  {row['resolution_id']}  {row['failure_id']}  {str(row['timestamp'])[:19]}  {row['action'][:44]}")

    if not args.yes:
        print("\nDry run. Re-run with --yes to remove these and reopen their cases.")
        return

    _run(_DELETE, write=True)
    after = _run(_COVERAGE)[0]
    print(f"\nRemoved. Now {after['resolved']} resolved / {after['open']} open.")
    print("Seeded embeddings are untouched - no need to re-run the backfill.")


if __name__ == "__main__":
    main()
