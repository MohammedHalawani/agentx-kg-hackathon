# Model evaluation — Ollama Cloud `gpt-oss`

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-ollama-cloud` |
| **Repository** | `C:\Projects\demo` |
| **Branch** | `fhd` |
| **Date** | 2026-10-07 |
| **Scope** | Compare **gpt-oss:20b** (primary) vs **gpt-oss:120b** on Ollama Cloud |
| **Verdict** | **COMPLETE** — both models pass smoke matrix; default **`openai/gpt-oss:20b`** |

**No secrets in this document.**

---

## API key probe (length only)

| Source | Non-empty? |
| --- | --- |
| `OLLAMA_API_KEY` (repo root `.env` + process) | **Yes** (feeds fallback) |
| `chat/config.py` → effective `LLM_API_KEY` | **Yes** (length **57** at probe) |

---

## Model IDs

| Priority | API model id | LiteLLM `LLM_MODEL` |
| --- | --- | --- |
| **1 (default)** | `gpt-oss:20b` | `openai/gpt-oss:20b` |
| **2 (compare)** | `gpt-oss:120b` | `openai/gpt-oss:120b` |

Embeddings unchanged: local `ollama/bge-m3` — **no** local `gpt-oss` pull.

---

## Per-model results

Raw timings: `docs/agent-runs/_agentx_gpt_oss_eval_results.json`

### gpt-oss:20b

| Test | Result |
| --- | --- |
| 1 Direct plain | **PASS** (~1.2s) |
| 2 JSON-only | **PASS** (~1.3s) |
| 3 Arabic | **PASS** (~2.7s) |
| 4 LiteLLM | **PASS** (~2.4s) |
| 5 `ask_json()` | **PASS** (~2.0s) |
| 6 `extract_entities()` | **PASS** (~4.7s) |

### gpt-oss:120b

| Test | Result |
| --- | --- |
| 1–6 | **PASS** (all faster on this short smoke; not used as default per baseline rule) |

---

## Integration note

Ollama Cloud returns `content` as a **list of blocks** (`thinking` + `text`). `chat/llm/pipeline/_llm.py` gained `message_text()` so `ask_json()` and stages parse final text. See `2026-10-07_agentx-ollama-cloud-b3-integration.md`.

---

## Recommendation

| Item | Value |
| --- | --- |
| **`LLM_MODEL` in `.env`** | `openai/gpt-oss:20b` |
| **`LLM_API_BASE`** | `https://ollama.com/v1` |

Pipeline smoke: `eval_pipeline.py --hard -n 3` exit **0** with this model.

No commit or push.
