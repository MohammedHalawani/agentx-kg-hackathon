# Dataset V2 isolated loader

> Superseded implementation note: the final checkpoint loader uses bounded committed batches, a LOADING manifest, exact resume validation and COMPLETE publication only after full verification. See `2026-10-09-shadow-import-gate.md` for the actual 2000-shipment apply/replay/recovery results. Single-transaction claims below describe the earlier revision.

Recorded 2026-10-08T19:03:03+00:00 (22:03 Asia/Riyadh).

`chat/dataset_v2/load.py` validates the full frozen export offline by rebuilding
`World`, verifying canonical sorted node/edge/gold hashes against the exact executable
manifest, and rerunning `dataset_v2.validate.validate_world`. Saved validation and
statistics must equal recomputed reports; a writable PASS report is insufficient.
Gold remains in offline memory and is never supplied to a database transaction.

Default invocation is offline dry-run and does not import live configuration or create
a driver. Applying requires both `--apply` and an explicit isolated database. The safe
name is `shipments-v2-demo`: Neo4j permits letters/digits/dots/dashes, not underscores.
Explicit invalid names are refused, not redirected. Naming reference:
[Neo4j naming rules](https://neo4j.com/docs/operations-manual/current/database-administration/standard-databases/naming-databases/).

The loader accepts only uncredentialed `bolt://localhost:7687`, `127.0.0.1` or `::1`
endpoints (default port may be omitted). It refuses configured domain/chat/default
databases, `neo4j`, `system`, aliases, default/home/nonstandard/offline targets and
targets outside `shipments-v2-`. Kernel Enterprise edition is verified before database
creation. The target's content and schema are inspected before constraint/index DDL.

All data and the immutable COMPLETE manifest marker are created in one transaction.
The marker and entity IDs have uniqueness constraints; all imported labels/types come
from contract allowlists. UTC fields become typed temporal properties. Primitive
properties retain types; unsupported maps, mixed arrays, nonfinite values and integers
outside Neo4j's signed 64-bit range are refused. JSON nulls represent absent properties.

Exact replay compares full properties, types, labels, topology, record hashes and
manifest, reports zero added nodes/edges and issues no graph-data writes. Existing
foreign, incompatible or tampered content is refused rather than overwritten. There
is no clear, delete, drop, model call, notification or V1 configuration switch.
Reports distinguish domain entities from the one metadata manifest node: `nodes` is
the export entity count, `total_graph_nodes` includes the marker, and `added_nodes`
counts all newly created nodes while `added_entities` counts domain records only.

Database creation and DDL are separate from the graph transaction. A failed import
may leave an empty isolated database with loader indexes/constraints; rerun safely
retries the complete transaction. There are no partially committed data checkpoints.
Large worlds require transaction memory proportional to the exported graph; the main
2000-shipment profile still needs its actual import gate before performance is claimed.

Examples from `chat/` (actual apply is reserved for the coordinator's reviewed gate):

```powershell
.venv/Scripts/python.exe -m dataset_v2.load ../artifacts/dataset-v2/main
.venv/Scripts/python.exe -m dataset_v2.load ../artifacts/dataset-v2/main --apply --database shipments-v2-demo
.venv/Scripts/python.exe -m dataset_v2.load ../artifacts/dataset-v2/main --database shipments-v2-demo --export-target ../artifacts/dataset-v2/recovery
```

Read-only recovery export verifies the target then writes node/edge snapshots and its
manifest to a new local directory. It includes no gold and never removes the target.
Retain the original frozen scoring export for full reload. Dry-run output includes
manual inspection queries; shipment journey query takes a DEMO `shipment_id` parameter.
