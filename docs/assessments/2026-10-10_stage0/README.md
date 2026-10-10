# Stage 0 assessment: why S5 root-cause accuracy was 63%

Date: 2026-10-10. Branch `fhd` at 144d15e. Subject: the final S5 run at f36736b (`docs/evals/2026-10-09_s5/final/`), with the
three earlier runs (run2, run3, run4_154dd3e) used for stability. No model calls were made and nothing was rerun or tuned on
these cases. All data is synthetic (DEMO-SUHAIL-LIVE-TEST) and says nothing about real SPL operations.

S5 stays recorded as an independent-review FAIL. This assessment explains the 63%; it does not change that verdict.

## 1. Short answer

The 63% (26 of 41, Wilson 95% interval 48% to 76%) is not a reliable measure of how well Suhail investigates.

- **About a third of the error comes from how S5 was scored, not from the investigator.** Five of the 15 wrong cases were
  scored against labels the investigator could not have known at the time, or against answer keys that contradict each other.
  As a sensitivity analysis only, scoring each case against what was knowable at its own investigation time gives 31 of 41,
  and 131 of 168 over all four runs. That is not a new baseline: the measured S5 result stays 26 of 41 (63%).
- **About half of what was right came from the alert's name.** Accuracy was 17 of 22 when an opening symptom named an
  acceptable cause, and 9 of 19 when none did. A plain symptom-name baseline scores 22 of 41.
- **The investigator does not yet beat the deterministic rule engine.** Reporting the monitor's own rule code at opening
  scores 28 of 41 (116 of 168 pooled) against the agent's 26 (111 pooled). The agent wins only on DELAYED_SYNC, the one class
  where reading device telemetry matters.
- **The genuine investigator weakness is narrow and repeatable.** It answers CUSTODY_GAP when a parcel is not where expected
  (34 predictions, 10 right), and it missed DELAYED_SYNC in 4 cases where the depot handheld was visibly silent and it had
  called device_status (which device it queried was not recorded). It never once answered UNRECONCILED_CUSTODY, which was the only acceptable cause in 16 case-runs.
- **The reviewer does not separate right from wrong.** It accepted 47 of 53 wrong diagnoses and rejected 22.5% of correct
  ones against 11.3% of wrong ones. In the final run, 8 of the 9 cases escalated as "reviewer rejected" were correct.
- **The dataset is too easy where it is scored and too thin where it matters.** 20 of 24 abnormal recipes have a one-to-one
  tell (a constant gate, a fixed barcode suffix, a fixed weight ratio). Healthy shipments never vary, so detection precision
  of 1.00 is guaranteed by construction. The only shared-world mechanism is one kind of device outage.

The baseline every later evaluation must beat, on the same cases, is the rule-code baseline (28 of 41 here), alongside
the measured agent result of 26 of 41. A rescored figure is never used as the baseline.

So the honest reading is: on this dataset, the investigator mostly repeats what the alert already says, does slightly worse
than the rule engine, and adds real value only when it reads telemetry. The dataset rarely requires investigation, and the
scoring penalises some correct answers. Stages 1 to 3 have to fix all three together; fixing any one alone would not tell us
whether Suhail investigates.

## 2. Where the 15 wrong final cases came from

Each case is assigned to the one cause without which it would have been right. Evidence is from an offline replay of the
investigator's own read-only tools at each case's opening time (`scripts/evidence_audit.py`, `scripts/replay.py`), which
reproduces the monitor's opening time and symptom set for 39 of 39 shipments.

| Layer | Cases | n | What happened |
|---|---|---|---|
| Evaluation: label not knowable yet | 000187, 000239 | 2 | contractor_unreturned. At the investigation, the evidence was failed attempts with no answer, and the rule engine itself said RECIPIENT_UNAVAILABLE. The non-return only becomes visible a median 9.25 h later. The case was never re-investigated. |
| Evaluation: inconsistent answer key | 000101, 000482, 000067 | 3 | absent_session_receipt rejects CUSTODY_GAP although its evidence-identical sibling (partial_packages) accepts it and both map to the same action. report_different_location rejects PROOF_INSUFFICIENT although the rule engine flags it at opening and three sibling recipes accept it. |
| Tools: evidence not retrievable | 000387 | 1 | traffic_safe_return. The TrafficObservation (9 h delay, confidence 0.95) is in the graph and the monitor used it, but no investigator tool returns it. Wrong in all 4 runs. |
| Investigator: wrong reading of visible evidence | 000431, 000017, 000392, 000030 | 4 | Outage cases. The depot handheld had been silent for 3.5 to 18 h, the investigator called device_status (the queried device was not recorded), and still answered CUSTODY_GAP. |
| Investigator: wrong reading of visible evidence | 000400, 000029 | 2 | 000400 answered CUSTODY_GAP with every transfer corroborated (no custody gap exists). 000029 answered DELAYED_SYNC with the handheld reporting normally; the deciding row was cut off by tool truncation, and the automatic DELAYED_SYNC check passed because hourly ingestion makes ordinary records look 60+ min late. This produced the one automatic action on a wrong cause. |
| Reviewer loop | 000567 | 1 | A REVISE round turned BARCODE_MISMATCH (right in 3 of 3 other runs) into INSUFFICIENT_EVIDENCE. Round 2 starts with a fresh conversation and only a 500-character feedback note. |
| Model output reliability | 000262, 000337 | 2 | Two invalid replies in one tool turn end the whole investigation (fail-closed, correctly). There were no provider failures. Both shipments were right in the other three runs. |

Totals: evaluation 5, tools 1, investigator 6, reviewer 1, output reliability 2.

## 3. The questions the mission asked

### Dataset

- Anomalies are 24 independent per-shipment recipes (`chat/dataset_v2/network.py:42-54`), each with 1 to 3 shipments in the
  scored split. One case moves a recipe's accuracy by 33 to 100 points, so no per-recipe conclusion is possible from S5.
- The only cross-shipment mechanism is the depot-handheld outage (`propagate_outages`, network.py:288-312): 7 outages touching
  39 other shipments, 6 of them scored. There are no shared vehicles, drivers, sessions, containers or facility backlogs:
  0 of 1,204 vehicle assignments overlap, vehicles and drivers are 287 to 287, and each linehaul assignment moves one shipment.
- One-to-one tells: status IN_TRANSIT only in two recipes (17/17), 'Gate 1' only in different_gate (8/8), barcode always the
  manifest barcode plus '8' (16/16), weight always 0.65 times declared (23/24), a revised manifest only in conflicting_manifest
  (10/10), every recipient report with the same text, and a newer address version visible before the shipment exists.
- No benign variation: 4,512 of 4,512 healthy milestones happen exactly on plan. Detection precision and recall of 1.00 were
  guaranteed by construction, so S5's detection numbers measure nothing.
- Physical contradictions: the "miscalibrated" scale read 109 other parcels correctly within two hours; the second vehicle in
  conflicting custody reports is a Riyadh linehaul van in 7 of 9 cases whose depot is in another city.
- The dataset does not cap accuracy. A lookup over the evidence visible at opening would label 197 of 204 opened shipments
  correctly (96.6%). Only one pair is truly indistinguishable at opening (contractor_unreturned vs unanswered_contact).

### Tools and retrieval

- Strictly single-shipment (`chat/operations/read_model.py:122-141`). No tool can ask "what else happened on this device,
  driver, vehicle, session or facility". In all four outage cases the investigator could not see that other parcels on the
  same handheld were also held back (1 to 8 per case, `data/evidence_audit.json`).
- Device telemetry exists for 54 of the 303 devices the tools name (18%); for the rest device_status says NO_TELEMETRY, which
  cannot be told apart from a silent device.
- TrafficObservation, RouteSegment, Route and status history are unreachable. Session end time is only in
  vehicle_and_manifest, which was called in 1 of the 28 case-runs where UNRECONCILED_CUSTODY was the answer.
- Values the tools compare against (manifest barcode and weight, tolerance, proof corroboration) are shown but not citable,
  so the reviewer never sees them.
- Truncation (30 rows, 6,000 characters) hid a missing milestone in 2 wrong cases, while citable ids were still listed for the
  rows that were cut.
- The tool budget never bound (mean 5.1 calls, 10 reached in 2 of 168 case-runs).

### Investigator and prompt

- No deterministic code sets or overrides the diagnosis (`chat/operations/graph.py:60-82, 185-194`). The safety layers only
  remove automatic authority. This is what the mission requires, and it holds.
- The 21 cause codes are given as a bare list with no definitions (`chat/operations/investigator.py:127`). Observation codes
  (MISSED_MILESTONE, CUSTODY_GAP, PROOF_INSUFFICIENT) and mechanism causes (DELAYED_SYNC, HUB_DELAY, a parcel left at the
  depot) are mixed in one list, and the scoring enforces distinctions the prompt never states.
- Prediction precision over 168 case-runs: CUSTODY_GAP 10/34, MISSED_MILESTONE 1/10, DELAYED_SYNC 12/19; measurement and
  report causes are near perfect (WEIGHT 20/20, BARCODE 15/15, MANIFEST 10/10, DISPUTE 10/10). Seven codes were never predicted.
- Procedural instructions are ignored ("check precedents first" was followed in 4 of 168).
- Run-to-run variance at temperature 0 with identical prompts and data: 28, 27, 30 and 26 correct; only 21 of 39 shipments got
  the same answer in all four runs. A single run cannot resolve differences smaller than about 4 shipments (10 points).

### Reviewer

- It sees only the raw cited records, not the comparisons a tool computed, so it rejects measurement and proof diagnoses it
  cannot check (first-round REVISE: WEIGHT 18/20, PROOF 9/9) and rarely rejects DELAYED_SYNC (1/19), whose device citation is
  rendered as a computed summary.
- Discrimination is inverted (22.5% of correct rejected vs 11.3% of wrong) and it accepted 47 of 53 wrong diagnoses.
- The deterministic fact check flagged 0 of 164 diagnoses, 53 of them wrong, because it treats six causes as consistent with
  any overdue milestone (`chat/operations/checks.py:14-23`).
- A revision round re-runs the whole investigation without the first round's evidence and gave no accuracy gain (two-round
  ACCEPTs 61% correct vs 66% for one-round).

### Simulator

- The scenario runner ingests hourly and stamps records with the tick time, so 61.5% of ordinary records look 60 to 69 min
  late. That crosses the 60-minute late-upload threshold, which is why the DELAYED_SYNC check passed on 000029.
- Open items from the round-2 review (not fixed in S5, carried to Stage 4): a sync to the wrong device can still be credited
  at natural reconnect, the holder is always "found", and buffering is decided per shipment rather than per device.

### Evaluation

- One investigation at the first symptom, scored against a label defined by the whole story; 20 of 41 cases gained symptoms
  later and were never re-investigated.
- Case-level scoring counts two easy shipments twice (premature closures 000415, 000466); degraded runs are scored as wrong
  answers instead of a separate reliability rate; the key-evidence metric cannot be met for DELAYED_SYNC by design.

## 4. Ambiguous and single-cause cases

An opening symptom set is "determined" if, across all 204 abnormal shipments of the 600-shipment world, one label is
acceptable for every shipment that opens with that set.

| Group | Cases | Agent | Symptom-name baseline | Rule-code baseline |
|---|---|---|---|---|
| Determined by the opening symptoms | 19 | 15 (79%) | 18 | 19 |
| Ambiguous | 22 | 11 (50%) | 4 | 9 |
| All | 41 | 26 (63%) | 22 | 28 |

MILESTONE_OVERDUE alone opened 13 of 41 cases (agent 5 of 13) and, in the full world, maps to 9 different root causes; the
best single label covers only 35 of 70. This family is where investigation is actually needed, and it is where the agent is
weakest. A stricter definition (one distinct cause among the scored cases) gives 9 determined and 32 ambiguous; the
conclusion is the same. S5's own report used a third split (one rule code vs several: 21/33 and 5/8).

## 5. What each later stage must change, and why

These are requirements derived from the findings above, not tuning to these cases. None of them is a diagnosis rule.

**Stage 1, the world**
1. Faults are world-level mechanisms (a device outage, a hub backlog, a scale drift window, a missort, a late truck, a driver
   who skips return scans) that act on every parcel they physically touch. Labels come from what the mechanism did.
2. The same alert must arise from different mechanisms, with the discriminating evidence present but only reachable by
   investigation, often across shipments.
3. No tells: magnitudes and forms drawn from distributions, full status histories, plans stamped at booking, varied text.
4. Benign variation (processing jitter, late-within-tolerance uploads, second attempts within promise) so detection precision
   is a real measurement.
5. Telemetry for every device class, with "no telemetry stream" distinguishable from "silent".
6. Truth records each cause with the time its evidence first reached Suhail (`knowable_at`), kept outside the graph.
7. At least 10 cases per mechanism in the scored split.

**Stage 2, tools and prompt**
8. Bounded, read-only, time-correct cross-shipment tools (same device, driver, session, trip, facility), route conditions and
   customer communications, returning UNKNOWN when there is no evidence.
9. Tools cite the records they compared against; no citable ids for truncated rows; telemetry next to each missing milestone;
   session end and reconciliation in the custody view.
10. Cause catalogue with one-line operational definitions, observation separated from mechanism, and the action catalogue's
    "addresses" lists removed from the investigator's input.
11. Reviewer sees the computed comparisons and the retrieved-but-uncited ids; revision keeps round-1 context; both rounds logged.
12. A validation error on a tool turn does not end the investigation.
13. Fact checks tightened (DELAYED_SYNC needs the expected device silent; CUSTODY_GAP needs an uncorroborated transfer). These
    only remove automatic authority; they never choose the diagnosis.
14. Re-investigate when a standing or human-floor symptom is added.

**Stage 3, evaluation**
15. Score per shipment, against the label knowable at the investigation and the eventual label, as two numbers.
16. Always report the symptom-name and rule-code baselines, determined vs ambiguous accuracy, Wilson intervals, at least three
    repetitions, and degraded runs as a reliability rate.
17. Blind protocol: a fresh seed and held-out sessions never used in development, plus matched pairs with identical alerts and
    different causes, to show that diagnoses follow retrieved evidence.

**Stage 4, execution and verification**
18. Ingestion lag measured from the provider's delivery time, not the tick; device sync credited only for the right device;
    a holder found only where the parcel physically is; buffering per device.

## 6. Files

- `audits.md`: the three independent audits in full (dataset, tools and prompt, evaluation), with file and line references.
- `scripts/`: the offline replay and analysis scripts; `data/`: their outputs. They regenerate the S5 world in memory
  (`generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))`, truth hash 0775597…) and read the committed
  results; they make no model calls and touch no database. They were written as scratch tools and use absolute paths.
