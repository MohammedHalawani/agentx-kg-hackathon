# Batch 3 Review — `metric-semantics-bounded-workspace`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT C (REVIEW / FIX)  
**Branch:** `fhd` (unchanged; no commits)  
**Candidate build:** `index-DVhlRZ8U.css` / `index-BVWhf3oi.js` @ `http://127.0.0.1:8000`  
**Viewport:** 1440×900 desktop, locale EN  
**Date:** 2026-09-17

---

## Overall verdict: **PASS**

Independent verification confirms B3 implementation claims. Semantic outcome coloring is live and distinct from `bg-primary`. Panel heights preserved. Queue sticky header pins after scroll. Focus matching-cases sticky header pins inside `ScrollArea` viewport. KPI tones and coverage counts match `GET /cases`. No BLOCKER or HIGH defects found; no in-scope fixes applied.

---

## Per-issue review verdicts

| ID | Impl claim | Review verdict | Evidence |
| --- | --- | --- | --- |
| **M01** | Semantic green/red/amber/neutral segments | **VERIFIED** | 28 segments; variants `success`, `pending`, `failure`; `primaryOnly: 0` |
| **M02** | 100% vs 80% visually distinct | **VERIFIED** | 100% rows: single `success` segment; partial rows: `success` + `failure` |
| **M03** | Coverage green resolved + amber open | **VERIFIED** | UI 165 resolved / 75 open matches API; two-tone bar (`success` + `pending`) |
| **M04** | Learning neutral badge | **VERIFIED** | Badge `text-muted-foreground` / `variant="secondary"`; no `text-chart-good` |
| **M05** | KPI truthful tone | **VERIFIED** | Precedent KPI `warning` when open > 0; Written-by-agent neutral (`text-primary`) |
| **D01** | Pending writebacks amber when > 0 | **PARTIAL** | Live API `pending: 0` — amber path not live-visible; unit test passes |
| **L01** | Heights 440/440/440/400 preserved | **VERIFIED** | Problems 440, Actions 440, Focus 440, Queue 400 |
| **L02** | Queue sticky header pins | **VERIFIED** | `headerPinned: true` after `scrollTop=400`; scroll owner `overflow-auto` |
| **L03** | Focus matching-cases sticky header | **VERIFIED** | `headerPinned: true` after scroll to end; `position: sticky` |
| **B1 H03** | Problem selected contrast | **VERIFIED** | Light 9.95:1, dark 11.58:1 |
| **B1 H04** | Queue row contrast | **VERIFIED** | Light 14.55:1, dark 13.02:1 (hover state) |

---

## Build & test gate

| Check | Result |
| --- | --- |
| `npm run test` | **67/67 passed** (19 files, incl. 9 DecisionsView tests) |
| `npm run lint` | **Pass** (pre-existing warnings only) |
| `npm run build` | **Pass** — fingerprint `index-DVhlRZ8U.css` / `index-BVWhf3oi.js` |
| Build served @ :8000 | **Match** — same CSS/JS hashes |

---

## API ↔ UI metric comparison

Source: `GET /cases` vs live Decisions view @ 1440×900 EN light.

| Metric | API | UI | Match |
| --- | ---: | ---: | --- |
| Coverage resolved | 165 | 165 | ✅ |
| Coverage open | 75 | 75 | ✅ |
| Coverage % | 69% | 69% | ✅ |
| Historical success rate | 90% (149/165 incl. escalation:*) | 90% | ✅ |
| Queue rows | 75 | 75 | ✅ |
| Writebacks by_agent | 0 | 0 | ✅ |
| Writebacks pending | 0 | (hidden) | ✅ expected |
| Writebacks seeded | 165 | — | N/A (footer text) |

**Calculation integrity:** `overallRate` still sums all `by_category` rows including `escalation:*` (90% = 149/165). Problems panel still filters `escalation:*` from display only — unchanged from audit.

**KPI tone mapping (live):**

| KPI | Expected | Observed |
| --- | --- | --- |
| Open cases (75) | warning | `text-chart-warning` ✅ |
| Precedent (165, open > 0) | warning | `text-chart-warning` ✅ |
| Written by agent (0) | neutral/default | `text-primary` ✅ |

---

## Semantic color verification (M01–M03)

### Segment inventory (live)

| Property | Value |
| --- | --- |
| Total segments | 28 |
| Variants present | `success`, `pending`, `failure` |
| `bg-primary` indicators | 0 |

### Computed colors (light theme sample)

| Variant | Computed `background-color` |
| --- | --- |
| success | `rgb(12, 163, 12)` |
| pending | `rgb(250, 178, 25)` |
| failure | `oklch(0.58 0.19 25)` |

### M02 differentiation

| Row type | Segments | Example |
| --- | --- | --- |
| 100% success | 1 × `success` | `failed_attempt_barcode_mismatch` |
| Partial success | `success` + `failure` | 91%, 90%, 80% rows |

### M03 coverage split

`CaseCoverageCard` renders `SegmentedProgress` with `{ resolved: success, open: pending }` — not a single primary fill.

### Selected/hover surfaces

Semantic segment classes (`bg-outcome-*`) remain on `MetricRow` buttons in both default and selected (`bg-accent`) states. B1 H03 selected-row contrast preserved (9.95:1 light).

### Accessibility

`SegmentedProgress` exposes `role="img"` with `aria-label` describing segment values/variants. Empty denominator uses `aria-label="No data"`.

---

## Layout verification (L01–L03)

### Panel heights (L01)

| Panel | Measured | Target |
| --- | ---: | ---: |
| Problems | 440 | 440 |
| Resolution actions | 440 | 440 |
| Focus | 440 | 440 |
| Queue | 400 | 400 |

Constants `PANEL_HEIGHT` / `QUEUE_HEIGHT` unchanged in `DecisionsView.tsx:33-34`.

### Queue scroll reach

| Property | Value |
| --- | --- |
| Row count | 75 |
| `scrollHeight` | 2511 |
| `clientHeight` | 276 |
| Last row visible after scroll-to-end | ✅ (`FR-fcc7dcdf17` / SHP-0178) |

### Queue sticky header (L02)

| Check | Before scroll | After `scrollTop=400` |
| --- | --- | --- |
| Viewport top | 996.5 | 996.5 |
| `thead` top | 996.5 | 996.5 |
| `headerPinned` | — | **true** |

Scroll owner: `.overflow-auto` (not `ScrollArea`). `Table bare` removes `overflow-x-auto` wrapper.

### Focus sticky header (L03)

| Check | Before scroll | After scroll-to-end |
| --- | --- | --- |
| Viewport top | 501.5 | 501.5 |
| `thead` top | 682.5 | 501.5 |
| `headerPinned` | — | **true** |

Scroll owner: `scroll-area-viewport` with `Table bare`. Sticky pins correctly when inner content scrolls past header — prior audit failure was likely compounded by non-bare table wrapper on queue; focus panel benefits from `bare` + sticky class.

---

## Scope & regression checks

### `table.tsx` `bare` prop

- Default `bare=false` — all other tables retain `overflow-x-auto` wrapper.
- `bare` used only in `DecisionsView.tsx` (queue, focus matching-cases, escalations).
- No regressions detected in other table consumers.

### Files reviewed (allowlist)

| File | Review notes |
| --- | --- |
| `DecisionsView.tsx` | Semantic bars, KPI tones, pending display, scroll ownership |
| `progress.tsx` | `OutcomeVariant`, `SegmentedProgress`, aria labels |
| `table.tsx` | `bare` prop — minimal, backward-compatible |
| `index.css` | Outcome tokens map to chart-good/danger/warning/neutral |
| `agent.ts` | `writebacks.pending` typed |
| `DecisionsView.test.tsx` | 9 regression tests — all pass |

### Metric calculations

No changes to numerators/denominators or API field usage. Presentation-only delta confirmed.

---

## B1 sentinel re-check

| Sentinel | Light | Dark | Threshold | Verdict |
| --- | ---: | ---: | ---: | --- |
| H03 Problem selected | 9.95:1 | 11.58:1 | ≥4.5:1 | PASS |
| H04 Queue hover | 14.55:1 | 13.02:1 | ≥4.5:1 | PASS |

Selected-row tokens (`bg-accent text-accent-foreground`) unchanged from B1.

---

## Fixes applied

**None.** No BLOCKER or HIGH defects found in allowlist scope.

---

## Residual notes (non-blocking)

| Note | Severity | Detail |
| --- | --- | --- |
| D01 live pending | LOW | API returns `pending: 0`; amber pending text verified via unit test only |
| D01 i18n | LOW | `"pending"` string inline English in learning card + KPI detail |
| Focus sticky scroll owner | INFO | Uses `ScrollArea` viewport (not `overflow-auto` like queue); pins correctly with `bare` table |
| H04 selector | INFO | Review measured hover, not selected+hover combo; ratios well above threshold |

---

## Artifact paths

| Artifact | Path |
| --- | --- |
| Review report | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b3-review.md` |
| Measurements JSON | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b3-review.json` |
| Capture script | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b3-review-capture.mjs` |
| Screenshot | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b3-decisions-light-review.png` |
| Prior impl evidence | `docs/agent-runs/evidence/.../measurements-b3-after.json` |

---

## Return to coordinator

```
VERDICT: PASS

M01-M05: VERIFIED
D01: PARTIAL (unit test only; live pending=0)
L01-L03: VERIFIED
B1 H03/H04: VERIFIED

Tests: 67/67 pass
Build: index-DVhlRZ8U.css / index-BVWhf3oi.js
Fixes applied: none
Commit: not performed (per gate)
```
