# GPT-OSS v1 paired synthetic-history benchmark

controlled frozen classifier/recommender/reviewer/AFL benchmark; 30 identical case-language inputs across models (18AR/12EN, not same-case bilingual translations); synthetic seeded labels/actions and random outcomes, not independent human SPL gold; extraction measured but not used to alter frozen retrieval; casefile/writeback disabled

Rates use all 30 planned cases per model, including exceptions/no-grounding. Partial runs remain partial; missing attempts are visible.

| Model | Completed | Pipeline base agreement | Valid model base agreement | Family agreement | Action exact | Action history proxy | Review accept | AFL retry | Escalate | Mean seconds | p95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-oss:20b | 30/30 | 13/30 (43.3%) | 13/30 (43.3%) | 18/30 (60.0%) | 7/30 (23.3%) | 17/30 (56.7%) | 24/30 (80.0%) | 10/30 (33.3%) | 6/30 (20.0%) | 28.648 | 53.598 |
| openai/gpt-oss:120b | 30/30 | 16/30 (53.3%) | 16/30 (53.3%) | 18/30 (60.0%) | 8/30 (26.7%) | 18/30 (60.0%) | 21/30 (70.0%) | 11/30 (36.7%) | 9/30 (30.0%) | 8.537 | 14.746 |

False acceptance/rejection: unavailable without independent human gold. Accepted seeded-cause disagreements are descriptive proxies only.

Pipeline agreement includes application defaults after invalid output; valid-model agreement excludes a final classifier call with malformed, missing, invalid or errored declared output.

Raw escalation-prefix agreement is separate from supported-base cause agreement. Canonical Arabic action text is separate from Arabic explanation quality. Model-blind AI editorial rubric scoring is complete; see [quality review](quality-review/summary.md). This is not independent human/SPL gold.

Wilson 95% intervals use completed case agreement counts, including exceptions as disagreements. Balanced synthetic sampling is not random production sampling; intervals are descriptive uncertainty, not evidence of significance.

| Base category | 20B agreement | 120B agreement |
|---|---:|---:|
| address_conflict | 4/5 (80%) | 5/5 (100%) |
| recipient_unavailable | 5/5 (100%) | 5/5 (100%) |
| failed_attempt_wrong_gate | 0/5 (0%) | 0/5 (0%) |
| failed_attempt_barcode_mismatch | 0/5 (0%) | 1/5 (20%) |
| failed_attempt_weight_mismatch | 0/5 (0%) | 0/5 (0%) |
| hub_delay | 4/5 (80%) | 5/5 (100%) |

- Barcode, weight and gate/contact outcome observations absent from local projection; some subtypes are underidentified.
- Only base categories are supported outputs; full escalation-prefix agreement is separately penalized unsupported vocabulary.
- History action plausibility and retrieval category matching are synthetic proxies, not independently adjudicated correctness.
- False acceptance/rejection rates cannot be measured without independent adjudication.
- Arabic complaints do not require Arabic explanations in native English production prompts; Arabic actions and Arabic prose measured separately.

Model choice: recommend 120B for development and a curated human-reviewed demo on the measured endpoint. All 60 attempts and blinded review are complete. See [evaluation closure](closure.md) for quality, limitations and A/B/C/D failure attribution. Derived closure annotations were added after scoring; archived run inputs, result records and metric values were not changed.
