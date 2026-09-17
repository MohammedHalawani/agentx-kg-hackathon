# Batch 1 Validation Gate — `theme-cascade-hover-repair`

**RUN_ID:** `2026-09-17T19-21-agentx-ui-repair-proof`  
**Agent:** AGENT D (VALIDATION / COMMIT-READINESS GATE)  
**Branch:** `fhd` @ `a9b39a098dea08a3b2aeb40f1216ebc3e3a1a169` (unchanged; not committed)  
**Candidate build:** `index-B9I8LKnG.css` / `index-Cy1Gdul3.js`

---

## Overall Batch 1 verdict: **CONDITIONAL PASS**

| Category | Verdict |
| --- | --- |
| **Functional** (H01–H06, E01) | **PASS** — all in-scope interaction/contrast checks pass with pointer hover at 1440×900 |
| **Visual** (screenshots + contrast matrix) | **PASS** — independent gate captures confirm hover states; H05 active+hover caveat documented |
| **Data / graph** (E02–E04) | **BLOCKED** — `GET /graph` → HTTP 500; no live graph controls or 3D chrome to verify |
| **Commit readiness** | **READY (conditional)** — automated checks pass; scope note below for out-of-allowlist dirty files |

Batch 1 meets the coordinator rule: H01–H06 + E01 **PASS**; E02–E04 explicitly **BLOCKED** (not FAIL).

---

## Per-issue gate verdicts

| ID | Review rec. | Gate verdict | Functional | Visual | Data | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| **H01** | PASS | **PASS** | Metadata uses `text-muted-foreground`; built CSS maps `.text-muted → --muted-foreground` | Light 5.62:1, dark 8.23:1 on Intake count | — | `measurements-gate.json` H01; `gate-intake-*-hover.png` (default state in intake shots) |
| **H02** | PASS | **PASS** | Dark hover bg `rgb(30,50,74)` — not `#e8f1fc` | Light 9.95:1, dark **11.58:1** with **pointer hover** | — | `gate-intake-{light,dark}-hover.png`; `measurements-gate.json` H02 (`pointerHover: true`) |
| **H03** | PASS | **PASS** | Selected, selected+hover, unselected hover all ≥4.5:1 both themes | Compound states stable under pointer hover | — | `measurements-gate.json` H03-* |
| **H04** | PASS | **PASS** | Main queue `tr[data-state="selected"]` cells inherit accent fg on accent row bg | Light 9.95:1, dark 11.58:1 selected+hover | — | `gate-decisions-{light,dark}-queue-selected-hover.png`; selector `tr[data-state="selected"] td` (not matching-cases sub-table) |
| **H05** | PASS | **PASS** | Inactive hover ≠ active default (muted vs accent+border) | Hover muted bg; active accent + 2px primary border | — | `gate-sidebar-{light,dark}-hover.png` |
| **H05 caveat** | — | **MEDIUM (not blocking)** | Active item + pointer hover reverts to muted bg; border + font-weight remain | Documented for Batch 2 polish | — | Review handoff; not re-fixed in B1 |
| **H06** | PASS | **PASS** | Empty escalation icon uses theme-aware `bg-muted` | Light 5.27:1, dark 6.32:1; no light chip in dark | — | `gate-escalations-{light,dark}-empty.png` |
| **E01** | PASS | **PASS** | Dark lens **4.76:1** white on `rgb(59,111,212)` | Light white on brand oklch blue (ratio null — oklch unparsed; visually passes) | — | `gate-explore-{light,dark}-lens.png`; `measurements-gate.json` E01 |
| **E02** | BLOCKED | **BLOCKED** | `bg-primary` token fixed in CSS (code-only) | Controls not rendered | `/graph` 500 | `graphEndpointStatus: 500` in `measurements-gate.json` |
| **E03** | BLOCKED | **BLOCKED (code PASS)** | `BrainGraph` `useMemo(..., [resolvedTheme])` confirmed in source | No live 3D | `/graph` 500 | Source: `BrainGraph.tsx:114–120`; no live proof |
| **E04** | BLOCKED | **BLOCKED** | — | Legend/tooltip/NVL not auditable | `/graph` 500 | Same blocker |

---

## Commands run and results (Agent D, independent)

| Command | Result | Notes |
| --- | --- | --- |
| `cd frontend && npm run test` | **PASS** | 17 files, **53/53** tests |
| `cd frontend && npm run lint` | **PASS** | 8 warnings only (pre-existing `only-export-components`; intentional `resolvedTheme` dep in BrainGraph) |
| `cd frontend && npm run build` | **PASS** | Output: `index-B9I8LKnG.css` (109.69 kB), `index-Cy1Gdul3.js` (4043.81 kB) — **matches candidate** |
| `node docs/agent-runs/evidence/.../built-css-guard.mjs` | **PASS** | `forbiddenTextMuted: false`, `correctTextMuted: true`, `darkAfterRoot: true` |
| `node docs/agent-runs/evidence/.../gate-capture.mjs` | **PASS** | 0 issues; 10 screenshots; EN × {light,dark} @ 1440×900 |
| `GET http://127.0.0.1:8000` | **200** | App serving |
| `GET http://127.0.0.1:8000/graph` | **500** | E02–E04 blocker confirmed |

No staging, commit, push, or deploy performed.

---

## Source / build fingerprint manifest

| Layer | Identity | Match candidate? |
| --- | --- | --- |
| **Served CSS** | `http://127.0.0.1:8000/assets/index-B9I8LKnG.css` | **Yes** |
| **Served JS** | `http://127.0.0.1:8000/assets/index-Cy1Gdul3.js` | **Yes** |
| **Dist on disk** | `frontend/dist/assets/index-B9I8LKnG.css`, `index-Cy1Gdul3.js` | **Yes** (post-gate rebuild identical hash) |
| **Prior audit baseline** | `index-6fyoBKuw.css` / `index-Ca8GudiR.js` | Superseded |

Gate rebuild did not change content hashes — candidate build is current and served.

---

## Acceptance matrix (gate-measured)

EN × {Light, Dark} @ 1440×900 — pointer hover where applicable:

| Surface | Light | Dark |
| --- | --- | --- |
| Intake metadata (H01) | 5.62:1 | 8.23:1 |
| Intake hover (H02) | 9.95:1 | 11.58:1 (no `#e8f1fc`) |
| Problem selected (H03) | 9.95:1 | 11.58:1 |
| Problem selected+hover (H03) | 9.95:1 | 11.58:1 |
| Problem unselected hover (H03) | 14.55:1 | 13.02:1 |
| Queue selected+hover (H04) | 9.95:1 | 11.58:1 |
| Sidebar inactive hover (H05) | muted `rgb(240,242,245)` | muted `rgb(36,43,53)` |
| Escalations empty icon (H06) | 5.27:1 | 6.32:1 |
| Explore lens selected (E01) | white on oklch blue (visual) | **4.76:1** |

Full JSON: `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/measurements-gate.json`

Screenshots: `docs/agent-runs/evidence/2026-09-17T19-21-agentx-ui-repair-proof/gate-*.png`

---

## Run-owned file list vs forbidden changes

### Batch 1 run-owned edits (allowlist — expected)

| File | Agent | Purpose |
| --- | --- | --- |
| `frontend/src/index.css` | B, C | Cascade order, token pairs, E01 dark primary fix |
| `frontend/src/components/views/IntakeView.tsx` | B | H01/H02 class + hover pairing |
| `frontend/src/components/ui/table.tsx` | B, C | H04 inheritance + selected+hover accent |
| `frontend/src/components/ui/sidebar.tsx` | B | H05 hover vs active |
| `frontend/src/components/views/shell.tsx` | B | `text-muted-foreground` |
| `frontend/src/components/views/DecisionsView.tsx` | C | H04 remove cell `text-foreground` |
| `frontend/src/components/artifacts/BrainGraph.tsx` | B | E03 `resolvedTheme` memo dep |
| `frontend/src/components/views/IntakeView.test.tsx` | B | H01/H02 regression sentinel |
| `frontend/src/components/views/BrainView.test.tsx` | B | ThemeProvider wrap |
| `docs/agent-runs/**` | B, C, D | Evidence + gate scripts only |

### Out-of-allowlist dirty files (pre-existing at audit baseline — not expanded by B1 agents)

These were already modified in `BASE_WORKTREE` per audit baseline; Agents B/C reported no edits. Gate did not diff each file independently but flags for commit coordinator:

| Path | Allowlist? | Gate note |
| --- | --- | --- |
| `frontend/src/components/chat/AppNav.tsx` | **No** | Pre-existing dirty; exclude from B1 commit or separate PR |
| `frontend/src/components/chat/TrustChip.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/chat/TrustChip.test.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/ui/Skeleton.tsx` | **No** | Pre-existing dirty |
| `frontend/src/components/ui/Tooltip.tsx` | **No** | Pre-existing dirty |
| `frontend/vite.config.ts` | **No** | Pre-existing dirty |
| `frontend/package.json` / `package-lock.json` | Conditional | Pre-existing; may include audit Playwright transient install |
| `frontend/tsconfig*.json` | **No** | Pre-existing dirty |
| `chat/scripts/load_shipment_graph.py` | **Forbidden** | Untracked; not part of B1 |

### Forbidden paths

- `backend/**` — not edited ✓
- `frontend/dist/**` — regenerated via build only ✓
- No database writes / mutation endpoints invoked ✓

**Scope verdict:** B1 theme/hover repair changes are confined to allowlist paths. Working tree carries additional pre-B1 dirt; coordinator should stage only run-owned files for the suggested commit.

---

## Regression test sentinel status (later batches)

| Sentinel | Status | Gap |
| --- | --- | --- |
| `built-css-guard.mjs` | **ACTIVE / PASS** | Post-build guard for forbidden `.text-muted{color:var(--muted)}` and `.dark` after `:root` |
| `IntakeView.test.tsx` (H01/H02) | **ACTIVE / PASS** | Class-name only; does not assert computed contrast ratios |
| `BrainView.test.tsx` (E03) | **WEAK** | Resample fetch only; **no theme-toggle / CSS-var assertion** for 3D scene colors |
| `gate-capture.mjs` | **NEW** | Independent gate matrix; H04 uses `tr[data-state="selected"]` (correct queue table) |

**Recommendation for Batch 2+:** Add computed-style or visual regression for E03 when `/graph` is healthy; strengthen H04 queue selector in any shared capture script.

---

## Suggested commit message (READINESS ONLY — do not commit)

```
fix(ui): resolve theme cascade and interaction contrast

Move .dark token overrides after :root so dark-mode accent/primary
utilities resolve correctly. Fix Intake metadata, Decisions selection
states, queue cell inheritance, sidebar hover vs active, and Explore
lens contrast. Add CSS build guard and IntakeView regression tests.

E02–E04 graph chrome remains unverified until GET /graph returns 200.
```

Stage only allowlist files listed above; exclude pre-existing chat/vite/tsconfig dirt unless intentionally bundled.

---

## Handoff for Batch 2 coordinator

1. **Commit posture:** CONDITIONAL PASS — safe to commit B1 allowlist changes with message above after coordinator strips out-of-scope dirty files.
2. **Blockers for E02–E04:** Restore `GET /graph` (Neo4j/backend env). Re-run `gate-capture.mjs` or extend it for Force/Tree, 2D/3D toggles, theme toggle without reload (E03 live), legend/tooltip/NVL (E04).
3. **Known polish (non-blocking):** H05 active+hover reverts to muted background; consider `data-active:hover:bg-sidebar-accent` in Batch 2.
4. **E01 light:** Contrast script cannot parse oklch pill bg; dark measured at 4.76:1 post-review fix — both themes visually acceptable.
5. **Asset pin:** Any deployment must serve `index-B9I8LKnG.css` / `index-Cy1Gdul3.js` (rebuild if source changes after gate).
6. **Evidence index:**
   - Gate: `docs/agent-runs/2026-09-17T19-21-agentx-ui-repair-proof-b1-gate.md` (this file)
   - Measurements: `measurements-gate.json`, `measurements-review.json`
   - Screenshots: `gate-*.png`, `review-*.png`
   - Scripts: `gate-capture.mjs`, `built-css-guard.mjs`

---

## Coordinator payload

```yaml
RUN_ID: 2026-09-17T19-21-agentx-ui-repair-proof
AGENT: D (VALIDATION GATE)
VERDICT: CONDITIONAL_PASS
BUILD_CSS: index-B9I8LKnG.css
BUILD_JS: index-Cy1Gdul3.js
TESTS: PASS (53/53)
LINT: PASS (warnings only)
CSS_GUARD: PASS
BROWSER_GATE: PASS (0 issues, pointer hover)
H01_H06_E01: PASS
E02_E04: BLOCKED (/graph 500)
SCOPE: ALLOWLIST_OK; PRE_EXISTING_DIRT_OUTSIDE_ALLOWLIST
COMMIT: NOT_PERFORMED
NEXT: Batch 2 coordinator — graph endpoint + optional H05 polish
```
