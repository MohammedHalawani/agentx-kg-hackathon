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
