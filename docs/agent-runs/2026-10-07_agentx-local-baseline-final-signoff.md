# Final sign-off — `2026-10-07_agentx-local-baseline`

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-local-baseline` |
| **Repository** | `C:\Projects\demo` |
| **Branch** | `fhd` @ `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` |
| **Date** | 2026-10-07 (UTC+3) |
| **Overall** | **CONDITIONAL VERIFIED** — shipment baseline + app smoke **PASS**; Explore **Graph** lens on governance DB is empty (expected until governance graph is loaded) |

**No secrets in this document.**

---

## 29-item closure checklist

| # | Item | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Re-probe: `config.LLM_API_KEY` effective length > 0 | **PASS** | Length **57** via `uv run python -c "import config; …"` from `chat/` |
| 2 | Re-probe: TCP `127.0.0.1:7687` | **PASS** | `TcpTestSucceeded: True` |
| 3 | Re-probe: Neo4j auth (driver connect) | **PASS** | `get_driver()` + `SHOW DATABASES` |
| 4 | Re-probe: database **`shipments`** ONLINE | **PASS** | `neo4j`, `shipments`, `system` all **online** |
| 5 | B1 repo integrity (`fhd` @ `origin/main`) | **PASS** (prior gate) | `b1-gate.md` |
| 6 | B2 runtime deps (`uv` / `npm` test/lint/build) | **PASS** (prior gate) | `b2-gate.md` |
| 7 | Local Ollama `:11434` + `bge-m3` | **PASS** | HTTP **200** on `/api/tags`; embed backfill used local model |
| 8 | Ollama Cloud direct API `gpt-oss:20b` | **PASS** | `_agentx_gpt_oss_eval_results.json` test t1 |
| 9 | Ollama Cloud JSON-only `gpt-oss:20b` | **PASS** | t2 |
| 10 | Ollama Cloud Arabic handling `gpt-oss:20b` | **PASS** | t3 |
| 11 | LiteLLM / `ChatLiteLLM` `openai/gpt-oss:20b` | **PASS** | t4 |
| 12 | `ask_json()` with cloud model | **PASS** | t5 (after `message_text()` fix) |
| 13 | `extract_entities()` smoke | **PASS** | t6 |
| 14 | Compare `gpt-oss:120b` (same six tests) | **PASS** | All six in results JSON |
| 15 | Default `LLM_MODEL` set to verified winner | **PASS** | `.env` → `openai/gpt-oss:20b` (non-secret) |
| 16 | Neo4j edition + version census | **PASS** | **Enterprise** `2026.09.0` (`dbms.components()`) |
| 17 | Cypher 25 compatibility | **PASS** | `CYPHER 25 RETURN 1` on `shipments` |
| 18 | Vector index API compatibility | **PASS** | `failurereason_case_summary` **VECTOR** **ONLINE** post-embed |
| 19 | Pre-load census: empty disposable `shipments` | **PASS** | **0** nodes; no foreign labels |
| 20 | `load_shipment_graph.py` dry-run | **PASS** | **7848** statements; Arabic sample OK |
| 21 | `load_shipment_graph.py --yes` | **PASS** | Wipe + import complete (~2.5 min) |
| 22 | Seed split `reset_shipment_graph.py` | **PASS** | **165** resolved / **75** open |
| 23 | Node labels (Shipment…Outcome) | **PASS** | Shipment 300, Order 300, Customer 300, Address 355, Courier 25, Policy 3, Event 1780, FailureReason 240, Resolution 165, Outcome 165 |
| 24 | Relationship types | **PASS** | HAS_EVENT, DELIVERED_TO, LIVES_AT, HAS_SHIPMENT, PLACED_BY, ASSIGNED_TO, GOVERNED_BY, CAUSED_BY, RESOLVES_WITH, HAD_OUTCOME |
| 25 | Arabic UTF-8 in graph | **PASS** | Courier names e.g. سعود العتيبي; Resolution action not all `?` |
| 26 | `embed_backfill_shipments.py` dry-run → real | **PASS** | **165** embedded; **1024** dims; index ensured |
| 27 | `eval_pipeline.py --hard -n 3` | **PASS** (smoke) | 67% category, 67% plausible action — not a benchmark |
| 28 | FastAPI Windows-native `:8000` | **PASS** | `GET /` `/meta` `/samples` `/cases` `/graph` `/schema` → **200** |
| 29 | Browser smoke (Intake, Decisions, Explore, cases, AR UI) | **PASS** | `cursor-ide-browser` @ `http://127.0.0.1:8000` — 75 open cases listed; case SHP-0072 opened; pipeline started |

---

## Conditions / caveats

| Topic | Detail |
| --- | --- |
| **Explore Graph lens** | `GET /graph` uses **`NEO4J_DATABASE`** (governance), which has **0** nodes — response is empty graph JSON (**200**). Shipment data lives in **`shipments`**; Explore graph is not shipment-scoped. |
| **`.env` correction** | `SHIPMENT_DATABASE` was **`neo4j`** at probe; updated to **`shipments`** for this run (matches `.env.example`). |
| **Uncommitted code** | `chat/config.py` (`OLLAMA_API_KEY` fallback), `chat/llm/pipeline/_llm.py` (`message_text`) — required for cloud `gpt-oss`. |
| **Optional mutating complaint** | **Skipped** — one case pipeline triggered during browser smoke only. |
| **Git** | No commit / push per run policy. |

---

## Artifacts updated this checkpoint

| Path | Role |
| --- | --- |
| `docs/agent-runs/2026-10-07_agentx-local-baseline-b3-impl.md` | Status → **COMPLETE** |
| `docs/agent-runs/2026-10-07_agentx-local-baseline-resume-checklist.md` | Live probes refreshed |
| `docs/agent-runs/2026-10-07_agentx-ollama-cloud-model-eval.md` | Results filled |
| `docs/agent-runs/2026-10-07_agentx-ollama-cloud-b3-integration.md` | **New** |
| `docs/agent-runs/_agentx_gpt_oss_eval_results.json` | Raw latency JSON (no secrets) |

---

## Server still running

Uvicorn was left on **`http://127.0.0.1:8000`** for operator soak (PID from gate session). Stop manually when done.
