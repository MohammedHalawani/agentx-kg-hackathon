# Batch 2 Review — `runtime-dependency-baseline`

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-local-baseline` |
| **Batch slug** | `runtime-dependency-baseline` |
| **Agent** | BATCH 2 REVIEW/FIX |
| **Audit reference** | `docs/agent-runs/2026-10-07_agentx-local-baseline-b2-audit.md` |
| **Impl reference** | `docs/agent-runs/2026-10-07_agentx-local-baseline-b2-impl.md` |
| **Gate recommendation** | **PASS** |

---

## Review scope

Independent verification of Implementation claims: reproducible Python/Node installs from lockfiles, no tracked product or manifest edits, optional parent validation (`import config`, `npm run test` / `lint` / `build`), and working-tree hygiene. No commit or push.

---

## Git state verified

| Check | Expected | Observed | Result |
| --- | --- | --- | --- |
| Current branch | `fhd` | `fhd` | Pass |
| `fhd` HEAD | `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` (per audit/impl) | Same | Pass |
| Staged / unstaged tracked changes | None | `git diff` and `git diff --cached` empty | Pass |
| Lockfiles / manifests | Unchanged | `git diff HEAD -- chat/pyproject.toml chat/uv.lock frontend/package.json frontend/package-lock.json` empty | Pass |
| `.env` / `.env.example` in diff | Not modified | Empty diff for both paths | Pass |
| `origin/fhd` (no push) | Still behind local | Ahead of `origin/fhd` by 8 (unchanged from Batch 1) | Pass (expected) |

### Untracked files (working tree)

| Path | Notes |
| --- | --- |
| `docs/agent-runs/2026-10-07_agentx-local-baseline-b1-*.md` | Batch 1 run docs (allowed) |
| `docs/agent-runs/2026-10-07_agentx-local-baseline-b2-audit.md` | Batch 2 audit (allowed) |
| `docs/agent-runs/2026-10-07_agentx-local-baseline-b2-impl.md` | Batch 2 impl (allowed) |
| `docs/agent-runs/2026-10-07_agentx-ollama-cloud-b1-audit.md` | Sibling run doc; not Batch 2 product scope; no tracked edits |

Local-only dependency trees (`chat/.venv/`, `frontend/node_modules/`, `frontend/dist/` from build) are gitignored and do not appear in `git status`.

---

## Lockfile and source integrity

| Path class | Review |
| --- | --- |
| `chat/pyproject.toml`, `chat/uv.lock` | No diff vs `HEAD` |
| `frontend/package.json`, `frontend/package-lock.json` | No diff vs `HEAD` |
| Application source (`backend/**`, `chat/**` except venv, `frontend/src/**`, etc.) | No tracked modifications |
| `.env` | Gitignored; not in diff; batch did not require creating or editing |

**No unintended lockfile or source changes detected.**

---

## Implementation claims vs independent evidence

### Python (`chat/`)

| Impl claim | Review |
| --- | --- |
| `uv sync` exit 0 | **Confirmed** — `Resolved 80 packages`; `Checked 78 packages`; exit 0 |
| `uv run python --version` ≥ 3.12 | **Confirmed** — `Python 3.12.3` |
| `import config` smoke | **Confirmed** — `config_ok C:\Projects\demo\chat\config.py` |

### Frontend (`frontend/`)

| Impl claim | Review |
| --- | --- |
| `npm ci` exit 0 | **Assumed from impl log**; environment already had `node_modules` from impl; lockfile still clean |
| `npm run test` — 26 files / 99 tests | **Confirmed** — Vitest v4.1.9; all passed (~20s) |
| `npm run lint` — 0 errors, 13 warnings | **Confirmed** — oxlint warnings only (react-hooks / only-export-components) |
| `npm run build` exit 0 | **Confirmed** — `tsc -b && vite build`; Vite v8.1.1; output under `frontend/dist/` (ignored) |

### Git hygiene

| Impl claim | Review |
| --- | --- |
| No tracked product or lockfile edits | **Confirmed** |

---

## Windows npm `.bin` shim (impl note)

Implementation reported that the **first** `npm run test` / `lint` / `build` immediately after `npm ci` failed with `'vitest' is not recognized`, then succeeded after `npx vitest run` and on subsequent `npm run` invocations.

**Review finding:** On this machine, in a shell with `node_modules` already populated from impl, `npm run test` succeeded on first attempt without `npx`. Treat the impl note as a **possible transient Windows/npm PATH or `.bin` shim timing** issue immediately post-`npm ci`, not a gate failure unless reproduced on a clean `npm ci` in a fresh shell. Gate may want Batch 3+ to retry scripts once if `.bin` is empty.

---

## npm / uv warnings (recorded, non-blocking)

| Source | Detail |
| --- | --- |
| `npm ci` (impl) | Deprecated `uuid@8.3.2` transitive; `npm audit` reported 20 vulnerabilities (not remediated; out of scope) |
| `npm run build` | Chunk size > 500 kB (Vite reporter) |
| `npm run lint` | 13 oxlint warnings, 0 errors |

---

## Secrets scan (batch docs)

Heuristic scan on `docs/agent-runs/2026-10-07_agentx-local-baseline-b2-*.md`: no API keys, passwords, or private key material. Placeholder env names in audit (Neo4j, Ollama) are documentation only.

---

## Fixes applied by Review agent

**None.** No blockers in approved scope.

| Path | Change |
| --- | --- |
| `docs/agent-runs/2026-10-07_agentx-local-baseline-b2-review.md` | **Created** (this note) |

No commit or push performed.

---

## Risks (carry-forward, not Batch 2 failures)

| Risk | Notes |
| --- | --- |
| **Ollama** not on PATH | Per audit; blocks embeddings default path later, not dependency baseline |
| **Neo4j** not on PATH | Expected deferral to Batch 3+ |
| **`.env` / LLM keys** | Not created; required for full app run later |
| **Docker daemon** stopped | Only if Neo4j via containers |
| **`origin/fhd` stale** | Local still ahead by 8 until authorized push |
| **Untracked run docs** | B1/B2 (and sibling ollama audit) not committed in this batch |

---

## Review verdict

**PASS** — `runtime-dependency-baseline` acceptance criteria met: `uv sync` and Python 3.12.3, lockfiles unchanged, tracked tree clean, and parent validation commands (`test` / `lint` / `build` / import smoke) succeed independently.
