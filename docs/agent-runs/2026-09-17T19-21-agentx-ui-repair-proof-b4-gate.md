# Batch 4 Validation Gate — `bilingual-ui-domain-display`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT D (VALIDATION / COMMIT-READINESS GATE)  
**Branch:** `fhd` (unchanged; **not committed**)  
**Candidate build:** `index-DVhlRZ8U.css` / `index-DE557tU5.js` @ `http://127.0.0.1:8000`  
**Viewport:** 1440×900 desktop, locales EN + AR × themes Light + Dark  
**Prior:** B4 Audit [e99e7880], Impl [deecf0ca], Review [1c4694a5] — PASS  
**Date:** 2026-09-17

---

## Overall Batch 4 verdict: **PASS**

| Category | Verdict |
| --- | --- |
| **Scope** | **PASS** — B4 run-owned edits confined to allowlist; pre-existing dirty files not expanded by B4 agents |
| **Automated** (test/lint/build/fingerprint) | **PASS** — 74/74 tests; fingerprint matches candidate served @ :8000 |
| **Bilingual matrix** (EN+AR × Light+Dark) | **PASS** — intake idle, Decisions, Schema legend, theme/language menus captured |
| **I01–I04** (browser evidence) | **PASS** — independent Playwright gate with documented exceptions applied |
| **Layout safety** | **PASS** — `dir=ltr`, sidebar left, no graph remount, selection preserved across locale toggle |
| **B1 sentinels** (AR) | **PASS** — H01 light 5.62:1 / dark 8.23:1; H03 light 9.95:1 / dark 11.58:1 |
| **B3 metrics** (AR) | **PASS** — 31 `data-variant` segments; Problems 440px / queue 400px |
| **Live Graph lens** | **BLOCKED** — `GET /graph` → 500 (unchanged; out of B4 scope) |
| **Commit readiness** | **READY (conditional)** — stage B4 allowlist (+ prior batch allowlists if bundling); exclude pre-existing chat/vite/tsconfig dirt |

Batch 4 meets coordinator rules: I01–I04 **PASS** with browser proof; B1/B3 AR smoke **PASS**; `/graph` **BLOCKED** (not FAIL).

---

## Per-issue gate verdicts

| ID | Expected | Gate verdict | Functional | Visual | Evidence |
| --- | --- | --- | --- | --- | --- |
| **I01** | FIXED | **PASS** | Shell scope, chrome aria-labels, StageCard/CaseFile/ShipmentMap/GraphView close via `t()` | AR screenshots show Arabic scope + dashboard chrome | `b4-gate-intake-ar-{light,dark}.png`, `b4-gate-decisions-ar-*.png`; `englishInventory.intake-ar-*` blockingMarkers **[]** |
| **I02** | FIXED | **PASS** | Idle case metadata uses `rootCauseLabel()` | Cards show `تعذر الوصول إلى المستلم`, `تأخر في مركز المعالجة`, … | Zero raw category keys in AR scan; `IntakeView.test.tsx` |
| **I03** | FIXED | **PASS** | Legend + detail `dt` via `entityLabel()` / `propertyLabel()` | Legend Arabic (`سياسة الخدمة`, `الشحنة`, …); canvas node chips English (intentional) | `b4-gate-schema-ar-light.png`; `GraphView.test.tsx` |
| **I04** | FIXED | **PASS** | StageCard field labels; pending via `t('common.pending')`; count-neutral awaiting | `بانتظار قرار — 75`; no ` pending` in AR Decisions body | `b4-gate-decisions-ar-light.png`; `DecisionsView.test.tsx` |
| **Safety** | — | **PASS** | `dir=ltr` all combos; `sidebarLeft: 0`; `App.tsx` keys on `view` only | Schema canvas persists lang+theme toggle | `toggle-no-remount.hasCanvas: true`; `selectionPreserved: true` |
| **B1 H01** | PASS | **PASS** | AR intake count contrast ≥4.5:1 | Light 5.62:1, dark 8.23:1 | `measurements-b4-gate.json` |
| **B1 H03** | PASS | **PASS** | Selected problem row contrast ≥4.5:1 | Light 9.95:1, dark 11.58:1 | Same |
| **B3 M01/L01** | PASS | **PASS** | 31 semantic segments; panel heights 440/400 | Unchanged post-i18n | `B3-progress-variants`, `B3-panel-heights` |

### I01 residual (documented, non-blocking)

| Finding | Severity | Disposition |
| --- | --- | --- |
| sr-only `Toggle Sidebar` in `ui/sidebar.tsx` appears in `innerText` scan | **LOW** | Documented exception; visible trigger uses `t('common.toggleSidebar')` in `AppHeader` |
| Canvas node type chips (`Shipment`, `Policy`, …) | **INFO** | Ontology tokens from graph payload — legend translated, node labels are data |

Review script auto-FAIL on `Toggle Sidebar` is **overridden at gate** per audit/review documented exceptions.

---

## Commands run and results (Agent D, independent)

| Command | Result | Notes |
| --- | --- | --- |
| `cd frontend && npm run test` | **PASS** | 23 files, **74/74** tests |
| `cd frontend && npm run lint` | **PASS** | 13 warnings (pre-existing `only-export-components`; intentional `resolvedTheme` deps) |
| `cd frontend && npm run build` | **PASS** | `index-DVhlRZ8U.css` (110.68 kB), `index-DE557tU5.js` (4049.31 kB) — **matches candidate** |
| `node docs/agent-runs/evidence/.../b4-gate-capture.mjs` | **PASS** | 0 blocking issues; 21 screenshots; full EN+AR matrix + menus |
| `GET http://127.0.0.1:8000` | **200** | Served `index-DVhlRZ8U.css` / `index-DE557tU5.js` |
| `GET http://127.0.0.1:8000/graph` | **500** | Live Graph blocked (unchanged) |
| `GET http://127.0.0.1:8000/schema` | **200** | Schema proxy viable for I03 |

No staging, commit, push, or deploy performed. **No product code edits** by Agent D.

---

## Source / build fingerprint manifest

| Layer | Identity | Match candidate? |
| --- | --- | --- |
| **Served CSS** | `http://127.0.0.1:8000/assets/index-DVhlRZ8U.css` | **Yes** |
| **Served JS** | `http://127.0.0.1:8000/assets/index-DE557tU5.js` | **Yes** |
| **Dist on disk** | `frontend/dist/assets/index-DVhlRZ8U.css`, `index-DE557tU5.js` | **Yes** (post-gate rebuild identical hash) |
| **Prior B4 audit** | `index-BVWhf3oi.js` | JS superseded (i18n bundle growth) |

Gate rebuild did not change content hashes — candidate build is current and served.

---

## Acceptance matrix (gate-measured)

EN + AR × {Light, Dark} @ 1440×900:

| Surface | EN Light | EN Dark | AR Light | AR Dark |
| --- | --- | --- | --- | --- |
| Intake idle (categories) | ✓ | ✓ | ✓ Arabic categories + scope | ✓ |
| Decisions | ✓ | ✓ | ✓ Arabic chrome + pending | ✓ |
| Schema legend | ✓ | ✓ | ✓ Arabic entity legend | ✓ |
| Theme menu | Light/Dark/System | ✓ | فاتح/داكن/النظام | ✓ |
| Language menu | English/العربية | ✓ | English/العربية (endonym) | ✓ |

Screenshots: `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-gate-*.png`

Full JSON: `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b4-gate.json`

### Before → after (audit baseline → gate)

| Finding (audit) | After (gate) |
| --- | --- |
| Scope header English in AR | `معالجة شكاوى الشحنات تلقائيًا عبر رسم معرفي Neo4j` |
| Intake cards: `recipient unavailable`, `hub delay` | `تعذر الوصول إلى المستلم`, `تأخر في مركز المعالجة` |
| Schema legend: `Policy`, `Shipment`, … | `سياسة الخدمة`, `الشحنة`, … |
| Hardcoded `pending` | `{count} معلّق` |
| Count: `75 shipment(s) awaiting` | `بانتظار قرار — 75` |

---

## Intentional exceptions (preserved)

| Item | Rationale |
| --- | --- |
| `SHP-*`, `FR-*`, resolution IDs | Technical identifiers; `dir=ltr` |
| Complaint text, cities, couriers, actions | API domain content |
| Graph node captions, property values | Evidence/data from `/schema` |
| Canvas node type chips (English ontology) | Data labels on NVL renderer; legend uses `entityLabel()` |
| `English` endonym, `EN`/`AR` codes | Language picker convention |
| `Neo4j` in scope string | Product name in translated scope |
| OpenStreetMap attribution | Third-party license |
| sr-only `Toggle Sidebar` in `ui/sidebar.tsx` | Out of allowlist; visible control translated |
| Backend `stage.label`, `stage.lane` | SSE pipeline vocabulary (B4 out of scope) |

---

## Layout safety verification

| Check | Gate result |
| --- | --- |
| `document.documentElement.dir` | **`ltr`** in all 4 locale×theme combos |
| Sidebar position | **Left** (`sidebarLeft: 0`) |
| Language toggle remount | **No** — `App.tsx` keys on `view` only; schema `hasCanvas: true` before/after toggle |
| Problem selection after locale toggle | **Preserved** — same `.border-primary/30` row (`selectionPreserved: true`) |
| Global RTL | **Not introduced** |

---

## B1 sentinel re-check (AR)

| Sentinel | Light | Dark | Threshold | Status |
| --- | ---: | ---: | ---: | --- |
| H01 Intake count | 5.62:1 | 8.23:1 | ≥4.5:1 | **PASS** |
| H03 Problem selected | 9.95:1 | 11.58:1 | ≥4.5:1 | **PASS** |

No regression vs `measurements-b4-audit.json` / `measurements-b4-review.json`.

---

## B3 metric smoke re-check (AR)

| Check | Light | Dark | Target | Status |
| --- | ---: | ---: | ---: | --- |
| `data-variant` segments | 31 | 31 | ≥20 | **PASS** |
| Problems panel height | 440px | 440px | 440 | **PASS** |
| Queue panel height | 400px | 400px | 400 | **PASS** |

Variants include `success`, `failure`, `pending`, `secondary` — semantic colors intact post-i18n.

---

## Run-owned file list vs forbidden changes

### Batch 4 run-owned edits (allowlist — expected)

| File | Agent | Purpose |
| --- | --- | --- |
| `frontend/src/i18n/en.ts`, `ar.ts` | B | Dictionary keys: scope, stages, entities, properties, common |
| `frontend/src/i18n/parity.test.ts` | B | EN↔AR leaf parity |
| `frontend/src/components/i18n/LanguageProvider.tsx` | B | +`entityLabel()`, +`propertyLabel()` |
| `frontend/src/components/i18n/LanguageProvider.test.tsx` | B | Display map regression |
| `frontend/src/components/views/IntakeView.tsx` | B | I02 `rootCauseLabel()` on idle cards |
| `frontend/src/components/agent/StageCard.tsx` | B | I01/I04 `t()` field labels |
| `frontend/src/components/agent/StageCard.test.tsx` | B | AR label regression |
| `frontend/src/components/agent/CaseFile.tsx` | B | I01 panel titles |
| `frontend/src/components/agent/ShipmentMap.tsx` | B | I01 map legend/popup |
| `frontend/src/components/views/DecisionsView.tsx` | B | I04 `t('common.pending')` |
| `frontend/src/components/views/DecisionsView.test.tsx` | B | AR pending fragment |
| `frontend/src/components/views/IntakeView.test.tsx` | B | AR root cause assertion |
| `frontend/src/components/artifacts/GraphView.tsx` | B | I03 legend/detail maps |
| `frontend/src/components/artifacts/GraphView.test.tsx` | B | AR legend regression |
| `frontend/src/components/artifacts/BrainGraph.tsx` | B | I03 parity with GraphView |
| `frontend/src/components/artifacts/BrainGraph.test.tsx` | B | LanguageProvider wrap |
| `frontend/src/components/layout/AppHeader.tsx` | B | I01 scope + sidebar trigger |
| `frontend/src/components/layout/AppSidebar.tsx` | B | I01 favicon alt |
| `docs/agent-runs/**` | A–D | Evidence + gate scripts only |

### Out-of-allowlist dirty files (pre-existing — not expanded by B4)

| Path | Allowlist? | Gate note |
| --- | --- | --- |
| `frontend/src/components/chat/AppNav.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/chat/TrustChip.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/chat/TrustChip.test.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/ui/Skeleton.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/ui/Tooltip.tsx` | **No** | Pre-existing dirty |
| `frontend/vite.config.ts` | **No** | Pre-existing dirty |
| `frontend/tsconfig*.json` | **No** | Pre-existing dirty |
| `chat/scripts/load_shipment_graph.py` | **Forbidden** | Untracked; not part of B4 |

### Forbidden paths

- `backend/**` — not edited ✓
- `chat/view/subgraph.py` — not edited ✓ (`CYPHER 25` remains; blocks `/graph`)
- No env / chat mutation invoked ✓

**Scope verdict:** B4 bilingual-ui-domain-display changes are confined to allowlist paths. Working tree carries B1–B3 + pre-batch dirt; coordinator should stage only run-owned files for the suggested commit.

---

## Regression test sentinel status

| Test | Status | Asserts |
| --- | --- | --- |
| `LanguageProvider.test.tsx` | **PASS** | `rootCauseLabel`, `entityLabel`, `propertyLabel` EN+AR |
| `parity.test.ts` | **PASS** | Dictionary leaf parity |
| `StageCard.test.tsx` | **PASS** | No raw `Category`/`Verdict` in AR DOM |
| `IntakeView.test.tsx` | **PASS** | Arabic root cause on idle cards |
| `DecisionsView.test.tsx` | **PASS** | Arabic pending; no `2 pending` |
| `GraphView.test.tsx` | **PASS** | Legend `الشحنة` not `Shipment` |
| `b4-gate-capture.mjs` | **NEW** | Full matrix; documented exceptions; selection preservation |

---

## Suggested commit message (READINESS ONLY — do not commit)

```
fix(i18n): complete bilingual UI and domain display labels

Extend LanguageProvider with entityLabel/propertyLabel and wire t()
through Intake, Decisions pending, StageCard, CaseFile, ShipmentMap,
and GraphView/BrainGraph legend. Preserve dir=ltr, left sidebar, and
no key={language} remounts. Add dictionary parity and AR regression tests.

Live Graph lens verification remains blocked (GET /graph returns 500).
```

Stage B4 allowlist files listed above (plus B1–B3 allowlists if bundling single repair commit). Exclude pre-existing chat/vite/tsconfig dirt unless intentionally bundled.

---

## Cross-batch status (post-B4 gate)

| Batch | Status |
| --- | --- |
| B1 theme cascade | Sentinels **PASS** in AR (H01, H03) |
| B2 visualization | Schema OK; `/graph` **BLOCKED** (unchanged) |
| B3 metric semantics | Segments + heights **PASS** in AR |
| B4 bilingual | **PASS** — ready for coordinator merge / Batch 5 closure |

---

## Handoff for Batch 5 closure

1. **Freeze candidate:** `index-DVhlRZ8U.css` / `index-DE557tU5.js` @ `http://127.0.0.1:8000`
2. **Commit posture:** PASS — safe to commit B4 allowlist with message above after coordinator strips out-of-scope dirty files.
3. **Live Graph blocker:** Restore `GET /graph` (`CYPHER 25` in `chat/view/subgraph.py` — needs coordinator permission). Re-run B2 gate Graph lens for full E03/E04 live proof.
4. **Optional polish (non-blocking):** sr-only `Toggle Sidebar` in `ui/sidebar.tsx`; SSE `stage.label`/`stage.lane` display-map; H05 active+hover polish from B1.
5. **Batch artifact index:**

| Batch | Docs | Measurements | Capture scripts | Key screenshots |
| --- | --- | --- | --- | --- |
| **B1** | `b1-audit.md`, `b1-impl.md`, `b1-review.md`, `b1-gate.md` | `measurements-gate.json`, `measurements-review.json` | `gate-capture.mjs`, `built-css-guard.mjs` | `gate-*.png` |
| **B2** | `b2-audit.md`, `b2-impl.md`, `b2-review.md`, `b2-gate.md` | `measurements-b2-*.json` | `b2-*-capture.mjs` | `b2-*-gate.png` |
| **B3** | `b3-audit.md`, `b3-impl.md`, `b3-review.md`, `b3-gate.md` | `measurements-b3-*.json` | `b3-gate-capture.mjs` | `b3-*-gate.png` |
| **B4** | `b4-audit.md`, `b4-impl.md`, `b4-review.md`, `b4-gate.md` (this file) | `measurements-b4-*.json` | `b4-*-capture.mjs`, `b4-gate-capture.mjs` | `b4-gate-*.png`, `b4-*-after.png`, `b4-review-*.png` |
| **Shared** | `issue-register.md` | — | — | `evidence/2026-09-17T19-21-agentx-ui-repair-proof/` |

6. **Suggested unified commit** (if bundling B1–B4): combine allowlists; message may reference theme + metrics + i18n; pin build `index-DVhlRZ8U.css` / `index-DE557tU5.js`.

---

## Evidence paths

| Artifact | Path |
| --- | --- |
| Gate capture script | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-gate-capture.mjs` |
| Gate measurements | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b4-gate.json` |
| Gate screenshots (21) | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-gate-*.png` |
| Review baseline | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b4-review.md` |
| Audit baseline | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b4-audit.md` |

---

## Coordinator payload

```yaml
RUN_ID: 2026-09-17T19-21-agentx-ui-repair-proof
AGENT: D (B4 VALIDATION GATE)
VERDICT: PASS
BUILD_CSS: index-DVhlRZ8U.css
BUILD_JS: index-DE557tU5.js
TESTS: PASS (74/74)
LINT: PASS (warnings only)
BROWSER_GATE: PASS (0 blocking issues)
I01: PASS
I02: PASS
I03: PASS
I04: PASS
B1_H01_H03_AR: PASS
B3_METRICS_AR: PASS
LAYOUT_SAFETY: PASS
GRAPH_ENDPOINT: 500 (unchanged)
SCOPE: ALLOWLIST_OK; PRE_EXISTING_DIRT_OUTSIDE_ALLOWLIST
COMMIT: NOT_PERFORMED
SUGGESTED_COMMIT: fix(i18n): complete bilingual UI and domain display labels
NEXT: Batch 5 closure — freeze candidate, coordinator merge
```
