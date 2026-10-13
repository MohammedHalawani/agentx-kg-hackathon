# Deliverable 9 — Composer Phase B: GPS/evidence and parallel-case visuals

Continue the same V3 Composer chat and `v3/route-ui` worktree at `C:\Projects\suhail-v3-route-ui`. Read the approved master plan and Sol's approved `suhail-v3-1` wire schema/fixture. The starter example is `C:\Projects\suhail-v3-plan-2026-10-13\06-contract-examples.json`. Do not invent a new backend contract. If Sol has revised it, require the integrator-reviewed version and use it consistently. No new-data-dependent work before that contract is approved; you can use its deterministic fixture before the full dataset is ready.

The baseline is committed `frontend-next` imported from `C:\Projects\demo\.ui-integration` `5aab052daead6141bf54fda068f7bd4bdcba3cb2`, on backend fhd `4cd43045...`. Verify shared bootstrap ancestry and retain the recording UI's design, bilingual behavior, accessibility and responsive layout. Protected references, recordings, databases and port 8022 remain untouched.

## Exact owned files

Within your root, modify only necessary files:

- `frontend-next\src\api\contracts.ts`, `adapters.ts`.
- `src\services\api-operations.ts`, `domain\types.ts`, `state\operations.tsx`.
- `src\pages\operations.tsx`, `pages\investigation.tsx`.
- `src\components\route-map.tsx`, `network-map.tsx`, `knowledge-graph.tsx`, `investigation-record.tsx`.
- `src\styles\workspace.css` for small compatible adjustments.
- `tests\unit\api-adapters.test.ts`, `api-service.test.ts`, `tests\fixtures\backend.ts`, `tests\e2e-backend\backend-stub.ts`, `connected.spec.ts` and proposed `v3-evidence.spec.ts`, `v3-concurrency.spec.ts`.

Do not edit root legacy `frontend`, backend, generators, tools, claims, provider/reviewer/policy code or recording assets. Request a concrete ownership handoff for any additional path. Follow applicable React-quality instructions when editing several TSX components.

## Route/evidence behavior

Use existing `route_layers.layers.expected_route`, `vehicle_path`, `custody_points`, `actual_route`, `hub_stops`, `delivery_attempts`, `traffic`. New additive `route_evidence` provides shared transport context, source records/relationships and summary, all at one declared `as_of`. Plan endpoints are approximate expected connections; observed vehicle samples are recorded GPS; actual/custody evidence stays corroborated parcel records. Labels must make these meanings understandable.

Extend TypeScript contracts/adapters for receipt timestamp, source reference, accuracy, vehicle, route/trip, assignment and `position_scope`. Preserve `evidence_id` exactly. HTTP IDs are `SYN-*`; never manually convert them to DEMO or strip namespaces. Do not generate a fake evidence ID when one is absent. An unidentifiable point may not be selected/cited as a source; report its missing identity or omit it according to the approved contract.

Show expected connection and observed GPS with existing distinct styles/layer toggles; include observation time and received time in details and disclose bounded sampling/gaps. Do not draw interpolated points as measured GPS. Do not join different vehicles/routes into one continuous path. Do not extend a GPS path to a recipient address merely because the shipment was planned there. Traffic needs an actual source; no congestion story from geometry alone. GPS never means delivered, parcel location or driver misconduct.

Merge real `route_evidence.source_nodes`/`source_relationships` with existing graph data without inventing edges. Map selection highlights the exact source ID and opens source details. Handle a source node with no retrievable edge honestly. Case switching clears old source selection and stale async results. Preserve existing graph layout and evidence timeline; distinguish model findings/reviewer acceptance from deterministic signals and independently verified outcomes.

Missing geometry/source/context stays missing with a concise UI state. Do not fall back to lab fixtures in a connected build. No redesign or new library. A small factual timeline should sort by occurrence and display receipt separately; explain why a late-upload record was unavailable at the earlier snapshot.

## Parallel investigation behavior

Consume `worker.active_cases`, `active_count`, configured `concurrency` and existing heartbeat map from `/worker/status`. Treat active_cases as authoritative; legacy activeCaseId is only for old backends or a single active case. Do not infer two active cases from concurrency=2. Show at most two active rows/cards using the current operations layout, with each shipment/run/stage/update and evidence cutoff.

Preserve per-case cache/watchers and case/run/sequence stream identity. One run's progress, review or completion must never update its peer. Ignore out-of-date run events after reanalysis and late fetches after case selection changes. Completion of one active case leaves the other active. Support zero/one/two active cases, global pause/recovery and older backend payloads with the new fields absent. `diagnosis` stays unavailable until the current run's existing acceptance conditions hold; do not replace missing diagnosis with rule triage.

## Verification and handoff

In `C:\Projects\suhail-v3-route-ui\frontend-next`:

```powershell
npm.cmd ci
npm.cmd run typecheck
npm.cmd test -- tests/unit/api-adapters.test.ts tests/unit/api-service.test.ts
npm.cmd run build
npm.cmd run test:e2e -- tests/e2e-backend/connected.spec.ts tests/e2e-backend/v3-evidence.spec.ts tests/e2e-backend/v3-concurrency.spec.ts
```

Check test ports and prevent reuse of an unrelated server; current Playwright config's `reuseExistingServer` is not a license to use a protected demo. Mock only in test fixtures. Verify expected/observed/custody meanings, absent coordinates/source IDs, correct graph selection, chronology/receipt distinction, truncation and two simultaneous case streams with one peer completing or failing. Include case-switch/reanalysis stale events. Preserve bilingual/phone layout through a short walkthrough, not a new visual redesign campaign.

After Sol's route data is available, perform an isolated integration walkthrough at `http://127.0.0.1:8023/app/`; integrator starts the server. Do not trigger paid investigations. Use the mocked-provider integration harness for changing states. Live model specs or uncontrolled Auto mode are prohibited without the bounded live approval.

Feature freeze at hour 48; hour 48–72 is defects only. Deliver commit SHA, changed files, exact contract version/fixture, test results/skips, a few screenshots from the isolated build, and browser limitations. Use shared checkpoint template. No merge/push into peers or fhd. The integrator reviews and merges your exact SHA last, after dataset and concurrency contracts pass.

Next complete `09-composer-phase-c-prompt.md` in the SAME Composer chat/worktree. Reserve at most four hours during hours 48–60 to independently reconstruct evidence/storylines for all approximately 6–10 curated cases plus the two original V2 video shipments where evidence exists. Finalize evidence-first notes before catalogue comparison, cite actual source IDs and mark PASS/REVIEW/FAIL. Return data defects to Sol; fix UI defects only in your owned files. This QA report is required before final integration signoff and does not authorize model calls.
