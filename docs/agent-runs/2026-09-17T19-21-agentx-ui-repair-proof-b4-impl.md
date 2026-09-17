# Batch 4 Implementation — `bilingual-ui-domain-display`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT B (IMPLEMENTATION)  
**Branch:** `fhd` (unchanged; **no commit**)  
**Date:** 2026-09-17

---

## Summary

Extended the existing `LanguageProvider` / `t()` / `rootCauseLabel()` system to cover ~70 user-visible English gaps identified in the B4 audit (I01–I04). Added `entityLabel()` and `propertyLabel()` for graph/schema vocabulary. All changes are frontend-only under the allowlist; `dir=ltr` and left sidebar preserved; no `key={language}` remounts.

---

## Issue resolution

| ID | Status | Implementation |
| --- | --- | --- |
| **I01** | **FIXED** | Shell scope via `t('scope')`; sidebar favicon alt + sidebar trigger aria/title; `StageCard`, `CaseFile`, `ShipmentMap` wired to `t()`; GraphView/BrainGraph close aria-label |
| **I02** | **FIXED** | `IntakeView` idle metadata uses `rootCauseLabel(c.category)` |
| **I03** | **FIXED** | `entityLabel()` on GraphView/BrainGraph legend + node-type headers; `propertyLabel()` on detail `dt` keys |
| **I04** | **FIXED** | StageCard field labels, verdict badges, AFL banner; Decisions pending via `t('common.pending')`; count-neutral `intake.awaiting` and `decisions.kpi.teamsDetail` |

---

## Files changed

| File | Change |
| --- | --- |
| `frontend/src/i18n/en.ts` | +`scope`, `common.*`, `intake.stages.*`, `intake.caseFile.*`, `intake.map.*`, `entities.*`, `properties.*`; count-neutral awaiting/teams |
| `frontend/src/i18n/ar.ts` | Mirror all new keys; layout labels per spec (تخطيط بالقوى, ثنائي الأبعاد, …) |
| `frontend/src/components/i18n/LanguageProvider.tsx` | +`entityLabel()`, +`propertyLabel()` |
| `frontend/src/components/views/IntakeView.tsx` | `rootCauseLabel()` on idle case cards |
| `frontend/src/components/agent/StageCard.tsx` | Full `t()` + `rootCauseLabel()` for stage bodies, AFL divider |
| `frontend/src/components/agent/CaseFile.tsx` | Panel titles/hints via `t()` |
| `frontend/src/components/agent/ShipmentMap.tsx` | Legend, popup, empty state via `t()` |
| `frontend/src/components/views/DecisionsView.tsx` | Pending fragments → `t('common.pending', { count })` |
| `frontend/src/components/artifacts/GraphView.tsx` | Legend/detail via display maps; close aria-label |
| `frontend/src/components/artifacts/BrainGraph.tsx` | Same as GraphView; layout toggle via `t()` |
| `frontend/src/components/layout/AppHeader.tsx` | `t('scope')`; translated sidebar trigger |
| `frontend/src/components/layout/AppSidebar.tsx` | `t('common.application')` favicon alt |
| `frontend/src/components/i18n/LanguageProvider.test.tsx` | **new** — rootCause/entity/property maps |
| `frontend/src/i18n/parity.test.ts` | **new** — EN↔AR leaf key parity |
| `frontend/src/components/agent/StageCard.test.tsx` | **new** — AR field labels |
| `frontend/src/components/artifacts/GraphView.test.tsx` | **new** — AR legend entities |
| `frontend/src/components/views/IntakeView.test.tsx` | +AR root cause on idle cards |
| `frontend/src/components/views/DecisionsView.test.tsx` | +AR pending fragment |
| `frontend/src/components/artifacts/BrainGraph.test.tsx` | Wrap with `LanguageProvider` |
| `docs/agent-runs/evidence/.../b4-impl-capture.mjs` | **new** — after screenshots script |
| `docs/agent-runs/evidence/.../b4-*-after.png` | AR light captures (intake, decisions, schema) |

---

## Translation inventory (new keys)

### Shell / common
- `scope`, `common.close`, `common.application`, `common.toggleSidebar`, `common.pending`

### Intake pipeline (`intake.stages.*`)
- Extract, retrieve, classify, recommend, review, writeback field labels
- AFL retry + divider copy
- `intake.caseFile.*` — case file panel titles/hints
- `intake.map.*` — map legend, popup roles, empty/approximate

### Graph vocabulary
- `entities.*` — Policy, Order, Address, Customer, Outcome, FailureReason, Shipment, Event, Courier, Resolution, Node
- `properties.*` — municipality_id, incident_key, first_seen, name, tracking_id, city, district, category, priority, confidence, action, success, score, image_path, lat, lon

### Count-neutral phrasing (I04)
| Key | EN | AR |
| --- | --- | --- |
| `intake.awaiting` | `Awaiting decision — {count}` | `بانتظار قرار — {count}` |
| `decisions.kpi.teamsDetail` | `Across {count} teams` | `عدد الفرق: {count}` |
| `common.pending` | `{count} pending` | `{count} معلّق` |

---

## Intentional exceptions (preserved)

| Item | Rationale |
| --- | --- |
| `SHP-*`, `FR-*`, resolution IDs | Technical identifiers; `dir=ltr` where shown |
| Complaint text, cities, couriers, actions from API | Domain content / evidence |
| Graph node captions, property values | Data, not UI labels |
| `English` endonym, `EN`/`AR` codes | Language picker convention |
| OpenStreetMap attribution | Third-party license |
| Backend `stage.label`, `stage.lane` | Pipeline vocabulary from SSE (not translated in this batch) |
| `ui/sidebar.tsx` internal sr-only “Toggle Sidebar” | Out of allowlist; overridden via `aria-label` on trigger in AppHeader |

---

## Test results

```text
npm run test   → 23 files, 74 tests PASS
npm run lint   → 0 errors (pre-existing warnings only)
npm run build  → PASS
```

### New / updated regression tests
- `LanguageProvider.test.tsx` — `rootCauseLabel`, `entityLabel`, `propertyLabel` EN+AR
- `parity.test.ts` — dictionary leaf parity
- `StageCard.test.tsx` — no raw `Category`/`Verdict` in AR DOM
- `IntakeView.test.tsx` — Arabic root cause on idle cards (not `address conflict`)
- `DecisionsView.test.tsx` — Arabic pending in learning card
- `GraphView.test.tsx` — legend shows `الشحنة` not `Shipment`

B1 sentinels (H01/H02) and B3 metrics (M01 panel heights, segmented bars) remain covered by existing IntakeView/DecisionsView tests; all pass after B4 changes.

---

## Build fingerprint

| Asset | Before (audit) | After (impl) |
| --- | --- | --- |
| CSS | `index-DVhlRZ8U.css` | `index-DVhlRZ8U.css` ✓ (unchanged) |
| JS | `index-BVWhf3oi.js` | `index-DE557tU5.js` (new hash — i18n bundle growth) |

Served from `http://127.0.0.1:8000` after `npm run build`.

---

## Browser evidence (AR after)

| Screenshot | Path |
| --- | --- |
| Intake idle | `evidence/.../b4-intake-ar-light-after.png` |
| Decisions | `evidence/.../b4-decisions-ar-light-after.png` |
| Schema | `evidence/.../b4-schema-ar-light-after.png` |

Capture script: `evidence/.../b4-impl-capture.mjs`

---

## Handoff for Review (AGENT C)

1. **Verify AR surfaces** — intake idle categories Arabic; schema legend entities Arabic; scope header Arabic; no English `Category`/`Verdict`/`pending` in active-run/decisions chrome.
2. **Layout constraints** — confirm `dir=ltr`, sidebar left, no graph remount on language toggle (Schema canvas persistence).
3. **Regression** — re-run B1 contrast sentinels + B3 metric smoke in AR (`measurements-b4-audit.json` gate scripts).
4. **Known unchanged** — `/graph` backend 500 (B2 blocker); Toggle Sidebar sr-only span in `ui/sidebar.tsx` still English internally (aria-label overridden).
5. **No commit** — coordinator merges when Review passes.

---

## Cross-batch status

| Batch | Post-B4 |
| --- | --- |
| B1 theme cascade | Sentinels pass in test suite |
| B2 visualization | Schema OK; `/graph` still BLOCKED (backend) |
| B3 metrics | Panel heights + segments pass |
| B4 bilingual | **IMPLEMENTED** — ready for Review |
