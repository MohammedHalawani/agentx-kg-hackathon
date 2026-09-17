# Batch 2 Review — `visualization-theme-lifecycle`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT C (REVIEW / FIX)  
**Branch:** `fhd` (unchanged; no commits)  
**Candidate build:** `index-B9I8LKnG.css` / `index-276MDZLC.js` @ `http://127.0.0.1:8000`  
**Date:** 2026-09-17

---

## Overall verdict: **REVIEW_PASS**

Batch 2 implementation claims are **verified independently**. All in-scope BLOCKER/HIGH issues from the B2 audit are addressed. No code fixes were required during review. Live Graph-lens verification remains **BLOCKED** by `GET /graph` → 500 (backend `CYPHER 25` — forbidden path).

---

## Independent verification matrix

| ID | Impl claim | Review method | Verdict |
| --- | --- | --- | --- |
| **I01** | `text-muted` → `text-muted-foreground` in StageCard/CaseFile/ShipmentMap | Grep `frontend/src/components/agent/` — zero bare `.text-muted`; spot-read changed files | **PASS** |
| **I02** | ShipmentMap pins refresh on theme toggle | Code: `useTheme()` + `pinColors` memo keyed on `resolvedTheme`; no `key={theme}` on `MapContainer` | **PASS** (code; map browser optional) |
| **E04** | GraphView `colors` memo + `restyle()` on theme change | Code review `GraphView.tsx:85,157-159`; Schema 2D UI toggle: wrap bg light→dark | **PARTIAL PASS** (schema proxy; live Graph BLOCKED) |
| **E03** | BrainGraph memos include `resolvedTheme` | Code review `BrainGraph.tsx:114-177`; `BrainGraph.test.tsx`; Schema 3D UI toggle: wrap/surface var light→dark | **PARTIAL PASS** (schema proxy; live Graph BLOCKED) |
| **Intake lifecycle** | Vitest fixtures for busy/error/success | Read `IntakeView.test.tsx` — mocks `useComplaintStream`, no POST/SSE | **PASS** |
| **B1 sentinels H01–H05** | No regression | Re-ran with gate `effectiveBg()` methodology (`b2-review-capture.mjs`) | **PASS** |

---

## Test / build results (Agent C)

| Command | Result | Detail |
| --- | --- | --- |
| `npm run test` | **PASS** | 18 files, **58/58** |
| `npm run lint` | **PASS** | 12 warnings (pre-existing + intentional `resolvedTheme` exhaustive-deps on theme memos) |
| `npm run build` | **PASS** | CSS `index-B9I8LKnG.css`; JS `index-276MDZLC.js` |
| `node built-css-guard.mjs` | **PASS** | `forbiddenTextMuted: false`, `correctTextMuted: true` |
| `node b2-review-capture.mjs` | **PASS** | 0 issues; B1 sentinels all PASS (UI theme toggle) |

---

## Code review lenses

### No `key={theme}` remount anti-pattern

Grep across `frontend/src/components/artifacts/` — no `key={theme}` or `key={resolvedTheme}` on graph/map containers. Graph identity and camera/layout preserved on toggle. **PASS**

### GraphView `restyle()` path

```85:85:frontend/src/components/artifacts/GraphView.tsx
  const colors = useMemo(() => buildLabelColors(orderedLabels), [orderedLabels, resolvedTheme])
```

```156:159:frontend/src/components/artifacts/GraphView.tsx
  // Refresh NVL node colours when theme tokens change without remounting the graph.
  useEffect(() => {
    if (ready) restyle()
  }, [resolvedTheme, ready, restyle])
```

- `restyle()` calls `updateElementsInGraph` only — does not replace `graphData`, reheat simulation, or remount `InteractiveNvlWrapper`. **PASS**
- No listener leaks — effect is a one-shot restyle, no subscriptions added. **PASS**

### BrainGraph memo / disposal

- `colors`, `nodeColorById`, `data` memos all include `resolvedTheme` (lines 133–177). **PASS**
- `ForceGraph3D` receives updated `backgroundColor` and `graphData` on theme change; unit test confirms without remount. **PASS**
- No custom Three.js materials created — disposal handled by library. **PASS**

### ShipmentMap theme subscription

```22:31:frontend/src/components/agent/ShipmentMap.tsx
  const { resolvedTheme } = useTheme()
  const pinColors = useMemo(
    () => ({
      line: cssVar('--color-chart-blue'),
      warehouse: cssVar(STYLE.warehouse.color),
      delivery: cssVar(STYLE.delivery.color),
      home: cssVar(STYLE.home.color),
    }),
    [resolvedTheme],
  )
```

Chart tokens (`--color-chart-*`) are themed in `.dark` block — pins will refresh when `resolvedTheme` changes. **PASS**

---

## Browser evidence (Agent C)

### Build fingerprint

| Asset | Served @ `:8000` |
| --- | --- |
| CSS | `index-B9I8LKnG.css` ✓ |
| JS | `index-276MDZLC.js` ✓ |

### Schema proxy — UI theme toggle (not DOM-only)

Methodology: `ThemeToggle` dropdown (Light/Dark) so React `resolvedTheme` updates, not just `.dark` class.

| View | Light wrap | Dark wrap | Surface var light→dark |
| --- | --- | --- | --- |
| Schema 2D | `rgb(250, 249, 247)` | `rgb(17, 19, 24)` | `#faf9f7` → `#111318` |
| Schema 3D | `rgb(250, 249, 247)` | `rgb(17, 19, 24)` | `#faf9f7` → `#111318` |
| Toggle return | `rgb(250, 249, 247)` (light restored, no remount) | — | — |

Screenshots: `evidence/.../b2-*-review.png`  
Measurements: `evidence/.../measurements-b2-review.json`

### Graph legend swatch colors unchanged — expected

`--graph-1`…`--graph-8` and `--node-*` tokens are **fixed hex in both themes** by design (`index.css` — not overridden in `.dark`). Legend swatches staying identical after toggle is correct; the memo+restyle fix ensures canvas state stays in sync if palette is themed later and supports BrainGraph dimming (`mix(node.color, scene.bg)`).

### `GET /graph` — still blocked

| Probe | Result |
| --- | --- |
| `GET /schema` | **200** |
| `GET /graph` | **500** (unchanged) |

Live BrainView / domain-graph NVL verification **cannot PASS** until `chat/view/subgraph.py` `CYPHER 25` → `CYPHER 5` (needs coordinator permission).

---

## B1 sentinel re-check (H01–H05)

Re-ran with gate-equivalent `effectiveBg()` walk in `b2-review-capture.mjs`.

| Sentinel | Light | Dark | Status |
| --- | --- | --- | --- |
| H01 intake count | 5.62:1 | 8.23:1 | **PASS** |
| H02 intake hover | 9.95:1 | 11.58:1 | **PASS** |
| H03 problem selected | 9.95:1 | — | **PASS** |
| H04 queue selected+hover | 9.95:1 | 11.58:1 | **PASS** |
| H05 sidebar hover ≠ active | distinct bgs | distinct bgs | **PASS** |

No B1 regression vs `measurements-gate.json`.

---

## Findings

### BLOCKER

| ID | Finding | Status |
| --- | --- | --- |
| **GRAPH_ENDPOINT** | `GET /graph` → 500 (`CYPHER 25` invalid). Blocks live Graph-lens E03 gate proof. | **DOCUMENTED** — not fixable in B2 allowlist |

### HIGH

None. All audit HIGH items (I01, I02, E03/E04 memo gaps, Intake `text-muted`) are resolved in code and tests.

### MEDIUM

| ID | Finding | Gate recommendation |
| --- | --- | --- |
| **M01** | `b2-after-capture.mjs` / `b2-audit-capture.mjs` toggle theme via `page.evaluate` (DOM class only) — does **not** update React `resolvedTheme`. Wrap/overlay CSS still changes; memo-driven canvas refresh untested by those scripts. | Gate should use UI `ThemeToggle` (as in `b2-review-capture.mjs`) |
| **M02** | No `GraphView.test.tsx` for E04 `restyle()` on theme change (BrainGraph has equivalent test). | Optional follow-up test; not blocking |
| **M03** | Intake active-run tests assert class absence (`.text-muted`) not computed contrast ratios. Acceptable for lifecycle fixtures; contrast covered by H01 gate. | No action |

### LOW

| ID | Finding | Gate recommendation |
| --- | --- | --- |
| **L01** | Oxlint `exhaustive-deps` warnings on intentional `resolvedTheme` deps in GraphView/BrainGraph/ShipmentMap. | Suppress or ignore — deps are deliberate |
| **L02** | `MapView.tsx` (BrainGraph detail card mini-map) has no `useTheme()` — out of B2 I02 scope; pins use inline `cssVar` at render. | Track separately if detail-card map theming needed |
| **L03** | `CypherCode.tsx` still uses `text-muted` — pre-existing, outside Intake agent allowlist. | Out of B2 scope |

---

## Fixes applied (Agent C)

**None.** Review found no in-scope BLOCKER/HIGH defects requiring code changes.

---

## Gate recommendations per issue

| ID | Recommendation |
| --- | --- |
| **I01** | **PASS** — grep + vitest |
| **I02** | **PASS** — code review; optional ShipmentMap pin color spot-check in browser |
| **E03** | **PARTIAL PASS** — code + `BrainGraph.test.tsx` + schema 3D proxy; live Graph **BLOCKED** |
| **E04** | **PARTIAL PASS** — `restyle()` wired + schema 2D proxy; live Graph **BLOCKED** |
| **Intake lifecycle** | **PASS** — vitest mocks, no POST |
| **H01–H05** | **PASS** — no regression |
| **GRAPH_ENDPOINT** | **BLOCKED** — document; do not fake PASS on live Graph lens |

### Permission still needed for full E03 gate

- `chat/view/subgraph.py`: `CYPHER 25` → `CYPHER 5`

---

## Coordinator payload

```yaml
RUN_ID: 2026-09-17T19-21-agentx-ui-repair-proof
AGENT: C (B2 REVIEW)
VERDICT: REVIEW_PASS
BUILD_CSS: index-B9I8LKnG.css
BUILD_JS: index-276MDZLC.js
TESTS: PASS (58/58)
LINT: PASS (warnings only)
CSS_GUARD: PASS
B1_SENTINELS: PASS (effectiveBg methodology)
I01: PASS
I02: PASS
E03: PARTIAL PASS (schema proxy; live Graph BLOCKED)
E04: PARTIAL PASS (schema proxy; live Graph BLOCKED)
INTAKE_LIFECYCLE: PASS
GRAPH_ENDPOINT: 500 (unchanged)
FIXES_APPLIED: none
COMMIT: NOT_PERFORMED
ARTIFACTS:
  - docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b2-review.md
  - docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b2-review.json
  - docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b2-review-capture.mjs
  - docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b2-*-review.png
NEXT: Agent D (Gate)
```
