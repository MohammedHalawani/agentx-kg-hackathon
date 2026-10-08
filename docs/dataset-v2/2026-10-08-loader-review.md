# Dataset V2 loader review evidence

> Superseded implementation note: the final checkpoint loader uses bounded committed batches, a LOADING manifest, exact resume validation and COMPLETE publication only after full verification. See `2026-10-09-shadow-import-gate.md` for the actual 2000-shipment apply/replay/recovery results. Single-transaction claims below describe the earlier revision.

Recorded 2026-10-08T19:03:03+00:00 (22:03 Asia/Riyadh).

Focused offline suite: **17 tests PASS**, `chat/.venv/Scripts/python.exe -m unittest
tests.test_v2_import -v` from `chat/`. Tests use small importer envelope fixtures and a
transactional fake driver; domain fixtures are independently tested by the validator.
No actual database writes were performed by the loader author.

Coverage includes canonical order-independent digest validation, duplicate identities,
dangling edges, changed content, forged reports/statistics, recomputed domain rejection,
dry-run configuration/driver isolation, local/protected/alias/home/Enterprise fences,
foreign schema refusal before DDL (including a nonunique marker index using our name),
typed UTC, scoring sentinel exclusion from all transaction parameters, injected edge
failure rollback, replay without added objects, actual-property/topology corruption,
timestamp/scalar type tampering, in-memory bundle mutation, compatible schema replay
and read-only recovery export. A completed target missing required constraints/indexes
is refused; both Cypher 5 and Cypher 25 node-uniqueness type spellings are accepted.

Actual local **read-only** syntax checks passed for Kernel component detection, database
inventory, indexes and constraints. Server: Neo4j Kernel Enterprise 2026.09.0; existing
database names at inspection: `neo4j`, `shipments`, `system`. `dbms.components()` also
returns a Cypher component, so the loader explicitly selects the Kernel row rather
than relying on ambiguous result ordering.

Pending integrated gate: a real generated export must pass the real domain validator,
then the coordinator reviews and performs the isolated import, identical replay and
V1 before/after fingerprint checks. The fake driver's atomic rollback is a unit proof
of transaction boundaries, not an observed Neo4j rollback or performance claim.
