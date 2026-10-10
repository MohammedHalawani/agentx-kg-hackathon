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

---

## Amendment 1 (2026-10-10, before any evaluation world or evaluation case exists)

Reason: an independent review of the design above (coordinator, 2026-10-10) found that it under-specified truth timing,
leakage controls, the no-tools baseline, the statistics, abstention and the budget. No evaluation world, case or run exists
yet, so this is still pre-registration. Where this amendment conflicts with the sections above, the amendment wins; the
original text is kept unedited for the record.

### A. Truth timing (replaces "knowable_at is the first evidence" in section 1)
- t is the investigation's start in simulated time. Tools return only records with recorded_at <= t.
- A mechanism is knowable at t when the run's own ingestion log contains, at or before t, a record that separates it from
  the other mechanisms sharing the case's opening symptoms, or when an expected observation that would separate them is
  overdue at t by the monitor's threshold. The separating evidence for each mechanism is the world's committed
  discrimination spec (see F). The scorer computes knowability from the run's ingestion log, never from generator intent.
- Precedents are cut at each case's t: a precedent counts only if its outcome was verified before t, and no mechanism
  instance may span the history/development cut-off (the generator ends it or excludes that history case from precedents).

### B. Leakage controls (new)
- Truth labels live outside the runtime filesystem (default `C:\Projects\suhail-eval-truth\<dataset_id>\`) and are read
  only by a separate post-run scoring process. The operational simulator reads only private physical state, which carries no
  cause codes, mechanism names or labels.
- A canary token is stored in every truth row. After every run the graph, tool outputs, API responses, execution receipts
  and logs are scanned for the canary and for every mechanism name and id; any hit invalidates the run.
- No simulated human finding is derived from truth labels. Simulated field responses come only from private physical state.
- Pre-run tell test: a lookup classifier on opening case data, trained on development-world data only, must not beat
  B_rulecode on the ambiguous stratum of an evaluation world. If it does, the generator is fixed and new evaluation worlds
  are generated; the scorer is never changed to compensate.

### C. Baselines (adds to section 2)
- **B_notools:** the agent's model, temperature, prompts, cause catalogue and output format, given the same opening case data
  (symptoms and the case summary the investigator receives) and no tools; INSUFFICIENT_EVIDENCE allowed; same cases.
- B_rulecode's primary is the first code in this fixed order among the monitor's rule codes at opening: CONFLICTING_CUSTODY,
  MANIFEST_CONFLICT, DELIVERY_DISPUTE, PROOF_INSUFFICIENT, BARCODE_MISMATCH, WEIGHT_MISMATCH, ADDRESS_CONFLICT, WRONG_GATE,
  RECIPIENT_UNAVAILABLE, UNRECONCILED_CUSTODY, TRAFFIC_DELAY, JOURNEY_DELAY, CUSTODY_GAP, MISSED_MILESTONE; no code gives
  INSUFFICIENT_EVIDENCE. Its cause set is all its codes. (Stage 0 used the alphabetically first code other than
  MISSED_MILESTONE; the stratum test in F reproduces that S5 split with the Stage 0 rule.)
- B_symptom's table is committed with the stratum script before any evaluation case exists. Its cause set is its primary.
- B_notools and the agent: the cause set is the primary plus at most three supported hypotheses.

### D. Statistics (replaces section 6 where they differ)
- One result per case; repetitions never count as extra cases. The main test is one agent run per case.
- Stability: a seeded subset of 40 cases run three times, reported as run-to-run agreement only.
- Degraded or invalid model output counts as wrong.
- Pass bars, each on the identifiable ambiguous stratum only, each an exact two-sided McNemar test at alpha 0.05 that also
  requires more agent wins than losses: (1) agent vs B_rulecode; (2) agent vs B_notools. Only (2) supports the claim that
  retrieval helps.
- Determined stratum: the lower bound of the 95% interval of the paired difference (agent minus B_rulecode) must be above
  minus 5 points.
- Power: detecting a 15-point gain at 80% power needs about 120 to 155 identifiable ambiguous cases (discordance 35% to 45%).
  The target is at least 150 in the primary evaluation world. A 600-shipment development world is expected to give about 60,
  so evaluation worlds are dedicated fresh-seed worlds sized from the development world's measured yield.
- Headlines are reported per stratum against each baseline, never pooled across strata.
- The over-sampling weights are fixed in the world package's committed config before any evaluation world is generated.
- 26 of 41 appears only as history. 31 of 41 never appears in a comparison.

### E. Abstention (adds to sections 1 and 3)
- Cases not identifiable at t form their own stratum, outside the main test. There, INSUFFICIENT_EVIDENCE plus escalation
  with no automatic action is correct.
- INSUFFICIENT_EVIDENCE on an identifiable case is wrong.
- Reported: coverage, abstention rate, accuracy when answering, INSUFFICIENT_EVIDENCE precision and recall.

### F. Committed before any evaluation case exists
- The acceptable-codes table per mechanism and the evidence-to-cause discrimination map (both in the world package).
- The stratum script: a case's stratum comes from truth knowable at opening, using the evaluation world's census when a
  symptom set has at least 5 shipments, else the generator's mechanism-to-symptom map.
- A test that reproduces a named S5 split (Stage 0: 19 determined, 22 ambiguous) with that script's rules.
- After an evaluation world is generated and before any agent run, the per-case stratum list is written and its hash is
  committed.

### G. Held-out (replaces section 5's seeds and held-out variation)
- Seeds 7101 to 7103 are withdrawn because they are public. Evaluation seeds are int(sha256("<commit>:<k>")[:8], 16) for
  k = 1, 2, where <commit> is the hash of the commit that freezes the investigator, tools and reviewer for the evaluation.
- World E1 (k = 1): primary evaluation world, development providers, sized for at least 150 identifiable ambiguous cases.
- World E2 (k = 2): held-out world with at least one provider never seen in development and mechanism pairings never
  paired in development, sized for at least 60 identifiable ambiguous cases, reported separately and descriptively.
- World-1's own held-out days are used for detection and safety checks, not for the main accuracy test.
- Expected sizes are stated in the evaluation config committed before E1 and E2 are generated.

### H. Freeze and rerun rules
- Every edit after b1d331f is a dated amendment with reasons. Configuration and baseline tables are sealed with the stratum
  script (F).
- The first complete run on E1 and E2 counts. A run may be declared invalid only for: provider failures on more than 5% of
  calls (from the run's provenance), an infrastructure crash before completion, a code, data or prompt hash differing from
  the sealed configuration, or a canary or truth-vocabulary hit (B). Every attempt, valid or not, is disclosed with its
  partial results. A rerun uses the same seeds and configuration.

### I. Investigating, not explaining
- Evidence-grounded accuracy: a correct answer that also cites at least one valid, retrieved, discriminating record (per
  the committed discrimination map) other than the opening alert's own evidence. Reported next to plain accuracy.
- Also reported: agreement with B_rulecode, and accuracy on the cases where the agent's answer departs from B_rulecode.

### J. Pairs and ablation (replaces section 4's ablation)
- Matched pairs are drawn by a seeded procedure and do not overlap. Same-cause pairs are scored on consistency.
- Ablation: every identifiable ambiguous case is rerun with the cross-shipment tools disabled, compared by a paired exact
  McNemar test. A drop is predicted only for mechanisms whose discriminating evidence is cross-shipment (device outage,
  facility backlog, late linehaul trip, container-level missort, traffic); no drop is predicted for the others.

### K. Outcome metrics and their denominators
Wrong automatic actions per automatic execution; false automatic resolutions per automatic closure; premature closures
(re-detected within 24 simulated hours) per closure; safe automatic resolutions per eligible case; human interventions per
case; verifier verdicts against truth per execution. Release bar, set by Fahad: zero unjustified or premature resolutions,
otherwise an explicit failed gate. Reviewer failures are injected in a separate run on a seeded 30-case subset by making
every reviewer call fail at the provider. Latency is reported as p50, p90 and p99 investigation wall time and p50 and p95
per tool query.

### L. Budget
- At most 12 model calls per investigation (investigator turns, conclusion and reviewer rounds together), enforced in code.
- Planned total for E1 and E2 together, including B_notools, the ablation and the stability subset: about 9,500 model calls
  and about 45 million tokens at S5's rate (about 4,600 tokens per call). Hard cap: 12,000 calls.
- No result-dependent stopping. If this exceeds what Fahad's Ollama Cloud plan allows, that is reported as a blocker for
  his decision, and the evaluation is not silently shrunk.

---

## Amendment 2 (2026-10-10, before any evaluation world or evaluation case exists)

Reason: Fahad set a hard cap of 4,000 model calls for the blind evaluation (his answer to the budget question, relayed by
the coordinator on 2026-10-10). Amendment 1 planned about 9,500. This amendment re-plans the evaluation inside the cap. It
replaces amendment 1's sections D (repetitions, sizes, determined-stratum bar), J (ablation) and L (budget) where they
differ. Everything else in amendment 1 stands.

### What the 4,000 calls cover
Every model call made for the blind evaluation on worlds E1 and E2: the agent's investigator and reviewer calls, B_notools,
and any optional extra below, including retries. The cap is enforced in code: a call that would exceed it is refused. It does
not cover development runs, the case-family A to H demonstrations or the reviewer-failure safety run, which happen on the
development world at roughly S5 scale and are reported separately. Every gate report states cumulative model calls and tokens
across all runs.

### Arms
- Agent: one run per case (investigator plus reviewer), capped at C_cap calls per investigation.
- B_notools: one run per case on the same cases, at most 2 calls (one retry on invalid output).
- B_rulecode and B_symptom: scored on the same cases at no model cost.
- One result per case. Cap hits, degraded and invalid runs count as wrong.

### Dropped
- The three repetitions (amendment 1, D) and the stability subset as a required item.
- The full ablation on every identifiable ambiguous case (amendment 1, J). The agent vs B_notools comparison is the
  evidence that retrieval helps.

### Sizing rule (fixed now; the numbers are set once C_cap is fixed)
- C_cap is set from development runs on the development world, as the 95th percentile of model calls used by correct
  development investigations (raised in a dated amendment if it truncates more than 5% of development investigations),
  before the investigator is frozen. Planning value: 12.
- The main test is sized by worst-case cost so it always completes inside the cap:
  N_main = floor(4000 / (C_cap + 2)). With C_cap = 12, N_main = 285.
- Allocation of N_main (C_cap = 12), cases drawn by a seeded procedure from each stratum:

| World and stratum | Cases | Role |
|---|---|---|
| E1, identifiable ambiguous | 160 | Main test (headline) |
| E2, identifiable ambiguous (unseen providers and pairings) | 60 | Held-out, reported separately |
| E1 and E2, determined | 40 (30 + 10) | Descriptive |
| E1 and E2, unidentifiable at t | 25 (20 + 5) | Abstention and escalation, descriptive |
| Total | 285 | |

- If C_cap ends above 12, N_main shrinks and cases are removed in this order: unidentifiable down to 15, determined down to
  30, then E2 down to 40, then E1. E1 keeps at least 150 cases if N_main allows it.

### Power (stated now, and stated plainly in the final report)
- E1 main test, 160 identifiable ambiguous cases: the minimum detectable gain at 80% power (exact McNemar, two-sided, alpha
  0.05) is about 13 to 14 points for discordance between 35% and 45%. Smaller real gains may go undetected.
- E2, 60 cases: about 22 points; reported descriptively with Wilson intervals, no pass bar.
- Determined stratum, 40 cases: too small for the minus-5-point non-inferiority bound to be informative (the paired
  interval is wider than 5 points), so that bar becomes a descriptive report with Wilson intervals.
- Pass bars that remain: on E1 identifiable ambiguous cases, agent vs B_rulecode and agent vs B_notools, each an exact
  two-sided McNemar test at alpha 0.05 with more agent wins than losses.

### Expected spend and optional extras
- Expected main-test spend at S5's measured cost (about 10 calls per case for agent plus reviewer, about 1.1 for
  B_notools): about 3,200 calls. Worst case: 4,000.
- Only if calls remain after the main test is complete, the harness runs, automatically and in this fixed order, without
  anyone looking at results: (1) a targeted ablation on E1 identifiable ambiguous cases whose mechanism's discriminating
  evidence is cross-shipment, seeded order, each case sized by worst-case cost; (2) a stability subset of up to 20 seeded E1
  cases run once more. Whatever completes inside the cap is reported; nothing else is run.
