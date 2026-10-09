# Batch 2 Audit — `runtime-dependency-baseline`

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-10-07_agentx-local-baseline` |
| **Batch slug** | `runtime-dependency-baseline` |
| **Agent** | BATCH 2 AUDIT |
| **Repository** | `agentx-kg-hackathon` (local clone on Windows) |
| **Development branch** | `fhd` |
| **Verdict** | **SCOPE-READY** |

---

## Current truth (environment + repo)

Audit performed **read-only** (no `uv sync`, `npm install`/`npm ci`, or application edits). Batch 1 sync outcome assumed: local `fhd` at `origin/main` tip.

| Item | State |
| --- | --- |
| **Local HEAD** | `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` |
| **`origin/main`** | `2b9f7c8ebd25c22a2bbef7a5e8255dd9a3a913f2` (matches HEAD) |
| **Branch tracking** | `fhd` → `origin/fhd` (**ahead 8** — local has `main` commits not yet on `origin/fhd`; does not block dependency baseline) |
| **`frontend/node_modules/`** | Present on disk (likely from prior work; ignored by git) |
| **`chat/.venv/`** | Present on disk (likely from prior `uv sync`; ignored / local) |
| **Untracked run docs** | Batch 1 audit/impl/review/gate markdown under `docs/agent-runs/` (not product code) |

---

## Installed tooling (versions recorded, no secrets)

| Tool | Detected | Notes |
| --- | --- | --- |
| **git** | 2.50.1.windows.1 | OK |
| **node** | v22.18.0 | OK for Vite 8 / React 19 stack |
| **npm** | 11.6.3 | OK |
| **python** (default on PATH) | 3.10.11 | **Below** project minimum; do not rely on this interpreter |
| **py** launcher | 3.14.3 (default `*`), also **3.12**, 3.13, 3.10 registered | **3.12+ available** for `uv` |
| **uv** | 0.12.15 | OK; can provision/use CPython 3.12+ |
| **java** | 23.0.1 | Present; Neo4j server often bundles JRE — not required for Python driver-only dev |
| **ollama** | **Not on PATH** | Required for default embeddings (`ollama/bge-m3` per `.env.example`); **not** part of npm/uv lock install |
| **neo4j** CLI | **Not on PATH** | Neo4j Desktop / server not confirmed via CLI |
| **docker** | CLI 29.1.3 | **Daemon not running** (`dockerDesktopLinuxEngine` pipe missing) |

### Windows hardware summary (non-sensitive)

| Resource | Value |
| --- | --- |
| **Machine** | HP ENVY Laptop 16-h1xxx |
| **OS** | Windows 11 Home, build 26200, 64-bit |
| **CPU** | 13th Gen Intel Core i7-13700H, 14 cores / 20 logical processors |
| **RAM** | ~32 GiB (34,038,341,632 bytes reported) |
| **GPU (discrete)** | NVIDIA GeForce RTX 4060 Laptop GPU — **8188 MiB** VRAM (`nvidia-smi`); driver 592.82, CUDA 13.1 |
| **GPU (integrated)** | Intel Iris Xe Graphics |
| **System drive (C:)** | ~426 GiB free of ~952 GiB total |

---

## Project dependency manifests (read-only)

| File | Finding |
| --- | --- |
| **`chat/pyproject.toml`** | `requires-python = ">=3.12"` |
| **`chat/uv.lock`** | `requires-python = ">=3.12"`; Windows wheels present in lock (e.g. `win_amd64`) |
| **`frontend/package.json`** | Scripts: `dev`, `build`, `lint`, `test`, `preview` |
| **`frontend/package-lock.json`** | **Present** (`lockfileVersion: 3`) — **no** `pnpm-lock.yaml`, `yarn.lock`, or `bun.lockb` under `frontend/` |
| **`.env.example`** | Neo4j bolt URI, LLM via LiteLLM, embeddings default to Ollama `bge-m3` at `localhost:11434` |
| **`serve.sh`** | Bash-only: `npm install` + `npm run build` in `frontend/`, then `uv run --project chat uvicorn --app-dir backend main:app` on `127.0.0.1:8000` |
| **`README.md`** | Documents Neo4j, LiteLLM LLM, Ollama embeddings, `uv` for Python, external `json/` geography clone for KG generation |

### Python version compliance

| Check | Result |
| --- | --- |
| **Minimum required** | Python **≥ 3.12** |
| **Default `python` command** | **FAIL** (3.10.11) |
| **Suitable interpreters on machine** | **PASS** — Python **3.12.3** and **3.14.3** registered with `py`; `uv python list` sees 3.12 and 3.14 |
| **Impl expectation** | `uv sync` in `chat/` should create/use `.venv` with ≥3.12 without requiring `python` on PATH to be 3.12 |

---

## Windows / script assumptions

| Script / doc | Issue | Mitigation for impl |
| --- | --- | --- |
| **`serve.sh`** | `#!/usr/bin/env bash`, `set -euo pipefail`, `$(dirname "$0")` | On Windows: Git Bash, WSL, or **manual equivalent** in PowerShell (`cd frontend; npm …; cd ..; uv run --project chat uvicorn …`) |
| **`serve.sh` frontend step** | Uses **`npm install`**, not `npm ci` | Lockfile policy below recommends **`npm ci`** when refreshing deps; align run docs with team policy |
| **`frontend/README.md`** | References `./serve.sh` and legacy project name in comment | Same Bash requirement |
| **No PowerShell serve script** | None in repo root | Impl does not need to add one in this batch unless scoped later |

---

## Expected operations for Implementation agent

**Goal:** Establish reproducible local dependency trees for Python (`chat/`) and Node (`frontend/`) per lockfiles, without starting long-running services or mutating `.env`.

### Python (from repo root or `chat/`)

```powershell
cd chat
uv sync
```

Optional verification (read-only-ish):

```powershell
uv run python --version
```

Expect **Python 3.12+**.

### Frontend (lockfile policy)

Because **`frontend/package-lock.json` is committed**:

```powershell
cd frontend
npm ci
```

Use **`npm install`** only if intentionally updating the lockfile (out of scope for baseline unless explicitly authorized).

### Not in Batch 2 impl scope (document only)

- `npm run build` / `npm run test` / `npm run lint` (Review/Gate or later batch unless impl batch explicitly includes verify)
- `./serve.sh` end-to-end (Bash + build + serve)
- `ollama pull bge-m3`, Neo4j start, LLM API keys, `.env` creation
- `docker` pulls (daemon currently stopped)

---

## npm scripts inventory (`frontend/package.json`)

| Script | Command | Purpose |
| --- | --- | --- |
| **dev** | `vite` | Vite dev server (README notes production build is primary for NVL) |
| **build** | `tsc -b && vite build` | Typecheck + production bundle → `frontend/dist/` |
| **lint** | `oxlint` | Lint |
| **test** | `vitest run` | Unit/component tests |
| **preview** | `vite preview` | Preview production build |

*Not executed during this audit.*

---

## Exact scope (what Implementation may do)

| In scope | Out of scope |
| --- | --- |
| `cd chat && uv sync` (may download wheels, create/update `chat/.venv`) | Editing `chat/pyproject.toml`, `chat/uv.lock`, `frontend/package.json`, or `frontend/package-lock.json` |
| `cd frontend && npm ci` (or `npm install` only if policy exception documented) | `npm run build`, `test`, `lint` unless a later gate requires |
| Read-only checks: `uv run python --version`, `npm ls` (depth 0) | Committing, pushing, git branch operations |
| Writing Batch 2 impl/review/gate run docs if tasked | Modifying `.env` or copying secrets into tracked files |
| | Installing **Ollama**, **Neo4j**, or starting **Docker** unless explicitly scoped |
| | Running `serve.sh` or binding port 8000 for soak tests |

---

## Allowed / forbidden files

| Allowed to create/modify (local only) | Forbidden |
| --- | --- |
| `chat/.venv/**` (uv-managed) | Tracked product source: `backend/**`, `chat/**` (except local venv), `frontend/src/**`, etc. |
| `frontend/node_modules/**` | Lockfiles and manifests unless a dedicated “lockfile update” batch |
| Run documentation under `docs/agent-runs/` when assigned | `.env` contents in commits; evidence trees with vendored deps |
| | Deleting user `.env` |

Audit agent created **only** this markdown file.

---

## Commands Implementation may run

| Command | Purpose |
| --- | --- |
| `uv sync` (in `chat/`) | Install Python deps from `uv.lock` |
| `uv run python --version` | Confirm interpreter ≥3.12 |
| `npm ci` (in `frontend/`) | Install Node deps from `package-lock.json` |
| `npm ls --depth=0` | Sanity check top-level packages (optional) |
| `git status` | Confirm no accidental tracked edits |

---

## Risks and STOP conditions

| Risk | Mitigation / STOP |
| --- | --- |
| **`uv sync` fails** (network, disk, Python resolution) | **STOP** — capture log; fix Python 3.12+ availability (`uv python install 3.12`) before retry |
| **`npm ci` fails** (lock out of sync with `package.json`) | **STOP** — do not hand-edit lock; escalate lockfile repair batch |
| **Default `python` is 3.10** | Use **`uv`** only; **STOP** if impl scripts call bare `python` expecting 3.12 |
| **Disk space** | ~426 GiB free — sufficient for typical `node_modules` + venv; **STOP** if install errors on ENOSPC |
| **Chocolatey `python3.13` shim broken** | `uv` warned on inspect; prefer explicit 3.12/3.14 via `uv` — non-blocking if `uv sync` succeeds |
| **Ollama / Neo4j / LLM absent** | **Does not STOP** dependency baseline; **STOP** for “full app running” gate later |
| **Docker daemon stopped** | **Does not STOP** this batch unless impl tries containerized Neo4j |
| **Accidental lockfile or source edits** | **STOP** Review/Gate; revert tracked changes |
| **Bash-only `serve.sh` on PowerShell-only session** | **Does not STOP** `uv sync` / `npm ci`; blocks one-command serve without Bash |

---

## Acceptance criteria

### Implementation

- [ ] `cd chat && uv sync` exits 0; `uv run python --version` reports **≥ 3.12**.
- [ ] `cd frontend && npm ci` exits 0; `package-lock.json` unchanged in `git diff`.
- [ ] `git status` shows **no** staged/unstaged changes to tracked product files (local `node_modules`/`.venv` ignored).

### Review

- [ ] Confirms only dependency directories and authorized run docs touched.
- [ ] Confirms lockfiles not modified.
- [ ] Records any `uv`/`npm` warnings for Gate.

### Gate

- [ ] **PASS** if Implementation + Review criteria met.
- [ ] **FAIL/STOP** if lockfiles or application source changed, or either install command failed.

---

## Version gaps and runtime dependencies (for parent agent)

| Gap | Blocks dependency baseline? | Blocks full local run? |
| --- | --- | --- |
| Default `python` 3.10 vs requires ≥3.12 | No (use `uv`) | Yes if tools ignore `uv` |
| **Ollama** not installed | No | Yes for default embeddings / vector backfill |
| **Neo4j** not detected on PATH | No | Yes for API/graph features |
| **LLM** keys / `.env` | No | Yes for agent answers |
| **Docker** daemon stopped | No | Only if Neo4j via Docker |
| **`serve.sh`** Bash-only | No | Yes on bare PowerShell |

**Recommended npm install strategy:** **`npm ci`** in `frontend/` (committed `package-lock.json`, no alternate lockfiles).

---

## Audit conclusion

**SCOPE-READY** for `runtime-dependency-baseline`: `git`/`node`/`npm`/`uv` are present, Python **3.12+** is available to `uv`, and the repo declares lockfiles for both stacks. External services (Neo4j, Ollama, LLM) remain outside this batch but must be tracked for later run gates.
