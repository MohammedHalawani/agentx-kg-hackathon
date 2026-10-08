# Shipment product coherence — backend gate

Timestamp: 2026-10-07T22:22:12+03:00. Backend gate: **PASS**.
Run: `2026-10-07_shipment-product-coherence`. Browser/UI gate belongs to the coordinator.

`chat/.venv/Scripts/python.exe -m unittest discover -s tests -v`: six tests passed.
Checks cover pending outcome attention, stalled/critical evidence, coordinate validity,
filter/graph identical membership, explicit scan/empty boundaries, and API validation.
Starlette emits a dependency deprecation warning for its httpx TestClient; tests pass and
no dependency was changed for this reversible feature.

Live read-only FastAPI TestClient against verified local synthetic SHIPMENT_DATABASE:

| Filter | HTTP | Returned / total | Nodes / edges | Graph clipped |
| --- | --- | --- | --- | --- |
| needs_attention | 200 | 25 / 70 | 301 / 334 | false |
| all | 200 | 25 / 300 | 326 / 357 | false |
| stalled | 200 | 16 / 16 | 195 / 212 | false |
| critical | 200 | 25 / 28 | 310 / 344 | false |
| delivered | 200 | 25 / 80 | 244 / 275 | false |

For every filter, selected shipment IDs exactly equal Shipment node IDs in the graph;
all returned graph relationships have returned endpoints. All filters obey their shared
flags and graph caps. Counts are all_shipments, dataset_truncated false.

Selected SHP-0004 graph: 14 nodes / 14 edges, exactly one Shipment (SHP-0004).
Missing selected shipment: empty graph. Shipment schema: 11 nodes / 11 relationship types,
includes Shipment and EscalatedCase, excludes governance Person. Invalid lost filter,
limits 0/51, and empty shipment ID: 422. `git diff --check` passed.

Maximum limit live check (all, 50): 50 selected shipments, 500 nodes / 516 edges,
graph.truncated true. All 50 shipment seeds are retained and every edge has returned endpoints.
Final six-test repeat after the city-without-map-point refinement passed; compileall passed.

No model calls, DB writes, .env reads in outputs, destructive operations, commits, or pushes.
