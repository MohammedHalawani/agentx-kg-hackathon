# Evaluation V2 plan

Design 2026-10-08. V1 remains closed with30 paired cases; it is not rerun automatically.
V2 execution starts only after data/derivation/lifecycle and harness gates, with an explicit
cloud-call budget. None of the measurements below has been run yet.

## Data and task contract

Evaluate supported cause **and evidence sufficiency**, alternative diagnoses, applicable
next action and correct lifecycle destination. Allow unknown/insufficient_evidence,
conflicting_evidence and multi-cause sets. A barcode/weight/gate subtype cannot be established
without its raw observation. Known expected status is not a model-input cause label.

Core strata: address conflict, documented recipient unavailability, wrong gate, barcode
discrepancy, weight discrepancy, contextual hub dwell, explained route/traffic delay,
unreconciled custody, transfer custody gap, corroborated-delivery dispute, possible
misdelivery/status-proof conflict, and ambiguous/multi-cause evidence. Include normal
controls across every class. Record primary stratum plus overlapping causes; score sets
and evidence references rather than force a single oracle label.

Propose 60 unique hard shipments (five per core stratum), 30 Arabic/30 English complaints
assigned before execution and identical across models. Separately translate 12 anchor cases
to the other language for a paired-language diagnostic:72 inputs/model, 144 planned total
for 20B/120B. Report the 60-unique-shipment headline and 12 bilingual anchors separately;
they are not 72 independent shipments. This proposed cost requires a future budget approval,
not an automatic run. A 24-input smoke establishes protocol before the 144-attempt run.

Split whole shipments with all packages/cases/events/failures/resolutions/outcomes together.
Keep scenario/template/time groups separate where possible; test unseen wording and city
combinations without claiming geography alone causes quality. History references are
verified-outcome synthetic stories, never the held-out shipment or any sibling. Freeze
corpus membership, complete evidence, rules, prompts, model/provider settings, extraction,
first and category-conditioned retrieval. Do not give one model gold-guided retrieval.

Runtime DTOs contain observations/known policy, not scenario names, gold cause, retrospective
FailureReason description, chosen action or future outcome. Own current asserted status may
be necessary for delivery disputes; keep it as an assertion paired with independently
modeled proof/complaint, not as hidden ground truth. IDs/facility names must not encode cause.

## Gold and adjudication

Simulation truth is useful for chronology/physical consistency, but is not automatically
operator ground truth. Maintain scoring-only expected causes, uncertainty, evidence IDs,
required/forbidden action conditions and permitted final state. Two independent domain
reviewers adjudicate an anchor/validation set before model output review; resolve disagreements
and report agreement. If human/domain review is unavailable, label reference-rule/AI judgments
honestly and keep false-acceptance/rejection and production effectiveness unavailable.

Random historical success booleans and one exact action string are insufficient action
gold. A action may be plausible only after address/contact verification/consent. Verified
administrative correction and verified physical delivery have separate outcome targets.

## Metrics and denominators

| Dimension | Proposed measurement |
|---|---|
| Diagnosis |Cause exact/set/family agreement, per-stratum confusion; evidence-ID precision/recall; unknown/conflict/multi-cause handling|
| Factual fidelity |Correct counts/units/times/policy comparisons; attributed reports vs recorded facts; unsupported hard-fact and person-blame flags|
| Action |Adjudicated conditional action appropriateness and forbidden-action rate; exact string only as secondary descriptive metric|
| Review/AFL |Accept/reject/escalation, actual bounded iterations, changed action/cause, correction/regression; false acceptance/rejection only on independent adjudicated subsets|
| Lifecycle |Approval/execution/outcome provenance, no false RESOLVED, pending exclusion, reopened/invalidation behavior|
| Retrieval |Observed-corpus eligibility, relevant-evidence/case retrieval, complete sibling exclusion, vector/structural contribution and abstention when irrelevant|
| Language |Same-case 12-anchor AR/EN comparison, clear neutral Arabic, intact IDs/numbers; native backend vs deterministic/localized display separate|
| Reliability |Call/attempt malformed JSON, missing/invalid shapes, typed provider exceptions, fallback model, resumed failed attempts, no hidden retry bias|
| Performance |Case and stage mean/p50/p95 with sample counts; measured numeric usage; optional cost only with verified pricing/billing|

Use all planned attempts for headline rates; errors/no-grounding/missing completed rows
remain visible. Report call denominators separately. Paired comparisons use the same
case-language/evidence assignment and randomized/alternating model order; temperature,
timeout/retries and budgets fixed. Preserve successful/failed attempts and source/provider
hashes on resume. Blinded editorial rubric scores final/earlier outputs before identity,
latency or cost revelation. Statistical intervals are descriptive, not production claims.

## Gates and ablations

Hard gates: zero evaluation DB/notification/external writes, zero hidden thinking in public
artifacts, zero held-out siblings in banks, zero pending/unverified outcomes in precedent,
zero model self-certification of RESOLVED, and complete immutable result identity/attempt
accounting. Exact deterministic facts and lifecycle invariants must pass every fixture.
Model quality thresholds should be frozen using independently reviewed validation cases
before touching test gold; do not choose them after observing a favorable test run.

Compare full graph evidence versus vector-only, timeline-only and omitted key observation
on a prespecified small anchor set. Removing a barcode/weight/contact/custody observation
should increase uncertainty rather than retain the same confident cause. Verify GPS-only
does not yield parcel-location proof/driver blame. Test traffic+safe return remains an
accounted-for delay. These are additional planned experiments, not hidden changes to the
main paired inputs. Include actual full extraction→retrieval integration alongside a
controlled frozen-context arm so extraction failures are no longer invisible.

Output: versioned runtime/gold/corpus/membership/source/provider manifests, final structured
case/call rows, model-blind review packets/score keys, diagnostics/comparison and graph
census before/after. Never store raw provider thinking, credentials, prompts containing
PII or raw exceptions. No live email, real execution or production-accuracy claim.
