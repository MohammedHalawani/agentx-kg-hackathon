# AgentX / Suhail — evaluation closure and Dataset V2 signoff

Timestamp: 2026-10-08T16:39:53.370962+00:00 (UTC; local timezone Asia/Riyadh). Current branch: **fhd**.
Validated baseline/evaluation/design HEAD before this report's enclosing signoff commit:
**7ce7a62751dc643731812bad3e40070d90bda142**. The final delivery HEAD is the commit that first adds this report; its exact
hash and remote push result are provided in the completion reply. It is also obtainable
with `git log -1 --format=%H -- docs/agent-runs/2026-10-08_agentx-evaluation-dataset-v2-final.md`.

The latest request superseded immediate implementation of the earlier product-expansion
phases. This run closes V1, stabilizes the current baseline and delivers **V2 DESIGN ONLY**.
No major UI redesign, V2 database import, outcome write API or live email was implemented.

## Commits and working-tree preservation

| Exact commit | Change |
|---|---|
| 295d03d76640a1e626f1cb12ec0321f60896dcf4 | fix(suhail): enforce shipment evidence and pending outcome boundaries |
| 7e6f40e4003f75d3afa326f5d3c0ae11ac4d63a1 | fix(suhail): align shipment exploration and Arabic operator UI |
| 8d35afeae5fadb2b2e684c7994805f9a6bf747ec | test(suhail): archive closed-loop proof and GPT-OSS V1 evaluation |
| 7ce7a62751dc643731812bad3e40070d90bda142 | docs(suhail): design evidence-derived logistics Dataset V2 |

A final documentation signoff commit adds this report. All requested gates passed before
the first baseline commit. Earlier untracked `agentx-local-baseline-*`,
`agentx-ollama-cloud-*`, `_agentx_gpt_oss_eval_results.json` and browser scratch files were
preserved outside these commits. All current tracked implementation changes are committed.
The local environment remains ignored and secrets were neither printed nor staged.
The fetched remote was an ancestor; eight pre-existing local commits are also part of the
ordinary fast-forward push. No main merge, reset, force push or history rewrite occurred.

## Evaluation V1 closure

All 30 paired cases completed on each model, with disabled writeback/case-file sinks.
The completed 60-case run was preserved without an expensive rerun. All 60 model-blind
editorial rubric records were saved before alias-key reveal. This is AI editorial review,
not independent human/SPL operational ground truth.

| Measure | 20B | 120B |
|---|---:|---:|
| Base synthetic root-cause agreement |13/30 (43.3%)|16/30 (53.3%)|
| Cause-family agreement |18/30|18/30|
| Exact seeded action / history plausibility proxy |7/30 / 17/30|8/30 / 18/30|
| Reviewer accept / escalation |24 / 6|21 / 9|
| Cases using AFL |10|11|
| Provider exceptions / calls |0/145|0/149|
| Malformed output calls |0|2 (one case; failed closed)|
| Mean / median / p95 seconds |28.648 / 22.558 / 53.598|8.537 / 6.797 / 14.746|
| Reported tokens (numeric usage on all calls) |228448|216611|
| Blind score / ready-to-show |6.233/10 / 2/30|7.000/10 / 5/30|
| Critical-flag cases |11/30|8/30|
| Paired preference wins |5|19|

Six paired preferences tied. Barcode/weight/gate subtypes remain weak: most had 0/5 agreement;
120B barcode was 1/5. No first-to-final cause improvement/regression occurred through AFL.
Token usage is not a billing comparison. Accepted cases and ready-to-show thresholds do not
establish operational correctness. Independent false acceptance/rejection is unavailable.

Recommend **120B for development and the curated, human-reviewed final demo on the tested
cloud endpoint**. It had higher descriptive agreement/editorial quality and lower measured
latency. Code/example defaults now recommend 120B; the explicitly configured local 20B
selection was preserved and still overrides them. Neither model is approved for autonomous
physical execution.

Failure attribution:

- **A — model reasoning:** fabricated attempt/exhaustion/rate claims, unsupported certainty,
  citation/action misattribution and accepted factual mistakes. Source-derived operator and
  persistence summaries now compute those facts; internal category/action judgments remain
  unverified. Four saved accepted false-fact examples and all 60 outputs were replayed offline.
- **B — business rules/prompts:** plain retry versus verification/redirect ambiguity and
  invented refund/cancellation authority. Prompt clarification and existing hard rules help;
  V2 needs versioned policy/action authority rather than model-invented rules.
- **C — graph evidence:** missing measured barcode, weight, gate/contact outcomes, custody,
  vehicles, session reconciliation and contextual expected journey. More model parameters
  cannot reconstruct absent observations.
- **D — evaluation/harness:** synthetic labels/actions/random outcomes are proxies; controlled
  extraction does not change frozen retrieval; other cohort shipments can be reference history;
  18 AR/12 EN are different-case inputs rather than bilingual pairs. Earlier identity/fairness
  defects and summary column ordering were fixed before publication. V2 must use grouped
  holdouts, evidence-derived gold and same-case language anchors.

See [complete evaluation closure](../evals/2026-10-08_gpt-oss-v1/closure.md),
[comparison](../evals/2026-10-08_gpt-oss-v1/comparison.md) and
[blinded review](../evals/2026-10-08_gpt-oss-v1/quality-review/summary.md).
Post-run prompt/operator fixes do not rescore the archived benchmark or prove new model quality.
Frozen inputs/results/metrics remain intact; derived closure annotations simply link completed review.

## Baseline verification and graph changes

Python: **81 tests passed**. Frontend: **107 tests / 28 files passed**, followed by **12 focused
Intake/language/parity tests** after the final review copy correction. Lint: **zero errors,
13 existing warnings**. TypeScript/Vite build, tracked/staged whitespace checks and secret
scan passed. Latest pre-signoff scan checked 426 text files. A trailing blank line in the new
rubric was removed when staged whitespace checking exposed it; rubric criteria were unchanged.
The final report is scanned again before its commit.

Read-only API/browser checks confirm shipment Explore routing, five filters, address map,
bounded shipment graph, live schema, Intake 73, Decisions 165 observed histories/two pending,
English LTR/Arabic RTL and responsive navigation without horizontal overflow. Legacy chat and
registry return 410 on valid requests; favicon loads. Private provider thinking is excluded
from normalized display/SSE/persistence. Pending recommendations cannot enter precedent or
success/failure denominators. Stable-ID/transactional writeback replay is covered by tests and
prior sequential/concurrent controlled proof.

**No graph writes occurred during V1 evaluation or this closure/design phase.** Evaluation
before/after and latest stabilization census match in every non-timestamp field:
300 shipments, 3638 nodes, 4210 edges, 165 observed outcomes, two pending recommendations,
73 unresolved failures; cosine 1024 vector index ONLINE. The earlier authorized October 7
SHP-0004 controlled proof added two nodes/two edges for a pending recommendation and a
case_summary on its existing failure; replay added nothing. The older SHP-0227 pending
chain stayed unchanged. No V2 graph/schema mutation occurred.

Fresh read-only independent review caught an EN/AR rejection claim that incorrectly implied
no escalation record could be written. It now says no recommendation was recorded and human
review is required. Reviewer conditional PASS was satisfied. Remaining limits: experimental
model/rule authority, approximate V1 timeline span, no real outcome-confirmation integration,
translation presentation-only, library deprecations and roughly 4 MB application/graph bundle.

See [baseline gate](2026-10-08_baseline-stabilization-gate.md) and
[V1 gate](2026-10-08_gpt-oss-evaluation-v1-gate.md).

## Dataset V2 proposal and next implementation order

Seven detailed artifacts propose a connected Saudi demo network across the nine requested
cities, with 600 shipments (360 observed histories, 120 development, 120 held-out test),
24 scenario narratives and all requested entity types. Observations precede derived exceptions.
Custody, package/vehicle compatibility, expected-versus-actual journey, delivery disputes,
traffic, returns, multi-package outcomes and reopened cases are explicit. Vehicle GPS alone
is not parcel position; missing reconciliation is neutral UNRECONCILED_CUSTODY. Nobody is
blamed without evidence. Recommendations, operator approvals, execution receipts and verified
outcomes have separate authority. All facilities/routes/fleets/schedules/policies are synthetic
assumptions; public address/API documentation does not certify generated SPL infrastructure.

Read the [design catalog](../design/2026-10-08_dataset-v2/README.md),
[graph schema](../design/2026-10-08_dataset-v2/graph-schema.md),
[scenario matrix](../design/2026-10-08_dataset-v2/scenario-matrix.md),
[generation/migration/reset](../design/2026-10-08_dataset-v2/generation-migration.md) and
[Evaluation V2 plan](../design/2026-10-08_dataset-v2/evaluation-v2.md).

Next batches: contracts/narratives → offline deterministic network generator → evidence
and exception derivation → isolated shadow import/read adapter → reasoning contract →
operator/outcome authority → sequential queue/audit → dry notifications → controlled V2
evaluation → UI planning/implementation → demo readiness. Each has audit/implementation/
review/gate exit criteria in [implementation batches](../design/2026-10-08_dataset-v2/implementation-batches.md).
Never delete V1 to restart a demo. Dry notifications make zero provider calls even with keys.

Manual decisions before dependent future work: synthetic size/network/policy assumptions;
Neo4j edition/isolated target and backup choice; operator roles and outcome verification
policy; model-call budget and domain adjudication. Live notifications additionally need
sender/recipient/consent choices and explicit send authorization. No permission is needed
to review the completed design.
