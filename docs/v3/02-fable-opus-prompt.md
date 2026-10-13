# Deliverable 6 — Claude Fable coordinator, with Opus implementation brief

Paste this into one fresh V3 coordination chat in the EXISTING Suhail Claude project. Use Fable for coordination and one focused Opus chat at high effort for backend implementation. Do not start a new Claude project or duplicate existing V3 threads.

You are coordinating the approved Suhail V3 72-hour prototype. Sol owns architecture, dataset/GPS and integration; Composer owns frontend. Read `C:\Projects\suhail-v3-plan-2026-10-13\01-master-plan.md` and `06-contract-examples.json`. The user's approval of that plan must already exist before implementation. If it does not, produce a readiness report and stop. Implementation approval does not authorize paid model calls.

## Verified starting facts

- Protected `C:\Projects\demo`: `fhd` at `4cd43045a1db284e83cd5702d63acf7950492492`.
- Protected `.stage4`: `187ae087a0083dd36192d3653a669b4de706f692`; `backend`, `chat`, `scripts` match fhd.
- Protected `.ui-integration`: `5aab052daead6141bf54fda068f7bd4bdcba3cb2`. The recording UI is `frontend-next`, not root `frontend`.
- No active port-8022 listener was found during the planning snapshot. This is not permission to start/stop or modify that demo.
- Sol bootstraps `C:\Projects\suhail-v3-integration`, imports only committed `frontend-next`, freezes the contract, and creates sibling worktrees. Receive and verify the bootstrap SHA before development.
- Opus branch/root: `v3/concurrency`, `C:\Projects\suhail-v3-concurrency`.
- `OperationsStore.process_one` currently refuses every claim while `OpsControl.worker_claim` is set. `WorkerPool` has one investigation loop. Each graph invocation already owns its Session/tool cache/call budget.
- `_llm.invoke` returns on a deadline while its underlying provider thread may remain active. Do not release provider capacity on caller timeout.
- Root `.env` selects 20B; the recording launcher overrides to 120B. Keep GPT-OSS/LangGraph; explicit 120B belongs in the new V3 launch configuration only.

## Your coordination duties

Create or reuse one dedicated V3 implementation coordination chat in this project, and delegate the following brief to one Opus high-effort development chat using approved platform capabilities. If you cannot create/delegate chats, give the user the brief directly; do not pretend delegation occurred. Keep ownership, dependency state and checkpoint SHAs in a concise board. Do not message unrelated people or platforms.

Confirm that Opus uses its own V3 root and the shared bootstrap SHA. Track Sol's `route_evidence` work and Composer's phases without assigning them to Opus. Composer A can start on the bootstrap; B consumes frozen wire fixtures and later the real Sol dataset. You do not authorize merges: send the reviewed concurrency SHA/checkpoint to Sol through the user's approved channel.

Checkpoint deadlines: hour 4 baseline/design, hour 24 claims/fences, hour 36 two-worker/provider/DB races, hour 48 feature freeze. From hour 48 onward accept defect fixes only. Reserve a hard four-hour Composer Phase C evidence-first review during hours 48–60, before final signoff, using the same Composer branch/thread. Sol provides neutral source packets for every curated case, then releases the isolated test catalogue only after independent notes are finalized. Phase C data defects return to Sol; UI defects stay with Composer. Keep historical evaluation answers and private truth inaccessible to the runtime. Escalate missing real DB race evidence, timeout-capacity errors or file conflicts immediately. Cut polish/scenario breadth first. No policy or correctness shortcuts. Hour 68 is go/no-go; final V2 videos remain fallback.

## Complete Opus brief

Objective: two existing investigator workflows genuinely overlap on different cases, with atomic claims, recoverable wall-clock leases, stale-result fencing, separate review/authority/outcome records and no duplicate simulated operational effect. No new orchestration framework, queue broker or database technology.

Work only in `C:\Projects\suhail-v3-concurrency` on `v3/concurrency`. Verify branch/clean status/bootstrap ancestor and protected paths before editing. Own these files:

- `chat\operations\store.py`, `workers.py`, `schema.py`.
- `chat\llm\pipeline\_llm.py`, `chat\llm\translate.py`.
- Proposed `chat\operations\claims.py`, `provider_gate.py` if useful.
- `chat\tests\test_operations_store.py`, `test_stage_event_batching.py`, `test_llm_safety.py`.
- Proposed `test_v3_concurrency.py`, `test_v3_concurrency_neo4j.py`, `test_v3_provider_gate.py`.

Read the corresponding protected originals for reference. Do not edit Sol's `tools.py`, `cross_shipment.py`, `read_model.py`, `reasoning.py`, `world/*`, or Composer's frontend. `graph.py`, `investigator.py`, backend routes, `.env.example` and launch scripts are Sol-integrator-owned. Request a specific hook/patch with rationale if necessary; do not independently alter them.

### 1. Claims and leases

Keep the existing short `_control(tx, lock=True)` lock for claim/ledger transactions. Remove the single-active flag as an exclusion; under the lock, select one eligible OPEN/REOPENED case and ensure total live claims remain within 1/2 configured capacity. No provider call or adapter I/O inside a transaction. Acquire claims identically for automatic, manual, explicit-case and reanalysis entry points.

Retain case `claim_id`, logical `claim_at`, `last_run_id`, `as_of` and business `state_version`. Add registered per-case `worker_id`, `claim_epoch`, `claim_wall_at`, `claim_as_of`, `lease_expires_at`, `lease_heartbeat_at`; register claim identity on OpsRun for terminal trace fencing. Transactionally increment the epoch for every grant. Wall-clock UTC controls leases; simulation time controls evidence. Default lease 180 s, heartbeat 15 s, injected clock/timing in tests. Heartbeats do not increment case business state_version or alter evidence cutoff.

Every active progress/result/recommendation/execution-intent write must match case/run/worker/token/epoch and a nonexpired lease. An expired owner cannot renew, release its replacement, publish current events or finish after a new claim. Preserve `_material_since_claim`, material versus routine evidence, reanalysis limits and authority checks.

Audit `process_one`, `_record_stages`, `_save_run_trace`, pipeline publication, StageBuffer timer callbacks, global pause, reset, skip-to-event, initialization/restart and operator requests. The current exception handler pauses the global worker; replace that with per-claim failure handling for background worker errors. Intentional user global pause revokes all active claims safely. Reset/skip sees all live claims.

Do not block legitimate terminal events emitted after the finish transaction clears the active claim. Allow them only for that same finalized owned/current run; preserve its final status and committed authority. A terminal event cannot set REVIEWED back to RUNNING. `_save_run_trace` preserves actual writeback decisions. Include a failure timed between finish, StageBuffer flush and trace save in tests.

Expired recovery marks the old run ABORTED and requeues safely. Bound automatic crash attempts to two before human attention; do not fabricate reviewer acceptance or outcomes. Initialize recovery only for expired claims; a healthy peer or another still-valid V3 process must not have its claim stolen. Report single-process deployment assumptions.

### 2. Worker loops and status

Extend existing `WorkerPool` with two independently paced investigation loops; retain other workers. Use separate per-worker pacing state. New env settings: `SUHAIL_INVESTIGATION_WORKERS` default 1, allowed 1/2; `SUHAIL_CLAIM_LEASE_SECONDS` 180; `SUHAIL_CLAIM_HEARTBEAT_SECONDS` 15. Preserve `SUHAIL_WORKER_PACE_SECONDS`; set it to zero only in throughput tests.

No shared mutable investigator Session, messages, tool cache, review history or result accumulator. Reader driver can be shared but sessions/transactions must remain per-operation. Pre-initialize or otherwise safely construct the cached model/reader before loops race. Stop signals must prevent new claims and shut down heartbeats/buffers cleanly without stealing peer state.

Implement the master plan's status projection in `OperationsStore.status` and `case_detail`: additive `worker.active_cases`, `active_count`, configured `concurrency`; legacy active IDs only when exactly one claim is active. Include case/shipment/worker/claim/epoch/run, existing workflow/run/stage values, wall timestamps, immutable `as_of`, state_version and bounded final_result. Sol forwards case-detail projection through the read model. Preserve case/run/sequence SSE identity. Do not expose provider response text or credentials in status.

### 3. Provider capacity

New `SUHAIL_PROVIDER_MAX_INFLIGHT`, default 1, allowed 1/2. Gate both deadline and no-deadline `_llm.invoke` paths at the actual underlying call. A timed-out request still holds its slot until it exits; its late response is discarded. Gate wait is bounded/cancellable, releases exactly once, and cannot create unlimited waiting threads. Retry paths cannot bypass capacity. Preserve contextvars/callbacks and call accounting. Test concurrent cached model construction/use; keep invocation inputs isolated, use per-thread model clients if needed without changing model/provider semantics.

Route translation's direct `model().invoke` through shared invocation. Narration and Canopus already use `_llm.ask_json`; they must count against the same gate. Shared gate is process-local; do not claim it enforces account-wide capacity against other clients. Logs for overlap carry case/run/role/request IDs and start/finish timestamps, not prompt contents. Supply a small instrumented mock harness and a separate live proposal; no cloud calls here.

### 4. Execution and focused gates

Keep execution's existing single worker and stable execution/recommendation/run IDs, approval and dispatch rechecks, adapter replay and independent verification. Prove repeated dispatch/recovery causes one effect in a counting synthetic adapter. Test that stale investigator results cannot create a fresh authorized action. Do not change reviewer rules, `authority.py`, `worker.py` guard, `outcome.py`, `outcome_engine.py`, `materiality.py` or policy semantics.

From `C:\Projects\suhail-v3-concurrency\chat`, run:

```powershell
uv run python -m unittest tests.test_operations_store tests.test_stage_event_batching tests.test_llm_safety tests.test_v3_concurrency tests.test_v3_provider_gate -v
```

Required new behavioral tests: two distinct cases overlap using a barrier, same-case race loses once, expiry/reclaim fences all old write paths, failure leaves peer running, buffers preserve terminal state, paused/accelerated simulation cannot expire/extend a wall lease, duplicate dispatch/restart has one effect, one-worker fallback works, in-flight provider cap holds through caller timeout and later retry, cancellation does not leak permits.

Implement/run real two-client Neo4j race tests against ONLY `shipments-v2-world-v3-ci-20261013` after exact-target protection checks and integrator provisioning. Tests must not silently use an existing V2 CI DB. Coordinate provisioning with Sol; fake driver tests alone cannot prove atomicity. Record skips as outstanding gates.

### 5. Checkpoint, commit and rollback

Commit only owned files on `v3/concurrency`, no secrets/generated answers. Provide exact SHA, diffstat, tests/pass-fail-skip counts, claim/status contract examples, failure/recovery behavior, feature-off config and remaining limitations. Run the secret scanner before sharing. Do not merge/push without the user's authorized workflow; do not touch fhd or protected checkouts.

Fallback is `SUHAIL_INVESTIGATION_WORKERS=1` with provider cap 1 on an isolated V3 process, or the previous integration SHA. Wait for live claims/provider calls to drain before mode changes; don't start a second process against the same ledger to evade a hanging request. No reset of V2 or alteration of its videos.

## Shared checkpoint format

WORKSTREAM:
BRANCH / HEAD:
COMPLETED:
CHANGED FILES:
TESTS RUN / RESULTS:
BLOCKERS:
INTEGRATION DEPENDENCIES:
NEXT ACTION:
READY TO MERGE: YES / NO

Send meaningful checkpoints and blockers to the designated Sol integrator through the user's approved channel. Do not accept a deadline as authorization to change another workstream's design, spend provider credits or merge an unsafe branch.
