# Deliverable 8 — Composer Phase A: current UI discovery and preparation

Read the approved Suhail V3 plan at `C:\Projects\suhail-v3-plan-2026-10-13\01-master-plan.md`. Use one Composer chat/worktree for both phases. Implementation/preparation requires the user's plan approval; no paid model calls are authorized.

Work only on `v3/route-ui` in `C:\Projects\suhail-v3-route-ui`, from Sol's shared bootstrap SHA. Verify branch/root/ancestor. Sol imports committed `frontend-next` from protected `C:\Projects\demo\.ui-integration`, commit `5aab052daead6141bf54fda068f7bd4bdcba3cb2`, onto backend fhd `4cd43045a1db284e83cd5702d63acf7950492492`. If the bootstrap is missing, report that dependency and inspect reference files read-only. Do not build in `.ui-integration`, `.stage4`, main `demo`, or `demo-ui`.

Your objective is a precise map/graph/status implementation inventory using the actual recording UI. You can begin immediately without a new dataset. Keep current styling/navigation/Arabic and English behavior. No new component library, redesign or model/provider work.

Inspect in your V3 root:

- `frontend-next\src\components\route-map.tsx`, `network-map.tsx`, `knowledge-graph.tsx`, `investigation-record.tsx`.
- `src\api\contracts.ts`, `adapters.ts`, `client.ts`; `src\services\api-operations.ts`.
- `src\domain\types.ts`, `state\operations.tsx`, `pages\operations.tsx`, `pages\investigation.tsx`.
- `tests\unit\api-adapters.test.ts`, `api-service.test.ts`; `tests\fixtures\backend.ts`, `tests\e2e-backend\backend-stub.ts`, `connected.spec.ts`.
- `vite.config.ts`, `playwright.config.ts`, `playwright.live.config.ts`, package/lockfile.

Already verified: seven existing route layers, GPS as vehicle context, source IDs in evidence adapters, one `activeCaseId` state assumption. Backend `/worker/status` will add `worker.active_cases`. Backend case/shipment detail will add `route_evidence` and enrich vehicle_path. Existing GPS fallback `gps@time` is a display key, not a source record; Phase B must require actual evidence IDs for source selection.

Document current wire shapes, adapter losses (receipt/source/accuracy/route IDs), how selected evidence maps to graph IDs, stream/cache keys, case switching and active-panel logic. Identify the smallest changes needed to show two active investigations without swapping streams. Distinguish current functionality from proposed changes.

Permitted Phase A edits: isolated presentation/accessibility fixes using existing fields and a small written discovery report. Do not implement new-data-dependent behavior until Sol approves `suhail-v3-1` and supplies its fixture. Do not edit backend files, lab data to disguise missing evidence, recording scripts/videos or entire CSS theme. Your owned Phase B file list is in the plan; request ownership for any other file first. Keep Phase A changes easy to review separately.

Run current adapter/service unit checks, typecheck and a fresh isolated build in `frontend-next` if source changed. Inspect ports before launching UI tests. Current connected Playwright tests reuse a server on 5191; refuse an unrelated existing server or select a fresh test port. Never point automated writes at 8022. Do not run live model specs: some opt-in specs trigger investigations.

By hour 24 produce: current contract inventory, exact Phase B edit list, required Sol/Opus fields, one source-selection sketch consistent with existing design, targeted baseline test results, and any missing contract blockers. Commit only owned files on `v3/route-ui` and provide SHA/checkpoint. Do not merge. Continue to Phase B in this same chat once the frozen schema and fixture are delivered. Then complete Phase C in this same branch/chat within a hard four-hour budget, using `09-composer-phase-c-prompt.md`: independent source-first review of every curated development shipment and the two original video shipments where evidence is available, before reading the isolated test catalogue and before integration signoff. No dataset edits or paid inference.

WORKSTREAM:
BRANCH / HEAD:
COMPLETED:
CHANGED FILES:
TESTS RUN / RESULTS:
BLOCKERS:
INTEGRATION DEPENDENCIES:
NEXT ACTION:
READY TO MERGE: YES / NO
