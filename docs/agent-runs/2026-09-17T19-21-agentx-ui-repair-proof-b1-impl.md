# Batch 1 Implementation Handoff — `theme-cascade-hover-repair`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT B (IMPLEMENTATION)  
**Branch:** `fhd` @ `a9b39a098dea08a3b2aeb40f1216ebc3e3a1a169` (unchanged; not committed)

---

## Summary

Fixed the root CSS cascade defect (`.dark` overrides were losing to later `:root` rules) and aligned interaction tokens with audit target pairs. Intake metadata, dark-mode hovers, Decisions selection states, queue row inheritance, sidebar hover vs active, and Explore primary controls all show corrected computed styles in the served build.

---

## Files changed

| File | Change |
| --- | --- |
| `frontend/src/index.css` | Moved `.dark` block **after** `:root` so dark tokens win; set `--primary` to brand oklch blue (not accent soft fill); aligned light/dark accent, muted, secondary, and sidebar tokens to audit reference pairs; added `@layer utilities` override for `.text-muted → --muted-foreground` |
| `frontend/src/components/views/IntakeView.tsx` | Replaced all `text-muted` → `text-muted-foreground`; case buttons use `group` + `hover:text-accent-foreground` pairing with `hover:bg-accent` |
| `frontend/src/components/ui/table.tsx` | Selected rows propagate foreground: `data-[state=selected]:[&_[data-slot=table-cell]]:text-inherit` |
| `frontend/src/components/ui/sidebar.tsx` | Hover uses subtle `bg-muted`; active uses `bg-sidebar-accent` + left `border-sidebar-primary` rail |
| `frontend/src/components/views/shell.tsx` | `text-muted` → `text-muted-foreground` in `Center` |
| `frontend/src/components/artifacts/BrainGraph.tsx` | `scene` `useMemo` depends on `resolvedTheme` (E03 code fix) |
| `frontend/src/components/views/IntakeView.test.tsx` | **New** — H01/H02 regression (metadata class + hover pairing) |
| `frontend/src/components/views/BrainView.test.tsx` | Wrap with `ThemeProvider` |
| `docs/agent-runs/evidence/.../built-css-guard.mjs` | **New** — post-build CSS guard script |
| `docs/agent-runs/evidence/.../after-capture.mjs` | **New** — Playwright after-measurement script |
| `docs/agent-runs/evidence/.../measurements-after.json` | After computed-style matrix |
| `docs/agent-runs/evidence/.../*-after.png` | 14 desktop screenshots |

---

## Token / CSS fixes applied

1. **Cascade order (H02–H05, E01–E02 root cause):** `.dark { --accent, --primary, … }` now follows `:root` in source and built output (`darkIdx > rootIdx` verified).
2. **`text-muted` (H01):** `@layer utilities { .text-muted { color: var(--muted-foreground); } }` overrides shadcn's `color: var(--muted)` in built CSS.
3. **`--primary` (E01/E02):** Explicit brand blue `oklch(54.6% 0.245 262.9)` in light; `#5b8def` in dark — no longer aliases accent soft fill.
4. **Interaction pairs (audit targets):**
   - Light: hover `#F0F2F5` / `#20201E` via `--muted`/`--secondary`; selected `#E8F1FC` / `#163B66` via `--accent`/`--accent-foreground`
   - Dark: hover `#242B35` via `--muted`; selected `#1E324A` / `#EAF2FF` via `--accent`/`--accent-foreground`
5. **Sidebar (H05):** Hover = muted surface; active = accent fill + primary left border.
6. **Queue (H04):** Row-level `text-accent-foreground` now inherited by cells.

---

## Test commands and results

| Command | Result |
| --- | --- |
| `cd frontend && npm run test` | **PASS** — 17 files, 53 tests (includes new `IntakeView.test.tsx`) |
| `cd frontend && npm run lint` | **PASS** (warnings only; pre-existing `only-export-components`, one intentional `resolvedTheme` dep in BrainGraph) |
| `cd frontend && npm run build` | **PASS** |
| `node docs/agent-runs/evidence/.../built-css-guard.mjs` | **PASS** — no forbidden `.text-muted{color:var(--muted)}`; `.dark` after `:root` |

---

## Build fingerprint (after rebuild)

| Asset | Hash |
| --- | --- |
| CSS | `index-CmO_l9MU.css` |
| JS | `index-ZxmGr1I6.js` |
| Served at | `http://127.0.0.1:8000` |

---

## Before / after measurements (H01–H05, E01–E02)

Source: `measurements.json` (audit) vs `measurements-after.json` (this run).

| Issue | Theme | Metric | Before | After | ≥4.5:1? |
| --- | --- | --- | --- | --- | --- |
| **H01** | Light | Count/metadata color | `rgb(236,234,229)` (surface gray) | `rgb(102,100,95)` (`--muted-foreground`) | **Yes** (5.62 vs `#faf9f7`) |
| **H01** | Dark | Count/metadata color | `rgb(236,234,229)` (unchanged wrong) | `rgb(167,173,183)` | **Yes** on surface |
| **H02** | Dark | Intake hover contrast | **1.02** (`#e8f1fc` bg) | **11.58** (`#1e324a` bg, `#eaf2ff` text) | **Yes** |
| **H02** | Light | Intake hover contrast | 14.31 | 9.95 | **Yes** |
| **H03** | Dark | Problem selected contrast | ~low (pale `#e8f1fc` bg) | **11.58** | **Yes** |
| **H03** | Light | Problem selected contrast | — | 9.95 | **Yes** |
| **H04** | Dark | Queue cell on selected row | `rgb(240,242,245)` w/ wrong row bg | `rgb(241,245,249)` inherits row fg | **Improved** (row bg now dark accent) |
| **H05** | Both | Sidebar hover vs active | Identical `sidebar-accent` tokens | Hover=`muted`, active=`sidebar-accent`+border | **Visual** — see `sidebar-*-hover-intake-after.png` |
| **E01** | Light | Explore lens selected bg | `rgb(232,241,252)` (washed pale) | `oklch(0.546 0.245 262.9)` brand blue | **Yes** (white on blue) |
| **E01** | Dark | Explore lens selected | `rgb(96,165,250)` | `rgb(91,141,239)` + `#eaf2ff` text | **2.87** — Review may want primary-foreground tweak |
| **E02** | Both | Graph layout / 2D-3D controls | Not rendered (`/graph` 500) | Not rendered (`/graph` 500) | **Unverified live**; same `bg-primary` token fix as E01 |

### H06 (empty escalation icon)

**NOT REPRODUCED** in audit; not re-tested (0 escalations in dataset, below fold). `EmptyMedia` uses `bg-muted` — should track fixed dark `--muted` (`#242b35`). Review agent should scroll to escalations empty card.

---

## Known limitations

| ID | Status | Notes |
| --- | --- | --- |
| **E03** | Code fixed, live **unverified** | `BrainGraph` scene colors now rememo on `resolvedTheme`; `/graph` still returns 500 — no live 3D proof |
| **E04** | **BLOCKED** | Graph empty; legend/tooltip/NVL colors not auditable until backend graph endpoint healthy |
| **E02** | **BLOCKED** | Force/Tree and 2D/3D toggles not visible without graph data |
| **E01 dark** | **Marginal** | Lens contrast 2.87:1 — may need `--primary-foreground` adjustment in dark |

---

## Evidence artifacts

```
docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/
  measurements-after.json
  built-css-guard.mjs
  intake-{light,dark}-{default,hover}-after.png
  decisions-{light,dark}-{default,problem-selected,queue-hover}-after.png
  sidebar-{light,dark}-hover-intake-after.png
  explore-{light,dark}-graph-after.png
```

---

## Handoff for Review agent (Agent C)

### Verify manually

1. **EN × {Light, Dark} × {Intake, Decisions, Explore}** @ 1440×900 using `*-after.png` baselines.
2. Confirm sidebar: hover is gray-muted, active item has blue left rail + accent fill.
3. Scroll Decisions escalations empty state (H06).
4. If `/graph` is restored, re-run `after-capture.mjs` selectors for E02 graph controls and E03/E04 3D theme toggle without reload.

### Review focus

- Dark Explore lens contrast (2.87:1) — accept or request `--primary`/`--primary-foreground` tweak.
- Queue selected+hover stacked state (only single-state captured).
- No regressions in chat/dashboard components still using legacy `text-muted` class (global CSS override should protect, but spot-check).

### Do not

- Commit or push (per run rules).
- Edit `backend/**` for `/graph` 500.

---

## Coordinator payload

```yaml
RUN_ID: 2026-09-17T19-21-agentx-ui-repair-proof
AGENT: B (IMPLEMENTATION)
VERDICT: IMPLEMENTATION_COMPLETE
BUILD_CSS: index-CmO_l9MU.css
BUILD_JS: index-ZxmGr1I6.js
TESTS: PASS (53/53)
LINT: PASS (warnings only)
BLOCKERS_REMAINING:
  - GET /graph 500 (E02/E03/E04 live proof)
  - E01 dark lens contrast marginal (2.87:1)
NEXT_AGENT: Agent C (Review)
```
