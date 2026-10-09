# Batch 3 Audit — `neo4j-shipment-graph-baseline`

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-local-baseline` |
| **Batch slug** | `neo4j-shipment-graph-baseline` |
| **Agent** | BATCH 3 AUDIT |
| **Repository** | `C:\Projects\demo` |
| **Branch** | `fhd` @ `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` |
| **Audit mode** | Read-only — no Neo4j load, no wipes, no `.env` read/write |
| **Verdict** | **SCOPE-READY** (implementation **STOP** until Neo4j is up and pre-load census passes) |

---

## Executive summary

The shipment graph baseline is well scripted (`load_shipment_graph.py`, `embed_backfill_shipments.py`) with UTF-8-safe import and destructive wipe isolated to `config.SHIPMENT_DATABASE`. **At audit time Neo4j is not reachable** on `bolt://127.0.0.1:7687`, so no database census was possible. **Ollama is not on PATH** (Batch 2 also noted this); embedding backfill remains blocked until a local `:11434` endpoint with `bge-m3` is available.

Implementation may proceed only after: (1) Neo4j running with credentials in local `.env`, (2) edition-aware handling of the `shipments` database name, (3) read-only inspection proving it is safe to wipe `SHIPMENT_DATABASE`, (4) dry-runs, then (5) `--yes` load and real embed backfill.

---

## Neo4j detection (this machine, 2026-10-07)

| Check | Result |
| --- | --- |
| **`Test-NetConnection 127.0.0.1:7687`** | **TcpTestSucceeded: False** — nothing listening |
| **Windows service `*neo4j*`** | None found |
| **`neo4j` CLI on PATH** | Not found |
| **Neo4j Desktop** (`%LOCALAPPDATA%\Programs\Neo4j Desktop`) | Not in default path |
| **Docker** (`docker ps --filter name=neo4j`) | **Daemon not running** (Desktop Linux engine pipe missing) |
| **Driver connectivity** | Not attempted (would require `.env` password; audit did not load secrets) |

**Neo4j status for parent agent:** **DOWN / unreachable** — operator must start Neo4j Desktop, a local service, or Docker (once daemon runs) before any impl step that calls `get_driver()`.

---

## Prior run context (read-only)

| Document | Relevant takeaway |
| --- | --- |
| **B1 audit** (`…-b1-audit.md`) | Repo at `origin/main`; `.env` exists locally (ignored); three DB names in `.env.example`. |
| **B2 audit/gate** (`…-b2-*`) | `uv`/`npm` baseline **PASS**; Neo4j and Ollama **not** required for B2; Docker daemon stopped. |
| **Ollama cloud B1** (`…-ollama-cloud-b1-audit.md`) | Embeddings stay on local `EMBEDDING_API_BASE`; vector index `failurereason_case_summary` on shipment DB. |
| **B3 status stub** (`…-b3-status.md`) | Coordinator marked **BLOCKED** on Neo4j; claims Ollama ready — **this audit re-check found `ollama` not on PATH** (reconcile before embed step). |
| **UI repair (2026-09)** | `CYPHER 25` prefix broke `GET /graph` on **older** Neo4j (error: use `CYPHER 5` only). Current code still uses **`CYPHER 25`** in `chat/view/subgraph.py` and `chat/core/threads.py` — target server should be **Neo4j 5.25+** (Cypher 25) or impl must align prefix with server (out of scope unless batch expands). |

**Local git note (not modified by audit):** unstaged edit in `chat/config.py` adds `OLLAMA_API_KEY` to `LLM_API_KEY` fallback (from sibling ollama run). Implementation must not rely on audit changing tracked files.

---

## Configuration map: three database names

Loaded from repo root `.env` via `chat/config.py` (`load_dotenv` → `parents[1]/.env`). Neo4j URI/username/password are **required** (`_require()`).

| Variable | Default (`.env.example`) | Used for |
| --- | --- | --- |
| **`NEO4J_DATABASE`** | `neo4j` | Governance / steering-committee domain graph: `chat/core/query_runner.py` (`run()`, `schema_graph()`), `chat/core/registry.py`, `chat/scripts/embed_backfill.py` |
| **`CHAT_DATABASE`** | `neo4j` (same physical DB as governance in template) | Chat threads: `chat/core/threads.py` — `(:ChatThread)-[:HAS_MESSAGE]->(:ChatMessage)` |
| **`SHIPMENT_DATABASE`** | `shipments` | Shipment complaint pipeline + loaders: `load_shipment_graph.py`, `reset_shipment_graph.py`, `embed_backfill_shipments.py`, `chat/llm/pipeline/*` (retrieve, cases, writeback, eval) |

**Important:** Governance and chat **share** `neo4j` in the template; only shipment data is isolated in `shipments`. Wiping `SHIPMENT_DATABASE` does **not** touch governance or chat **when** the name is correct and multi-database routing works.

**Edition risk:** Neo4j **Community** supports a **single** database (`neo4j`). A separate `shipments` database requires **Enterprise**, **Aura**, or **Neo4j Desktop** with multi-database enabled. If `SHOW DATABASES` does not list `shipments`, **STOP** — do not point `SHIPMENT_DATABASE` at a missing DB; resolve with `CREATE DATABASE shipments` (Enterprise) or an explicit operator decision (not auto-wipe `neo4j`).

---

## Key files reviewed

| File | Role |
| --- | --- |
| **`.env.example`** | Bolt URI, three DB names, embedding defaults (`bge-m3`, 1024 dims). |
| **`chat/config.py`** | Env constants; shipment DB comment references sibling dump path. |
| **`chat/core/query_runner.py`** | Shared driver; reads **`NEO4J_DATABASE`** only (not shipment). |
| **`chat/view/subgraph.py`** | Explore graph sample; **`NEO4J_DATABASE`**; `_DISCOVER_CYPHER` starts with **`CYPHER 25`** + `CALL (s) { … }` subqueries. |
| **`backend/main.py`** | FastAPI; imports `query_runner`, `threads`, pipeline, `subgraph` — Neo4j needed at runtime. |
| **`chat/scripts/load_shipment_graph.py`** | UTF-8 read of `shipment_kg/shipment_dataset.cypher`; dry-run default; **`--yes`** → `MATCH (n) DETACH DELETE n` then batched `session.run` on **`SHIPMENT_DATABASE`**. |
| **`chat/scripts/reset_shipment_graph.py`** | Non-destructive undo of `source='agent_pipeline'` resolutions only (not part of baseline load). |
| **`chat/scripts/embed_backfill_shipments.py`** | **`failurereason_case_summary`** vector index; embeds `FailureReason.case_summary` on **`SHIPMENT_DATABASE`**. |
| **`chat/scripts/embed_backfill.py`** | Governance graph embeddings on **`NEO4J_DATABASE`** (schema.yaml-driven); separate from shipment baseline. |
| **`shipment_kg/shipment_dataset.cypher`** | **7848** executable lines (comments stripped); **~1550** lines contain non-ASCII (Arabic names/text). |

---

## Cypher version: hardcodes vs Neo4j server

| Source | Cypher version prefix | Features |
| --- | --- | --- |
| **`chat/view/subgraph.py`** | `CYPHER 25` | `CALL (node) { … }` correlated subqueries |
| **`chat/core/threads.py`** | `CYPHER 25` | Same + `count { (t)-[:HAS_MESSAGE]->() }` pattern |
| **`shipment_kg/shipment_dataset.cypher`** | None (plain `CREATE` / `MATCH`) | Broad Neo4j 5.x compatibility |
| **`embed_backfill_shipments.py`** | `CREATE VECTOR INDEX …`, `db.create.setNodeVectorProperty` | Neo4j **5.11+** vector index API |
| **`chat/llm/pipeline/retrieve.py`** | `db.index.vector.queryNodes` | Same vector stack on **`SHIPMENT_DATABASE`** |

**Expected server:** Neo4j **5.11+** minimum for vector indexes; **5.25+** recommended so `CYPHER 25` matches chat/explore paths without the historical `GET /graph` 500 seen on older servers.

**Shipment load** does not use `CYPHER 25` — load can succeed on an older 5.x even if explore/chat queries fail until server or prefix is aligned.

---

## Database safety: inspect before load

**Never run `load_shipment_graph.py --yes` until all STOP checks below pass.**

### 1. Connect read-only (Browser, cypher-shell, or `uv run` one-liner)

Use credentials from local `.env` only on the operator machine; **do not** paste passwords into run docs.

```cypher
SHOW DATABASES;
CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition;
```

Switch to shipment DB (name from `SHIPMENT_DATABASE`, default `shipments`):

```cypher
MATCH (n) RETURN count(n) AS node_count;
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c ORDER BY c DESC LIMIT 15;
MATCH (f:FailureReason)
RETURN sum(CASE WHEN (f)-[:RESOLVES_WITH]->() THEN 1 ELSE 0 END) AS resolved,
       sum(CASE WHEN NOT (f)-[:RESOLVES_WITH]->() THEN 1 ELSE 0 END) AS open;
```

Optional governance DB (`neo4j`) — **do not wipe**:

```cypher
MATCH (n) RETURN count(n) AS governance_nodes LIMIT 1;
```

### 2. STOP before wipe if

| Condition | Action |
| --- | --- |
| **`SHIPMENT_DATABASE` does not exist** | **STOP** — create DB (Enterprise) or fix `.env`; never fall back to wiping `neo4j` without explicit approval |
| **Unexpected domain labels** in shipment DB (e.g. `Mandate`, `Committee`, `ChatThread`) | **STOP** — likely wrong database name or mixed data; investigate |
| **Node count > 0** and counts are **not** consistent with a prior hackathon seed (~**165** resolved / **75** open failures per `reset_shipment_graph.py` doc) and operator did not confirm disposable data | **STOP** — treat as **unknown user data** |
| **Cannot reach Neo4j** | **STOP** — no load, no embed |
| **About to run `--yes` on `neo4j` DB** because `SHIPMENT_DATABASE` was mis-set | **STOP** — would destroy governance and/or chat |

### 3. What `--yes` does

Single transaction scope per wipe statement: **`MATCH (n) DETACH DELETE n`** on **`SHIPMENT_DATABASE` only** — **irreversible** for that database.

---

## Vector index: `failurereason_case_summary`

| Item | Detail |
| --- | --- |
| **Script** | `chat/scripts/embed_backfill_shipments.py` |
| **Index name** | `failurereason_case_summary` (`VECTOR_INDEX_NAME`) |
| **Label / property** | `:FailureReason(embedding)` |
| **Source text** | `FailureReason.case_summary` (non-null, non-empty — resolved precedent cases only) |
| **Write API** | `db.create.setNodeVectorProperty` (native vector encoding) |
| **Dimensions / similarity** | `config.EMBEDDING_DIMENSIONS` (default **1024**), cosine |
| **Runtime consumer** | `chat/llm/pipeline/retrieve.py` → `db.index.vector.queryNodes($index, …)`; degrades to graph-only if index missing |
| **Prerequisites** | Shipment graph loaded; **local** embedding endpoint (`EMBEDDING_MODEL` / `EMBEDDING_API_BASE`); model output dim must match index |

**Governance counterpart:** `embed_backfill.py` on **`NEO4J_DATABASE`** — optional for shipment baseline; comment in file says **not yet run against live DB** — treat as separate operator action.

**Pipeline write path:** New resolutions from the agent do **not** get embeddings until backfill is re-run (`writeback.py` comment); baseline embed covers seeded **165** resolved cases.

---

## Arabic / UTF-8 import risks

| Risk | Mitigation in repo |
| --- | --- |
| Windows **cp1252** via cypher-shell / PowerShell pipe | **Use `load_shipment_graph.py`** — `path.read_text(encoding="utf-8")` |
| Silent `?` replacement | Loader prints ASCII-safe sample of `Resolution.action`; **exits** if action looks all `?` |
| Console font/display | Audit snippet from file shows proper Arabic in `Courier.name` lines |
| JSON/API downstream | Backend uses `json.dumps(..., default=str)`; frontend commits on `origin/main` address RTL Arabic display (B1 sync) |

**Dry-run acceptance:** Sample line printed in dry-run should show backslash-escaped Arabic, not `?` runs.

---

## Commands for Implementation agent

All from **`chat/`** with repo root `.env` present (password filled locally). Use **`uv run`** so Python ≥3.12 matches Batch 2.

### Shipment graph

```powershell
cd C:\Projects\demo\chat
uv run python scripts/load_shipment_graph.py
# Expect: Database shipments, ~7848 statements, Arabic sample snippet
uv run python scripts/load_shipment_graph.py --yes
# Destructive: only after census STOP checks pass
```

Optional alternate file:

```powershell
uv run python scripts/load_shipment_graph.py --yes --file ..\shipment_kg\shipment_dataset.cypher
```

### Shipment embeddings + vector index

```powershell
uv run python scripts/embed_backfill_shipments.py --dry-run
# Expect: ~165 resolved case(s) to embed (order of magnitude)
uv run python scripts/embed_backfill_shipments.py
```

Ensure Ollama (or configured embedding host) is running and `bge-m3` is pulled before non-dry-run.

### Optional governance embeddings (separate DB)

```powershell
uv run python scripts/embed_backfill.py --dry-run
uv run python scripts/embed_backfill.py
```

### Post-load sanity (read-only)

```powershell
uv run python scripts/reset_shipment_graph.py
# Expect: 165 resolved / 75 open, 0 agent_pipeline resolutions on fresh seed
```

---

## Exact scope (Batch 3 implementation)

| In scope | Out of scope (unless expanded) |
| --- | --- |
| Start Neo4j locally; verify bolt URI | Committing `.env` or passwords |
| Pre-load census on `SHIPMENT_DATABASE` | Wiping `neo4j` / governance graph |
| `load_shipment_graph.py` dry-run → `--yes` | `reset_shipment_graph.py --yes` unless undoing agent demo |
| `embed_backfill_shipments.py` dry-run → real | Full `embed_backfill.py` unless governance vectors required |
| Run docs under `docs/agent-runs/` | Fixing `CYPHER 25` / subgraph without explicit batch |
| | Overwriting operator `.env` |

Audit agent created **only** this markdown file.

---

## Risks

| Risk | Impact |
| --- | --- |
| Neo4j offline | All scripts using `get_driver()` fail |
| Community single-DB vs `shipments` name | Load targets missing or wrong DB |
| `--yes` wipe on misconfigured `SHIPMENT_DATABASE` | Data loss in wrong graph |
| Ollama / embeddings offline | Load succeeds; pipeline vector retrieval empty (graph-only) |
| `EMBEDDING_DIMENSIONS` ≠ model output | Index create or query failures |
| Neo4j < 5.11 | Vector index / `setNodeVectorProperty` unsupported |
| Neo4j < 5.25 with `CYPHER 25` | Chat threads / Explore graph queries fail |
| Long import (~7848 stmts) | Timeouts — tune `--batch` if needed (default 100) |
| Uncommitted `chat/config.py` | Impl/review should not confuse with shipment baseline |

---

## STOP conditions (implementation)

1. **Bolt not reachable** after operator start attempt.
2. **`SHIPMENT_DATABASE` not listed** and no approved plan to create it.
3. **Pre-load census** shows unknown or business-critical data in shipment DB.
4. **Dry-run** Arabic sample shows corruption (`?` only).
5. **Embedding dry-run** attempted while embedding service down — STOP before real run (wastes time / partial writes).
6. **Verification** after load: `reset_shipment_graph.py` coverage far from **165 / 75** without explanation.

---

## Acceptance criteria

### Implementation

- [ ] Neo4j reachable at `NEO4J_URI` (from `.env`, not recorded in docs).
- [ ] `SHOW DATABASES` includes `SHIPMENT_DATABASE` value (default `shipments`).
- [ ] Pre-load census documented in impl notes; **STOP** conditions cleared.
- [ ] `load_shipment_graph.py` dry-run: **7848** statements, Arabic sample OK.
- [ ] `load_shipment_graph.py --yes` completes; verification `Resolution.action` not all `?`.
- [ ] `reset_shipment_graph.py` (no `--yes`): **165** resolved / **75** open (seeded split).
- [ ] `embed_backfill_shipments.py --dry-run`: ~**165** cases.
- [ ] `embed_backfill_shipments.py` completes; index **`failurereason_case_summary`** ensured.
- [ ] No secrets in committed run markdown; `.env` unchanged by agents unless operator opts in.

### Review / Gate

- [ ] Confirms only `SHIPMENT_DATABASE` was wiped, not governance/chat.
- [ ] Confirms lockfiles and unrelated product source untouched.
- [ ] Records Neo4j **edition + version** from `dbms.components()`.

---

## Blockers (current)

| Blocker | Severity |
| --- | --- |
| **Neo4j not listening on 7687** | **Critical** — blocks entire batch impl |
| **Cannot verify DB census** (consequence of above) | **Critical** — blocks `--yes` |
| **Ollama not on PATH** / embedding host unverified | **High** — blocks embed backfill, not Cypher load |
| **Multi-database `shipments` vs Community edition** | **High** — must be resolved before load |
| **Docker daemon stopped** | **Low** — only if Neo4j planned via containers |

---

## Audit conclusion

**SCOPE-READY** for `neo4j-shipment-graph-baseline`: scripts, env split, UTF-8 path, and vector index contract are clear. **Implementation must STOP** on destructive steps until Neo4j is running and the shipment database pre-load census approves a wipe.

**Audit path:** `docs/agent-runs/2026-10-07_agentx-local-baseline-b3-audit.md`
