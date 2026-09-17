# Batch 4 Audit — `bilingual-ui-domain-display`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT A (AUDIT)  
**Branch:** `fhd` (unchanged; no commits)  
**Candidate build:** `index-DVhlRZ8U.css` / `index-BVWhf3oi.js` @ `http://127.0.0.1:8000`  
**Viewport:** 1440×900 desktop, locales EN + AR × themes Light + Dark  
**Date:** 2026-09-17

---

## Overall verdict: **SCOPE_READY**

Batch 4 bilingual UI work is **ready for implementation** with a documented allowlist. The `/graph` 500 remains an **unchanged backend blocker** for live Graph-lens bilingual verification; Schema lens (`GET /schema` → 200) is sufficient to reproduce I03. No coordinator permission is required for frontend-only dictionary/extension work under the existing `LanguageProvider` / `t()` / `rootCauseLabel()` system.

**Live Graph lens:** BLOCKED (`GET /graph` → 500, same `CYPHER 25` defect as prior batches).

---

## Per-issue audit verdicts

| ID | Verdict | Evidence | Root cause (observed) |
| --- | --- | --- | --- |
| **I01** | **REPRODUCED** | `b4-intake-ar-light.png`, `b4-decisions-ar-light.png`, `b4-schema-ar-light.png`; source grep | Shell scope from `/meta` is English-only; Intake active-run components (`StageCard`, `CaseFile`, `ShipmentMap`) contain ~50 hardcoded English UI strings; chrome aria-labels (`Close`, `Toggle Sidebar`, `Application`) untranslated |
| **I02** | **REPRODUCED** | `b4-intake-ar-light.png` — cards show `recipient unavailable`, `hub delay`, `escalation:address conflict`; `IntakeView.tsx:133` | Category metadata uses `c.category.replace(/_/g, ' ')` instead of `rootCauseLabel()` used elsewhere in Decisions |
| **I03** | **REPRODUCED** | `b4-schema-ar-light.png` — legend `Policy`, `Order`, `Shipment`, `FailureReason`, …; `GraphView.tsx:274`; `/meta` → `labels: {}` | Graph legend renders raw Neo4j label strings; property panel uses `humanizeKey()` (English title-case); `/meta` returns no localized entity descriptions |
| **I04** | **REPRODUCED** | Source audit + AR browser; `measurements-b4-audit.json` H01 count text | `StageCard` field labels (`Category`, `Confidence`, `Verdict`, …) and status phrases (`Reject`/`Accept`, `AFL retry`, `worked`) hardcoded English; `DecisionsView.tsx:150,446` hardcodes `{n} pending`; AR `intake.awaiting` uses singular `شحنة` for all counts (no plural rule vs EN `shipment(s)`) |

---

## i18n infrastructure (read-only)

### Existing system (extend — do not replace)

| Piece | Path | Notes |
| --- | --- | --- |
| Provider | `frontend/src/components/i18n/LanguageProvider.tsx` | Sets `dir=ltr` for both langs ✓; exposes `t()`, `rootCauseLabel()` |
| Dictionaries | `frontend/src/i18n/en.ts`, `ar.ts` | Parity enforced by `Messages` type |
| Messages helper | `frontend/src/i18n/messages.ts` | `getMessage`, `interpolate` |
| Toggle | `LanguageToggle.tsx`, `ThemeToggle.tsx` | Menus fully translated |

### `rootCauseLabel()` usage audit

| Surface | Uses `rootCauseLabel()`? | Evidence |
| --- | --- | --- |
| Decisions Problems list | **Yes** | `DecisionsView.tsx:476` |
| Decisions Focus panel | **Yes** | `:528` |
| Decisions queue table | **Yes** | `:680` |
| Decisions queue filter `<select>` | **Yes** | `:640` |
| Decisions search | **Yes** (filter field) | `:350` |
| Intake idle case metadata | **No** — raw `replace(/_/g,' ')` | `IntakeView.tsx:133` |
| StageCard classify field | **No** — raw `d.category` | `StageCard.tsx:125` |
| Escalations | N/A (0 rows live) | Would show free-form `reason` / actions |

### Dictionary interpolation parity (EN ↔ AR)

| Key | EN | AR | Gap |
| --- | --- | --- | --- |
| `intake.awaiting` | `{count} shipment(s) awaiting…` | `{count} شحنة بانتظار قرار` | AR lacks plural forms (1 vs 75) |
| `decisions.learning.seeded` | `{count} seeded precedents` | `{count} سوابق أساسية` | Acceptable; no plural rule |
| `decisions.kpi.teamsDetail` | `Across {count} team(s)` | `عبر {count} فريق` | AR singular `فريق` for all counts |
| Pending writebacks | — | — | **Missing** — UI uses hardcoded English `pending` |

All other checked `t()` keys in shell, Decisions, Explore have AR counterparts.

---

## Display inventory — untranslated strings by surface

Classification: **UI** = translate via `t()` · **Display map** = `rootCauseLabel()` / entity map · **Technical ID** = preserve · **Evidence** = preserve free-form

| Surface | UI (translate) | Display map gap | Technical / evidence (preserve) | Total gaps |
| --- | ---: | ---: | ---: | ---: |
| **Shell / header** | 1 scope + 3 chrome aria-labels | 0 | 0 | **4** |
| **Intake idle** | 0 (uses `t()`) | **1** category line per case | complaint text, SHP IDs, cities | **1 pattern** |
| **Intake active-run** (`StageCard`) | **~42** labels/messages | **2** (`Category` value, precedent category) | actions, rationale, lane/label from SSE | **~44** |
| **Intake active-run** (`CaseFile`) | **6** titles/hints | 0 | node captions, graph counts | **6** |
| **Intake active-run** (`ShipmentMap`) | **5** legend/popup strings | 0 | coordinates, addresses | **5** |
| **Decisions** | **2** `pending` fragments | 0 (root causes OK) | action text, SHP IDs, cities | **2** |
| **Explore chrome** | 0 | 0 | — | **0** |
| **Graph / Schema** (`GraphView`) | **2** aria-labels | **10** entity legend labels + property keys via `humanizeKey` | node captions, property values | **12+** |
| **Theme / language menus** | 0 | 0 | `EN`/`AR` codes (optional) | **0** |

**Aggregate:** ~**70** user-visible English strings/gaps across active surfaces in AR mode (excluding chat/artifact modals outside nav scope).

---

## Browser evidence (EN + AR × Light + Dark)

### Build fingerprint

| Asset | Served |
| --- | --- |
| CSS | `index-DVhlRZ8U.css` ✓ |
| JS | `index-BVWhf3oi.js` ✓ |

### Screenshots

| File | Finding |
| --- | --- |
| `evidence/.../b4-intake-ar-light.png` | Arabic chrome; **English category tags** on every case card; English scope header |
| `evidence/.../b4-decisions-ar-light.png` | Fully translated dashboard; **root causes Arabic** via `rootCauseLabel()`; English scope header |
| `evidence/.../b4-schema-ar-light.png` | Arabic toggles; **English entity legend** (Policy, Shipment, …); English scope header |
| `evidence/.../b4-*-{en,ar}-{light,dark}.png` | Full 12-surface matrix |
| `evidence/.../b4-schema-ar-dark-after-toggle.png` | Canvas persists after lang+theme toggle |

### Layout constraints

| Check | Result |
| --- | --- |
| `document.documentElement.dir` | **`ltr`** in all 4 locale×theme combos |
| Sidebar position | **Left** (`sidebarLeft: 0`) |
| Language toggle | Does **not** remount view (`App.tsx` keys on `view` only) |
| Theme toggle on Schema | Canvas **persists** (`hasCanvas: true` before/after); surface token updates |

### B1 sentinels + B3 metrics (AR mode smoke)

| Check | AR result | Pass? |
| --- | --- | --- |
| H01 intake count contrast | light **5.62:1**, dark **8.23:1** | ✓ |
| H03 selected problem contrast | light **9.95:1**, dark **11.58:1** | ✓ |
| B3 progress segments | **31** `data-variant` incl. success/failure/pending | ✓ |
| B3 panel heights | Problems **440px**, queue **400px** | ✓ |
| AR count string | `75 شحنة بانتظار قرار` | ✓ (text present; plural grammar gap I04) |

Full matrix: `evidence/.../measurements-b4-audit.json`

---

## Intentional exceptions (do not translate)

| Item | Rationale |
| --- | --- |
| `SHP-*`, `FR-*`, resolution IDs | Technical identifiers; render `dir=ltr` |
| Customer complaint / case description text | Free-form evidence (already Arabic in dataset) |
| City, courier, action strings from API | Domain content, not UI chrome |
| Graph node **captions** (addresses, IDs) | Evidence values attached to entities |
| Property **values** in Graph detail panel | Data, not labels |
| `English` in language menu | Endonym for language picker |
| `EN` / `AR` toggle codes | Locale codes (optional localization) |
| OpenStreetMap attribution | Third-party license string |
| Backend SSE `stage.label`, `stage.lane` | Pipeline vocabulary from architecture diagram — **display-map candidate**, not raw preservation; currently English from server |

---

## B4 implementation allowlist

### In scope — frontend only

| File | Change |
| --- | --- |
| `frontend/src/i18n/en.ts` | Add keys: `scope`, `intake.stages.*`, `intake.caseFile.*`, `intake.map.*`, `entities.*`, `common.pending`, plural forms |
| `frontend/src/i18n/ar.ts` | Mirror all new keys |
| `frontend/src/components/i18n/LanguageProvider.tsx` | Add `entityLabel(label: string)` mirroring `rootCauseLabel` pattern for graph entities |
| `frontend/src/components/views/IntakeView.tsx` | Replace category `replace(/_/g,' ')` with `rootCauseLabel(c.category)` |
| `frontend/src/components/agent/StageCard.tsx` | `t()` for all field labels, status strings, AFL banner |
| `frontend/src/components/agent/CaseFile.tsx` | `t()` for panel titles/hints |
| `frontend/src/components/agent/ShipmentMap.tsx` | `t()` for legend, popup, empty state |
| `frontend/src/components/views/DecisionsView.tsx` | Replace hardcoded `pending` with `t('common.pending', { count })` |
| `frontend/src/components/artifacts/GraphView.tsx` | Legend + detail dt via `entityLabel()` / `propertyLabel()`; aria-labels via `t()` |
| `frontend/src/components/artifacts/BrainGraph.tsx` | Same legend/detail pattern as GraphView |
| `frontend/src/lib/humanizeKey.ts` | Route through dictionary or rename to `propertyLabel(key, t)` |
| `frontend/src/App.tsx` | `t('scope')` or map `/meta.scope` through dictionary |
| `frontend/src/components/layout/AppSidebar.tsx` | `t('common.application')` for favicon alt |

### Out of scope (unless coordinator grants)

| Path | Reason |
| --- | --- |
| `chat/**`, `backend/**` | Forbidden by run constraints |
| `/graph` backend fix | BLOCKED env; Schema proxy sufficient for I03 UI |
| Populating `/meta.labels` | Backend; frontend can ship static `entities.*` map as interim |

### Do not

- Introduce a second i18n library or parallel translation files
- Set `dir=rtl` globally or move sidebar
- Remount graphs on language change (`key={language}` anti-pattern)

---

## Regression tests to add (impl agent)

| Test | Assert |
| --- | --- |
| `LanguageProvider.test.tsx` | `rootCauseLabel('failed_attempt_barcode_mismatch')` → AR mapped string; escalation prefix |
| `IntakeView.test.tsx` (AR wrapper) | Case metadata shows Arabic root cause, not `recipient unavailable` |
| `StageCard.test.tsx` | Field labels use `t()` — no raw `Category`/`Verdict` in DOM when `language=ar` |
| `DecisionsView.test.tsx` | Pending fragment uses Arabic when `pending > 0` fixture |
| `GraphView.test.tsx` | Legend shows `entityLabel('Shipment')` not raw English when AR |
| Dictionary parity | Script or vitest: every `en.*` leaf has `ar.*` counterpart |
| `b4-audit-capture.mjs` (gate) | AR intake: zero raw category keys; schema legend zero `/^[A-Z]/` labels |
| B1/B3 smoke in AR | Reuse gate scripts with `localStorage agentx-language=ar` |

---

## Cross-batch status

| Batch | Status |
| --- | --- |
| B1 theme cascade | Sentinels **PASS** in AR smoke |
| B2 visualization lifecycle | Schema proxy OK; `/graph` **BLOCKED** |
| B3 metric semantics | Segments + heights **PASS** in AR smoke |
| B4 bilingual | **SCOPE_READY** — I01–I04 reproduced with evidence |

---

## Evidence paths

| Artifact | Path |
| --- | --- |
| Capture script | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-audit-capture.mjs` |
| Measurements JSON | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b4-audit.json` |
| Screenshots (12 + toggle) | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b4-*.png` |
| Dictionaries | `frontend/src/i18n/en.ts`, `frontend/src/i18n/ar.ts` |
| Issue register | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-issue-register.md` |
