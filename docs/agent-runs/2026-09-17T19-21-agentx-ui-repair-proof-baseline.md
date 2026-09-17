# Baseline — AgentX UI Repair Batch 1 Audit

| Field | Value |
| --- | --- |
| **RUN_ID** | `2026-09-17T19-21-agentx-ui-repair-proof` |
| **Batch slug** | `theme-cascade-hover-repair` |
| **Agent** | AGENT A (AUDIT) |
| **Timestamp (local)** | 2026-09-17T19:21 (UTC+3) |

## Repository layout

| Constant | Path |
| --- | --- |
| **PROJECT_ROOT** | `C:\Projects\demo` |
| **FRONTEND_ROOT** | `C:\Projects\demo\frontend` |
| **Backend (read-only reference)** | `C:\Projects\demo\backend` |
| **Serve entrypoint** | `C:\Projects\demo\serve.sh` |

## Git baseline

| Field | Value |
| --- | --- |
| **BRANCH** | `fhd` |
| **BASE_HEAD** | `a9b39a098dea08a3b2aeb40f1216ebc3e3a1a169` |

### BASE_WORKTREE (at audit start)

**Modified (tracked):** 24 files under `frontend/` including `index.css`, `App.tsx`, `main.tsx`, all three shell views (`IntakeView`, `DecisionsView`, `ExploreView`), graph artifacts, layout/chat components, `vite.config.ts`, `tsconfig*`, `index.html`, `package.json`, `package-lock.json`.

**Untracked:** `frontend/components.json`, `frontend/src/components/i18n/`, `layout/`, `theme/`, multiple `ui/*` primitives, `frontend/src/i18n/`, `frontend/src/hooks/use-mobile.ts`, `frontend/src/lib/utils.ts`, `chat/scripts/load_shipment_graph.py`.

**Audit-side note:** Playwright was installed transiently in `frontend/` for headless evidence capture (`npm install --no-save playwright`), which further modified `frontend/package-lock.json` and added `frontend/node_modules/playwright*`. Do not treat this as product intent; revert or ignore lockfile drift from audit tooling if desired.

## Runtime / service

| Field | Value |
| --- | --- |
| **APP_URL** | `http://127.0.0.1:8000` |
| **Service status at audit** | **UP** — HTTP 200 on `/` |
| **Start method (production)** | `./serve.sh` → `npm run build` in `frontend/`, then `uvicorn backend.main:app` on `:8000` |
| **DATABASE_WRITES** | None performed |
| **LIVE_MUTATING_REQUESTS** | None performed |

### Build / asset identity (served vs dist)

| Asset | Served URL | On disk |
| --- | --- | --- |
| JS bundle | `/assets/index-Ca8GudiR.js` | `frontend/dist/assets/index-Ca8GudiR.js` |
| CSS bundle | `/assets/index-6fyoBKuw.css` | `frontend/dist/assets/index-6fyoBKuw.css` |

- **Dist build time:** `index-6fyoBKuw.css` last modified `2026-09-17 18:41:58` (local).
- **Source `index.css`:** `2026-09-17 18:39:45` — build is current relative to CSS source at audit time.
- **Identity check:** Served HTML references match `frontend/dist/index.html` hashes (not stale alternate bundle).

## Package manager & validation scripts

| Field | Value |
| --- | --- |
| **PACKAGE_MANAGER** | npm (`frontend/package-lock.json`) |
| **dev** | `vite` |
| **build** | `tsc -b && vite build` |
| **lint** | `oxlint` |
| **test** | `vitest run` |
| **preview** | `vite preview` (not used; production served via FastAPI static mount) |

## Browser tooling

| Tool | Status |
| --- | --- |
| **cursor-ide-browser MCP** | Present in environment but **blocked** — `browser_navigate` / `browser_cdp` returned "No browser tab available" |
| **Playwright (headless Chromium)** | Used successfully for evidence capture (see evidence folder) |

## Theme / locale wiring (observed)

- Inline FOUC guard in `frontend/index.html` reads `localStorage['agentx-theme']` and toggles `html.dark`.
- React `ThemeProvider` (`frontend/src/components/theme/ThemeProvider.tsx`) mirrors storage key `agentx-theme`.
- `LanguageProvider` + `en`/`ar` catalogs under `frontend/src/i18n/`.
- Audit matrix: **EN + Light**, **EN + Dark**, desktop viewport **1440×900**.

## API health (read-only probes)

| Endpoint | Result |
| --- | --- |
| `GET /` | 200 |
| `GET /samples` | 200 — 75 open cases |
| `GET /cases` | 200 (used by Decisions view) |
| `GET /graph` | **500** — Explore graph lens empty at audit time |
| `GET /schema` | Not re-probed after graph failure |

## Evidence artifacts

- Measurements JSON: `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements.json`
- Screenshots (16): `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/*.png`
- Capture script (audit tooling): `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/audit-capture.mjs`
