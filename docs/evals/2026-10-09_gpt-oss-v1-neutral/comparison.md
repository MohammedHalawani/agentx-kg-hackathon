# GPT-OSS v1 paired synthetic-history benchmark

controlled frozen classifier/recommender/reviewer/AFL benchmark; 30 identical case-language inputs across models (18AR/12EN, not same-case bilingual translations); synthetic seeded labels/actions and random outcomes, not independent human SPL gold; extraction measured but not used to alter frozen retrieval; casefile/writeback disabled

Rates use all 30 planned cases per model, including exceptions/no-grounding. Partial runs remain partial; missing attempts are visible.

| Model | Completed | Pipeline base agreement | Valid model base agreement | Family agreement | Action exact | Action history proxy | Review accept | AFL retry | Escalate | Mean seconds | p95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-oss:20b | 30/30 | 6/30 (20.0%) | 6/30 (20.0%) | 6/30 (20.0%) | 0/30 (0.0%) | 6/30 (20.0%) | 24/30 (80.0%) | 6/30 (20.0%) | 6/30 (20.0%) | 23.669 | 50.848 |
| openai/gpt-oss:120b | 30/30 | 14/30 (46.7%) | 14/30 (46.7%) | 14/30 (46.7%) | 5/30 (16.7%) | 14/30 (46.7%) | 27/30 (90.0%) | 6/30 (20.0%) | 3/30 (10.0%) | 7.483 | 12.682 |

False acceptance/rejection: unavailable without independent human gold. Accepted seeded-cause disagreements are descriptive proxies only.

Pipeline agreement includes application defaults after invalid output; valid-model agreement excludes a final classifier call with malformed, missing, invalid or errored declared output.

Raw escalation-prefix agreement is separate from supported-base cause agreement. Canonical Arabic action text is separate from Arabic explanation quality. Manual rubric scoring is pending.

Wilson 95% intervals use completed case agreement counts, including exceptions as disagreements. Balanced synthetic sampling is not random production sampling; intervals are descriptive uncertainty, not evidence of significance.

| Base category | 20B agreement | 120B agreement |
|---|---:|---:|
| address_conflict | 0/5 (0%) | 3/5 (60%) |
| recipient_unavailable | 5/5 (100%) | 5/5 (100%) |
| failed_attempt_wrong_gate | 0/5 (0%) | 1/5 (20%) |
| failed_attempt_barcode_mismatch | 0/5 (0%) | 0/5 (0%) |
| failed_attempt_weight_mismatch | 0/5 (0%) | 0/5 (0%) |
| hub_delay | 1/5 (20%) | 5/5 (100%) |

- Barcode, weight and gate/contact outcome observations absent from local projection; some subtypes are underidentified.
- Only base categories are supported outputs; full escalation-prefix agreement is separately penalized unsupported vocabulary.
- History action plausibility and retrieval category matching are synthetic proxies, not independently adjudicated correctness.
- False acceptance/rejection rates cannot be measured without independent adjudication.
- Arabic complaints do not require Arabic explanations in native English production prompts; Arabic actions and Arabic prose measured separately.

Model choice: pending paired completion and quality review; no assumption that the larger model is better.
