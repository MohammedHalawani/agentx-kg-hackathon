# Shadow import gate

PASS: the frozen 2000-shipment main export was imported into `shipments-v2-demo`, verified against every canonical property, typed UTC value, label, relationship and immutable manifest. Actual counts: 198454 domain entities, one manifest node, 456026 source relationships. The actual replay reported zero added entities, relationships and manifest nodes. Gold was never imported.

The host is local Neo4j Enterprise 2026.09.0. Its transaction memory limit made the original single large transaction unsuitable. The final loader commits at most1000 source records per checkpoint under a strict LOADING manifest. It refuses read/runtime access until complete exact content verification publishes COMPLETE. Interruptions can resume only the same exact manifest; foreign or tampered records are refused. No server memory setting was changed.

V1 remains the configured `shipments` database. Before/after read-only snapshots are exactly equal: 3638nodes,4210relationships, all properties, topology and13ONLINE indexes unchanged. Original vector index remains ONLINE. No V1 benchmark was rerun.

Actual read-only inspection covers10 representative graph paths. Context smoke covers24 development recipes and proves held-out lookup refusal, future timestamp filtering, private-field removal, bounded route layers, independent vehicle GPS semantics and bounded verified historical retrieval. No provider call.

A recovery export was produced after complete replay validation. Its 198454node and456026edge canonical records match the frozen export. It contains no gold. Retain the original scorer/export bundle for complete reload; the recovery copy preserves graph content. The earlier Windows writer usedCRLF, and normalized canonical records match exactly; the final writer streams explicitLF.

The source graph is immutable. A registered development-only OpsEntity ledger may exist only after COMPLETE and is validated separately during replay. Its topology cannot cross shipments or attach to held-out evidence. There is no destructive cleanup/reset command in the importer. Runtime is fenced to this synthetic shadow; rollback to V1 is available via explicitly scoped V1 diagnostic routes with unchanged configuration. Actual deletion or replacement is not performed.

Detailed evidence: `2026-10-09-import-result.json`, `2026-10-09-replay-result.json`, `2026-10-09-recovery-result.json`, `2026-10-09-v1-preservation.json`, `2026-10-09-graph-inspection.json`, `2026-10-09-read-content-smoke.json`. Native driver acceleration was used only for large read-only auditing; the public driver API is unchanged ([Neo4j performance documentation](https://neo4j.com/docs/python-manual/current/performance/)).
