# Batch 1 Audit Handoff — `theme-cascade-hover-repair`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT A (AUDIT)  
**Verdict:** **SCOPE_READY**

---

## Executive summary

Theme and interaction contrast failures are **confirmed in the served production build** at `http://127.0.0.1:8000`. The dominant defect is a **CSS token cascade mismatch** between intended theme definitions in `frontend/src/index.css` and the compiled shadcn/Tailwind output in `frontend/dist/assets/index-6fyoBKuw.css`.

The most severe user-visible bugs:

1. **`text-muted` renders as `var(--muted)` (surface gray)** → Intake secondary text nearly invisible in light mode (H01).
2. **`hover:bg-accent` / `bg-accent` / `bg-primary` resolve to light `#e8f1fc` in dark mode** → Intake hover unreadable (H02), Decisions selection states wrong in dark (H03–H04).
3. **Sidebar hover ≡ active styling** (H05).
4. **Explore/Graph selected controls use washed-out primary fill** (E01–E02).

Explore graph/3D theme issues (E03–E04) are **blocked** by `GET /graph` → 500; code review flags `BrainGraph` theme memoization as likely follow-up.

---

## Observed facts vs hypotheses

### Observed facts

| ID | Fact |
| --- | --- |
| F1 | Built rule: `.text-muted{color:var(--muted)}` (not `--muted-foreground`). |
| F2 | Light Intake `text-muted` computed color `#eceae5` on surface `#faf9f7`. |
| F3 | Dark Intake hover: `background-color #e8f1fc`, `color #f0f2f5`, contrast **1.02:1**. |
| F4 | Dark Decisions selected MetricRow: same `#e8f1fc` / `#1a4fa8` pair on dark shell. |
| F5 | `SidebarMenuButton` hover and active classes both target `sidebar-accent` background. |
| F6 | Explore Graph lens selected pill: `bg-primary` → `#e8f1fc` with white text. |
| F7 | Served assets match `frontend/dist` hashes; service was already running. |
| F8 | `/graph` returned HTTP 500 during audit — Explore graph empty. |

### Hypotheses (for implementation agent to validate)

| ID | Hypothesis |
| --- | --- |
| P1 | `@import "shadcn/tailwind.css"` generates utilities that override custom `@utility text-muted` — fix import order, rename utility (`text-muted-copy`), or migrate Intake to `text-muted-foreground`. |
| P2 | `@theme inline` / shadcn color registry binds `accent` and `primary` to light-fill values that don't re-resolve under `.dark` for state utilities. |
| P3 | Decisions queue cells need selected-state-aware text classes or `inherit` from row. |
| P4 | `BrainGraph` `useMemo([], [])` freezes 3D background — add `resolvedTheme` dependency. |
| P5 | Separate **hover** tokens needed for sidebar (`sidebar-accent/60`) vs **active** (`sidebar-primary` or left border). |

---

## Implementation allowlist (Batch 1)

### ALLOW — may edit

```
frontend/src/index.css
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/lib/theme.ts
frontend/src/lib/cn.ts
frontend/src/lib/utils.ts
frontend/src/components/theme/**
frontend/src/components/layout/**
frontend/src/components/i18n/**          # only if locale affects theme class/layout
frontend/src/components/views/IntakeView.tsx
frontend/src/components/views/DecisionsView.tsx
frontend/src/components/views/ExploreView.tsx
frontend/src/components/views/BrainView.tsx
frontend/src/components/views/SchemaView.tsx
frontend/src/components/views/shell.tsx
frontend/src/components/ui/table.tsx
frontend/src/components/ui/sidebar.tsx
frontend/src/components/ui/button.tsx
frontend/src/components/ui/empty.tsx
frontend/src/components/ui/badge.tsx
frontend/src/components/ui/card.tsx
frontend/src/components/artifacts/Graph.tsx
frontend/src/components/artifacts/GraphView.tsx
frontend/src/components/artifacts/BrainGraph.tsx
frontend/index.html                    # only theme FOUC script if needed
frontend/package.json                  # only if adding test deps explicitly requested
frontend/src/**/*.test.tsx             # regression tests only
```

### FORBIDDEN — do not edit in Batch 1

```
backend/**
chat/**
.env*
**/*.py                                # except read-only inspection
shipment_kg/**
neo4j scripts / seed / reset tooling
frontend/node_modules/**
frontend/dist/**                       # regenerate via build, don't hand-edit
database writes / POST /complaint / mutation endpoints
```

---

## Regression tests & acceptance criteria

### Automated

| Test | Intent |
| --- | --- |
| Extend or add Vitest test asserting `text-muted` utility resolves to foreground token | Prevent H01 recurrence |
| `BrainView.test.tsx` — mock theme toggle, assert graph wrapper receives updated CSS vars | Guard E03 |
| Optional: node script parsing built CSS for forbidden `.text-muted{color:var(--muted)}` | CI guard on token mapping |

Run: `cd frontend && npm run test && npm run lint && npm run build`

### Manual acceptance (post-build, `http://127.0.0.1:8000`)

| Check | Pass criteria |
| --- | --- |
| H01 Light Intake | Count, description, metadata ≥ **4.5:1** contrast vs adjacent surface |
| H02 Dark Intake hover | Hover bg stays **dark** (not `#e8f1fc`); text ≥ **4.5:1** |
| H03 Problems/Actions | Selected, hover, selected+hover all ≥ **4.5:1** in light **and** dark |
| H04 Queue rows | Selected row + cells readable; hover distinct from selected |
| H05 Sidebar | Active item visually distinct from hover; icons/labels remain visible |
| H06 Empty escalation | Icon well matches theme (no light chip in dark) |
| E01 Explore lens | Selected Graph/Schema label readable |
| E02 Graph controls | Force/Tree + 2D/3D selected states readable |
| E03 3D renderer | Background updates after theme toggle without full page reload |
| E04 Graph chrome | Legend, tooltip, detail panel consistent across themes |

**Matrix:** EN × {Light, Dark} × {Intake, Decisions, Explore} @ 1440×900 minimum.

---

## Recommended implementation sequence (Agent B)

1. **Fix token cascade in `index.css`**
   - Ensure `.text-muted` maps to `--muted-foreground` in **built** output (verify in `dist` after build).
   - Audit `:root` / `.dark` `--primary`, `--accent`, `--accent-foreground` — ensure `bg-primary` is saturated blue in light, dark variants in `.dark`.
   - Consider renaming conflicting shadcn utilities or using `@layer` ordering.

2. **Intake (`IntakeView.tsx`)**
   - Replace `text-muted` → `text-muted-foreground` as interim fix even after CSS repair.
   - Add `hover:text-accent-foreground` or dedicated `hover:bg-accent` pairing when using accent hover bg.

3. **Decisions (`DecisionsView.tsx` + `table.tsx`)**
   - Fix `MetricRow` selected/hover tokens for dark mode.
   - Remove or conditionalize cell-level `text-foreground` on selected queue rows.

4. **Sidebar (`sidebar.tsx` or `AppSidebar.tsx`)**
   - Differentiate `data-active` vs `hover` backgrounds.

5. **Explore / Graph (`ExploreView`, `Graph`, `GraphView`, `BrainGraph`)**
   - Fix `bg-primary` selected controls.
   - Add theme dependency to `BrainGraph` scene colors.

6. **Rebuild & re-run acceptance matrix** — confirm `/graph` if backend team can fix 500 (not in B1 scope unless read-only env issue).

---

## Blockers

| Blocker | Impact | Owner |
| --- | --- | --- |
| `GET /graph` → 500 | E03/E04 live verification incomplete | Backend / env (Neo4j) — **does not block** H01–H05 fixes |
| cursor-ide-browser MCP unavailable | Used Playwright fallback | Audit tooling only |

---

## Artifact index

| File | Purpose |
| --- | --- |
| `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-baseline.md` | Repo/runtime baseline |
| `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-issue-register.md` | Per-issue reproduction status |
| `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b1-audit.md` | This handoff |
| `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements.json` | Computed styles + build fingerprint |
| `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/*.png` | 16 desktop screenshots |

---

## Coordinator return payload

```yaml
RUN_ID: 2026-09-17T19-21-agentx-ui-repair-proof
PROJECT_ROOT: C:\Projects\demo
FRONTEND_ROOT: C:\Projects\demo\frontend
BRANCH: fhd
BASE_HEAD: a9b39a098dea08a3b2aeb40f1216ebc3e3a1a169
APP_URL: http://127.0.0.1:8000
PACKAGE_MANAGER: npm
VERDICT: SCOPE_READY
BLOCKERS:
  - GET /graph returns 500 (E03/E04 live audit incomplete)
  - cursor-ide-browser MCP tab unavailable (Playwright used instead)
NEXT_AGENT: Batch 1 Implementation — start with index.css token cascade + Intake text-muted fix
```
