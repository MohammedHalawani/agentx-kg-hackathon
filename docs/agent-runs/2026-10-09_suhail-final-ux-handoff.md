# Suhail — final operations UX handoff (2026-10-09)

Branch `fhd`. Starting HEAD `e885bd1` with an interrupted, uncommitted Sol/Codex session (39 modified + 11 new
files). Primary presentation targets: desktop 1440×900 and 1920×1080, English and Arabic. Mobile is a
minimal "loads, navigable, no blocking overflow" regression only.

## Takeover

- No merge in progress; second worktree `C:/Projects/demo-ui` (`ui/suhail-operations-v2`) untouched.
- Sol's last full gate ran *after* its last edits (189 Python, 132 frontend, lint 0 errors, build OK), so the
  interrupted work was reviewed and checkpointed as-is:
  - `8db1390` V2 triage as a recorded LangGraph; two-clock Audit pagination; reversible `SYN-*` IDs; reopen
    limited to RESOLVED/REJECTED/ESCALATED; explicit versioned re-analysis.
  - `22977db` automatic-triage execution status and separate Human decision gate.
- Older untracked `docs/agent-runs/2026-10-07_agentx-*` notes and `.playwright-mcp/` scratch remain uncommitted.

## Architecture truth (what actually runs)

V2 topology (compiled LangGraph, `chat/operations/graph.py`):
`extract → retrieve → classify → retrieve_context → recommend → review → (writeback | recommend [retry ≤2] | escalate)`.

| Kind | Where |
|---|---|
| Deterministic evidence rules | classify (`operations.reasoning.triage`), recommend, review guard, routing |
| Graph-derived | retrieve (bounded Neo4j case neighborhood), retrieve_context (verified, non-invalidated precedent traversal) |
| LLM-backed | **None in V2.** The model-backed GPT-OSS LangGraph remains on the V1 `/v1/*` complaint path |
| Human authority | approve / reject / request evidence / escalate, action receipt, outcome observation and verification, reopen |

The reviewer rejection → revision on SYN-SHP-001241 is an explicit deterministic rehearsal (a GPS-delivery
proposal the guard must reject), not measured model behaviour. The UI labels the pipeline
"Automatic · LangGraph · evidence rules".

## UX changes in this session

- **Pipeline** (`InvestigationPipeline`, `lib/pipelineSteps`): eight connected steps
  Collect · Graph · Diagnose · Precedent · Recommend · Review · Route · Outcome, mapped from recorded events.
  Route shows whichever terminal branch actually ran; Outcome is a dashed *gate* (not a LangGraph node) that is
  only ✓ for a VERIFIED, non-invalidated outcome. Glyphs + text for completed / running / queued / revising /
  rejected / human review / escalated / waiting / skipped / failed / timing-not-recorded. Review carries a ↺n
  revision badge and an expandable rejection→revision chain. Clicking inspects; it never POSTs.
- **Stage ↔ graph ↔ map**: one `highlightedIds` set (stage evidence, or evidence chosen in the Evidence tab) drives
  both the Neo4j graph dimming and route emphasis; route layers auto-select per stage among layers with data.
- **Focus modes**: Balanced / Map focus / Graph focus (≈50/50, 70/30, 30/70), animated grid, persisted in
  `sessionStorage`. Until the operator chooses, the stage-relevant pane only gets a subtle ring + hint.
- **Sidebar**: case workspace compacts the sidebar to its icon rail and restores the prior state on Back
  (`useCompactSidebar`; no persisted preference is read or changed).
- **Overview** (≥1280px): summary rail (What happened → Expected vs actual → Recommended action with the
  Human decision controls directly beneath it) beside the pipeline and full-height evidence surfaces. The whole
  reference story fits 1440×900.
- **Evidence**: Key evidence (only what diagnosis / recommendation / outcome cite, divergent milestones, and
  components bound to them by a real graph edge; no inferred scores) with provenance, stages that cited it, and
  Show in graph / Show on map (map only when plotted); Route & custody chronology with kind filters and
  `from → to` custody handoffs; Parties & locations; Policy & context (+ verified precedents link);
  Full inventory last.
- **Intake**: Auto-triage status with Start/Pause beside the counters; replay controls collapsed by default.
- **Reopen** moved into the case header (shown only for RESOLVED/REJECTED/ESCALATED).
- Compact map layer chips double as a line-style legend (dashed plan, solid custody, dotted vehicle telemetry).

## Verification (after final edits)

- Python: 189 tests OK. Frontend: 145 tests / 39 files OK (new: step mapping incl. no recommendation→resolved
  shortcut, evidence categories, sidebar compact/restore, focus persistence, evidence→graph focus).
- Build OK (large-chunk warning unchanged). Lint 0 errors. `git diff --check` clean. Secret scan PASS.
- `operations_final_audit.py`: PASS — V1 exactly preserved, 2000 V2 shipments, every RESOLVED case backed by a
  verified outcome + execution, 0 external notification calls.
- Headless Chromium at 1440×900 and 1920×1080 (EN + AR) over Intake, reference case (all sections), resolved
  case, Explore Map/Graph/Schema, Decisions, Audit page 1→2: no console errors, no 4xx/5xx, no horizontal
  overflow, no missing i18n keys, no demo/prototype/placeholder/fixture/mock wording. Arabic 390×844: loads,
  no overflow.

## Presentation cases (live state)

1. **SYN-SHP-001241** delivery dispute → HUMAN_REVIEW; recorded rejection → revision; proof vs NOT_RECEIVED report.
2. **SYN-SHP-000762** journey delay → RESOLVED via verified outcome (Outcome gate ✓).
3. **SYN-SHP-000044** unreconciled custody → HUMAN_REVIEW (no "lost" claim; GPS ≠ parcel).
4. **SYN-SHP-000126** traffic delay → AWAITING_APPROVAL (next eligible session), or **SYN-SHP-001727** address conflict.

Use Start on Intake to show a queued case advancing live while 001241 waits for a human.

## Known limitations

Synthetic data only; no SPL integration, live GPS, authentication or real execution. V2 reasoning is
deterministic rules, not a model. Earlier runs (before stage persistence) show "timing not recorded".
Straight custody lines connect corroborated stops and are labelled as unobserved movement, not road routes.
~4 MB bundle. Mobile is functional, not polished.

## Run

```powershell
Set-Location C:\Projects\demo\frontend; npm.cmd run build
Set-Location C:\Projects\demo\chat; uv run uvicorn --app-dir ..\backend main:app --host 127.0.0.1 --port 8001
```
Open http://127.0.0.1:8001 (Neo4j `shipments-v2-demo` and Ollama must be running).
