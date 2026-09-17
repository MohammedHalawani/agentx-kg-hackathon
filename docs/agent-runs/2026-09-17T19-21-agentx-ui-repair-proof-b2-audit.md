# Batch 2 Audit — `visualization-theme-lifecycle`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT A (AUDIT)  
**Branch:** `fhd` (unchanged; no commits)  
**Candidate build:** `index-B9I8LKnG.css` / `index-Cy1Gdul3.js` @ `http://127.0.0.1:8000`  
**Viewport:** 1440×900 desktop, locale EN  
**Date:** 2026-09-17

---

## Overall verdict: **SCOPE_READY**

Batch 2 frontend theme-lifecycle work is **ready for implementation** with a documented backend blocker for live Graph-lens verification. The `/graph` 500 is an **env/backend bug** (invalid Cypher version prefix), not a frontend defect. Schema lens (`GET /schema` → 200) provides a viable proxy for E02/E04 control chrome; E03 live BrainView proof remains blocked until `/graph` is healthy.

**Coordinator permission needed** if Batch 2 impl agent is allowed to fix `chat/view/subgraph.py` (`CYPHER 25` → `CYPHER 5`) — that path is **forbidden** under default B2 allowlist.

---

## Per-issue audit verdicts

| ID | Verdict | Functional | Visual | Data | Notes |
| --- | --- | --- | --- | --- | --- |
| **H01–H05** (B1 sentinels) | **NOT REPRODUCED** | B1 fixes hold | Gate methodology | — | B2 script false-positives on H01-dark/H04-light due to missing `effectiveBg()`; see §Regression |
| **E01** | **NOT REPRODUCED** | Explore lens OK | Light visual; dark 4.76:1 on pill | — | B1 fix confirmed; B2 mis-measured unselected lens text |
| **E02** | **NOT REPRODUCED** | Force/Tree + 2D/3D controls readable | Schema proxy screenshots | Schema live | White on `rgb(59,111,212)` dark = **4.76:1**; light oklch blue visually OK |
| **E03** | **BLOCKED** (partial code gap) | `BrainGraph` scene memo has `resolvedTheme` | Wrap bg toggles; WebGL bg unverified on Graph lens | `/graph` 500 | Node-color memos still lack `resolvedTheme`; NVL has same gap |
| **E04** | **PARTIAL PASS** | Legend/detail overlays use token classes | Schema proxy OK both themes | Schema live | NVL node colors stale on theme toggle without remount |
| **Intake lifecycle** | **REPRODUCED** (code) | Active-run uses `text-muted` in pipeline | Not browser-verified (no POST) | Mock-only | StageCard, CaseFile, ShipmentMap gaps |

---

## `/graph` 500 investigation (read-only)

| Probe | Result |
| --- | --- |
| `GET /schema` | **200** — Neo4j connectivity OK |
| `GET /graph` | **500** — empty response body |
| `GET /samples` | **200** |
| Root cause | `chat/view/subgraph.py` line 42: `_DISCOVER_CYPHER = "CYPHER 25\n..."` |
| Neo4j error | `Invalid pre-parser option, specified '25' is not valid for option 'cypher version'. Valid options are: '5'.` |

**Classification:** Backend bug / version mismatch — **not** missing Neo4j or empty database. `/schema` uses `CALL db.schema.visualization()` without the bad prefix and succeeds.

**Impact on B2:**

| Activity | Blocked? |
| --- | --- |
| Frontend theme fixes (E02–E04, Intake) | **No** — impl can proceed |
| Live Graph lens browser verification | **Yes** — BrainView shows empty state |
| Live 3D on domain graph sample | **Yes** — blocked |
| Schema lens 2D/3D proxy verification | **No** — works today |

**Read-only fix available:** Change `CYPHER 25` → `CYPHER 5` in `subgraph.py` (requires coordinator permission — `backend/**` and `chat/**` forbidden by default).

---

## Theme behavior analysis

### Layer model (toggle styling vs canvas vs overlays)

| Layer | Components | Theme mechanism | Toggle without remount |
| --- | --- | --- | --- |
| **Toggle / control chrome** | `ExploreView` lens, `Graph.tsx` 2D/3D, `GraphView`/`BrainGraph` layout buttons | Tailwind `bg-primary`, `text-primary-foreground`, `bg-card/90` | **Works** — CSS vars cascade via `.dark` |
| **Card frame / HTML overlays** | Legend, detail panel, zoom controls | Token utility classes (`text-foreground`, `text-muted-foreground`, `bg-card`) | **Works** — re-renders on context for consumers; CSS handles rest |
| **2D NVL canvas** | `GraphView` → `InteractiveNvlWrapper` | `buildLabelColors()` → `cssVar()` at memo time | **Broken** — `colors` memo deps `[orderedLabels]` only |
| **3D WebGL canvas** | `BrainGraph` → `ForceGraph3D` | `tokenHex('--color-surface')` in `scene` memo | **Partial** — `backgroundColor` updates (`[resolvedTheme]`); node `color`/`data` memos do not |
| **Leaflet map** | `ShipmentMap`, `MapView` | `cssVar()` inline in JSX / `pathOptions` | **Broken** — no `useTheme()` subscription; component won't re-render on toggle unless parent forces it |

### Anti-patterns found

| Pattern | Location | Severity |
| --- | --- | --- |
| `useMemo(..., [orderedLabels])` freezing `buildLabelColors` | `GraphView.tsx:83`, `BrainGraph.tsx:133` | **High** — NVL/3D node colors stale after theme toggle |
| `useMemo` for `data` nodes without `resolvedTheme` | `BrainGraph.tsx:160-177` | **Medium** — dimmed/mixed colors frozen |
| `text-muted` (surface token, not foreground) | `StageCard.tsx` (11×), `CaseFile.tsx:22`, `ShipmentMap.tsx:23,100` | **High** — same H01 defect class in Intake active-run |
| No `key={theme}` remount | None found | Good — prefer fixing memos over remount hack |
| Stale module-level theme reads | None found | `cssVar()` reads live `getComputedStyle` when called |

### E03 — BrainGraph memo status (post-B1)

```114:121:frontend/src/components/artifacts/BrainGraph.tsx
  const scene = useMemo(
    () => ({
      bg: tokenHex('--color-surface'),
      link: tokenHex('--color-muted'),
      signal: cssVar('--marker'),
    }),
    [resolvedTheme],
  )
```

B1 fix applied for scene background. **Remaining gap:** `colors`, `nodeColorById`, and `data` memos omit `resolvedTheme` — node palette and link tints won't refresh on toggle. Schema 3D proxy shows `wrapBg` updates (`rgb(250,249,247)` → `rgb(17,19,24)`) without remount; canvas pixel sampling not performed in this audit.

### E04 — NVL / overlay consistency

- **HTML overlays** (legend, detail card, zoom cluster): use `text-foreground` / `text-muted-foreground` — **consistent** in both themes (schema proxy).
- **NVL node colors**: computed once per graph load — **will diverge** after theme toggle until `restyle()` is triggered with refreshed colors.
- **Tooltips**: NVL native (canvas) — not separately themed; node labels appear at zoom threshold.

---

## Intake active-run lifecycle (mock/code audit)

**Constraint honored:** No `POST /complaint` or live mutation. Assessment via source + existing vitest mocks.

| State | UI surfaces | Theme gaps |
| --- | --- | --- |
| **Idle** (case list) | H01/H02 fixed in B1 | PASS (vitest + gate) |
| **Running** (`busy`) | StageCard trace, loader, CaseFile pane | `StageCard` lane labels, field labels, precedent scores use `text-muted` |
| **Success** (`final.disposition`) | Outcome banner, CaseFile graph + map | `CaseFile` panel hint `text-muted`; map legend `text-muted` |
| **Error** | Red border banner | OK — uses `text-danger` |
| **Evidence graph** | `CaseFile` → `Graph` | Same E02–E04 issues as Explore |
| **Evidence map** | `CaseFile` → `ShipmentMap` | `cssVar` pin colors + `text-muted` legend |

**Test coverage gap:** `IntakeView.test.tsx` only covers idle state (H01/H02 class sentinels). No fixtures for `busy`, `stages[]`, `caseFile`, `error`, or `final` states.

**Recommended fixtures (vitest, no POST):** Extend `useComplaintStream` mock with stage arrays from `types/agent.ts` samples; assert `text-muted-foreground` in active-run headings and no `.text-muted` in pipeline trace.

---

## Browser evidence

### Build fingerprint

| Asset | Served |
| --- | --- |
| CSS | `index-B9I8LKnG.css` ✓ |
| JS | `index-Cy1Gdul3.js` ✓ |

### Screenshots (B2 audit)

| File | Content |
| --- | --- |
| `evidence/.../b2-schema-2d-light.png` | Schema 2D, light, Force selected |
| `evidence/.../b2-schema-2d-dark.png` | Schema 2D, dark |
| `evidence/.../b2-schema-3d-light.png` | Schema 3D, light |
| `evidence/.../b2-schema-3d-dark.png` | Schema 3D, dark |
| `evidence/.../b2-theme-toggle-no-remount.png` | After light→dark→light without reload |
| `evidence/.../b2-graph-empty-light.png` | Graph lens empty (`/graph` 500) |

### Measurements

- `evidence/.../measurements-b2-audit.json` — full matrix
- `evidence/.../measurements-gate.json` — B1 gate baseline (authoritative for H01–H05)

### Theme toggle without remount (Schema view)

| Step | `--color-surface` | Primary btn bg | Legend fg |
| --- | --- | --- | --- |
| light | `#faf9f7` | oklch blue | `rgb(32,32,30)` |
| dark | `#111318` | `rgb(59,111,212)` | `rgb(241,245,249)` |
| light (return) | `#faf9f7` | oklch blue | `rgb(32,32,30)` |

Control chrome and HTML overlays track theme. Canvas/WebGL background wrapper tracks theme; node color refresh unverified.

---

## B1 sentinel regression (H01–H05)

Re-ran hover sentinels via `b2-audit-capture.mjs`. Three apparent failures (H01-dark, H04-light, E01-dark) are **measurement artifacts** — script used element `backgroundColor` instead of gate's `effectiveBg()` walk and measured wrong E01 element on Schema tab.

**Authoritative regression status:** Align with B1 gate (`measurements-gate.json`) — **H01–H05 PASS, no regression detected.**

| Sentinel | B2 raw script | Gate-equivalent |
| --- | --- | --- |
| H01 dark | 2.15:1 (wrong bg) | **8.23:1** PASS |
| H04 light | 1.85:1 (transparent cell bg) | **9.95:1** PASS |
| H02–H03, H05 | PASS | PASS |

---

## Allowlist / forbidden paths for B2 implementation

### Allowlist (frontend theme lifecycle)

| Path | Purpose |
| --- | --- |
| `frontend/src/components/artifacts/BrainGraph.tsx` | E03 — extend `resolvedTheme` to color/data memos |
| `frontend/src/components/artifacts/GraphView.tsx` | E04 — NVL color refresh on theme change |
| `frontend/src/components/artifacts/Graph.tsx` | E02 — renderer toggle (verify only; likely OK post-B1) |
| `frontend/src/components/views/ExploreView.tsx` | E01 verify |
| `frontend/src/components/views/SchemaView.tsx` | Tests only |
| `frontend/src/components/views/BrainView.tsx` | Resample button chrome |
| `frontend/src/lib/theme.ts` | Optional `useThemeColors()` hook |
| `frontend/src/components/agent/StageCard.tsx` | Intake — `text-muted` → `text-muted-foreground` |
| `frontend/src/components/agent/CaseFile.tsx` | Intake — panel hint contrast |
| `frontend/src/components/agent/ShipmentMap.tsx` | Intake map — legend + `useTheme` for pin refresh |
| `frontend/src/components/views/IntakeView.tsx` | Intake layout (if needed) |
| `frontend/src/components/views/IntakeView.test.tsx` | Active-run state fixtures |
| `frontend/src/components/views/BrainView.test.tsx` | E03 theme-toggle assertion |
| `frontend/src/index.css` | Only if new tokens needed |
| `docs/agent-runs/**` | Evidence scripts |

### Forbidden (unless coordinator grants permission)

| Path | Reason |
| --- | --- |
| `backend/**` | Audit constraint |
| `chat/view/subgraph.py` | `/graph` fix lives here — **NEEDS_PERMISSION** |
| `chat/scripts/load_shipment_graph.py` | Untracked / out of scope |
| `frontend/dist/**` | Build output only |
| Any `POST /complaint` | Mutation forbidden |

### Pre-existing dirty (do not expand)

`AppNav.tsx`, `TrustChip.tsx`, `Skeleton.tsx`, `Tooltip.tsx`, `vite.config.ts`, `tsconfig*.json` — per B1 gate.

---

## Recommended implementation sequence

1. **Intake active-run `text-muted` sweep** — `StageCard`, `CaseFile`, `ShipmentMap` (low risk, no `/graph` dependency).
2. **GraphView theme subscription** — add `resolvedTheme` to `colors` memo + call `restyle()` on theme change.
3. **BrainGraph theme subscription** — extend `resolvedTheme` to `colors`, `data`; verify `backgroundColor` prop propagates to ForceGraph3D.
4. **ShipmentMap / MapView** — `useTheme()` + re-read `cssVar` on toggle (or shared hook).
5. **Vitest fixtures** — Intake running/success/error states; BrainView theme CSS-var assertion.
6. **(Optional, permissioned)** Fix `CYPHER 25` → `CYPHER 5` in `subgraph.py` for live Graph-lens gate re-run.
7. **Re-capture** — extend `b2-audit-capture.mjs` with `effectiveBg()` and Graph lens shots when `/graph` healthy.

---

## Tests run (audit)

| Command | Result |
| --- | --- |
| `npm run test` | **PASS** — 17 files, 53/53 |
| `node b2-audit-capture.mjs` | **PASS** (0 true issues; 3 measurement artifacts) |
| Python `connected_sample_graph()` | **FAIL** — Cypher version error (confirms `/graph` 500) |

---

## Coordinator payload

```yaml
RUN_ID: 2026-09-17T19-21-agentx-ui-repair-proof
AGENT: A (B2 AUDIT)
VERDICT: SCOPE_READY
PERMISSION: NEEDS_PERMISSION for chat/view/subgraph.py if /graph fix in B2
BUILD_CSS: index-B9I8LKnG.css
BUILD_JS: index-Cy1Gdul3.js
B1_SENTINELS: PASS (no regression)
E01: NOT REPRODUCED
E02: NOT REPRODUCED (schema proxy)
E03: BLOCKED (live Graph lens); code gap remains
E04: PARTIAL (overlays OK; NVL colors stale on toggle)
INTAKE_LIFECYCLE: REPRODUCED (text-muted in active-run)
GRAPH_ENDPOINT: 500 (CYPHER 25 invalid; blocks live verify only)
COMMIT: NOT_PERFORMED
ARTIFACTS:
  - docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b2-audit.md
  - docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-b2-audit.json
  - docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b2-audit-capture.mjs
  - docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b2-schema-*.png
  - docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b2-theme-toggle-no-remount.png
  - docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/b2-graph-empty-light.png
```
