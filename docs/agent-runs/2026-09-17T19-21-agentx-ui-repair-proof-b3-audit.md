# Batch 3 Audit — `metric-semantics-bounded-workspace`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT A (AUDIT)  
**Branch:** `fhd` (unchanged; no commits)  
**Candidate build:** `index-B9I8LKnG.css` / `index-276MDZLC.js` @ `http://127.0.0.1:8000`  
**Viewport:** 1440×900 desktop, locale EN  
**Date:** 2026-09-17

---

## Overall verdict: **SCOPE_READY**

Batch 3 metric-semantics and bounded-workspace repairs are **ready for implementation**. Panel height constants (`h-[440px]` trio, `h-[400px]` queue) are **correct in the served build** and must be preserved. Primary defect class is **M01** — all `Progress` bars use `bg-primary` with no outcome-based green/red/amber/neutral contract. **L02** (sticky headers ineffective inside `ScrollArea`) is a separate scroll UX gap. B1 sentinels and B2 schema proxy regressions: **no issues detected**.

**Coordinator permission needed** only if B3 impl wants to fix `/graph` 500 (`chat/view/subgraph.py`) for live E03/E04 re-verification — forbidden by default.

---

## Per-issue audit verdicts

| ID | Verdict | Notes |
| --- | --- | --- |
| **M01** | **REPRODUCED** | All 15 live + 51 overflow progress indicators share single `bg-primary` fill; no outcome semantics |
| **L01** | **NOT REPRODUCED** | Problems/Actions/Focus = **440px** equal; queue = **400px**; bounded heights present and correct |
| **L02** | **REPRODUCED** (discovered) | Queue `thead.sticky` scrolls away inside `ScrollArea` viewport — `position:sticky` set but does not pin |
| **L03** | **REPRODUCED** (discovered) | Focus panel inner matching-cases table has no sticky header (`position: static`) |
| **M02** | **REPRODUCED** (discovered) | 100% success bars visually identical to 80% bars — full primary fill conveys magnitude only, not outcome |
| **M03** | **REPRODUCED** (discovered) | Case coverage card uses single primary bar for resolved %; spec requires green=resolved / amber=open split |
| **M04** | **REPRODUCED** (discovered) | Closed-loop learning badge uses `text-chart-good` when `byAgent > 0`; learning counts should be neutral composition |
| **M05** | **REPRODUCED** (discovered) | KPI “Precedent available” always `tone="good"` regardless of resolved/open ratio |
| **D01** | **REPRODUCED** (discovered) | `writebacks.pending` returned by API (`cases.py` `_AGENT_WRITEBACKS`) but never surfaced in UI |
| **D02** | **NOT REPRODUCED** | KPI historical success rate matches API aggregate (90%) including `escalation:` categories hidden from Problems panel — consistent but potentially confusing; document only |
| **H01–H05** | **NOT REPRODUCED** | B1 regression clean @ 1440×900 |
| **H06** | **NOT REPRODUCED** | Escalations empty state visible; `Empty` renders |
| **E01–E02** | **NOT REPRODUCED** | Schema proxy controls readable |
| **E03–E04** | **BLOCKED** | `/graph` → 500 |

---

## Metric provenance table

Backend source: `chat/llm/pipeline/cases.py` → `GET /cases` → `DecisionsView` via `useFetch<CasesOverview>('/cases')`.

| UI surface | Display | API field(s) | Numerator / denominator | Zero vs missing |
| --- | --- | --- | --- | --- |
| **KPI: Open cases** | `coverage.unresolved` | `coverage.unresolved` | Unresolved failures (no `RESOLVES_WITH`) | 0 = no open cases (good tone) |
| **KPI: Precedent available** | `coverage.resolved` | `coverage.resolved` | Resolved failures | 0 possible; always `tone="good"` (M05) |
| **KPI: Historical success** | `overallRate%` | `by_category[].cases/succeeded` summed in FE | `sum(succeeded) / sum(cases) × 100` over **all** categories incl. `escalation:*` | 0 cases → 0% (not “unknown”) |
| **KPI: Waiting for human** | `openEscalations.length` | `escalations[]` where `status === 'open'` | Count of open escalations | 0 escalations → “nothing escalated” detail |
| **KPI: Written by agent** | `writebacks.by_agent` | `writebacks.by_agent` | Resolutions with `source='agent_pipeline'` | 0 → neutral tone; `pending` in API unused (D01) |
| **Case coverage card** | `resolved%` + counts | `coverage.resolved`, `coverage.unresolved` | `resolved / (resolved+open) × 100` | `total=0` → 0% bar |
| **Closed-loop learning** | `byAgent`, seeded line | `writebacks.by_agent`, `writebacks.seeded` | Agent vs seeded resolution counts | `byAgent=0` → secondary badge |
| **Problems `MetricRow`** | `success_rate%` bar | `by_category[]` (filtered: not `escalation:*`) | `succeeded / cases × 100` where `o.success IS NOT NULL` | Category omitted if no observed outcomes in graph |
| **Actions `MetricRow`** | `success_rate%` bar | `by_action[]` (top 8 by `used`) | `succeeded / used × 100` | Same — pending outcomes excluded server-side |
| **Focus: historical success** | `selectedCategory.success_rate` | Selected `by_category` row | Backend `success_rate` field | Rounded with `Math.round` |
| **Focus: open cases now** | `matchingOpenCases.length` | `queue[]` filtered by `category === selection.key` | Live unresolved queue subset | 0 → section hidden |
| **Queue table** | Row list | `queue[]` (up to 200 unresolved) | N/A — inventory, not a rate | Empty → “No results” |
| **Escalations table** | Row list | `escalations[]` (up to 100) | N/A | Empty → `Empty` component |

### Backend outcome semantics (authoritative)

From `cases.py` comments and Cypher:

- **`_BY_CATEGORY` / `_BY_ACTION`:** Only rows where `Outcome.success IS NOT NULL`. Pending outcomes (`success` null, status pending) are **excluded** — prevents agent self-confidence from inflating rates.
- **`_COVERAGE`:** Resolved = has `RESOLVES_WITH` edge; unresolved = no edge. Not delivery-success semantics.
- **`_AGENT_WRITEBACKS`:** Returns `by_agent`, `seeded`, **`pending`** (outcomes with `success IS NULL`), `total`. Frontend ignores `pending`.

### Live API snapshot (2026-09-17 audit)

| Metric | Value |
| --- | --- |
| Coverage | 165 resolved / 75 open / 240 total (69%) |
| Writebacks | 0 agent / 165 seeded / 0 pending |
| Queue | 75 rows |
| Escalations | 0 |
| Categories @ 100% | `failed_attempt_barcode_mismatch` (7/7), plus 4 `escalation:*` rows (hidden from Problems) |
| Categories @ 0% | `escalation:failed_attempt_weight_mismatch` (0/1) — hidden from Problems |
| Overall historical rate | 90% (FE computation matches API) |

---

## Semantic color contract — current vs required

| Context | Required (spec) | Current | Gap |
| --- | --- | --- | --- |
| Historical success bars (Problems/Actions) | GREEN success share, RED unsuccessful remainder (only with proof), NEUTRAL unknown | Single `bg-primary` fill proportional to rate | **M01, M02** — no red segment; 100% looks like 80% |
| Case coverage bar | GREEN resolved, AMBER open (not delivery success) | Single primary bar at resolved % | **M03** |
| Learning counts | Neutral composition styling | Green outline badge when `byAgent > 0` | **M04** |
| KPI icon tones | Outcome-aware where applicable | Heuristic warning/good on counts | **M05** (precedent always green) |
| Pipeline stages (Intake) | success green, rejection red, waiting amber, in-progress blue | `StageCard` `ScoreMeter` uses tone prop correctly | Out of B3 scope but reference pattern |
| Threshold coloring | No arbitrary “below 90% is bad” | Not used on bars | OK — magnitude-only bars are misleading for different reason |

`Progress` implementation (`frontend/src/components/ui/progress.tsx`):

```38:47:frontend/src/components/ui/progress.tsx
function ProgressIndicator({
  className,
  ...props
}: ProgressPrimitive.Indicator.Props) {
  return (
    <ProgressPrimitive.Indicator
      data-slot="progress-indicator"
      className={cn("h-full bg-primary transition-all", className)}
```

All consumers inherit primary blue — no semantic variant.

**Reference patterns in repo (for impl):**

- `StackedBar.tsx` — multi-segment with explicit `colorClass` per segment + legend
- `StageCard.tsx` `ScoreMeter` — `bg-chart-good` / `bg-chart-warning` / `bg-chart-blue` by tone
- `RankedBars.tsx` — single-hue magnitude (explicitly not outcome semantics)

---

## Panel measurement evidence

Measured @ 1440×900, Decisions view, live data. Corrected queue selector: `.h-[400px]` (initial script falsely matched Focus “open cases” copy).

| Panel | Outer height | Target | Scroll viewport (clientH) | scrollHeight | Overflow | Scroll-to-end |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Problems | **440** | ~440 | 351 | 429 | yes | ✅ last row visible |
| Actions | **440** | ~440 | 351 | 607 | yes | ✅ last row visible |
| Focus | **440** | ~440 | 343 | 561 | yes | ✅ last row visible |
| Queue | **400** | ~400 | 276 | 2511 | yes | ✅ row 75/75 visible |
| Escalations (empty) | 264 | min-content | — | — | — | N/A |

**Overflow fixture** (30 categories, 20 actions, 80 queue rows via `page.route` mock):

| Panel | Outer height | Overflow scroll | Scroll-to-end |
| --- | ---: | --- | --- |
| Problems | 440 | 2162 > 351 | ✅ |
| Actions | 440 | 1770 > 351 | ✅ |
| Focus | 440 | 343 = 343 (short selection) | ✅ |
| Queue | 400 | 2511 > 276 (live remeasure) | ✅ |

**L01 guardrail:** Constants `PANEL_HEIGHT = 'h-[440px]'`, `QUEUE_HEIGHT = 'h-[400px]'` in `DecisionsView.tsx:33-34`. Implementation must not collapse these when adding semantic bars.

---

## Sticky header / scroll ownership

| Table | Scroll owner | `sticky top-0` declared | Pins during inner scroll |
| --- | --- | --- | --- |
| Queue (main) | `ScrollArea` viewport | yes (`z-10 bg-card`) | **No** — header scrolls out (L02) |
| Escalations | `ScrollArea h-[280px]` | yes | Not tested (0 rows); same pattern likely broken |
| Focus matching-cases | Parent `ScrollArea` | no | N/A (L03) |

Sticky test evidence (`b3-sticky-scroll2.mjs`): after `scrollTop=400`, `theadTop` moved from 623.5 → 223.5 while `ScrollArea` viewport top stayed 623.5 — header not pinned.

**Root cause (observed):** `position: sticky` on `thead` inside Base UI `ScrollArea` viewport does not establish sticky containing block as expected; scroll ownership is the viewport wrapper, not the table.

---

## Browser evidence

### Build fingerprint

| Asset | Served |
| --- | --- |
| CSS | `index-B9I8LKnG.css` ✓ |
| JS | `index-276MDZLC.js` ✓ |

### Screenshots

| File | Content |
| --- | --- |
| `evidence/.../b3-decisions-light-default.png` | Decisions EN light — KPIs + panels |
| `evidence/.../b3-decisions-dark-default.png` | Decisions EN dark — selected problem row |
| `evidence/.../b3-decisions-overflow-scrolled.png` | Overflow fixture — Problems scrolled to end |
| `evidence/.../b3-escalations-empty-light.png` | Escalations empty state |

### Measurement artifacts

| File | Purpose |
| --- | --- |
| `evidence/.../measurements-b3-audit.json` | Full B3 matrix (note: queue height entry used wrong selector — corrected in this doc) |
| `evidence/.../b3-audit-capture.mjs` | Playwright capture script |
| `evidence/.../b3-queue-measure.mjs` | Corrected queue height + scroll reach |
| `evidence/.../b3-sticky-scroll2.mjs` | Sticky header failure proof |

### Progress bar color samples (light theme)

All indicators: `oklch(0.546 0.245 262.9)` (primary). Includes **100%** rows (`failed_attempt_barcode_mismatch`, `التنسيق بين فريق المستودع…`) — indistinguishable from 80% rows by color.

---

## B1 sentinel + B2 renderer regression

Re-ran via `b3-audit-capture.mjs` @ 1440×900 EN light+dark:

| Sentinel | Light | Dark | Verdict |
| --- | ---: | ---: | --- |
| H01 Intake count | 5.62:1 | 8.23:1 | NOT REPRODUCED |
| H02 Intake hover | 9.95:1 | 11.58:1 | NOT REPRODUCED |
| H03 Problem selected | 9.95:1 | 11.58:1 | NOT REPRODUCED |
| H04 Queue selected+hover | 9.95:1 | 11.58:1 | NOT REPRODUCED |
| E02 Schema Force selected | — | — | NOT REPRODUCED (oklch bg) |
| E03/E04 | — | — | BLOCKED (`/graph` 500) |

---

## Allowlist / forbidden paths for B3 implementation

### Allowlist

| Path | Purpose |
| --- | --- |
| `frontend/src/components/views/DecisionsView.tsx` | Metric rows, coverage/learning cards, panel constants |
| `frontend/src/components/ui/progress.tsx` | Semantic indicator variants (or parallel component) |
| `frontend/src/components/dashboard/StackedBar.tsx` | Reuse for coverage split bar |
| `frontend/src/components/dashboard/StatTile.tsx` | Optional KPI tone alignment |
| `frontend/src/index.css` | Chart semantic tokens if new variants needed |
| `frontend/src/components/views/DecisionsView.test.tsx` | **New** — panel heights, scroll, semantics |
| `frontend/src/types/agent.ts` | Only if typing `writebacks.pending` for display |
| `docs/agent-runs/**` | Evidence scripts + gate captures |

### Forbidden (unless coordinator grants permission)

| Path | Reason |
| --- | --- |
| `backend/**`, `chat/**` | Read-only audit constraint |
| `chat/view/subgraph.py` | `/graph` fix — NEEDS_PERMISSION |
| `frontend/dist/**` | Build output |
| `POST /complaint` | Mutation forbidden |
| B1/B2 unrelated views (`IntakeView`, `BrainGraph`, etc.) | Out of B3 slug scope |

### Pre-existing dirty (do not expand)

Per B1/B2 gates: `AppNav.tsx`, `TrustChip.tsx`, `Skeleton.tsx`, `Tooltip.tsx`, `vite.config.ts`, `tsconfig*.json`.

---

## Recommended implementation sequence

1. **Semantic `Progress` API** — add `variant` or `segments[]` supporting green/red/amber/neutral without changing track height.
2. **Case coverage card** — replace single bar with `StackedBar` or dual-segment bar (green resolved + amber open).
3. **MetricRow bars** — stacked success (green) + unsuccessful (red) from `succeeded`/`cases`; neutral when `cases === 0`; do not infer red from remainder without denominator proof.
4. **Learning card** — neutral badge styling; remove green “success” signaling for counts.
5. **KPI tones** — decouple from bar semantics where misleading (M05).
6. **Sticky headers (L02)** — move sticky to scroll viewport edge or replace `ScrollArea` with `overflow-auto` on queue body; verify header pins.
7. **Preserve `h-[440px]` / `h-[400px]`** — add regression tests before/after.
8. **Optional:** Surface `writebacks.pending` as amber-neutral count (D01) if product agrees.

---

## Regression tests to add (B3 gate)

| Test | Assertion |
| --- | --- |
| `DecisionsView.test.tsx` panel constants | Cards with Problems/Actions/Focus titles have `h-[440px]`; queue has `h-[400px]` |
| Semantic progress fixture | 100% row uses green indicator; 0% uses red or neutral; not all `bg-primary` |
| Coverage card | Two-tone or stacked segments; not single primary |
| Learning card | No `text-chart-good` badge class when `byAgent > 0` |
| Scroll fixture (RTL/jsdom or Playwright) | `scrollHeight > clientHeight` → scrollTop reaches end |
| Sticky header (Playwright) | Queue header `theadTop ≈ viewportTop` after inner scroll |
| Metric provenance unit | `overallRate` documents inclusion of `escalation:` categories |
| Overflow mock | 30+ categories still inside 440px card |

---

## Artifact paths

| Artifact | Path |
| --- | --- |
| Audit report | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b3-audit.md` |
| Issue register (updated) | `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-issue-register.md` |
| Measurements JSON | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b3-audit.json` |
| Capture script | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b3-audit-capture.mjs` |
| Queue measure | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b3-queue-measure.mjs` |
| Sticky proof | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b3-sticky-scroll2.mjs` |
| Screenshots | `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b3-decisions-*.png`, `b3-escalations-empty-light.png` |

---

## Return to coordinator

```
VERDICT: SCOPE_READY

M01: REPRODUCED
L01: NOT REPRODUCED (heights correct; guard tests required)
L02: REPRODUCED (sticky headers)
H01-H06: NOT REPRODUCED
E03/E04: BLOCKED

Allowlist: DecisionsView.tsx, progress.tsx, StackedBar.tsx, index.css, DecisionsView.test.tsx (new), docs/agent-runs/**
Forbidden: backend/**, chat/**, POST /complaint, dist/**, out-of-scope B1/B2 files
```
