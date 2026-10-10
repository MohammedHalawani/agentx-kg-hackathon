# S5 gate report (revised after the fix round)

**Status: S5 is open.** The gate verdict comes from the coordinator's independent review of the pushed
commit. This report gives my own assessment against the acceptance criteria and every number behind it.

All data is synthetic (dataset `DEMO-SUHAIL-LIVE-TEST`, generator `live-network-1`); nothing here is SPL
operational data. Model calls are real `openai/gpt-oss:120b` calls through Ollama Cloud (investigation
agent with its Neo4j tool loop, and the independent reviewer). Truth labels are read only by the scoring
code and by the synthetic field simulator.

Every number below recomputes from the results files in [`final/`](final):

```
python scripts/s5_report_numbers.py docs/evals/2026-10-09_s5/final
```

Each results file carries a provenance block: commit, dirty flag at start, whether the tree changed during
the run, database, dataset id, manifest/feed/truth hashes, configured model, prompt hashes and the model
calls LiteLLM completed, by the model name the provider reported.

## 1. Latest `fhd` commit

The code under test is **f36736b** (pushed; working tree clean; nothing unpushed). The results and this
report are committed on top of it; the thread names the final head commit. Every file in `final/` names
f36736b with `dirty_tree: false` and `tree_changed_during_run: false`.

Fix round, in order: 58df781 (unavailable review recorded and shown as unavailable), d8e2202 (no
answer-key wording in receipts; answer-key scan), 002f93f (authority re-checked at execution on every
path), 6e80663 (provenance), 154dd3e (scoring transparency, human path, real paused window), dfe5e4c
(simulation controls moved to a Development view), then the gaps an independent review of those fixes
found: b614de6 (case view serves the current run's review; refused and unacknowledged executions shown
as such), e620b37 (simulator answers only the device or facility a request reaches), 78ffb1b (authority
edge cases), fbeb3c0 and f36736b (evaluation details).

## 2. Investigation accuracy (real gpt-oss:120b), final run at f36736b

| Measure | Result |
|---|---|
| Root cause correct, all cases | **26 / 41 (63.4%)** |
| One-label: every opening symptom comes from one rule code | 21 / 33 (63.6%) |
| Multi-label: an opening symptom comes from several rule codes | 5 / 8 (62.5%) |
| An opening symptom's single rule code is an acceptable cause ("named") | 17 / 22 (77.3%) |
| No opening symptom names an acceptable cause | 9 / 19 (47.4%) |
| With the second-cause credit (network.py answer-key change) | 26 / 41 |
| Without it | 26 / 41 (no case in this run is credited only by it) |
| Shipments whose only acceptable cause is delayed sync | 3 / 5 |
| Diagnosis equals an opening symptom's single rule code | 15 correct, 2 wrong |
| Investigations that failed closed (degraded) | 2 (no diagnosis; sent to a person) |

Caveat on the one/multi-label split: a symptom from one rule code is not one diagnosis. Delayed sync,
hub delay, route delay, SLA risk and possible misdelivery have no rule code, so an overdue milestone has
several possible causes. The named / not-named rows measure what the symptom name gives away.

Run-to-run variance on the same data: 63% (run 3), 67% (run 2), 71% (run 4 at 154dd3e), 63% (final).

## 3. Detection precision and recall

| Set | Commit | Shipments | Cases on healthy | Abnormal missed | Precision | Recall |
|---|---|---|---|---|---|---|
| Live split (final pipeline) | f36736b | 120 (81 healthy, 39 abnormal) | 0 | 0 | 1.00 (39 / 39 shipments with a case) | 1.00 (39 / 39) |
| Held-out split | f36736b | 120 (76 healthy, 44 abnormal) | 0 | 0 | 1.00 | 1.00 (44 / 44) |

The held-out split informed one generator fix in S2b, so it is not pristine. The held-out result lists
every shipment with its detection result.

## 4. Automatic resolutions and false resolutions

- 10 automatic executions (plus 1 operator-approved); 1 on a wrong root cause (partial-packages
  shipment diagnosed as delayed sync; verification failed, unresolved).
- **6 resolved automatically:** 000113 and 000120 (offline handheld: device sync, held-back scans
  uploaded, verified), 000003 (delayed sync on an outage-affected shipment), 000100 (rescan matched),
  000415 and 000466 (address confirmed).
- **False resolutions: 0 on a wrong root cause, 0 with a standing symptom at closure.** The pipeline's
  own metric (resolution on a shipment whose expected resolution is not automatic) also gives 0 of 6.
- **2 of 6 were premature:** 000415 (wrong gate) and 000466 (obsolete address) closed when the
  recipient confirmed the address, but the redelivery never happened. The monitor, not a person, caught
  it hours later when the delivery milestone went overdue and opened a new case; the same automatic
  action ran again and was verified, and only the verifier's exception check then sent the case to a
  person.
- Per shipment: 4 of the 20 shipments whose expected resolution is automatic were resolved with no human
  and no later case.
- The independent reviewer rejected 9 proposals twice, so they were escalated; 8 of those diagnoses were
  correct, including 6 rescan or reweigh proposals (the investigator's summary claimed more than it cited,
  for example a manifest weight it had not cited). Safe, but it lowered autonomy in this run.

## 5. Human escalation

- Final states: 23 human review, 9 escalated, 3 awaiting approval, 6 resolved (41 cases).
- Wrong diagnoses (15): 10 routed to a person, 1 escalated, 3 approval pending, 1 executed and failed
  verification. None executed and verified.
- Scenario C's human path (`human.json`): the test harness, acting as the depot supervisor from the
  simulated field state, recorded three findings through the dashboard's store call: contractor
  unreturned, parcel not found (HUMAN_VERIFIED, escalated, not resolved); returned unscanned, returned
  to depot (resolved); left at depot, parcel located (resolved).
- Approvals: two attempts to approve person-only actions (delivery-dispute review, conflicting-custody
  review) were refused by `AUTH-12-human-review-action` with 0 executions before and after; one
  approval-required device sync was approved and executed with rule `AUTH-19-operator-approved`.

## 6. Independent verification

- 2 executed actions failed verification and stayed unresolved with a person (next-session delivery
  failed again; device sync on a wrong cause, no confirming evidence).
- 2 actions were verified but the exception remained; both stayed open with a person
  (`OUTCOME_VERIFIED_EXCEPTION_REMAINS`).
- Answer-key scan over 11 receipts, 13 outcomes, 1,433 audit entries, 58 reviews, 39 recommendations,
  41 case API responses and 6 command results: **0 hits** (109 terms plus single-word field states).
  Run 3 before the fix had 28 hits, all in receipts and the API responses serving them.
- Authority: every one of the 11 executions is tied to what authorized it (its own run's AUTO decision,
  or its own approve decision); **0 bypasses**.
- Citations: 133 cited ids; 130 resolve to the case's evidence, 3 to device telemetry, 0 unresolved.
  Key evidence cited 5 of 5 where it had been ingested; for 7 cases it had not been ingested yet.
- Reviewer outage (`reviewer_failure.json`): stored verdict `review_unavailable`, `AUTH-02-model-degraded`,
  human review, 0 executions; the case view says "Independent review unavailable — routed to a person".

## 7. Remaining failures and limitations

From a second independent review of the follow-up fixes (confirmed, not fixed in this round):

1. Simulator: a device sync to the wrong device, or with no target, is still acknowledged, and is
   verified when the device reconnects on its own (the verifier credits the effect, not causation).
2. Simulator: a hub check or reconciliation always reaches the last visible facility and treats it as
   the parcel's location, so the new gate rarely blocks a "found" result.
3. Simulator: for an offline-handheld shipment the parcel stays "at the depot" regardless of time, so a
   check after loading or delivery fabricates a depot scan.
4. Simulator: whether a device has buffered scans is decided by the requesting shipment's truth row,
   not by the device's outage, so shipments caught in another shipment's outage do not upload early.
5. Case view: after a refused or unacknowledged execution and a second approval at a paused clock, the
   lifecycle panel can show the older execution.
6. Case view: the current run's review is filtered from a 20-row page across runs; a case re-analysed
   13 or more times could show no review.
7. Runner: an unacknowledged execution would be counted as executed (none occurred in the final run).
8. Runner: the per-shipment "human floor" sub-metric uses opening symptoms, while the product applies
   the floor to the grown symptom set.
9. Smaller runner and record issues: the accounting ledger guard ignores `--source`; the human phase acts
   on new cases when re-run; an (unreachable) automatic pre-check refusal leaves the stored run saying AUTO.

Product limitations:

- Diagnosis accuracy is 63%, and contractor-unreturned shipments were misdiagnosed as recipient
  unavailable in every run (they still went to a person by the contractor-custody rule).
- Address confirmation closes a case before the redelivery happens (item 4 above).
- One local operator identity; read routes are unauthenticated; pausing does not stop actions already
  authorized.
- Scoring is per shipment; there is no held-out diagnosis evaluation.
- Frontend tests time out at the default 5 s under heavy load (162 of 162 pass with a 60 s timeout).

## 8. Scenarios A to F (final validation at f36736b)

| Scenario | Status | Evidence |
|---|---|---|
| A. Genuine investigation of an unknown issue | Shown | 000113: opened on an overdue milestone (whose rule code is "missed milestone"); the agent called shipment_overview, journey, custody_chain and device_status, concluded delayed sync from the silent handheld, the reviewer accepted |
| B. Automatic resolution of a delayed/offline scan, no human | Shown | 000113, 000120 (offline handheld) and 000003; see limitations 1, 3 and 4 on simulator fidelity |
| C. Private-car contractor missing return, human intervention | Shown, with a wrong diagnosis | 000187 and 000239 routed to a person by `AUTH-04-contractor-custody`; diagnosis wrong; person's finding recorded as HUMAN_VERIFIED and escalated (`human.json`) |
| D. Reviewer failure blocks automatic action | Shown | `reviewer_failure.json` |
| E. Executed action fails verification, stays unresolved | Shown | 000553 (delivery failed again), 000029 (no confirming evidence) |
| F. Slow investigation while ingestion and monitoring continue | Shown | `concurrency.json`: investigation paused 210 s with 2 cases waiting: 782 events ingested, 85 monitor checks, 0 investigations; then 37 s, 21 s and 12 s investigations with 144, 130 and 40 events ingested meanwhile |

## 9. Does S5 meet its acceptance criteria? (my assessment)

Met: the reviewer fails closed and is shown as unavailable; nothing from the answer key reaches records,
the API or the UI; the four authority levels hold at execution on every path; no resolution on a wrong
cause or with the exception still present; failed actions stay unresolved; scenarios A to F are shown on
committed, clean code with provenance; detection has no false positives on live or held-out data.

Not yet met to a credible standard: autonomy (6 automatic resolutions, 4 of 20 eligible shipments, 63%
diagnosis accuracy) and the evidence for scenario B, which rests on a simulator with the four fidelity
defects above. My assessment: S5 meets its safety and verification-integrity criteria, but not its
autonomous-resolution quality bar. The gate stays open for the independent review.

## 10. Ready for controlled frontend integration?

Yes, for a controlled integration against the test databases, not for production. The case API now
carries the review verdict of the current run, the execution lifecycle (authorized, acknowledged, refused,
not acknowledged, verified, exception remains, human-verified) and approvability, which a new frontend
can render. Two backend items should precede or accompany it: serving the current execution explicitly
(limitation 5) and real operator identity on read and write routes.

## Live demo database: facts for a later decision (no change made)

- Target: Neo4j database `shipments-v2-demo-live` on the local Neo4j Enterprise 2026.09.0
  (bolt://localhost:7687).
- It holds the S2b-era import of dataset `DEMO-SUHAIL-LIVE-1` (600 shipments, manifest hash
  `1d561711…`, 54,812 evidence nodes, 10,870 pending provider feed items) and **no operations ledger**
  (0 cases, runs, decisions or audit entries). Its bundle is `artifacts/live-network/main`.
- A newer export exists at `artifacts/live-network/2026-10-09-s5` (feed hash `650656eb…`), built from the
  generator that has not changed since e4207f9. A replacement should use a fresh export built at the
  approved commit.
- Snapshot and rollback plan: (1) back up the database online with
  `neo4j-admin database backup --to-path=<backup dir> shipments-v2-demo-live`; (2) keep
  `artifacts/live-network/main` untouched and export the new bundle to a new directory (exports are
  immutable); (3) replace with `CREATE OR REPLACE DATABASE`, apply the new bundle with
  `python -m dataset_v2.live_bundle apply <dir> --database shipments-v2-demo-live`, and point
  `SUHAIL_LIVE_BUNDLE` at it; (4) roll back with
  `neo4j-admin database restore --from-path=<backup> --overwrite-destination=true shipments-v2-demo-live`
  (or re-apply the old bundle, since the ledger is empty) and point the bundle back.

## Tests and regression evidence

- Backend: 283 unit tests pass (10 Neo4j-gated tests skipped in that run); the 10 Neo4j integration
  tests (device sync, wrong-label and misread rescans, live ingestion, monitor detection, slow
  investigation not blocking ingestion) pass against the local Neo4j at f36736b (`final/neo4j_tests.txt`).
- Frontend: 162 of 162 tests pass; build and lint (0 errors) pass.
- Case API check (`final/case_api_smoke.json`): for all 41 cases the served run and review belong to the
  case's last run. Dashboard check in the browser (`final/dashboard_smoke.json`): verified, exception
  remains, person-only action with Approve disabled, verification failed, person's finding escalated,
  reviewer-rejected; simulation controls only in the Development view.
- No product feature was removed; legacy `agents.py` and `outcome.py` are kept (agents.py is live: the
  investigator imports its constants and `_ask`, and the API uses `agents.enabled()`; outcome.py is
  unreferenced).

## Earlier runs (superseded, kept for the record)

| Run | Code | Cases | Root cause | Auto executed | Auto resolved |
|---|---|---|---|---|---|
| 1 | before the S5 verifier fixes | 41 | 26 / 41 | 8 | 3 |
| 2 (`run2/`) | verifier held-back criterion | 42 | 28 / 42 | 13 | 8 |
| 3 (`run3/`) | plus exception-clearance check | 43 | 27 / 43 | 16 | 7 |
| 4 (`run4_154dd3e/`) | first fix round | 42 | 30 / 42 | 17 | 9 |

Runs 1 to 3 carry no provenance block (added in 6e80663). Run 3's receipts contained answer-key wording
(`run3/answer_key_scan_before_fix.json`).
