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
