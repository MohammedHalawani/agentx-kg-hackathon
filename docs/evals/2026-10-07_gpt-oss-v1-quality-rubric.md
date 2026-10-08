# GPT-OSS v1 operator-output quality rubric

Recorded: 2026-10-07 22:53 +03:00 (19:53 UTC). Protocol fixed before reviewing paired 30 model results. This planning review made no model calls or database writes.

## What is scored

Score only structured final operator outputs: classification category/confidence/priority/rationale, recommended action/cited resolution IDs/rationale, final reviewer verdict/reason/checks, and any operator-facing escalation summary. Never inspect or retain provider thinking. Assess the final accepted/escalated iteration; separately flag factual/action errors in earlier visible iterations and whether review corrected them. An accepted review is a model/policy judgment, not proof of correctness or operational success.

For each case the reviewer needs the complaint, frozen own-shipment evidence, deterministic attempt/timeline/policy findings, retrieved observed-outcome cases, actual cited IDs and final outputs. Mark a dimension **not assessable** when required evidence is absent; never award points by guessing. Keep root-cause exact/family accuracy, recorded-action agreement, acceptance, latency and parsing metrics separate from this rubric. Fluent text can accompany a wrong diagnosis.

## Five dimensions, each 0–2

| Dimension | 2: operator-ready | 1: needs a small edit | 0: unreliable or unusable |
|---|---|---|---|
| Factual fidelity | Counts, IDs, policy values, comparisons and timeline statements match supplied evidence; complaint assertions are attributed. | Minor imprecision does not change the operational interpretation; no invented hard fact. | Invented/wrong count, ID, location, SLA comparison, cited success rate or claimed event; unsupported causal certainty. |
| Evidence and concision | One or two useful sentences per rationale/reason connect concrete evidence to diagnosis/action. | Grounding is recoverable but generic, repetitive or unnecessarily long. | Unsupported assertion, contradiction, irrelevant narrative or no usable evidence summary. |
| Action and review consistency | Action addresses this cause, respects recorded retry/SLA findings, cites applicable observed cases; verdict and reason agree. | Plausible next step with an omitted condition or a small rationale mismatch. | Plain retry with exhausted budget, wrong-cause remedy/citation, verdict contradicts findings, or unsupported authority/execution. |
| Language clarity | Target-language prose is clear and grammatical; Arabic reads naturally; identifiers/numbers stay exact and mixed text remains understandable. | Awkward grammar/translation or terminology, but an operator can understand the instruction. | Ambiguous/unintelligible instruction, corrupt identifier/number, substantial wrong-language prose when a target was required. |
| Uncertainty and lifecycle honesty | Missing facts stay unknown; inference is qualified; recorded recommendation, review acceptance, human approval, external execution and observed outcome are distinguished. | Slight overconfidence or an omitted uncertainty qualification without a materially false claim. | Asserts delivery/execution/success from recommendation or reviewer approval; invents enterprise/GPS capability or attributes wrongdoing without evidence. |

Use integer scores with a short evidence-based note. Report each dimension separately and a 0–10 total only when all five are assessable. A provisional “ready to show” indicator requires no critical flag, factual/action/lifecycle dimensions all 2, language at least 1 and total at least 8. This is an editorial threshold, not a measured accuracy or safety guarantee.

Critical flags override a high total: exposed provider thinking; fabricated operational fact affecting the decision; exhausted-budget plain retry; false execution/success; unauthorized or unsupported enterprise action; GPS presented as parcel proof or driver blame. Preserve only a minimal final-output excerpt needed to show the defect and the contradictory recorded fact.

## Evidence anchors and category boundaries

The six supported base categories are `address_conflict`, `recipient_unavailable`, `hub_delay`, `failed_attempt_wrong_gate`, `failed_attempt_barcode_mismatch`, `failed_attempt_weight_mismatch`. An `escalation:` prefix is case history on the same base cause, not a seventh independent root cause. Loss/GPS/vehicle causes are absent from this baseline.

| Base cause | Existing action vocabulary families to assess for applicability |
|---|---|
| Address conflict | Confirm/correct destination, obtain coordinates with the customer, redirect; scheduling remains conditional on retry policy. |
| Recipient unavailable | Contact recipient for an alternative time, reschedule when permitted, alternative recipient only with consent. |
| Wrong gate / barcode / weight | Correct shipment data, relabel/recheck or arrange an operational handoff when relevant. Shared failed-attempt actions are not a unique subtype oracle; do not claim a gate/barcode/weight remedy is established without its specific evidence. |
| Hub delay | Alternative sorting path, expedited transport or notify/update ETA, with availability presented as a recommendation rather than a confirmed enterprise capability. |

Synthetic escalation actions include supervisor coordination, combined corrections and reopening for multiple causes. A permitted vocabulary string alone does not make an action appropriate. Rate action agreement against the seeded label separately from manual plausibility; the seeded action may be one of several plausible options.

Specific pitfalls to check equally for both models:

- Two recorded DELIVERY_ATTEMPT events are two attempts, not proof both failed. A linked FailureReason does not automatically establish every attempt's outcome.
- Two attempts against limit 2 exhaust the budget; they do not exceed it. SLA breach requires recorded timeline span strictly greater than policy SLA; equality is not a breach.
- The deterministic current timeline span is calculated from minimum/maximum valid recorded event timestamps. It is not wall-clock age or live lateness today. Missing policy/timeline evidence is unknown.
- A 2/2 cited success rate is a tiny synthetic observed sample, not a general 100% guarantee. Verify numerator/denominator and exact cited IDs against retrieved evidence.
- Root-cause rationale, recommended action and review reason must agree; an accepted review may still contain a factual error.

## Language and blind paired review

Record complaint language, required prose language and actual final prose language separately. Current prompts often produce English rationale/review text even for Arabic complaints, while canonical action strings are Arabic. Arabic action text alone is not evidence of Arabic explanation quality; canonical Arabic actions/technical IDs do not count as English grammar errors. If no target language was requested, record language mismatch as a product observation rather than retroactively inventing a scoring requirement. A UI translation output is a separate artifact and cannot be assumed from an English backend rationale.

Coordinator's post-Batch2 Arabic browser observation: Decisions displayed 2 pending recommendations, 165 observed outcomes, 149 successes and 90%; no provider thinking/error/overflow was observed. Root HTML/main layout remained LTR despite Arabic labels. Keep that rendering-direction observation for the gated Phase 8 audit, separate from backend output-language quality. The benchmark retains native English explanation/Arabic canonical-action mixtures; any UI translation is a separate model-dependent display output and is not scored as if it were the benchmark's native Arabic explanation.

For paired 30 review, use neutral A/B output aliases assigned independently per case and hide model names, parameter sizes and latency during scoring. Score both against the same frozen evidence before revealing the model key. Prefer ties to unsupported preference. If complete blinding is unavailable, explicitly report that limitation; prior baseline model examples are calibration anchors, not benchmark scores.

Store reviewer/case/alias/iteration/language metadata, five scores, critical flags, concise notes and final A/B/tie preference. Report per-model score distributions, each dimension's defect count, critical failures, not-assessable counts and language-specific denominators; add latency only after quality scoring. Thirty synthetic cases support an initial comparison, not production accuracy or population-wide reliability.

## Why this is not human SPL ground truth

The generator declares a synthetic dataset, uses `random.seed(42)`, chooses seeded actions from a category list and generates `Outcome.success` with `random.random() < 0.85`. Its Standard/Express/Economy policy values, warehouses/couriers and event patterns are demo rules/data. Real Saudi city/district names do not turn parcel histories into enterprise observations. Live graph counts may differ from generator constants after augmentation and controlled recommendations; use the frozen evaluation snapshot.

“Verified history” in this baseline means the graph has a non-null recorded synthetic outcome eligible for retrieval/statistics. It does not mean an SPL operator adjudicated the cause, executed the action, confirmed delivery or approved these service rules. Excluding pending recommendations prevents feedback contamination but does not establish external ground truth. Conclusions must say agreement/quality on synthetic recorded cases, not SPL effectiveness, human approval accuracy or real-world delivery success.

Sources inspected: `shipment_kg/generate_shipment_kg.py`, `chat/llm/pipeline/{extract,classifier,recommender,rules,reviewer}.py`, Batch2 final proof and recorded-evidence-integrity reports. Baseline calibration includes invented attempt counts, equality described as exceeding a limit, and imprecise SLA timing; later guards reduce specific defects but do not replace manual evaluation.
