# Blinded operator-output quality review

60 outputs / 30 paired synthetic cases; model-blind AI editorial review, not independent human/SPL gold

Scores were finalized before revealing the per-case model aliases. Five dimensions use 0–2; total is 0–10.

| Model | Mean total | Ready to show | Cases with critical flags | Paired preference wins |
|---|---:|---:|---:|---:|
| openai/gpt-oss:20b | 6.233 | 2/30 | 11/30 | 5/30 |
| openai/gpt-oss:120b | 7 | 5/30 | 8/30 | 19/30 |

Tied preferences: 6/30.

| Dimension | 20B mean / below-two cases | 120B mean / below-two cases |
|---|---:|---:|
| factual_fidelity | 0.967 / 22 | 1.333 / 16 |
| evidence_concision | 1.2 / 21 | 1.467 / 15 |
| action_review_consistency | 1.033 / 19 | 1.2 / 17 |
| language_clarity | 2 / 0 | 1.867 / 4 |
| uncertainty_lifecycle | 1.033 / 25 | 1.133 / 23 |

- Two agent reviewers split the cases; each reviewed both aliases on the same case.
- No output language required; English prompts and Arabic actions are not a prose target.
- Ready-to-show is an editorial threshold, not a safety or correctness guarantee.
- Critical flags can concern blocked or earlier proposals, not executed actions.
