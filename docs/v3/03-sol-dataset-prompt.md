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
