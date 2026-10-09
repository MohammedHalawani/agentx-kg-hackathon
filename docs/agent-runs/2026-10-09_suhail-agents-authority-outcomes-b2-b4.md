# Suhail — Batches 2–4: GPT-OSS agents, action authority, outcome engine (2026-10-09)

Branch `fhd`, continuing from `1407511`. All three gates passed live against real Neo4j and real GPT-OSS.

## Batch 2 — model-backed V2 investigation

- **Model:** `openai/gpt-oss:120b` through the existing V1 LiteLLM plumbing (`llm/pipeline/_llm.ask_json`, Ollama Cloud).
  It reuses V1's private-reasoning stripping. Switch it off with `SUHAIL_V2_AGENTS=off` (deterministic only).
- **Fact packet** (`operations/agents.facts`): built by code only, from evidence visible at `as_of`. It contains
  shipment fields, evidence counts, deterministic signals with evidence IDs, expected-vs-actual milestones, custody,
  up to 60 observations, verified precedents and the whitelist `visible_evidence_ids`.
- **Roles (real LLM calls):**
  - Diagnose stage → **investigator**: hypothesis, alternatives, supporting/conflicting IDs, missing evidence,
    confidence, sensitivity.
  - Recommend stage → **planner**: an action from the catalog, evidence basis, expected result and reason.
  - Review stage → **reviewer**: ACCEPT / REVISE / HUMAN_REVIEW / ESCALATE, followed by the existing deterministic
    guard. REVISE feeds back into the LangGraph retry loop (at most 2).
- **Validation** rejects:
  - IDs that are not visible;
  - a hypothesis with no supporting deterministic signal;
  - numbers that are absent from the packet;
  - GPS treated as delivery evidence;
  - personal blame, theft or fraud language;
  - prohibited or unknown actions.

  A rejected output is retried once with feedback, then replaced by a fallback labelled `deterministic_fallback`.
- **GraphRAG:** the existing `PRECEDENTS` traversal already meets the eligibility rules: history split only,
  VERIFIED and non-invalidated outcomes, operator-approved executions, and `verified_at <= snapshot`.
  Held-out and development data are never used.
- **Live result:** SYN-SHP-000041's investigator, planner and reviewer all ran on GPT-OSS on the first attempt.
  They cited only visible IDs and quoted the real barcodes. No chain-of-thought appears in stored output.
  A case takes about 37 s.

## Batch 3 — action authority (`operations/authority.py`)

- **Risk classes:**
  - AUTO: rescan, reweigh, custody reconciliation, hub check, prioritize next session, address confirmation,
    additional evidence.
  - APPROVAL_REQUIRED: reroute, return to sender.
  - HUMAN_REVIEW: delivery dispute review, conflicting custody review.
  - PROHIBITED: compensation, liability.
- **Policy order:**
  1. A reviewer HUMAN_REVIEW or ESCALATE verdict goes to a human.
  2. Sensitive codes (dispute, misdelivery, conflicting custody) go to a human.
  3. A rule-flagged evidence conflict goes to a human.
  4. An AUTO action that doesn't address a supported diagnosis needs approval.
  5. AUTO is allowed only in a synthetic **live session**; otherwise approval is required.
- **Executor:**
  - A deterministic `OpsExecution` is written with `authority=AUTO_POLICY`, `decision_id=None`, a synthetic receipt,
    an idempotency key and a 72-hour scenario deadline.
  - Audit records `ACTION_AUTHORIZED` (SUHAIL-AUTHORITY-POLICY) and `ACTION_INITIATED` (SUHAIL-SYNTHETIC-EXECUTOR).
  - The case moves RECOMMENDATION_READY → ACTION_INITIATED → AWAITING_OUTCOME.
  - No external call is made.

## Batch 4 — outcome engine (`operations/outcome_engine.py`, `store.outcome_step`)

- **Inputs:** only evidence that occurred after the action and is visible at the clock.
- **Rules per action:**

  | Action | Success | Failure |
  |---|---|---|
  | Rescan | Matching readable scan | Persistent mismatch |
  | Reweigh | Matching calibrated kg measurement | Calibrated measurement still differs |
  | Address confirmation | Verified, confirmed AddressVersion | — |
  | Custody reconciliation, hub check | Corroborated custody for every package | — |
  | Any action | Corroborated delivery proof for every package | — |

  For every action, a new NOT_RECEIVED report counts as failure (`dispute_unresolved`), and so does reaching the
  deadline with no confirming evidence.
- **Success:** a VERIFIED `OpsOutcome` (verifier SUHAIL-OUTCOME-VERIFIER). The case becomes RESOLVED with
  `is_terminal`, `closed_at` and `verified_outcome_id`, plus a dry-run notification.
- **Failure:** NEEDS_EVIDENCE for evidence-type actions; HUMAN_REVIEW otherwise and for disputes. Never RESOLVED.
- **Learning eligibility:** resolved live cases are development split, so they are never precedent. Precedent stays
  history-only.

## Intake

- `GET /cases/queue?scope=active|resolved|all`, default `active`. Terminal means `is_terminal` (or a legacy
  RESOLVED state). A reopen clears the terminal fields.
- UI:
  - Active / Resolved / All segmented control.
  - Counters use `scope=all`.
  - The issue text becomes the neutral rule diagnosis after investigation.
  - Each stage shows its actual engine.

## Live rehearsal (fresh session, 600×)

| Case | Path | Result |
|---|---|---|
| 000041 | barcode → REQUEST_RESCAN | Matching scan at 17:00 (action 09:59) → **RESOLVED**, no human |
| 001601, 000802 | weight → REQUEST_REWEIGH | **RESOLVED**, no human |
| 000762 | — | **RESOLVED**, no human |
| 001241, 001642 | delivery dispute | HUMAN_REVIEW |
| 000601 | GPT-OSS reviewer escalated | HUMAN_REVIEW |
| 001721 | INITIATE_CUSTODY_RECONCILIATION | No confirmation by deadline → OUTCOME_FAILED → HUMAN_REVIEW (not resolved) |

Zero `OpsDecision` records exist for any of the resolutions.

## Limitations

- The runtime loop is single-threaded: the scenario clock pauses during a model investigation (~37 s).
- At 600×, a shipment with new events during an investigation is re-queued (snapshot guard).
- The case workspace still offers manual outcome controls for auto cases in AWAITING_OUTCOME.
- Rows leave Active on refresh without an exit animation.
- Arabic text for model summaries is not generated; Arabic shows the rule labels.
