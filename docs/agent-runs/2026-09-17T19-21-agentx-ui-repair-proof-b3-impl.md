# Batch 3 Implementation — `metric-semantics-bounded-workspace`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT B (IMPLEMENTATION)  
**Branch:** `fhd` (unchanged; no commits)  
**Date:** 2026-09-17

---

## Summary

Implemented semantic outcome coloring for all Decisions metric bars, fixed queue/focus sticky headers by correcting scroll ownership, surfaced `writebacks.pending` when present, and added regression tests. Panel height constants (`h-[440px]` trio, `h-[400px]` queue) preserved.

**Post-build fingerprint:** `index-DVhlRZ8U.css` / `index-BVWhf3oi.js` @ `http://127.0.0.1:8000`

---

## Files changed

| File | Change |
| --- | --- |
| `frontend/src/index.css` | Added `--color-outcome-success/failure/pending/neutral` tokens (light + dark) |
| `frontend/src/components/ui/progress.tsx` | `OutcomeVariant` type, semantic `ProgressIndicator` variant, new `SegmentedProgress` component |
| `frontend/src/components/ui/table.tsx` | `bare` prop to skip `overflow-x-auto` wrapper (fixes sticky inside scroll containers) |
| `frontend/src/components/views/DecisionsView.tsx` | Semantic bars, KPI tone fixes, pending display, queue/escalations `overflow-auto`, focus sticky header |
| `frontend/src/types/agent.ts` | Added `writebacks.pending` to `CasesOverview` type |
| `frontend/src/components/views/DecisionsView.test.tsx` | **New** — 9 tests for heights, semantics, scroll structure |
| `docs/agent-runs/evidence/.../b3-after-capture.mjs` | Post-impl Playwright capture script |
| `docs/agent-runs/evidence/.../measurements-b3-after.json` | Post-impl measurements |
| `docs/agent-runs/evidence/.../b3-decisions-light-after.png` | Post-impl screenshot |

---

## Metric mapping table

| UI surface | Segments | Variant mapping | Data source |
| --- | --- | --- | --- |
| **Problems `MetricRow`** | success + failure | GREEN `succeeded`, RED `cases − succeeded` | `by_category[]` (escalation:* filtered) |
| **Actions `MetricRow`** | success + failure | GREEN `succeeded`, RED `used − succeeded` | `by_action[]` |
| **Case coverage card** | success + pending | GREEN `resolved`, AMBER `open` | `coverage.resolved`, `coverage.unresolved` |
| **100% success row** | success only | Full green bar (no red segment) | `succeeded === cases` |
| **0% success row** | failure only | Full red bar | `succeeded === 0`, `cases > 0` |
| **Empty denominator** | neutral | Single neutral track fill | `cases === 0` |
| **Closed-loop learning badge** | — | Neutral outline (`text-muted-foreground`) | `writebacks.by_agent` count |
| **Pending writebacks (D01)** | — | Amber text when `pending > 0` | `writebacks.pending` |
| **KPI: Precedent available (M05)** | — | `good` only when resolved > 0 && open === 0; `warning` when open > 0 | `coverage.*` |
| **KPI: Written by agent** | — | Neutral default (removed false-green tone) | `writebacks.by_agent` |

**Not changed:** aggregate calculations, API contracts, backend queries.

---

## Issue resolution

| ID | Status | Implementation |
| --- | --- | --- |
| **M01** | Fixed | `SegmentedProgress` with outcome variants replaces single `bg-primary` bars |
| **M02** | Fixed | 100% rows render single green segment; partial rows show green + red split |
| **M03** | Fixed | Coverage card uses green resolved + amber open segments |
| **M04** | Fixed | Learning badge uses neutral outline styling |
| **M05** | Fixed | Precedent KPI tone reflects resolved/open ratio |
| **D01** | Fixed | `pending` surfaced in learning card + agent KPI detail when > 0 |
| **L02** | Fixed | Queue uses `overflow-auto` + `Table bare`; sticky header pins (`headerPinned: true`) |
| **L03** | Fixed | Focus matching-cases `TableHeader` has `sticky top-0` |
| **L01** | Preserved | Heights unchanged: Problems/Actions/Focus 440px, queue 400px |

---

## Test results

```
cd frontend && npm run test   → 67 passed (19 files), incl. 9 new DecisionsView tests
cd frontend && npm run lint → pass (pre-existing warnings only)
cd frontend && npm run build → pass
```

### New test coverage (`DecisionsView.test.tsx`)

- Panel height constants (`h-[440px]` × 3, `h-[400px]` queue)
- Segmented progress with success/failure/pending variants (no `bg-primary` indicators)
- 100% vs partial success bar differentiation
- Coverage two-tone split
- Neutral learning badge (no `text-chart-good`)
- Pending writeback display
- Overall rate includes escalation categories (91% fixture)
- Queue `overflow-auto` scroll owner (no ScrollArea)
- Sticky headers on queue + focus tables

---

## B1 sentinel status (post-impl)

Re-ran via `b3-after-capture.mjs` @ 1440×900:

| Sentinel | Light | Dark | Verdict |
| --- | ---: | ---: | --- |
| H01 Intake count | 5.62:1 | 8.23:1 | NOT REPRODUCED |
| H03 Problem selected | 9.95:1 | 11.58:1 | NOT REPRODUCED |
| H04 Queue hover | — | — | Not measured (selector); no contrast regression observed in code |

Problems/Actions selected-row tokens (`bg-accent text-accent-foreground`) unchanged — B1 contrast preserved.

---

## Browser evidence

| Artifact | Path |
| --- | --- |
| Screenshot (light) | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b3-decisions-light-after.png` |
| Measurements JSON | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b3-after.json` |
| Capture script | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b3-after-capture.mjs` |

### Key measurements (live @ 1440×900)

| Check | Result |
| --- | --- |
| Panel heights | Problems 440, Actions 440, Focus 440, Queue 400 |
| Semantic segments | 28 segments; variants: success, pending, failure; `primaryOnly: 0` |
| Queue sticky header | `headerPinned: true` after `scrollTop=400` |
| Focus sticky header | `position: sticky` |

---

## Handoff for Review

1. **Visual review** — Confirm green/red/amber/neutral semantics match product intent on live data (especially 100% vs 80% rows and coverage split).
2. **Sticky headers** — Scroll queue and focus matching-cases panels; verify headers pin in both light and dark themes.
3. **Pending display** — Live data has `pending: 0`; verify amber pending text when API returns non-zero (or use mock).
4. **Arabic locale** — Pending strings are inline English (`"pending"`); consider i18n keys in a follow-up (outside B3 allowlist).
5. **No commit** — Changes are unstaged per gate instructions.

```
VERDICT: IMPLEMENTATION_COMPLETE

M01-M05: FIXED
D01: FIXED
L02-L03: FIXED
L01: PRESERVED
B1 H01/H03: NOT REPRODUCED

Build: index-DVhlRZ8U.css / index-BVWhf3oi.js
Tests: 67/67 pass
```
