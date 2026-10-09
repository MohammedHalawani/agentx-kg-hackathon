# Operator resume checklist — `2026-10-07_agentx-local-baseline`

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-local-baseline` (+ sibling `2026-10-07_agentx-ollama-cloud`) |
| **Repository** | `C:\Projects\demo` |
| **Branch** | `fhd` @ `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` (local **ahead of `origin/fhd` by 8**; no push unless authorized) |
| **Purpose** | Single operator-facing gate before re-triggering full local baseline resume (B3 graph → eval → app) |
| **Last probe** | 2026-10-07 (this document) |

**No secrets in this file.** Never paste API keys or Neo4j passwords in chat or run docs.

---

## Completed checkpoint summary

| Checkpoint | Status | Evidence |
| --- | --- | --- |
| **B1 — git `repo-integrity-sync`** | **PASS** | `fhd` fast-forwarded to `origin/main` (`2b9f7c8`); clean tree aside from run docs — `b1-gate.md` |
| **B2 — deps `runtime-dependency-baseline`** | **PASS** | `uv sync` (Python **3.12.3**), `npm ci`, `npm run test` / `lint` / `build` — `b2-gate.md` |
| **Ollama local + `bge-m3`** | **Ready** | Ollama **0.40.0**, `:11434` HTTP 200, `bge-m3` pulled, LiteLLM embedding **1024** dims — `ollama-cloud-b1-impl.md`, `b2-install.md` |
| **`chat/config.py` fallback** | **Done** | `LLM_API_KEY` ← `OPENAI_API_KEY` ← `OLLAMA_API_KEY` — `ollama-cloud-b2-review.md` |
| **Frontend production build** | **Pass** | Vite **8.1.1** → `frontend/dist/` (gitignored) — `b2-impl.md` / `b2-gate.md` |
| **B3 Neo4j shipment graph** | **PASS** | Loaded on `shipments`; 165/75 split — `b3-impl.md`, `local-baseline-final-signoff.md` |
| **Cloud LLM smoke (B3 gate)** | **PASS** | `openai/gpt-oss:20b` @ `ollama.com/v1` — `ollama-cloud-b3-integration.md` |
| **Ollama Cloud `gpt-oss` model eval** | **PASS** | 20b + 120b matrix — `ollama-cloud-model-eval.md`, `_agentx_gpt_oss_eval_results.json` |

---

## Ollama Cloud `gpt-oss` eval — unblock (repo root `.env` only)

Set the key on **repo root** `.env` (`C:\Projects\demo\.env`), **not** `chat/.env`. `chat/config.py` loads that file via `load_dotenv(parents[1] / ".env")`.

| Item | Value |
| --- | --- |
| **Required** | `OLLAMA_API_KEY=<key>` **or** `LLM_API_KEY=<key>` (never commit; never paste in chat/docs) |
| **Also set (non-secret)** | `LLM_API_BASE=https://ollama.com/v1` |
| **Primary model id** | `openai/gpt-oss:20b` (API chat name: `gpt-oss:20b`) |
| **Fallback compare** | `openai/gpt-oss:120b` (API: `gpt-oss:120b`) |

**Deferred test order (per model: 20b then 120b):** (1) direct `POST https://ollama.com/v1/chat/completions` → `AGENTX_OLLAMA_OK`; (2) JSON-only `{"status":"ok","provider":"ollama_cloud"}`; (3) Arabic logistics snippet; (4) LiteLLM + `ChatLiteLLM` @ same base; (5) `ask_json()` trivial schema; (6) `extract_entities()` smoke (Neo4j optional). **No local `gpt-oss` pulls.** After both pass, default winner **`openai/gpt-oss:20b`** unless 120b latency justifies everywhere — then set `LLM_MODEL` in repo root `.env` and write `b3-integration.md`.

**Re-probe after key:** from `chat/`, `uv run python -c "import config; print(len(config.LLM_API_KEY or ''))"` → must be **> 0** (length only).

---

## Active blockers

**None (2026-10-07 resume).** Final sign-offs: `2026-10-07_agentx-local-baseline-final-signoff.md`, `2026-10-07_agentx-ollama-cloud-final-signoff.md`.

### Blocker 1 — `OLLAMA_API_KEY` in repo root `.env` (historical)

| Item | Detail |
| --- | --- |
| **Why** | Ollama Cloud chat/pipeline uses `https://ollama.com/v1` with Bearer auth; `eval_pipeline.py -n 3` and `ChatLiteLLM` need a non-empty `config.LLM_API_KEY`. |
| **Operator action** | Create a key at [ollama.com](https://ollama.com) ([cloud docs](https://docs.ollama.com/cloud.md)). Add **one** line to **repo root** `.env` only (never `chat/.env`, never commit): `OLLAMA_API_KEY=<your-key>` **or** `LLM_API_KEY=<your-key>`. |
| **Target models (post-unblock)** | `LLM_MODEL=openai/gpt-oss:20b` (preferred) or `openai/gpt-oss:120b` after eval — see `ollama-cloud-model-eval.md`. |
| **Already on disk (non-secret)** | `LLM_API_BASE=https://ollama.com/v1`; prior `gemma4:31b` placeholder **out of scope** for current eval. |
| **Do not** | Paste the key in chat, commit `.env`, or duplicate into tracked files. |

### Blocker 2 — Neo4j on **7687** (`bolt://127.0.0.1:7687`)

| Item | Detail |
| --- | --- |
| **Why** | Shipment load, census, embeddings backfill, `eval_pipeline`, and FastAPI driver init all require Bolt. |
| **Verify** | `Test-NetConnection 127.0.0.1 -Port 7687` → `TcpTestSucceeded : True` |

#### Start Neo4j (pick one path)

**Neo4j Desktop (recommended for multi-database `shipments`)**

1. Install [Neo4j Desktop](https://neo4j.com/download/) if needed.
2. Create or open a local DBMS (**5.11+** minimum for vector indexes; **5.25+** recommended — see Cypher note below).
3. Set DBMS password to match `NEO4J_PASSWORD` in repo root `.env` (edit locally only).
4. **Start** the instance; confirm Bolt on **7687** (default).
5. Re-run port test above.

**Docker** (after Docker Desktop / engine is running)

```powershell
docker run -d --name neo4j-shipments `
  -p 7474:7474 -p 7687:7687 `
  -e NEO4J_AUTH=neo4j/<password-matching-.env> `
  neo4j:5.25
```

Adjust image tag and auth to match `.env`. A separate **`shipments`** database needs **Enterprise**, **Aura**, or **Desktop multi-DB** — not Community single-DB only.

**Windows service**

If Neo4j is installed as a service, start from Services (`services.msc`) or the installer UI, then verify port **7687**.

#### Community vs `SHIPMENT_DATABASE=shipments`

| Edition | Implication |
| --- | --- |
| **Community** | Single database (`neo4j` only). **`SHIPMENT_DATABASE=shipments` will not work** unless you use Enterprise/Aura/Desktop multi-DB or an explicit operator plan to repoint shipment scripts — **never** auto-wipe `neo4j` (governance + chat share it per `.env.example`). |
| **Enterprise / Aura / Desktop (multi-DB)** | Ensure `SHOW DATABASES` lists `SHIPMENT_DATABASE` (default **`shipments`**). Create with `CREATE DATABASE shipments` if missing. |

#### Cypher 25 / server version note

- `chat/view/subgraph.py` and `chat/core/threads.py` use **`CYPHER 25`** (correlated subqueries).
- **Recommended:** Neo4j **5.25+** so explore/chat match server capabilities.
- **Minimum for vectors:** **5.11+** (`embed_backfill_shipments.py`, `db.index.vector.queryNodes`).
- **Shipment Cypher file** (`shipment_kg/shipment_dataset.cypher`) has no `CYPHER 25` prefix — load can succeed on older 5.x even if explore/chat fail until server or prefix is aligned.

#### Pre-load census (read-only — before any `--yes` wipe)

Run in Browser or `cypher-shell` with credentials from local `.env` only on this machine:

```cypher
SHOW DATABASES;
CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition;
```

On shipment DB (name from `SHIPMENT_DATABASE`, default `shipments`):

```cypher
MATCH (n) RETURN count(n) AS node_count;
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c ORDER BY c DESC LIMIT 15;
MATCH (f:FailureReason)
RETURN sum(CASE WHEN (f)-[:RESOLVES_WITH]->() THEN 1 ELSE 0 END) AS resolved,
       sum(CASE WHEN NOT (f)-[:RESOLVES_WITH]->() THEN 1 ELSE 0 END) AS open;
```

**STOP before `load_shipment_graph.py --yes` if:** DB missing, wrong labels (e.g. `ChatThread` in shipment DB), unknown non-disposable data, or Bolt unreachable. Full STOP table: `b3-audit.md`.

---

## Ordered re-run sequence (when both blockers cleared)

Execute in order; stop on any failure.

| Step | Action | Working dir / command |
| --- | --- | --- |
| **1** | **Cloud B3 smoke** (LLM) | `cd C:\Projects\demo\chat` — direct `POST https://ollama.com/v1/chat/completions` smoke (`AGENTX_OLLAMA_OK`), then LiteLLM H1 (`openai/gemma4:31b`), then `uv run python -c "from llm.pipeline._llm import model; print(model().invoke('AGENTX_OLLAMA_OK').content[:80])"` |
| **2** | **Neo4j census** | Read-only Cypher above on `SHIPMENT_DATABASE`; document edition/version from `dbms.components()` |
| **3** | **Load shipment graph** | `uv run python scripts/load_shipment_graph.py` (dry-run: ~**7848** statements, Arabic sample OK) → only if census clears: `uv run python scripts/load_shipment_graph.py --yes` |
| **4** | **Verify seed split** | `uv run python scripts/reset_shipment_graph.py` — expect **165** resolved / **75** open (no `--yes` on fresh seed) |
| **5** | **Embed + vector index** | Local Ollama on `:11434` with `bge-m3`; `uv run python scripts/embed_backfill_shipments.py --dry-run` then real run; confirm index **`failurereason_case_summary`** ONLINE |
| **6** | **Pipeline eval** | `uv run python scripts/eval_pipeline.py -n 3` (add `--hard` if coordinator script requires) |
| **7** | **App + HTTP checks** | From repo root: `uv run --project chat uvicorn --app-dir backend main:app --host 127.0.0.1 --port 8000` — smoke `http://127.0.0.1:8000` (health/graph endpoints per README) |

**Ollama PATH tip:** If `ollama` is not on PATH, use `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`.

---

## Live probe results (2026-10-07)

Probes run for this checklist only; values were **not** printed.

| Probe | Result | Satisfied? |
| --- | --- | --- |
| **Neo4j `127.0.0.1:7687`** | `TcpTestSucceeded: True` | **Yes** |
| **`config.LLM_API_KEY` effective** (`uv run python -c "import config; …"`) | length **57** (not printed) | **Yes** |
| **`shipments` database** | **online**, post-load graph verified | **Yes** |

**Ready to re-trigger full resume:** **Yes** — checkpoint completed; see final sign-off docs.

---

## Files not to commit

| Path | Reason |
| --- | --- |
| **`.env`** (repo root) | Neo4j password, `OLLAMA_API_KEY` / `LLM_API_KEY`, any operator secrets |
| **`chat/.venv/`** | Local Python env |
| **`frontend/node_modules/`** | npm install tree |
| **`frontend/dist/`** | Production build output |
| **`chat/__pycache__/`**, `*.pyc` | Python caches |

Run documentation under `docs/agent-runs/` may be committed later when the parent batch authorizes; this checklist contains **no** secrets.

---

## Source run notes (consolidated from)

- `docs/agent-runs/2026-10-07_agentx-local-baseline-b1-*.md` through `b3-*.md`
- `docs/agent-runs/2026-10-07_agentx-ollama-cloud-b1-audit.md`, `b1-impl.md`, `b2-install.md`, `b2-review.md`, `coordinator-status.md`

No commit or push performed for this checklist.
