# GPT-OSS v1 independent fairness and harness review

Recorded: 2026-10-08T13:22:45+03:00; final review: 2026-10-08T13:34:06+03:00.
Status: **PASS for the frozen paired cloud benchmark**. This is readiness approval, not a
claim that model performance has passed: no benchmark cloud results existed at this review.
Scope: read-only implementation review and offline provider fixtures. No cloud model calls,
Neo4j queries/writes, evaluation bundle preparation, or production-feature edits by this reviewer.

The reviewed harness is `chat/scripts/evaluate_gpt_oss_v1.py`. The old eval_pipeline.py is
not the benchmark: its self-including action statistics and successful-only exception
denominator must not be merged into these results.

## Data and gold isolation

The corpus uses seeded Resolution.source null and actual boolean Outcome.success. Preparation
selects 30 distinct shipments, five per supported base category, with an intended modest
escalation subset. The schedule is 18 Arabic/12 English complaints (three/two per category).
Both models receive the same 30 case-language inputs; this is paired across models, not
same-case bilingual translation testing.

Own local context retains operational shipment/courier/policy/address/event facts. Own
retrospective failure, description, resolution, outcome and status are withheld. Neutral
case IDs do not expose categories. Known category-specific symptom templates are synthetic
complaints, not actual customer traffic; barcode and weight inputs deliberately share a
symptom because the available local observations cannot distinguish them reliably.

The complete held-out shipment FailureReason membership, including escalation/base siblings,
is excluded from first retrieval, every second-pass bank and plausibility scoring history.
Membership validation now checks that the excluded set is complete. Frozen second-pass
lookup is selected only by the model's predicted category; it never uses the expected cause
or model rationale. Both models therefore share the same bank for the same predicted branch.

Gold is held in a separate scoring file and is absent from graph state/model prompts.
Bundle verification reads it to validate the protocol before execution; scoring reads it
after each run. This is isolation from model inputs, not a claim that the process never
opens gold before a provider call. Other evaluated shipments may remain historical references
for a given held-out shipment; the protocol excludes the whole current shipment, not the
entire 30-case cohort, and conclusions must describe that leave-one-shipment-out design.

## Execution safety and reproducibility

Real extract/classify/recommend/review/AFL code runs with frozen retrieval, disabled case-file
construction, dry recommendation/escalation returns, and forbidden live retrieval/writer
driver access. No physical execution or outcome is observed. An independent offline accepted
path traversed all four model-backed stages through a fake final-only provider: driver
fail-spies were never called, the final outcome remained unconfirmed, and private reasoning
and provider metadata sentinels did not enter saved results. A synthetic selection fixture
returned 30 unique shipments with one escalation per supported base.

The initial review found the evaluator's own source missing from the source freeze, weaker
report identity checks than resume, an all-escalations sampling preference despite the
one-escalation docstring, and requested error rates represented only as counts. These findings
were sent to the owner before preparation or model runs. The owner has added evaluator,
retrieve/writeback source hashes, provider endpoint identity hash (no credentials), stronger
case/model/language/gold/source/version result identity, modest escalation ordering, and
explicit call/planned-case error rates. Out-of-range confidence/review score and unsupported
extractor category hints are now diagnosed; exact seeded (failure, resolution) identity is
required, so a later agent chain on a seeded failure cannot enter the benchmark.

All 15 final offline harness tests passed independently. The evaluator source SHA-256 is
`c9eeb8c5326c55a6a720f0b032080004800f008d2d6098891717305d089da0eb`.
No owner script or production code was edited by this reviewer.

Changing prompt/rule/evaluator/input/provider identity must invalidate resume/report. Completed
error rows must remain completed attempts; automatic omission/retry would bias denominators.
Provider responses are retained only through the final-field boundary, with allowlisted
numeric usage counters and exception type. No raw response, credential, private reasoning,
or raw exception text is required for reporting.

## Metric meanings

All model rate denominators are 30 planned cases; exceptions, malformed/fallback results,
no-grounding exits and unattempted partial rows are visible. Call-level malformed/exception
rates use attempted calls separately. Latency distributions state their observed sample size.

Supported base-cause agreement, broader failed-attempt family agreement, raw source-label
agreement including unsupported escalation prefixes, and agreement with any recorded cause
on a multi-failure shipment are separate metrics. A raw escalation-prefix miss must not be
described as failure to identify its supported underlying root cause. Seeded action agreement
and historical plausibility are synthetic proxies; plausibility excludes all held-out sibling
histories. Reviewer acceptance is not independent correctness, and false acceptance/rejection
remain unavailable without independent adjudication.

The controlled-evidence design measures extraction separately while preventing extracted
fields from changing shared evidence. It consequently does not measure real end-to-end
missing-context routing after extraction failures. Arabic canonical actions do not establish
Arabic explanation quality; actual native prose language and independent rubric review must
be reported separately. Fluency/acceptance cannot establish factual fidelity.

## Actual prepared bundle gate

The immutable bundle at `docs/evals/2026-10-08_gpt-oss-v1` was inspected after preparation.
Its runtime SHA-256 is
`5fa0ab93c2b4973192b28647a45d1137063c7378ed7c35a978ccd250637a0ca5`.
The real verifier passed source, provider, template, runtime, gold, corpus and membership
identity checks without contacting a model or database. Independent additional assertions
confirmed 30 unique shipments, five per base category, 18 Arabic/12 English cases, and five
multi-failure held-out shipments. All 210 banks (30 initial plus 180 category branches)
contain five references; all 1,050 reference rows have boolean observed outcomes and exact
seeded failure/resolution pairs from the 165-row frozen eligible corpus. Complete own
sibling sets are absent from every bank and plausibility history. Own operational context
contains only the allowlisted shipment, courier, policy, address and event fields: no own
failure IDs, retrospective label/description, action, outcome or shipment status.

There is no known leakage, database-write, private-reasoning or resume-identity blocker in
the frozen implementation and bundle. Parent may run the planned 60 paired case/model
attempts with dry writeback. Source changes invalidate this gate. Synthetic proxies,
underidentified subtypes, language difficulty confounding, lack of independent reviewer
gold and controlled extraction routing remain reporting limits, not grounds for production
accuracy claims. Five escalation histories are included; escalation-first language ordering
does not support a causal Arabic-versus-English comparison. Independent post-run rubric
review and explicit exceptions/partial denominators remain required before Batch3 completion.
