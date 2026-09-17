# Issue Register — Batch 1 `theme-cascade-hover-repair`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**APP_URL:** `http://127.0.0.1:8000` @ build `index-6fyoBKuw.css` / `index-Ca8GudiR.js`  
**Viewport:** 1440×900 desktop, locale EN

Legend: **REPRODUCED** = confirmed in served build with computed-style and/or screenshot evidence.

---

## H01 — Light Intake count, explanation, and case metadata unreadable

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `IntakeView` — `text-muted` on count (`span.text-sm.text-muted`), description (`p.text-muted`), case metadata (`span.text-muted` inside case buttons) |
| **Evidence** | `intake-light-default.png`; `measurements.json` → `color: rgb(236, 234, 229)` (= `#eceae5`) |
| **Root cause (observed)** | Built CSS defines `.text-muted { color: var(--muted) }` — uses **muted surface token** (`#eceae5`), not `--muted-foreground` (`#66645f`). Contrast vs surface `#faf9f7` ≈ **1.14:1**. |
| **Source intent vs build** | `frontend/src/index.css` has `@utility text-muted { color: var(--muted-foreground) }` but **shadcn/Tailwind output wins** in `dist/assets/index-6fyoBKuw.css`. |
| **Hypothesis** | `@import "shadcn/tailwind.css"` generates `text-muted` after or with higher precedence than custom `@utility`; legacy Intake markup still uses `text-muted` (9 occurrences in `IntakeView.tsx`). |

---

## H02 — Dark Intake hover produces pale background under light text

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | Intake case list buttons: `hover:bg-accent` with persistent `text-ink` / child `text-muted` |
| **Evidence** | `intake-dark-hover.png`; `measurements.json` dark `intake-hover-contrast` → **ratio 1.02** (`bg: rgb(232,241,252)`, `color: rgb(240,242,245)`) |
| **Root cause (observed)** | In dark mode, hover background resolves to **light-mode accent** `#e8f1fc` instead of `.dark { --accent: #1d2b3f }`. Light text on pale blue is effectively invisible. |
| **Hypothesis** | Semantic token cascade break: interaction utilities (`hover:bg-accent`) not receiving `.dark` overrides consistently while surface tokens (`--color-surface`) do. May involve `@theme` / shadcn token channel vs `:root` `--accent` split. |

---

## H03 — Problems/Actions selected, hover, and selected+hover lose contrast

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `DecisionsView` → `MetricRow` (`bg-accent text-accent-foreground` when selected; `hover:bg-muted` when not) |
| **Evidence** | `decisions-light-problem-selected.png`, `decisions-dark-problem-selected.png`, `decisions-light-problem-hover.png`; dark selected computed `bg: #e8f1fc`, `color: #1a4fa8` on dark chrome |
| **Root cause (observed)** | Selected state uses **light accent pair** even in dark theme (same `#e8f1fc` / `#1a4fa8`). Unselected hover uses `hover:bg-muted` — light-mode muted hover contrast ≈ **4.92:1** (borderline for small text). |
| **Hypothesis** | Same accent cascade failure as H02; selected+hover stacks identical tokens (no distinct hover-over-selected styling). |

---

## H04 — Queue selected/hover rows and child cells lose contrast

| | |
| --- | --- |
| **Status** | **REPRODUCED** (code + partial runtime) |
| **Where** | `DecisionsView` queue `TableRow` with `data-state=selected`; `frontend/src/components/ui/table.tsx` row styles |
| **Evidence** | `decisions-*-queue-hover.png`; source inspection |
| **Root cause (observed)** | `TableRow` applies `data-[state=selected]:bg-accent data-[state=selected]:text-accent-foreground`, but `TableCell` children set explicit `text-foreground` / `text-muted-foreground`, **defeating row-level foreground**. Selected row background still flips to light accent in dark mode. |
| **Hypothesis** | Cell-level color classes need `data-[state=selected]:inherit` pattern or removal of redundant foreground utilities on selected rows. |

---

## H05 — Sidebar hover looks like active selection or hides icons/labels

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `frontend/src/components/ui/sidebar.tsx` → `SidebarMenuButton` |
| **Evidence** | `sidebar-light-hover-intake.png`, `sidebar-dark-hover-intake.png`; source lines ~476–482 |
| **Root cause (observed)** | **Hover and active share identical tokens:** `hover:bg-sidebar-accent hover:text-sidebar-accent-foreground` and `data-active:bg-sidebar-accent data-active:text-sidebar-accent-foreground`. No visual distinction except `data-active:font-medium`. |
| **Hypothesis** | Active state needs stronger indicator (border, primary fill, or left rail); hover should be subtler (`sidebar-accent/50` or `muted`). |

---

## H06 — Empty escalation icon/container has inappropriate light surface

| | |
| --- | --- |
| **Status** | **NOT REPRODUCED** (in captured viewport) |
| **Where** | `DecisionsView` empty escalations → `Empty` + `EmptyMedia variant="icon"` (`bg-muted`) |
| **Evidence** | Code review only; dataset has **0 escalations** — empty card exists but was below fold in full-page captures |
| **Hypothesis** | `EmptyMedia` icon variant uses `bg-muted` (`#eceae5` light / `#1e2229` dark). In dark mode, if `--muted` fails to cascade (see H01/H02), icon well may appear as **light gray chip on dark card**. Implementation agent should scroll to escalations empty state and verify. |

---

## E01 — Light Graph/Schema selected controls unreadable

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `ExploreView` lens toggle — selected pill `bg-primary text-primary-foreground` |
| **Evidence** | `explore-light-graph.png`; `measurements.json` light explore-lens → `bg: rgb(232,241,252)`, `color: rgb(255,255,255)` |
| **Root cause (observed)** | `bg-primary` resolves to **pale `#e8f1fc`** (same as `--accent`), not corporate blue `--color-accent`. White label on pale blue ≈ **low contrast** (visually washed out in screenshot). |
| **Hypothesis** | `--primary: var(--color-accent)` mapping broken at computed-style time (oklch resolution?) or primary channel aliased to accent soft fill. |

---

## E02 — Light Force/Tree and 2D/3D controls unreadable

| | |
| --- | --- |
| **Status** | **NOT REPRODUCED** (B2 audit — schema proxy) |
| **Where** | `GraphView.tsx` layout toggle; `Graph.tsx` 2D/3D renderer switch — both use `bg-primary text-primary-foreground` for active button |
| **Evidence** | B1 CSS cascade fix; B2 schema proxy: dark Force selected **4.76:1** white on `rgb(59,111,212)`; light oklch blue visually OK. Screenshots: `b2-schema-2d-{light,dark}.png` |
| **Root cause (resolved)** | B1 `index.css` primary token cascade fix. |
| **Residual** | Graph lens controls unverified live (`/graph` 500) — schema proxy sufficient for control chrome. |

---

## E03 — Actual 3D renderer or controls do not follow resolved theme

| | |
| --- | --- |
| **Status** | **BLOCKED** (live Graph lens) + **PARTIAL CODE GAP** |
| **Where** | `BrainGraph.tsx` — `scene` memo has `[resolvedTheme]` (B1 fix); `colors`/`data` memos still omit `resolvedTheme` |
| **Evidence** | Schema 3D proxy: `wrapBg` toggles light→dark without remount (`measurements-b2-audit.json` E03-3d-wrap). `/graph` 500 blocks BrainView live proof. |
| **Root cause (observed)** | Scene background updates; node palette and link tints frozen in `useMemo([orderedLabels])` / `useMemo([graph, colors, degree])`. |
| **Hypothesis** | Add `resolvedTheme` to color/data memos; verify `ForceGraph3D` `backgroundColor` prop updates WebGL clear color. Re-test on Graph lens when `/graph` healthy. |

---

## E04 — Graph labels/legend/details/tooltips inconsistent between themes

| | |
| --- | --- |
| **Status** | **PARTIAL** — overlays OK; NVL canvas stale on toggle |
| **Where** | `GraphView.tsx` legend (`bg-card/90 text-foreground`), detail panel (OK); NVL node colors via `buildLabelColors` (stale); `BrainGraph.tsx` overlay legend (OK) |
| **Evidence** | B2 schema proxy: legend `text-foreground` correct both themes (`b2-schema-2d-*.png`). `GraphView.tsx:83` — `colors` memo lacks `resolvedTheme`. |
| **Root cause (observed)** | HTML overlays use Tailwind tokens (cascade correctly). Canvas/WebGL colors read `cssVar()` once at memo time. |
| **Hypothesis** | Subscribe `GraphView`/`BrainGraph` color memos to `resolvedTheme`; trigger `restyle()` on theme change for NVL. |

---

## I01 — Intake active-run pipeline uses `text-muted` (surface token)

| | |
| --- | --- |
| **Status** | **REPRODUCED** (code audit) |
| **Where** | `StageCard.tsx` (lane labels, field labels, precedent scores — 11× `text-muted`); `CaseFile.tsx` panel hint; `ShipmentMap.tsx` empty state + legend |
| **Evidence** | Source inspection; no live POST (constraint). Idle Intake fixed in B1; active-run states never audited in browser. |
| **Root cause (observed)** | Same `text-muted` → `--muted` (surface) defect class as H01. |
| **Hypothesis** | Replace with `text-muted-foreground` in agent/ components; add vitest fixtures for `busy`/`stages`/`caseFile` states. |

---

## I02 — Intake map pin colors stale after theme toggle

| | |
| --- | --- |
| **Status** | **REPRODUCED** (code audit) |
| **Where** | `ShipmentMap.tsx` — `cssVar()` in `pathOptions` / legend `style.background`; no `useTheme()` subscription |
| **Evidence** | Component does not consume `ThemeContext`; won't re-render on toggle unless parent forces remount. |
| **Hypothesis** | Add `useTheme()` or shared `useThemeColors()` hook; same pattern as E03/E04 canvas fix. |

---

## Cross-cutting findings

1. **Token cascade is the primary defect class** — shadcn/Tailwind semantic tokens (`text-muted`, `bg-primary`, `bg-accent`) do not consistently track `.dark` overrides or intended custom mappings in the served bundle. **B1 fixed cascade for H/E01; `text-muted` persists in Intake active-run (I01).**
2. **`text-muted` utility is actively harmful** in production CSS — maps to background color. **Still present in `StageCard`, `CaseFile`, `ShipmentMap`.**
3. **Canvas/WebGL/Leaflet colors need `resolvedTheme` subscription** — `buildLabelColors`/`cssVar` at memo/render time without theme dep leaves NVL, 3D nodes, and map pins stale after toggle (E03/E04/I02).
4. **`GET /graph` → 500** — backend bug: `CYPHER 25` invalid (Neo4j accepts `5` only) in `chat/view/subgraph.py`. Blocks Graph lens live audit; schema proxy works for E02/E04 chrome.

---

## Batch 3 — `metric-semantics-bounded-workspace` (2026-09-17)

**Build:** `index-B9I8LKnG.css` / `index-276MDZLC.js` @ `http://127.0.0.1:8000`  
**Evidence:** `measurements-b3-audit.json`, `b3-audit-capture.mjs`, `b3-queue-measure.mjs`, `b3-sticky-scroll2.mjs`

---

## M01 — Metric bars lack outcome-based semantic meaning

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `DecisionsView` → `MetricRow`, `CaseCoverageCard`; `frontend/src/components/ui/progress.tsx` (`bg-primary` only) |
| **Evidence** | `measurements-b3-audit.json` → all 15 live indicators `oklch(0.546 0.245 262.9)` / dark `rgb(59,111,212)`; 100% and 80% bars indistinguishable |
| **Root cause (observed)** | `ProgressIndicator` hard-coded to `bg-primary`. No green/red/amber/neutral mapping from `succeeded`/`cases` or coverage resolved/open split. |
| **Spec gap** | Historical outcomes: GREEN success, RED unsuccessful (with proof), AMBER pending only when data supports, NEUTRAL unknown. Coverage: GREEN resolved / AMBER open. Learning: neutral. |

---

## L01 — Bounded workspace/table sizing must survive repairs

| | |
| --- | --- |
| **Status** | **NOT REPRODUCED** (heights correct; guardrail for B3 impl) |
| **Where** | `DecisionsView.tsx` — `PANEL_HEIGHT = h-[440px]`, `QUEUE_HEIGHT = h-[400px]` |
| **Evidence** | `b3-queue-measure.mjs` → Problems/Actions/Focus **440px** equal; queue **400px**; overflow fixture preserves 440px with scroll |
| **Root cause (observed)** | N/A — current build meets targets. |
| **Impl guard** | B3 must not remove height constants; add vitest/Playwright height assertions. |

---

## L02 — Queue sticky headers do not pin inside ScrollArea

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `DecisionsView` queue table — `TableHeader className="sticky top-0"` inside `ScrollArea` |
| **Evidence** | `b3-sticky-scroll2.mjs` → after `scrollTop=400`, `theadTop` moves with content; `headerPinned: false` |
| **Root cause (observed)** | Sticky on `thead` inside Base UI `ScrollArea` viewport does not pin; scroll ownership mismatch. |
| **Hypothesis** | Move sticky to viewport wrapper, use `overflow-auto` on table container, or restructure scroll owner. |

---

## L03 — Focus matching-cases sub-table has no sticky header

| | |
| --- | --- |
| **Status** | **REPRODUCED** (code + measurement) |
| **Where** | `DecisionsView` Focus panel inner `Table` (matching open cases) |
| **Evidence** | `b3-sticky-scroll.mjs` → `innerTableHasSticky: "static"`; 12 matching rows in live data |
| **Hypothesis** | Add sticky header when matching-cases table overflows inside Focus `ScrollArea`. |

---

## M02 — False 100% bars indistinguishable from partial success

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | Problems/Actions `MetricRow` — e.g. `failed_attempt_barcode_mismatch` 7/7 @ 100% |
| **Evidence** | Same primary fill as 80% rows in `measurements-b3-audit.json` progressBars |
| **Hypothesis** | Outcome-based stacked bar (green success + red failure) or full-green only when `succeeded === cases`. |

---

## M03 — Case coverage bar not green/amber split

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `CaseCoverageCard` — single `Progress value={pct}` |
| **Evidence** | Coverage indicator index 0 shares primary color with metric rows |
| **Hypothesis** | Use `StackedBar` with green resolved + amber open segments per spec. |

---

## M04 — Learning card uses success green for agent writeback count

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `ClosedLoopLearningCard` — `border-chart-good/40 text-chart-good` badge when `byAgent > 0` |
| **Evidence** | Source `DecisionsView.tsx:139`; live `by_agent: 0` so badge not visible — code audit |
| **Hypothesis** | Neutral/outline badge; learning is source composition not delivery outcome. |

---

## M05 — KPI “Precedent available” always good tone

| | |
| --- | --- |
| **Status** | **REPRODUCED** (code) |
| **Where** | `KpiCard` for precedent — hard-coded `tone="good"` |
| **Evidence** | `DecisionsView.tsx:383` |
| **Hypothesis** | Tone should reflect resolved/open ratio or use neutral default. |

---

## D01 — `writebacks.pending` in API not surfaced

| | |
| --- | --- |
| **Status** | **REPRODUCED** (code; value 0 in live data) |
| **Where** | `cases.py` `_AGENT_WRITEBACKS` returns `pending`; `CasesOverview` type omits it; UI ignores |
| **Evidence** | API field exists; `writebacks.pending: 0` in live `/cases` |
| **Hypothesis** | Optional amber-neutral pending count in learning/KPI area if product wants closed-loop visibility. |

---

## Batch 4 — `bilingual-ui-domain-display` (2026-09-17)

**Build:** `index-DVhlRZ8U.css` / `index-BVWhf3oi.js` @ `http://127.0.0.1:8000`  
**Evidence:** `measurements-b4-audit.json`, `b4-audit-capture.mjs`, `b4-*-{en,ar}-{light,dark}.png`

---

## I01 — Static UI copy remains English in Arabic mode

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | Header scope (`/meta` → `AppHeader`); `StageCard.tsx` (~42 strings); `CaseFile.tsx` (6); `ShipmentMap.tsx` (5); chrome aria-labels |
| **Evidence** | `b4-intake-ar-light.png`, `b4-decisions-ar-light.png`, `b4-schema-ar-light.png`; source grep |
| **Root cause (observed)** | Only shell nav/Decisions/Explore chrome wired to `t()`; active-run agent components and backend scope bypass dictionaries |
| **Hypothesis** | Extend `en.ts`/`ar.ts`; wire `StageCard`, `CaseFile`, `ShipmentMap`, scope through `t()` |

---

## I02 — Intake category labels bypass translated display mapping

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `IntakeView.tsx:133` — `c.category.replace(/_/g, ' ')` on case list metadata |
| **Evidence** | `b4-intake-ar-light.png` — cards show `recipient unavailable`, `hub delay`, `escalation:address conflict` |
| **Root cause (observed)** | Decisions surfaces use `rootCauseLabel()`; Intake idle list does not |
| **Hypothesis** | Replace with `rootCauseLabel(c.category)` |

---

## I03 — Graph/schema vocabulary remains English in visible presentation

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `GraphView.tsx:274` legend; detail panel `humanizeKey()`; `/meta` returns `labels: {}` |
| **Evidence** | `b4-schema-ar-light.png` — legend `Policy`, `Order`, `Shipment`, `FailureReason`, … |
| **Root cause (observed)** | Raw Neo4j label strings rendered; no `entityLabel()` display map; ontology descriptions empty |
| **Hypothesis** | Add `entities.*` to dictionaries + `entityLabel()` in `LanguageProvider`; apply in GraphView/BrainGraph |

---

## I04 — Stage/status/field labels and interpolated Arabic counts incomplete

| | |
| --- | --- |
| **Status** | **REPRODUCED** |
| **Where** | `StageCard.tsx` field labels (`Category`, `Verdict`, `Reject`/`Accept`, AFL strings); `DecisionsView.tsx:150,446` hardcoded `pending`; `ar.intake.awaiting` singular for all counts |
| **Evidence** | Source audit; AR browser count `75 شحنة بانتظار قرار` (no plural); EN `shipment(s)` plural rule |
| **Root cause (observed)** | Pipeline UI labels not in dictionaries; pending not keyed; Arabic count templates lack plural forms |
| **Hypothesis** | Add `intake.stages.*`, `common.pending`, plural-aware AR templates or ICU-style branching |
