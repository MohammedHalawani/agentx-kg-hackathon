# Batch 1 Implementation — Ollama Cloud LLM + local embeddings

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-ollama-cloud` |
| **Batch** | B1 — IMPLEMENTATION (coordinator) |
| **Audit reference** | `docs/agent-runs/2026-10-07_agentx-ollama-cloud-b1-audit.md` |
| **Verdict** | **PARTIAL** — local stack ready; cloud LLM tests blocked on API key |

---

## Secret handling

| Check | Result |
| --- | --- |
| `$env:OLLAMA_API_KEY` | **Absent** (length 0) |
| `OLLAMA_API_KEY` in repo root `.env` | **Not set** |
| `LLM_API_KEY` in `.env` | Present key line, **empty value** (length 0) |
| `.env` in `.gitignore` | **Yes** |

**STOP (per run policy):** Cloud API smoke tests (`AGENTX_OLLAMA_OK`, JSON, Arabic), LiteLLM chat completion, and `ask_json()` via pipeline code were **not executed** — operator must add `OLLAMA_API_KEY=` to repo root `.env` manually (from [Ollama Cloud](https://docs.ollama.com/cloud)); do not paste the key in chat.

After the key is set, `chat/config.py` maps `OLLAMA_API_KEY` → `LLM_API_KEY` so a duplicate `LLM_API_KEY` is optional.

---

## Ollama install (local embeddings only)

| Step | Result |
| --- | --- |
| Official Windows installer | `irm https://ollama.com/install.ps1 \| iex` — **success** |
| Version | **0.40.0** |
| Local API | `http://127.0.0.1:11434` — **HTTP 200** on `/api/tags` |
| Large chat model pulls | **None** (no `qwen3:8b` / `14b` or other chat LLM pulls) |
| `ollama pull bge-m3` | **Success** — only local model on disk |

---

## Embedding validation (local)

| Test | Result |
| --- | --- |
| Ollama `/api/embed` with `bge-m3` | **dims = 1024** |
| `retrieve.py` threshold | **Not modified** |

---

## Cloud + LiteLLM configuration (prepared, not live-tested)

Per [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) and audit hypothesis **H1**:

| Variable | Value written to `.env` (non-secret) |
| --- | --- |
| `LLM_MODEL` | `openai/gemma4:31b` |
| `LLM_API_BASE` | `https://ollama.com/v1` |
| `EMBEDDING_MODEL` | `ollama/bge-m3` (unchanged) |
| `EMBEDDING_API_BASE` | `http://127.0.0.1:11434` |
| `EMBEDDING_DIMENSIONS` | `1024` |

**Code change:** `chat/config.py` — `LLM_API_KEY` fallback chain includes `OLLAMA_API_KEY`.

**LiteLLM prefix (intended, pending key):** `openai/<cloud-model-id>` with `api_base=https://ollama.com/v1` (not `ollama/` for direct cloud).

---

## Tests deferred until `OLLAMA_API_KEY` is set

- [ ] Raw `POST https://ollama.com/v1/chat/completions` — prompt `AGENTX_OLLAMA_OK`
- [ ] JSON + Arabic completion via same endpoint
- [ ] `ChatLiteLLM` / LiteLLM path with project env
- [ ] `ask_json()` from `chat/llm/pipeline/_llm.py`

---

## Files touched by this batch

| Path | Change |
| --- | --- |
| `chat/config.py` | `OLLAMA_API_KEY` → `LLM_API_KEY` fallback |
| `.env` (gitignored) | Cloud LLM base URL + model; embedding locals; BOM stripped for `load_dotenv` |
| `docs/agent-runs/2026-10-07_agentx-ollama-cloud-b1-impl.md` | This note |

No commit or push.
