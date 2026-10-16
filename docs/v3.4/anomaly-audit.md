# Suhail V3.4 Workstream A: anomaly detection audit

Date 2026-10-16. Worktree `C:\Projects\suhail-v34-anomaly`, branch `v3/v34-anomaly-detection` from `1ff6518` (tree `b4ead6d8`).
Everything here was read from source and from the frozen V3 world bundle; no database was written and no model was called.

## A1. What the monitor actually does (implemented code, not design documents)

| Question | Answer, with source |
|---|---|
| How shipments enter monitoring | Event-driven queue on `OpsControl.monitor_queue` (`operations/store.py` `monitor_enqueue`, cap 500). A shipment is queued when (a) any record of it is ingested (`_tick_live` / replay `touched`) or (b) a deadline passes with no event: `_due_shipments` queries ExpectedMilestone `latest_at + grace + 900 s` and DeliverySession `end_at + grace + 900 s + 60 s` falling inside the tick. The `monitor` thread (`operations/workers.py`) drains it 10 at a time via `monitor_step`. Shipments with no new record and no due deadline are not re-checked (they cannot change state). |
| Evidence fields read | `dataset_v2/derive.py::assess_shipment` on the shipment's visible evidence world (`OpsReader.evidence(sid, clock)`): Package manifest barcode/weight; ScanEvent readable/confidence/observed_barcode/measured_weight_kg/calibrated; CustodyEvent from/to/event_type/acknowledgments/source_quality/source_event_id/assignment_id; Manifest versions; ExpectedMilestone predicate/location/latest_at/grace; DeliveryAttempt disposition/failed_reason/address version/observed gate; DeliveryInstruction; ContactAttempt; DeliveryProof and its Authentication/Signature/Photo/Handoff components; RecipientReport `NOT_RECEIVED`; DeliverySession + VehicleAssignment + DepotReconciliation; TrafficObservation (only as corroboration of a delay); Policy thresholds (barcode confidence 0.9, weight max(0.5 kg, 10 %), reconciliation grace 3600 s). |
| Rules that create exceptions (15) | BARCODE_MISMATCH, WEIGHT_MISMATCH, CUSTODY_GAP, CONFLICTING_CUSTODY, MANIFEST_CONFLICT, MISSED_MILESTONE, JOURNEY_DELAY, ADDRESS_CONFLICT, WRONG_GATE, RECIPIENT_UNAVAILABLE, DELIVERY_DISPUTE, PROOF_INSUFFICIENT, UNRECONCILED_CUSTODY, TRAFFIC_DELAY, INSUFFICIENT_EVIDENCE. `monitor_finding` maps them to 11 neutral symptoms (`SYMPTOMS`), never a cause. |
| Derived from evidence or seeded labels? | Evidence. Live development cases are opened only by `monitor_step` (`case_source: monitor`); `split_feed` drops the offline-derived development Case/Exception nodes from the import. `holdout_group` is only the shipment-ownership key. `gold.jsonl` in the bundle holds derived assessments, not causes; causes and mechanisms live outside the repository. The 24 Case / 27 Exception nodes in the graph are history-split records. |
| How healthy shipments avoid cases | No rule fires: every milestone observed by its corroborated custody event within latest+grace, readable barcodes match, calibrated weights inside tolerance, custody chain corroborated, sessions reconciled, proofs corroborated. Uncorroborated records younger than the 900 s allowance are skipped (`fresh`). |
| Expected milestones and promises | Per package ExpectedMilestone (RECEIVED / LOADED / DELIVERED) with earliest/nominal/latest and grace. JourneyPlan carries `promise_at`; the evaluation confirms the DELIVERED milestone deadline equals the promise for all 135 development packages, so delivery-promise lateness is already detected through that milestone. No ETA model exists; `journey_forecast` writes a risk flag only and never opens a case. |
| Time zones, clocks, event vs ingestion time | All instants UTC (Saudi local = UTC+3 helpers in `world/config.py`). A record counts only when `occurred_at <= recorded_at <= clock` (`derive._observed`); the live gateway stamps `recorded_at` at ingestion. So a buffered upload is judged on its event time once it arrives, and never before. The clock is the simulation clock in `OpsControl.as_of`. |
| Deduplication and repeats | One active case per shipment: new symptoms are merged into it (`SYMPTOMS_UPDATED`); a symptom set already covered by a resolved case does not reopen; feed retransmissions are deduplicated by `OpsEventReceipt`. Monitoring repeats on every touch/deadline. |
| Can later evidence clear or change an alert? | Partly. The assessment itself clears (e.g. MISSED_MILESTONE becomes JOURNEY_DELAY when a late scan arrives; CUSTODY_GAP disappears when the buffered source scan arrives). After an investigation, `materiality` requeues the case on material new evidence. **But before an investigation nothing records that the monitored discrepancy cleared**: `monitor_step` skips shipments whose finding is empty, so the case keeps its stale symptom and no audit says the alert no longer stands. Verified resolution stays the verifier's job (`closure.py`); nothing turns a cleared alert into RESOLVED. |
| GPT-OSS in detection? | None. `monitor_step`, `assess_shipment`, `monitor_finding` are deterministic; the model is called only by the investigator, reviewer, narration and Canopus. |

## A2. The existing synthetic world (frozen V3 bundle = demo DB evidence)

Bundle `C:\Projects\suhail-v3-data\world-v3-20261013\bundle`, dataset `DEMO-SUHAIL-WORLD-V3-20261013`, seed 11, world-1.1.
Imported 28,129 nodes / 45,823 edges + 40,452 provider feed items; reconstituted 68,413 nodes (equals the frozen DB count). The demo DB's 92,769 nodes are these plus the V3.2/V3.3 operations ledger.

- Shipments: 211 (development/live 102, history 109). Service: 156 STANDARD, 55 EXPRESS. Flow B2C 126, C2C 54, B2B 31. Handling: 3 bulky, 208 standard.
- Actors: 92 drivers (54 employee, 20 contractor, 18 independent), 97 vehicles incl. 18 private cars, 5 providers, 59 facilities.
- Evidence coverage (live shipments with at least one record): scans, custody, milestones, status, manifests 101-102/102; delivery attempts 101; proof bundles (proof/photo/handoff) 95; OTP/PIN authentication 66; signatures 21; contact attempts 26; recipient reports 22 (4 NOT_RECEIVED); inventory checks 24. GPS: 2,919 observations, all `VEHICLE_ONLY` scope (never parcel position). Calibrated weighings 342 of 3,895 scans.
- Buffered uploads (delivered at least 1 h after occurrence): 34 records on 19 live shipments (16 communication, 8 custody, 8 scans, 2 status).

Observable population by simulated time (from evidence, not truth):

| Clock (UTC) | Booked | Awaiting first scan | In progress | Delivered (corroborated) | Returned to depot | Tracking "delivered" without corroboration | Recipient dispute | Cases opened so far | No active finding now |
|---|---|---|---|---|---|---|---|---|---|
| 09-15 09:00 | 49 | 2 | 41 | 4 | 2 | 0 | 0 | 2 | 47 |
| 09-16 21:00 | 102 | 0 | 71 | 26 | 5 | 0 | 0 | 14 | 92 |
| 09-17 21:00 | 102 | 0 | 41 | 51 | 10 | 0 | 0 | 23 | 83 |
| 09-19 21:00 | 102 | 0 | 9 | 81 | 7 | 4 | 1 | 35 | 70 |
| 09-21 21:00 (horizon) | 102 | 0 | 6 | 89 | 1 | 2 | 4 | 40 | 65 |

Truth-scored (external generated truth, read only after detection, never by code paths): 60 healthy / 42 abnormal live shipments.

| Metric | Value |
|---|---|
| Healthy shipments that ever opened a case | **0 of 60** (at every clock) |
| Abnormal shipments opened by horizon | **40 of 42** |
| Missed | 000239 facility backlog (every milestone met: no observable deviation, correctly silent); 000131 wrong address (one ADDRESS_NOT_FOUND failed attempt, re-delivered within promise) |
| Opened before the cause was knowable | 1 at most at any clock (a symptom precedes its explanation, by design) |
| Hours from cause knowable to opening | median 0.8 h, range -18 h to 36 h (n 39) |
| Openings whose detector findings later cleared on new evidence | 18 transitions on 16 shipments; 4 fully cleared (000133, 000134, 000194 custody gaps cleared by buffered first-mile uploads; 000207) |

Evidence panels at the horizon (Fahad's A3 list):

| Panel | Shipments | Opened | Result |
|---|---|---|---|
| Delivered with corroborated proof, no failed attempt | 69 | 12 | the 12 carry another visible discrepancy (barcode 3, weight 2, custody gap 4, manifest 1, milestone 1, unreconciled 1) |
| Failed attempt then recorded return to depot | 26 | 21 | opened for overdue delivery / recipient unavailable; no rule asserts loss (`lost: false` always) |
| Bulky/heavy | 2 | 2 | both barcode, none weight |
| Recipient reported not received | 4 | 4 | human-floor dispute; never auto-dismissed |
| Tracking says delivered without corroboration | 5 | 5 | custody gap / proof insufficient |
| Buffered upload | 19 | 11 | reassessed on event time; 8 cleared transitions |
| Awaiting first scan, nothing due | 4 shipment-clock pairs | 0 | silent |
| Vehicle GPS missing | n/a | n/a | `assess_shipment` never reads GPSObservation, so GPS presence or absence cannot open or clear a case |

The generator's own replay (`suhail-v3-private/.../monitor_replay.json`) reports the same 0/60 and 40/42.

### 12 prioritized scenarios versus detector support

| Scenario | Detector rule that opens it | In the live world |
|---|---|---|
| S03 barcode misread, S04 wrong label | BARCODE_MISMATCH | yes (label misread 2, wrong label 2) |
| W04 wrong container | MISSED_MILESTONE (no container-membership rule) | indirect |
| C03 return not scanned back | UNRECONCILED_CUSTODY | yes |
| C04 unrecorded handover | CUSTODY_GAP | yes |
| D02 offline records uploaded later | CUSTODY_GAP, cleared when the upload arrives | yes (000133/134/194) |
| D11 one device, many shipments | per-shipment CUSTODY_GAP only; no cross-shipment correlation | per shipment only |
| P01 delivered but tracking in transit | PROOF_INSUFFICIENT / MISSED_MILESTONE | indirect |
| P11 proof of another shipment | PROOF_INSUFFICIENT (component binding) | yes (misdelivery 2) |
| G08 vehicle near address, no proof | MISSED_MILESTONE / UNRECONCILED_CUSTODY; GPS never used | indirect by design |
| Q01 weight differs | WEIGHT_MISMATCH | yes (scale drift 1, declared weight 1) |
| R01 not received despite proof | DELIVERY_DISPUTE | yes |

Of the 136 catalogue rows, 12 are prioritized with action/verifier support; the other 124 are catalogued but "not assessed". The detector has 15 rules: the catalogue is not 136 detectors.

## Gaps found

1. **A case does not say why it was detected.** The case stores only symptom codes. The rule's evidence (which milestone, expected location, deadline and grace, observed time, last corroborated event, evidence ids) is computed and thrown away; Fahad's "case with evidence of the missed deadline, expected location and last confirmed event" is not met.
2. **A cleared monitored alert is not recorded.** When later authoritative evidence removes the monitored discrepancy (D02 buffered upload), the case keeps the stale symptom with no audit, and the queue cannot distinguish "alert no longer stands" from "still standing".
3. **No healthy / monitored counts.** `monitor_checked` counts checks, not shipments; nothing records which shipments are currently clear, so the Operations page cannot show monitored vs healthy honestly.
4. Not gaps (documented): the two misses have no observable deviation that a rule could use without opening healthy failed-attempt shipments too; delivery promise is already the DELIVERED milestone; device-wide correlation (D11) and container membership (W04) are unassessed.

## Proposed minimal fixes (Workstream A, in order)

1. Record the detection evidence on the case at opening and on symptom updates (`detection_json`: rule code, symptom, reason, evidence ids, milestone expected/actual/deadline/grace, last corroborated custody event), serve it in the case detail. Visible evidence only; the investigator prompt is unchanged.
2. Record the monitor's alert state on every re-check of a case (`ACTIVE` / `PARTLY_CLEARED` / `CLEARED`, with the evidence that cleared it and an audit event). No workflow transition and no resolution: a cleared alert is not a verified outcome and the investigation still runs.
3. Per-shipment monitor watch state (last check, active symptoms) plus a read-only `/operations/monitor/overview` with shipments monitored, no active exception, newly detected, active investigations, waiting/human review, verified outcomes; a compact strip on Operations only if time remains.
4. Regression tests for the positive and negative panels, and the evaluation script `scripts/v34_detection_eval.py`.

## Worker/lane scaling

Owned by Workstream B; nothing in this workstream touches worker counts, lanes or credentials.

## Blockers

None for the offline work. The real-Neo4j gate needs a new disposable database (`shipments-v2-world-v34-anomaly-20261016`) created from the frozen bundle; the device safety check may block `.env`-based steps, in which case I will hand over one reviewable command.
