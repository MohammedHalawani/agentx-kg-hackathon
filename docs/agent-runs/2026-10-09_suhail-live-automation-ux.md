# Suhail — live automation UX pass (2026-10-09)

Branch `fhd`, starting HEAD `8446621` (Composer shadcn work preserved).

## Automation policy discovered (unchanged)

- Investigation and routing are fully automatic (V2 LangGraph, deterministic evidence rules, no LLM).
- Every V2 recommendation carries `requires_approval: True`; the review guard *rejects* any proposal that
  does not. No auto-authorization concept exists.
- Outcome verification requires the local operator (`require_actor`) and an operator-approved execution receipt.
- Routes: `AWAITING_APPROVAL` (proposal accepted), `HUMAN_REVIEW` (conflicting evidence), `NEEDS_EVIDENCE`
  (no grounded action), `ESCALATED` (review rejected twice).

**Not built:** an automatic path to `AWAITING_OUTCOME → RESOLVED` (live story steps 12–14). Supporting it would
need a new, explicit, synthetic-only allowlist (e.g. `AUTO_EXECUTION_MODE=simulation_only` for a low-risk
action) *plus* a non-operator outcome verifier. Both change authority rules, so they were left as a decision
for the owner. In this pass `AWAITING_OUTCOME`/`RESOLVED` are only reachable through the human path.

## Changes

- Backend: worker status now exposes `active_shipment_id` and the last completed run
  (`last_case_id`, `last_shipment_id`, `last_workflow_state`, `last_processed_at`), registered in the ledger schema.
- Backend: `SUHAIL_WORKER_PACE_SECONDS` (default 6) adds a gap *between* cases, measured from when each run finishes.
  Stage execution is never delayed. Real runs already take ~6.5 s (Neo4j retrieval), so stages advance visibly.
- Intake: the counters are now Queued · Processing · Human attention · Awaiting outcome · Resolved, with tooltip
  status copy. **Now processing** reads `/worker/status` (1.2 s poll while running) and the case SSE stream. Its
  chips use only recorded stage events. After a run it shows "Investigation completed automatically → {state}",
  plus "auto-triage continues" when the case went to a person.
- Intake: a collapsible **Human attention** rail with Review / Approval / Evidence / Escalated tabs. Each tab is
  server-paginated (`/cases/queue?workflow_state=…&limit=25`, cursor). Counts are unfiltered totals. The rail has
  no decision controls.
- Case workspace: new **Auto** focus (default), driven by `stageFocus()`. Collect is balanced. Graph, precedent and
  review use graph focus. Diagnose uses the map for spatial causes (route, custody, traffic, address) and the graph
  otherwise. Route uses the map for spatial causes and is balanced otherwise. A manual Balanced/Map/Graph choice
  is never overridden.
- Build: vendor chunks split (`nvl`, `leaflet`, `vendor`). On this machine the single 4 MB chunk exceeded the
  import-analysis WebAssembly memory, and the build failed even on the baseline.

## Verified

Python 189 passed · frontend 153 passed / 42 files · tsc clean · lint 0 errors · build OK · `git diff --check` clean.
Browser at 1440×900 and 1920×1080, EN + AR: Start → row claimed → chips advanced Collect→…→Route from real
events → case routed to Human review / Awaiting approval → worker claimed the next case without waiting.
Opening the live case: Auto focus moved graph → map with the stage. No console errors, no 4xx/5xx.

## Live data note

QA processed 32 queued cases. Queue now: OPEN 5, AWAITING_APPROVAL 15, HUMAN_REVIEW 12, RESOLVED 1.

## Not done in this pass

Ask Suhail stays feature-gated. No road geometry. Decisions/Audit/Explore unchanged apart from shared copy.
The Review rejection→revision chain is the existing pipeline expander.
