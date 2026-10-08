# Shipment Explore contract

Explore reads `SHIPMENT_DATABASE`; the legacy governance catalog remains separate. All
queries are fixed Cypher with bound parameters and read routing. Map, graph, and shipment
list use the identical selection from `GET /explore`.

`GET /explore?filter=needs_attention&limit=25` supports `needs_attention`, `all`, `stalled`,
`critical`, and `delivered`. Limit is 1–50. Unsupported filters, including `lost`, return 422.
The current dataset has only `FAILED` and `DELIVERED` shipment statuses; no lost status is
inferred. Results are ordered by shipment ID.

| Filter | Evidence definition |
| --- | --- |
| needs_attention | Shipment has an unresolved FailureReason, a recommendation whose Outcome.success is null, or an open EscalatedCase. |
| all | All shipments in the bounded census. |
| stalled | Needs attention, plus a hub_delay failure category (including escalation prefix) or latest HUB_DELAY event. |
| critical | Needs attention, plus a policy SLA breach, exhausted delivery retry budget, or an open escalation. |
| delivered | Shipment.status is exactly DELIVERED. A resolution/recommendation never establishes delivery. |

SLA elapsed time is the graph's first-to-latest event interval, consistent with the pipeline
business rule; this synthetic historical dataset is not aged against today's wall clock.
`priority` is derived (`high` for critical, `medium` for attention, otherwise `low`), with
`priority_source: operational_rules`; it does not claim a stored dispatch priority.

Response fields: `shipments`, `counts` for every filter, selected `filter`/`limit`, matching
`total`, `returned`, result `truncated`, `dataset_truncated`, `counts_scope`, and `graph`.
Each shipment has shipment_id, tracking_id, raw status, carrier, priority, priority_source,
root_causes, needs_attention/stalled/critical/delivered flags, pending_recommendation,
open_escalation, last_event, origin, destinations, city, courier, sla_breached, and
retry_budget_exhausted. Root causes describe recorded failure categories, not a fresh model
diagnosis. Pending recommendations remain attention cases until real outcome confirmation.

Destination pins come from Address lat/lng, validated for finite values and geographic
bounds. Warehouse origins are existing approximate city centroids, labelled
`approximate: true` and `coordinate_source: city_centroid`. They are not precise facility
coordinates. Connecting endpoints does not reconstruct an actual travelled route. Missing
coordinates yield no point; no geocoded, inferred, or (0,0) fallback is inserted.

The census reads at most 1001 rows and uses the first 1000; if more exist,
`dataset_truncated: true` and `counts_scope: first_1000_shipments` make the counts' scope
explicit. The response returns at most 50 shipments. Their graph follows only curated
shipment evidence branches; Courier/Policy hubs are terminal, avoiding unrelated shipments.
It reads at most 1201 paths and returns at most 500 nodes/800 edges. `graph.truncated` records
any cap; all returned edges have returned endpoints. Node embeddings are omitted.

`GET /graph?shipment_id=SHP-0004` returns that shipment's bounded graph. Missing shipment
IDs return an empty graph. `GET /graph` defaults to the shared attention selection.
`GET /schema` introspects the live shipment database and returns the same nodes/relationships
shape, including EscalatedCase when present. No data or schema is written by these routes.
