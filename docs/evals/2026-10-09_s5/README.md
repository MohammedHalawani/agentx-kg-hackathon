# S5 gate: end-to-end scenarios and measured metrics

All data is synthetic (dataset `DEMO-SUHAIL-LIVE-TEST`, generator `live-network-1`). Nothing here is
SPL operational data. Every investigation below is a real `openai/gpt-oss:120b` call through Ollama
Cloud (investigation agent with its Neo4j tool loop, plus the independent reviewer). Truth labels are
read only by the scoring code and by the synthetic field simulator; never by the investigator, its
tools, the reviewer, the API or the UI (`chat/tests/test_s5_safeguards.py`).

Reproduce from `chat/` (each phase recreates an isolated test database; `SUHAIL_TEST_DATABASE`
selects `shipments-v2-demo-test` or `shipments-v2-demo-test2`):

```
LLM_MODEL=openai/gpt-oss:120b uv run python ../scripts/s5_scenarios.py --phase pipeline --out <dir>
uv run python ../scripts/s5_scenarios.py --phase checks --out <dir>
uv run python ../scripts/s5_scenarios.py --phase accounting --out <dir>
uv run python ../scripts/s5_scenarios.py --phase heldout|reviewer|concurrency --out <dir>
```

## Runs

| Run | Code | Files |
|---|---|---|
| 1 | before the S5 verifier fixes | per-case file overwritten by run 2; metrics and the executed-action list were kept in the session log and are quoted below |
| 2 | held-back device-sync criterion, target-device fix, two-cause scoring | `run2/` |
| 3 (of record) | run 2 plus the exception-clearance check (`OUTCOME_VERIFIED_EXCEPTION_REMAINS`) | `run3/` |

Each run replays the 120 live shipments (81 healthy, 39 abnormal) hour by hour through the provider
gateway, the monitor, the investigation agent and reviewer, the authority policy, the execution
adapter (synthetic simulator) and the independent verifier. Wall time 36 to 38 minutes per run.

## Metrics

| | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Cases opened | 41 | 42 | 43 |
| Cases on healthy shipments | 0 | 0 | 0 |
| Abnormal shipments with no case | 0 | 0 | 0 |
| Root cause correct | 26/41 (63%) | 28/42 (67%) | 27/43 (63%) |
| Investigations degraded (fail-closed to a person) | 0 | 0 | 2 |
| Citations within retrieved evidence | 41/41 | 42/42 | 43/43 |
| Cited ids that resolve in the operator's case view | n/a | 145/148 (+3 device telemetry, 0 unresolved) | 139/141 (+2 device telemetry, 0 unresolved) |
| Key truth evidence cited | 6/13 | 5/12 | 6/13 |
| Automatic actions executed | 8 | 13 | 16 |
| ... on a wrong root cause | 3 | 2 | 3 |
| Automatic executions resolved after verification | 3/8 | 8/13 | 7/16 |
| AUTO-eligible shipments resolved with no human | 2/20 | 7/20 | 5/20 |
| Executed actions that failed verification and stayed unresolved | 5 | 5 | 5 |
| Verified actions kept open because the exception remained | n/a | n/a | 4 |
| Authority bypasses (execution without an AUTO decision or an approval) | n/a | 0/13 | 0/16 |

Held-out detection (`heldout_detection.json`, detection only, measured before these verifier fixes
and unaffected by them): the 120 held-out shipments replayed through the real gateway and monitor
gave 0 false-positive cases on 76 healthy shipments and caught 44 of 44 abnormal ones.

### False resolution

The automatic metric in `pipeline.json` flags a resolved case when the shipment's expected
resolution was not automatic. The accounting below goes case by case (`accounting.json`).

Run 3, 7 automatic resolutions:

| Shipment | Diagnosis | What happened after closure | Verdict |
|---|---|---|---|
| 000583, 000100 | barcode mismatch | rescan matched; nothing re-detected | correct |
| 000299 | weight mismatch | calibrated reweigh in tolerance; nothing re-detected | correct |
| 000392 | delayed sync (second cause) | the opening exception (depot receipt missing) was gone at closure 09-02 20:00. The manifest conflict arose at last-mile loading 09-03 03:00, was detected at 04:00, opened as a new case, diagnosed MANIFEST_CONFLICT and routed to a person | correct closure; second exception handled |
| 000030 | delayed sync (second cause) | same pattern: the recipient dispute arrived the next day, a new case was diagnosed PROOF_INSUFFICIENT and routed to a person | correct closure; second exception handled |
| 000415, 000466 | wrong gate, obsolete address | the recipient confirmed the address and the case closed; the redelivery never happened, the delivery milestone went overdue 5 to 6 hours later, a new case opened and (with the new check) went to a person | **premature** |

- Resolved on a wrong root cause: **0/7** (run 2: 0/8; run 1: 1/3, shipment 000392 scored before the two-cause correction).
- Resolved while a standing symptom was still present: **0/7** (run 2: **2/8**: the second cases of 000415 and 000466 were closed while MILESTONE_OVERDUE stood; this was the S5 defect fixed by the clearance check).
- Premature (action verified, but the exception it addressed came back): **2/7** (run 2: 2/8).

### The two-cause shipments

The second cause comes from the truth generator, not from the agent: `propagate_outages`
(`chat/dataset_v2/network.py`) delays every receipt the offline depot handheld made during its outage
window, for any shipment, and records `secondary_issue: DELAYED_SYNC` with the affected event ids on
abnormal shipments it touches (000030, 000392, 000459). Scoring credits either cause.

Resolution now requires the exception to be gone, in two layers: the verifier re-assesses the same
evidence snapshot and keeps the case open (`OUTCOME_VERIFIED_EXCEPTION_REMAINS`, routed to a person)
while a standing symptom remains; and the monitor opens a new case when a new symptom appears after
closure. Run 3 exercised both: the check fired 4 times (000404, 000415, 000459, 000466), and the
monitor re-detected 000392 and 000030.

### Every wrong diagnosis

| End state | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Routed to a person (human review, escalated) | 12 (incl. approval pending) | 10 | 12 |
| Approval pending | | 2 | 1 |
| Executed, verification failed, unresolved | 2 | 2 | 2 |
| Executed, verified, exception remained, unresolved with a person | | 0 | 1 |
| Executed, verified and resolved (false resolution) | 1 | 0 | 0 |
| Total | 15 | 14 | 16 |

Run 1's three automatic ones: 000392 conflicting manifest diagnosed delayed sync (executed, verified,
resolved; a false resolution as scored then); a wrong-label shipment diagnosed insufficient evidence
(executed, verification failed); 000337 absent transfer receipt diagnosed delayed sync (executed,
verification failed). Runs 2 and 3 are listed per case in `run2/accounting.json` and
`run3/accounting.json`.

## Scenarios

- **A, genuine investigation of an unknown issue.** Run 3, 000392 second case: opened by the monitor
  on MANIFEST_CUSTODY_CONFLICT; the agent called shipment_overview, custody_chain (2), vehicle_and_manifest,
  scans (2), delivery_attempts, precedents and device_status; concluded MANIFEST_CONFLICT (high
  confidence) citing 3 records; the reviewer accepted; authority sent it to a person
  (`AUTH-04-contractor-custody`). Mean 5.3 tool calls per investigation (2 to 10).
- **B, automatic resolution of a delayed scan with no human.** Run 3: 000392 and 000030 first cases
  (depot receipt missing, diagnosed delayed sync, device sync requested automatically, the held-back
  receipts arrived from the expected handheld, verified, resolved). Run 2: 000431 and 000017. Run 1: 000120.
- **C, private-car contractor missing return.** 000187 and 000239: routed to a person in runs 2 and 3
  (`AUTH-04-contractor-custody`, once `AUTH-16-review-rejected`); no action executed. The agent's diagnosis was wrong in runs 2 and 3
  (recipient unavailable instead of unreconciled custody). In the dashboard smoke test a person's
  finding ("parcel not found", with evidence) was recorded on 000239: HUMAN_VERIFIED, case escalated,
  not resolved. A second person's finding ("returned to depot") closed 000482 as HUMAN_VERIFIED, kept
  apart from evidence-verified outcomes.
- **D, reviewer failure blocks automatic action** (`reviewer_failure.json`). The real 120b
  investigation concluded BARCODE_MISMATCH with REQUEST_RESCAN (an AUTO action); the reviewer's
  endpoint was unreachable; review UNAVAILABLE, `AUTH-02-model-degraded`, HUMAN_REVIEW, 0 executions.
- **E, executed action fails verification and stays unresolved.** Run 3: both wrong-label rescans
  (barcode still differs), the unanswered-contact next-session delivery (failed again), and two device
  syncs on wrong diagnoses (no confirming evidence). All five unresolved with a person.
- **F, slow investigation while ingestion and monitoring continue** (`concurrency.json`). With
  automatic investigation paused for 60 s: 208 events ingested, 17 monitor checks, 0 investigations.
  During an 82 s investigation: 321 events ingested and 42 monitor checks; during a 30 s one: 119 and 14.

## The four requested checks

1. Normal events open no cases: 0 cases on 81 healthy live shipments in every run, 0 on 76 held-out.
2. Ingestion and monitoring continue while automatic investigation is paused: F above.
3. Case triggers seen in run 3: missed milestones (MILESTONE_OVERDUE, 28 cases), end-of-session
   reconciliation (SESSION_END_UNRECONCILED, 14), contradictory evidence (CUSTODY_REPORTS_CONFLICT 2,
   MANIFEST_CUSTODY_CONFLICT 3, BARCODE_READ_DIFFERS 4, WEIGHT_READ_DIFFERS 5), recipient reports
   (RECIPIENT_REPORTED_NOT_RECEIVED, 6).
4. The automatic switch cannot bypass action authority: every automatic execution has an AUTO
   authority decision and every other one an operator approval (0 bypasses of 16). Authority
   decisions by rule in run 3: AUTH-10 auto allowlist 16, AUTH-06 evidence conflict 10, AUTH-16
   review rejected 6, AUTH-04 contractor custody 5, AUTH-05 sensitive 3, AUTH-02 model degraded 2,
   AUTH-07 action mismatch 1.

## Dashboard smoke test

Served from the built frontend against the run 2 and run 3 test databases (agents off). Checked in the
browser: verified (device sync with receipt and field response), verification failed (wrong-label
rescan), authorized then executed with a receipt and verification pending (operator approval; "ask the
verifier to check now" left it pending with no evidence), human investigation with the finding form,
human-verified closure, a person's "parcel not found" shown as escalated (a labelling bug that showed
it as closed was fixed), action verified but exception remains (with the remaining symptom named),
the Explore risk-watch badge on an on-time shipment (no case opened), and the Arabic right-to-left
view. The duplicate "Synthetic action receipts" card with stale copy was removed.

## Limitations

- Delayed-sync diagnosis is the weakest area: 3 of 9 (run 2) and 2 of 10 (run 3) cases whose
  acceptable causes include DELAYED_SYNC were diagnosed as such; most others were called custody gaps
  and went to a person. Safe, but not autonomous. Not tuned on this split to avoid overfitting.
- Address confirmation closes a case before the redelivery happens (the 2 premature closures).
  Making a successful redelivery part of the verified effect is the next fix.
- The simulator models buffered uploads per shipment, so a device sync for a shipment caught in
  another shipment's handheld outage reports "nothing buffered" while the device's natural reconnect
  delivers the held-back records. The verifier credits the expected effect, not causation.
- Root-cause accuracy is measured on the development split only; there is no held-out diagnosis run.
- 2 of 43 run 3 investigations failed the citation validation and were sent to a person.
- The dashboard's live database (`shipments-v2-demo-live`) still holds the earlier S2b export. These
  runs used the current generator; a validated current export is at
  `artifacts/live-network/2026-10-09-s5` and replacing the live database with it is pending approval.
