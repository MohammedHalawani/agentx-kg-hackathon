# Batch4 isolated import audit

Neo4j Kernel2026.09.0 Enterprise supports a separate standard database. Exact target:shipments-v2-demo; underscore names are invalid and refused. V1 shipments/default neo4j/system/aliases/home/configured domains are protected. Local endpoint only, no unknown server. V1 full read-only snapshot captured before DDL.

Read-only settings inspection found1GiB heap and716.80MiB total transaction memory. A single654480-object transaction is unsafe at this size. Bounded1000-row committed checkpoints in an isolated LOADING target are used instead; interruption can resume only the same frozen manifest and exact verified subset. COMPLETE is published after full content/schema verification. The target remains disconnected from active V1 API. Future mutable OpsEntity ledger must not modify immutable dataset objects or import manifest.

No server memory settings are changed. No DROP/DELETE/clear operation or active database switch is used. An original frozen export plus verified read-only recovery export provide reconstruction; reversibility is logical and isolation-based, not a claim of whole-import atomicity.
