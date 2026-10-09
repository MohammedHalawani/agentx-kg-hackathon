# Canopus: conversational operations agent (proposal, not implemented)

Status: proposal only. No Canopus code exists. It is to be built after the S5 gate, as a separate,
read-only conversational agent over what Suhail already records. It does not replace or override
the investigator, the reviewer, the authority policy or the verifier.

## What already exists to power it

| Question an operator asks | Recorded source today |
|---|---|
| Why was this case opened? | `OpsCase.symptom_codes`, `opened_at`, audit `CASE_OPENED` and `SYMPTOMS_UPDATED` (monitor) |
| What did the investigator retrieve, hypothesize, conclude? | `OpsRun.result_json.pipeline_events` (one event per tool call: tool, args, purpose, evidence ids), `investigation` (hypotheses with status and cited ids, primary cause, confidence, missing evidence, summary) |
| What did the reviewer accept or reject? | `OpsReview` per round, `trace[*].review` (verdict, feedback), audit `MODEL_DEGRADED` |
| Why AUTOMATIC / APPROVAL / HUMAN / PROHIBITED? | audit `AUTHORITY_DECISION` (rule id, risk class, closure, reason, inputs) |
| Was the action executed? | `OpsExecution` (status, authority, receipt, adapter response, deadline), audit `ACTION_EXECUTED` |
| What verified or failed to verify it? | `OpsOutcome` (verifier rule id, expected effect, evidence ids, reason, VERIFIED vs HUMAN_VERIFIED) |
| What is unresolved, what is missing? | case state, `investigation.missing_evidence`, failed outcomes, open human tasks |

Model-backed roles in V2 today: two. The investigation agent (iterative tool loop) and the
independent reviewer. Action selection is part of the investigator's conclusion; authority,
execution and verification are deterministic.

## Smallest clean implementation

1. **Chat API and streaming.** `POST /canopus/sessions` and `POST /canopus/sessions/{id}/messages`
   returning server-sent events (`token`, `tool_call`, `citation`, `done`, `error`), reusing the SSE
   pattern of `/cases/{id}/events`. One GPT-OSS role ("Canopus") with the same fail-closed `_llm`
   plumbing; no chain-of-thought stored or streamed. Conversation memory in its own ledger label
   (`CanopusMessage`), never in the evidence graph.
2. **Read-only tools.** Thin wrappers over existing reader/store reads only: `case_summary`,
   `investigation_trace`, `review_rounds`, `authority_decisions`, `execution_and_outcome`, `case_audit`,
   `shipment_evidence` (the same `OperationsReader.evidence` at the clock), `precedents`. No write
   tools in v1. Each tool returns typed records with their ids.
3. **Current-case context.** The UI passes `case_id`; the session pins it and preloads
   `case_summary`. Switching cases starts a new context; nothing from another shipment is in scope
   unless the operator asks and has permission.
4. **Citations and auditability.** Every answer sentence that states a fact must reference ids
   returned by its tools (validated like the investigator's citations). Answers are typed as
   observed fact, AI hypothesis (investigator), policy decision (rule id) or verified outcome
   (verifier rule id or human-verified). Each session and message is audited (actor, case, tools
   called, cited ids).
5. **Authentication and authorization.** Prerequisite: replace the local single-operator
   authority with real operator identity (OIDC) and roles. Canopus runs with the caller's
   permissions; tools filter by role (e.g. personal data in recipient reports only for roles that
   may see it). Not exposed without authentication.
6. **Controlled reinvestigation (optional, v2).** A `request_reinvestigation` tool that only calls
   the existing `POST /cases/{id}/reanalyze` with the operator's identity, expected version and an
   idempotency key; it never approves, executes or verifies anything.

## Contracts missing today (to add before Canopus)

- A stable, versioned read schema for `OpsRun.result_json` (pipeline events, investigation,
  checks, authority) instead of an opaque JSON blob.
- A case timeline endpoint that joins audit, runs, decisions, executions and outcomes in order.
- Operator identity and role claims on every write (today: `DEMO-OPERATOR-LOCAL`).
- Per-role field visibility rules for personal data.
- A published glossary of symptom, cause, action and verifier rule ids (en/ar).
