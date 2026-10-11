# Case brief, stage facts and plain Canopus answers

Additive on `GET /cases/{case_id}`. Composed by code from the case's stored records on every read: nothing is stored and
no model is called, so the same records give the same brief. Sentences carry no internal codes; codes and record ids are
in their own fields. Real examples from archived runs of 11 October 2026 are in `docs/api/examples/`.

## `brief`

| Field | Meaning |
|---|---|
| `resolved` | true only when the case is RESOLVED by a verified outcome |
| `waiting_kind`, `waiting_label_en/_ar` | `queued_for_investigation` (OPEN, REOPENED), `investigating` (INVESTIGATING, RECOMMENDATION_READY), `awaiting_operator_decision` (AWAITING_APPROVAL, HUMAN_REVIEW, ESCALATED, NEEDS_EVIDENCE, and any unknown state), `awaiting_operational_action` (ACTION_INITIATED), `awaiting_new_evidence` (AWAITING_OUTCOME), `resolved`, `closed_unresolved` (REJECTED). There is no long-lived verifying state: verification happens when the awaited evidence arrives or the deadline passes |
| `lines[]` | the operator's short view, in order: `{key, label_en, label_ar, text_en, text_ar}` with keys `problem`, `finding`, `review` (only when the review did not accept), `action`, `status` |
| `what_happened` | `{text_en, text_ar, opened_at, symptoms[{code, label_en, label_ar}]}` |
| `suspected_cause` | `{status: accepted / hypothesis_not_accepted / none, code, label_en, label_ar, confidence, text_en, text_ar, investigator_summary}`. A cause is a hypothesis unless the independent review accepted it |
| `evidence[]` | up to six cited records: `{id, kind, label_en, label_ar, occurred_at, facility_id, device_id, in_graph}` |
| `review` | `{status: accepted / challenged / asked_for_person / unavailable / not_reviewed, text_en, text_ar, reason_summary_en, reason_summary_ar, reason_original, verdict_code}`. `reason_summary` is the stored Canopus summary of that review round when one exists; `reason_original` is the reviewer's own words |
| `policy` | `{decision: automatic / needs_approval / needs_person / prohibited / none, text_en, text_ar, action_type, action_label_en, action_label_ar, action_description_en, rule_id, rule_reason}` |
| `actions[]` | one explanation per executed action, newest first (below) |
| `verification` | `{status: not_applicable / awaiting_evidence / verified_resolved / verified_not_fixed / verified_but_problem_remains / verified_not_closed / verified_awaiting_reassessment / not_delivered, text_en, text_ar, outcome_type, verified_at, verifier_reason}` |
| `next_step` | `{code, actor, text_en, text_ar}` |
| `technical` | `{workflow_state, state_version, run_id, authority_rule_id, review_verdict, closure}` for an expandable details view |

### `actions[]`

`{execution_id, action_type, label_en, label_ar, simulated: true, authorized_by: automatic_policy / operator_approval, status: authorized / sent / not_delivered, sent_at, recipient{known, kind, id, facility_id, label_en, label_ar}, awaiting{text_en, text_ar}, expected_response_at, expected_response_basis, deadline_at, deadline_text_en/_ar, continues_automatically, text_en, text_ar, outcome}`

- `recipient.known` is false when the request names no device or facility; nothing is invented.
- `awaiting` says which new record the verifier waits for (for a rescan, a new barcode read of this parcel).
- `deadline_at` is the only future time given. `expected_response_at` is null: it will be filled only from the answer
  times of verified past actions of the same type, never from the simulator's schedule.
- `outcome` is null until the verifier has decided, then `{verification_status, success, outcome_type, exception_cleared, verified_at, text_en, text_ar}`.

## `pipeline.stage_facts[]`

`{stage, iteration, sequence, status: done / running / rejected / failed / not_reached, fact_en, fact_ar}`: one entry per
stage and review round, from the stage events the run recorded, then one entry with stage `outcome`. A run with a
revision has two entries for `classify`, `retrieve_context`, `recommend` and `review`; the operator's action summary is
the highest iteration (`brief.policy`, `brief.actions`).

## Canopus answers (`POST /cases/{case_id}/canopus/ask`)

- `answer_en`, `answer_ar`: plain text. An answer that contains a rule id, a state, verdict or cause code, or an
  internal record id is discarded and the record-based answer (the brief's lines) is returned. Shipment, facility and
  device identifiers are allowed.
- `offers[]`: only what can be done now, `{type, action_type, label_en, label_ar, confirm}`.
- `unavailable_offers[]`: `{type, action_type, label_en, label_ar, reason_en, reason_ar, rule_id}`, to show only when
  the operator asks why something cannot be done.
- `quotes[]`: returned only when the question asks for an agent's original message or words.
- `technical`: `{workflow_state, rule_id, review_verdict, evidence_ids}`. `evidence_ids` and `graph_node_ids` are unchanged.
