# Stage 3 blind evaluation: report

All data is synthetic. Nothing here describes real SPL operations.

Freeze commit `284220f`, run driver at `82f19ac`, sealed configuration `a20e92e27460732c`, 244 pre-registered cases
(E1 169, E2 75), per-case limit 20 model calls. Scored exactly as pre-registered; no threshold, stratum or case was
changed after the run. Per-case scores and the harness's own full report (which carries truth-derived detail) are kept
outside the repository; this file holds aggregates only.

## 1. What can and cannot be read from this run

**The run as a whole is invalid under amendment 1, rule H.** Provider failures were 13.6% of calls against a 5% limit.
Every one of them came from the model provider's monthly usage limit, reached during E2 at case index 192.

| Part | State | How to read it |
|---|---|---|
| E1 (169 cases) | Complete, zero provider failures | The main result. Everything in sections 2 to 5 is E1 only. |
| E2 (75 cases, held-out) | 23 ran, 52 failed at the provider | Not scored as a world. No E2 claim is made. |
| Extras (32 ablation, 40 stability) | All 72 failed at the provider | No usable data. The harness report's ablation figure (18 agent-only) is an artefact of comparing real answers with provider failures and must not be quoted. |
| No-tools baseline | Defective arm (section 6) | Not reportable as a bar. |

## 2. Main test (E1, identifiable but ambiguous, 119 cases): FAIL

The one pre-registered pass bar was that the agent beats the rule-code baseline (a lookup from the alert's rule code to
a cause, no model).

| Arm | Correct | Wilson 95% |
|---|---|---|
| Agent with tools | 81/119 (68.1%) | 59.2 to 75.8 |
| Rule-code baseline | 92/119 (77.3%) | 69.0 to 83.9 |
| Symptom baseline | 85/119 (71.4%) | 62.7 to 78.8 |

Paired: the agent alone was right on 9 cases, the baseline alone on 20; exact McNemar p = 0.061. The bar required more
agent wins than losses, so it fails on direction, not only on significance. **The agent did not beat a lookup table.**

Where the agent differs from the lookup, it is right 25 times in 66 (37.9%). It agrees with the lookup on 60.9% of E1.

## 3. Observation level and mechanism level

| E1 identifiable-ambiguous | Correct | Observation level | Mechanism level |
|---|---|---|---|
| Agent with tools | 81 | 53 | 28 |
| Rule-code baseline | 92 | 85 | 7 |
| Symptom baseline | 85 | 85 | 0 |

Observation level means the cause is what the opening alert already names. Mechanism level means a correct specific
cause that no opening symptom names. The agent found four times as many mechanism-level causes as the lookup (28
against 7), and lost 32 observation-level cases the lookup gets for free. When an opening symptom names an acceptable
cause the agent is right 93/115 (80.9%); when none does, 12/34 (35.3%).

The pattern in the wrong answers: the agent moves away from the alert's cause toward custody explanations
(custody gap, unreconciled custody, insufficient proof) on evidence that does not support the move.

## 4. Other strata (E1, descriptive)

- **Determined (30):** agent 24/30, both baselines 30/30. This is a flagged regression. Five of the six misses are
  invalid model replies (the investigation ended without a usable conclusion), one is a wrong cause.
- **Unidentifiable (20):** the right answer is "insufficient evidence". The agent gave a specific cause in all 20,
  twelve of them with high confidence. Abstention rate over all of E1 is 0%. **The agent never says it does not know.**

## 5. Safety, evidence and behaviour (E1 agent, 169 cases)

- No case was closed or resolved by the run; every case ended with a person (human review 81, escalated 69, awaiting
  approval 19). The release bar of zero unjustified automatic resolutions holds trivially here, because Stage 3 does
  not execute outcomes. Stage 4 has to show it.
- 41 automatic actions were authorised, 11 of them on a wrong diagnosis, 2 on cases where the cause was unknowable.
  All 41 are evidence-gathering types (custody reconciliation, rescan, reweigh, hub check, device sync, evidence
  request). None is a reroute, return or closure.
- Unsafe or fabricated answers: 0. Citations: 163 of 169 conclusions cite evidence and every cited id resolves.
  Answers both correct and fully supported by their citations: 27/169 (16.0%). Most correct answers do not cite the
  discriminating record.
- Reviewer: accepted 63 correct and 31 wrong; asked for revision on 42 correct and 27 wrong. It does not separate right
  from wrong.
- Matched pairs: same symptoms, different true cause, both right and different in 8 of 27. Same cause, different
  symptoms, both right in 19 of 31.
- Cost: 1,632 model calls, 15.5 million tokens, median 9 calls per case (p90 13, max 19, no cap hits), median 40.9 s
  per investigation (p90 66.9 s, p99 116.7 s). Tool queries: median under 1 ms, p95 0.24 s.
- Leakage: the capture of everything the runtime served (966 MB) holds no canary and no mechanism id. The full
  scan, including mechanism names, finished clean for both worlds on all seven captured surfaces, with its
  positive control passed.

## 6. The no-tools baseline is defective and is not reported

The arm scored 13/119 on the main cell, but 140 of its 169 E1 answers were rejected replies, and that cannot be
attributed to the model. Three harness defects, in plain words: the arm reused the agent's system prompt, which tells
the model to call tools it was not given; the one retry did not show the model its rejected reply; and the reply text
was not recorded, so the rejections cannot be examined afterwards. The harness's "agent beats no-tools: PASS" is
therefore not a result. A corrected arm is prepared with tests and costs at most 3 calls per case (at most 507 calls
for E1) under a recorded amendment.

## 7. What this means for the product

1. On this world the investigator adds mechanism-level findings but is less accurate overall than the alert's own rule
   code. It should not be presented as more accurate than rules.
2. It does not abstain. Any demo case shown as "appropriately uncertain" must be one where the system really does
   route to a person on evidence, not one where the model is assumed to recognise its own uncertainty.
3. The reviewer adds calls without adding discrimination.
4. Authority and citation controls held: nothing unsafe, nothing fabricated, no automatic action beyond
   evidence-gathering.

Next steps that follow from the data, none started: anchor the investigator on the alert's cause and require a cited
discriminating record before it departs from it; add an explicit insufficient-evidence path with a test on
unidentifiable cases; re-run E1's 119 under an amendment to measure the change.

## 8. Open items

- E2: 52 cases and the 72 extras need a re-run under an amendment once the provider is available (tool prepared:
  `stage3_eval rerun-failed`, union scoring labelled post hoc). Decision pending.
- Campaign calls to date: 173 (pilot and its re-run) + 2,595 (this run) = 2,768; 17.8 million agent tokens in this run.
- Full leak-scan verdict: clean (see section 5).
