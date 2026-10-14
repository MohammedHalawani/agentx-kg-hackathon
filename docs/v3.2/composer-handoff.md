# Composer handoff — additive action lifecycle

Backend branch: `codex/v3-2-case-intelligence`, worktree `C:\Projects\suhail-v3-2-case-intelligence`, based exactly on V3.1 `7287e44ad99c9a8b90aac7543e8218c1302aa31a`, which is also the current local `v3/integration` HEAD. Final commit and gate results are in `engineering-handoff.md` and `verification.json`. No frontend file was changed.

The frozen `suhail-v3-1` interface remains. The additive action sub-contract is **`suhail-action-1`**. No case-state or reviewer-verdict renames are required. Real examples from controlled store/verifier executions are in `action-status.examples.json`; they are synthetic examples, not an importable frozen dataset or instructions to alter real cases.

## Read model

`GET /cases/{case_id}` retains `diagnosis`, `recommendation`, `review`, `run`, `outcome`, `executions`, `investigation_status`, `workflow_state` and `state_version`. Each execution adds `action_lifecycle`. The case adds:

```ts
type ActionStatus = {
  version: "suhail-action-1";
  resolution: "VERIFIED_RESOLVED" | "HUMAN_DECISION_REQUIRED" |
              "UNRESOLVED" | "OPERATIONAL_WORK_PENDING" | "INVESTIGATION_PENDING";
  human_decision_required: boolean;
  actions: ActionLifecycle[]; // current investigation cycle only
  synthetic: true;
};
type ActionLifecycle = {
  version: "suhail-action-1";
  execution_id: string;
  action_type: string;
  revision: number;
  authorization: "AUTHORIZED" | "REFUSED";
  dispatch: "PENDING" | "SENT" | "UNAVAILABLE" | "REFUSED";
  acknowledgement: "PENDING" | "ACKNOWLEDGED";
  acceptance: "PENDING" | "ACCEPTED" | "REJECTED";
  execution: "PENDING" | "EXECUTING" | "FAILED" | "EXPIRED";
  verification: "NOT_REQUESTED" | "AWAITING_VERIFICATION" |
                "VERIFIED_SUCCESS" | "VERIFIED_FAILURE";
  state: "AUTHORIZED" | "REFUSED" | "AWAITING_ACKNOWLEDGEMENT" | "ACKNOWLEDGED" |
         "ACCEPTED" | "EXECUTING" | "EVIDENCE_RECEIVED" | "REJECTED" |
         "FAILED" | "EXPIRED" | "VERIFIED" | "UNRESOLVED";
  operational_label: string;
  requires_response_events: boolean;
  resolved?: boolean;
  created_at: string;
  dispatched_at?: string;
  events: Array<{id: string; kind: string; occurred_at: string; recorded_at: string;
                 evidence_ids: string[]; synthetic: true; source_ref?: string;
                 late?: boolean; rule_id?: string; request_hash?: string}>;
  synthetic: true;
};
```

Keep the axes separate. Operational axes retain the reported task facts; verification and case closure are later independent determinations. A transport receipt is not an employee acknowledgement, an accepted task is not an execution result, and an evidence receipt is not a verified result. `VERIFIED_SUCCESS` means the action's evidential effect was verified; the case can remain unresolved. Case closure is authoritative only through the verified outcome and `action_status.resolution`.

## Display field map

Every item Composer needs maps to a field that already exists in `GET /cases/{case_id}`. Only `action_status` and each execution's `action_lifecycle` are new. Where no backend field exists, the cell says so; do not invent one.

| Display | Source field | Notes |
|---|---|---|
| Case family | none in the API | `case-taxonomy.json` is a catalogue, not a classifier. If a family chip is wanted, map `diagnosis.primary_cause` or `symptom_codes` through a static frontend table and label it as a grouping, never as a diagnosis. Otherwise omit it. |
| Symptoms | `symptom_codes`; `rule_signals.signals[]` | Rule signals are deterministic checks (`is_diagnosis: false`). Show them as symptoms, not findings. |
| Investigation finding | `diagnosis.primary_cause`, `summary`, `confidence`, `missing_evidence`, `requires_physical_check`, `as_of` | Only when `diagnosis.available` and the review accepted it. Otherwise `diagnosis.unaccepted_investigation` stays under the existing unaccepted presentation. |
| Competing explanations | `diagnosis.hypotheses[]` (`cause`, `status` supported/refuted/uncertain, `assessment`, `supporting_evidence_ids`, `contradicting_evidence_ids`) | Show refuted and uncertain alternatives too; they are part of the finding. |
| Reviewer verdict | `review.verdict`, `review.reason_code`, `review.feedback`; `diagnosis.review.accepted` | REVISE is not ACCEPT. `model_verdict` is the model's own label and can differ from the enforced `verdict`. |
| Proposed action | `recommendation.action_type`, `summary_en`/`summary_ar`, `risk_class`, `authority_reason` | A proposal, not an authorization. |
| Authorized action | `action_status.actions[].authorization`, `dispatch`; `decisions[]` for a person's approval | `REFUSED` means nothing was sent. |
| Awaiting acknowledgement | `actions[].state == "AWAITING_ACKNOWLEDGEMENT"` | |
| Operational responses | `actions[].acknowledgement`, `acceptance`, `execution`, `events[]` | Each event carries `source_ref` and `synthetic: true`. `late: true` events are audit history only. |
| Evidence received | `events[]` with `kind == "EVIDENCE_RECEIVED"` and its `evidence_ids` | Receipt is not verification. |
| Verification result | `actions[].verification`; `outcome.verification_status`, `success`, `rule_id`, `reason`, `evidence_ids`, `remaining_symptoms`, `exception_cleared`, `verifier_id` | `VERIFIED_SUCCESS` is about the action's effect. The case can still be open. |
| Verified resolved | `action_status.resolution == "VERIFIED_RESOLVED"` | The only green state. |
| Still unresolved | `resolution` in `UNRESOLVED`, `OPERATIONAL_WORK_PENDING`, `INVESTIGATION_PENDING` | Show `remaining_symptoms` and the next evidence step. |
| Human decision required | `action_status.human_decision_required == true` (resolution `HUMAN_DECISION_REQUIRED`) | Use this flag, not `workflow_state == "HUMAN_REVIEW"` alone. A person doing a rescan is operational work, not a human decision. |

`action-status.examples.json` holds seven real traces from the controlled store: two verified resolved, five unresolved (continued mismatch, concurrent contradictory evidence, custody verified with handover still uncertain, rejected/duplicate/late response, foreign evidence then expiry).

## Presentation and source access

| Backend fact | Display |
|---|---|
| authorization/dispatch `REFUSED` | Authorization/context changed; nothing dispatched; show the recorded rule |
| `AWAITING_ACKNOWLEDGEMENT` | Waiting for employee/device acknowledgement |
| `ACKNOWLEDGED` | Request received; acceptance pending |
| accepted/executing + `AWAITING_RESCAN` | Awaiting independent rescan |
| accepted/executing + `AWAITING_SYNCHRONIZATION` | Awaiting device synchronization |
| accepted/executing + `AWAITING_CUSTODY_RECONCILIATION` | Awaiting directed custody check |
| `EVIDENCE_RECEIVED` / `AWAITING_VERIFICATION` | Evidence received; verification pending |
| action `VERIFIED`, case `UNRESOLVED` | Action verified; exception/uncertainty remains |
| `REJECTED`, `FAILED`, `EXPIRED`, `UNRESOLVED` | Operational request unresolved; show reason and next evidence step |
| `HUMAN_DECISION_REQUIRED` | Policy requires human judgment; show the recorded authority/reviewer reason |
| `VERIFIED_RESOLVED` | Verified resolved; link the outcome's source IDs and verifier decision |

The old `HUMAN_REVIEW` case state also appears after an unconfirmed action. Do not translate that field alone into a policy decision. Use the explicit human-decision flag and action state. Keep the underlying case/reviewer facts visible; the new presentation does not grant authority or bypass closure rules. When these additions are absent (older backend), retain existing behavior.

Use `diagnosis.available`, `primary_cause`, `confidence`, `summary`, `hypotheses`, `missing_evidence`, `requires_physical_check`, `as_of` and `review` for accepted findings. An unaccepted investigation stays under the existing unaccepted/superseded presentation. Display reviewer findings independently; REVISE is not ACCEPT. Preserve source event occurrence time versus receipt time and the investigation cutoff. Show action-event `source_ref` and link `evidence_ids` through the existing source drawer; the OpsAudit trail records the reporting local operator. Late responses are audit history and never reopen a completed/expired action.

Public IDs consistently use SYN, including dictionary keys and cross-shipment references. Actual verifier source references and rule IDs are in `outcome.evidence_ids`, `rule_id`, `reason`, `remaining_symptoms`, `exception_cleared`, `verification_status`, `verifier_id`. An acknowledgement has none of these outcome powers. Do not hide a remaining original custody gap merely because a later stock check succeeded.

## Synthetic response endpoint

`POST /cases/{case_id}/action-responses`, using the existing same-origin local operations session token/authority:

```json
{
  "execution_id": "SYN-OPS-EXECUTION-example",
  "expected_revision": 3,
  "response_id": "response_04",
  "kind": "EVIDENCE_RECEIVED",
  "occurred_at": "2026-09-20T13:00:00+00:00",
  "evidence_ids": ["SYN-SCAN-example"],
  "source_ref": "synthetic:controlled-field-response"
}
```

Allowed kinds: ACKNOWLEDGED, ACCEPTED, STARTED, EVIDENCE_RECEIVED, REJECTED, FAILED. Responses return `{action_lifecycle, idempotent}`. Exact duplicate IDs/content replay safely even after a revision; reused IDs with different content or stale new revisions return 409. Invalid/extra fields return 422; missing operator authority returns 403. There is no success/resolved/authority field. Refresh case detail after a response; its case version is separate from execution revision.

This endpoint requires both `SUHAIL_SYNTHETIC_ACTION_RESPONSES=1` and the explicitly attached synthetic response transport. It defaults off. It sends zero real-world requests and cannot create source evidence: supplied IDs must refer to already ingested, own-shipment, source-backed records received after dispatch. Synthetic field events enter through the existing controlled feed/simulation, not by inventing records in the UI. A subsequent worker verification or the existing `/cases/{id}/outcomes` request decides the result from actual source evidence.

## Composer acceptance

Use the examples and scripted backend fixtures while a separately provisioned V3.2 mutable database is pending. Test acknowledgement, acceptance without evidence, valid evidence, wrong/foreign evidence, rejection, duplicate responses, timeout, late responses, a verified action with an unresolved case, and a genuine dispute. Never show green resolution from response acceptance. Keep synthetic labels visible. No real employee/device authorization or carrier integration is implemented.

Do not run the protected V3 launcher or attach this development build to the frozen V3/V2 databases. The existing launcher intentionally targets the protected integration checkout and is unchanged. Backend source-kind/temporal verification and private evaluation answers remain outside frontend ownership. Request dataset defects through their owner; do not rewrite cases to obtain a preferred result.

Retain Composer Phase C before integration signoff, in the same Composer thread/worktree: a **60-minute manual QA budget** for the eight curated development cases and the two original video cases as read-only references where evidence is available. Reconstruct chronology and shipment/custody/device/route relationships from actual source IDs and receipt cutoffs; compare graph, map, timeline and accessible source evidence. Record competing explanations and action/verification limits before consulting isolated expectations, then produce a concise pass/review/fail matrix. Include the new pending, unresolved and verified action presentations. Dataset defects return to Sol for separately approved correction; UI defects remain Composer's. Do not alter the frozen dataset, manufacture evidence or run a live model campaign.
