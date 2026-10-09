> **Superseded (2026-10-09): not valid as an independent reasoning evaluation.** Complaint texts were
> authored per gold category and keyed the complaint-similarity retrieval, so part of the answer was
> in the input. See `docs/evals/2026-10-09_gpt-oss-v1-neutral/` for the neutral-complaint recomputation.

# Evaluation V1 closure

Closed 2026-10-08, UTC+3. **PASS for complete controlled measurement and reporting.**
This is not a production-quality approval. All 30 planned cases completed on both models
with original immutable inputs/source identities. The expensive benchmark was not restarted.
The run used dry recommendation/escalation sinks; all 14 non-timestamp before/after census
fields are identical. The graph remains 300 synthetic shipments, 3638 nodes, 4210 edges,
165 observed synthetic histories, two pending recommendations and 73 unresolved failures.
The cosine 1024 vector index remains ONLINE.

| Measure | 20B | 120B |
|---|---:|---:|
| Supported base-cause agreement |13/30 (43.3%)|16/30 (53.3%)|
| Failed-attempt family agreement |18/30 (60%)|18/30 (60%)|
| Exact seeded action agreement |7/30|8/30|
| Historical action plausibility proxy |17/30|18/30|
| Accepted recommendation / escalated |24 /6|21 /9|
| AFL cases |10/30|11/30|
| Malformed calls / attempted calls |0/145|2/149 (one case)|
| Provider exceptions / case exceptions |0 /0|0 /0|
| Mean /p50 /p95 seconds |28.648 /22.558 /53.598|8.537 /6.797 /14.746|
| Exposed numeric usage |145 calls;228448 tokens|149 calls;216611 tokens|
| Blinded editorial mean /10 |6.233|7.000|
| Editorial ready-to-show |2/30|5/30|
| Cases with critical editorial flags |11/30|8/30|
| Paired editorial preference |5 wins|19 wins|

Six paired preferences tied. Flags include rejected/contained proposals and earlier visible
iterations as well as accepted outputs; they are not counts of unsafe executed actions.
All 60 rubric records, totals, language strata, ready thresholds and 30 preferences passed
coordinator validation before alias revelation. Two AI reviewers scored disjoint case
halves, each comparing both aliases against the same evidence. This is model-blind AI
editorial review, not independent human/SPL ground truth. Their score files were saved
completely before their later account-limit errors; no missing judgments were inferred.

Language clarity means were 2.0/2 for 20B and 1.867/2 for 120B. The 18 Arabic complaints per
model did not require Arabic prose. 120B produced some mixed Arabic/English explanations;
canonical Arabic actions alone do not establish Arabic explanation quality. Automated
language heuristics mainly marked English and are less precise than the editorial notes.
Arabic UI translation is a separate, model-dependent display artifact, not tested by this
native-output benchmark. No causal Arabic-vs-English quality comparison is supported.

## Failure attribution

| Class | Evidence | Consequence / next step |
|---|---|---|
| A — model reasoning |Accepted false 2/3 exhaustion (20B case 05), cited-action misattribution (20B case 07), 2/3=80% (120B case 12), five same-action successes vs one (120B case 15); reported locations upgraded to courier visits|No reviewer acceptance-as-correctness claim. Post-eval operator summaries now compute counts/rates and label diagnoses hypotheses; internal judgments still require verification.|
| B — rules/prompts |Reviewer sometimes interpreted every redirect as prohibited retry and suggested unsupported cancellation/refund authority; repeated plain retries were hard-rejected|Preserve hard retry rules; clarify their scope and withhold invented model policy prose from operator/persisted summaries.|
| C — insufficient evidence |Gate/weight/barcode groups share event patterns without measured subtype observations; selected-label agreement is0/5 for most of these groups|Dataset V2 must generate observations first and derive exceptions; missing-evidence cases need abstention/human review. More parameters cannot recover absent facts.|
| D — evaluation/harness |Controlled extraction does not alter frozen retrieval; leave-one-shipment-out references may contain other benchmark shipments; synthetic actions/outcomes are not human gold; low first-retrieval category proxy0.16|Report controlled scope, proxies and planned denominators. Earlier identity/fairness defects were fixed before cloud execution. Root corrected an aggregate table-order defect before publication.|

First/final cause agreement did not improve or regress through AFL in this 30-case run.
AFL did revise actions or escalate; do not claim measured diagnostic improvement here.
False acceptance/rejection remains unavailable without independent adjudication. Wilson 95%
agreement intervals are broad (20B 27.38–60.80%, 120B 36.14–69.77%); these balanced synthetic
samples are not random production samples and do not establish significance.

## Model recommendation and preservation

Recommend **120B for development and a curated, human-reviewed demo on this tested cloud
endpoint**: higher descriptive cause agreement, 19–5 editorial preference, fewer flagged
cases and lower measured latency. There is no measured latency penalty to justify default
20B here. Keep 20B for inexpensive comparison only if separately measured billing supports
that choice; token counts do not establish monetary cost. Neither is approved for autonomous
physical execution. Default code/example config now recommends 120B; the existing local
environment explicitly selecting 20B was preserved and still overrides that default.

Original metric values, result records and manifest are immutable V1 evidence. Comparison reports now carry derived closure annotations linking the completed blind review; these annotations do not rescore the run. Post-run changes to the
operator boundary and reviewer prompt do **not** change these scores and do not claim new
model quality. The strict V1 runner will refuse current-source resume/report after source
changes; use these archived results or a separately versioned future bundle. An offline
60-output replay validates display regressions without model calls or DB writes.

See [machine comparison](comparison.json), [paired report](comparison.md),
[blinded scores](quality-review/summary.md), methodology/fairness companion notes and
before/after census under docs/agent-runs. Remaining semantic defects are explicit limits
of the experimental baseline, not hidden improvements attributed to this evaluation.
