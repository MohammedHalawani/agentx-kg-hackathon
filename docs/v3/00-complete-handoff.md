# Suhail V3 — 72-hour execution master plan

Prepared 13 October 2026 (UTC+03:00), approved by the user on 13 October 2026. The implementation remains scoped to the original 72-hour prototype. The initial bootstrap and readiness report precede downstream code changes. Claude/Composer ownership and a separate Sol High dataset task are retained; no Codex subagents are launched from the bootstrap chat. No paid inference, broad evaluation or API migration is authorized.

## Decision

Build a two-worker extension of the existing V2 investigator, expose shared last-mile GPS through the existing evidence infrastructure, and demonstrate four carefully selected scenario families plus an innocent counterexample. Keep GPT-OSS, LangGraph, the reviewer, deterministic authority and outcome verification. Use the committed recording UI under `frontend-next`, not the older root `frontend`.

Retain the short Neo4j `OpsControl` transaction lock for two-worker coordination. Remove its one-active-case restriction and move ownership/leases onto individual cases. A short serialized claim transaction is compatible with parallel model work; removing every global lock is unnecessary for this prototype.

This is a technical prototype. It must demonstrate safe concurrency and source-backed evidence; it does not claim improved diagnostic accuracy, production readiness or physical logistics execution.

## 1. Verified technical baseline — Deliverable 1

### Inputs and inspection limits

Read all three supplied notes:

- [Scope recommendation](<C:/Users/fbass/.codex/attachments/a4338866-322a-4ada-a0d5-069f97c88ec2/Pasted text.txt>).
- [Team coordination recommendation](<C:/Users/fbass/.codex/attachments/500cfe8d-ad73-44ef-a876-e2d799aaddbf/Pasted text.txt>).
- [Master assignment](<C:/Users/fbass/.codex/attachments/9d7b2ec4-29c5-4928-a45a-6014d950aa74/Pasted text.txt>).

The local ChatGPT mirror at `C:\Users\fbass\.codex\.chatgpt-projects\g-p-6aa86b79b414819184f4012e29bebd64\sources` is empty. No unavailable project source is represented as inspected. Repository architecture, contracts, showcase handoff and aggregate evaluation reports provide sufficient evidence for this plan. Synced project sources remain read-only.

During the original planning pass, no application code, environment, branch, database or video was changed, and no tests, model calls, database queries, migrations, app launches, commits, merges or pushes were performed. The approved bootstrap is documented separately in the readiness report. Original inspection used files, Git metadata, selected non-secret configuration values and process/listener inventory. External evaluation answer files and simulator physical-state files were not opened.

### Repository and demonstration source

| Location | Verified state | V3 treatment |
|---|---|---|
| `C:\Projects\demo` | Clean `fhd`, HEAD `4cd43045a1db284e83cd5702d63acf7950492492` | Frozen backend base; no direct changes |
| `C:\Projects\demo\.stage4` | Clean `stage4`, HEAD `187ae087a0083dd36192d3653a669b4de706f692` | Protected recording backend checkout |
| `C:\Projects\demo\.ui-integration` | `claude/project-thread-unq829`, HEAD `5aab052daead6141bf54fda068f7bd4bdcba3cb2`; tracked tree clean; untracked screenshots and `showcase-videos/` | Read-only source for committed `frontend-next` import |
| `C:\Projects\demo-ui` | Clean `ui/suhail-operations-v2`, HEAD `8b86624c4ead51c70a9e7e1921cb26139603504e` | Older separate worktree; do not use as recording UI baseline |

`187ae087...` is an ancestor of `fhd`. `git diff 187ae087... 4cd43045... -- backend chat scripts` is empty. Thus the inspected `fhd` backend/chat/scripts match the recorded stage4 source. The `.ui-integration` commit is not present in the main repository's object database: import it from that local repository after approval.

No listener on ports 8022, 8023 or 8000, and no Python Uvicorn command, appeared during inspection. Consequently, an actively running process's effective source/configuration cannot be certified. The launcher and showcase report establish the recording configuration, not a current live process.

The recording launcher [scripts/showcase_backend.ps1](C:/Projects/demo/scripts/showcase_backend.ps1) points to `C:\Projects\demo\.ui-integration\frontend-next\dist-8022`. Its stop-process behavior makes it unsuitable for V3: do not execute it. [backend/main.py](C:/Projects/demo/backend/main.py) serves the build selected by `SUHAIL_FRONTEND_NEXT_DIST` under `/app/`.

The recorded build exists. Its entry HTML references `index-Ct2BapBv.js` and `index-CD_EZO1c.css`. SHA-256:

- `frontend-next/dist-8022/index.html`: `4D49860B5357829D7E56BC744F5CB6CE9ACD62524E377626D7E12048F24ABF34`.
- `frontend-next/package-lock.json`: `F6A5C9C719903EC710168F7133260C83CA39B78E775CB1E5EF1FE8748FE91BBE`.

These pin inspected artifacts; they do not prove a fresh build is byte-identical. Rebuild only in V3's new checkout and validate compatibility there.

Preserved fallback files:

- `C:\Projects\demo\.ui-integration\showcase-videos\suhail-video-A-v2.mp4`.
- `C:\Projects\demo\.ui-integration\showcase-videos\suhail-video-B-v2.mp4`.

The [showcase handoff](C:/Projects/demo/docs/showcase/README.md) identifies both as the final 59.7-second recordings and explains their simulated execution and edited waiting time.

### Relevant architecture and exact seams

| Verified path/function | Finding and implication |
|---|---|
| [workers.py:WorkerPool](C:/Projects/demo/chat/operations/workers.py) | Five independent worker loops; exactly one investigation thread, one shared `_last_case` pacing timestamp. Add two bounded investigation loops with separate pacing. Keep ingestion, monitor, execution and verification. |
| [store.py:process_one](C:/Projects/demo/chat/operations/store.py:1292) | Short claim transaction locks `OpsControl`, then returns early whenever `worker_claim` exists. Case claim token and `last_run_id` already exist. Model work runs outside that transaction. |
| [store.py:_record_stages](C:/Projects/demo/chat/operations/store.py:1527) and [_save_run_trace](C:/Projects/demo/chat/operations/store.py:1558) | Buffered pipeline events and traces write separately from final disposition. Fence all paths; preserve terminal event ordering and final run state. |
| [store.py:_approval_check](C:/Projects/demo/chat/operations/store.py:1849), [_dispatch_check](C:/Projects/demo/chat/operations/store.py:1883), [execute_step](C:/Projects/demo/chat/operations/store.py:1164) | Approval/dispatch rechecks, recommendation linkage and execution idempotence exist. Reuse them; do not replace policy. |
| [graph.py:investigate](C:/Projects/demo/chat/operations/graph.py:499), [investigator.py:Session](C:/Projects/demo/chat/operations/investigator.py:311) | Graph invocation owns its holder, tool belt, conversation, review history and call budget. No new agent framework or shared conversation is needed. |
| [schema.py:FIELDS](C:/Projects/demo/chat/operations/schema.py:21) | Strict ledger property allowlists. Lease fields must be explicitly registered and timestamp handling updated. |
| [llm/pipeline/_llm.py:invoke](C:/Projects/demo/chat/llm/pipeline/_llm.py:171) | Deadline calls run on daemon threads. Caller timeout does not cancel the underlying provider request. A caller-side semaphore released at timeout would undercount active requests. |
| [llm/pipeline/_llm.py:model](C:/Projects/demo/chat/llm/pipeline/_llm.py:126) | Shared cached ChatLiteLLM instance. Establish safe construction/use before concurrency; use invocation-local messages and context. |
| [tools.py:_container_and_trip](C:/Projects/demo/chat/operations/tools.py:1198) | Already retrieves shared trip GPS via `trip_positions`, returns bounded position/stationary summaries and source IDs. GPS is not wholly absent from the investigator. |
| [tools.py:_same_route_run](C:/Projects/demo/chat/operations/tools.py:1120), [cross_shipment.py:QUERIES](C:/Projects/demo/chat/operations/cross_shipment.py) | Route-run context retrieves assignments, custody, attempts, scans, reconciliations and manifests; its query catalogue has no route-run GPS query. This is the principal last-mile gap. |
| [tools.py:_vehicle_and_manifest](C:/Projects/demo/chat/operations/tools.py:760) | Shows GPS in shipment-owned context. World GPS is shared, so this is not a complete last-mile retrieval path. |
| [read_model.py:OperationsReader.evidence](C:/Projects/demo/chat/operations/read_model.py:396), `fetch` | Bounded owned/shared context plus a fixed, parameterized cross-shipment port. Reuse temporal/split fencing. |
| [reasoning.py:route_layers](C:/Projects/demo/chat/operations/reasoning.py:205) | Existing expected, actual, vehicle, custody, facility, attempt and traffic layers. Actual route means corroborated custody stops, not a measured parcel track. |
| [world/observe.py:Observer.gps](C:/Projects/demo/chat/world/observe.py:997) | GPS carries route/trip, vehicle, coordinates, accuracy, speed, source and `VEHICLE_ONLY` semantics. |
| [operations/ingestion.py:Gateway](C:/Projects/demo/chat/operations/ingestion.py) | `occurred_at` is event time; gateway `recorded_at` is receipt/visibility time; `ingested_at` is processing tick. Feed `deliver_at` determines availability. Preserve all three. |
| [operations/identifiers.py](C:/Projects/demo/chat/operations/identifiers.py) and `backend/operations_api.py:invoke` | Storage IDs are `DEMO-*`; HTTP IDs are `SYN-*`. Translation is reversible. Cursors/tokens have special handling. Do not rewrite database IDs. |
| [world/build.py](C:/Projects/demo/chat/world/build.py), [world/config.py](C:/Projects/demo/chat/world/config.py), [world/export.py](C:/Projects/demo/chat/world/export.py) | Existing causal logistics world, seeded generation, time-cut V2 export and isolated import. Expand this universe. |
| `frontend-next/src/api/contracts.ts`, `api/adapters.ts`, `services/api-operations.ts`, `domain/types.ts`, `pages/operations.tsx` in `.ui-integration` | Current wire adapters and state assume a single `activeCaseId`. Composer must consume `active_cases` and maintain separate per-case streams. |
| `frontend-next/src/components/route-map.tsx`, `network-map.tsx`, `knowledge-graph.tsx` in `.ui-integration` | Existing map and graph should be extended. Current GPS adapter fabricates a fallback UI key when source ID is absent; V3 must require a source ID for evidence interaction. |

### Configuration and historical evidence

Both inspected root `.env` files (main and stage4) select `openai/gpt-oss:20b` with `https://ollama.com/v1`. The showcase launcher explicitly overrides to `openai/gpt-oss:120b`. V3 must explicitly set 120B in its own environment; do not copy the file and assume the effective model. Credentials were not displayed.

The account's Ollama subscription and remaining balance were not inspected. Current [Ollama concurrency documentation](https://ollama.com/pricing) lists Free=1, Pro=3, Max/Team=10 simultaneous requests; over-limit calls can queue. These published limits do not establish the user's entitlement or prove server-side execution overlaps. Keep the provider unchanged and verify the actual account before any approved live test. The application gate only controls this V3 process, not other account clients.

The [Stage 3 aggregate report](C:/Projects/demo/docs/evals/2026-10-11_stage3/report.md) supports the E1 identifiable-ambiguous comparison: agent 81/119 (68.1%), rules 92/119 (77.3%), historical median 40.9 seconds. The full campaign was invalid because provider quota failures exceeded its bar; E2 and defective no-tools/ablation results must not be reported as valid. Do not extrapolate an accuracy gain from V3 throughput.

The supplied 39-eligible-precedent figure remains a historical supplied figure; no new DB census was performed. V1 BGE-M3 plumbing exists in `chat/config.py` and `chat/llm/pipeline/retrieve.py`; V2 uses `OperationsReader.historical_precedents` and its structural `PRECEDENTS` query. Pending, unverified or invalidated cases are not new eligible precedents.

## 2. Priorities and dependencies — Deliverable 2

| Rank / work | Hackathon value | Difficulty / risk | Dependency / owner |
|---|---|---|---|
| P0: isolated baseline, UI import, contracts | Enables all work | Low-medium / high impact if wrong | Sol integrator; first 4 hours |
| P1: case leases, fencing, failure isolation | Essential correctness | High / high | Opus; seeded mocked cases |
| P1: two worker loops and provider gate | Main architecture improvement | Medium-high / high | Opus after claim design |
| P1: real Neo4j race and duplicate-dispatch proof | Release gate | Medium / high | Opus + Sol; new scratch DB |
| P2: shared route GPS and temporal/source checks | Meaningful reasoning and map improvement | Medium / medium-high | Sol; existing fetch port |
| P2: four scenario refinements and counterexample | Convincing evidence stories | Medium / medium | Sol; existing mechanism world |
| P3 A: current UI discovery/preparation | Removes obsolete-baseline risk | Low / low | Composer; baseline only |
| P3 B: route/source visuals and active-case list | Clear demonstration | Medium / medium | Composer; approved contract examples, then real Sol data |
| Optional: semantic precedent retrieval | Unmeasured | Medium-high / medium-high | Defer beyond this assignment |

Critical path: approved baseline → leases and fencing → two-worker/provider behavior → real Neo4j races → integrated two-case run. GPS/UI proceed alongside it. Composer A starts immediately; B starts after the contract is approved and fixtures are available, without waiting for the full dataset.

## 3. Frozen architecture and interfaces — Deliverable 3

Frozen approved version: `suhail-v3-1`. User approval adopts this contract. Composer Phase C adds a QA/signoff gate without changing wire fields. Implementers may clarify an ambiguity with Sol; they may not independently rename wire fields or expand scope.

### Concurrency design

One FastAPI process and one Neo4j operations ledger; no extra broker. Two named investigation `Worker` loops call the existing `process_one`. A short `OpsControl` write lock serializes candidate selection, capacity checks and ledger transitions. Model calls, adapter I/O and waits stay outside write transactions. Preserve existing transactional materiality/authority checks; do not add large GPS reads to claim transactions. This reuses Neo4j's documented dependent-property write-lock mechanism ([Neo4j documentation](https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/)).

Add per-case `worker_id`, `claim_epoch`, `lease_expires_at`, `lease_heartbeat_at`, `claim_wall_at` and `claim_as_of`. Keep existing `claim_id`, `claim_at`, `last_run_id`, `as_of`, `state_version`. Register fields on `OpsCase`; put claim identity on `OpsRun` for terminal trace fencing. `claim_at` retains its existing logical-time meaning. Lease timestamps use authoritative wall-clock UTC, not the simulation clock, which can pause/accelerate. Default lease 180 seconds and renewal every 15 seconds; both injectable in tests. Renewal must not alter business `state_version`, evidence counters or snapshot cutoff.

Increment `claim_epoch` transactionally for every ownership grant. Retain stable run identity derived from the case and unique claim token. Check case, run, worker, token, epoch and nonexpired lease before active progress, result, recommendation and execution-intent writes. An expired token cannot renew, release the new owner, publish current status or overwrite any current decision. Keep existing materiality and reanalysis behavior.

Progress buffered by `StageBuffer` and terminal events after `finish` require special handling: active events need a live claim; legitimate postcommit terminal events may append only to that same finalized owned run while it is current. They cannot set a finalized run back to `RUNNING`, modify its authority or reopen a case. `_save_run_trace` must preserve the actual committed authority/disposition and reject superseded owners. Test this ordering explicitly.

On worker failure, abort/release only its own matching claim; its peer continues. Recovery marks the old run `ABORTED`, increments the epoch and requeues through the existing `OPEN` lifecycle. Bound crash recovery attempts (two automatic attempts per case before human attention); do not invent a successful review/outcome. A user-issued global pause remains a deliberate global operation: revoke active claims safely and fence their late results. Reset/skip checks must inspect all live claims, not a leftover single flag.

Execution stays on its existing single loop. Preserve stable execution IDs, recommendation/run linkage and adapter replay handling; demonstrate no duplicate simulated effect under replay/restart. Do not claim exactly-once external execution from this prototype.

New settings (proposed, absent from V2):

| Setting | Default / range | Meaning |
|---|---|---|
| `SUHAIL_INVESTIGATION_WORKERS` | 1 / 1 or 2 | Two-worker feature switch; 1 is fallback |
| `SUHAIL_PROVIDER_MAX_INFLIGHT` | 1 / 1 or 2 | Maximum underlying V3 provider calls |
| `SUHAIL_CLAIM_LEASE_SECONDS` | 180 / bounded positive | Lease lifetime |
| `SUHAIL_CLAIM_HEARTBEAT_SECONDS` | 15 / less than lease/3 | Renewal cadence |

Implement the shared provider gate at `_llm.invoke`, including both deadline and no-deadline paths. Acquire inside the actual provider-call execution and release only when that underlying call exits. Caller timeout never frees its slot early. Waiting for a slot is bounded and cancellable; late responses remain discarded. Avoid unbounded waiting threads/retries if a provider hangs. Preserve contextvars. Test safe model client construction/thread use. Route the direct `llm/translate.py:model().invoke` path through the same plumbing, without changing translation semantics. Narration and Canopus already use `_llm.ask_json`; count them too. Disable their calls only for the controlled overlap measurement, then verify normal feature compatibility with mocks.

### Investigation status

Extend existing `GET /worker/status` at `worker.active_cases`; keep its other fields and the `workers` heartbeat map. Add the same status projection under `GET /cases/{id}` as `investigation_status`. Sol owns read-model wiring for the latter; Opus provides `OperationsStore.case_detail`'s projection. No new status endpoint.

`active_cases` is a sorted array of current, unexpired claims only. It is authoritative for V3. Legacy `active_case_id`/`active_shipment_id` are populated only when exactly one claim is active, otherwise null. `concurrency` reports configured capacity; `active_count` reports actual live claims. A client must not infer activity from capacity.

Status fields: `case_id`, `shipment_id`, `worker_id`, `claim_id`, `claim_epoch`, `workflow_state` (unchanged V2 enum), `run_id`, `run_status` (`QUEUED`, `RUNNING`, `REVIEWED`, `ABORTED`, `FAILED`), `active_stage` (existing graph stage key or null), `started_at`, `updated_at`, `lease_expires_at` (wall UTC), `as_of` (immutable source cutoff), `state_version`, `final_result` (null until finalized; bounded workflow/review/outcome summary). Event ordering remains per case/run/sequence; no global sequence is required. SSE payloads retain `run_id` and reject stale runs in the client.

The valid synthetic wire example is in [06-contract-examples.json](06-contract-examples.json). Storage uses `DEMO-*`; this HTTP example correctly uses `SYN-*`. [08-interface-reference.md](08-interface-reference.md) defines field types, bounds and optional/null behavior; these examples are not an importable V2 bundle.

### Route/GPS evidence

Add `chat/operations/route_evidence.py` with a shared pure projection `build_route_evidence(context, fetch, *, max_points=160, max_runs=4)`. `context` is the existing shipment evidence at a fixed cutoff. The callable `fetch(name, **params)` uses the existing validated port and must apply that cutoff. It returns a bounded record-backed route view, not a diagnosis. No reads of private simulator state or scenario answers.

Sol adds a fixed `route_run_positions` query beside `trip_positions`, reusing dataset/split/time predicates. Validate the referenced route/trip against this shipment's visible assignment, custody, attempt or manifest before fetching. Reject unrelated runs/vehicles; restrict positions to the connected vehicle and valid assignment/transport interval. No unrestricted vehicle expansion.

Use a 161-row sentinel for a maximum 160-point UI result, with an explicit truncation flag. Maximum four connected transport contexts. If multiple contexts exist, allocate the bound deterministically, retaining earliest/latest and important recorded event boundaries; disclose sampling and gaps. The model tool returns at most 12 selected points plus concise counts/timing facts, under existing 6,000-character/30-row/120-citation limits. Missing coordinates, assignments, plans or traffic stay absent/unknown. No inferred detour/misconduct diagnosis from a stop.

Expose `route_evidence` as an additive top-level field on shipment/case detail, with `schema`, `shipment_id`, `as_of`, `contexts`, `observations`, `summary`, `source_nodes`, `source_relationships`, `truncated`. Each context carries actual route/trip/assignment/vehicle/device IDs (nullable when genuinely unavailable), assignment interval, plan source IDs and custody/load source IDs. Observations carry `evidence_id`, `entity_id`, `vehicle_id`, route/trip context, `lat`, `lng`, `accuracy_m`, `speed_kmh`, `occurred_at`, `recorded_at`, optional `ingested_at`, `source_ref`, `position_scope`, `classification: observed_vehicle`, and nullable `source_event_id`.

`summary` contains factual counts, observed time range, bounded stationary intervals or planned-versus-observed timing comparisons, with exact `input_evidence_ids`. It must not contain a scenario name, cause label, claimed delivery, unsupported traffic explanation or accuracy claim. Compute a delay only from a visible planned window and a matching observed milestone. Without road geometry, draw expected connections and observed samples without claiming an exact road deviation. A planned future window is permitted as a plan; a future observation is not.

`source_nodes` use the existing `{id, kind, properties}` evidence shape; relationships use `{id, kind, start, end, properties}`. Return actual records/edges only. Metadata may be selected/allowlisted but never invented. The graph can highlight an isolated source node if no real connecting edge is retrievable; do not fabricate an edge. This route field lets graph/map resolve shared GPS sources without expanding the main shipment context indiscriminately.

Populate existing `route_layers.layers.vehicle_path` from this same projection at the same detail `as_of`. Extend points additively with recorded time/source/accuracy/transport identity. Preserve every other existing layer and its meaning. `actual_route`/`custody_points` stay corroborated parcel evidence. At a given cutoff, map, graph and investigator use the same source IDs/projection; model sampling can be a disclosed subset. Existing UI detail can follow the live clock while a run stays at its older snapshot. Label both cutoffs, and never present later UI sources as evidence used by the earlier run.

Register one `route_observations` tool in `InvestigationTools.CATALOG`. It uses the helper through `_fetch`, registers returned shared sources via `_remember`, and comparisons via `_compute`. Cite only sources present in the rendered result. Preserve existing trip tools; do not duplicate them or change reviewer rules. Existing `external`/evidence-index machinery supplies those records to the reviewer.

### Dataset/scenario fixture contract

Use V2 `Node`, `Edge`, provenance, typed timestamps, fixed seed and hashes. Storage dataset ID: `DEMO-SUHAIL-WORLD-V3-20261013`; HTTP ID is its `SYN-*` view. Use four refinements, not a new cause taxonomy:

| Family | Reuse verified mechanism | Required evidence exercise |
|---|---|---|
| Buffered delivery device, shared across 2–3 shipments | `DEVICE_OUTAGE` / `PARTIAL_UPLOAD_LOSS` | Before receipt: missing records/telemetry uncertainty; after receipt: old occurrence times become visible with later receipt. Independent case/review/outcome records. |
| Recipient disputes a delivery with strong proof | `CUSTOMER_COMPLAINT` / `NEIGHBOUR_RECEIVES` | Attributed report versus bound handoff/authentication/proof. Human review remains legitimate despite strong proof. |
| Photograph without successful OTP | `OTP_NOT_RECEIVED` | Photo plus absent/failed authentication; supporting context cannot certify delivery. Include an insufficient-evidence snapshot. |
| Route delay with actual vehicle observations | `TRAFFIC_DISRUPTION` / `LATE_LINEHAUL` | Source-backed route observations and planned windows; connect traffic only where records support it. |
| Innocent counterexample | Existing ordinary journey variation and schedule slack | Vehicle stop within expected journey window; no planted fault label, blame or automatic loss inference. |

First reproduce the existing 240-shipment test-world configuration (`seed=11`, `uniform_rates(.012,.012)`) as a compatible test substrate; do not start a larger generation campaign. Develop a scoped scenario-profile entry point using existing bookings/mechanisms/physical/observation generation. Limit curated new/refined stories to approximately 6–10 development shipments (shared family included). Background shipments can remain from that substrate; do not add hundreds of new shipments. If full-world coverage validation requires the existing substrate, keep it rather than weakening the validator to force a tiny world to pass. No repeated blind seed search; bound selection attempts and report missing coverage.

Use a label-free runtime fixture manifest with stable IDs, seed, content hashes, source IDs and replay cutoffs. Keep the scenario catalogue, expected temporal behavior, allowed outcomes and test-only expected findings outside the import/HTTP/retriever paths. Generated scoring truth remains an external opaque artifact; do not inspect or use historical evaluation answers to choose cases. Tests may assert operational evidence properties without feeding expected answers to the investigator.

Fixture times must satisfy `occurred_at <= recorded_at <= ingested_at` after gateway processing. The raw provider send timestamp and feed delivery timestamp retain their original meanings; do not back-date gateway `recorded_at` to a provider send time. Records become visible only once received. Filter nodes AND edges for scope and time. Deduplicate by source event identity; no synthetic proof fabricated to make a story resolve.

Scratch locations, proposed and not created during planning:

- Data: `C:\Projects\suhail-v3-data\world-v3-20261013`.
- Physical simulation state: `C:\Projects\suhail-v3-state\world-v3-20261013` (adapter only).
- External generated evaluation artifacts: `C:\Projects\suhail-v3-private\world-v3-20261013` (never runtime/tool/API imports).
- Development DB: `shipments-v2-world-v3-20261013`.
- Race-test DB: `shipments-v2-world-v3-ci-20261013`.

The `shipments-v2-world-*` prefix is deliberate: `operations/datasets.py` and `world/export.py` already permit it. Do not introduce `shipments-v3-*` and then broaden database guards. No V2 DB replacement or `--replace` on an existing DB.

## 4. Branches, worktrees and ownership — Deliverable 4

Use the user's proposed `v3/*` names. None appeared in the inspected main branch inventory; recheck immediately before creation. Worktrees must be siblings under `C:\Projects`, outside every protected checkout.

| Branch | Directory | Owner / ancestry |
|---|---|---|
| `v3/integration` | `C:\Projects\suhail-v3-integration` | Sol; starts at pinned `fhd`, imports committed recording UI |
| `v3/concurrency` | `C:\Projects\suhail-v3-concurrency` | Opus; starts from reviewed integration bootstrap commit |
| `v3/scenarios` | `C:\Projects\suhail-v3-scenarios` | Sol dataset; same bootstrap commit |
| `v3/route-ui` | `C:\Projects\suhail-v3-route-ui` | Composer; same bootstrap commit |

After approval, Sol runs this sequence. Abort on changed HEAD, dirty baseline, existing conflicting destination or branch; reuse a suitable existing V3 worktree only after verifying its ancestry. Do not reset an existing branch.

```powershell
Set-Location C:\Projects\demo
git status --short --branch
git rev-parse HEAD
git branch --list 'v3/*'
git worktree list --porcelain
git worktree add -b v3/integration C:\Projects\suhail-v3-integration 4cd43045a1db284e83cd5702d63acf7950492492
Set-Location C:\Projects\suhail-v3-integration
git fetch --no-tags C:\Projects\demo\.ui-integration 5aab052daead6141bf54fda068f7bd4bdcba3cb2
git restore --source=FETCH_HEAD --staged --worktree -- frontend-next
git diff --cached --stat
git diff --cached --name-only
git commit -m "chore(v3): establish committed recording frontend baseline"
```

Only committed `frontend-next` content is restored. No whole-branch merge, `.env`, `dist-8022`, untracked screenshots or videos are copied. Existing committed screenshots within that subtree can be retained; Composer need not edit them. Inspect the staged list and source lockfile before committing. The protected origin checkouts remain unchanged; Git worktree/ref metadata changes occur only after approval.

Then copy the approved contracts/plan into `docs/v3/` in integration, create the sibling worktrees from the resulting bootstrap HEAD, and record that SHA for all owners:

```powershell
Set-Location C:\Projects\demo
git worktree add -b v3/concurrency C:\Projects\suhail-v3-concurrency v3/integration
git worktree add -b v3/scenarios C:\Projects\suhail-v3-scenarios v3/integration
git worktree add -b v3/route-ui C:\Projects\suhail-v3-route-ui v3/integration
```

Build imported `frontend-next` and run its current mocked adapter/connected smoke checks before calling the bootstrap ready. This proves baseline compatibility; visual parity still needs one isolated browser walkthrough. Do not rebuild a protected source tree.

### Exact file ownership

All paths below are relative to each owner's V3 root; the earlier absolute paths are read-only references. New files are explicitly marked proposed.

| Owner | Writable files |
|---|---|
| Opus | `chat/operations/store.py`, `workers.py`, `schema.py`; `chat/llm/pipeline/_llm.py`, `chat/llm/translate.py`; proposed `chat/operations/claims.py`, `chat/operations/provider_gate.py`; `chat/tests/test_operations_store.py`, `test_stage_event_batching.py`, `test_llm_safety.py`; proposed `test_v3_concurrency.py`, `test_v3_concurrency_neo4j.py`, `test_v3_provider_gate.py` |
| Sol dataset/GPS | `chat/world/config.py`, `mechanisms.py`, `schedule.py`, `physical.py`, `observe.py`, `build.py`, `validate.py`, `pipeline.py`, `export.py` only where a scenario refinement requires them; `chat/operations/tools.py`, `cross_shipment.py`, `read_model.py`, `reasoning.py`; proposed `route_evidence.py`, `chat/world/v3_scenarios.py`; `chat/tests/world_fixture.py`, `test_cross_shipment.py`, `test_operations_read_model.py`, `test_investigator.py`, `test_world_build.py`, `test_world_contracts.py`; proposed `test_v3_route_evidence.py`, `test_v3_scenarios.py` |
| Composer | `frontend-next/src/api/contracts.ts`, `api/adapters.ts`, `services/api-operations.ts`, `domain/types.ts`, `state/operations.tsx`, `pages/operations.tsx`, `pages/investigation.tsx`, `components/route-map.tsx`, `network-map.tsx`, `knowledge-graph.tsx`, `investigation-record.tsx`, `src/styles/workspace.css`; `frontend-next/tests/unit/api-adapters.test.ts`, `api-service.test.ts`, `tests/fixtures/backend.ts`, `tests/e2e-backend/backend-stub.ts`, `connected.spec.ts`; proposed `tests/e2e-backend/v3-evidence.spec.ts`, `v3-concurrency.spec.ts` |
| Composer Phase C | Same `v3/route-ui` branch/chat; evidence-first notes and case-audit matrix under `docs/v3/case-qa/` only. Read-only source/chronology review; no dataset edits. UI fixes remain in Composer-owned files. Sol alone repairs data and provides full-dataset structural validation. |
| Sol integrator only | `backend/operations_api.py`, `backend/main.py`, `chat/operations/graph.py`, `investigator.py`, `checks.py`, `datasets.py`, `ingestion.py`, `chat/dataset_v2/contracts.py`, `.env.example`, proposed `scripts/v3_backend.ps1`, `scripts/v3_smoke.py`, `docs/v3/*` |

`read_model.py` belongs to Sol: Opus supplies status from store; Sol adds the one forwarding field. `tools.py` belongs to Sol: concurrency reuses it unchanged. `graph.py` and `investigator.py` are integration-owned and ordinarily remain unchanged; request a narrowly justified hook instead of editing them concurrently. Sol's route helper avoids a need to change the graph. Do not change `authority.py`, `worker.py` safety guard, `outcome.py`, `outcome_engine.py`, `materiality.py`, policy definitions, reviewer instructions or verification semantics. If a requested schema extension becomes unavoidable, Sol reviews it first and owns the edit.

Each owner stages only owned paths. Changes to a shared file require an ownership handoff recorded in the checkpoint; nobody cherry-picks a patch into a peer's live checkout. Merge scenarios first, concurrency second, UI third into integration, reviewing exact SHAs. Integrator owns conflicts; do not choose an entire side blindly. Feature-off rollback means a new V3 one-worker process or prior integration commit, never a V2 reset.

## 5. 72-hour schedule — Deliverable 5

| Elapsed time | Opus / Fable | Sol | Composer | Required gate |
|---|---|---|---|---|
| 0–4 h | Read contract; design claim paths | Bootstrap/pin UI; distribute contract fixtures | Phase A starts on new UI branch | One baseline SHA, ownership, scratch targets |
| 4–16 h | Claim epoch, wall leases, finish/progress fences | Verify scenario reuse; implement shared route query/helper | Audit adapters/map/graph/status; prepare bounded changes | Claim/temporal contract frozen |
| 16–24 h | Failure/recovery and StageBuffer tests | First deterministic profiles + GPS tests | Phase A report; Phase B on approved fixtures | Day 1 checkpoint, no shared edits |
| 24–36 h | Two workers, pacing, provider orphan-call gate | Export/validate scratch dataset; read-model map sources | Route overlays/source details, two-active-case state | Overlap with mocked model, first DB races |
| 36–44 h | Finish real DB races/dispatch replay | Review branch SHAs; begin first controlled merges | Adapter/mock browser gates and build | Integration candidate |
| 44–48 h | Fix critical issues | Merge approved work; isolated app walkthrough | Verify two-case/source interactions | **Feature freeze at hour 48** |
| 48–60 h | Fix defects only | Focused regression, scratch DB/source integrity; supply neutral QA packets and sealed test catalogue | Browser fixes and **Phase C within a hard 4-hour budget** | Every curated case reviewed before signoff |
| 60–68 h | Final checkpoint | Final signoff, throughput/capacity report | Short V3 video if stable, new output path | Go/no-go by hour 68 |
| 68–72 h | Buffer | Preserve release SHA and rollback config | Presentation check | Use final V2 videos if any hard gate fails |

Stopping criteria: by hour 24, if claim fencing cannot be demonstrated, limit UI work to Phase A and do not expand scenarios. By hour 36, if the provider gate or real DB race proof is missing, mark live V3 at risk and continue deterministic verification. At hour 48, cut extra scenarios/polish. At hour 68, unresolved duplicate claim/action, stale write, temporal leak, source fabrication or reviewer/authority regression means no-go. Do not weaken tests/policy to meet the deadline.

## 6–10. Individually copyable execution prompts — Deliverables 6–10

The following standalone prompts contain their own baseline, scope, paths, objectives, checks and outputs. They are also included in the combined [00-complete-handoff.md](00-complete-handoff.md).

6. [Fable coordinator with complete Opus technical brief](02-fable-opus-prompt.md).
7. [GPT-6 Sol dataset and GPS implementation](03-sol-dataset-prompt.md).
8. [Composer Phase A discovery](04-composer-phase-a-prompt.md).
9. [Composer Phase B implementation](05-composer-phase-b-prompt.md).
10. [Final Sol integration](07-sol-integration-prompt.md).

These are handoff artifacts, not messages dispatched to other agents. Keep the requested role/model labels; platform availability is not verified here. Do not create redundant chats simply to fit the labels. Implementation starts only after explicit approval of this plan. Approval of implementation does not authorize paid calls or a full evaluation campaign.

Composer now has an additional [Phase C independent case-evidence/storyline QA prompt](09-composer-phase-c-prompt.md). The same Composer thread/worktree conducts it after map/frontend implementation and before integration signoff. The [updated ownership and milestone addendum](11-approved-coordination-addendum.md) is part of the approved execution handoff.

## 11. Progress reporting — Deliverable 11

Fable maintains one concise status board; Sol owns merge decisions. Owners report at hour 4/24/36/48, at each merge-ready milestone, and immediately on a blocker or contract conflict. No need for continuous narrative updates. Send reports through the user-approved coordination channel; no automated cross-platform messaging is assumed.

```text
WORKSTREAM:
BRANCH / HEAD:
COMPLETED:
CHANGED FILES:
TESTS RUN / RESULTS:
BLOCKERS:
INTEGRATION DEPENDENCIES:
NEXT ACTION:
READY TO MERGE: YES / NO
```

Include exact commands, pass/fail/skip counts and report paths inside the tests line or linked report. A skipped DB race is not a pass. Flag mock-only overlap explicitly. Contract changes need the old/new field and affected owner. Fable cannot authorize a merge, policy change, paid test or protected-demo modification.

## 12. Tests and go/no-go — Deliverable 12

### Compact verification sequence

Run relevant existing unit suites once per material change; use deterministic provider doubles. Proposed new tests are release-specific behavioral/race tests, not mirrored implementation tests. New worktrees do not inherit `.env`: provide required configuration privately in each isolated environment, or copy the existing ignored root `.env` read-only into the new root and explicitly override model/database settings for that process. Never print credentials or stage `.env`. Offline suites use mocks; a model setting is not authorization to send calls.

Opus, from `C:\Projects\suhail-v3-concurrency\chat`:

```powershell
uv run python -m unittest tests.test_operations_store tests.test_stage_event_batching tests.test_llm_safety tests.test_v3_concurrency tests.test_v3_provider_gate -v
```

Sol, from `C:\Projects\suhail-v3-scenarios\chat`:

```powershell
uv run python -m unittest tests.test_cross_shipment tests.test_operations_read_model tests.test_investigator tests.test_world_contracts tests.test_v3_route_evidence tests.test_v3_scenarios -v
```

Run `tests.test_world_build` once when generator logic changes (it builds a shared 240-shipment world); reuse its fixture rather than rebuilding per test. Tests involving generated truth may produce opaque files but must not expose answer values to tools/model inputs.

Composer, from `C:\Projects\suhail-v3-route-ui\frontend-next`:

```powershell
npm.cmd ci
npm.cmd run typecheck
npm.cmd test -- tests/unit/api-adapters.test.ts tests/unit/api-service.test.ts
npm.cmd run build
npm.cmd run test:e2e -- tests/e2e-backend/connected.spec.ts tests/e2e-backend/v3-evidence.spec.ts tests/e2e-backend/v3-concurrency.spec.ts
```

Check ports 5191/5190 before test/dev launch. The current Playwright config reuses servers; make tests refuse an unrelated server or choose a fresh isolated port. Do not attach to a protected UI. Live UI tests are opt-in and can start investigations; they are not automatically free/read-only.

Integrator runs existing `test_operations_graph`, `test_operations_authority`, `test_operations_api`, applicable outcome/snapshot regression modules, the changed-owner suites, and a real Neo4j two-client race fixture on `shipments-v2-world-v3-ci-20261013`. Its harness must fail closed unless this exact isolated target is confirmed. No full Stage 3 run. Run the secret scanner before a reviewed commit is shared. Record actual skips.

### Required gates

| Gate | Evidence required |
|---|---|
| Independent two-case overlap | Barrier-controlled concurrent investigator/provider doubles with distinct session objects, tools, run IDs, reviewer/authority/outcome records and separate stage streams |
| Atomic claims | Two real Neo4j clients race for one case; exactly one owner. Two different eligible cases can be claimed together. Fake-driver tests alone are insufficient. |
| Lease recovery/fencing | Expiry during a blocked provider call; new owner succeeds, old owner cannot renew/progress/finish/release/alter action intent. Leases work with a paused/fast simulation clock. |
| Peer isolation | One worker throws/crashes; the other completes. Global pause/reset behavior is separately intentional and tested. |
| Provider capacity | Maximum underlying in-flight calls never exceeds configured gate, even after caller timeout/retry. Waiting/cancellation bounded; no leaked permits. |
| Execution integrity | Repeated approval/dispatch/restart returns one execution/effect in the synthetic adapter, with preserved review and verifier semantics |
| Dataset/temporal integrity | Existing schema validation, stable repeated hashes, isolated import, source references and relations resolve; before-receipt and after-receipt snapshots differ correctly; late arrival never alters earlier evidence |
| No answer leakage | Runtime import/HTTP/tools/reviewer cannot reach scenario catalogue, expected findings, truth/private state, held-out split or future observations; test positive control detects a planted forbidden test field |
| GPS | Shared route GPS now retrievable and citable, foreign runs refused, exact source IDs/time/vehicle preserved, no GPS-only parcel custody/delivery conclusion |
| UI | Imported recording design retained; planned connections/observed vehicle samples/custody distinguishable; missing data remains missing; source selection resolves graph records; active cases and SSE streams never swap |
| Composer Phase C | All approximately 6–10 curated development shipments have a source-ID-cited PASS/REVIEW/FAIL row, with immutable evidence-first notes recorded before catalogue comparison. Original video shipments SYN-SHP-000304 and SYN-SHP-000443 reviewed read-only where source evidence is available; unavailable evidence is recorded as not checked, not passed. Dataset/UI defects have assigned owners. |
| Integration | Isolated port 8023 and V3 data/state only; compatibility/fallback tested; fhd/protected checkout status and video files unchanged |

### Live model gate (propose separately, never run under this planning approval)

After every mocked and DB gate passes, request approval for exactly two concurrent GPT-OSS 120B investigations, cap 12 calls each, maximum 24 attempted provider calls including reviewer and repair calls. Instrument actual wire-call starts/finishes with case/run/role/request IDs. Disable narration/Canopus/automatic translation calls for this measurement and enforce a separate shared live budget; do not let later automatic reanalysis exceed it. Stop on a capacity/quota error. Preserve model/provider, no retry campaign. Capture configured model and response model, database, manifest hash and HEAD. Pricing/cost ceilings must be agreed before the run; current subscription credit cannot be assumed.

Overlapping client HTTP intervals prove concurrent outstanding requests, not necessarily provider GPU overlap if requests are queued. With a confirmed multi-request entitlement and two successful overlapping responses, describe the evidence precisely as overlapping provider requests. Claim server-side inference overlap only if provider telemetry establishes it. If entitlement is one request or no paid approval is given, retain a mock-verified engineering candidate with live model overlap unverified; use V2 for the official live-agent demonstration. Do not mark the full V3 success target achieved from mocks alone.

Throughput: compare a fixed mocked batch at one/two workers with identical fixtures/provider behavior and record wall time/completed count/errors. An optional second live batch requires separate approval; a single live pair cannot support a robust throughput/accuracy claim. The historical 40.9-second figure is a planning reference only, not a new benchmark.

### Go/no-go and acceptable incompleteness

**GO for the requested successful V3 technical prototype** only when all correctness, real DB, temporal, source and UI gates pass AND the separately approved two-case live pair succeeds with distinct GPT-OSS investigation/review records and honest provider-overlap evidence. Record a release SHA. A mock-only result may be a reviewed engineering candidate, but is not completion of the user's full V3 success target. A presentation claiming simultaneous server-side inference additionally needs corresponding provider telemetry; otherwise describe concurrent outstanding model requests precisely. Always retain V2 videos.

Can remain incomplete: five-plus workers, distributed recovery, semantic retrieval, perfect map road geometry, exhaustive scenarios, extended visual polish, enterprise integrations and diagnostic accuracy improvement. Keep return-scan refinements for later unless one of the four curated families naturally covers them.

**NO-GO** for V3 if safety/evidence gates fail, the app requires a protected checkout/database change, baseline UI compatibility is unresolved, or the only overlap evidence is two labels on one serial process. Present final V2 videos, optionally explain the separately verified V3 progress. Do not merge unsafe code for a deadline.

## BGE-M3 decision gate

Defer and keep disabled in V2/V3. V1's reusable embedding/vector/RRF code is not a demonstrated V2 benefit. The new scenario fixtures do not become verified precedent merely by being added or investigated. Eligible cases require independent verified, noninvalidated outcomes before the querying snapshot. A later retrieval-only experiment can freeze an eligible corpus, use external holdouts, compare structural versus semantic/hybrid ranked sources under identical bounds, and measure added embedding latency, context size and grounding. No vector database, backfill, embedding calls or experiment is authorized in this assignment.

## Approval boundary

The user approved the scoped implementation and initial bootstrap. This bootstrap chat stops after reporting the exact commit, common worktree ancestry, frozen contract and readiness; the user distributes the ready handoffs to Claude, Composer and a separate Sol High task. No development agents are launched here. Paid testing remains separately unauthorized until a concrete bounded request is explicitly approved.


---

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


---

# Deliverable 7 — GPT-6 Sol High: dataset and GPS implementation

You own Suhail V3 scenario refinements and source-correct GPS retrieval. Read the approved `C:\Projects\suhail-v3-plan-2026-10-13\01-master-plan.md` and `06-contract-examples.json`. Implementation requires the user's approval of that plan. No paid calls or evaluation campaign are authorized.

Work on `v3/scenarios` in `C:\Projects\suhail-v3-scenarios`, created from Sol's shared V3 bootstrap SHA. Verify it before editing. Protected reference repository is `C:\Projects\demo`, fhd `4cd43045a1db284e83cd5702d63acf7950492492`. Its backend/chat/scripts match `.stage4` `187ae087...`. The committed recording UI is in protected `.ui-integration\frontend-next`, commit `5aab052...`; Composer handles it. Synced ChatGPT `sources` was empty at planning time; do not claim unavailable material was inspected.

## Ownership and boundaries

Own only necessary edits in `chat\world\config.py`, `mechanisms.py`, `schedule.py`, `physical.py`, `observe.py`, `build.py`, `validate.py`, `pipeline.py`, `export.py`; `chat\operations\tools.py`, `cross_shipment.py`, `read_model.py`, `reasoning.py`; proposed `operations\route_evidence.py`, `world\v3_scenarios.py`; tests `world_fixture.py`, `test_cross_shipment.py`, `test_operations_read_model.py`, `test_investigator.py`, `test_world_build.py`, `test_world_contracts.py` and proposed `test_v3_route_evidence.py`, `test_v3_scenarios.py`.

Opus owns store/workers/schema/provider plumbing and concurrency tests. You must not edit those files. `backend\operations_api.py`, `operations\graph.py`, `investigator.py`, `checks.py`, `datasets.py`, `ingestion.py`, `dataset_v2\contracts.py`, `.env.example` and launch scripts belong to the integrator. Supply a specific integration patch request if needed; do not broaden schema/policy on your own. Reviewer, authority, guard and outcome semantics stay unchanged.

## Dataset task

Audit narrowly: `world/README.md`, `WorldConfig`, `build_world`/`export_bundle`, Observer, mechanism scheduling, V2 contracts/feed, `Gateway`, and existing world test fixture. Already verified: offline devices, partial uploads, complaints, alternate handoff, OTP failure, linehaul delay, traffic disruption and ordinary variation exist. Refine evidence-rich fixtures; do not recreate the logistics world or add a new cause taxonomy.

Create four families plus an innocent counterexample, roughly 6–10 curated development shipments:

1. One offline delivery device affects 2–3 shipments. Before receipt, buffered scans are invisible; after reconnect, earlier occurrence times appear with later receipt. Each case retains separate run/review/action/outcome records.
2. An attributed recipient dispute conflicts with strong bound delivery proof or an alternate handoff. Strong proof cannot automatically dismiss the report. Human review/unresolved state is acceptable.
3. Photo exists but OTP is absent/failed. Include a snapshot where the correct operational response is more evidence or human review. A photograph is not verified delivery.
4. A last-mile or linehaul delay with actual vehicle observations, visible plan and source-grounded traffic/operational context.
5. A stop within an ordinary planned window/slack as a counterexample; no fault/blame merely because the vehicle is stationary.

Use the existing test substrate `WorldConfig(total=240, seed=11, rates=uniform_rates(.012,.012))` for fixture/testing reuse. Adopt dataset ID `DEMO-SUHAIL-WORLD-V3-20261013` and fixed documented profile seed. Keep existing world/network conventions and shipment count bounded; curate/refine stories rather than add hundreds of shipments. A new scenario-profile CLI in `world/v3_scenarios.py` is proposed: define its explicit export/validate interface and document it; do not pretend that CLI already exists. Generate physically coherent records through existing simulation/observation/gateway mechanisms, not hand-written resolved cases. Bound selection attempts; don't weaken full-world validators to make a tiny profile pass.

Runtime manifest must be label-free: seed, stable case/shipment/record IDs, source references, hashes and replay cutoffs only. Keep scenario descriptions, expected temporal assertions and allowed outcomes in test/design artifacts outside DB/import/HTTP/tool access. Generate any private truth as opaque external artifacts; never inspect or reuse existing evaluation hidden answers. The physical-state adapter may receive the newly generated physical state, but investigator/reviewer/Canopus/API may not read it.

Preserve `occurred_at` event time, provider send time in raw feed, gateway `recorded_at` receipt time from `deliver_at`, and `ingested_at` processing tick. Verify late-arriving records remain invisible at earlier cutoffs even after later ingestion. Preserve source-event deduplication, IDs, relationships and provenance. No future observations, hidden scenario tags or invented proof. Test required fields and no-leakage with a synthetic positive control.

Output under `C:\Projects\suhail-v3-data\world-v3-20261013`; new physical state under `C:\Projects\suhail-v3-state\world-v3-20261013`; opaque generated evaluation artifacts under `C:\Projects\suhail-v3-private\world-v3-20261013`. Import only into `shipments-v2-world-v3-20261013` after target confirmation. Existing `world.export apply <directory> --database <name>` is available; `--replace` is prohibited on any existing database. Check existing target/nonempty imports and stop on mismatch. Coordinate new DB creation with integrator; do not reset an existing V2 database. Do not run existing `world.export check --ingest` blindly: it resets the selected live session after replay; use it only on your isolated, disposable V3 target and account for that behavior.

## GPS task and wire freeze

Verified gap: `InvestigationTools._container_and_trip` already reads `trip_positions` and returns GPS summaries; `_same_route_run` does not retrieve shared route GPS. `vehicle_and_manifest` only sees GPS present in the owned context. Add a fixed bounded `route_run_positions` query to `operations/cross_shipment.py`, using its `visible`/`in_scope` predicates and `clean_params`. No model-authored Cypher.

Implement `build_route_evidence(context, fetch, *, max_points=160, max_runs=4)` in the proposed helper. Validate route/trip references against this shipment's visible assignment/custody/attempt/manifest. Bound vehicle and assignment interval; reject unrelated routes and held-out/future records. Use a 161-row sentinel for the 160-point UI bound, disclose truncation/sampling and retain context/endpoint/event boundaries deterministically. Do not fill missing coordinates/records from private simulation or inference.

Add `route_observations` to `InvestigationTools.CATALOG`, using helper and existing `_fetch`, `_remember` and `_compute`. At most 12 selected points/factual summary, within current character/row/citation limits. Every cited source must actually appear in the rendered result and in reviewer evidence. Keep existing trip tools. No cause/answer labels in returned data. GPS remains vehicle-only; assignments/manifests remain plans.

Expose the frozen additive `route_evidence` contract on existing shipment/case detail, and populate the existing `route_layers.layers.vehicle_path` from the same data/cutoff. Preserve actual/custody layer semantics. Include real source nodes/relationships for graph highlighting; absent connecting edges remain absent. Add receipt/source/accuracy/transport metadata to points. Current expected route is an approximate connection, not road geometry; do not calculate unsupported road deviations.

Forward Opus's store-provided `investigation_status` into case-detail in YOUR `read_model.py` after his contract is ready. Do not implement claims or duplicate status logic; use agreed fixture meanwhile. Send the schema JSON and one valid bounded fixture to Composer before waiting for the complete dataset. Any wire change requires the integrator's review and Composer acknowledgement.

For Composer Phase C, supply neutral read-only packets for EVERY curated development shipment: exact shipment/case IDs, actual source node/edge records, before/after receipt cutoffs, dataset/manifest hash and a reproducible permitted investigator-tool snapshot. Do not include scenario family, intended diagnosis, expected outcome, scoring truth or hidden answers in these first-pass packets. Keep the isolated authored test catalogue separate until Composer has completed and timestamped all evidence-first reviews. Its later comparison must never read historical evaluation gold. You retain full-dataset automated structural validation and all dataset corrections; Composer cannot edit or reshape data. Support read-only reference evidence for original video shipments SYN-SHP-000304 and SYN-SHP-000443 where available, without resetting/rerunning V2. Do not treat QA as permission for provider calls.

## Tests, commits and outputs

From `C:\Projects\suhail-v3-scenarios\chat`:

```powershell
uv run python -m unittest tests.test_cross_shipment tests.test_operations_read_model tests.test_investigator tests.test_world_contracts tests.test_v3_route_evidence tests.test_v3_scenarios -v
```

Run `tests.test_world_build` once if generator logic changes. Reuse cached fixtures. Add tests for before/after receipt, same snapshot after later ingest, foreign run rejection, valid assignment interval, real source IDs/edges, bounded model rendering with citeable sample IDs only, no GPS delivery/custody claim, null/missing geometry, deterministic hashes and harmless counterexample. Update MemoryPort for new fixed queries. Confirm real query behavior on the new scratch DB without inspecting answers. No full Stage 3 or cloud calls.

Commit only owned files on `v3/scenarios`; don't stage private state/truth, credentials or large generated exports. Provide schema/fixture paths, exact export/load instructions, SHA/hashes, scratch DB verification, targeted test results/skips, demonstrated temporal cases and integration requests. Use the shared checkpoint format from the master plan. Hour 24: first designs/GPS fixtures; hour 36: validated export/retrievable data; hour 48: feature freeze. Escalate missing source data instead of fabricating it. Integrator alone merges the reviewed SHA.


---

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


---

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


---

# Composer Phase C — Independent case evidence and storyline QA

Continue the SAME Composer thread and `v3/route-ui` worktree at `C:\Projects\suhail-v3-route-ui`. This follows Phase B and precedes final integration signoff. The user explicitly approved this addition on 13 October 2026. The API contract stays frozen at `suhail-v3-1`; no new branch, dataset manipulation or paid model calls are authorized.

## Scope and hard budget

Review EVERY curated V3 development shipment, approximately 6–10, and original video reference shipments `SYN-SHP-000304` and `SYN-SHP-000443` where actual evidence is available. Do not audit hundreds of shipments. Full-dataset automated structural validation belongs to Sol.

Reserve a hard FOUR HOURS during hours 48–60 of the existing schedule: 15 minutes for packet inventory; up to 12 minutes per case/reference (12 total maximum = 144 minutes); 20 minutes for later catalogue comparison; 35 minutes for matrix/defect handoff; 26 minutes for one affected-case retest/buffer. At the limit, report incomplete coverage as REVIEW and escalate to the integrator; do not silently expand scope or skip a curated case and mark overall PASS. No new features after hour 48.

Use the same worktree/thread; own only your existing UI files plus `docs\v3\case-qa\evidence-first.md`, `case-audit-matrix.csv`, `case-audit-report.md`. These are QA outputs, never runtime evidence. Dataset records, generation, source metadata, test expectations and expected diagnoses are read-only to you.

## Evidence-first protocol

1. Receive Sol's neutral packet manifest: exact shipment/case/source IDs, dataset/hash, actual node/edge records, relevant before/after receipt cutoffs and allowed tool snapshots. It must exclude scenario family, intended diagnosis, desired action, expected outcome and scoring truth. Do not open the isolated test catalogue, historical evaluation gold or private physical state.
2. For each shipment, reconstruct chronology from actual occurred_at/recorded_at/ingested_at and provider source records. Distinguish missing-at-cutoff from never recorded. Check the same earlier snapshot after later ingestion for improper backdating.
3. Trace shipment→package→custody and driver/device/assignment/route/trip/GPS relationships using real edges and source IDs. Plans/manifest membership do not prove loading. Vehicle GPS does not locate/deliver a parcel. Missing edges/coordinates stay missing.
4. Check permitted investigator access using deterministic read-only tool invocations or captured tool results at the stated cutoff; verify source IDs, scope, rendered/citable sample and reviewer-accessible evidence. No live GPT-OSS run is needed. Do not start a backend merely to obtain records without the integrator's exact V3 target check.
5. Compare graph, route map and timeline at the SAME declared source cutoff. If UI follows a later live clock than the saved run, label that difference and verify later records are not presented as earlier investigator evidence. Cross-select exact source IDs; compare vehicle context, custody, planned connection, observed samples and receipt chronology.
6. Record contradictions, missing/implausible/fabricated evidence and alternative explanations BEFORE inspecting authored expectations. Separate what is directly observed from inference and uncertainty. A neutral route stop or strong proof does not eliminate every competing explanation.
7. Write your initial evidence-first conclusion, missing evidence and the operational actions/escalation/verification that the visible facts can support. Then inspect the stored investigator recommendation/review/authority/outcome as an ACTUAL system result, clearly separate from your conclusion. This is not an expected answer.
8. Finalize ALL first-pass notes, with timestamp and input hashes; send the integrator that immutable snapshot or commit SHA. Sol then releases the isolated authored test catalogue for comparison. Never edit the first-pass notes to match the catalogue; add a separate comparison section/delta. Do not read hidden evaluation answers at this step.
9. Classify mismatches: evidence defect, UI defect, tool-access defect, action/verification problem, catalogue expectation defect or legitimate ambiguity. Intended outcomes can be wrong; do not force a preferred diagnosis or a resolved state.
10. Produce the concise matrix and route each defect to its owner. Sol corrects data and supplies a new immutable fixture/hash; you correct UI only. Integrator/Opus handle concurrency/lifecycle defects under frozen ownership. Recheck affected rows only after a reviewed repair; retain original findings.

## V2 reference checks

Use only available read-only source snapshots or explicitly read-only queries of the protected V2 evidence. Do not start/stop/reset the V2 app, replay its feed, invoke its investigator, seed a take, rerun a video or modify recorded files. If querying the V2 database, use a read-only session without operations-runtime initialization. If evidence is unavailable, mark reference coverage `NOT CHECKED — evidence unavailable` in the notes and REVIEW in the three-state matrix; do not reconstruct source facts from the movie or its explanatory diagnosis notes. Keep V2 and V3 dataset IDs distinct. Reference outcomes are not a V3 answer key.

## Required concise matrix

One row per curated shipment and available/unavailable video reference:

```text
CASE / SHIPMENT ID | DATASET / HASH | CUTOFFS | CHRONOLOGY |
RELATIONSHIPS / GPS | TOOL ACCESS | GRAPH / MAP / TIMELINE |
ALTERNATIVES / GAPS | ACTION / VERIFICATION SUPPORT |
SOURCE IDS | FIRST-PASS NOTE / HASH | CATALOGUE DELTA |
PASS / REVIEW / FAIL | DEFECT OWNER / NEXT ACTION
```

PASS: reconstructable and time-correct evidence, source/relationship/tool/view agreement, defensible operational outcome or legitimate human/insufficient-evidence state, no blocking defect. PASS is evidence-integrity QA, not an accuracy claim.

REVIEW: genuine uncertainty, missing source/reference availability, an unresolved noncritical discrepancy, incomplete review at the time limit or a catalogue expectation requiring Sol's assessment. Legitimately ambiguous cases can pass when the system represents their uncertainty safely; REVIEW is not automatically a wrong diagnosis.

FAIL: fabricated/contradictory impossible records, temporal/split leak, invalid cited source, graph/map/timeline materially disagree, tool cannot retrieve required permitted evidence, GPS falsely proves parcel custody/delivery, or operational action/verification unsupported by visible records.

Cite concrete source IDs and cutoffs for every defect; do not fill them with invented examples. A curated-case FAIL blocks signoff until fixed/reviewed; removing the case to conceal a failure is prohibited. A REVIEW needs explicit integrator disposition, not automatic acceptance. If all curated cases cannot be covered in four hours, escalate the coverage gap without rewriting the architecture or broadening testing.

Deliver original evidence-first notes, matrix, catalogue comparison, owners, retest status and exact elapsed time to Fable and Sol through the user's distribution channel. Use the existing checkpoint template. No new thread/branch and no paid inference.


---

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


---

# Suhail V3 interface freeze reference

Version `suhail-v3-1`, approved and frozen by the user on 13 October 2026. This is a compatible extension, not a replacement for V2 contracts. Composer Phase C adds an independent QA gate without changing these wire fields. `06-contract-examples.json` contains synthetic shape examples; they are not generated operational records or an importable V2 bundle.

## Common rules

IDs are opaque strings, at most 160 characters unless an existing tighter bound applies. Storage IDs use DEMO; HTTP uses the existing SYN boundary. Do not alter cursor/token formats. Timestamps are UTC ISO 8601 strings with an offset; use the existing `instant` validator. Wall times and evidence times have different meanings. Missing optional fields support old backends; explicit null means known absence, not a value to synthesize.

No generic new diagnosis/status enums replace V2. Additional response fields must be ignored safely by older clients. TypeScript adapters may map snake_case to internal camelCase; wire keys remain unchanged.

## InvestigationStatusV3

| Field | Type / rule |
|---|---|
| `case_id`, `shipment_id`, `run_id` | string; run_id nullable before any run |
| `worker_id`, `claim_id` | string or null; terminal projection retains the last run's recorded ownership; queued projection has null current ownership |
| `claim_epoch` | integer >= 0, persistent monotonic ownership generation |
| `workflow_state` | existing V2 workflow enum |
| `run_status` | QUEUED / RUNNING / REVIEWED / ABORTED / FAILED |
| `active_stage` | existing extract/retrieve/classify/retrieve_context/recommend/review/writeback/escalate, or null |
| `started_at` | wall UTC string or null before a run |
| `updated_at` | wall UTC string from latest accepted current-run status/progress; lease-only heartbeat must not fabricate a stage event |
| `lease_expires_at` | wall UTC string while active; null once ownership is released |
| `as_of` | immutable evidence cutoff of that run; queued projection may use pending case cutoff and must be labelled QUEUED |
| `state_version` | current case business version, integer >= 0 |
| `final_result` | null before finalization; otherwise bounded object below |

`final_result` fields: `workflow_state` (existing enum), `review_verdict` (existing verdict or null), `model_verdict` (existing model verdict or null), `outcome_verification_status` (existing verification status or null). Never imply verified delivery from a reviewed run. Case detail is authoritative for full action/outcome history.

`worker.active_cases`: at most configured 1/2 unexpired current claims, sorted by started_at then case_id. Required identities are nonnull there. `worker.active_count` equals array length. `worker.concurrency` is capacity. Legacy single IDs are null with zero/two active cases, populated with one. Finalized status is served in case-detail, not retained as an active claim.

Status ordering: within a run use persisted pipeline sequence and wall timestamps. On a new run, its run_id replaces current state. Never compare one case's sequence to another's. On expiry, abort the old current projection, then expose the new claim after a transactional regrant. Heartbeat timestamps alone do not establish that a model call is working.

## RouteEvidenceV3

| Field | Type / rule |
|---|---|
| `schema` | literal `route-evidence-v3-1` |
| `shipment_id`, `as_of` | ID and fixed evidence cutoff |
| `contexts` | array, max 4 connected transport contexts |
| `observations` | array, max 160 valid-coordinate points for UI; tool selects <=12 |
| `summary` | bounded facts/comparisons with exact input IDs, no cause/answer field |
| `source_nodes` | existing evidence node shape `{id,kind,properties}`, scoped and allowlisted |
| `source_relationships` | existing evidence edge shape `{id,kind,start,end,properties}`, actual visible edges with returned/known endpoints only |
| `truncated` | boolean flags for contexts, observations and source_relationships |

Context fields: `route_run_id` and `trip_id` (string or null, at least one); `assignment_id`, `vehicle_id`, `device_id` (actual ID or null); `valid_from`, `valid_to` (visible plan/assignment interval or null); `plan_source_ids`, `custody_source_ids` (ID arrays). An unknown assignment is explicit: do not turn a plan into parcel custody. At least one visible shipment record must bind the chosen route/trip. Never allow an arbitrary vehicle/run supplied by the model or UI to pass this validation.

Observation fields:

| Field | Type / rule |
|---|---|
| `entity_id`, `evidence_id`, `vehicle_id` | actual stored source IDs, nonnull |
| `route_run_id`, `trip_id` | ID or null, matching context |
| `lat`, `lng` | finite numbers in [-90,90] / [-180,180]; unknown-coordinate sources can be represented as source_nodes but not invented points |
| `accuracy_m`, `speed_kmh` | finite nonnegative number or null when not recorded |
| `occurred_at`, `recorded_at` | required event/receipt UTC, both <= as_of; recorded >= occurred |
| `ingested_at` | optional UTC string, processing time >= recorded; not substituted for receipt |
| `source_ref` | actual source reference string |
| `position_scope` | literal VEHICLE_ONLY for this feature |
| `classification` | literal observed_vehicle |
| `source_event_id` | actual value or null; no alias created from the point ID unless the source defines it |

Order by occurred_at then evidence_id, grouped by vehicle/context; do not connect groups into one track. Retrieve bounded sentinel rows to detect truncation. Samples retain deterministic endpoints and records at actual operational transitions. A gap stays a gap. No fabricated intermediate road coordinates or parcel locations.

Summary fields: `points_returned` integer, `sampled` boolean, `first_observed_at`/`last_observed_at` UTC or null, `stationary_intervals` array (max 4), `timing_comparisons` array (max 8), `input_evidence_ids` array and optional bounded `note` (<=400 characters).

Stationary interval shape: `{vehicle_id, route_run_id, trip_id, first_observed_at, last_observed_at, threshold_kmh, gap_limit_seconds, input_evidence_ids}`. A point with speed below a documented threshold is a stationary observation; call it an interval only when at least two qualifying samples satisfy a documented maximum gap. Missing samples do not establish continuous stopping. Defaults: <3 km/h and max 300-second gap. No cause/blame label.

Timing comparison shape: `{planned_source_id, observed_source_id, milestone, planned_latest_at, observed_at, delay_seconds, input_evidence_ids}`. Compute nonnegative lateness as max(0, observed_at - planned_latest_at) only when a visible plan and the same observed milestone exist. Both source IDs must resolve. A GPS point near an endpoint alone is not a custody/arrival milestone unless an existing documented matching rule supports that observation; no new delivery certification rule. If only an expected deadline has passed without an observation, state missing evidence rather than an actual arrival delay.

The investigator tool uses `_remember` for displayed sources and `_compute` for comparisons; computed IDs remain distinct from graph node IDs. Runtime tool `_ids` and CitableEvidence must refer only to displayed rows. The model's character/row/citation caps remain those of V2. Do not expose the full UI source array in a model prompt.

Existing `route_layers` keys remain unchanged. Vehicle points may gain the fields above; source remains vehicle_telemetry_only. `actual_route` and custody layers keep existing corroboration rules. All enriched route data shares the declared detail cutoff. Full case-detail evidence can be at the live clock; an investigator run remains pinned to its own as_of. The UI labels these snapshots distinctly and must not present later UI sources as evidence used by an earlier run.

## Fixture manifest versus test catalogue

Runtime manifest: `schema`, `dataset_id`, `seed`, stable `fixture_id`, `shipment_ids`, `source_record_ids`, `replay_cutoffs`, `content_hashes` (generated SHA-256 values). It may be kept outside DB entirely. No scenario family/cause, expected answer, desired model response or allowed-outcome label is imported/served to the investigator.

Separate test catalogue: scenario family, source IDs, expected before/after visibility and allowed workflow outcomes. Its values are author-defined test assertions, not historical evaluation hidden answers. New generated scoring truth is stored externally and remains inaccessible to the runtime. The design example and runtime example in the JSON are separate objects deliberately; never import the entire example file.

Operational source records continue to use existing V2 Node/Edge envelopes, provenance and strict field allowlists. The new route response projection does not justify adding arbitrary fields to the source schema. If an extension is unavoidable, the integrator owns `dataset_v2/contracts.py` and reviews it before generation.


---

# Approved ownership and milestone addendum — Composer Phase C

Approved 13 October 2026. Architecture and wire contract remain `suhail-v3-1`. This adds an independent QA gate to the approved 72-hour prototype without a new development branch/chat.

| Owner / branch | Responsibility | Additional Phase C boundary |
|---|---|---|
| Fable coordinator / existing Claude project | Coordinate milestones, blockers and ownership; delegate concurrency to one Opus high-effort chat | Track neutral packet readiness, four-hour QA budget and defect owners; do not authorize unsafe merges or paid calls |
| Opus / `v3/concurrency` | Claims/leases/fencing, workers, provider limit, failure isolation, concurrency tests | Fix only assigned worker/lifecycle defects; no dataset/UI edits |
| Separate Sol High task / `v3/scenarios` | Scenario generation, GPS/source retrieval, temporal/provenance and automated structural validation over full generated dataset | Supply neutral actual-source packets; withhold test catalogue until independent review snapshot is complete; fix all data defects |
| Composer / `v3/route-ui` | Phase A discovery; Phase B map/graph/timeline and multi-case display; same thread/worktree | Phase C: review every 6–10 curated development shipment and two V2 video references where evidence exists; no dataset changes |
| Sol integrator / `v3/integration` | Bootstrap, controlled merges, focused verification and final signoff | Require completed case-audit matrix, resolve REVIEW rows and block curated-case FAILs; preserve V2 |

## Existing milestones, with the QA addition

- Bootstrap checkpoint before any downstream code edits: exact common SHA, frozen contracts, recording UI provenance, protection checks and readiness.
- Hours 0–4: owners receive that SHA and verify their assigned worktree; Composer A can start immediately.
- Hour 24: Opus claims/fencing, Sol first deterministic source fixtures, Composer A report.
- Hour 36: two-worker/mock provider and DB races; first validated scenarios/GPS evidence; Composer B integration fixtures.
- Hour 48: feature freeze, first controlled integration; Sol seals curated case list and neutral evidence packets. No new scenarios/features after this point.
- Hours 48–60: Composer C, HARD FOUR HOURS total, after Phase B is ready. Neutral first-pass notes are finalized before catalogue release/comparison. Sol performs full-dataset structural validation in parallel and owns corrections.
- Hours 60–68: focused defect fixes/retests, case QA dispositions and final integration signoff. No paid calls are authorized by this addendum.
- Hours 68–72: buffer/presentation; V2 final videos remain fallback. No-go if core concurrency/source/temporal gates or curated-case QA remain unsafe.

## QA packet and reporting ownership

Sol supplies actual source records/relationships, shipment/case IDs, hashes, relevant before/after receipt cutoffs and deterministic tool-access snapshots. No expected diagnosis/desired outcome/scenario labels in the neutral first-pass packet. The separate authored test catalogue is released only after all first-pass notes are timestamped/hashed. Historical hidden evaluation answers and private truth remain inaccessible to runtime tools, investigator, reviewer, Canopus and API throughout.

Composer writes `docs/v3/case-qa/evidence-first.md`, `case-audit-matrix.csv` and `case-audit-report.md` on its existing branch. It routes data defects to Sol, UI defects to itself and lifecycle defects to integrator/Opus. First-pass notes are immutable; later expectation comparison and repair/retest notes are appended separately. Structural validation across the entire generated dataset is not delegated to Composer.

Original video reference IDs are `SYN-SHP-000304` and `SYN-SHP-000443`. Review only available read-only evidence; no replay/reset/live inference/video modification. Unavailable reference evidence is documented as not checked, never passed. Curated V3 cases must all have a PASS/REVIEW/FAIL row with actual source citations before signoff. Catalogue matching alone is insufficient.

## Dispatch boundary

This bootstrap chat stops after the readiness report. The user distributes Fable/Opus, Composer A (with B/C follow-ups), and separate Sol High handoffs. No Codex subagents or replacement developer threads are launched here. No push, paid model run, database migration, API migration or broad evaluation campaign is authorized.


# Frozen contract examples

```json
{
  "contract_version": "suhail-v3-1",
  "status": "approved_frozen",
  "examples_are_synthetic": true,
  "id_boundary": {
    "storage_prefix": "DEMO-",
    "http_prefix": "SYN-",
    "conversion_module": "chat/operations/identifiers.py"
  },
  "worker_status_http_example": {
    "synthetic": true,
    "as_of": "2026-09-15T11:00:00+03:00",
    "database": "shipments-v2-world-v3-20261013",
    "worker": {
      "state": "running",
      "concurrency": 2,
      "active_count": 2,
      "processed_count": 0,
      "active_case_id": null,
      "active_shipment_id": null,
      "last_case_id": null,
      "active_cases": [
        {
          "case_id": "SYN-OPS-CASE-EXAMPLE-A",
          "shipment_id": "SYN-SHP-EXAMPLE-A",
          "worker_id": "investigation-1",
          "claim_id": "SYN-OPS-CLAIM-EXAMPLE-A-1",
          "claim_epoch": 1,
          "workflow_state": "INVESTIGATING",
          "run_id": "SYN-OPS-RUN-EXAMPLE-A-1",
          "run_status": "RUNNING",
          "active_stage": "classify",
          "started_at": "2026-10-13T15:00:00+03:00",
          "updated_at": "2026-10-13T15:00:15+03:00",
          "lease_expires_at": "2026-10-13T15:03:15+03:00",
          "as_of": "2026-09-15T11:00:00+03:00",
          "state_version": 2,
          "final_result": null
        },
        {
          "case_id": "SYN-OPS-CASE-EXAMPLE-B",
          "shipment_id": "SYN-SHP-EXAMPLE-B",
          "worker_id": "investigation-2",
          "claim_id": "SYN-OPS-CLAIM-EXAMPLE-B-1",
          "claim_epoch": 1,
          "workflow_state": "INVESTIGATING",
          "run_id": "SYN-OPS-RUN-EXAMPLE-B-1",
          "run_status": "RUNNING",
          "active_stage": "review",
          "started_at": "2026-10-13T15:00:01+03:00",
          "updated_at": "2026-10-13T15:00:16+03:00",
          "lease_expires_at": "2026-10-13T15:03:16+03:00",
          "as_of": "2026-09-15T11:00:00+03:00",
          "state_version": 2,
          "final_result": null
        }
      ]
    }
  },
  "finalized_case_status_http_example": {
    "case_id": "SYN-OPS-CASE-EXAMPLE-A",
    "shipment_id": "SYN-SHP-EXAMPLE-A",
    "worker_id": "investigation-1",
    "claim_id": "SYN-OPS-CLAIM-EXAMPLE-A-1",
    "claim_epoch": 1,
    "workflow_state": "HUMAN_REVIEW",
    "run_id": "SYN-OPS-RUN-EXAMPLE-A-1",
    "run_status": "REVIEWED",
    "active_stage": null,
    "started_at": "2026-10-13T15:00:00+03:00",
    "updated_at": "2026-10-13T15:00:40+03:00",
    "lease_expires_at": null,
    "as_of": "2026-09-15T11:00:00+03:00",
    "state_version": 3,
    "final_result": {
      "workflow_state": "HUMAN_REVIEW",
      "review_verdict": "human_review",
      "model_verdict": "HUMAN_REVIEW",
      "outcome_verification_status": null
    }
  },
  "route_evidence_http_example": {
    "schema": "route-evidence-v3-1",
    "shipment_id": "SYN-SHP-EXAMPLE-A",
    "as_of": "2026-09-15T11:00:00+03:00",
    "contexts": [
      {
        "route_run_id": "SYN-RUN-EXAMPLE-1",
        "trip_id": null,
        "assignment_id": "SYN-ASSIGN-EXAMPLE-A",
        "vehicle_id": "SYN-VEH-EXAMPLE-1",
        "device_id": "SYN-DEV-APP-EXAMPLE-1",
        "valid_from": "2026-09-15T08:00:00+03:00",
        "valid_to": "2026-09-15T20:00:00+03:00",
        "plan_source_ids": [
          "SYN-ROUTE-SEG-EXAMPLE-1"
        ],
        "custody_source_ids": [
          "SYN-CUSTODY-LOAD-EXAMPLE-A"
        ]
      }
    ],
    "observations": [
      {
        "entity_id": "SYN-GPS-EXAMPLE-1",
        "evidence_id": "SYN-GPS-EXAMPLE-1",
        "vehicle_id": "SYN-VEH-EXAMPLE-1",
        "route_run_id": "SYN-RUN-EXAMPLE-1",
        "trip_id": null,
        "lat": 24.7136,
        "lng": 46.6753,
        "accuracy_m": 15.0,
        "speed_kmh": 0.0,
        "occurred_at": "2026-09-15T10:50:00+03:00",
        "recorded_at": "2026-09-15T10:50:20+03:00",
        "ingested_at": "2026-09-15T10:50:21+03:00",
        "source_ref": "telematics",
        "position_scope": "VEHICLE_ONLY",
        "classification": "observed_vehicle",
        "source_event_id": null
      }
    ],
    "summary": {
      "points_returned": 1,
      "sampled": false,
      "first_observed_at": "2026-09-15T10:50:00+03:00",
      "last_observed_at": "2026-09-15T10:50:00+03:00",
      "stationary_intervals": [],
      "timing_comparisons": [],
      "input_evidence_ids": [
        "SYN-GPS-EXAMPLE-1"
      ],
      "note": "One vehicle observation does not establish a stop interval or parcel custody."
    },
    "source_nodes": [
      {
        "id": "SYN-GPS-EXAMPLE-1",
        "kind": "GPSObservation",
        "properties": {
          "entity_id": "SYN-GPS-EXAMPLE-1",
          "vehicle_id": "SYN-VEH-EXAMPLE-1",
          "route_run_id": "SYN-RUN-EXAMPLE-1",
          "lat": 24.7136,
          "lng": 46.6753,
          "accuracy_m": 15.0,
          "speed_kmh": 0.0,
          "occurred_at": "2026-09-15T10:50:00+03:00",
          "recorded_at": "2026-09-15T10:50:20+03:00",
          "source_ref": "telematics",
          "position_scope": "VEHICLE_ONLY"
        }
      }
    ],
    "source_relationships": [],
    "truncated": {
      "contexts": false,
      "observations": false,
      "source_relationships": false
    }
  },
  "route_layers_http_extension_example": {
    "layers": {
      "vehicle_path": [
        {
          "entity_id": "SYN-GPS-EXAMPLE-1",
          "evidence_id": "SYN-GPS-EXAMPLE-1",
          "vehicle_id": "SYN-VEH-EXAMPLE-1",
          "route_run_id": "SYN-RUN-EXAMPLE-1",
          "trip_id": null,
          "lat": 24.7136,
          "lng": 46.6753,
          "accuracy_m": 15.0,
          "occurred_at": "2026-09-15T10:50:00+03:00",
          "recorded_at": "2026-09-15T10:50:20+03:00",
          "source_ref": "telematics",
          "source": "vehicle_telemetry_only",
          "position_scope": "VEHICLE_ONLY"
        }
      ]
    },
    "truncated": {
      "vehicle_path": false
    }
  },
  "runtime_fixture_manifest_storage_example": {
    "schema": "v3-runtime-fixtures-1",
    "dataset_id": "DEMO-SUHAIL-WORLD-V3-20261013",
    "seed": 11,
    "fixture_id": "DEMO-V3-FIXTURE-001",
    "shipment_ids": [
      "DEMO-SHP-EXAMPLE-A",
      "DEMO-SHP-EXAMPLE-B"
    ],
    "source_record_ids": [
      "DEMO-SCAN-EXAMPLE-LATE-A"
    ],
    "replay_cutoffs": [
      "2026-09-15T10:00:00+03:00",
      "2026-09-15T12:00:00+03:00"
    ],
    "example_only": true,
    "content_hashes": {
      "example_source_record_ids_sha256": "37938ee1a16868b09d2cb1e5376294b6cf776059c7ad029b60fb49c6f2e8953a"
    }
  },
  "design_test_fixture_example_not_for_runtime_import": {
    "fixture_id": "DEMO-V3-FIXTURE-001",
    "scenario_family": "buffered_device_receipt",
    "source_record_id": "DEMO-SCAN-EXAMPLE-LATE-A",
    "occurred_at": "2026-09-15T09:30:00+03:00",
    "recorded_at": "2026-09-15T11:30:00+03:00",
    "expected_temporal_behavior": [
      {
        "as_of": "2026-09-15T10:00:00+03:00",
        "record_visible": false
      },
      {
        "as_of": "2026-09-15T12:00:00+03:00",
        "record_visible": true
      }
    ],
    "allowed_operational_outcomes": [
      "NEEDS_EVIDENCE",
      "HUMAN_REVIEW",
      "AWAITING_OUTCOME"
    ],
    "expected_answer_artifact_handling": "External test-only output; never imported, served or read by the investigator."
  },
  "approval_date": "2026-10-13",
  "implementation_dispatch": "User distributes Claude, Composer and separate Sol High handoffs after bootstrap checkpoint; no subagents launched here."
}
```

