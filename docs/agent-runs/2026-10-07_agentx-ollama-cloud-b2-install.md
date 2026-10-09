# Batch 2 Install + Verify — Ollama Cloud LLM + local embeddings

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-ollama-cloud` |
| **Batch** | B2 — INSTALL + VERIFY |
| **Repository** | `C:\Projects\demo` |
| **Branch** | `fhd` @ `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` (unchanged) |
| **Agent** | OLLAMA CLOUD BATCH 2 |
| **Verdict** | **PARTIAL** — local Ollama + `bge-m3` OK; **cloud auth BLOCKED** (no API key) |

---

## Skipped steps (prior run docs)

| Step | Reason |
| --- | --- |
| `git fetch` / ff-only merge | **SUCCESS** in `2026-10-07_agentx-local-baseline-b1-impl.md` |
| `uv sync` / `npm ci` | Out of B2 scope; venv used successfully for embedding smoke |

---

## 1. Ollama (local daemon)

| Check | Result |
| --- | --- |
| `Get-Command ollama` (PATH) | **Not found** at session start; binary at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` |
| Install attempt | `winget install Ollama.Ollama` — **exit 1** (another installer already running); existing **0.40.0** binary present |
| `ollama --version` | **0.40.0** (client; server matched after setup completed) |
| `http://127.0.0.1:11434` | **HTTP 200** |
| `ollama list` | **`bge-m3:latest`** (~1.2 GB) |
| Large local **chat** pulls | **None** (no `qwen3`, no cloud chat weights pulled locally) |

**Note:** After a stuck `OllamaSetup` process exited, `ollama list` succeeded. Operators may need a **new shell** or PATH refresh for `Get-Command ollama` if the installer updated user PATH.

---

## 2. Embeddings — `bge-m3`

| Check | Result |
| --- | --- |
| `ollama pull bge-m3` | **SUCCESS** (first pull on this machine) |
| LiteLLM embedding smoke | `uv run python` with `model=ollama/bge-m3`, `api_base=http://127.0.0.1:11434` → **`dims 1024`** |

---

## 3. Secrets / `.gitignore`

| Check | Result |
| --- | --- |
| `.env` in root `.gitignore` | **Yes** (line 21) |
| `OLLAMA_API_KEY` in process env | **Absent** (non-empty: no) |
| `.env` keys (non-empty, values **not** read) | `LLM_API_KEY` → **empty**; `OLLAMA_API_KEY` → **not set / empty**; `OPENAI_API_KEY` → **empty** |
| `LLM_API_KEY=` line present in `.env` | **Yes** (placeholder only) |

**STOP (per run plan):** Cloud direct API and LiteLLM hypothesis tests **not executed** — no valid Bearer token available without operator action.

**Operator action:** Add Ollama cloud API key to repo root `.env` as either `LLM_API_KEY=...` or `OLLAMA_API_KEY=...` (both are wired in `chat/config.py` via fallback chain). Create key at [ollama.com](https://ollama.com) per [cloud docs](https://docs.ollama.com/cloud.md).

---

## 4. Cloud API (direct OpenAI-compatible)

| Test | Result |
| --- | --- |
| `POST https://ollama.com/v1/chat/completions` | **Skipped** — `AGENTX_OLLAMA_OK=0` (`reason=no_key`) |
| JSON / Arabic smoke | **Skipped** (depends on auth) |

Official reference (for B3 re-run): `base_url=https://ollama.com/v1`, model id **`gemma4:31b`** (API name, not `:cloud` alias), `Authorization: Bearer <OLLAMA_API_KEY>`.

---

## 5. LiteLLM hypotheses (H1–H4)

| # | Config | Result |
| --- | --- | --- |
| H1 | `openai/gemma4:31b` + `https://ollama.com/v1` | **Not tested** (no key) |
| H2 | `gemma4:31b` + same base | **Not tested** |
| H3 | `ollama/gemma4:31b` | **Not tested** (deferred; audit says try only if H1/H2 fail) |
| H4 | `openai/nemotron-3-nano:4b` etc. | **Not tested** |

**Working `LLM_MODEL` string:** **Unverified** — `.env` already has `LLM_MODEL=openai/gemma4:31b` and `LLM_API_BASE=https://ollama.com/v1` (audit template; empirically unconfirmed this batch).

---

## 6. `config.py` — `OLLAMA_API_KEY` fallback

| Item | Result |
| --- | --- |
| Change required | **No** — `LLM_API_KEY` already resolves `LLM_API_KEY` → `OPENAI_API_KEY` → `OLLAMA_API_KEY` |

---

## 7. `.env` merge (non-secret LLM + embedding vars)

| Variable | On-disk value (non-secret) | B2 action |
| --- | --- | --- |
| `LLM_MODEL` | `openai/gemma4:31b` | **Unchanged** (already set) |
| `LLM_API_BASE` | `https://ollama.com/v1` | **Unchanged** |
| `EMBEDDING_MODEL` | `ollama/bge-m3` | **Unchanged** |
| `EMBEDDING_API_BASE` | `http://127.0.0.1:11434` | **Unchanged** |
| `EMBEDDING_DIMENSIONS` | `1024` | **Unchanged** |
| Neo4j / CSV / shipment vars | Present | **Not modified** |

No wipe of Neo4j or other secrets; API key placeholders left for operator.

---

## B3 integration gate

| Area | Can proceed? |
| --- | --- |
| Local embeddings / vector path (`bge-m3` on `:11434`) | **Yes** |
| Cloud LLM via `ChatLiteLLM` | **No** until API key populated and B2/B3 smoke re-run (`AGENTX_OLLAMA_OK`, LiteLLM H1 matrix, optional JSON/Arabic) |
| Docs / `.env.example` hygiene | **Yes** (no key required for template edits) |

---

## Commands reference (no secrets)

```powershell
# Local Ollama (if not on PATH)
$ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
& $ollama --version
& $ollama list
Invoke-WebRequest http://127.0.0.1:11434 -UseBasicParsing

# Embedding dims (from chat/)
cd C:\Projects\demo\chat
uv run python -c "import litellm; r=litellm.embedding(model='ollama/bge-m3', api_base='http://127.0.0.1:11434', input=['hello']); print(len(r.data[0]['embedding']))"

# After key added — re-run cloud smoke (parent/coordinator script or B3 gate)
```

---

## Return summary (parent agent)

| Item | Status |
| --- | --- |
| **Install status** | Ollama **0.40.0** installed/running; `bge-m3` pulled; `:11434` OK |
| **Cloud auth** | **BLOCKED** — no non-empty `LLM_API_KEY` / `OLLAMA_API_KEY` |
| **Working `LLM_MODEL`** | **Unverified** (intended: `openai/gemma4:31b`) |
| **bge-m3** | **OK** — 1024-dim embedding smoke passed |
| **B3 proceed** | **Partial** — embeddings yes; cloud LLM after operator key + smoke |
