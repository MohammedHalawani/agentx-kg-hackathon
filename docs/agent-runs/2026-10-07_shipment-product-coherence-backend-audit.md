# Shipment product coherence — backend audit

Timestamp: 2026-10-07T22:20:00+03:00. Run: `2026-10-07_shipment-product-coherence`.

Repository instructions: no applicable AGENTS.md in this repository or its parent paths.
Existing edits to config.py and pipeline/_llm.py were present before this subtask and were
preserved. No environment files or secrets were printed or edited by this subtask.

The active `/graph` route used view/subgraph.py's generic random sampler on NEO4J_DATABASE;
`/schema` also used NEO4J_DATABASE. The complaint pipeline and Decisions read
SHIPMENT_DATABASE. This explained the empty Explore lens while the shipment workload existed.
The old schema caption helpers describe governance nodes and cannot label shipment evidence.
Existing cases.py already has curated shipment-specific graph branches and explicit approximate
warehouse city coordinates, so that evidence is reused rather than inventing a parallel graph.

Read-only live census: Shipment 300, statuses FAILED 220 / DELIVERED 80; Event includes
HUB_DELAY, no lost status. Shipment fields include shipment_id/tracking_id/carrier/status;
Event has type/timestamp; Address has coordinates; Policy has SLA/retry limit; FailureReason
category and Resolution/Outcome edges describe complaint state. Parent coordinator verified
this local database is synthetic before live checks. No data/model/write calls were needed.

Contract agreed with Explore UI: one `/explore` result supplies filtered shipments, graph,
counts, map endpoints, and evidence metadata. Needs-attention includes pending outcomes so
acceptance of a recommendation does not claim successful delivery.
