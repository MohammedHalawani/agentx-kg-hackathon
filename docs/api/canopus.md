# Canopus questions

`POST /cases/{case_id}/canopus/ask` (operator token). Enabled on a server started with `SUHAIL_CANOPUS=1`; otherwise 409.
One question about one case, answered from that case's stored records. Nothing is stored and no case record is written.

## Request

```json
{"question": "What did the reviewer say?", "language": "en", "history": [{"role": "operator", "text": "..."}, {"role": "canopus", "text": "..."}]}
```

`question` 1 to 500 characters. `language` `en` or `ar` (default `en`). `history` at most 6 earlier turns, used only as
conversational context.

## Response

| Field | Meaning |
|---|---|
| `case_id`, `shipment_id`, `run_id`, `workflow_state`, `answered_at` | the case as recorded when the question was answered |
| `kind` | `canopus_answer`: written by the model from the case's records. `record_answer`: built by code from the records, when the model's reply was unusable, the call failed, or the model is off |
| `answer_en`, `answer_ar` | Canopus's text; `answer_ar` may be null |
| `evidence_ids`, `graph_node_ids` | records the answer relies on, and the subset that are nodes of the case's evidence graph |
| `quotes[]` | `{role, text, record_id, run_id, stage, iteration, occurred_at, title_en}`: the investigator's or reviewer's recorded words, copied by the server from stored records. The model only chooses which ids to show. Never Canopus's words |
| `offers[]` | `{type, action_type, allowed, rule_id, reason, label_en, label_ar, confirm}`: what the existing rules allow an operator to do now. `confirm` is `{method, path, body}` for the existing endpoint; the interface adds its own `idempotency_key` and calls it only after the operator confirms |
| `next_step` | the case's `next_step`, unchanged |
| `model`, `grounded`, `fallback`, `model_calls` | which model wrote the answer; whether the reply passed the grounding check; whether a record-based answer replaced it; 0 or 1 |

## Offers

- `approve_recommendation`: only when the case's current recommendation is an evidence-gathering request
  (`REQUEST_RESCAN`, `REQUEST_REWEIGH`, `REQUEST_DEVICE_SYNC`, `REQUEST_ADDITIONAL_EVIDENCE`, `REQUEST_HUB_CHECK`).
  `allowed` is the recommendation's own approval check, the one Review & authorize uses. Any other recommended action is
  listed with `allowed: false`, rule `CANOPUS-evidence-requests-only` and no `confirm`.
- `request_evidence` and `reanalyze`: the existing operator decisions, `allowed` in the states that accept them.

Canopus performs none of them. An approval goes through the existing recheck, execution and verification path.

## Grounding

A reply is discarded, and a `record_answer` returned, when it names a record id that is not in the case's context, says
the case is resolved when `workflow_state` is not `RESOLVED`, selects a quote id that does not exist, or is empty or too
long. The model is given the case's stored fields only: state, investigator conclusion, review, authority decision,
recommendation, attempted actions, verified outcome, next step, narration events, the count of evidence records by
kind, the available quotes and the offers. No prompt of another agent, no raw model reply, no simulator state.
