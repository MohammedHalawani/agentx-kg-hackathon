# Demo lifecycle: the endpoints the UI uses, stage by stage

One case, from detection to a verified outcome, on a mechanism-world database. Everything is synthetic. Paths are as
`backend/operations_api.py` registers them (no prefix). Identifiers are served in their public form (as the API
returns them) and are accepted back in that form. Nothing served holds truth labels or the simulator's private state.

## 0. Starting the server for a world database

| Variable | Value |
| --- | --- |
| `SUHAIL_OPERATIONS_DATABASE` | the world database, `shipments-v2-world-<name>` (never chosen implicitly) |
| `SUHAIL_SIM_STATE_ROOT` | the root of that export's private **physical** state (`<root>/<dataset_id>/development/parcels.jsonl` ...). With it the world operational simulator is the execution adapter. Without it there is no adapter: an authorized action is recorded as not acknowledged and the case goes to a person |
| `SUHAIL_DEV_RESET=1` | only if the UI may reset the session |

Recommended for the live demo (all four are read by the backend process; unset, each keeps the evaluated behaviour):

| Variable | Value | Why |
| --- | --- | --- |
| `SUHAIL_TOOL_BATCH` | `3` | up to three independent evidence tools per model reply: fewer model round trips |
| `SUHAIL_PREFETCH_OVERVIEW` | `1` | the shipment overview is fetched before the first model turn: one model call fewer |
| `SUHAIL_INVALID_OUTPUT_REPAIR` | `1` | one repair attempt when a model reply is invalid twice, shown as a `RETRYING` event (`output.kind: "invalid_output_repair"`, "model reply invalid, retrying"); if it fails the case goes to a person as before |
| `SUHAIL_MODEL_CALL_CAP` | `20` | the per-case model-call cap (default 12), so a repair and a revision round fit |

These are demo settings: the frozen evaluation ran with none of them. Details and the `latency` block
(`GET /cases/{case_id}` → `run.result.latency`) are in `docs/api/investigation-run.md` sections 3a and 4a.

Never set a truth-label root for the server. `GET /worker/status` → `execution.adapter` says which adapter is attached:
`world_operational_simulator`, or `none`.

Session and writes: `GET /operations/session` returns `{token, actor_id, role, scope}`. Every `POST` below needs the
header `X-Operations-Token: <token>` and a loopback connection. Bodies are strict JSON (unknown fields are refused).

## 1. Clock, ingestion, monitoring (what makes cases appear)

| Call | Body | Use |
| --- | --- | --- |
| `GET /simulation/status` | | clock (`as_of`), simulator and worker state, `session.monitor_pending`, `execution.adapter` |
| `POST /simulation/start` | `{"speed": 600, "replay_mode": "timeline"}` (speed 1, 10, 60, 600 or 3600) | the ingestion worker advances the clock; the monitor opens cases |
| `POST /simulation/pause` | | |
| `POST /simulation/tick` | `{"seconds": 3600}` (optional `speed`, `replay_mode`) | one manual step |
| `POST /worker/start`, `POST /worker/pause` | | automatic investigation of open cases, oldest first |
| `POST /simulation/reset` | `{"confirmation": "<status.development_reset.confirmation>"}` | development only: deletes the operations ledger |

Background workers do the rest with no call from the UI: ingestion, monitoring, investigation (when the worker runs),
execution (`execute_step` every 2 s) and verification (`outcome_step` every 2 s).

## 2. Queue

`GET /cases/queue?scope=active&limit=25` (`scope`: `active`, `resolved`, `all`; filters `workflow_state`,
`operational_status`, `priority`, `city`, `cause`, `search`, `from`, `to`; `cursor` for the next page). Poll it (every
few seconds while the simulation runs). A case's `workflow_state` is the stage:

| State | Meaning |
| --- | --- |
| `OPEN`, `REOPENED` | detected by the monitor, waiting for investigation |
| `INVESTIGATING` | the investigator and reviewer are running |
| `AWAITING_APPROVAL`, `RECOMMENDATION_READY` | a person must approve the recommended action |
| `HUMAN_REVIEW`, `ESCALATED`, `NEEDS_EVIDENCE` | with a person (see section 6) |
| `AWAITING_OUTCOME` | an action was authorized or executed; the verifier is waiting for evidence |
| `RESOLVED` | closed from evidence (or by a person's finding that passed the same check) |

## 3. Case detail: diagnosis, review, run log

`GET /cases/{case_id}` returns the case with the shipment's evidence at the current clock, plus:

| Field | Content |
| --- | --- |
| `workflow_state`, `state_version` | `state_version` is the `expected_version` of every write below |
| `diagnosis` | the accepted agent diagnosis, or explicitly absent with the reason |
| `review` | the current run's final review: `verdict`, `model_verdict`, `reason_code`, `feedback` |
| `run.result` | the whole run record: `investigation_log` (rounds, tool calls), `authority` (`rule_id`, `risk_class`, `action_type`, `closure`, `reason`), `pipeline_events`; see `docs/api/investigation-run.md` |
| `recommendation` | `action_type`, `risk_class`, `approvable`, `approval_rule`, `approval_reason`, `approval_context_stale` |
| `executions[]` | `action_type`, `authority` (`AUTO_POLICY` or `OPERATOR_APPROVAL`), `status` (`AUTHORIZED`, `EXECUTING`, `ACKNOWLEDGED`, `NOT_ACKNOWLEDGED`, `REFUSED`), `mode`, `executed_at`, `deadline_at`, `adapter_result_json` (the receipt) |
| `outcome` | the latest outcome: `verification_status` (`VERIFIED`, `HUMAN_VERIFIED`, `HUMAN_FINDING`), `success`, `outcome_type`, `exception_cleared`, `remaining_symptoms`, `reason`, `evidence_ids`, `verifier_id`, `source` |

Live stages of a running investigation: `GET /cases/{case_id}/events` (server-sent events, event name `pipeline`, data
`{workflow_state, state_version, run_id, status, events[]}`). Subscribe while a case is `OPEN`/`INVESTIGATING`; fall
back to polling `GET /cases/{case_id}`. Manual investigation of one case: `POST /cases/{case_id}/investigate` (no body).

## 4. Approval and other decisions

`POST /cases/{case_id}/decision`

```json
{"decision": "approve", "expected_version": 7, "idempotency_key": "ui-approve-0007"}
```

`decision`: `approve`, `reject`, `request_evidence`, `escalate`, `reopen`. `idempotency_key`: 8 to 128 characters of
`A-Z a-z 0-9 _ -`; the same key replays the same result. Show the approve button only when
`recommendation.approvable` is true, and show `approval_reason` otherwise. An approval is rechecked on the current
case (evidence, symptoms, run, review, version): a refusal is HTTP 409 with the rule id (`AUTH-20-approval-context-stale`
requeues the case for a new investigation; `AUTH-21`, `AUTH-22`, `AUTH-24` leave it where it is). Approval authorizes
the action; it is not an outcome. Re-investigation on request: `POST /cases/{case_id}/reanalyze` with
`{"expected_version": 7, "idempotency_key": "ui-reanalyze-07"}`.

## 5. Execution and verification (nothing to call)

After an automatic authorization or an approval the case is `AWAITING_OUTCOME`. Poll `GET /cases/{case_id}`:

1. `executions[0].status` becomes `ACKNOWLEDGED` with a receipt. The receipt says a request was delivered. It never
   says what will be found, and it changes nothing about the case.
2. The simulator's answer arrives later as ordinary evidence (new records on the shipment, `source_ref`
   `synthetic:field-response`), at its own delivery time on the simulation clock.
3. The verifier records `outcome` from evidence recorded after the execution. `RESOLVED` only when
   `outcome.success` and `outcome.exception_cleared`. A verified action whose exception remains
   (`remaining_symptoms` not empty), a failed check, or silence until `deadline_at` (72 simulated hours) sends the case
   to `HUMAN_REVIEW`.

An operator may ask the verifier to check now: `POST /cases/{case_id}/outcomes` with
`{"expected_version": 9, "idempotency_key": "ui-verify-0009"}`. There is no field for success: nobody can declare it.

## 6. A person's finding

`POST /cases/{case_id}/human-outcome` (case in `HUMAN_REVIEW`, `ESCALATED`, `NEEDS_EVIDENCE` or `AWAITING_APPROVAL`)

```json
{"outcome_type": "parcel_located", "finding": "Found on shelf C2 during the depot check.",
 "evidence_ids": ["<evidence id>"], "expected_version": 11, "idempotency_key": "ui-finding-0011"}
```

`outcome_type`: `parcel_located`, `delivered_confirmed_by_person`, `returned_to_depot`, `parcel_not_found`,
`data_corrected`. Rules the UI should explain:

- The cited evidence must be visible, relevant to the kind of finding and recorded **after** the case's last executed
  action (after the case opened when no action ran). Otherwise HTTP 409 and nothing is recorded.
- The same clearance check the verifier uses then runs. The response says what happened:
  `{"workflow_state": "RESOLVED", "verification_status": "HUMAN_VERIFIED", "resolved": true, "remaining_symptoms": []}`
  or `{"workflow_state": "ESCALATED", "verification_status": "HUMAN_FINDING", "resolved": false, "remaining_symptoms": [...]}`.
  In the second case the finding is on record and the case stays open.
- `parcel_not_found` never resolves a case.

## 7. Audit

`GET /audit?case_id={case_id}&limit=100` (filters `shipment_id`, `event_type`, `actor`, `workflow_state`, `search`,
`from`, `to`; `cursor`). Event types of one lifecycle, in order: `CASE_OPENED`, `CASE_CLAIMED`, `PIPELINE_STAGE` (many),
`RECOMMENDATION_READY`, `AUTHORITY_DECISION`, `ACTION_AUTHORIZED` (automatic) or `APPROVAL_CONTEXT_CHECKED` +
`OPERATOR_DECISION` + `EXECUTION_REQUESTED` (approved), `EXECUTION_CONTEXT_CHECKED`, `ACTION_EXECUTED` (or
`ACTION_NOT_ACKNOWLEDGED`, `EXECUTION_REFUSED`), `EVIDENCE_INGESTED` (each new record), `OUTCOME_OBSERVED`, then
`OUTCOME_VERIFIED` + `CASE_RESOLVED`, or `OUTCOME_VERIFIED_EXCEPTION_REMAINS`, `OUTCOME_VERIFIED_HUMAN_CLOSURE`,
`OUTCOME_FAILED`; `HUMAN_OUTCOME_RECORDED` for a person's finding.

## 8. What the simulator does and does not do (demo limits)

It answers from the physical state only, through the provider feed, per action:

| Action | Answer |
| --- | --- |
| `REQUEST_DEVICE_SYNC` | only the targeted device; it uploads the records it holds when the request reaches it, and a heartbeat reports that queue. A healthy or wrong device uploads nothing. An unknown device, or one with no management channel, is not acknowledged |
| `REQUEST_RESCAN` | a read of the label the parcel really carries, at the facility where it is on a shelf (a wrong label reads wrong again). Nothing for a parcel in a container, on a vehicle or delivered |
| `REQUEST_REWEIGH` | the real weight on a scale of that facility that is not drifting then. Nothing at a facility with no scale |
| `REQUEST_HUB_CHECK`, `INITIATE_CUSTODY_RECONCILIATION` | each facility the evidence names (last corroborated holder, expected locations of missing observations) scans the parcel if it is there, else answers not found; reconciliation also records custody |
| `REQUEST_ADDRESS_CONFIRMATION` | the recipient confirms the address in force or replaces it with where they live. Never a delivery, and never enough to close a case |
| `PRIORITIZE_NEXT_SESSION` | for a parcel on a depot shelf: an attempt in the depot's next session, delivered only if the recipient is home then and lives at the address in force. If the depot loads it in that session anyway, the world's own records follow and nothing is added |
| `REQUEST_ADDITIONAL_EVIDENCE` | the shipment's records a device still holds are fetched; else nothing |
| `REROUTE_TO_CONFIRMED_DESTINATION` | simplified: from a depot shelf to an address the recipient confirmed; nothing otherwise |
| `RETURN_TO_SENDER` | simplified: from a facility shelf back to the facility of first handover, received about a day later |

Known limits (documented, not fixed for the demo):

- The world is simulated in advance. When the simulator moves a parcel (a simulated delivery, a return) it withdraws
  the shipment's later pre-generated provider messages; other shipments and shared records (route runs, containers)
  are not re-simulated.
- What the simulator changed (moved parcels, confirmed addresses) is kept in memory: it is lost on a server restart and
  cleared by a session reset.
- A device that is offline is assumed reachable by a sync request (someone reconnects it); only the records it holds at
  that moment upload, later ones wait for its own reconnect.
- A returned shipment keeps its overdue delivery milestone, so it is never closed automatically or by a finding: it
  stays with a person. A terminal "returned" disposition is a product decision that is not made here.
- Simulated attempts carry no delivery session or vehicle assignment record, and are sent on the SPL channel whatever
  the driver's provider.
- `scripts/world_demo.py` runs the whole lifecycle from the command line for named shipments (its header says how).
