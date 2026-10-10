# world-1 small (600 shipments), revision after independent review: evaluation outputs

Synthetic data only (`DEMO-SUHAIL-WORLD-1`, seed 20261010, 600 shipments booked over 8 days from 2026-09-10, 4-day horizon; history days 1-4, development the next 3, held-out the last 1). Generator and method: `chat/world/README.md`. Everything here was recomputed by the export and check commands on 2026-10-10, after the fixes for the independent review of the first build:

```
cd chat
uv run python -m world.export export --output ../artifacts/world/world-1-small-r4 --with-heldout --determinism \
    --eval-dir ../docs/evals/2026-10-10_world1_small            # 7 min 32 s wall, includes the second-seed world and the determinism rebuild
uv run python -m world.export apply ../artifacts/world/world-1-small-r4 --database shipments-v2-world-1-small --replace   # 3 min 10 s
uv run python -m world.export check ../artifacts/world/world-1-small-r4 --database shipments-v2-world-1-small \
    --ingest --out ../docs/evals/2026-10-10_world1_small/cypher.json                                        # 15 min 28 s
```

| File | What |
|---|---|
| `validation.json` | every validation section of the development export (and the held-out export's), the pre-run tell test, digests, timings |
| `monitor_replay.json` | the monitor replay over the 254 live development shipments (aggregates only; per-shipment rows are in the truth directory) |
| `monitor_replay_heldout.json` | the same for the held-out export (72 live shipments) |
| `cypher.json` | Neo4j counts, referential, temporal and isolation checks, timed time-correct traversals, PRECEDENTS, live ingestion |

Bundles: `artifacts/world/world-1-small-r4` and `artifacts/world/world-1-small-r4-heldout` (not committed). Truth labels: `C:\Projects\suhail-eval-truth\world-1-small-r4\DEMO-SUHAIL-WORLD-1\`. Simulator physical state: `C:\Projects\suhail-sim-state\world-1-small-r4\DEMO-SUHAIL-WORLD-1\`. Both are outside the repository. The first build (`artifacts/world/world-1-small`, truth in `C:\Projects\suhail-eval-truth\DEMO-SUHAIL-WORLD-1\`) is superseded and kept only because exports are immutable.

## Overall

Export verdict: **pass**. Gating sections: physics pass, observation pass, coverage pass, tells pass, discrimination pass, import_cut pass, forecasts pass, throughput_separation pass, precedent_cutoff pass, tell_test pass; per export: foundation (documented exceptions only) pass, isolation pass, discrimination specs of the export's own truth pass, monitor replay (nothing identifiable before booking) pass; determinism pass.

Reported, not gating, and **not met**: the floor of 10 clean development cases per mechanism and per family (section "Coverage").

Digests: development feed `1ea4b394...e210`, development V2 manifest `bf6b0a51...679d`, development truth `347f8b79...52db`, held-out feed `5a15ccc8...3cde`, held-out V2 manifest `b3eb5518...3162`, held-out truth `0d04a975...a4da`, mechanisms `ea201b96...97c3`. A second build from the same configuration reproduced every digest.

Timings (cumulative seconds): build 39.2, both exports 84.2, validation 213.5, monitor replays 243.3, second-seed world and tell test 292.4, determinism rebuild 413.5.

## Counts

| Split | Shipments | Healthy (no cause that needs an answer) | Abnormal | With a scheduled fault | Multi-cause |
|---|---|---|---|---|---|
| history (days 1-4) | 274 | 147 | 127 (46%) | 104 (38%) | 39 |
| development | 254 | 117 | 137 (54%) | 125 (49%) | 54 |
| held-out | 72 | 27 | 45 (62%) | 42 (58%) | 14 |

Development export: 46,381 imported nodes, 84,887 relationships, 57,944 feed messages (MDM 28,083, SPL_CORE 22,770, DRIVER_APP 2,867, TELEMATICS 1,809, MESSAGING 1,324, CARRIER_EDI 930, RECIPIENT_PORTAL 118, TRAFFIC 43; 332 provider retransmissions). 66 imported node kinds; largest: DeviceHeartbeat 13,882, ExpectedMilestone 5,209, RouteMilestone 5,209, ScanEvent 3,726, CustodyEvent 2,752, RouteSegment 2,476, StatusEvent 1,407, FacilityThroughput 1,293. Fed record kinds, largest: HEARTBEAT 28,083, ScanEvent 6,144, CustodyEvent 4,727, StatusEvent 2,700, FacilityThroughput 2,612, FIX 1,809, VehicleAssignment 1,372, DLR 1,324. Held-out export: 31,371 feed messages.

### Import cut by time

- development export, live start 2026-09-13T21:00:00+00:00: 46,381 imported nodes, of which **0** recorded after the live start other than the booking-time context of live shipments (8,501 records stamped exactly at their shipment's booking: the foundation contract). Fed instead: 7,124 later records of earlier booking days and 34,601 shared records.
- held_out export, live start 2026-09-16T21:00:00+00:00: 80,735 imported nodes, of which **0** recorded after the live start other than the booking-time context of live shipments (2,260 records stamped exactly at their shipment's booking: the foundation contract). Fed instead: 7,113 later records of earlier booking days and 19,968 shared records.

## Coverage: causes, not touches

Committed rate 0.02 per scheduled mechanism in every split (history and live alike): targets 5 (history) and 5 (development) shipments on which the mechanism is the CAUSE of a deviation. Below target in development: none.

Shipments the mechanism caused a deviation on (history / development / held-out), and in development: cases the monitor opened that it explains / clean cases (opened, and it is the shipment's only cause).

| Mechanism | H | D | HO | D explained | D clean | Mechanism | H | D | HO | D explained | D clean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ASSIGNED_NOT_LOADED | 14 | 7 | 2 | 5 | 4 | OTP_NOT_RECEIVED | 6 | 7 | 2 | 5 | 2 |
| CONTRACTOR_RETAINS | 5 | 9 | 1 | 5 | 4 | PARTIAL_UPLOAD_LOSS | 6 | 15 | 2 | 11 | 5 |
| CUSTOMER_COMPLAINT | 5 | 5 | 1 | 4 | 4 | RECIPIENT_UNAVAILABLE | 5 | 5 | 1 | 3 | 0 |
| DECLARED_WEIGHT_WRONG | 5 | 6 | 1 | 6 | 2 | RETURN_SCAN_SKIPPED | 6 | 5 | 3 | 3 | 0 |
| DELIVERY_SCAN_SKIPPED | 8 | 5 | 4 | 4 | 3 | ROUTINE_FAILED_ATTEMPT | 43 | 39 | 12 | 25 | 10 |
| DEVICE_OUTAGE | 6 | 5 | 2 | 4 | 2 | SCALE_DRIFT | 6 | 8 | 10 | 8 | 6 |
| FACILITY_BACKLOG | 5 | 11 | 2 | 6 | 0 | SCAN_SKIPPED_AT_RECEIPT | 7 | 9 | 2 | 9 | 5 |
| LABEL_MISREAD | 7 | 8 | 3 | 8 | 2 | TRAFFIC_DISRUPTION | 5 | 9 | 3 | 1 | 0 |
| LATE_LINEHAUL | 9 | 10 | 1 | 3 | 0 | UNRECORDED_HANDOFF | 5 | 6 | 1 | 4 | 3 |
| MANIFEST_ERROR | 5 | 7 | 1 | 4 | 1 | WRONG_ADDRESS | 5 | 5 | 1 | 2 | 1 |
| MISDELIVERY | 6 | 6 | 1 | 6 | 6 | WRONG_GATE | 5 | 5 | 1 | 5 | 4 |
| MISSORT | 7 | 5 | 7 | 3 | 3 | WRONG_LABEL_APPLIED | 5 | 7 | 1 | 7 | 2 |
| NEIGHBOUR_RECEIVES | 7 | 7 | 1 | 5 | 3 |  | | | | |  |

**Clean-case floor (10 per mechanism and per family): not met.** Clean development cases per scheduled mechanism range from 0 to 6; none: FACILITY_BACKLOG, LATE_LINEHAUL, RECIPIENT_UNAVAILABLE, RETURN_SCAN_SKIPPED, TRAFFIC_DISRUPTION. From the measured yield, the development size that would reach the floor at these rates is 424 to 2,540 shipments depending on the mechanism (this world has 254). Per family (clean cases; F = opened multi-cause cases; G = healthy shipments and how many opened): A: ASSIGNED_NOT_LOADED 4, CONTRACTOR_RETAINS 1, DELIVERY_SCAN_SKIPPED 2, clean 7; B: DEVICE_OUTAGE 2, PARTIAL_UPLOAD_LOSS 5, clean 7; C: ASSIGNED_NOT_LOADED 4, CONTRACTOR_RETAINS 4, MANIFEST_ERROR 1, PARTIAL_UPLOAD_LOSS 5, SCAN_SKIPPED_AT_RECEIPT 5, UNRECORDED_HANDOFF 3, clean 22; D: MISSORT 3, clean 3; E: MISDELIVERY 6, NEIGHBOUR_RECEIVES 3, OTP_NOT_RECEIVED 2, clean 11; F: opened 54; G: opened 2, shipments 117; H: CUSTOMER_COMPLAINT 4, OTP_NOT_RECEIVED 2, WRONG_ADDRESS 1, WRONG_GATE 4, clean 11.

## Validation

- Physics: pass. 10,777 scans where the parcel was, 9,003 custody-location agreements, 1,197 travel times, 352 facility-hours within capacity. Final parcel locations: {'FACILITY': 25, 'PERSON': 878, 'VEHICLE': 14}.
- Observation: pass. 90,745 occurred-before-recorded checks, 93 device-offline windows (scheduled and ordinary), 36 stuck-upload windows, 2,470 out-of-order pairs, 332 retransmissions. Upload lag p50/p90/p99/max: records no mechanism shaped 6/108/646/19281 s, records a mechanism shaped 74/16399/85201/88135 s.
- Foundation (`validate_live_bundle`): only the documented exceptions fail ({'ADDRESS_VERSION_INTERVAL': 24, 'PHYSICAL_CUSTODY_CHAIN': 49}), all 73 explained. Reconstituted development world: 104,366 nodes, 348 shipments with no case and 180 cases at the end of the horizon. Held-out export: {'ADDRESS_VERSION_INTERVAL': 27, 'PHYSICAL_CUSTODY_CHAIN': 54}.
- Export isolation: pass. 224 substrings, 9 words, 43 cause/type tokens, 16 action tokens over 2,780,414 texts; canary 0 hits, mechanism ids 0 hits. Held-out export: pass.
- Physical state vocabulary (hygiene only; the state is outside the repository and causes are derivable from it by design): 0 hits over 3,384 records (161 devices listed, every device of the network).
- Forecasts: pass. 431 carrier estimates issued before arrival, 0 equal to the later arrival; estimate error p50 547 s, p90 3389 s; 47 delay notices sent while a truck was held at origin. Other future-dated fields equal to a later event of the same shipment (plan and validity fields): {'AuthenticationEvidence.expires_at': 2, 'ExpectedMilestone.earliest_at': 36, 'ExpectedMilestone.latest_at': 1, 'VehicleAssignment.valid_to': 1}.
- Throughput separation: pass. Utilisation of staffed capacity over 352 working facility-hours: p50 0.28, p90 0.88, max 1.33; 115 ordinary hours end with a queue. Backlogs (facility, caused, exposed, oldest wait max in its hours, ordinary p95, ordinary max, minutes): DEPOT-RUH-N 9/4/178/0/55; DEPOT-RUH-N 0/1/11/0/55; SORT-DMM-01 2/10/119/0/59; SORT-DMM-01 0/1/1/0/59; SORT-DMM-01 5/9/361/0/59; SORT-RUH-01 2/9/204/26/153.
- Tell detector (single-record observables incl. absent values, list lengths, number and lag buckets, barcode and weight gaps, value-with-absent-field pairs): 0 tells in development and 0 in the world over 768 / 781 features. Documented discriminators found and reported apart (world): LABEL_MISREAD <- ScanEvent <barcode> 1 off (10 shipments); MISSORT <- VehicleAssignment mode=linehaul & segment_id <none> (9 shipments); NEIGHBOUR_RECEIVES <- HandoffEvidence recipient_type=AUTHORIZED_ALTERNATE & authorization_ref <none> (10 shipments); ROUTINE_FAILED_ATTEMPT <- DeliveryAttempt failed_reason=ACCESS_NOT_COMPLETED & observed_gate <none> (5 shipments); WRONG_LABEL_APPLIED <- ScanEvent <barcode> 5+ off (5 shipments); WRONG_LABEL_APPLIED <- ScanEvent <barcode> another parcel's (5 shipments).
- Discrimination specs: pass. 446 actionable instances; 854 record items, 98 absence items recompute and are real; 633 groups each hold an item of the shipment; no estimate before booking (444 checked); nothing identifiable one second before booking (600 shipments). Without any discriminator: {'DECLARED_WEIGHT_WRONG': 1, 'UNRECORDED_HANDOFF': 1}. The same checks pass on each export's own truth (every cited record is in that export: 719 checked for development).
- Precedent cut-off: pass. Development export: 59 history cases, 39 precedents (14 succeeded, 25 failed), not imported: {'MECHANISM_ACTIVE_AT_OR_AFTER_CUTOFF': 20}. Held-out export: 186 history cases, 147 precedents (74 succeeded, 73 failed), not imported: {'MECHANISM_ACTIVE_AT_OR_AFTER_CUTOFF': 37, 'NOT_VERIFIABLE_BEFORE_CUTOFF': 2}.
- Consolidation (reported): 282 containers, 110 with one parcel, median 2; 142 route runs, median 7 parcels; 246 trips ran with containers, 361 scheduled departures were cancelled empty (each with a dated cancellation).

## Pre-run tell test (addendum B3, gating)

Train: 127 development opening cases (seed 20261010). Test: seed 20261011, 116 cases. Stratum: cases whose opening symptom set another cause code shares. Scored against the truth's acceptable causes for the opening. The lookup sees every visible value except the records the explaining mechanisms themselves shaped (their documented evidence).

| | Cases | Baseline (rule codes) | Lookup |
|---|---|---|---|
| Forward (train this world, test the other) | 84 | 45 | 43 |
| Reverse | 96 | 59 | 57 |
| **Pooled (the gate: lookup must not exceed baseline)** | 180 | 104 | 100 |
| Literal variant, forward (lookup also reads the cause's own evidence) | 84 | 45 | 43 |
| Literal variant, reverse | 96 | 59 | 59 |
| Forward, ambiguous and nothing discriminating arrived by the opening | 12 | 3 | 9 |
| Forward, ambiguous and discriminating evidence arrived by the opening | 72 | 42 | 34 |
| Forward, all opened abnormal cases | 116 | 77 | 75 |

Result: **pass** (forward alone: pass; reverse alone: pass; literal variant pooled: lookup does not beat the baseline). Forward discordant cases: 17 lookup-only right, 19 baseline-only right. Features behind lookup wins: StatusEvent.status=OUT_FOR_DELIVERY (8), Manifest.provider_id=DEMO-PROV-INDEP-01 (3), ExpectedMilestone.location_id=DEMO-HUB-JED-01 (2), Address.city=Jeddah (2), ScanEvent.confidence=0.998 (1), ScanEvent.confidence=0.951 (1). Behind losses: ExpectedMilestone.location_id=DEMO-HUB-JED-01 (3), Address.city=Jeddah (2), Customer.contact_preference=CALL (2), ScanEvent.confidence=0.975 (2), StatusEvent.status=OUT_FOR_DELIVERY (2), StatusEvent.status=DELIVERY_ATTEMPTED (1), ScanEvent.confidence=0.95 (1), Customer.contact_preference=WHATSAPP (1).

Open point, not closed by the gate: in the 12 forward ambiguous cases where nothing discriminating had arrived by the opening, the lookup is right in 9 and the baseline in 3. The values behind it are the stage the shipment had reached (tracking status, planned hub): context the rule codes do not carry, not a planted field. Whether stage context counts as part of what the monitor shows is a decision for the product owner (see `chat/world/README.md` section 8, which also lists the three choices this test makes that differ from the first build).

## Monitor replay, development (hourly ticks from the live start, 900 s allowance)

- Live shipments 254. Healthy 117, opened 2 (false-positive rate 1.7%): {'CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE': 1, 'SESSION_END_UNRECONCILED': 1}.
- Without a scheduled fault 129 (of which 12 with an ordinary cause), opened 14: {'CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE': 1, 'DELIVERY_ATTEMPT_FAILED': 5, 'MILESTONE_OVERDUE': 5, 'SESSION_END_UNRECONCILED': 1, 'WEIGHT_READ_DIFFERS': 2}.
- Abnormal 137: opened 127, not opened 10, multi-cause 54; opened with no cause that explains the opening 1. Acceptable cause codes per opened case: {'1': 58, '2': 44, '3': 15, '4': 7, '5': 2, '6': 1}.
- Identifiable under `labels_at` with the time-aware ingestion log: at opening 113 of 127, by the end of the horizon 127; opened before any cause was knowable 14. Shipments with a cause identifiable before their booking: **0**.
- Ambiguous (opening shared with another cause code) 95 of 127 opened abnormal cases: identifiable 95 (88 at opening, 7 only later), unidentifiable 0.

| Opening symptom set | Cases | Healthy | Without a scheduled fault | Mechanisms that explain it (cases) | Clean cases by mechanism |
|---|---|---|---|---|---|
| BARCODE_READ_DIFFERS | 11 | 0 | 0 | LABEL_MISREAD 7, WRONG_LABEL_APPLIED 7 | LABEL_MISREAD 2, WRONG_LABEL_APPLIED 2 |
| BARCODE_READ_DIFFERS + WEIGHT_READ_DIFFERS | 1 | 0 | 0 | DECLARED_WEIGHT_WRONG 1, LABEL_MISREAD 1 | none |
| CUSTODY_TRANSFER_UNCONFIRMED | 28 | 0 | 0 | DEVICE_OUTAGE 3, MISSORT 1, NEIGHBOUR_RECEIVES 2, PARTIAL_UPLOAD_LOSS 10, SCAN_SKIPPED_AT_RECEIPT 9, UNRECORDED_HANDOFF 4 | DEVICE_OUTAGE 2, MISSORT 1, PARTIAL_UPLOAD_LOSS 5, SCAN_SKIPPED_AT_RECEIPT 5, UNRECORDED_HANDOFF 3 |
| CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE | 12 | 1 | 1 | MISDELIVERY 6, NEIGHBOUR_RECEIVES 3, OTP_NOT_RECEIVED 2 | MISDELIVERY 6, NEIGHBOUR_RECEIVES 3, OTP_NOT_RECEIVED 2 |
| DELIVERY_ATTEMPT_FAILED | 17 | 0 | 5 | RECIPIENT_UNAVAILABLE 1, ROUTINE_FAILED_ATTEMPT 11, WRONG_GATE 5 | ROUTINE_FAILED_ATTEMPT 5, WRONG_GATE 4 |
| DELIVERY_ATTEMPT_FAILED + MANIFEST_CUSTODY_CONFLICT | 1 | 0 | 0 | MANIFEST_ERROR 1, ROUTINE_FAILED_ATTEMPT 1 | none |
| MANIFEST_CUSTODY_CONFLICT | 3 | 0 | 0 | MANIFEST_ERROR 3 | MANIFEST_ERROR 1 |
| MILESTONE_LATE | 4 | 0 | 0 | FACILITY_BACKLOG 4, OTP_NOT_RECEIVED 1, RECIPIENT_UNAVAILABLE 1 | none |
| MILESTONE_OVERDUE | 25 | 0 | 5 | CONTRACTOR_RETAINS 3, DELIVERY_SCAN_SKIPPED 2, DEVICE_OUTAGE 1, FACILITY_BACKLOG 2, LATE_LINEHAUL 3, MISSORT 2, OTP_NOT_RECEIVED 2, PARTIAL_UPLOAD_LOSS 1, RECIPIENT_UNAVAILABLE 1, RETURN_SCAN_SKIPPED 3, ROUTINE_FAILED_ATTEMPT 13, TRAFFIC_DISRUPTION 1, WRONG_ADDRESS 2 | CONTRACTOR_RETAINS 3, DELIVERY_SCAN_SKIPPED 1, MISSORT 2, ROUTINE_FAILED_ATTEMPT 5, WRONG_ADDRESS 1 |
| RECIPIENT_REPORTED_NOT_RECEIVED | 4 | 0 | 0 | CUSTOMER_COMPLAINT 4 | CUSTOMER_COMPLAINT 4 |
| SESSION_END_UNRECONCILED | 10 | 1 | 1 | ASSIGNED_NOT_LOADED 5, CONTRACTOR_RETAINS 2, DELIVERY_SCAN_SKIPPED 2 | ASSIGNED_NOT_LOADED 4, CONTRACTOR_RETAINS 1, DELIVERY_SCAN_SKIPPED 2 |
| WEIGHT_READ_DIFFERS | 13 | 0 | 2 | DECLARED_WEIGHT_WRONG 5, SCALE_DRIFT 8 | DECLARED_WEIGHT_WRONG 2, SCALE_DRIFT 6 |

## Monitor replay, held-out (hourly ticks from the live start, 900 s allowance)

- Live shipments 72. Healthy 27, opened 0 (false-positive rate 0.0%): none.
- Without a scheduled fault 30 (of which 3 with an ordinary cause), opened 3: {'DELIVERY_ATTEMPT_FAILED': 1, 'MILESTONE_OVERDUE': 2}.
- Abnormal 45: opened 40, not opened 5, multi-cause 14; opened with no cause that explains the opening 1. Acceptable cause codes per opened case: {'1': 17, '2': 15, '3': 5, '4': 1, '5': 2}.
- Identifiable under `labels_at` with the time-aware ingestion log: at opening 36 of 40, by the end of the horizon 40; opened before any cause was knowable 4. Shipments with a cause identifiable before their booking: **0**.
- Ambiguous (opening shared with another cause code) 27 of 40 opened abnormal cases: identifiable 27 (25 at opening, 2 only later), unidentifiable 0.

| Opening symptom set | Cases | Healthy | Without a scheduled fault | Mechanisms that explain it (cases) | Clean cases by mechanism |
|---|---|---|---|---|---|
| BARCODE_READ_DIFFERS | 2 | 0 | 0 | LABEL_MISREAD 1, WRONG_LABEL_APPLIED 1 | LABEL_MISREAD 1, WRONG_LABEL_APPLIED 1 |
| BARCODE_READ_DIFFERS + WEIGHT_READ_DIFFERS | 2 | 0 | 0 | LABEL_MISREAD 2, SCALE_DRIFT 2 | none |
| CUSTODY_TRANSFER_UNCONFIRMED | 4 | 0 | 0 | DEVICE_OUTAGE 1, PARTIAL_UPLOAD_LOSS 1, SCAN_SKIPPED_AT_RECEIPT 1, UNRECORDED_HANDOFF 1 | DEVICE_OUTAGE 1, PARTIAL_UPLOAD_LOSS 1, SCAN_SKIPPED_AT_RECEIPT 1, UNRECORDED_HANDOFF 1 |
| CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE | 3 | 0 | 0 | MISDELIVERY 1, NEIGHBOUR_RECEIVES 1 | MISDELIVERY 1, NEIGHBOUR_RECEIVES 1 |
| DELIVERY_ATTEMPT_FAILED | 5 | 0 | 1 | RECIPIENT_UNAVAILABLE 1, ROUTINE_FAILED_ATTEMPT 4 | RECIPIENT_UNAVAILABLE 1, ROUTINE_FAILED_ATTEMPT 1 |
| MANIFEST_CUSTODY_CONFLICT | 1 | 0 | 0 | MANIFEST_ERROR 1 | MANIFEST_ERROR 1 |
| MILESTONE_OVERDUE | 11 | 0 | 2 | ASSIGNED_NOT_LOADED 2, MISSORT 6, RETURN_SCAN_SKIPPED 1, ROUTINE_FAILED_ATTEMPT 4, TRAFFIC_DISRUPTION 2, WRONG_ADDRESS 1 | MISSORT 5, ROUTINE_FAILED_ATTEMPT 2, TRAFFIC_DISRUPTION 1 |
| SESSION_END_UNRECONCILED | 3 | 0 | 0 | CONTRACTOR_RETAINS 1, DELIVERY_SCAN_SKIPPED 1, RETURN_SCAN_SKIPPED 1 | CONTRACTOR_RETAINS 1, DELIVERY_SCAN_SKIPPED 1, RETURN_SCAN_SKIPPED 1 |
| WEIGHT_READ_DIFFERS | 9 | 0 | 0 | DECLARED_WEIGHT_WRONG 1, SCALE_DRIFT 8 | SCALE_DRIFT 3 |

B4 sizing: this 600-shipment world yields 95 identifiable ambiguous development cases (7 only after opening) from 254 development shipments. A fresh-seed evaluation world needs about 400 development shipments at these rates for 150 such cases.

## Neo4j (`shipments-v2-world-1-small` only)

- Verdict: **pass**. Counts match the bundle exactly: 46,381 nodes (46,381 expected), 84,887 relationships (84,887), 57,944 feed items; per kind True, per relationship type True.
- Referential: 59,150 references resolved, unresolved 0, cross-shipment edges 0; after ingestion 218,341, unresolved 0.
- Temporal: all checks 0 before and after ingestion, among them `imported_after_live_start_other_than_live_booking_context` = 0 and `feed_delivered_at_or_before_live_start` = 0; 8,501 live booking-context records are imported (the documented exception).
- Isolation scan (canary, 779 mechanism ids, 50 name forms): 0 hits over 189,213 records (67.1 s); after ingestion 0 hits over 341,458 (138.7 s).
- Gateway ingestion in 72 six-hour steps: 57,944 messages, 57,612 ingested, 332 duplicates, 0 conflicting, 0 rejected, 688.2 s (84.2 msg/s). Reset afterwards: {'feed_items_not_pending': 0, 'live_ingested_nodes_left': 0}.
- **Time-correct traversals** as of 2026-09-22T21:00:00+00:00: pass. The same rows with the clock there and after the whole feed was ingested: True; traversals returning a record from after that instant: none.
- PRECEDENTS query: 39 rows ({'False': 25, 'True': 14}), median 54.17 ms.
- Traversal medians in ms (imported, as of the live start -> live, as of the end; all through `visible()`):
  - device_heartbeats_around_window: 6.23 -> 4.15 (live max 24.44); live example {'beats': 1, 'max_pending': 56}
  - same_container: 6.72 -> 8.48 (live max 25.6); live example {'container': 'DEMO-CTR-RUH-00062', 'parcels': 19, 'shipments': 10}
  - same_device_in_window: 5.3 -> 5.01 (live max 21.03); live example {'device': 'DEMO-DEV-APP-DRV-MAK-01-01', 'scans': 21, 'shipments': 6}
  - same_facility_in_window: 5.53 -> 4.49 (live max 19.83); live example {'by_event': {'LOADED': 1}, 'facility': 'DEMO-DEPOT-AHB-01', 'oldest_waiting_minutes_max': 0, 'throughput_hours': 10, 'window_hours': 12}
  - same_route_run: 8.71 -> 8.49 (live max 43.49); live example {'custody_events': 24, 'route_run': 'DEMO-RR-JED-01-0914-1', 'shipments': 12}
  - same_sms_route_in_window: 4.89 -> 4.01 (live max 17.82); live example {'by_status': {'DELIVERED': 11, 'FAILED': 14}, 'carrier_route': 'OP-3'}
  - same_trip: 7.41 -> 5.97 (live max 28.78); live example {'shipments': 36, 'trip': 'DEMO-TRIP-FM-RUH-0914-1330', 'trip_events': 2}

