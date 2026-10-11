# Canopus narration

A read-only account of one investigation, built from what the run already recorded. Enabled on a server started with
`SUHAIL_NARRATION=1`; without it nothing is narrated and `narration.events` is empty.

## Where it is served

- `GET /cases/{case_id}` → `narration`: `{run_id, status, model_calls, events[]}` for the case's current run, oldest
  first. `status` is `idle` (nothing stored), `narrating` (the run is still in progress) or `complete`.
- `GET /cases/{case_id}/narration?run_id=…` → the same shape for any run of the case (the current run by default).
- `GET /cases/{case_id}/events` (the existing stream) keeps its `event: pipeline` messages and adds `event: narration`,
  whose data is one event, sent when it is stored. De-duplicate by `id`.
- `POST /cases/{case_id}/narrate` (operator token) asks for the stored narration of the current run to be brought up to
  date from its recorded events. It writes narration records only.

## Event

| Field | Meaning |
|---|---|
| `id`, `case_id`, `shipment_id`, `run_id` | identity |
| `sequence` | display order within the run; the list is append-only |
| `stage` | one of the eight pipeline nodes: `extract`, `retrieve`, `classify`, `retrieve_context`, `recommend`, `review`, `writeback`, `escalate` |
| `phase` | `investigation`, `review`, `authority`, `execution`, `verification`, `reassessment`. What happens after the pipeline (authorization, execution, verification) carries stage `writeback` and its own phase |
| `kind` | `canopus_summary` (the narrator model, from recorded events), `agent_output` (the investigator's or reviewer's own recorded words, quoted), `system_event` (written by code from a deterministic record) |
| `iteration` | the review round of the source |
| `title_en`, `title_ar`, `text_en`, `text_ar` | `text_ar` is present for system events, and for a summary when the model supplied a grounded one; `agent_output` is in the agent's language |
| `evidence_ids` | the records the message is about |
| `graph_node_ids` | the subset that are nodes of the case's evidence graph (for highlighting); tool computations and shared records are not |
| `source` | `{pipeline_sequences[], audit_event_types[], record_ids[]}`: what it was built from |
| `occurred_at`, `scenario_time`, `created_at` | wall time of the source, simulation clock of the source, when the narration was stored |
| `model`, `grounded` | set for `canopus_summary` only |
| `fallback` | true when a summary could not be used (call limit, provider failure, or a reply that named an id it was not given or claimed a resolution the record does not show) and the record-based text was stored as a `system_event` instead |
| `outcome_state` | the recorded case state after an authority, execution or verification message, so "resolved" is never inferred from prose |

## What is narrated

| Source | Kind |
|---|---|
| extract, retrieve, retrieve_context, recommend, writeback or escalate completed | `system_event` |
| each investigator tool call (its stated purpose) | `agent_output` |
| each investigator round | one `canopus_summary`, plus the investigator's own summary as `agent_output` |
| each review round | one `canopus_summary`, plus the reviewer's feedback as `agent_output` |
| authorization, execution receipt, verifier result, reassessment (from the audit trail) | `system_event`, text copied from the audit entry |
| after the last verification entry | one `canopus_summary` wrap-up |

## Limits

- Model calls: at most `SUHAIL_NARRATION_MAX_CALLS` per run (default 6; 0 turns the model off). They are made on the
  narrator's own thread after the source events are stored and do not count against the investigation's call cap.
- The narrator reads stored pipeline events, the run's conclusion and final review, and audit entries. It is given no
  prompt, no raw model reply and no simulator state. It has no tools and writes only narration records; nothing reads
  narration back into a conclusion, an authority decision, an execution or a state.
- Narration model calls are real provider calls and are not part of the evaluation ledger.
