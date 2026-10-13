# Deliverable 10 — Final GPT-6 Sol High integration and signoff

You are the sole Suhail V3 integration owner. Read the approved `C:\Projects\suhail-v3-plan-2026-10-13\01-master-plan.md`, contract example and all three workstream checkpoints. User approval must authorize implementation. Paid model use remains separately bounded/approved. Do not silently alter another workstream's major design or merge unsafe changes for a deadline.

## Baseline and isolation

Protected main repository: `C:\Projects\demo`, `fhd` `4cd43045a1db284e83cd5702d63acf7950492492`. Protected `.stage4` `187ae087a0083dd36192d3653a669b4de706f692` has identical backend/chat/scripts. Protected recording frontend: `.ui-integration\frontend-next`, commit `5aab052daead6141bf54fda068f7bd4bdcba3cb2`, branch `claude/project-thread-unq829`. Tracked tree was clean; untracked videos/screenshots must be preserved. Older `demo-ui` branch is not this UI baseline. No active 8022 listener was found during planning; recheck without starting/stopping it.

Your worktree is `C:\Projects\suhail-v3-integration`, branch `v3/integration`. If bootstrap has not been done after approval, execute the master plan's pinned worktree/local-fetch/frontend-next-only import sequence. Review staged paths, commit the imported baseline, add approved contract artifacts under `docs\v3`, run imported UI baseline checks and pin the common bootstrap SHA. Create sibling branches from that SHA, never from an obsolete UI or dirty tree. Main fhd and protected checkouts stay unchanged.

Development roots: `C:\Projects\suhail-v3-concurrency` (`v3/concurrency`), `C:\Projects\suhail-v3-scenarios` (`v3/scenarios`), `C:\Projects\suhail-v3-route-ui` (`v3/route-ui`). Recheck actual branch HEADs and SHAs; do not merge a moving branch merely because its name is correct. Branch refs/paths were unoccupied during planning; abort/reconcile if that changed.

## Review and merge order

Require each owner: exact SHA, clean tree, bootstrap ancestor, owned changed files, focused test evidence/skips, contract version and rollback config. Examine diff from bootstrap; check no unrelated generated artifacts/secrets/truth, reviewer/policy/outcome changes or protected configuration. Treat mock-only and skipped DB gates as incomplete evidence.

Merge exact reviewed scenarios SHA first, concurrency SHA second, UI SHA third, with no fast-forward and explicit merge messages. Resolve only small integration glue yourself. If a conflict changes claim fencing, evidence semantics or UI design, request the owner's repair and a fresh reviewed SHA. Do not select an entire conflicting file from one side blindly. No merge into fhd, no automatic push/deployment.

You own necessary glue in `backend\operations_api.py`, `backend\main.py`, `chat\operations\graph.py`, `investigator.py`, `checks.py`, `datasets.py`, `ingestion.py`, `chat\dataset_v2\contracts.py`, `.env.example`, proposed `scripts\v3_backend.ps1`, `scripts\v3_smoke.py`, and `docs\v3\*`. Default is to leave graph/reviewer/schema semantics unchanged. Sol dataset owns read_model/tools/reasoning and forwards Opus's store-produced investigation_status; avoid editing those while that branch is active. Major shared design changes require ownership handoff and affected-owner review.

## Code review gates

Check atomic claim capacity and token/epoch ownership under real transactions; wall-clock leases independent of simulation; heartbeat not counted as material case evidence; all progress/final/trace/action-intent paths fenced; terminal StageBuffer events cannot revert a finalized run; one worker failure cannot globally pause its peer. Reanalysis/pause/reset/skip and restart handle all claims. DB sessions are per-operation and model messages/cache/budget per run.

Provider gate counts the actual underlying request after caller timeout, including translation/narration/Canopus. Timeout retries cannot exceed the limit or leave unlimited waiting threads. Audit stable action IDs and adapter replay; reviewer acceptance never equals outcome verification. Verify one-worker fallback and the declared one-process prototype scope.

Check new GPS queries are fixed/parameterized/scoped, source cutoff applies to nodes and relationships, route/trip references bind to this shipment and vehicle interval, model sample IDs were actually rendered, records are resolvable by reviewer/graph, vehicle position never implies parcel delivery. Missing traffic/coordinates cannot be filled from private state. Existing structural precedent eligibility remains unchanged and BGE-M3 disabled.

Check HTTP uses existing DEMO↔SYN boundary, no ID rewrite. UI uses imported frontend-next and actual new fields; active_count/capacity and streams remain separate; no lab fallback or invented map source IDs. A static status banner is insufficient concurrency proof.

## Scratch data and launch

V3 database: `shipments-v2-world-v3-20261013`. Race target: `shipments-v2-world-v3-ci-20261013`. Before writing, inspect exact names/content/configured protected defaults. Provision NEW local DBs only after confirming they do not exist, using a safe parameterized/validated administrative operation. If an existing target has different content, choose a new explicit V3 name and update the approved coordination contract; do not `CREATE OR REPLACE`, clear or reset it. Do not reuse `shipments-v2-world-ux-test` or existing V2 CI databases.

Import Sol's validated label-free bundle and feed with the existing `world.export apply <directory> --database <name>` interface, without `--replace`; record dataset/manifest/hash, counts, validation and idempotent repeat-import result. Do not open historical gold/answer files. Private newly generated physical state is adapter-only; no API/tool/reviewer access. Do not run the scorer or a full Stage 3 campaign. Existing `check --ingest` resets its selected session afterward; only run it deliberately on the disposable V3 target, not the presentation candidate.

Create a V3-only launcher under your worktree. Never call `scripts\showcase_backend.ps1`, which stops demo processes. Build `frontend-next` in your root, and select its `dist`. Proposed launcher must validate fresh port 8023 and exact V3 DB/state root; refuse to kill any existing process. Use one Uvicorn process (no auto-reload/multiple-process workers). Background starts use hidden windows.

Set explicit new-process environment: model `openai/gpt-oss:120b`, base `https://ollama.com/v1`, operations DB V3 exact name, state root `C:\Projects\suhail-v3-state\world-v3-20261013`, frontend dist `C:\Projects\suhail-v3-integration\frontend-next\dist`, workers 2, provider in-flight 2 for a confirmed multi-request account or mocks, lease 180 s/heartbeat 15 s. Disable development reset in presentation configuration. Obtain credentials locally without displaying/committing them. `.env` selected 20B at planning time; do not depend on its model default.

Starting a backend may initialize the ledger and start background workers even on first read. Complete exact-target checks BEFORE initialization. For unpaid end-to-end checks, inject deterministic provider doubles through a test-only harness; keep Auto/narration/Canopus/translation provider paths disabled or mocked. Do not set live GPT-OSS Auto on a funded account under general implementation approval.

## Compact verification

Run owner suites for changed modules and existing graph/API/authority/outcome/snapshot gates. From integration's `chat`:

```powershell
uv run python -m unittest tests.test_operations_graph tests.test_operations_authority tests.test_operations_api tests.test_operations_store tests.test_stage_event_batching tests.test_llm_safety tests.test_cross_shipment tests.test_operations_read_model tests.test_investigator tests.test_world_contracts tests.test_v3_concurrency tests.test_v3_provider_gate tests.test_v3_route_evidence tests.test_v3_scenarios -v
```

Add only the actual outcome/materiality modules implicated by merged changes. Run world_build once if generator logic changed. Run proposed two-client Neo4j race suite only after its exact-target guard is satisfied; no silent skips in signoff. Fake drivers cannot establish transaction atomicity. Use a barrier, expiry/reclaim race, failure while peer runs and repeated dispatch counting adapter. Keep approved scratch DB tests isolated.

From integration's `frontend-next`, typecheck, changed unit tests, build and connected mocked-browser tests. Check existing test ports; do not reuse a protected/unrelated server. Then walk `http://127.0.0.1:8023/app/` against your mock-provider backend: two different cases with overlapping work, distinct stages/citations/reviews/authority/executions/outcomes; old-run events ignored; shared route GPS source selection; receipt chronology; innocent/insufficient-evidence behavior. Capture report/screenshots under V3 output only. Run secret scanner and inspect protected Git statuses afterward.

## Bounded live proposal and honest measurements

Do not run paid calls unless the user explicitly approves the concrete proposal: two concurrent 120B case investigations, max 12 calls each and max 24 attempted provider calls in total, including reviewer/repair/retry, with an agreed spend ceiling. Disable narration/Canopus/automatic translation and automatic repeat investigations for that measurement; enforce a shared budget before every actual send. Verify account capacity/balance privately, stop on quota/capacity failure, no follow-on campaign/provider switch.

Record configured/returned model, provider, case/run/role/request IDs, wire start/finish, HEAD, manifest hash, cutoff and outcome. Overlapping HTTP intervals establish concurrent outstanding requests; provider queues can serialize inference. Claim server-side model execution overlap only with corresponding telemetry. If one-request entitlement or no live approval, report a mock-verified engineering candidate with unverified live overlap, not completion of the full V3 target, and use V2 videos as the official live-agent fallback. Full V3 success requires the approved live pair as well as the non-paid correctness gates.

Measure one/two-worker throughput with the same bounded mocked batch and presentation pacing off; report configuration, completed cases, errors and wall time. No accuracy claim. Another live batch needs a new approval.

## Rollback and final report

Freeze features at hour 48; go/no-go by hour 68. Composer Phase C is a required pre-signoff gate: all approximately 6–10 curated development cases have independent source-first notes and an actual-source-ID-cited PASS/REVIEW/FAIL matrix; the original V2 video shipments are read-only references where source evidence is available. Require first-pass notes timestamped/hashed BEFORE the authored test catalogue is disclosed. Missing reference evidence is reported as not checked. Resolve blocking data defects with Sol and UI defects with Composer; rerun only affected rows within the four-hour QA budget and escalate if it cannot be completed. Keep the Day-2 freeze; no new scenario creation to make the audit pass. Rollback only your V3 service/commit/settings. Drain active claims/calls before worker-mode changes. Stop only a PID explicitly created by your V3 launcher and verified against its root/port; do not terminate arbitrary Uvicorn. Use the previous reviewed V3 commit or worker/provider capacity 1; leave V2 database, demo checkouts and videos intact.

Final report: release/bootstrap and merged SHAs, exact changed files, approved contracts, checks with pass/fail/skip, DB/hash/port, evidence of overlap and limits, temporal/GPS/leakage/source checks, retained reviewer/authority/verifier semantics, one-worker rollback, remaining limitations and explicit go/no-go. Hard safety/source failures mean no-go, not a conditional unsafe merge. Preserve final `suhail-video-A-v2.mp4` and `suhail-video-B-v2.mp4`; record any V3 video only to a new separate directory after signoff.

Use the shared checkpoint template at meaningful milestones and immediately on blockers. BGE-M3 remains deferred and disabled. Do not launch an evaluation campaign, redesign frontend or add enterprise features during integration.
