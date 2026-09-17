# Batch 4 Review — `bilingual-ui-domain-display`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT C (REVIEW / FIX)  
**Branch:** `fhd` (unchanged; **no commit**)  
**Candidate build:** `index-DVhlRZ8U.css` / `index-DE557tU5.js` @ `http://127.0.0.1:8000`  
**Prior:** B4 Audit [e99e7880], B4 Impl [deecf0ca](deecf0ca-c927-46dc-9529-66c5ac926d8d)  
**Date:** 2026-09-17

---

## Overall verdict: **PASS**

Independent verification confirms I01–I04 are resolved in scoped surfaces. B1 contrast sentinels and B3 metric semantics hold in AR after translation. Layout safety constraints preserved (`dir=ltr`, left sidebar, no `key={language}` remount). One documented **LOW** residual (`Toggle Sidebar` sr-only text in out-of-allowlist `ui/sidebar.tsx`) — not a blocker.

**Fixes applied by Review:** none (no BLOCKER/HIGH in-scope defects found).

---

## Verification matrix

| ID | Verdict | Independent evidence |
| --- | --- | --- |
| **I01** | **PASS** | AR screenshots show Arabic scope header, shell chrome, Decisions dashboard; `StageCard`/`CaseFile`/`ShipmentMap` wired via `t()`; GraphView close aria via `t('common.close')`. Residual `Toggle Sidebar` is sr-only in `ui/sidebar.tsx` (out of allowlist; trigger `aria-label`/`title` overridden in `AppHeader`). |
| **I02** | **PASS** | Intake idle cards show Arabic root causes (`تعذر الوصول إلى المستلم`, `عدم تطابق الباركود`, …); zero raw category keys in Playwright scan; `IntakeView.test.tsx` asserts `تعارض في العنوان` not `address conflict`. |
| **I03** | **PASS** | Schema legend shows Arabic entity labels (`الشحنة`, `سياسة الخدمة`, `سبب التعثر`, …); detail panel uses `propertyLabel()`; `GraphView.test.tsx` asserts no raw `Shipment`/`Policy` in legend. Canvas node type chips remain English (API ontology labels — intentional). |
| **I04** | **PASS** | StageCard field labels via `t('intake.stages.*')`; verdict badges `رفض`/`قبول`; pending via `t('common.pending')`; count phrasing `بانتظار قرار — 75`. |
| **Safety** | **PASS** | `document.documentElement.dir === 'ltr'` in light+dark AR; `sidebarLeft: 0`; `App.tsx` keys on `view` only; schema canvas persists after lang+theme toggle (`hasCanvas: true` before/after). Raw keys preserved for filter/API (`category` values unchanged; display via `rootCauseLabel`). |
| **Dictionary** | **PASS** | `parity.test.ts` — identical EN↔AR leaf paths; `Messages` type enforces structural parity; interpolation placeholders (`{count}`, `{total}`, …) match per key. |
| **B1/B3** | **PASS** | H01 light **5.62:1**, dark **8.23:1**; H03 light **9.95:1**, dark **11.58:1**; B3 segments **31** `data-variant`; panel heights Problems **440px**, queue **400px**. |

---

## Tooling results (re-run by Review)

| Command | Result |
| --- | --- |
| `npm run test` | **23 files, 74 tests PASS** |
| `npm run lint` | **0 errors** (pre-existing warnings only) |
| `npm run build` | **PASS** → `index-DE557tU5.js` |

Build fingerprint served from `http://127.0.0.1:8000` matches candidate JS hash.

---

## Browser evidence (AR × Light/Dark)

Capture script: `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-review-capture.mjs`  
Measurements: `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b4-review.json`

| Surface | Light | Dark | vs audit (before) |
| --- | --- | --- | --- |
| Intake idle | `b4-review-intake-ar-light.png` | `b4-review-intake-ar-dark.png` | Category tags **English → Arabic**; scope **English → Arabic** |
| Decisions | `b4-review-decisions-ar-light.png` | `b4-review-decisions-ar-dark.png` | Root causes already Arabic; pending now `معلّق` not `pending` |
| Schema | `b4-review-schema-ar-light.png` | `b4-review-schema-ar-dark.png` | Legend **Policy/Shipment/… → Arabic** entity labels |

### Before → after highlights

| Finding (audit) | After (review) |
| --- | --- |
| Scope header English in all AR captures | `معالجة شكاوى الشحنات تلقائيًا عبر رسم معرفي Neo4j` |
| Intake cards: `recipient unavailable`, `hub delay` | `تعذر الوصول إلى المستلم`, `تأخر في مركز المعالجة` |
| Schema legend: `Policy`, `Order`, `Shipment`, … | `سياسة الخدمة`, `الطلب`, `الشحنة`, … |
| Count: `75 shipment(s) awaiting` / singular `شحنة` | `بانتظار قرار — 75` (count-neutral) |
| Hardcoded `pending` in Decisions | `{count} معلّق` via `t('common.pending')` |

---

## Grep — residual hardcoded English (allowlisted files)

| File | Finding | Severity |
| --- | --- | --- |
| `StageCard.tsx` | English only in comments | — |
| `ShipmentMap.tsx` | `OpenStreetMap` attribution (third-party) | Intentional |
| `CaseFile.tsx` | `'Shipment'` label check for graph node lookup (not displayed) | Intentional |
| `AppHeader.tsx` | All chrome via `t()` | ✓ |
| `AppSidebar.tsx` | `t('common.application')` favicon alt | ✓ |
| `IntakeView.tsx` | `rootCauseLabel(c.category)` | ✓ |
| `DecisionsView.tsx` | `t('common.pending')`; `variant: 'pending'` is CSS token | ✓ |
| `GraphView.tsx` / `BrainGraph.tsx` | `entityLabel()` / `propertyLabel()` / `t()` | ✓ |
| `i18n/en.ts`, `i18n/ar.ts` | Dictionary source strings (EN locale retains English) | Expected |

**Out of allowlist (not fixed):**

| File | String | Reason |
| --- | --- | --- |
| `ui/sidebar.tsx:273` | sr-only `Toggle Sidebar` | Shadcn primitive; visible trigger overridden in `AppHeader` with `t('common.toggleSidebar')` |
| `ui/sidebar.tsx:285-288` | `SidebarRail` aria/title | Collapse rail; not in B4 allowlist |

---

## Review lenses

### Unknown-key fallback

| Helper | Fallback chain | Exposes raw key? |
| --- | --- | --- |
| `t(key)` | AR → EN → key string | Only for missing dictionary entries (none found) |
| `rootCauseLabel(raw)` | map → `normalized` (spaces, not underscores) | Unknown causes show spaced English, not `snake_case` API key |
| `entityLabel(label)` | map → raw Neo4j label | Unknown entities show English ontology name |
| `propertyLabel(key)` | map → `humanizeKey(key)` | Unknown properties show English title-case |

App-owned labels route through dictionaries; no raw `intake.stages.*` keys observed in DOM.

### Mixed-language readability

- Complaint text, cities, couriers, actions: `dir="auto"` on evidence spans ✓
- SHP IDs, tracking: `dir="ltr"` / `font-mono` ✓
- Arabic chrome + Latin IDs render cleanly in screenshots

### Preserved (not translated)

| Item | Source | Reason |
| --- | --- | --- |
| `SHP-*`, `FR-*`, resolution IDs | API / SSE | Technical identifiers |
| Complaint text, cities, couriers, actions | API | Domain content |
| Graph node captions, property values | `/schema` payload | Evidence/data |
| Canvas node type chips (`Shipment`, `Policy`, …) | NVL renderer labels from graph | Ontology tokens attached to nodes; legend uses `entityLabel()` |
| `stage.label`, `stage.lane` from SSE | Backend pipeline | Out of B4 scope (display-map candidate) |
| `English`, `EN`/`AR` codes | Language picker | Endonym / locale codes |
| OpenStreetMap attribution | Leaflet | Third-party license |

---

## Regression tests verified

| Test file | Asserts |
| --- | --- |
| `LanguageProvider.test.tsx` | `rootCauseLabel`, `entityLabel`, `propertyLabel` EN+AR |
| `parity.test.ts` | EN↔AR leaf key parity |
| `StageCard.test.tsx` | No raw `Category`/`Verdict` in AR DOM |
| `IntakeView.test.tsx` | Arabic root cause on idle cards |
| `DecisionsView.test.tsx` | Arabic `2 معلّق`, no `2 pending` |
| `GraphView.test.tsx` | Legend `الشحنة` not `Shipment` |

---

## Issues found / disposition

| ID | Severity | Detail | Action |
| --- | --- | --- | --- |
| I01-residual | **LOW** | sr-only `Toggle Sidebar` in `ui/sidebar.tsx` appears in `innerText` scan | Documented exception; out of allowlist; visible control translated |
| I03-canvas | **INFO** | Graph canvas node chips still English ontology labels | Intentional — data labels, not UI chrome; legend translated |
| B2-graph-500 | **UNCHANGED** | `GET /graph` → 500 | Pre-existing backend blocker; Schema proxy sufficient for I03 UI |

**No BLOCKER or HIGH defects requiring in-scope fixes.**

---

## Cross-batch status (post-B4 review)

| Batch | Status |
| --- | --- |
| B1 theme cascade | Sentinels **PASS** in AR (H01, H03) |
| B2 visualization | Schema OK; `/graph` **BLOCKED** (unchanged) |
| B3 metric semantics | Segments + panel heights **PASS** in AR |
| B4 bilingual | **PASS** — ready for coordinator merge |

---

## Evidence paths

| Artifact | Path |
| --- | --- |
| Review capture script | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-review-capture.mjs` |
| Review measurements | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b4-review.json` |
| Review screenshots (6) | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-review-*.png` |
| Audit baseline | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b4-audit.md` |
| Impl handoff | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b4-impl.md` |
