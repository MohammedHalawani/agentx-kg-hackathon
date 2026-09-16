"""Two independent retrieval paths over the shipment graph (config.SHIPMENT_DATABASE),
fused by reciprocal-rank-fusion into the RetrievedContext the classifier reasons over.

vector_search  - KNN over the embedding stored on every RESOLVED FailureReason's
                 case_summary property (see chat/scripts/embed_backfill_shipments.py for how
                 those embeddings and the vector index get created - same pattern as
                 chat/scripts/embed_backfill.py uses for the governance graph, just against
                 a different database/label). Finds cases that *read* similarly to this one.
graph_traversal  - an N-hop Cypher walk from whatever extract.py resolved to a real node
                 (a matched Shipment, Courier, or Address) out through HAS_EVENT /
                 CAUSED_BY / RESOLVES_WITH / HAD_OUTCOME. Finds cases that are *structurally*
                 connected (same courier, same district, same failure chain shape) even
                 when the wording of their case_summary doesn't read alike.

Kept as two frozen, parameterized Cypher queries rather than LLM-generated Cypher, in
keeping with the rest of this app's query_runner.py convention (docs/queries.txt) - the only
thing an LLM decides here is which extracted entity to seed the traversal from, never the
Cypher itself.
"""
from core.query_runner import get_driver  # noqa: F401  (referenced once real queries land here)
from llm.pipeline.state import ExtractedComplaint, RetrievedContext


def vector_search(query_text: str, k: int = 10) -> list[dict]:
    """Embed query_text with config.EMBEDDING_MODEL and return the top-k resolved
    FailureReason nodes by cosine similarity on their case_summary embedding, via
    db.index.vector.queryNodes against config.SHIPMENT_DATABASE."""
    ...


def graph_traversal(extracted: ExtractedComplaint, hops: int = 2) -> dict:
    """Walk out N hops from whichever of extracted's fields resolves to a real node
    (shipment_id/tracking_id first, then courier+city/district), returning the local
    subgraph of nodes/relationships encountered."""
    ...


def fuse_rrf(vector_results: list[dict], graph_results: dict, k: int = 60) -> list[dict]:
    """Reciprocal-rank-fusion of the two result sets into one ranked list - standard
    RRF: score(d) = sum(1 / (k + rank_in_each_list_containing_d))."""
    ...


def retrieve_context(extracted: ExtractedComplaint) -> RetrievedContext:
    """The single entry point graph.py's retrieve node calls: runs vector_search and
    graph_traversal, fuses them, and shapes the result into a RetrievedContext."""
    ...
