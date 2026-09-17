# Batch 1 Review Handoff — `theme-cascade-hover-repair`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT C (REVIEW / FIX)  
**Branch:** `fhd` (unchanged; not committed)

---

## Executive summary

Verified implementation claims against source, built CSS, Vitest, and live Playwright measurements at `http://127.0.0.1:8000`. Agent B’s cascade/token fixes are **substantively correct** for H01–H03, H06, and the root CSS defect. Two issues required review fixes:

1. **E01 dark** — Explore lens label was **2.87:1** (BLOCKER); fixed by darkening `--primary` and setting `--primary-foreground: #ffffff`.
2. **H04** — Queue row `text-foreground` on cells blocked inheritance; selected+hover could lose accent bg. Fixed in `table.tsx` and `DecisionsView.tsx`.

Remaining gate blockers: **E02/E03/E04** still blocked by `GET /graph` → 500.

**Build fingerprint (post-review rebuild):** `index-B9I8LKnG.css` / `index-Cy1Gdul3.js`

---

## Verification methodology

| Layer | Action |
| --- | --- |
| Source | Read `index.css`, `IntakeView`, `DecisionsView`, `table.tsx`, `sidebar.tsx`, `ExploreView`, `BrainGraph`, tests |
| CSS guard | `built-css-guard.mjs` — PASS on post-review build |
| Tests | `npm run test` — 53/53 PASS; `npm run lint` — PASS (warnings only) |
| Browser | Playwright `review-capture.mjs` + targeted queue/sidebar probes with pointer hover |
| Contrast | Computed `color` / `backgroundColor` on painted elements; ratios ≥4.5:1 for normal text |

Evidence: `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-review.json`, `review-*.png`

---

## Findings by issue

### H01 — Light Intake metadata contrast

| Severity | **PASS** (was HIGH) |
| --- | --- |
| Impl claim | `text-muted` cascade fixed; Intake uses `text-muted-foreground` |
| Review evidence | Light count/metadata: `rgb(102,100,95)` on surface `rgb(250,249,247)` → **5.62:1**. Dark: **8.23:1** on `rgb(17,19,24)`. Built CSS: `.text-muted → --muted-foreground`; `.dark` after `:root`. |
| Gate | **PASS** — spot-check EN light/dark Intake default |

### H02 — Dark Intake hover background

| Severity | **PASS** (was HIGH) |
| --- | --- |
| Impl claim | Dark hover bg `#1e324a`, contrast 11.58:1 |
| Review evidence | Dark hover: `backgroundColor rgb(30,50,74)`, `color rgb(234,242,255)` → **11.58:1**. No `#e8f1fc` pale fill. Light hover **9.95:1**. Screenshots: `review-intake-{light,dark}-hover.png`. |
| Gate | **PASS** — confirm pointer hover in screenshots |

### H03 — Problems/Actions selected + hover

| Severity | **PASS** (was HIGH) |
| --- | --- |
| Impl claim | Selected states readable light/dark |
| Review evidence | Selected: light **9.95:1**, dark **11.58:1**. Selected+hover: same ratios (state stable). Unselected hover: light **14.55:1**, dark **13.02:1**. |
| Gate | **PASS** — re-verify selected+hover compound in Decisions |

### H04 — Queue cell inheritance

| Severity | **HIGH** → **FIXED** |
| --- | --- |
| Impl claim | `text-inherit` on selected cells |
| Review finding | Queue `TableCell` had `text-foreground` overriding row `text-accent-foreground` (light cells stayed `rgb(32,32,30)`). `hover:bg-muted` could override selected accent bg on hover. Initial capture script targeted wrong sub-table (matching-cases panel). |
| Fix applied | `table.tsx`: `data-[state=selected]:hover:bg-accent`, `!text-inherit`. `DecisionsView.tsx`: removed `text-foreground` from queue cells. |
| Post-fix evidence | Main queue selected row: light **9.95:1**, dark **11.58:1**; cells inherit `rgb(22,59,102)` / `rgb(234,242,255)`. |
| Gate | **PASS** — target bottom queue table, not detail-panel sub-table |

### H05 — Sidebar hover ≠ active

| Severity | **PASS** (was HIGH) |
| --- | --- |
| Impl claim | Hover=muted, active=accent+border |
| Review evidence | Inactive hover: muted `rgb(240,242,245)` / `rgb(36,43,53)`. Active (no hover): accent `rgb(232,241,252)` / `rgb(30,50,74)` + 2px primary border + `font-weight:500`. Icons/labels readable. |
| Caveat (MEDIUM) | **Active+hover** reverts to muted bg (`hover:bg-muted` wins over `data-active:bg-sidebar-accent`). Border + font-weight remain. Not fixed — below HIGH threshold. |
| Gate | **PASS** — compare inactive hover vs active default; note active+hover caveat |

### H06 — Escalations empty icon

| Severity | **PASS** |
| --- | --- |
| Impl claim | Not tested; `EmptyMedia` uses `bg-muted` |
| Review evidence | Scrolled to escalations empty card. Icon well: light **5.27:1** (`bg-muted` `rgb(240,242,245)`), dark **6.32:1** (`rgb(36,43,53)`). No light chip in dark. Screenshots: `review-escalations-{light,dark}-empty.png`. |
| Gate | **PASS** |

### E01 — Explore lens selected control

| Severity | **BLOCKER (dark)** → **FIXED** |
| --- | --- |
| Impl claim | Light fixed; dark **2.87:1** marginal |
| Review evidence | Pre-fix dark: `rgb(234,242,255)` on `rgb(91,141,239)` → **2.87:1** FAIL. Light: white on brand blue (oklch) — passes visually; script can't parse oklch. |
| Fix applied | `index.css` dark: `--primary: #3b6fd4`, `--primary-foreground: #ffffff` → post-fix **4.76:1**. |
| Gate | **PASS** — re-measure dark Explore lens label on `rgb(59,111,212)` pill |

### E02 — Graph controls (Force/Tree, 2D/3D)

| Severity | **BLOCKED** |
| --- | --- |
| Review | `/graph` still 500; controls not rendered. Code uses same `bg-primary` token (now fixed). |
| Gate | **BLOCKED** — restore graph endpoint, then verify selected toggles |

### E03 — BrainGraph theme memoization

| Severity | **CODE PASS / LIVE BLOCKED** |
| --- | --- |
| Review | `useMemo(..., [resolvedTheme])` confirmed in `BrainGraph.tsx`. |
| Test gap (MEDIUM) | `BrainView.test.tsx` only tests resample fetch; **no theme-toggle / CSS-var assertion** as impl report implied. |
| Gate | **BLOCKED** for live — code review PASS; live 3D toggle after `/graph` fix |

### E04 — Graph chrome (legend, tooltip, NVL)

| Severity | **BLOCKED** |
| --- | --- |
| Review | Graph empty; not auditable. |
| Gate | **BLOCKED** |

---

## Additional findings

### Scope compliance (MEDIUM)

Working tree contains edits **outside** Batch 1 allowlist (e.g. `AppNav.tsx`, `TrustChip.tsx`, `Skeleton.tsx`, `Tooltip.tsx`, `vite.config.ts`, `package.json`). Review did not modify these. Gate should confirm no unintended regressions in chat/dashboard.

### Test validity (MEDIUM)

| Test | Issue |
| --- | --- |
| `IntakeView.test.tsx` | Asserts class names only (`text-muted-foreground`, `hover:bg-accent`); does not measure computed contrast. |
| `BrainView.test.tsx` | No theme-toggle regression guard for E03. |
| `after-capture.mjs` | Dark H01 ratio used hardcoded light surface; queue selector hits wrong table. |

### CSS / cascade (LOW)

- `BrainGraph` lint: `resolvedTheme` flagged as unnecessary dep (intentional for E03).
- Impl after-screenshots (`*-after.png`) were not present in evidence dir at review time; review generated `review-*.png`.

---

## Fixes applied (Agent C)

| File | Change |
| --- | --- |
| `frontend/src/index.css` | Dark `--primary: #3b6fd4`, `--primary-foreground: #ffffff` (E01 WCAG) |
| `frontend/src/components/ui/table.tsx` | Selected+hover keeps accent bg; `!text-inherit` on cells |
| `frontend/src/components/views/DecisionsView.tsx` | Removed `text-foreground` from queue `TableCell` classes |

**Rebuild:** `npm run build` → `index-B9I8LKnG.css`  
**Tests:** 53/53 PASS, lint PASS, CSS guard PASS

---

## Gate recommendations

| Issue | Recommendation | Gate must re-test |
| --- | --- | --- |
| H01 | **PASS** | EN × light/dark Intake metadata contrast |
| H02 | **PASS** | Dark intake hover with pointer active |
| H03 | **PASS** | Problem selected, hover, selected+hover both themes |
| H04 | **PASS** (after C fix) | Bottom queue table selected + selected+hover |
| H05 | **PASS** | Sidebar inactive-hover vs active-default; note active+hover caveat |
| H06 | **PASS** | Escalations empty icon scrolled into view |
| E01 | **PASS** (after C fix) | Dark Explore lens ≥4.5:1 on painted pill |
| E02 | **BLOCKED** | Graph controls when `/graph` healthy |
| E03 | **BLOCKED** (live) / code **PASS** | 3D background after theme toggle without reload |
| E04 | **BLOCKED** | Legend/tooltip/NVL colors with graph data |

**Overall gate posture:** **CONDITIONAL PASS** for in-scope UI theme/hover repair (H01–H06, E01 light+dark). **FAIL/BLOCKED** until `/graph` restored for E02–E04 live proof.

---

## Artifact index

```
docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b1-review.md  (this file)
docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/
  measurements-review.json
  review-capture.mjs
  review-intake-{light,dark}-hover.png
  review-decisions-{light,dark}-queue-selected-hover.png
  review-sidebar-{light,dark}-hover.png
  review-escalations-{light,dark}-empty.png
  review-explore-{light,dark}-lens.png
```

---

## Coordinator payload

```yaml
RUN_ID: 2026-09-17T19-21-agentx-ui-repair-proof
AGENT: C (REVIEW)
VERDICT: REVIEW_COMPLETE_WITH_FIXES
BUILD_CSS: index-B9I8LKnG.css
BUILD_JS: index-Cy1Gdul3.js
TESTS: PASS (53/53)
FIXES_APPLIED: [index.css E01 dark, table.tsx H04, DecisionsView.tsx H04]
BLOCKERS_REMAINING:
  - GET /graph 500 (E02/E03/E04 live)
GATE_H01_H06_E01: PASS
GATE_E02_E04: BLOCKED
NEXT_AGENT: Agent D (Validation Gate)
```
