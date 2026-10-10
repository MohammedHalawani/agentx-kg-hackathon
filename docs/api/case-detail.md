# Case detail contract: `diagnosis` and `rule_signals`

`GET /cases/{case_id}` serves the case ledger (workflow state, recommendation, review, executions,
outcome) together with the shipment evidence. `GET /shipments/{shipment_id}/context` serves the
evidence part only. TypeScript types: `frontend/src/contracts/caseDetail.ts`.

Two fields describe the case and must never be confused. The old `reasoning` field is gone: it held
rule triage recomputed at the live clock, and screens presented it as "what happened".

## `diagnosis`: the current run's agent investigation, or explicitly absent

Built by `chat/operations/diagnosis.py` from the case's current run (`last_run_id`). Only a completed,
reviewed GPT-OSS agent investigation fills it. Rule output never does.

| Field | Meaning |
| --- | --- |
| `available` | `true` only for a completed agent investigation of the current run. |
| `reason` | Why it is absent (`null` when available): `not_a_case` (shipment view), `no_operations_ledger`, `not_investigated`, `investigation_in_progress` (a run is executing now), `reinvestigation_pending` (queued again; the earlier run is superseded), `investigation_incomplete`, `no_agent_investigation` (rules-only run), `investigation_unavailable` (the investigator failed or produced no valid conclusion). |
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
is its review: `review` is `null` until the new run has been reviewed.

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
(person-only or prohibited actions), or `LIFECYCLE-not-awaiting-decision`. `approval_context_stale` is
true when the basis changed. The same checks run again immediately before dispatch.
