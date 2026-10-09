# Ollama Cloud ↔ B3 integration — `gpt-oss` verified

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-ollama-cloud` + `2026-10-07_agentx-local-baseline` |
| **Date** | 2026-10-07 |
| **Repository** | `C:\Projects\demo` |
| **Branch** | `fhd` @ `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` |

**No secrets in this file.**

---

## Verified routing

| Setting | Value |
| --- | --- |
| `LLM_API_BASE` | `https://ollama.com/v1` |
| `LLM_MODEL` (repo root `.env`, updated) | `openai/gpt-oss:20b` |
| API chat name (direct HTTP) | `gpt-oss:20b` / `gpt-oss:120b` |
| Auth | Bearer via `config.LLM_API_KEY` (effective length **57** at probe; sourced from `OLLAMA_API_KEY` fallback) |
| Device / public key | **Not used** |
| Local `gpt-oss` pull | **Not performed** |
| Embeddings | Unchanged — `ollama/bge-m3` @ `http://127.0.0.1:11434`, **1024** dims |

---

## Model comparison (smoke, not benchmark)

Evidence: `docs/agent-runs/_agentx_gpt_oss_eval_results.json`

| Test | `openai/gpt-oss:20b` | `openai/gpt-oss:120b` |
| --- | --- | --- |
| Direct plain (`AGENTX_OLLAMA_OK`) | **PASS** ~1.2s | **PASS** ~0.8s |
| Direct JSON-only | **PASS** ~1.3s | **PASS** ~1.1s |
| Arabic logistics summary | **PASS** (Arabic in response) ~2.7s | **PASS** ~1.0s |
| `ChatLiteLLM` | **PASS** ~2.4s | **PASS** ~0.7s |
| `ask_json()` | **PASS** ~2.0s | **PASS** ~0.8s |
| `extract_entities()` | **PASS** ~4.7s | **PASS** ~1.8s |

**Winner for default dev:** **`openai/gpt-oss:20b`** — both models passed all six tests; 20b is the agreed primary candidate unless product policy prefers 120b for quality (120b was faster on this short smoke only).

---

## Code adjustments (uncommitted)

| File | Change | Rationale |
| --- | --- | --- |
| `chat/config.py` | `LLM_API_KEY` ← `OLLAMA_API_KEY` fallback | Cloud key in `.env` resolves without duplicating into `LLM_API_KEY` |
| `chat/llm/pipeline/_llm.py` | `message_text()` for block-list `content` | Ollama Cloud `gpt-oss` returns `[{type: thinking}, {type: text}]`; `ask_json()` / pipeline need text extraction |

---

## Downstream smoke

| Step | Result |
| --- | --- |
| `eval_pipeline.py --hard -n 3` | **Completed** — 2/3 category, 2/3 plausible action (smoke only) |
| Shipment graph + vector index | Loaded on DB **`shipments`**; index **`failurereason_case_summary`** **ONLINE** |

---

## Operator `.env` notes (non-secret)

| Variable | Action this run |
| --- | --- |
| `LLM_MODEL` | Set to `openai/gpt-oss:20b` (removed `openai/gemma4:31b` placeholder) |
| `SHIPMENT_DATABASE` | Corrected from `neo4j` → **`shipments`** so pipeline/API align with loaded graph |

No commit or push.
