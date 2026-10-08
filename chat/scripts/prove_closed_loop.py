"""Capture one reviewed recommendation on a verified local synthetic shipment.

Default is a read-only preview. --write runs ONE pipeline, then repeats only its frozen
accepted write state to verify idempotency. No resets, deletes, outcome confirmation,
embeddings, or unrelated writes. Artifacts contain final application fields, never provider
reasoning. Intended for the explicitly authorized local closed-loop proof only.
"""
import argparse
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neo4j import RoutingControl

import config
from core.query_runner import get_driver
from llm.pipeline import _llm, cases, graph, retrieve, writeback

ALLOWED_LABELS = {"Shipment", "Order", "Customer", "Address", "Courier", "Policy", "Event",
                  "FailureReason", "Resolution", "Outcome", "EscalatedCase"}


def safe(value):
    if isinstance(value, str):
        return _llm.final_text(value)
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items() if k not in {"embedding", "reasoning", "reasoning_content", "analysis"}}
    if isinstance(value, list):
        return [safe(v) for v in value]
    return value


def read(query, **params):
    rows, _, _ = get_driver().execute_query(
        query, parameters_=params, database_=config.SHIPMENT_DATABASE, routing_=RoutingControl.READ,
    )
    return [r.data() for r in rows]


def census():
    if urlparse(config.NEO4J_URI).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Proof requires a local Neo4j host")
    if config.SHIPMENT_DATABASE != "shipments":
        raise RuntimeError("Proof requires the reviewed local shipments database")
    nodes = read("MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels")
    rels = read("MATCH (a)-[r]->(b) RETURN elementId(r) AS id, type(r) AS type, elementId(a) AS start, elementId(b) AS end")
    ids = read("MATCH (s:Shipment) RETURN s.shipment_id AS shipment_id")
    labels = Counter(label for n in nodes for label in n["labels"])
    if len(ids) != 300 or not all(re.fullmatch(r"SHP-\d{4}", str(s["shipment_id"])) for s in ids):
        raise RuntimeError("Shipment census differs from the verified synthetic baseline")
    if set(labels) - ALLOWED_LABELS:
        raise RuntimeError("Unexpected domain labels; do not mutate this database")
    return {"nodes": nodes, "relationships": rels, "labels": dict(labels),
            "node_count": len(nodes), "relationship_count": len(rels)}


def inspected_case(shipment_id):
    return safe({"shipment_id": shipment_id,
                 "local": retrieve.local_subgraph({"shipment_id": shipment_id, "tracking_id": None}),
                 "route": cases.shipment_route(shipment_id),
                 "graph": cases.shipment_subgraph(shipment_id)})


def dump(path, value):
    path.write_text(json.dumps(safe(value), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def object_ids(snapshot):
    return ({n["id"] for n in snapshot["nodes"]}, {r["id"] for r in snapshot["relationships"]})


def final_dto(state):
    return {"extracted": graph._display_detail("extract", state.get("extracted")),
            "classification": graph._display_detail("classify", state.get("classification")),
            "recommendation": graph._display_detail("recommend", state.get("recommendation")),
            "review": graph._display_detail("review", state.get("review")),
            "disposition": state.get("disposition"), "resolution_id": state.get("resolution_id"),
            "escalation": state.get("escalation"), "loops": state.get("loop_count"),
            "execution_confirmed": False}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shipment-id", default="SHP-0004")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[2] / "docs" / "agent-runs" / "evidence" / "2026-10-07-shipment-closed-loop-proof")
    args = parser.parse_args()
    if not re.fullmatch(r"SHP-\d{4}", args.shipment_id):
        raise RuntimeError("Invalid synthetic shipment ID")
    before = census()
    original_case = inspected_case(args.shipment_id)
    local = original_case["local"]
    failure = local.get("live_failure") or {}
    failure_id = failure.get("failure_id")
    if not failure_id or failure.get("category") != "address_conflict":
        raise RuntimeError("Target must be a currently unresolved address-conflict shipment")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dump(args.output_dir / "before.json", {"captured_at": datetime.now(timezone.utc).isoformat(),
         "database": "shipments", "synthetic_verified": True,
         "census": before, "case": original_case, "existing_SHP_0227": inspected_case("SHP-0227")})
    print("Verified local synthetic target", args.shipment_id, failure_id, "nodes", before["node_count"])
    if not args.write:
        print("Read-only preview complete; no model calls or mutations.")
        return

    original_resolution, original_escalation = writeback.write_resolution, writeback.write_escalation

    def verify_before_mutation(state):
        current = census()
        # Refuse concurrent graph changes between the capture and this ONE pipeline write.
        if object_ids(current) != object_ids(before):
            raise RuntimeError("Graph changed since capture; stop before mutation")
        identity = writeback._identity(state)
        if not identity or identity[:2] != (args.shipment_id, failure_id):
            raise RuntimeError("Pipeline target identity differs from the verified proof target")
        target = retrieve.local_subgraph({"shipment_id": args.shipment_id, "tracking_id": None})
        if (target.get("live_failure") or {}).get("failure_id") != failure_id:
            raise RuntimeError("Proof failure is no longer unresolved; stop before mutation")

    def guarded_resolution(state):
        verify_before_mutation(state)
        return original_resolution(state)

    def guarded_escalation(state):
        verify_before_mutation(state)
        return original_escalation(state)

    complaint = f"الشحنة {args.shipment_id} لم تصل والعنوان المسجل غير صحيح"
    with patch.object(writeback, "write_resolution", guarded_resolution), \
         patch.object(writeback, "write_escalation", guarded_escalation):
        final = graph.run_complaint(complaint)

    after = census()
    old_nodes = {n["id"] for n in before["nodes"]}
    old_rels = {r["id"] for r in before["relationships"]}
    new_node_ids = [n["id"] for n in after["nodes"] if n["id"] not in old_nodes]
    new_relationships = [r for r in after["relationships"] if r["id"] not in old_rels]
    new_nodes = read("MATCH (n) WHERE elementId(n) IN $ids RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS properties", ids=new_node_ids)
    replay = {"performed": False}
    if final.get("resolution_id"):
        repeated = original_resolution(final)
        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent = list(pool.map(original_resolution, [final, final]))
        last = census()
        if (repeated != final["resolution_id"] or concurrent != [repeated, repeated]
                or object_ids(last) != object_ids(after)):
            raise RuntimeError("Replay created different graph objects; stop and inspect")
        replay = {"performed": True, "sequential_resolution_id": repeated,
                  "concurrent_resolution_ids": concurrent, "object_counts_unchanged": True}
    dump(args.output_dir / "after.json", {"captured_at": datetime.now(timezone.utc).isoformat(),
         "census": after, "case": inspected_case(args.shipment_id), "new_nodes": new_nodes,
         "new_relationships": new_relationships, "existing_SHP_0227": inspected_case("SHP-0227"),
         "replay": replay})
    dump(args.output_dir / "final.json", final_dto(final))
    print(json.dumps({"disposition": final.get("disposition"), "resolution_id": final.get("resolution_id"),
          "loops": final.get("loop_count"), "new_nodes": len(new_nodes),
          "new_relationships": len(new_relationships), "replay": replay}, ensure_ascii=False))


if __name__ == "__main__":
    main()
