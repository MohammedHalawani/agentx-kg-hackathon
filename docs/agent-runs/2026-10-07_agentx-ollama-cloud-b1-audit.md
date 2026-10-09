# Batch 1 Audit — Ollama Cloud LLM + local embeddings

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-ollama-cloud` |
| **Batch** | B1 — AUDIT ONLY |
| **Repository** | `C:\Projects\demo` |
| **Branch** | `fhd` @ `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` |
| **Verdict** | **SCOPE-READY** |

---

## Desired architecture (run goal)

| Layer | Target |
| --- | --- |
| Agents / orchestration | LangGraph + Python in `chat/` (local process) |
| Chat + pipeline LLM | Ollama **Cloud** via OpenAI-compatible API (`https://ollama.com/v1`, Bearer API key) |
| Graph DB | Neo4j local (`bolt://127.0.0.1:7687`) |
| Embeddings | **Local** Ollama at `http://127.0.0.1:11434`, model `bge-m3` (no large local **chat** LLM pulls) |

---

## Official Ollama documentation (fetched 2026-10-07)

Sources: [llms.txt](https://docs.ollama.com/llms.txt), [quickstart](https://docs.ollama.com/quickstart.md), [cloud](https://docs.ollama.com/cloud.md), [API introduction](https://docs.ollama.com/api/introduction.md), [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility.md), [cloud model search](https://ollama.com/search?c=cloud).

| Topic | Official guidance |
| --- | --- |
| Cloud auth | `OLLAMA_API_KEY` env var; `Authorization: Bearer` on `https://ollama.com/api/*` and `https://ollama.com/v1/*` |
| OpenAI client cloud | `base_url="https://ollama.com/v1"`, `api_key=os.environ["OLLAMA_API_KEY"]`, `model` e.g. **`gemma4:31b`** |
| Model names | **API / direct cloud:** names from `curl https://ollama.com/api/tags` (docs examples: `gemma4:31b`). **App/CLI:** suffix `:cloud` (e.g. `gemma4:cloud`) — **not** the string to send to `ollama.com/v1` |
| Local OpenAI shim | `http://localhost:11434/v1/` — API key required by client but **ignored**; cloud-through-local requires Ollama app sign-in |
| Embeddings | Separate capability; cloud docs focus on chat — this repo correctly keeps embeddings on local `:11434` |
| Usage / cost | Cloud page lists per-model usage tiers (e.g. **gemma4** — “Low usage”; many others Medium/High). Balance/usage APIs documented; no guarantee of unlimited free tier — plan for API key + credits |

---

## Secret handling (audit checks)

| Check | Result |
| --- | --- |
| `.env` in root `.gitignore` | **Yes** (line 21) |
| `.env` on disk | **Exists** (contents **not** read) |
| `OLLAMA_API_KEY` in process/user/machine env | **Absent** (non-zero length: **no**) |
| `LLM_API_KEY` / values in `.env` | **Not inspected** |

Implementation batches must never log or commit API keys. Prefer `LLM_API_KEY` / `OLLAMA_API_KEY` in `.env` only.

---

## How configuration is loaded

`chat/config.py` loads **repo root** `.env` via `load_dotenv(Path(__file__).resolve().parents[1] / ".env")` and exposes module-level constants. Neo4j vars use `_require()`; LLM/embedding vars do not fail-fast if missing (except Neo4j).

---

## 1. LLM env consumption (`LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY`)

| Variable | Definition (`config.py`) | Consumers |
| --- | --- | --- |
| `LLM_MODEL` | `os.getenv("LLM_MODEL", "gpt-4o-mini")` | `ChatLiteLLM(model=...)` in `chat/llm/agent.py` (`_agent`) and `chat/llm/pipeline/_llm.py` (`model`) |
| `LLM_API_KEY` | `os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")` | Same `ChatLiteLLM(api_key=...)` call sites |
| `LLM_API_BASE` | `os.getenv("LLM_API_BASE")` (optional) | Same `ChatLiteLLM(api_base=...)` call sites |

**Call pattern (both agent and pipeline):**

```python
ChatLiteLLM(
    model=config.LLM_MODEL,
    api_key=config.LLM_API_KEY,
    api_base=config.LLM_API_BASE,
    temperature=0,
    # agent.py also: streaming=True
)
```

**Pipeline stages** using shared `_llm.model()`: `extract.py`, `classifier.py`, `recommender.py`, `reviewer.py` (all JSON-oriented via `ask_json`).

**Not wired today:** `OLLAMA_API_KEY` is **not** read in `config.py`. Ollama’s documented env name will not reach `ChatLiteLLM` unless the operator duplicates the value into `LLM_API_KEY` (or `OPENAI_API_KEY`).

**Comment in `config.py` already documents the intended pattern for OpenAI-compatible hosts:** `openai/<model> + LLM_API_BASE` (vLLM/LM Studio); Ollama Cloud’s `https://ollama.com/v1` is the same class of endpoint per Ollama OpenAI compatibility docs.

---

## 2. Embedding env consumption

| Variable | Default | Consumers |
| --- | --- | --- |
| `EMBEDDING_MODEL` | `ollama/bge-m3` | `litellm.embedding(model=..., api_base=...)` |
| `EMBEDDING_API_BASE` | `http://localhost:11434` | Same |
| `EMBEDDING_DIMENSIONS` | `1024` | Vector index creation in `chat/scripts/embed_backfill.py`, `embed_backfill_shipments.py` |

**Runtime paths:**

- `chat/llm/pipeline/retrieve.py` — `_embed()` on each vector search (complaint pipeline).
- `chat/scripts/embed_backfill_shipments.py` — batch backfill for `FailureReason.case_summary` (precedent index).
- `chat/scripts/embed_backfill.py` — governance graph backfill (separate from shipment pipeline).

Embeddings do **not** pass `api_key` today; local Ollama matches Ollama docs (key ignored on localhost). Cloud LLM key does not affect embeddings if `EMBEDDING_API_BASE` stays on `127.0.0.1:11434`.

---

## 3. Can `ChatLiteLLM` use Ollama Cloud OpenAI-compatible endpoint with **current** code?

**Likely yes, without code changes**, if environment is set correctly:

- `LLM_API_BASE=https://ollama.com/v1` (no trailing slash required for most clients; match B2 smoke test)
- `LLM_API_KEY` set to a valid Ollama cloud API key (Bearer)
- `LLM_MODEL` set to a LiteLLM provider string that routes to OpenAI-compatible chat completions against `api_base`

**Gap:** `config.py` does not map `OLLAMA_API_KEY` → `LLM_API_KEY`, so operators using only Ollama’s documented env var will get `api_key=None` unless they also set `LLM_API_KEY`.

**No application code** sets `openai_api_base` separately — everything goes through `ChatLiteLLM`’s `api_base` parameter (langchain-litellm ≥0.2.4, litellm ≥1.61 per `pyproject.toml` / lock).

---

## 4. Cleanest integration route (verify in B2 — do not assume LiteLLM strings)

Ollama official OpenAI cloud example:

- Host: `https://ollama.com/v1`
- Model id in request body: **`gemma4:31b`** (and siblings from `/api/tags`)

Repo convention for custom OpenAI bases:

- `LLM_API_BASE=https://ollama.com/v1`
- `LLM_MODEL=openai/<exact-ollama-model-id>`

### LiteLLM model string hypotheses — **TEST in B2** (ordered)

| # | `LLM_MODEL` | `LLM_API_BASE` | `LLM_API_KEY` | Notes |
| --- | --- | --- | --- | --- |
| H1 | `openai/gemma4:31b` | `https://ollama.com/v1` | Ollama API key | Aligns with `config.py` comment; matches Ollama curl examples |
| H2 | `gemma4:31b` | `https://ollama.com/v1` | Ollama API key | LiteLLM sometimes accepts bare model + `api_base` |
| H3 | `ollama/gemma4:31b` | `https://ollama.com/v1` | Ollama API key | **Risk:** `ollama/` provider may target local Ollama semantics — try only if H1/H2 fail |
| H4 | `openai/gemma4:12b` or `openai/nemotron-3-nano:4b` | `https://ollama.com/v1` | Ollama API key | Smaller / “Low usage” cloud models from [cloud search](https://ollama.com/search?c=cloud) if latency/cost matters |

**Do not use** `gemma4:cloud` as the API model id (CLI/app alias per [cloud.md](https://docs.ollama.com/cloud.md)).

**Anti-goal confirmed:** avoid `ollama pull` of large local chat weights (`qwen3:8b`, `gemma4:e2b` ~7.2GB, etc.) for this run.

---

## 5. Source changes required?

| Change | Priority | Rationale |
| --- | --- | --- |
| **Minimal `OLLAMA_API_KEY` fallback** in `config.py` for `LLM_API_KEY` | **Recommended** | Matches Ollama docs; avoids duplicating secret under two names |
| Update `.env.example` + README | **Recommended** | Document Ollama Cloud split: cloud LLM vars vs local embedding vars |
| Changes to `agent.py` / `_llm.py` / pipeline | **Not required** for baseline routing | Already pass `api_base` / `api_key` / `model` |
| `retrieve.py` `MIN_VECTOR_SCORE` | **No change** for Ollama Cloud LLM work | Tied to **embedding** model distribution, not chat provider |

Optional B3+: map `EMBEDDING_API_BASE` default to `http://127.0.0.1:11434` in docs only (`.env.example` already uses `localhost`).

---

## 6. `retrieve.py` — `MIN_VECTOR_SCORE` / bge-m3 calibration

Constant: **`MIN_VECTOR_SCORE = 0.78`** (cosine similarity floor).

Documented in-file rationale (bge-m3 on this shipment corpus):

- Real complaints: top-1 scores ~**0.826–0.848**
- Junk queries: ~**0.688–0.710**
- Floor **0.78** leaves ~0.07 margin on each side

**If `EMBEDDING_MODEL` changes**, re-measure and adjust — not a universal constant. Ollama Cloud LLM switch does **not** invalidate this unless embeddings change.

When all vector hits are below the floor, `similar_cases` is empty → `graph.py` `_after_retrieve` escalates without LLM classification (by design).

---

## 7. Proposed non-secret configuration template

Copy to repo root `.env` (fill secrets locally; never commit):

```dotenv
# --- Neo4j (local) ---
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<set-me>
NEO4J_DATABASE=neo4j
CHAT_DATABASE=neo4j
SHIPMENT_DATABASE=shipments

# --- LLM: Ollama Cloud via LiteLLM + OpenAI-compatible endpoint ---
# Model id must match https://ollama.com/api/tags (API name, not ":cloud" alias).
LLM_MODEL=openai/gemma4:31b
LLM_API_BASE=https://ollama.com/v1
LLM_API_KEY=<ollama-cloud-api-key>
# After B3 fallback (recommended): you may set only:
# OLLAMA_API_KEY=<ollama-cloud-api-key>

# --- Embeddings: local Ollama only (pull once: ollama pull bge-m3) ---
EMBEDDING_MODEL=ollama/bge-m3
EMBEDDING_API_BASE=http://127.0.0.1:11434
EMBEDDING_DIMENSIONS=1024
```

---

## 8. Files allowed to modify in later batches (B2–B4)

| Batch | Typical touch points |
| --- | --- |
| **B2** (smoke / gate) | No tracked product edits unless gate documents require; may add run evidence under `docs/agent-runs/` |
| **B3** (impl) | `chat/config.py`, `.env.example`, `README.md`, optional `docs/agent-runs/*` |
| **B4** (review / docs) | `docs/agent-runs/*`, README if not done in B3 |

**Forbidden without explicit scope expansion:** `chat/llm/pipeline/*.py` logic, frontend, `shipment_kg/`, committed `.env`, embedding backfill logic (unless retrieval calibration task is opened).

---

## 9. Risks, STOP conditions, acceptance criteria (B2–B4)

### Risks

| Risk | Mitigation |
| --- | --- |
| **No `OLLAMA_API_KEY` / `LLM_API_KEY` in environment** (true at B1 audit) | Operator creates key at ollama.com; B2 smoke must fail clearly if missing |
| **Wrong LiteLLM model prefix** | Run H1–H4 matrix in B2; record working string in gate doc |
| **JSON stages** (`extract`, `classify`, `recommend`, `review`) | `_llm.ask_json` already tolerates fences/preamble; cloud models may improve or change failure modes — re-run pipeline eval if available |
| **ReAct agent tool calling** (`agent.py`) | Pick a cloud model with **Tools** support (e.g. gemma4 on cloud listing); verify in B2 |
| **Streaming** (`streaming=True` in agent) | Confirm ChatLiteLLM + cloud endpoint stream; pipeline uses non-streaming |
| **Local Ollama for embeddings** | If Ollama not running on `:11434`, vector search degrades to graph-only (`retrieve.py` catches errors); precedent quality drops |
| **Usage / billing** | Cloud models consume credits; monitor via Ollama account |
| **Data leaves machine** | Cloud LLM prompts/responses processed by Ollama per [cloud.md](https://docs.ollama.com/cloud.md) data handling |

### STOP conditions

1. No valid API key after operator setup and B2 cannot authenticate to `https://ollama.com/v1`.
2. None of H1–H4 produce a successful `ChatLiteLLM.invoke` / `litellm.completion` from `chat/` venv.
3. Chosen model fails **tool-calling** ReAct loop for `mandates_vs_attendance` / `show_on_map`.
4. Requirement interpreted as “embeddings in cloud” without local Ollama — **out of scope** for current code (would need new embedding provider config).

### Acceptance criteria (suggested)

| Batch | Criteria |
| --- | --- |
| **B2** | Documented passing smoke: minimal chat completion via configured `ChatLiteLLM`; at least one pipeline `ask_json` call; optional single agent question with tool use |
| **B3** | `OLLAMA_API_KEY` fallback (if approved), `.env.example` reflects cloud LLM + local embeddings; no secrets in git |
| **B4** | Review confirms architecture split; gate lists verified `LLM_MODEL` string and model id from Ollama tags |

---

## 10. Dependency stack (read-only)

| Package | Role |
| --- | --- |
| `langchain-litellm` | `ChatLiteLLM` wrapper |
| `litellm` | Embeddings + underlying completion routing |
| `langgraph` | Agent + complaint pipeline graphs |

Lockfile: `chat/uv.lock` pins `litellm` 1.92.0, `langchain-litellm` 0.7.0 (Python ≥3.12).

---

## Repo alignment summary

| Goal | Status |
| --- | --- |
| LangGraph agents local | **Met** — `agent.py`, `pipeline/graph.py` |
| LLM via Ollama Cloud | **Config-ready** — needs env + B2 validation of LiteLLM model string |
| Neo4j local | **Met** — unchanged |
| bge-m3 local embeddings | **Met** — defaults in `config.py` / `.env.example` |
| No large local chat LLM | **Compatible** — cloud path avoids local chat pulls |

---

## Verdict

**SCOPE-READY** — Current code already routes LLM calls through `ChatLiteLLM` with `api_base` and `api_key`. Ollama Cloud’s documented `https://ollama.com/v1` + API key matches the pattern described in `config.py`. Remaining work is **environment setup**, **B2 empirical LiteLLM model string validation**, and **small config/docs hygiene** (`OLLAMA_API_KEY` fallback recommended).

**B1 blocker note:** `OLLAMA_API_KEY` was **not** present in the audited environment; implementation must obtain a key before cloud smoke tests.
