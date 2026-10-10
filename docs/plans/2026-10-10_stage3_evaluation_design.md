# Stage 3 evaluation design (frozen before any evaluation case is generated)

Date: 2026-10-10. Status: frozen at the commit that adds this file. The evaluation worlds named below do not exist yet and
will be generated only after this file is committed. Any change to this design after the first evaluation run is recorded
here as a dated amendment, and a change to prompts, tools or reviewer after the first evaluation run requires new
evaluation seeds; results on the old seeds are then reported as superseded, never mixed.

All data is synthetic. No result here describes real SPL operations.

## 1. What is measured

The question is whether Suhail's investigator reaches the cause that the evidence available at investigation time supports,
better than rules that only read the alert, and whether that diagnosis follows the retrieved evidence rather than the alert's
name.

### Truth

- **Primary truth: knowable at investigation time.** For each case, the acceptable causes are the causes of the mechanisms
  that touched the shipment whose `knowable_at` is at or before the investigation's evidence snapshot (`labels_at(row, t)` in
  `chat/world/`). If no mechanism is knowable yet, INSUFFICIENT_EVIDENCE is the correct answer and any specific cause is
  wrong.
- **Multi-cause truth sets.** A primary cause is correct if it is any knowable cause. Cause-set recall (knowable causes named
  among primary plus supported hypotheses) and precision are reported separately.
- **Secondary truth: eventual.** The full story's causes, reported as a second number, never as the headline.
- Observation codes and mechanism causes are scored as defined by the world's truth: a case whose knowable mechanism is a
  device outage is not answered by "custody gap" unless the truth row lists that observation as acceptable at that time.

### Units

- Headline: first case per shipment, scored at its first investigation.
- Also reported: every case and every re-investigation (when symptoms grow), scored at its own snapshot.
- Degraded investigations (no valid conclusion) are a separate reliability rate, and are also counted as wrong in a
  conservative variant.

## 2. Baselines, run on the same cases

- **B_rulecode:** the monitor's own rule codes at the case's opening, most specific first (the S5 baseline that beat the
  agent, 28 vs 26 of 41). This is the bar.
- **B_symptom:** a fixed mapping from the opening symptom name to a cause, decided before the run (MILESTONE_OVERDUE maps to
  MISSED_MILESTONE, and so on).
- **Historical reference only:** the measured S5 result, 26 of 41 (63%). It is a different world and is never used as a
  comparison number for a pass or fail.

## 3. Strata (computed from the evaluation world's census before the agent runs)

- **Determined vs ambiguous:** an opening symptom set is determined if one cause is acceptable for every shipment in that world
  that opens with it; otherwise ambiguous. Accuracy is always reported per stratum.
- **Matched pairs:** pairs with the same opening symptom set and different knowable causes, and pairs with the same cause and
  different opening symptoms. A pair counts as discriminated only if both diagnoses are correct and differ.
- **Per mechanism and per case family (A to H).**

## 4. Showing that diagnoses follow evidence

- Matched-pair discrimination rate (above).
- **Evidence ablation:** on a pre-chosen stratified subset of 40 cases, rerun with the cross-shipment tools disabled. If
  accuracy on ambiguous cases does not drop, the claim that the investigator uses that evidence is not supported, and the
  report says so.
- **Citation validity:** every cited id resolves, was retrieved in that investigation, was recorded at or before the
  snapshot, and is of a kind that bears on the stated cause. Checked by code; the share of conclusions with only valid
  citations is reported.
- **Symptom-name dependence:** accuracy when an opening symptom names an acceptable cause vs when none does.

## 5. Evaluation worlds and protocol

- **Fresh seeds** never used in development: three worlds generated with seeds 7101, 7102 and 7103 after this file is
  committed. Seeds used during development are recorded in `chat/world/README.md` and are never reused for evaluation.
- **Held-out sessions:** world-1's held-out days, fed live in the held-out twin database.
- **Held-out variation:** each evaluation world differs from the development world in at least one of: provider mix,
  city demand weights, mechanism combination weights. These settings are fixed in the evaluation config committed with the
  first run and are not looked at during development.
- **Size:** a stratified sample of at least 10 cases per mechanism and per case family, about 150 to 200 cases per world.
- **Repetitions:** three runs on the first world; one run on each of the other two. Mean, range and per-shipment stability
  (always right, always wrong, flaky) are reported.
- **No tuning:** nobody looks at per-case evaluation traces before the full report is written. Fixes found from the
  evaluation are made afterwards and measured on new seeds.

## 6. Statistics and reporting

- Wilson 95% intervals for every accuracy.
- Paired comparison of agent vs B_rulecode on the same cases (McNemar exact test), overall and on the ambiguous stratum.
- Pass bar for "the investigator adds value": the agent beats B_rulecode on the ambiguous stratum, with the McNemar test at
  p < 0.05 on the pooled runs, and does not do worse than B_rulecode on the determined stratum by more than the interval width.
  Failing the bar is reported as a failure, not reframed.

## 7. Everything else measured on the same runs

Detection precision and recall (healthy shipments with normal variation included), reviewer accept/reject precision and
recall against correctness and its insufficient-evidence rate, wrong automatic actions, false and premature resolutions,
safe automatic resolution rate, human intervention rate, behaviour under reviewer failure, latency and model cost per case,
Neo4j query timings, and run-to-run stability.

## 8. What the reviewer must support (design input to Stage 2)

The S5 reviewer accepted 47 of 53 wrong diagnoses. In Stage 2 the reviewer must check that citations resolve and were
retrieved, that contradicting evidence the investigator retrieved was addressed, and that at least one alternative was
tested, and it must be able to return "evidence insufficient". The evidence and citation format from Stage 1 must carry
what it needs for that: stable ids for every comparison baseline and every cross-shipment query result.
