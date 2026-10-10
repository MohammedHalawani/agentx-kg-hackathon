# Investigation run contract: call shapes, the run record and the per-round log

For the evaluation harness, the pilot script (`scripts/world_pilot.py`) and the new UI. It describes what one
case investigation takes, what it stores and where to read it. Everything here is synthetic operational data;
no field holds truth, gold or scenario data, and no chain-of-thought is requested, stored or returned.

## 1. Call shapes (stable)

| Call | Shape | Notes |
| --- | --- | --- |
| `OperationsStore.process_one(case_id=None, *, manual=False)` | returns `{processed, case_id, workflow_state, state_version, run_id, mode, afl, outcome}` or `{processed: False, ...}` | Claims one `OPEN`/`REOPENED` case, runs the graph at the store's clock (the evidence snapshot) and writes the run. `{processed: False, reason: "snapshot_changed"}` means new evidence arrived during the run and the case was requeued (at most twice). |
| `graph.investigate(shipment_id, as_of, config, retrieve, precedents, *, commit=None, on_event=None, agents=None, live_session=False, symptoms=(), heartbeats=None, port=None, disabled_tools=(), call_cap=None)` | returns `(analysis, disposition)` | `port` is `OperationsReader.fetch` (the fixed cross-shipment queries) or `None`; `disabled_tools` and `call_cap` are the evaluation switches below. |
| `investigator.investigate(tools, *, turn=None, on_step=None, feedback=None, session=None, review=None)` | returns the investigation dict (section 3) | One round of the tool loop. `session` (an `investigator.Session`) carries the conversation and the model-call budget across rounds; without it the call is a self-contained investigation with its own budget. `review` is the previous review in a revision round. |
| `investigator.review(conclusion, records, checks, symptoms, *, ask=None, context=None, session=None)` | returns `{verdict, feedback, unsupported_claims, unaddressed_contradictions, alternatives_tested, mode, degraded, validation_error}` | `verdict` is `ACCEPT`, `REVISE`, `INSUFFICIENT_EVIDENCE`, `HUMAN_REVIEW`, `ESCALATE`, or `UNAVAILABLE` when the reviewer failed (fail closed). `context` is built by `checks.review_context`. |
| `InvestigationTools(context, config, *, symptoms=(), heartbeats=None, precedents=None, port=None, disabled=())` | | One tool belt per case investigation, kept across review rounds. |
| `InvestigationTools.describe()` | `[{tool, args, returns}]` | Disabled tools are absent. |
| `InvestigationTools.call(tool, args)` | `{result, evidence_ids, computed_ids}` or `{error}` | An unknown or disabled tool returns `{error}` and is not recorded as a call. `result` is JSON text followed by ` CITABLE_EVIDENCE_IDS: [...]`. |

Older investigator doubles that declare only `investigate(tools, on_step=None, feedback=None)` and
`review(conclusion, records, checks, symptoms)` keep working: the graph passes `session`, `review` and `context`
only to callables that declare them.

### Evaluation switches

| Switch | Where | Effect |
| --- | --- | --- |
| Disabled tools | `store.disabled_tools` (a tuple of tool names; initial value from `SUHAIL_DISABLED_TOOLS`, comma separated), or `disabled_tools=` on `graph.investigate`, or `disabled=` on `InvestigationTools` | The tools are absent from `describe()` and refused by `call()` and by the loop. Recorded as `investigation_log.disabled_tools`. `operations.tools.CROSS_SHIPMENT_TOOLS` names the four tools that look beyond one shipment. |
| Model-call cap | `store.model_call_cap` (int or `None`), or `call_cap=` on `graph.investigate`; default from `SUHAIL_MODEL_CALL_CAP`, else 12, clamped to 3..60 | One counter per case investigation covers investigator turns (including corrective retries), reviewer calls (including the reviewer's retry) and revision rounds. A call past the cap is refused in code. The investigator always leaves one call for the review. |

A cap hit is a degraded run: the investigator returns `mode: "model_call_cap"`, no diagnosis is substituted and the
case goes to a person. A revision round is started only when at least two calls remain (one investigator turn and
one review); otherwise the case is escalated.

## 2. Where the run record is

`store.process_one` writes one `OpsRun` node per investigation (`entity_id` = the returned `run_id`); its
`result_json` property is the whole analysis as canonical JSON. It is served, parsed, as

- `OperationsStore.case_detail(case_id)["run"]["result"]`
- `OperationsReader.case_detail(case_id)["run"]["result"]` and `GET /cases/{case_id}` → `run.result`

While a re-investigation is queued (`OPEN`, `REOPENED`) `run` is `null` and the earlier run is `previous_run`
(see `case-detail.md`). `run.status` is `RUNNING` while the graph executes, `REVIEWED` when the run was written
back and `ABORTED` when it was not (snapshot changed).

| `run.result` field | Meaning |
| --- | --- |
| `mode` | `gpt_oss_agents` for an agent investigation, `deterministic_evidence_rules` for a rules-only run. |
| `investigation` | The investigator's last round as it returned it (section 3). `null` for a rules-only run. |
| `review` | The final review: `verdict` (`accept`, `reject`, `human_review`, `review_unavailable`, `no_proposal`), `model_verdict`, `reason_code`, `feedback`. |
| `trace[]` | One entry per review round: `iteration`, `proposal`, `review`, `feedback_received`, `mode`. |
| `proposal` | The recommended catalogue action as a proposal (`action_type`, `evidence_ids`, `target`), or `null`. |
| `checks` | The deterministic checks of the last round: `checks[]`, `rule_codes`, `unsupported`, `sensitive`, `contractor_custody`, `alternative_recorded`, and `citations` (the citation summary without per-id rows). |
| `authority` | The deterministic authority decision: `risk_class`, `reason`, `rule_id`, `action_type`, `closure`, `inputs`. |
| `degraded[]` | Failed model roles: `{role, error, kind}` with `kind` one of `model_unavailable`, `invalid_model_output`, `model_call_cap`. |
| `investigation_log` | The per-round log (section 4). `null` for a rules-only run. |
| `pipeline_events[]` | Stage events as they happened (each tool call is a `classify` `RUNNING` event). |
| `result` | Case result fields derived from the conclusion (`diagnoses`, `assessment.supported_codes`, `workflow_state`). |

## 3. `investigation` (what `investigator.investigate` returns)

| Field | Meaning |
| --- | --- |
| `mode` | `gpt-oss` for a valid conclusion; else `model_unavailable`, `invalid_model_output` or `model_call_cap`. |
| `degraded` | `true` when no valid conclusion was reached. Then `primary_cause` is `null` and `hypotheses` is empty. |
| `primary_cause` | A cause code of the catalogue, or `INSUFFICIENT_EVIDENCE`. (`UNKNOWN` from the model is stored as `INSUFFICIENT_EVIDENCE`.) |
| `confidence` | `low`, `medium`, `high`. |
| `hypotheses[]` | `cause`, `status` (`supported`, `refuted`, `uncertain`), `supporting_evidence_ids`, `contradicting_evidence_ids`, `assessment`. |
| `missing_evidence[]` | What is missing. Required and non-empty for `INSUFFICIENT_EVIDENCE`. |
| `next_evidence_step` | One sentence: what to obtain next and from where. Used with `INSUFFICIENT_EVIDENCE`. |
| `recommended_action` | A catalogue action type. With `INSUFFICIENT_EVIDENCE` only an evidence-gathering action or a person's check or review is accepted. |
| `requires_physical_check`, `summary` | As the model stated them. |
| `steps[]` | Every tool call of the case investigation so far: `round`, `tool`, `args`, `purpose`, `evidence_ids`, `computed_ids`. `round_steps[]` holds this round's only. |
| `retrieved_evidence_ids[]` | Every id any tool call listed as citable. |
| `validation_error`, `validation_errors[]` | The error that ended the round (if degraded) and every rejected reply `{turn, error}`. |
| `model_calls` | The budget when the investigator returned: `model_call_cap`, `model_calls_used`, `model_calls_by_role`, `cap_reached`, `calls_refused_by_cap`. The final count for the case is `investigation_log.model_calls_used`. |

`INSUFFICIENT_EVIDENCE` never carries automatic closing authority: an evidence request may run automatically
(`authority.risk_class: "AUTO"`, `authority.closure: "HUMAN"`), anything else goes to a person (`AUTH-26`). A
reviewer verdict of `INSUFFICIENT_EVIDENCE` sends the case back once for more evidence while a round and calls
remain, then to a person (`review.reason_code: "MODEL_INSUFFICIENT_EVIDENCE"`, `AUTH-25`); it never passes.

## 4. `investigation_log` (one per run; read this for scoring)

| Field | Meaning |
| --- | --- |
| `snapshot_as_of` | The evidence snapshot: tools returned only records recorded (and occurred) at or before it. |
| `model_calls_used` | **The one per-case counter**: every model call of this case investigation. |
| `model_call_cap` | The cap in force. |
| `model_calls_by_role` | `{investigator: n, reviewer: n}`. |
| `cap_reached`, `calls_refused_by_cap` | Whether a call was refused by the cap, and how many. |
| `disabled_tools[]` | Tools withheld from the investigator in this run (empty: all enabled). The enabled set is the catalogue minus these. |
| `rounds[]` | One entry per review round, in order (below). |
| `computed_results` | `{id: {computation, tool, computed_as_of, input_ids, ...values}}` for every tool-computed comparison or count the investigator was shown (ids start with `DEMO-CMP-`). |
| `cited_external_records` | `{id: record}` for cited records that are not the shipment's own evidence nodes (other shipments' records, shared records, device telemetry, precedents), as the tools showed them. |
| `evidence_index` | `{id: {kind, scope, recorded_at, occurred_at}}` for every retrieved id. `scope` is `shipment`, `other_shipment`, `shared`, `precedent` or `computed`. |

Each `rounds[]` entry:

| Field | Meaning |
| --- | --- |
| `round` | 0 for the first round, 1 for the revision round. |
| `snapshot_as_of` | The snapshot time (the same for every round of a run). |
| `tool_calls[]` | This round's calls: `tool`, `args`, `evidence_ids` (records listed as citable), `computed_ids`, `omitted_rows` (`{list: n}` rows left out by the size cap; their ids are not citable), `failure` (`null`, `invalid_arguments` or `query_failed`). |
| `conclusion` | `primary_cause`, `confidence`, `hypotheses`, `missing_evidence`, `next_evidence_step`, `recommended_action`, `requires_physical_check`, `summary`; `null` when the round was degraded. |
| `investigator` | `mode`, `degraded`, `validation_error`, `validation_errors[]`. |
| `citation_validity` | Computed by code: `snapshot_as_of`, `cited`, `valid`, `invalid_ids`, `all_valid`, and `citations[]` with `id`, `kind`, `scope`, `resolves`, `retrieved_in_this_investigation`, `recorded_at_or_before_snapshot`, `valid`. `null` when the round was degraded. |
| `fact_checks[]` | `{check, passed, detail}`: `cause_consistent_with_evidence_rules`, `citations_valid`, `sensitive_dispute_or_conflict`, `parcel_held_by_contractor`, `alternative_explanation_recorded`. A failed check removes automatic authority; it never changes the diagnosis. |
| `review` | `verdict`, `model_verdict`, `reason_code`, `feedback`, `unsupported_claims[]`, `unaddressed_contradictions[]`, `alternatives_tested`, `mode`, `degraded`, `validation_error`. |
| `model_calls_used`, `model_call_cap`, `model_calls_by_role`, `cap_reached`, `calls_refused_by_cap` | The budget after this round's review. |

An invalid citation (`citation_validity.all_valid: false`) sets `checks.unsupported`, which removes automatic
authority. The investigator loop already rejects a conclusion citing an id its tools did not return, so an invalid
citation in a stored conclusion means an id that was listed but does not resolve or is dated after the snapshot.

## 5. What the reviewer receives

`investigator.review` sends one packet: `case_symptoms`, `investigator_conclusion`, `cited_records` (the records
behind the citations, as recorded), `deterministic_checks`, `visible_evidence_ids`, and from
`checks.review_context`: `review_round`, `citation_validity` (summary), `computed_results_seen`,
`computed_results_not_shown`, `retrieved_but_uncited` (`{kind: {count, ids}}`), `tool_calls`
(`round`, `tool`, `args`) and, in a revision round, `previous_reviews` (its own `verdict`, `feedback`,
`unsupported_claims`, `unaddressed_contradictions`).

## 6. Tools

`shipment_overview`, `journey`, `custody_chain`, `scans`, `delivery_attempts`, `vehicle_and_manifest`,
`device_status`, `address_and_instructions`, `policy`, `precedents`, `communications`, `route_conditions`, and the
cross-shipment tools `same_device_activity`, `same_route_run`, `container_and_trip`, `facility_window`.

All are read-only and bounded (30 rows per list, 6,000 characters, 120 citable ids per result). The cross-shipment
tools run only the fixed parameterised queries of `operations/cross_shipment.py` through
`OperationsReader.fetch(name, **params)`: this dataset, its live, history and shared records, recorded and
occurred at or before the snapshot. Without a port they answer `UNKNOWN: evidence beyond this shipment's own
records is not available in this deployment.` A failed query is reported as a failure
(`failure: "query_failed"`), never as absence of evidence.

## 7. World databases

`OperationsStore`, `OperationsReader` and `SUHAIL_OPERATIONS_DATABASE` accept `shipments-v2-world-<name>` for a
`DEMO-SUHAIL-WORLD...` dataset only (and a world dataset only there or in a scratch test database). A world
dataset has no operational simulator: `status()["execution"]` is `{adapter: "none", dataset_kind:
"mechanism_world"}`, an authorized action is recorded `NOT_ACKNOWLEDGED`, nothing is verified and nothing resolves.
A fed record's `recorded_at` is the provider's delivery time (`deliver_at`), never before `occurred_at` and never
after the tick that ingested it; `ingested_at` is that tick.
