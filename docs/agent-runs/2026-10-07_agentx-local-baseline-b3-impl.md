# Batch 3 Implementation — `neo4j-shipment-graph-baseline`

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-local-baseline` |
| **Batch slug** | `neo4j-shipment-graph-baseline` |
| **Agent** | BATCH 3 IMPLEMENTATION (resume) |
| **Repository** | `C:\Projects\demo` |
| **Status** | **COMPLETE** |
| **Audit reference** | `docs/agent-runs/2026-10-07_agentx-local-baseline-b3-audit.md` |
| **Final sign-off** | `docs/agent-runs/2026-10-07_agentx-local-baseline-final-signoff.md` |

---

## Gate result (2026-10-07 resume)

| Check | Result |
| --- | --- |
| **`bolt://127.0.0.1:7687`** | **Reachable** |
| **Neo4j** | **Enterprise** `2026.09.0`; `shipments` **online** |
| **Pre-load census** | **0** nodes on `shipments` — safe to wipe |
| **`load_shipment_graph.py` dry-run** | **7848** statements; Arabic sample OK |
| **`load_shipment_graph.py --yes`** | **Complete** (target DB **`shipments`** via `SHIPMENT_DATABASE`) |
| **`reset_shipment_graph.py`** | **165** resolved / **75** open |
| **`embed_backfill_shipments.py`** | **165** embedded; index **`failurereason_case_summary`** **ONLINE**; dim **1024** |

---

## Node / rel verification

| Label | Count |
| --- | ---: |
| Shipment | 300 |
| Order | 300 |
| Customer | 300 |
| Address | 355 |
| Courier | 25 |
| Policy | 3 |
| Event | 1780 |
| FailureReason | 240 |
| Resolution | 165 |
| Outcome | 165 |

Relationship types present: `HAS_EVENT`, `DELIVERED_TO`, `LIVES_AT`, `HAS_SHIPMENT`, `PLACED_BY`, `ASSIGNED_TO`, `GOVERNED_BY`, `CAUSED_BY`, `RESOLVES_WITH`, `HAD_OUTCOME`.

Arabic samples verified on `:Courier` names and `:Resolution` actions.

---

## Operator note

Repo root `.env` had `SHIPMENT_DATABASE=neo4j` at resume; corrected to **`shipments`** during this run so loaders and API match the isolated shipment graph (governance remains on `neo4j`).

No commit or push.
