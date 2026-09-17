# Batch 4 Closure Review — `bilingual-ui-domain-display`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** CLOSURE REVIEWER 5D (read-only)  
**Branch:** `fhd` (unchanged; no commits)  
**Frozen candidate:** `index-DVhlRZ8U.css` / `index-DE557tU5.js` @ `http://127.0.0.1:8000`  
**Viewport:** 1440×900 desktop, locales EN + AR × themes Light + Dark  
**Prior:** B4 audit [b4-audit.md], impl [b4-impl.md], review [b4-review.md], gate [b4-gate.md]  
**Date:** 2026-09-17

---

## Overall verdict: **PASS**

Independent closure revalidation confirms Batch 4 bilingual UI, data-identity, and layout-safety repairs **hold on the frozen final build**. I01–I04 pass across the full EN/AR × Light/Dark matrix with documented exceptions applied. Run-owned diff review finds **no forbidden backend/db/env edits** and **no test fixtures in production paths**. Theme and language persistence use **independent** `localStorage` keys. One **LOW** residual (`Toggle Sidebar` sr-only in `ui/sidebar.tsx`) and one **BLOCKED** cross-batch item (`GET /graph` → 500) remain non-blocking for B4 closure.

---

## Build fingerprint

| Layer | Identity | Match frozen candidate? |
| --- | --- | --- |
| Served CSS | `index-DVhlRZ8U.css` | **Yes** |
| Served JS | `index-DE557tU5.js` | **Yes** |
| Dist on disk (post-closure rebuild) | same hashes | **Yes** |
| Prior B4 audit JS | `index-BVWhf3oi.js` | Superseded (i18n bundle growth) |

---

## Per-issue closure verdicts (I01–I04)

| ID | B4 audit baseline | B4 gate | Closure (independent) | Verdict |
| --- | --- | --- | --- | --- |
| **I01** | REPRODUCED (~70 English gaps in AR) | PASS | **PASS** — `b4-gate-capture.mjs` re-run: `blockingMarkers: []` for AR intake/decisions; scope Arabic; `StageCard`/`CaseFile`/`ShipmentMap`/`AppHeader` wired via `t()`; visible sidebar trigger uses `t('common.toggleSidebar')` | **PASS** |
| **I02** | REPRODUCED (raw `replace(/_/g,' ')`) | PASS | **PASS** — `IntakeView.tsx:133` uses `rootCauseLabel(c.category)`; zero `rawCategoryKeys` in AR gate scan; `IntakeView.test.tsx` asserts `تعارض في العنوان` not `address conflict` | **PASS** |
| **I03** | REPRODUCED (English legend + `humanizeKey`) | PASS | **PASS** — `GraphView`/`BrainGraph` legend + detail `dt` via `entityLabel()` / `propertyLabel()`; `GraphView.test.tsx` asserts `الشحنة` not `Shipment`; schema proxy `GET /schema` → 200 | **PASS** |
| **I04** | REPRODUCED (hardcoded labels + `pending`) | PASS | **PASS** — StageCard field labels via `t('intake.stages.*')`; pending via `t('common.pending')`; count-neutral `بانتظار قرار — 75`; `DecisionsView.test.tsx` AR pending regression | **PASS** |

### Acceptance matrix (closure re-run @ 1440×900)

| Surface | EN Light | EN Dark | AR Light | AR Dark |
| --- | --- | --- | --- | --- |
| Intake idle (categories + scope) | ✓ | ✓ | ✓ Arabic | ✓ |
| Decisions (chrome + pending) | ✓ | ✓ | ✓ Arabic | ✓ |
| Schema legend | ✓ | ✓ | ✓ Arabic entity labels | ✓ |
| Theme menu | Light/Dark/System | ✓ | فاتح/داكن/النظام | ✓ |
| Language menu | English/العربية | ✓ | English/العربية | ✓ |

Gate capture re-run: **0 blocking issues**; verdicts `{ I01: PASS, I02: PASS, I03: PASS, I04: PASS }`.

---

## Display-map usage (`rootCauseLabel` / `entityLabel`)

### Verified call sites (grep + source read)

| Helper | Surfaces | API key preserved? |
| --- | --- | --- |
| `rootCauseLabel()` | `IntakeView` idle cards; `StageCard` classify + precedent; `DecisionsView` problems/focus/queue/filter (display only) | **Yes** — filter `<option value={rc}>` and `selection.key` use raw `c.category`; display uses `rootCauseLabel(rc)` |
| `entityLabel()` | `GraphView`/`BrainGraph` legend, selected labels, node-type headers | **Yes** — maps Neo4j label strings for display; unknown labels fall back to raw English ontology name |
| `propertyLabel()` | Graph detail `dt` keys | **Yes** — dictionary map → `humanizeKey()` fallback for unknown keys |

### Intentional exceptions (documented, not defects)

| Item | Rationale | Disposition |
| --- | --- | --- |
| `SHP-*`, `FR-*`, resolution IDs | Technical identifiers | Preserved; `dir="ltr"` / `font-mono` |
| Complaint text, cities, couriers, actions | API domain content | Preserved; `dir="auto"` on evidence spans |
| Graph node captions, property **values** | Data from `/schema` | Not UI labels |
| Canvas node type chips (`Shipment`, `Policy`, …) | NVL renderer ontology tokens from payload | Legend translated; chips are data labels |
| `stage.label`, `stage.lane` from SSE | Backend pipeline vocabulary | B4 out of scope |
| `English` endonym, `EN`/`AR` codes | Language picker convention | Expected |
| `Neo4j` in scope string | Product name in translated scope | Expected |
| OpenStreetMap attribution | Third-party license | Expected |
| sr-only `Toggle Sidebar` in `ui/sidebar.tsx` | Shadcn primitive; out of B4 allowlist | **LOW** — visible trigger overridden in `AppHeader` |
| `SidebarRail` aria/title in `ui/sidebar.tsx` | Collapse rail; out of allowlist | Not fixed |
| Unknown root cause / entity keys | Fallback to spaced English or raw label | Acceptable display-map behavior |

---

## Layout safety & data identity

| Check | Closure result |
| --- | --- |
| `document.documentElement.dir` | **`ltr`** in all 4 locale×theme combos (`measurements-b4-gate.json`) |
| Sidebar position | **Left** (`sidebarLeft: 0`) |
| Language toggle remount | **No** — `App.tsx` keys on `view` only |
| Schema canvas after lang+theme toggle | **Persists** (`hasCanvas: true` before/after) |
| Problem selection after locale toggle | **Preserved** (`selectionPreserved: true`) |
| Global RTL layout | **Not introduced** — per-span `dir="auto"` / `dir="rtl"` only on Arabic evidence text |
| Raw API/filter keys | **Preserved** — queue filter values, selection keys, failure/shipment IDs unchanged |
| Tooltip HTML safety | **PASS** — no `dangerouslySetInnerHTML` in `frontend/src`; `TooltipContent` renders React text children (`DecisionsView`, `TrustChip`, sidebar) |

### B1 / B3 sentinel survival (AR, post-i18n)

| Sentinel | Light | Dark | Threshold | Status |
| --- | ---: | ---: | ---: | --- |
| H01 Intake count | 5.62:1 | 8.23:1 | ≥4.5:1 | **PASS** |
| H03 Problem selected | 9.95:1 | 11.58:1 | ≥4.5:1 | **PASS** |
| B3 `data-variant` segments | 31 | 31 | ≥20 | **PASS** |
| B3 panel heights | Problems 440px / queue 400px | same | 440/400 | **PASS** |

---

## Theme / language persistence independence

| Concern | Implementation | Independent? |
| --- | --- | --- |
| Language storage | `localStorage['agentx-language']` in `LanguageProvider.tsx` | **Yes** |
| Theme storage | `localStorage['agentx-theme']` in `ThemeProvider.tsx` + FOUC guard in `index.html` | **Yes** |
| Cross-read | Neither provider reads the other's key | **Yes** |
| Provider nesting | `ThemeProvider` → `LanguageProvider` → `App` in `main.tsx` | Orthogonal contexts |

Toggling language does not alter theme storage; toggling theme does not alter language storage. Gate `toggle-no-remount` confirms combined lang+theme toggle preserves schema canvas and selection.

---

## Commands run (closure reviewer, independent)

| Command | Result | Notes |
| --- | --- | --- |
| `cd frontend && npm run test` | **PASS** | 23 files, **74/74** tests |
| `cd frontend && npm run lint` | **PASS** | 0 errors; 13 pre-existing warnings |
| `cd frontend && npm run build` | **PASS** | `index-DVhlRZ8U.css` / `index-DE557tU5.js` |
| `GET http://127.0.0.1:8000` | **200** | Fingerprints match candidate |
| `GET http://127.0.0.1:8000/graph` | **500** | Unchanged backend blocker |
| `GET http://127.0.0.1:8000/schema` | **200** | Schema proxy viable for I03 |
| `node …/b4-gate-capture.mjs` | **PASS** | 0 blocking issues; matrix + menus |

No product code edits. No staging, commit, push, or deploy.

---

## Full run diff review (B1–B4 cumulative)

### Forbidden paths — verified clean

| Path class | Status |
| --- | --- |
| `backend/**` | **No diff** vs `HEAD` |
| `*.env*` / env files | **No diff** |
| `chat/view/subgraph.py` | **Not edited** (`CYPHER 25` remains) |
| Database writes / live mutations | **None** performed |

### Run-owned allowlists (by batch)

| Batch | Scope | Key paths |
| --- | --- | --- |
| **B1** | Theme cascade / hover | `index.css`, `IntakeView`, `DecisionsView`, `table.tsx`, `sidebar.tsx`, `shell.tsx`, `BrainGraph.tsx`, tests |
| **B2** | Visualization theme lifecycle | `StageCard`, `CaseFile`, `ShipmentMap`, `GraphView`, `BrainGraph`, tests |
| **B3** | Metric semantics / workspace | `index.css`, `progress.tsx`, `table.tsx`, `DecisionsView`, `agent.ts`, `DecisionsView.test.tsx` |
| **B4** | Bilingual UI / display maps | `i18n/en.ts`, `ar.ts`, `parity.test.ts`, `LanguageProvider`, `IntakeView`, `StageCard`, `CaseFile`, `ShipmentMap`, `DecisionsView`, `GraphView`, `BrainGraph`, `AppHeader`, `AppSidebar`, tests, `docs/agent-runs/**` |

B4 run-owned edits are confined to the B4 allowlist. Working tree also carries B1–B3 allowlist files and infrastructure added during the run (`frontend/src/components/i18n/`, `layout/`, `theme/`, `ui/*` primitives, `hooks/`, `lib/utils.ts`).

### Out-of-allowlist / coordinator exclusions

| Path | Allowlist? | Gate note |
| --- | --- | --- |
| `frontend/src/components/chat/AppNav.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/chat/TrustChip.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/chat/TrustChip.test.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/ui/Skeleton.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/ui/Tooltip.tsx` | **No** | Pre-existing dirty |
| `frontend/vite.config.ts` | **No** | Pre-existing dirty |
| `frontend/tsconfig*.json` | **No** | Pre-existing dirty |
| `chat/scripts/load_shipment_graph.py` | **Forbidden** | Untracked fixture script — **exclude from commit** |

### Production fixture check

| Check | Result |
| --- | --- |
| Test mocks in `DecisionsView.tsx` production path | **None** |
| Vitest fixtures only in `*.test.tsx` | **Yes** |
| Playwright/evidence under `docs/agent-runs/evidence/` | Isolated from served bundle |

**Scope verdict:** ALLOWLIST_OK; pre-existing dirt outside allowlists remains; coordinator must stage only run-owned files and exclude `chat/scripts/load_shipment_graph.py`.

---

## Cross-batch defects (outside B4 scope, still present on frozen build)

| ID | Severity | Finding | Batch owner | Disposition |
| --- | --- | --- | --- | --- |
| **GRAPH-500** | **BLOCKED** | `GET /graph` → 500 (`CYPHER 25` in `chat/view/subgraph.py`) | B2 / backend | Live Graph lens E03/E04 proof deferred; Schema proxy sufficient for I03 UI |
| **D01** | **DEFERRED** | `writebacks.pending` not surfaced in UI; API `pending: 0` | B3 | Amber path unit-tested; re-verify when seed data changes |
| **I01-residual** | **LOW** | sr-only `Toggle Sidebar` + `SidebarRail` English aria in `ui/sidebar.tsx` | B4 adjacent | Visible trigger translated in `AppHeader`; rail out of allowlist |
| **CHAT-EN** | **LOW** | `TrustChip` tooltip remains English; chat nav out of nav-scope allowlists | Pre-batch | Exclude or separate PR |
| **SSE-PIPELINE** | **INFO** | `stage.label`, `stage.lane` from SSE still English during active Intake run | Backend / follow-up | Display-map candidate; not translated in B4 |
| **I03-canvas** | **INFO** | Graph canvas node chips show English ontology labels from payload | B4 documented | Intentional data labels; legend uses `entityLabel()` |
| **LOCKFILE-DRIFT** | **INFO** | `package-lock.json` may include transient Playwright from audit tooling | Baseline note | Coordinator may strip or accept with evidence-only deps |
| **H05-polish** | **OPTIONAL** | Sidebar hover vs active distinction (B1 addressed tokens; polish optional) | B1 | Non-blocking per B1 closure |

No new BLOCKER or HIGH defects introduced by B4. B1/B3 closure verdicts (5A, 5C) remain valid on this build.

---

## Regression tests verified

| Test | Status | Asserts |
| --- | --- | --- |
| `LanguageProvider.test.tsx` | **PASS** | `rootCauseLabel`, `entityLabel`, `propertyLabel` EN+AR |
| `parity.test.ts` | **PASS** | EN↔AR leaf key parity |
| `StageCard.test.tsx` | **PASS** | No raw `Category`/`Verdict` in AR DOM |
| `IntakeView.test.tsx` | **PASS** | Arabic root cause on idle cards |
| `DecisionsView.test.tsx` | **PASS** | Arabic pending; no `2 pending` |
| `GraphView.test.tsx` | **PASS** | Legend `الشحنة` not `Shipment` |
| `b4-gate-capture.mjs` | **PASS** | Full matrix; documented exceptions; selection preservation |

---

## Evidence artifacts

| Artifact | Path |
| --- | --- |
| Closure report | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b4-closure.md` (this file) |
| B4 audit | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b4-audit.md` |
| B4 gate | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b4-gate.md` |
| Gate measurements (re-run) | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b4-gate.json` |
| Gate capture script | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-gate-capture.mjs` |
| Gate screenshots | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-gate-*.png` |
| Issue register | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-issue-register.md` |

---

## Coordinator payload

```yaml
RUN_ID: 2026-09-17T19-21-agentx-ui-repair-proof
AGENT: 5D (B4 CLOSURE REVIEWER)
VERDICT: PASS
BUILD_CSS: index-DVhlRZ8U.css
BUILD_JS: index-DE557tU5.js
MATRIX: EN+AR × Light+Dark @ 1440×900
I01: PASS
I02: PASS
I03: PASS
I04: PASS
LAYOUT_SAFETY: PASS
DATA_IDENTITY: PASS
TOOLTIP_SAFETY: PASS
THEME_LANG_PERSISTENCE: INDEPENDENT
B1_H01_H03_AR: PASS
B3_METRICS_AR: PASS
GRAPH_ENDPOINT: 500 (unchanged)
SCOPE: ALLOWLIST_OK; PRE_EXISTING_DIRT_OUTSIDE_ALLOWLIST
FORBIDDEN_PATHS: CLEAN
COMMIT: NOT_PERFORMED
```

---

## Return to coordinator

```
VERDICT: PASS

B4 bilingual UI + domain display labels CONFIRMED on frozen final build.
I01–I04 pass EN/AR × Light/Dark with documented exceptions. rootCauseLabel/
entityLabel/propertyLabel wired correctly; API keys and IDs preserved; tooltips
safe; dir=ltr global layout intact. Full run diff: no backend/db/env edits;
exclude chat/scripts/load_shipment_graph.py and pre-existing chat/vite dirt.

Cross-batch: /graph still 500 (BLOCKED); D01 deferred; sr-only sidebar LOW.

Freeze: index-DVhlRZ8U.css / index-DE557tU5.js @ http://127.0.0.1:8000
```
