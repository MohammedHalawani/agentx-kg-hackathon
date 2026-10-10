# Case detail contract: `diagnosis` and `rule_signals`

`GET /cases/{case_id}` serves the case ledger (workflow state, recommendation, review, executions,
outcome) together with the shipment evidence. `GET /shipments/{shipment_id}/context` serves the
evidence part only. TypeScript types: `frontend/src/contracts/caseDetail.ts`.

Two fields describe the case and must never be confused. The old `reasoning` field is gone: it held
rule triage recomputed at the live clock, and screens presented it as "what happened".

## `diagnosis`: the current run's accepted agent investigation, or explicitly absent

Built by `chat/operations/diagnosis.py` from the case's current run (`last_run_id`). Only a completed
GPT-OSS agent investigation that the independent model reviewer accepted (final verdict `accept`, model
verdict `ACCEPT`) fills it. Rule output never does, and neither does an investigation the reviewer asked
to revise, sent to a person, escalated or could not review: that one is absent with
`review_not_accepted`, and its findings are served apart in `unaccepted_investigation`.

| Field | Meaning |
| --- | --- |
| `available` | `true` only for a completed agent investigation of the current run that the independent reviewer accepted. |
| `reason` | Why it is absent (`null` when available): `not_a_case` (shipment view), `no_operations_ledger`, `not_investigated`, `investigation_in_progress` (a run is executing now), `reinvestigation_pending` (queued again; the earlier run is superseded), `investigation_incomplete`, `no_agent_investigation` (rules-only run), `investigation_unavailable` (the investigator failed or produced no valid conclusion), `review_not_accepted` (the reviewer did not accept the investigation). |
| `review` | The reviewer's decision on the run: `verdict`, `model_verdict`, `reason_code`, `accepted`. `null` when no run was reviewed. |
| `unaccepted_investigation` | With `review_not_accepted` only: the investigator's findings (`primary_cause`, `confidence`, `summary`, `hypotheses`, `missing_evidence`, `requires_physical_check`, `tool_calls`, `run_id`, `as_of`), with `accepted: false` and the `review`. A screen may show them labelled as not accepted by the reviewer; never as what happened. Otherwise `null`. |
| `source` | `agent_investigation` when available. |
| `run_id` | The run the diagnosis came from. While a run is in progress, that run's id. |
| `superseded_run_id` | With `reinvestigation_pending`: the earlier run that is no longer current. |
| `as_of` | The investigation's evidence snapshot time, not the live clock. |
| `investigated_at` | When the run was recorded. |
| `primary_cause` | The investigator's primary cause code, or `UNKNOWN`. |
| `confidence` | `low`, `medium` or `high`, as the investigator stated it. |
| `summary` | The investigator's own text, untranslated (`language: "en"`). |
| `hypotheses[]` | `cause`, `status` (`supported`, `refuted`, `uncertain`), `assessment` (model text), `supporting_evidence_ids`, `contradicting_evidence_ids`. |
| `missing_evidence[]` | What the investigator said is missing. |
| `requires_physical_check` | The investigator asked for a physical check. |
| `tool_calls` | Number of evidence queries the investigator made. |
| `snapshot_superseded` | Evidence kept arriving during the run; the case went to a person. |

While a newer run is queued or running, the earlier diagnosis is not served as current, and neither
is its review: `review` is `null` until the new run has been reviewed. While a re-investigation is
queued (`OPEN`, `REOPENED`), `run` is `null` and the earlier run is served as `previous_run` with
`superseded: true`; `pipeline.status` is `QUEUED` with no stage events, and the event stream
(`GET /cases/{case_id}/events`) reports `QUEUED` with `previous_run_id`. Stored agent runs never carry
a rule-definition sentence as a hypothesis's Arabic summary (`summary_ar` is `null`; the assessment is
the model's own text).

## `outcome` and `executions`: the current cycle

Each execution records the `recommendation_id` and `run_id` it was authorized for, and each outcome the
`run_id`. As served, the latest `outcome` and every execution carry `current_cycle`: `false` when the
record belongs to an earlier investigation cycle (or a re-investigation is queued). Such a record is
history; it must not be presented as the reason the case is where it is now.

## `rule_signals`: deterministic rule checks, labelled, with their own as-of time

Built by `OperationsReader.rule_signals` from the evidence visible at the live clock. These checks
open cases and back the post-investigation fact checks; they are signals, not a diagnosis.

| Field | Meaning |
| --- | --- |
| `kind` | Always `rule_signals`. |
| `is_diagnosis` | Always `false`. |
| `source` | `deterministic_evidence_rules`. |
| `as_of` | The evidence cutoff the checks ran at (the live clock when served). |
| `signals[]` | `code`, `summary_en`, `summary_ar` (rule text), `evidence_ids`, `certainty`, `requires_human_review`. |
| `expected_vs_actual[]` | Expected milestones against observations at `as_of`. |
| `operational_labels`, `journey_forecast` | Rule labels and the bounded travel-window estimate. |
| `precedents[]` | Verified precedents retrieved for the signal codes. |

A screen may show rule signals, labelled as rule checks at `as_of`. It must not present them as the
cause, and must not fall back to them when `diagnosis.available` is `false`.

## `recommendation` approval fields

`approvable` is the result of the same recheck an approval runs, on the current case: the recorded
approval context (symptoms, visible evidence count and latest ingestion time, run, final review,
case version) must be unchanged, the proposal must come from an agent investigation, and the
authority policy is recomputed. `approval_rule` names the deciding rule and `approval_reason` explains
it: `AUTH-20-approval-context-stale` (the basis changed; the case is re-investigated and reviewed
before anything is approved), `AUTH-21-human-investigation-required` (only evidence-gathering requests
may be approved on a human-investigation case), `AUTH-22-rules-only-proposal`, `AUTH-12`/`AUTH-13`
(person-only or prohibited actions), `AUTH-24-recommendation-already-executed` (an execution was already
authorized for this recommendation; it is never approved twice), or `LIFECYCLE-not-awaiting-decision`.
`approval_context_stale` is true when the basis changed. Refusals that hold whatever the context (AUTH-24,
AUTH-22, AUTH-12/13, AUTH-01, a human-investigation refusal decided from the recorded risk) are checked
first and leave the case where it is; only a stale context on the current run's own, never-executed
recommendation sends the case back for re-investigation. The same checks run again immediately before
dispatch.

## Queue rows (`GET /cases/queue`)

What a queue row says about its case comes from an accepted agent diagnosis only.

| Field | Meaning |
| --- | --- |
| `diagnosis_available` | `true` when the case's last run is an agent investigation the independent reviewer accepted. |
| `summary_source` | `agent_diagnosis` (then `issue_summary` is the primary hypothesis's own text, model prose in English) or `monitor`. |
| `issue_summary` | With `monitor`: the monitor's neutral sentence. Never rule triage text. |
| `category`, `cause_codes` | The accepted diagnosis's cause codes; `null` and `[]` otherwise. Never rule codes. |
| `operational_status` | From the accepted diagnosis, or else from the observed `symptom_codes` (`RESOLVED` stays). |
| `rule_signal_codes` | Codes from a rules-only run's triage, labelled: rule signals, never the cause. |
| `symptom_codes` | What the monitor observed. |

These fields are reset to the monitor's view whenever the case goes back for re-investigation, and the
queue's `operational_status` and `cause` filters use the same served values. Records written before the
diagnosis flag existed are served the same way (their stored rule-derived values are not shown).
