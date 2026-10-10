

# AUDIT dataset

## Summary
I rebuilt the S5 world in memory with live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"); its truth hash matches the run (0775597...). I then reproduced the monitor's opening symptoms for all 207 abnormal shipments across the three splits. My reconstruction matches 35 of the 39 dev openings exactly; the other 4 differ only because the monitor ticks hourly. The anomalies are independent per-shipment recipes: 24 abnormal and 10 normal. The only cross-shipment mechanism is the depot-handheld outage, which reached 39 other shipments, 6 of them in dev. Each dev recipe has only 1 to 3 shipments, so the 63% (Wilson 95% CI 48-76%) cannot be broken down by recipe with any confidence. At the moment a case opens, the visible evidence is rich enough: a lookup over visible evidence would label 197 of 204 opened shipments correctly (96.6%). For 139 of 204 (68%), an acceptable cause is already a deterministic rule code at opening. Only one pair is truly indistinguishable at opening: contractor_unreturned vs unanswered_contact (15 shipments). The dataset is also artificially easy in places. Several fields correlate one-to-one with recipes (status IN_TRANSIT/OUT_FOR_DELIVERY, failed_reason values, DEPOT_DISPATCH_SCAN, the handover-report source_refs, "Gate 1", the barcode always being the manifest barcode plus an appended "8", the weight always 0.65 x declared). Healthy shipments have zero timing jitter, which is why detection precision of 1.00 is trivial. Realism is weak: no shared vehicles, drivers, sessions or containers, one address coordinate per city, and causal contradictions (the "miscalibrated" scale reads 109 nearby parcels correctly). Of the 15 dev failures, 5 are answers the taxonomy accepts for an evidence-identical sibling recipe or that equal a rule code firing at opening. 2 are contractor_unreturned, whose label only becomes visible a median 9.25 h after the single investigation. 4 named the observation (CUSTODY_GAP) instead of the mechanism (DELAYED_SYNC), although the depot handheld was retrievably SILENT. Only 4 are plain investigator failures (2 wrong answers, 2 degraded runs).

### [dataset] Anomalies are independent per-shipment recipes; the only shared-world mechanism is the depot-handheld outage
Evidence: Recipe branches are inside Builder.shipment (generate.py:147-572), plus 5 overlays (network.py:507-509) and accounted_return (network.py:426). network.py:42-50 defines 24 abnormal recipes and network.py:35-41 defines 10 normal ones. Recipes are assigned per split by alphabetical round-robin (network.py:157-172), after the 8 required abnormal recipes (network.py:52-54). The one cross-shipment mechanism is propagate_outages (network.py:288-312). Each offline_device_sync shipment silences one depot handheld for exactly 20.67 h (network.py:342-343). There are 7 such outages (4 history, 2 dev, 1 held-out), and they delayed receipts of 39 other shipments (21 history, 6 dev, 12 held-out). There are no facility backlogs: later_hub_departure shifts only its own shipment by 12 h (generate.py:283). There is no shared traffic: the TrafficObservation is per shipment and on that shipment's own RouteSegment (generate.py:543-547). There are no shared sessions: 1,313 DeliverySession nodes, 0 shared (generate.py:272).
Impact: The investigator never has to separate a network-level cause (a backlogged hub, a bad scale batch, a driver with many parcels) from a parcel-level one. The one shared mechanism, the outage, produced 8 of 39 dev abnormal shipments, and 4 of those were misdiagnosed.
Recommendation: Make faults world-level (facility backlog windows, scale drift windows, driver-route failures), apply them to every shipment they physically touch, and derive truth from the affected events instead of from the recipe name.

### [evaluation] Dev split is too small and too thin per recipe for per-recipe conclusions
Evidence: Dev has 120 shipments: 81 healthy, 36 recipe-abnormal, and 3 healthy shipments (fulfillment, next_day, contractor_on_time) converted to DELAYED_SYNC by the outage. Per abnormal recipe: conflicting_manifest 3; 10 recipes with 2; 13 recipes with 1. The 41 scored cases include 2 duplicates (000415 and 000466 each have 2 cases). 26/41 has a Wilson 95% CI of 0.481-0.764, which covers the reported run-to-run spread of 63-71%.
Impact: One case changes a recipe's accuracy by 33-100 points. The accuracy cannot be attributed to recipe difficulty from this run alone.
Recommendation: Score per shipment, using 10 or more shipments per recipe (for example a dev split of 600 or more, or several seeds), and report confidence intervals.

### [dataset] Visible evidence at opening separates the recipes (ceiling 96.6%); one pair is truly indistinguishable
Evidence: Opening was reconstructed with assess_shipment and DETECTION_ALLOWANCE 900 s (store.py:26, 72-75), using feed deliver_at as recorded_at. Grouping the 204 opened abnormal shipments by rule codes plus last corroborated holder, missing milestones, uncorroborated events (observation_type, quality), attempts, contacts, manifest versions, proof reasons, address versions and depot heartbeat gives a best-single-label ceiling of 197/204. Without status and heartbeat it is 195/204. All 6 irreducible errors come from contractor_unreturned (9) vs unanswered_contact (6). Both open DELIVERY_ATTEMPT_FAILED with FAILED/RECIPIENT_NOT_REACHED plus NO_RESPONSE contacts (generate.py:417-435). The overlay only removes the RETURNED receipt and reconciliation (network.py:365-379), which can only be noticed after session end plus grace. Other pairs: local later_hub_departure (2/8) and local absent_transfer_receipt (1/9) are identical at opening (missing RECEIVED@DeliveryDepot, last RECEIVED@Hub, status IN_TRANSIT, depot handheld reporting); their acceptable sets share only MISSED_MILESTONE. different_barcode vs wrong_label_applied and different_weight vs declared_weight_wrong are identical forever (generate.py:377-380): same cause, but AUTO vs HUMAN resolution (network.py:88-91). Distinguishing evidence that does exist: offline/outage shows a SILENT depot handheld at opening (105-1,163 min, 30-min cadence, network.py:25) and status not yet set. Intercity absent_transfer_receipt shows last LOADED on the linehaul vehicle plus a LINE-ARRIVAL GPS fix at the destination hub. Intercity later_hub_departure is the only recipe with LOADED@Hub missing. contractor_unconfirmed_pickup carries DEPOT_DISPATCH_SCAN with INCOMPLETE_ACK 1/2 (network.py:385-389). absent_session_receipt shows last LOADED on the last-mile vehicle, no attempt, status OUT_FOR_DELIVERY. partial_packages shows the same pattern on the last package only, with the other packages DELIVERED.
Impact: The dataset does not cap accuracy near 63%. At most 2 of 15 dev failures (000187, 000239) are forced by evidence that is identical at opening.
Recommendation: Keep the contractor_unreturned scenario, but score its diagnosis only after SESSION_END_UNRECONCILED exists, or accept RECIPIENT_UNAVAILABLE before then. Give wrong_label vs misread and declared vs miscalibrated an observable difference (another valid barcode, a second scale reading).

### [dataset] Many fields correlate one-to-one with a recipe (artificially obvious)
Evidence: Counts are over all 600 shipments (numerator/recipe total):
- StatusEvent: each shipment emits one (556 shipments; 44 accounted_return emit two). Its value is chosen per recipe (generate.py:559-569). IN_TRANSIT occurs only in absent_transfer_receipt and later_hub_departure (17/17). OUT_FOR_DELIVERY occurs only in 5 abnormal recipes (42/42).
- failed_reason: SESSION_CAPACITY_EXHAUSTED marks traffic_safe_return (6/6), RECIPIENT_NOT_REACHED marks unanswered_contact/contractor_unreturned (15/15), ACCESS_NOT_COMPLETED marks the gate/address recipes (generate.py:422).
- observed_gate 'Gate 1' marks different_gate (8/8); every instruction says 'Gate 4' (600/600).
- observation_type DEPOT_DISPATCH_SCAN and source_ref 'synthetic:INCOMPLETE_ACK:depot-dispatch-scan' mark contractor_unconfirmed_pickup (9/9).
- source_ref 'synthetic:carrier-/depot-handover-report' and source_quality ATTRIBUTED_REPORT mark conflicting_custody_sources (9/9; generate.py:407-409).
- Manifest v2 REVISED marks conflicting_manifest (10/10).
- HandoffEvidence recipient_type AUTHORIZED_ALTERNATE, UNVERIFIED_PERSON and OTHER_PERSON each mark one report recipe (6/6 each).
- Auth FAIL marks report_failed_authentication (6/6). PRIOR-* nodes mark report_after_prior_outcome (6/6).
- The barcode mismatch is always the manifest barcode plus '8' at confidence 0.99 (16/16). The weight is always 0.65 x declared (23/24; 0.66 x once).
- AddressVersion v2 (id suffix -ADDR-02) marks the obsolete-address recipes (14/14). It is imported with recorded_at = simulation start (contracts.py:204), so the investigator can see the newer address before the shipment exists.
- later_hub_departure leaks through booking-time plan data: VehicleAssignment is a CONTEXT kind (context.py:13-15) whose linehaul valid_from is +12.0 h versus the plan (6/8), and a '-ACTUAL-SESSION' session id appears (3/8), visible through vehicle_and_manifest (tools.py:205-212).
- All 36 RecipientReports carry the same statement_en (generate.py:499).
- Symptoms nearly name the rule (store.py:43-51). Cases opened with a single-rule symptom (barcode, weight, manifest, conflicting custody) scored 12/13; cases opened with only MILESTONE_OVERDUE scored 5/13.
Impact: For 20 of 24 abnormal recipes, accuracy measures matching a constant rather than reasoning. The hard part of the benchmark is only the MILESTONE_OVERDUE family.
Recommendation: Draw perturbation magnitudes and forms from distributions (barcode substitution or another live label; weight ratio 0.5-1.5). Emit full status histories for every shipment. Stamp plan records at booking time and re-plan only through dated events. Vary report text.

### [dataset] Realism gaps: exclusive resources, no consolidation, single coordinates, zero benign variation
Evidence: - Vehicle calendars are exclusive (generate.py:132): 1,204/1,204 assignments have no overlapping assignment on their vehicle. A last-mile run carries 1.64 parcels on average (max 4), all from one shipment.
- 287 vehicles map to 287 drivers, one to one.
- 450 linehaul assignments each move one shipment (a TRUCK or LHV per parcel lane).
- There are no Container, Pallet, Trip or Cage kinds (contracts.py:126-139). Local hops (origin, sorting, hub, depot) have RECEIVED events but no vehicle.
- Every AddressVersion in a city shares one coordinate (generate.py:188, 199): 1 distinct point per (city, version) across 614 versions.
- Proof coordinates equal the address exactly. report_different_location moves the proof by 0.04 degrees (about 6.0 km) against a 40 m tolerance (generate.py:448-450).
- GPS fixes exist only at the depot (LM-LOAD, LM-END: 600 each) and the destination hub (LINE-ARRIVAL: 450), never en route or at the door (generate.py:536-542).
- Healthy timing has no jitter: 4,512/4,512 non-delivery milestones are observed exactly at plan. Healthy upload lag is 0 min, or 10 min in 177 events (late_upload_within_tolerance).
- Customer communication exists only as a ContactAttempt 5 min before an attempt. OTP vs PIN is chosen by index parity (generate.py:467). There is no OTP issuance or ETA message.
- Designed multi-cause overlap exists only in weight_and_obsolete_address (6). All other overlaps are outage side effects (12 abnormal shipments).
Impact: Detection precision and recall of 1.00 (README section 3) are guaranteed by construction, because no healthy shipment is ever late. Shared-cause reasoning, consolidation-level custody, and misdelivery to a neighbour cannot be represented.
Recommendation: Add stochastic processing and transit times with benign late-within-tolerance cases, multi-shipment driver routes and linehaul consolidation (bags or cages), per-recipient address points with GPS noise, and en-route telemetry.

### [simulator] Physical truth contradicts the generated evidence (causal inconsistencies)
Evidence: - different_weight's truth says the scale is miscalibrated (network.py:101), but only packages[0] is distorted (generate.py:379-380). Within ±2 h on the same scale device, 109 other shipments' parcels read correctly (4 wrong, all other weight recipes), and 10 same-shipment packages read correctly.
- The second vehicle in conflicting_custody_sources is next(any other Vehicle) (generate.py:401). In 9/9 shipments it is a Riyadh LHV linehaul vehicle with no assignment, and in 7/9 the depot is in another city (Khobar, Dhahran, Jubail x2, Jeddah, Dammam, Madinah).
- contractor_* recipes fall back to an SPL employee driver when the shipment is bulky (network.py:137): 10 shipments, 3 in dev (000200, 000310, 000460) plus 1 contractor_unreturned in history (000180).
- 2/9 different_weight shipments (light parcels, |0.35w| <= 0.5 kg) and 1 outage-hit accounted_return are labelled abnormal but never open a case.
- Local absent_transfer_receipt deletes custody and attempts after depot_time but keeps the GPS and the manifest (generate.py:551-558).
Impact: A careful reasoner could correctly argue against the label (the scale is fine; the second report is physically impossible), so correct reasoning is penalised. Truth rows also contain unobservable positives.
Recommendation: Apply a physical fault to everything it causes (all readings on the scale in the drift window), draw conflicting vehicles from the same depot and session, and drop or relabel truth rows whose perturbation produced no evidence.

### [tools] Evidence that discriminates exists in the world but is not retrievable
Evidence: - Heartbeats are generated only for DeliveryDepot handhelds (network.py:534) and INDEPENDENT driver apps (network.py:544-547). Hub, sort and branch handhelds (36 devices) and SPL driver apps have no heartbeats, so device_status returns NO_TELEMETRY (tools.py:246). For intercity absent_transfer_receipt (missing receipt at the destination hub), a hub sync failure therefore cannot be ruled in or out; its truth state is 'received_unscanned' (network.py:106).
- No tool in tools.py:50-61 returns TrafficObservation. traffic_safe_return case 000387 had only the MILESTONE_LATE symptom to go on and answered MISSED_MILESTONE.
- No tool queries other shipments on the same depot handheld or scale, so the one shared mechanism cannot be corroborated across shipments.
Impact: Directly contributes to 000387, and to the DELAYED_SYNC vs CUSTODY_GAP confusion for hub-side gaps.
Recommendation: Emit heartbeats for every handheld and app. Add a route_conditions tool that returns TrafficObservation. Add a same-device/same-facility window query with counts only.

### [evaluation] Acceptable-cause sets are inconsistent with the rule codes and with evidence-identical sibling recipes
Evidence: Truth uses 18 cause names, 4 of which (DELAYED_SYNC, HUB_DELAY, POSSIBLE_MISDELIVERY, ROUTE_DELAY) are not derive.py codes. Inconsistencies:
- CUSTODY_GAP is accepted for partial_packages but not for absent_session_receipt, although partial_packages is absent_session_receipt applied to the last package (generate.py:411) with the same physical state 'returned_unscanned' (network.py:105).
- MISSED_MILESTONE is accepted for later_hub_departure and absent_transfer_receipt, but not for traffic_safe_return, where it fires at opening 4/4, nor for absent_session_receipt (8/8) or partial_packages (6/6).
- PROOF_INSUFFICIENT fires at opening 6/6 for report_different_location but is not acceptable there. It is accepted for report_authorized_alternate, whose proof is valid and where the rule never fires (0/6).
- DELIVERY_DISPUTE fires for every report and is accepted for all 6 report recipes (derive.py:301-305), so the misdelivery and proof distinctions never affect the score.
- contractor_unreturned accepts only UNRECONCILED_CUSTODY, while RECIPIENT_UNAVAILABLE fires 9/9 at opening and is literally true.
- Local later_hub_departure does not accept CUSTODY_GAP, although its evidence-identical sibling, local absent_transfer_receipt, does.
- Outage-only shipments accept only DELAYED_SYNC, while the rule code at opening is CUSTODY_GAP in 7/7 CUSTODY_TRANSFER_UNCONFIRMED-only openings.
5 dev failures are answers that are acceptable for a sibling recipe or equal a firing rule code: 000101 and 000482 (CUSTODY_GAP), 000067 (PROOF_INSUFFICIENT), 000387 (MISSED_MILESTONE), 000400 (local, CUSTODY_GAP).
Impact: Scoring is partly arbitrary. With consistent acceptable sets, the same run scores 31/41 (75.6%). Also crediting answers that are correct for the evidence visible at the single investigation (the 2 contractor_unreturned cases) gives 33/41.
Recommendation: Separate observation codes (MISSED_MILESTONE, CUSTODY_GAP, PROOF_INSUFFICIENT) from mechanism causes (DELAYED_SYNC, HUB_DELAY, LEFT_AT_DEPOT, MISDELIVERY). Score them as two fields, or with partial credit, and derive acceptable sets from physical states so that siblings share them.

### [evaluation] One investigation at opening is scored against a label defined by the whole story
Evidence: Every case was investigated exactly once (41 investigations for 41 cases); 20 cases gained symptoms afterwards and were not re-investigated. Delay from opening until an acceptable cause first becomes a rule code: contractor_unreturned median 9.25 h (9/9); absent_session_receipt 1.0 h (8/8; MILESTONE_OVERDUE is due at session end plus 15 min, UNRECONCILED_CUSTODY at plus 76 min, derive.py:320, 336); partial_packages 1.0 h (6/6). For outage-caught abnormal shipments the delay is 12.75-17 h. Key evidence is defined for only 12 dev shipments; for 7 of them it is the buffered upload (network.py:353, 310), which cannot be ingested until reconnect about 20.7 h later. That is why key_evidence_not_yet_ingested = 7.
Impact: At least 4 dev failures (000187, 000239, 000101, 000482) ask the investigator to predict an end-of-shift outcome. The key-evidence metric cannot be satisfied for DELAYED_SYNC by design.
Recommendation: Re-investigate when symptoms grow and score the latest diagnosis. Alternatively, label each case by the cause supported at its own investigation snapshot.

### [model] Residual investigator failures where the evidence was sufficient
Evidence: Outage cases where the depot handheld was SILENT at opening (162, 855, 684 and 1,030 min) and device_status was called (which device was queried is not recorded in pipeline.json), yet the answer was CUSTODY_GAP: 000431, 000392, 000030, 000017. Clear errors: 000567 (BARCODE_MISMATCH rule at opening; answered INSUFFICIENT_EVIDENCE) and 000029 (partial_packages, depot handheld reporting, other packages delivered; answered DELAYED_SYNC). Degraded runs with no diagnosis: 000262 and 000337. By opening symptom: MILESTONE_OVERDUE-only openings scored 5/13 and single-rule symptoms 12/13.
Impact: 8 of 15 failures sit with the investigator. Of those, 4 are on the observation-vs-mechanism boundary that the taxonomy blurs, so only 4 are plain errors.
Recommendation: Record the device_status arguments in pipeline.json. Add a prompt rule: a missing receipt plus a SILENT handheld at that facility means sync delay, and a missing receipt plus a reporting handheld means a custody gap.

## Tables
### Dev split: recipes, counts, final-run result (f36736b)
| Recipe (dev shipments) | Acceptable | Opening symptoms | Correct / cases |
|---|---|---|---|
| conflicting_manifest (3; 1 outage-hit) | MANIFEST_CONFLICT (+DELAYED_SYNC) | MANIFEST_CUSTODY_CONFLICT; outage-hit: MILESTONE_OVERDUE | 2/3 |
| absent_session_receipt (2) | UNRECONCILED_CUSTODY | MILESTONE_OVERDUE | 0/2 (both CUSTODY_GAP) |
| absent_transfer_receipt (2) | CUSTODY_GAP, MISSED_MILESTONE | MILESTONE_OVERDUE | 1/2 (1 degraded) |
| conflicting_custody_sources (2) | CONFLICTING_CUSTODY | CUSTODY_REPORTS_CONFLICT | 2/2 |
| contractor_unconfirmed_pickup (2) | CUSTODY_GAP, UNRECONCILED_CUSTODY | CUSTODY_TRANSFER_UNCONFIRMED+MO / MO | 2/2 |
| contractor_unreturned (2) | UNRECONCILED_CUSTODY | DELIVERY_ATTEMPT_FAILED | 0/2 (RECIPIENT_UNAVAILABLE) |
| declared_weight_wrong, different_weight, different_barcode (2 each) | WEIGHT/BARCODE_MISMATCH | WEIGHT/BARCODE_READ_DIFFERS | 6/6 |
| wrong_label_applied (2) | BARCODE_MISMATCH | BARCODE_READ_DIFFERS | 1/2 |
| offline_device_sync (2) | DELAYED_SYNC | MILESTONE_OVERDUE | 2/2 |
| outage-converted healthy (contractor_on_time, fulfillment, next_day) | DELAYED_SYNC | MO / CUSTODY_TRANSFER_UNCONFIRMED | 1/3 |
| 13 recipes with 1 shipment each (15 cases) | — | — | 9/15 |
| **Total** | | | **26/41 (Wilson 95% CI 48-76%)** |

### Where the 15 dev failures come from
| Class | Cases | n |
|---|---|---|
| Truth is visible only after the single investigation (median 9.25 h later) | 000187, 000239 (contractor_unreturned) | 2 |
| Answer is accepted for an evidence-identical sibling recipe, or equals a rule code firing at opening | 000101, 000482, 000067, 000387, 000400 | 5 |
| Observation instead of mechanism on outage shipments (CUSTODY_GAP vs DELAYED_SYNC; depot handheld SILENT and retrievable) | 000431, 000392, 000030, 000017 | 4 |
| Plain investigator error | 000567, 000029 | 2 |
| Degraded run, no diagnosis | 000262, 000337 | 2 |

### Separability at case opening (all 204 opened abnormal shipments, 3 splits)
| Measure | Value |
|---|---|
| An acceptable cause is a derive.py rule code at opening | 139/204 (68%) |
| Best single label per identical visible-evidence group (with heartbeat) | 197/204 (96.6%) |
| Same, without heartbeat and status | 195/204 (95.6%) |
| Indistinguishable at opening | contractor_unreturned (9) vs unanswered_contact (6); local later_hub_departure (2) vs local absent_transfer_receipt (1) |
| Identical forever (same cause, different expected resolution) | different_barcode vs wrong_label_applied; different_weight vs declared_weight_wrong |
| Dev accuracy: MILESTONE_OVERDUE-only openings vs single-rule-symptom openings | 5/13 vs 12/13 |

### One-to-one tells (shipments showing the tell / shipments of that recipe, all splits)
| Tell | Recipe |
|---|---|
| StatusEvent IN_TRANSIT (17/17 abnormal) / OUT_FOR_DELIVERY (42/42 abnormal) | absent_transfer, later_hub / 5 custody recipes |
| failed_reason SESSION_CAPACITY_EXHAUSTED 6/6; observed_gate 'Gate 1' 8/8 | traffic_safe_return; different_gate |
| observation_type DEPOT_DISPATCH_SCAN 9/9 | contractor_unconfirmed_pickup |
| source_ref *-handover-report, ATTRIBUTED_REPORT 9/9 | conflicting_custody_sources |
| Manifest v2 REVISED 10/10 | conflicting_manifest |
| Barcode = manifest + '8' at confidence 0.99 (16/16); weight = 0.65 x declared (23/24) | barcode / weight recipes |
| Linehaul VehicleAssignment +12.0 h in booking-time plan (6/8); '-ACTUAL-SESSION' id (3/8) | later_hub_departure |
| AddressVersion v2 visible from simulation start (14/14) | obsolete_address recipes |

### Realism counters
| Item | Value |
|---|---|
| Assignments with another overlapping assignment on the same vehicle | 0/1204 |
| Vehicles : drivers | 287 : 287 |
| Shipments per linehaul assignment | 1 (450 assignments) |
| Distinct address points per (city, version) | 1 |
| Healthy non-delivery milestones observed exactly at plan | 4512/4512 |
| Other parcels read correctly on the 'miscalibrated' scale within ±2 h | 109 (4 wrong) |
| Conflicting-custody second vehicle is a Riyadh LHV / in another city | 9/9 / 7/9 |
| Handhelds with heartbeats | 9 depot handhelds only (36 hub/sort/branch/fulfillment and 18 warehouse handhelds: 0) |


# AUDIT tools-prompt

## Summary
The 26/41 has five separate causes. Three are not mainly the investigating model's fault:
- 5 of the 15 wrong final cases come from evaluation design. 000187 and 000239 are scored against a cause that only became observable hours after the single investigation. 000101, 000482 and 000067 are scored against an answer key that rejects causes the rule engine and the action catalog treat as equivalent.
- 1 case (000387) comes from a tool gap: no tool returns the TrafficObservation that decides it.
- 3 cases are model failures that don't recur: two degraded (failed-closed) investigations and one diagnosis that changed after a REVISE round. All three shipments were correct in the other three runs.

The other 6 are genuine investigator errors. CUSTODY_GAP is the default answer for "parcel not where expected": it was predicted 34 times in 168 case-runs and correct 10 times. Six other codes were never predicted at all, including UNRECONCILED_CUSTODY, which was acceptable 28 times. In every DELAYED_SYNC snapshot, the journey tool names the depot handheld and that handheld reports SILENT, yet the model chose DELAYED_SYNC in only 3 of 9 such cases.

The reviewer works as a check on citations, not on correctness. It sees only the raw cited records (investigator.py:199-201). Comparisons that a tool computed (barcode or weight within tolerance, proof corroboration) are not stored on any record. So it rejects WEIGHT_MISMATCH 18/20 and PROOF_INSUFFICIENT 9/9 in the first round, against 1/19 for DELAYED_SYNC, whose cited device id is rendered as a computed telemetry summary (checks.py:88-89). Across 164 reviewed case-runs it rejected 22.5% of correct diagnoses and 11.3% of wrong ones, and accepted 47 of 53 wrong ones. In the final run, 8 of the 9 cases escalated by "Reviewer rejected" had the correct diagnosis (8 of all 26 correct).

No deterministic code sets or overrides the diagnosis. The safety logic (authority, symptom floor, fact_checks, guard) only removes automatic authority. The only diagnosis-shaping inputs are the symptom names, 10 of 13 of which are renamed rule codes, and the action catalog's "addresses" lists.

The investigator is strictly single-shipment: no other parcels on the same device, driver, vehicle, session, facility or manifest. The only cross-shipment signal is device heartbeats, and 249 of the 303 device ids the tools surface have none. The tool budget never binds (mean 5.1 calls, max 10 reached in 2 of 168 case-runs). Wrong cases did not skip device_status or custody_chain: custody_chain ran in 15/15 wrong final cases, and device_status in 67% of wrong vs 35% of correct ones. What wrong cases skip is vehicle_and_manifest (13/15), the only source of session_end_at.

Run4 and final used identical prompt hashes and the same investigator, tools and checks code, so the 71%→63% drop is model variance. Seven shipments were wrong in all four runs, accounting for 28 of the 57 wrong case-runs; 20 of those 28 are the evaluation and answer-key cases. Fixing only those five cases would give 31/41 (75.6%) with unchanged model behaviour.

Method: per-snapshot claims come from a read-only, in-memory regeneration (generate_live, total=600, DEMO-SUHAIL-LIVE-TEST), replaying the real tools at each case's opened_at. The investigation runs in that same simulated hour (s5_scenarios.py:129-137, store.py:687-692). Gateway ingestion times may differ slightly from the world's recorded_at. Scratch scripts are in C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad (replay.py, replay2.py, trunc.py, review_packet.py, stats.py). No repository files were changed.

### [evaluation] One investigation at the first symptom, scored against a cause that appears later (contractor_unreturned 8/8 wrong)
Evidence: store.py:443-450 adds new symptoms to an open case without requeueing it; store.py:687 claims only OPEN/REOPENED cases; investigations=1 for all 41 final and 42 run4 cases. 20/41 final symptom sets grew after the investigation. SESSION_END_UNRECONCILED is in 0 opening sets and 14 final sets in both run4 and final (DETECTION_ALLOWANCE_SECONDS=900, store.py:26, plus session grace). Replay of 000187 at its snapshot (2026-09-09T06:00, equal to truth last_activity_at): rule codes = [RECIPIENT_UNAVAILABLE], two FAILED/RECIPIENT_NOT_REACHED attempts with NO_RESPONSE contacts, session_end_at 13:00 the same day. The parcel's non-return could not be observed yet. 000239: same pattern with 8 attempts. Base recipe is unanswered_contact (network.py:45), and ACCEPTABLE has no entry for contractor_unreturned (network.py:71-85).
Impact: 2 of the 15 final wrong cases, and 8 of 8 case-runs across runs. The README calls this a misdiagnosis, but at the snapshot RECIPIENT_UNAVAILABLE is the evidence-supported answer.
Recommendation: Re-investigate when a STANDING or human-floor symptom is added (at least SESSION_END_UNRECONCILED and MILESTONE_LATE). Otherwise score each investigation against the cause observable at its own snapshot, and report contractor_unreturned separately until then.

### [evaluation] Answer key disagrees with the rule engine, fact_checks and the action catalog (000101, 000482, 000067)
Evidence: absent_session_receipt accepts only UNRECONCILED_CUSTODY (network.py:60; no ACCEPTABLE entry). partial_packages has the same physical state (returned_unscanned, network.py:105) and accepts {UNRECONCILED_CUSTODY, CUSTODY_GAP} (network.py:83). checks.py:22 treats CUSTODY_GAP as consistent with UNRECONCILED_CUSTODY. Both causes map to the same action, INITIATE_CUSTODY_RECONCILIATION (authority.py:14). 000101 and 000482 were wrong in 8/8 case-runs (CUSTODY_GAP x4, MISSED_MILESTONE x2, DELAYED_SYNC x2). report_different_location (000067): the replayed rule codes at the snapshot include PROOF_INSUFFICIENT (derive.py:310-312). PROOF_INSUFFICIENT is accepted for the three sibling report_* recipes (network.py:74-76) but not here (network.py:73). The model said PROOF_INSUFFICIENT in 4/4 runs.
Impact: 3 of the 15 final wrong cases; 12 of 57 wrong case-runs across runs.
Recommendation: Make ACCEPTABLE consistent with checks.CONSISTENT and with action equivalence: add CUSTODY_GAP to absent_session_receipt and PROOF_INSUFFICIENT to report_different_location. Alternatively tighten CONSISTENT so the safety check and the answer key encode the same taxonomy. Report accuracy both with and without these equivalences.

### [reviewer] Reviewer judges only the raw cited records; tool-computed comparisons are invisible, so correct measurement and proof diagnoses are rejected
Evidence: Reviewer packet = case_symptoms + conclusion + cited_records + deterministic_checks, with visible_evidence_ids = sorted(records) (investigator.py:199-201). REVIEWER_SYSTEM says to check 'against the cited evidence records below' (investigator.py:180-181). The reviewer gets no tool results and no list of retrieved-but-uncited evidence. Reconstructed packet for 000583: the investigator cites only the scan, and the reviewer sees observed_barcode 'DM0000583018' with no manifest barcode, next to a passed check 'evidence rules at this snapshot show BARCODE_MISMATCH'. Proof corroboration reasons are computed in derive.py:70-138 (haversine distance vs accuracy, recipient binding, OTP expiry) and are not on any record. First-round REVISE by predicted cause (4 runs): WEIGHT_MISMATCH 18/20, PROOF_INSUFFICIENT 9/9, BARCODE 7/15, DELIVERY_DISPUTE 5/10, CUSTODY_GAP 14/34, DELAYED_SYNC 1/19, CONFLICTING_CUSTODY 0/8. DELAYED_SYNC is the natural control: a cited device renders as a computed telemetry summary (checks.py:88-89). Citation count does not predict rejection: cited=1 20%, 2 26%, 3 19%, 4 10%, 5+ 19%; run4 rejected cases cited 5.8 on average vs 3.3 for accepted.
Impact: Final: 8 of the 9 'Reviewer rejected' escalations had the correct diagnosis, 8 of the 26 correct (30.8%). Across runs: 25 of 31 such escalations were correct, 8 of those 25 on AUTO-eligible shipments. Discrimination is inverted: 25/111 correct rejected (22.5%) vs 6/53 wrong rejected (11.3%); 47/53 wrong accepted.
Recommendation: Give the reviewer the same computed facts the investigator saw for each cited id: barcode_matches, manifest weight, tolerance_kg, weight_within_tolerance, proof corroborated and reasons, milestone state. Store them as tool-issued comparison records, the way device telemetry summaries already are. Also give it the ids and kinds of retrieved-but-uncited evidence so that 'obvious alternative ignored' can be checked. State in REVIEWER_SYSTEM that a cited comparison record plus a passed rule-consistency check is sufficient support for a measurement cause.

### [prompt] Bare 21-code cause catalog: CUSTODY_GAP becomes the catch-all and 7 codes are never predicted
Evidence: The investigator receives list(CAUSE_CHOICES), names only, no definitions (investigator.py:21,127; agents.py:17-20). Across 168 case-runs: CUSTODY_GAP predicted 34 times, correct 10 (29%) vs 20 acceptable. UNRECONCILED_CUSTODY predicted 0 times though acceptable in 28 case-runs (sole answer in 16). TRAFFIC_DELAY, HUB_DELAY, ROUTE_DELAY, JOURNEY_DELAY, POSSIBLE_MISDELIVERY and SLA_RISK: 0 predictions. MISSED_MILESTONE: 10 predictions, 1 correct. In the final run, 6 of the 7 wrong CUSTODY_GAP diagnoses (000431, 000392, 000101, 000482, 000400, 000030) had no CUSTODY_GAP rule code at the snapshot, and every custody transfer was corroborated ('2/2', corroborated=True in the replayed custody_chain). By rule (derive.py:235-240), a gap means an uncorroborated or discontinuous transfer, not a missing next transfer. SYSTEM's 'typical alternative explanations' (investigator.py:30-36) never mention session end or traffic.
Impact: The largest investigator-side error class: 7 of 13 non-degraded wrong cases in the final run.
Recommendation: Give each code a one-line operational definition plus its discriminating evidence. CUSTODY_GAP: a recorded transfer lacks acknowledgments or a bound source scan, or starts from a holder other than the last corroborated one. UNRECONCILED_CUSTODY: the session ended plus grace with no corroborated delivery or depot return. DELAYED_SYNC: the expected observation is missing and the device that should have made it is SILENT or has pending uploads. MISSED_MILESTONE or HUB_DELAY: overdue, with none of the above. Drop the overlapping codes that have no evidence path in this world (SLA_RISK, ROUTE_DELAY), or mark them 'not diagnosable from shipment evidence'.

### [model] DELAYED_SYNC evidence was reachable and mostly ignored; CUSTODY_GAP faces no deterministic pushback
Evidence: Replay: in 9 snapshots (000431, 000032, 000392, 000113, 000003, 000017, 000120, 000459, 000030) the missing milestone is a RECEIVED at a DeliveryDepot. journey() names that depot's handheld (tools.py:133), and device_status reports it SILENT (3.0-20.0 h since last seen). DELAYED_SYNC is acceptable in 8 of the 9; the model chose it in 3 (113, 003, 120). The four wrong ones (431, 017, 392, 030) all called journey and device_status, then concluded CUSTODY_GAP. Answering DELAYED_SYNC whenever this pattern appears would score 8/9 instead of 5/9 (+3). The fact check is asymmetric: CUSTODY_GAP passes on MISSED_MILESTONE alone (checks.py:22), while DELAYED_SYNC needs a cited late upload or a silent/gapped device (checks.py:56-59). Across 4 runs, the 5 DELAYED_SYNC-only shipments were correct in 7/20 case-runs. 000032 (answer CUSTODY_GAP) is observationally identical to 000431 at the snapshot, so one case in this class is inherently ambiguous.
Impact: 4 of the 15 final wrong cases; the main source of run-to-run flip-flopping (000003, 000113, 000120, 000431, 000017).
Recommendation: Prompt rule: when a missing observation's facility device is SILENT, DELAYED_SYNC must be a hypothesis, refuted only by evidence the device was reporting during the window. Have journey return the telemetry state inline for missing milestones, so the signal sits in the same tool result as the gap. Accept DELAYED_SYNC or REQUEST_DEVICE_SYNC (an evidence-gathering action) for the ambiguous missing-receipt plus silent-handheld class, or score the next evidence action there.

### [tools] TrafficObservation is in the evidence context but no tool returns it (000387 wrong 4/4)
Evidence: OBSERVATIONS includes TrafficObservation (dataset_v2/context.py:9-13), and derive.py:338-343 derives TRAFFIC_DELAY from it. None of the 10 tools in tools.py:50-61 reads it, and the replay counts it as unreachable. 000387 snapshot: TrafficObservation delay_seconds=32400, confidence=0.95 (generate.py:543-547); rule codes [MISSED_MILESTONE, TRAFFIC_DELAY]. The model said MISSED_MILESTONE in 4/4 runs. validate_conclusion requires the primary to cite retrieved evidence (investigator.py:90-92), so TRAFFIC_DELAY could not even be cited with its own evidence. Also unreachable: RouteSegment (228 nodes across the 41 snapshots), RouteMilestone (627), Route (41), StatusEvent history beyond the latest (tools.py:105-110).
Impact: 1 final wrong case; 4 wrong case-runs; TRAFFIC_DELAY and ROUTE_DELAY can never be supported.
Recommendation: Add route conditions (TrafficObservation and the planned segment) to journey, or as a route_conditions tool returning citable ids.

### [tools] Derived values are not citable: scans hides the Package/Policy baselines, vehicle_and_manifest hides Vehicle/Driver, precedents returns no ids
Evidence: scans returns only scan ids (tools.py:174) although each row includes manifest_barcode and manifest_weight_kg from the Package and tolerance_kg from the Policy (tools.py:165-172). vehicle_and_manifest shows vehicle_ownership and driver_employment but cites only assignment and session ids (tools.py:206-213). precedents returns evidence_ids [] (tools.py:283). validate_conclusion needs only one supporting id (investigator.py:90-92). SYSTEM never says the reviewer sees only cited records (investigator.py:23-56). Final mean cited: 3.63 for ACCEPT vs 2.11 for escalated cases; 000441 and 000583 cited one id each and were escalated.
Impact: Feeds the reviewer finding above. Measurement causes, which are 100% correct across runs (WEIGHT 20/20, BARCODE 15/15), lose autonomy because their support cannot be shown to the reviewer.
Recommendation: Have each tool return the ids of every node it reads to compute a displayed value (Package and Policy for scans; Vehicle, Driver and Provider for vehicle_and_manifest; AddressVersion and Shipment for proof binding). Tell the investigator to cite the comparison baseline, and that numbers in the summary must appear in cited records.

### [reviewer] The revision loop discards context, so a REVISE can turn a correct diagnosis into a wrong one
Evidence: MAX_REVIEW_ROUNDS=2 (graph.py:20, after_review graph.py:279-285), i.e. one revision. Round 2 gets a fresh tool belt (graph.py:143-150) and a fresh conversation whose only addition is reviewer_feedback (investigator.py:124-130), capped at 500 chars (investigator.py:215). unsupported_claims is dropped (graph.py:223-224). The round-2 reviewer is not shown its round-1 feedback (investigator.py:199-201). Across runs: REVISE then ACCEPT 22/36 correct (61%), first-round ACCEPT 64/97 (66%), REVISE twice 25/31 (81%). 000567 was BARCODE_MISMATCH in 3/3 other runs; in final it went REVISE then ACCEPT as INSUFFICIENT_EVIDENCE. pipeline.json keeps only last-round tools, without args (s5_scenarios.py:166-180), so round-1 diagnoses cannot be audited.
Impact: Probably 1 final wrong case (000567); the extra round costs a full re-investigation (final run: 416 model calls, 1.9M tokens for 41 cases) with no measurable accuracy gain.
Recommendation: Carry the round-1 conclusion, retrieved records and unsupported_claims into round 2. Give the round-2 reviewer its round-1 feedback and ask whether each point was addressed. Log both rounds' diagnoses, tool args and the reviewer's feedback and unsupported claims in the results.

### [tools] Single-shipment scope; telemetry exists for 18% of the devices the tools name; no facility, driver or vehicle view
Evidence: OWN_NODES selects only holdout_group = the shipment (read_model.py:122-128). SHARED_NODES adds only catalog kinds (read_model.py:129-141). context.py:3-4 'never reads ... another shipment sharing a facility, organization or vehicle'. Manifests are per shipment and per assignment (network.py:265), so no cross-shipment load manifest exists. The only cross-shipment read is device heartbeats (read_model.py:419-429). Heartbeats are generated only for DeliveryDepot handhelds and independent-driver apps while assigned (network.py:534-554). Replay: 303 device ids surfaced across 41 snapshots, 54 with telemetry (DEPOT_HH 41/41, INDEP_APP 13/13, other handhelds 0/187, SPL driver apps 0/62). Heartbeats carry no error codes (connectivity always ONLINE, network.py:532). Each of the 4 handheld outages affected 2 live shipments (DMM: 000392 and 000431, with 000032 at the same depot), but the investigator cannot see that. HUB_DELAY shifts only one shipment by 12 h (generate.py:283), so no hub-backlog evidence exists. Recipient communications are limited to ContactAttempt result and time plus RecipientReport text (tools.py:182-192); LocationPin coordinates are not returned (tools.py:260).
Impact: HUB_DELAY, JOURNEY_DELAY and ROUTE_DELAY have no positive evidence path; DELAYED_SYNC vs CUSTODY_GAP cannot be separated from co-affected shipments; a device_status call on 82% of named devices returns NO_TELEMETRY.
Recommendation: Add a bounded, read-only facility_device_window tool: count of other shipments with overdue expected observations at the same facility or device in the window, as ids only. Make device_status distinguish 'no telemetry stream for this device class' from SILENT. In the generator, create correlated facility-level events (hub backlog affecting several shipments) if HUB_DELAY is meant to be diagnosable.

### [tools] Output truncation hides the rows that matter on multi-package shipments
Evidence: MAX_ROWS=30 (tools.py:16, journey rows[:30] at tools.py:137) and MAX_RESULT_CHARS=6000 (tools.py:77-78). Then CITABLE_EVIDENCE_IDS (up to 80) is appended after the cut, naming rows the model never saw. Replay: journey() without package_id exceeds 6000 chars in 15/41 snapshots and 30 rows in 6/41. Missing milestones are cut off in 000459, 000030 and 000029; the last two are wrong final cases. Per-package calls fit (2389-4079 chars). scans exceeds 6000 chars in 8/41.
Impact: Contributes to 000029 (the one wrong-cause AUTO execution) and 000030.
Recommendation: Sort non-on-time rows first and summarize on-time ones as counts. Default to per-package output when there is more than one package. Never list citable ids for rows removed by truncation.

### [model] Procedural prompt instructions are ignored; the budget never binds; the tool that holds session end is rarely used
Evidence: Final: mean 5.07 calls (median 5, range 3-8; correct 4.85, wrong 5.47). Run4: mean 4.95 (range 2-8). All 4 runs: mean 5.14; MAX_TOOL_CALLS=10 (investigator.py:18) reached in 2/168. First tool: shipment_overview in 149/168. 'Check verified precedents ... before concluding' (investigator.py:28-29) was followed in 4/168. vehicle_and_manifest, the only source of session_end_at (tools.py:211), was used in 23/168 overall and in 1 of the 28 UNRECONCILED_CUSTODY-acceptable case-runs. Wrong cases did not skip device_status or custody_chain: final custody_chain 15/15 wrong vs 23/26 correct, device_status 10/15 vs 9/26; run4 12/12 and 8/12 vs 26/30 and 8/30. They skipped vehicle_and_manifest (final 13/15, run4 12/12) and delivery_attempts (7/13 non-degraded wrong in the final run). Repeated same-tool calls: 22 (final), 17 (run4).
Impact: UNRECONCILED_CUSTODY is never diagnosed; budget and procedure rules add no discrimination.
Recommendation: Remove the precedents instruction, or inject precedents automatically. Make the evidence that decides between causes part of the tools the model already calls first: session_end_at and reconciliation state in custody_chain, telemetry state in journey.

### [detection] No deterministic code sets or overrides the diagnosis; it is shaped only by input framing (symptom names, action catalog)
Evidence: The case result is built only from the model's hypotheses (graph.py:60-82). The proposal uses the model's primary_cause and recommended_action (graph.py:185-194). fact_checks, authorize and symptom_floor only remove AUTO (checks.py:46-74, authority.py:48-94, graph.py:255-265). The guard checks evidence binding and GPS only (worker.py:9-21). default_action and agents.validate_investigation (which restricts the diagnosis to rule codes, agents.py:96-100) are not on the S5 path; S5 wires operations.investigator (s5_scenarios.py:276-278). Diagnosis-shaping inputs: the monitor's SYMPTOMS table renames rule codes (store.py:43-51). 10 of 13 symptoms come from one rule code, and the symptom names are the investigator's only problem statement (investigator.py:126). accounting.json: 17/22 (77.3%) correct when an opening symptom names an acceptable cause vs 9/19 (47.4%) otherwise; primary equals an opening symptom's rule code in 24 cases (20 correct, 4 wrong). The investigator also sees each action's 'addresses' cause list and its authority class (investigator.py:128).
Impact: About half of the measured accuracy is symptom-name lookup. The safety logic is legitimate and is not a source of errors, apart from the permissive CUSTODY_GAP consistency rule noted above.
Recommendation: Keep symptoms observational but make the decisive ones (MILESTONE_OVERDUE, CUSTODY_TRANSFER_UNCONFIRMED) less label-like, e.g. include the missing predicate and facility type instead of a cause-shaped name. Remove 'addresses' from the investigator input so the action catalog does not double as a cause taxonomy. Keep reporting named vs not-named accuracy.

### [model] Fail-closed degradation and run-to-run variance at identical prompts
Evidence: ATTEMPTS_PER_TURN=2 (investigator.py:20,134-157): two invalid replies in one turn end the whole investigation. Final: 2 degraded (000262, 000337), with 0 failed provider calls in the provenance, so these were validation failures. Both shipments were correct in 3/3 other runs (DELIVERY_DISPUTE; CUSTODY_GAP). Run4 and final share prompt hashes (inv b86db16097bb, rev ed2e6a2b66a9), and investigator.py, tools.py and checks.py last changed in 58df781, before 154dd3e. Accuracy: 28/42, 27/43, 30/42, 26/41.
Impact: 2 final wrong cases; about ±4 cases of noise per run, which is larger than most single fixes.
Recommendation: Keep the conversation going after a validation error on a tool-call turn (only a final conclude should fail closed). Log the validation_error per degraded case. Report the mean and range over 3 or more runs and per-shipment stability, not a single run.

### [evaluation] Results lack the fields needed to separate investigator from reviewer errors
Evidence: pipeline.json 'tools' and 'tool_calls' come from the last investigation round only, with no arguments (s5_scenarios.py:166-180). No round-1 primary_cause, no reviewer feedback or unsupported_claims, no investigation as_of, no degraded validation_error. Which device each device_status call queried (the key question for 000431/017/392/030) is not recorded.
Impact: Reviewer-induced flips (likely 000567) and wrong-device queries cannot be proven from committed results.
Recommendation: Record per round: tool name, args and returned id count; the conclusion; the reviewer verdict, feedback and unsupported_claims; the snapshot as_of; and any validation_error.

## Tables
### Final run (f36736b): why each of the 15 wrong cases was wrong

| Case | Recipe | Model said | Acceptable | Category | Evidence at snapshot (replay) |
|---|---|---|---|---|---|
| 000187 | contractor_unreturned | RECIPIENT_UNAVAILABLE | UNRECONCILED_CUSTODY | Evaluation timing | Rule codes [RECIPIENT_UNAVAILABLE]; session ends 7 h after the investigation; never re-investigated |
| 000239 | contractor_unreturned | RECIPIENT_UNAVAILABLE | UNRECONCILED_CUSTODY | Evaluation timing | Same pattern, 8 attempts with NO_RESPONSE |
| 000101 | absent_session_receipt | CUSTODY_GAP | UNRECONCILED_CUSTODY | Answer key (plus investigator) | CUSTODY_GAP is accepted for partial_packages and maps to the same action; vehicle_and_manifest not called |
| 000482 | absent_session_receipt | CUSTODY_GAP | UNRECONCILED_CUSTODY | Answer key (plus investigator) | Same as 000101 |
| 000067 | report_different_location | PROOF_INSUFFICIENT | DELIVERY_DISPUTE, POSSIBLE_MISDELIVERY | Answer key | PROOF_INSUFFICIENT is a rule code at the snapshot |
| 000387 | traffic_safe_return | MISSED_MILESTONE | TRAFFIC_DELAY, ROUTE_DELAY | Tool gap | TrafficObservation (32,400 s, confidence 0.95) is returned by no tool |
| 000431 | fulfillment (outage-affected) | CUSTODY_GAP | DELAYED_SYNC | Investigator | Depot handheld SILENT 3.5 h; called journey and device_status |
| 000017 | next_day (outage-affected) | CUSTODY_GAP | DELAYED_SYNC | Investigator | Depot handheld SILENT 18 h; called journey and device_status |
| 000392 | conflicting_manifest | CUSTODY_GAP | DELAYED_SYNC, MANIFEST_CONFLICT | Investigator | Depot handheld SILENT 14.5 h; manifest revision not yet visible |
| 000030 | report_failed_authentication | CUSTODY_GAP | DELAYED_SYNC, DELIVERY_DISPUTE, PROOF_INSUFFICIENT | Investigator | Depot handheld SILENT 11.5 h; 1 missing milestone hidden by journey truncation |
| 000400 | later_hub_departure | CUSTODY_GAP | HUB_DELAY, JOURNEY_DELAY, MISSED_MILESTONE | Investigator | All transfers corroborated; no CUSTODY_GAP rule code |
| 000029 | partial_packages | DELAYED_SYNC | CUSTODY_GAP, UNRECONCILED_CUSTODY | Investigator (plus truncation) | Depot handheld REPORTING; missing milestone cut from journey(); delayed-sync check still passed, leading to a wrong automatic action |
| 000567 | wrong_label_applied | INSUFFICIENT_EVIDENCE | BARCODE_MISMATCH | Reviewer loop (probable) | Revised once, then accepted; BARCODE_MISMATCH in 3/3 other runs |
| 000262 | report_authorized_alternate | none (degraded) | DELIVERY_DISPUTE, PROOF_INSUFFICIENT | Model output failure | Correct in 3/3 other runs |
| 000337 | absent_transfer_receipt | none (degraded) | CUSTODY_GAP, MISSED_MILESTONE | Model output failure | Correct in 3/3 other runs |

Totals by category: evaluation and answer key 5, tool gap 1, investigator 6, reviewer loop 1, degraded 2. Fixing only the evaluation and answer-key cases gives 31/41 (75.6%).

### Reviewer outcome vs correctness (4 runs, 164 reviewed case-runs)

| Path | Case-runs | Correct | Mean cited ids | Mean tool calls |
|---|---|---|---|---|
| Accepted in round 1 | 97 | 64 (66%) | 3.38 | 5.41 |
| Revised, then accepted | 36 | 22 (61%) | 3.61 | 5.11 |
| Revised twice, escalated | 31 | 25 (81%) | 3.16 | 4.32 |

- **Rejection rate:** 22.5% of correct diagnoses vs 11.3% of wrong ones.
- **Wrong diagnoses accepted:** 47 of 53.
- **Final run:** 8 of the 9 "Reviewer rejected" escalations were correct, which is 8 of the 26 correct diagnoses.

### First-round REVISE rate by predicted cause (4 runs)

| Cause | Reviewed | First-round REVISE | Escalated after second REVISE |
|---|---|---|---|
| WEIGHT_MISMATCH | 20 | 18 | 12 |
| PROOF_INSUFFICIENT | 9 | 9 | 6 |
| BARCODE_MISMATCH | 15 | 7 | 3 |
| DELIVERY_DISPUTE | 10 | 5 | 3 |
| CUSTODY_GAP | 34 | 14 | 4 |
| DELAYED_SYNC | 19 | 1 | 0 |
| CONFLICTING_CUSTODY | 8 | 0 | 0 |

By number of cited ids, the escalation rate is flat: 1 id 20%, 2 ids 26%, 3 ids 19%, 4 ids 10%, 5+ ids 19%.

### Tool use: share of cases that called each tool

| Tool | Final, correct (n=26) | Final, wrong (n=15) | Run4, correct (n=30) | Run4, wrong (n=12) |
|---|---|---|---|---|
| shipment_overview | 88% | 87% | 97% | 100% |
| journey | 58% | 87% | 60% | 92% |
| custody_chain | 88% | 100% | 87% | 100% |
| scans | 69% | 67% | 67% | 58% |
| delivery_attempts | 35% | 47% | 33% | 67% |
| vehicle_and_manifest | 12% | 13% | 13% | 0% |
| device_status | 35% | 67% | 27% | 67% |
| address_and_instructions | 27% | 27% | 27% | 17% |
| policy | 12% | 7% | 20% | 0% |
| precedents | 4% | 0% | 7% | 0% |
| Mean calls | 4.85 | 5.47 | 4.80 | 5.33 |

### Predicted vs acceptable causes (168 case-runs)

| Cause | Predicted | Correct | Acceptable in | Only acceptable cause in |
|---|---|---|---|---|
| CUSTODY_GAP | 34 | 10 | 20 | 0 |
| DELAYED_SYNC | 19 | 12 | 36 | 20 |
| RECIPIENT_UNAVAILABLE | 12 | 4 | 4 | 4 |
| MISSED_MILESTONE | 10 | 1 | 12 | 0 |
| PROOF_INSUFFICIENT | 9 | 5 | 14 | 0 |
| UNRECONCILED_CUSTODY | 0 | 0 | 28 | 16 |
| TRAFFIC_DELAY, ROUTE_DELAY, HUB_DELAY, JOURNEY_DELAY, POSSIBLE_MISDELIVERY | 0 | 0 | 4 each | 0 |

### What the investigator can and cannot see

| Question | Can it see it? | Where |
|---|---|---|
| Other parcels on the same device, driver, vehicle, session, facility or manifest | No | read_model.py:122-128; context.py:3-4; manifests are per shipment (network.py:265) |
| Device heartbeat history | Yes, but heartbeats exist only for depot handhelds and independent-driver apps (54 of 303 named devices); no error codes | tools.py:223-252; network.py:534-554 |
| Facility backlog | No (not in the dataset either) | generate.py:283 |
| Recipient communications | Contact result and time, recipient report text, location pin times (no coordinates) | tools.py:182-192, 260 |
| Traffic and route segments, status history | No tool returns them | tools.py:50-61 |
| Session end time | Only through vehicle_and_manifest (called in 1 of 28 relevant case-runs) | tools.py:211 |
| Rule codes and fact checks | Not shown to the investigator; applied after it concludes | checks.py:1-6 |


# AUDIT evaluation

## Summary
Across the four S5 runs (168 scored cases, 39 shipments, same data), the errors are mostly systematic rather than random. 17 shipments were right in every run, 7 were wrong in every run and 15 flipped between runs. The 7 always-wrong shipments produce 28 of the 56 first-case errors, and in every run the agent gave the same kind of answer for them. None of these 7 failures is model noise. I rebuilt the monitor offline (scratchpad replica.py), and it reproduces the final run's opening time and symptom set for 39 of 39 shipments. That replica shows that contractor_unreturned (8/8 wrong) has its truth label's signal appear 9 hours after the investigation snapshot. absent_session_receipt and partial_packages (12/12 wrong) are judged 12 seconds after the session grace ends, and they are scored against inconsistent acceptable sets. traffic_safe_return (4/4 wrong) needs a TrafficObservation that no investigator tool returns. report_different_location (4/4 wrong) is answered PROOF_INSUFFICIENT, which the evidence rules also flag for that shipment and which three sibling recipes accept. Real model error is concentrated in the DELAYED_SYNC family: the handheld was silent for 3 to 20 hours at the snapshot in all 8 sync-acceptable final cases, and device_status was called in 32 of 36 such cases pooled, but the model concluded DELAYED_SYNC only 12 times. CUSTODY_GAP is its default answer (34 predictions, 10 correct). The agent beats a symptom-only baseline (26 vs 22 of 41 in the final run, 111 vs 92 of 168 pooled) but loses to simply reporting the monitor's own rule code at the snapshot (28 of 41 final, 116 of 168 pooled). The only class it wins over that rule-code baseline is DELAYED_SYNC. On opening symptom sets that determine one acceptable label the agent scores 15/19, below the symptom baseline's 18/19; on ambiguous sets it scores 11/22 against 4/22 for the symptom baseline and 9/22 for the rule-code baseline. MILESTONE_OVERDUE alone opens 13 of 41 cases and maps to 9 distinct root causes across the 204 abnormal shipments of the 600-shipment world. The reviewer is not informative about correctness: ACCEPT is right 86/133 times and the final REVISE is right 25/31 times, and the deterministic fact check flagged 0 of 164 non-degraded diagnoses (53 of them wrong). Rescoring with labels that are knowable at the snapshot moves final accuracy from 26/41 to 31/41 and pooled accuracy from 111/168 to 131/168, so roughly a third of the measured error comes from evaluation design. Scripts and outputs are in C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad (replica.py, snapshot.py, analyze.py, analyze2.py, decomp.py, lag.py, replica.json, snapshot.json).

### [evaluation] Labels describe a later state than the one the investigator sees; the diagnosis is never redone when new symptoms arrive
Evidence: The case is investigated in the same 1-hour tick it opens (scripts/s5_scenarios.py:131-139). Later symptoms are merged into the open case without a re-claim (chat/operations/store.py:443-449). The offline replica reproduces 39/39 opening times and symptom sets. contractor_unreturned (000187, 000239): at the snapshot the evidence is 2 or 4 FAILED RECIPIENT_NOT_REACHED attempts with NO_RESPONSE contacts and rule code RECIPIENT_UNAVAILABLE (derive.py:296). UNRECONCILED_CUSTODY appears 9 h later (derive.py:337). That evidence pattern is identical to 000553 (unanswered_contact, truth RECIPIENT_UNAVAILABLE, 4/4 correct) apart from vehicle ownership PRIVATE vs COMPANY. absent_session_receipt (000101, 000482) and partial_packages (000029) are investigated at 14:00:12, 12 s after session end 13:00 + 3600 s grace; the monitor's UNRECONCILED_CUSTODY only appears at 15:00 (+1 h). In the final run, 7 of 15 wrong cases gained a symptom whose single rule code is an acceptable cause after the diagnosis was made (000029, 000030, 000101, 000187, 000239, 000392, 000482).
Impact: Accounts for 16 of 57 pooled errors (8 contractor_unreturned plus 8 CG/MM answers on the session-receipt recipes) and for all 5 of the always-wrong shipments in these recipes. contractor_unreturned scores 0/8 although the model's answer equals the monitor's own rule code at the snapshot.
Recommendation: Score each run against labels derivable at its evidence_as_of: derive.assess_shipment at that time plus the outage state for DELAYED_SYNC. Alternatively, re-investigate on SYMPTOMS_UPDATED (store.py:445-448) and score the last run. Report snapshot-time accuracy and eventual-cause accuracy separately.

### [dataset] Inconsistent acceptable-cause sets across recipes that share the same mechanism
Evidence: network.py:71-85: partial_packages accepts {UNRECONCILED_CUSTODY, CUSTODY_GAP}, but absent_session_receipt has no ACCEPTABLE entry and falls back to {UNRECONCILED_CUSTODY}, although both are generated by the same branch (generate.py:411) with the same PHYSICAL 'returned_unscanned' and resolution AUTO. MISSED_MILESTONE is accepted for absent_transfer_receipt and later_hub_departure but not for traffic_safe_return or absent_session_receipt. PROOF_INSUFFICIENT is accepted for report_failed_authentication, report_photo_only and report_authorized_alternate but not for report_different_location, where the evidence rules at the snapshot (no allowance) return CUSTODY_GAP, DELIVERY_DISPUTE and PROOF_INSUFFICIENT. The model answered PROOF_INSUFFICIENT on 000067 in 4/4 runs and CUSTODY_GAP on 000101/000482 in 4 of 8 runs.
Impact: Final run: +2 (000101, 000482) under partial_packages' set and +1 (000067), so 26 becomes 29/41 from set consistency alone. Combined with snapshot-time labels: 31/41 final, 131/168 pooled.
Recommendation: Derive ACCEPTABLE from the rule-code family that each recipe actually triggers. Add CUSTODY_GAP to absent_session_receipt. Either add PROOF_INSUFFICIENT to report_different_location or score it as a partial match, with POSSIBLE_MISDELIVERY as the specific answer.

### [tools] Traffic evidence is visible to the monitor but not to the investigator
Evidence: generate.py:543-547 creates a TrafficObservation (delay 32,400 s, confidence 0.95) for traffic_safe_return. derive.py:338-343 turns it into the TRAFFIC_DELAY rule code, which is the replica's opening code for 000387 (MISSED_MILESTONE + TRAFFIC_DELAY, shown as MILESTONE_LATE). The InvestigationTools CATALOG (tools.py:50-61) has no tool that reads TrafficObservation; reasoning.py:98 reads it only in deterministic triage. The agent answered MISSED_MILESTONE 4/4; B_rulecode gets it right.
Impact: Always wrong: 4 pooled errors and 1 in the final run. In the 600-world all 4 MILESTONE_LATE + MILESTONE_OVERDUE openings are TRAFFIC_DELAY, so every traffic case fails.
Recommendation: Extend journey or vehicle_and_manifest to return TrafficObservation rows on the shipment's segments (segment_id, delay_seconds, confidence, window), or add a route_conditions tool.

### [model] The model often misses DELAYED_SYNC and defaults to CUSTODY_GAP, even though the distinguishing telemetry was available
Evidence: In all 8 final cases where DELAYED_SYNC is acceptable, the outage handheld was silent at the snapshot for 20 h (000003), 18 h (000017), 3 h (000113), 5 h (000120), 3.5 h (000431), 11.5 h (000030), 14.5 h (000392) and 7 h (000459). journey also returns that milestone's facility_handheld (tools.py:133). Pooled over 36 sync-acceptable cases, device_status was called 32 times but DELAYED_SYNC was concluded only 12 times. The model also said DELAYED_SYNC 7 times on shipments with no outage (000029 ×2, 000032 ×2, 000101, 000482, 000404). CUSTODY_GAP precision is 10/34 pooled and 3/10 in the final run. MISSED_MILESTONE precision is 1/10. The 8 sync-family shipments make up the core of the flaky set: 14/32 correct.
Impact: 17 + 7 = 24 of 57 pooled errors (42%) and 5 of 15 final errors are DELAYED_SYNC confusions. This is the main genuine model limitation.
Recommendation: Make the reasoning step explicit in the prompt: for a missing_after_deadline milestone, call device_status on its facility_handheld and conclude DELAYED_SYNC when the device is SILENT before the milestone deadline. Add the device id and its state to the conclusion schema so the reviewer can check it.

### [simulator] Hourly ingestion makes ordinary records look 60+ minutes late, so the DELAYED_SYNC check passes on almost any citation
Evidence: Live ingestion stamps recorded_at with the tick time (ingestion.py:119), and the runner ticks every 3600 s (s5_scenarios.py:131). Measured over 3,934 non-outage custody, scan and attempt feed records: 2,420 (61.5%) get an apparent lag of 60-69 min, which crosses LATE_UPLOAD_MINUTES=60 (checks.py:25). That is enough for _late_or_silent (checks.py:28-42) to report a delayed upload. tools.py:89 also shows this upload_lag_minutes to the model. Example: 000029 (partial_packages, no outage) was diagnosed DELAYED_SYNC, passed the check, got AUTO authority, REQUEST_DEVICE_SYNC was executed, and verification failed (final/accounting.json).
Impact: The deterministic guard against unsupported DELAYED_SYNC has close to no power, and the model sees a misleading lag signal. This is consistent with the 7 DELAYED_SYNC false positives and with the 1 automatic action on a wrong cause.
Recommendation: Compute lag from the provider's deliver_at, not the ingestion tick, or tick at 5 min or less in the scenario runner. Require DELAYED_SYNC to cite a SILENT device that equals action_target's expected facility_handheld (graph.py:89-97), not just any lag of 60 min or more or any gap of 4 h or more.

### [reviewer] The reviewer verdict and the fact check do not separate right from wrong diagnoses
Evidence: Pooled: ACCEPT was right in 86 of 133 cases (64.7%); a final REVISE was right in 25 of 31 (80.6%). REVISE caught 6 of 53 wrong non-degraded diagnoses and rejected 25 of 111 correct ones, 12 of them REQUEST_REWEIGH. Final run: 12 of 13 wrong non-degraded diagnoses were ACCEPTed; 8 of 26 correct ones ended REVISE. Two-round ACCEPTs were correct 22/36 vs 66% for one-round ACCEPTs, so revision rounds did not improve accuracy. fact_check_unsupported was False on 164/164 non-degraded diagnoses because CONSISTENT (checks.py:14-23) treats CUSTODY_GAP, DELAYED_SYNC, HUB_DELAY, ROUTE_DELAY, JOURNEY_DELAY and SLA_RISK as consistent with any MISSED_MILESTONE. 000400 (custody fully corroborated up to the hub) passed as CUSTODY_GAP.
Impact: Reviewer behaviour lowers autonomy (9 correct proposals escalated in the final run) without catching errors. At least 7 accepted final errors contradicted the snapshot evidence (000017, 000029, 000030, 000392, 000400, 000431, 000567).
Recommendation: Make CONSISTENT require the primary cause's own rule code, or a SILENT expected handheld for DELAYED_SYNC, instead of the MISSED_MILESTONE catch-all. Give the reviewer the snapshot rule codes and device_reports as facts. Measure reviewer recall and precision per run as a gate metric.

### [evaluation] A plain rule-code baseline matches or beats the agent; the symptom baseline does not
Evidence: Final, same 41 cases: agent 26, B_symptom 22, B_strict 20, B_rulecode 28 (the monitor's exception code at opened_at, which store.py:72-75 maps to symptoms and hides from the investigator, investigator.py:126). Pooled 168: agent 111, B_symptom 92, B_rulecode 116; B_rulecode beats the agent in run2 (29 vs 28), run3 (30 vs 27) and final (28 vs 26), and loses in run4 (29 vs 30). The agent wins over B_rulecode only on 000003, 000113, 000120 (DELAYED_SYNC) and 000459. On opening sets that determine one label: agent 15/19, B_symptom 18/19, B_rulecode 19/19. On ambiguous sets: agent 11/22, B_symptom 4/22, B_rulecode 9/22.
Impact: The 63% headline hides the fact that the agent adds about +11 points over symptom names and −3 points relative to the deterministic engine. Its only systematic value-add is reading telemetry for DELAYED_SYNC.
Recommendation: Report B_symptom and B_rulecode next to agent accuracy in scoring_transparency (s5_scenarios.py:555-620). Split accuracy into determined and ambiguous opening sets.

### [evaluation] Opening-symptom ambiguity is concentrated in MILESTONE_OVERDUE and DELIVERY_ATTEMPT_FAILED
Evidence: Final: MILESTONE_OVERDUE alone opens 13/41 cases with 6 distinct truth causes (agent 5/13). In the 600-shipment world it opens 70 of 204 abnormal shipments with 9 root causes; the best single label (DELAYED_SYNC) covers only 35/70. DELIVERY_ATTEMPT_FAILED: 29 shipments with 4 causes, and the most frequent (UNRECONCILED_CUSTODY, 9) is not observable at opening. Best opening-symptom-set → label classifier: 146/204 (71.6%); best rule-code-set classifier: 160/204 (78.4%).
Impact: 22 of 41 final cases are genuinely ambiguous from the symptoms; the remaining 19 are effectively given away by the symptom name.
Recommendation: Increase n for the MILESTONE_OVERDUE family (DELAYED_SYNC, HUB_DELAY, CUSTODY_GAP, UNRECONCILED_CUSTODY) and report accuracy on that family as the primary investigation metric.

### [model] Run-to-run variance at temperature 0 is about ±2 shipments; investigator prompts and data were unchanged across the runs
Evidence: _llm.py:132 sets temperature=0. run4 and final have identical prompt hashes (b86db160…, ed2e6a2b…) and identical manifest and truth hashes. Between 154dd3e and f36736b, investigator.py, tools.py and checks.py did not change, and graph.py changed only in status text and the non-agent branch. First-case accuracy per shipment: 26, 23, 27, 24 of 39. Only 21/39 shipments got the same primary label in all 4 runs. Outcome flips between consecutive runs: 7, 6, 7.
Impact: The README's 63-71% spread is provider-side nondeterminism, not code effects. A single run cannot resolve differences smaller than about 4 shipments (10 points).
Recommendation: Run at least 3 repetitions per commit and report mean and range per shipment, plus the always-wrong and flaky lists.

### [evaluation] Case-level scoring double-counts easy shipments, and per-shipment acceptable sets credit causes that were not yet evidenced
Evidence: 000415 and 000466 have 2 cases in every run (8 of 168 cases, all correct) because the address-confirmation simulator closes the first case before redelivery. Final: 26/41 (63.4%) case-level vs 24/39 (61.5%) by first case per shipment; run3: 27/43 vs 23/39. Second cases exist only when the first action resolved: 000392 became a separate MANIFEST case in run3 and run4 after a DELAYED_SYNC resolution, but in the final run the MANIFEST_CUSTODY_CONFLICT symptom was absorbed and never investigated. 000459 was credited for CUSTODY_GAP at 09-10T17:00, although its own CUSTODY_GAP rule code appears 15 h later and the only issue visible at the snapshot was the MAK handheld outage. 000030 and 000392 could only be right via the second-cause DELAYED_SYNC credit (their primary signals appear +17 h and +15 h). That credit applied in 1, 2, 2 and 0 cases per run. Degraded runs (4 pooled; 000262 and 000337 in the final run) are scored as wrong (s5_scenarios.py:203-205), although each shipment was correct in every non-degraded run.
Impact: Denominators of 41-43 depend on simulator outcomes; which label is correct for a case depends on timing that the per-shipment set does not encode.
Recommendation: Score per case with a snapshot-specific label, report first-case-per-shipment accuracy as the headline, and report degraded runs as a separate reliability rate.

### [evaluation] The key-evidence metric cannot evaluate DELAYED_SYNC investigations
Evidence: All 7 final cases with key_evidence_not_yet_ingested=True (000003, 000017, 000113, 000120, 000392, 000431, 000459) are outage cases. Their key_evidence is the buffered receipts themselves (network.py:349-351 and the propagate_outages conversion), which cannot be visible before the device reconnects. The real evidence is the DeviceHeartbeat silence, which this metric does not count.
Impact: The 5/5 key-evidence-cited figure covers only the non-sync cases, so there is no evidence-correctness measurement for the hardest class.
Recommendation: For buffered-upload cases, define key evidence as the expected facility_handheld's heartbeat series at the snapshot and check that device_status cited it.

### [prompt] Cause codes are given to the model without definitions, so it is never told the distinctions the scoring enforces
Evidence: investigator.py:127 sends cause_codes as a bare list of 21 codes (agents.py:17-20); the SYSTEM prompt (investigator.py:23-56) defines none of them. Confused pairs in the data: CUSTODY_GAP vs UNRECONCILED_CUSTODY vs MISSED_MILESTONE vs HUB_DELAY vs DELAYED_SYNC. 000400 (later_hub_departure, chain corroborated to the hub, no departure) got CUSTODY_GAP in 3/4 runs; CUSTODY_GAP precision is 10/34.
Impact: Part of the 29 pooled model errors is probably taxonomy confusion rather than evidence misreading.
Recommendation: Add one-line operational definitions for each cause code, especially the milestone family (e.g. HUB_DELAY: last corroborated holder is a hub and its departure milestone is overdue; CUSTODY_GAP: a transfer lacks acknowledgments or the source of a later transfer differs from the last corroborated holder).

### [dataset] Small, unbalanced sample: one shipment equals 2.6 points
Evidence: 39 shipments across 27 recipes; 17 recipes have n=1 in the live split. Three of them are 'healthy' recipes relabelled to DELAYED_SYNC by propagate_outages (000003 contractor_on_time, 000017 next_day, 000431 fulfillment; network.py:307-311), so recipe names in the tables are misleading. Three more carry a second-cause DELAYED_SYNC (000030, 000392, 000459; network.py:303-306).
Impact: The per-recipe conclusions for the n=1 recipes (traffic, later_hub, report_different_location, partial_packages) rest on a single shipment each; the 600-world census (204 abnormal) is needed for ambiguity estimates.
Recommendation: Evaluate diagnosis on the held-out split as well, and on more live-split shipments for the MILESTONE_OVERDUE family; label converted shipments as such in the case rows.

## Tables
### A. Run-level accuracy (same 39 abnormal shipments; investigator/reviewer prompt hashes b86db160…/ed2e6a2b… identical in run4 and final; temperature=0, chat/llm/pipeline/_llm.py:132)
| Run | Cases | Agent (case-level) | First case per shipment | Excl. degraded | B_symptom | B_rulecode |
|---|---|---|---|---|---|---|
| run2 | 42 | 28 (66.7%) | 26/39 | 28/42 | 23 | 29 |
| run3 | 43 | 27 (62.8%) | 23/39 | 27/41 | 24 | 30 |
| run4 | 42 | 30 (71.4%) | 27/39 | 30/42 | 23 | 29 |
| final | 41 | 26 (63.4%) | 24/39 | 26/39 | 22 | 28 |
| pooled | 168 | 111 (66.1%) | 100/156 | 111/164 | 92 (54.8%) | 116 (69.0%) |

The extra cases come from 000415 and 000466 being counted twice in every run (premature closure), plus 000030 in run2/run3 and 000392 in run3/run4.

### B. Per shipment, first case each run (run2 / run3 / run4 / final). + correct, - wrong, D degraded. Multi-case cells show all cases.
| Shipment | Recipe (truth) | r2 | r3 | r4 | fin | Class | Labels when wrong |
|---|---|---|---|---|---|---|---|
| 000060 | conflicting_custody_sources | + | + | + | + | always-correct | |
| 000100 | different_barcode | + | + | + | + | always-correct | |
| 000215 | different_weight | + | + | + | + | always-correct | |
| 000249 | report_photo_only | + | + | + | + | always-correct | |
| 000299 | different_weight | + | + | + | + | always-correct | |
| 000305 | declared_weight_wrong | + | + | + | + | always-correct | |
| 000324 | conflicting_custody_sources | + | + | + | + | always-correct | |
| 000326 | conflicting_manifest | + | + | + | + | always-correct | |
| 000362 | report_with_corroboration | + | + | + | + | always-correct | |
| 000397 | weight_and_obsolete_address | + | + | + | + | always-correct | |
| 000415 | different_gate | ++ | ++ | ++ | ++ | always-correct | |
| 000441 | wrong_label_applied | + | + | + | + | always-correct | |
| 000466 | obsolete_address | ++ | ++ | ++ | ++ | always-correct | |
| 000530 | declared_weight_wrong | + | + | + | + | always-correct | |
| 000532 | conflicting_manifest | + | + | + | + | always-correct | |
| 000553 | unanswered_contact | + | + | + | + | always-correct | |
| 000583 | different_barcode | + | + | + | + | always-correct | |
| 000003 | contractor_on_time→DELAYED_SYNC | - | - | + | + | flaky 2/4 | CG, CG |
| 000017 | next_day→DELAYED_SYNC | + | - | - | - | flaky 1/4 | CG ×3 |
| 000030 | report_failed_auth (+sync) | +- | ++ | - | - | flaky 2/4 | CG |
| 000032 | absent_transfer_receipt | + | - | - | + | flaky 2/4 | DS ×2 |
| 000113 | offline_device_sync | - | D | - | + | flaky 1/4 | CG ×2 |
| 000120 | offline_device_sync | - | - | + | + | flaky 2/4 | CG ×2 |
| 000262 | report_authorized_alternate | + | + | + | D | flaky 3/4 | degraded |
| 000337 | absent_transfer_receipt | + | + | + | D | flaky 3/4 | degraded |
| 000389 | report_after_prior_outcome | + | D | + | + | flaky 3/4 | degraded |
| 000392 | conflicting_manifest (+sync) | - | ++ | ++ | - | flaky 2/4 | CG ×2 |
| 000400 | later_hub_departure | - | - | + | - | flaky 1/4 | CG ×3 |
| 000404 | contractor_unconfirmed_pickup | - | + | + | + | flaky 3/4 | DS |
| 000431 | fulfillment→DELAYED_SYNC | + | - | - | - | flaky 1/4 | CG ×3 |
| 000459 | contractor_unconfirmed_pickup (+sync) | + | - | + | + | flaky 3/4 | MM |
| 000567 | wrong_label_applied | + | + | + | - | flaky 3/4 | INSUFFICIENT_EVIDENCE |
| 000029 | partial_packages | - | - | - | - | always-wrong | see C |
| 000067 | report_different_location | - | - | - | - | always-wrong | see C |
| 000101 | absent_session_receipt | - | - | - | - | always-wrong | see C |
| 000187 | contractor_unreturned | - | - | - | - | always-wrong | see C |
| 000239 | contractor_unreturned | - | - | - | - | always-wrong | see C |
| 000387 | traffic_safe_return | - | - | - | - | always-wrong | see C |
| 000482 | absent_session_receipt | - | - | - | - | always-wrong | see C |

Totals: 17 always-correct, 15 flaky, 7 always-wrong. If every shipment had the pooled p=0.641 independently, you would expect 6.6, 31.7 and 0.65. Only 21 of 39 shipments got the same primary label in all 4 runs. Between consecutive runs, 7, 6 and 7 shipments changed outcome.

### C. Always-wrong shipments: what the model said each run vs what is accepted, and what the evidence showed at the snapshot
| Shipment | Recipe | Accepted | r2 / r3 / r4 / final | State at investigation snapshot (replica) | Cause class |
|---|---|---|---|---|---|
| 000187 | contractor_unreturned | UNRECONCILED_CUSTODY | RU / RU / RU / RU | Rule code RECIPIENT_UNAVAILABLE; 2 FAILED RECIPIENT_NOT_REACHED + NO_RESPONSE; UNRECONCILED_CUSTODY appears +9 h | Label not observable at snapshot |
| 000239 | contractor_unreturned | UNRECONCILED_CUSTODY | RU ×4 | Same pattern (4 failed attempts); +9 h | Label not observable at snapshot |
| 000101 | absent_session_receipt | UNRECONCILED_CUSTODY | CG / MM / DS / CG | Monitor: MISSED_MILESTONE only; snapshot 14:00:12 is 12 s past session end + 3600 s grace; monitor flags +1 h | Grace boundary + narrow set |
| 000482 | absent_session_receipt | UNRECONCILED_CUSTODY | CG / DS / MM / CG | Same, +1 h | Grace boundary + narrow set |
| 000029 | partial_packages | CUSTODY_GAP, UNRECONCILED_CUSTODY | DS / MM / MM / DS | MISSED_MILESTONE; +1 h; no outage, so DS is a model error | Grace boundary + model (DS) |
| 000387 | traffic_safe_return | TRAFFIC_DELAY, ROUTE_DELAY | MM ×4 | Monitor already had TRAFFIC_DELAY (TrafficObservation 32,400 s, conf 0.95); no tool exposes it | Tool gap |
| 000067 | report_different_location | DELIVERY_DISPUTE, POSSIBLE_MISDELIVERY | PI ×4 | Rule codes at snapshot (no allowance): CUSTODY_GAP, DELIVERY_DISPUTE, PROOF_INSUFFICIENT | Taxonomy / acceptable set |

### D. Symptom-only and rule-code baselines on the final 41 cases
| Predictor | Correct /41 | Notes |
|---|---|---|
| Agent (gpt-oss:120b) | 26 (63.4%) | 26/39 excluding 2 degraded |
| B_strict: single opening symptom with one rule code, else none | 20 (48.8%) | |
| B_symptom: most specific single-code opening symptom, MILESTONE_OVERDUE→MISSED_MILESTONE as fallback, multi-code symptoms → none | 22 (53.7%) | |
| Oracle: any single-code opening symptom is acceptable | 22 | |
| B_rulecode: the monitor's own exception code at opened_at, most specific first | 28 (68.3%) | |
| Best opening-symptom-set → label map (in-sample upper bound) | 30 (73.2%) | 146/204 on all abnormal shipments of the 600-world; rule-code-set map 160/204 |

Agent vs B_symptom: both right 17, only agent 9, only baseline 5, both wrong 10. Agent vs B_rulecode: both right 22, only agent 4 (000003, 000113 and 000120 DELAYED_SYNC; 000459), only rule code 6 (000067, 000262, 000337, 000387, 000400, 000567), both wrong 9.

### E. Ambiguity by opening symptom set (final case rows, plus 204 abnormal shipments in the 600-shipment world)
| Opening set | Final cases | Distinct truth causes (cases) | 600-world shipments / distinct causes | One label acceptable for all? | Agent |
|---|---|---|---|---|---|
| MILESTONE_OVERDUE | 13 | 6 | 70 / 9 (DS 26, UNREC 15, CG 14, HUB 8, …) | no (best DS 35/70) | 5/13 |
| RECIPIENT_REPORTED_NOT_RECEIVED | 5 | 3 | 31 / 3 | yes (DELIVERY_DISPUTE) | 3/5 |
| DELIVERY_ATTEMPT_FAILED | 5 | 4 | 29 / 4 (UNREC 9, WRONG_GATE 7, ADDRESS 7, RU 6) | no | 3/5 |
| WEIGHT_READ_DIFFERS | 5 | 2 | 22 / 2 | yes (WEIGHT_MISMATCH) | 5/5 |
| BARCODE_READ_DIFFERS | 4 | 1 | 16 / 1 | yes | 3/4 |
| CUSTODY_TRANSFER_UNCONFIRMED + MILESTONE_OVERDUE | 2 | 2 | 5 / 2 | no | 1/2 |
| MANIFEST_CUSTODY_CONFLICT | 2 | 1 | 9 / 1 | yes | 2/2 |
| DELIVERY_ATTEMPT_FAILED + MILESTONE_OVERDUE (second cases) | 2 | 2 | not a first-opening set | no | 2/2 |
| CUSTODY_REPORTS_CONFLICT (alone or + MILESTONE_OVERDUE) | 2 | 1 | 9 / 1 | yes | 2/2 |
| MILESTONE_LATE + MILESTONE_OVERDUE | 1 | 1 | 4 / 1 (TRAFFIC) | yes | 0/1 |

| Group | Cases | Agent | B_symptom | B_rulecode |
|---|---|---|---|---|
| Determined (one label acceptable for all shipments with that opening set, 600-world) | 19 | 15 (78.9%) | 18 | 19 |
| Ambiguous | 22 | 11 (50.0%) | 4 | 9 |
| Strict definition: one distinct truth_cause in case rows | 9 | 7 | 8 | 9 |
| Strict definition: ambiguous | 32 | 19 | 14 | 19 |

### F. Error decomposition (wrong cases)
| Cause of error | run2 | run3 | run4 | final | Pooled /57 |
|---|---|---|---|---|---|
| Evaluation: label not observable at snapshot (contractor_unreturned) | 2 | 2 | 2 | 2 | 8 |
| Evaluation: answer defensible at snapshot, narrow or inconsistent acceptable set (CG/MM on session-receipt recipes) | 2 | 2 | 2 | 2 | 8 |
| Taxonomy: PROOF_INSUFFICIENT on report_different_location | 1 | 1 | 1 | 1 | 4 |
| Tool gap: traffic | 1 | 1 | 1 | 1 | 4 |
| Model: missed DELAYED_SYNC with handheld silent at snapshot | 4 | 5 | 4 | 4 | 17 |
| Model: DELAYED_SYNC with no outage | 2 | 2 | 2 | 1 | 7 |
| Model: other (later_hub→CG ×3, wrong_label→IE, dispute case→CG) | 2 | 1 | 0 | 2 | 5 |
| Investigator degraded (no diagnosis) | 0 | 2 | 0 | 2 | 4 |

### G. Reviewer and fact checks vs correctness
| Run | ACCEPT right/total | Final REVISE right/total | Wrong diagnoses caught by REVISE |
|---|---|---|---|
| run2 | 20/31 | 8/11 | 3/14 |
| run3 | 22/35 | 5/6 | 1/14 non-degraded |
| run4 | 26/37 | 4/5 | 1/12 |
| final | 18/30 | 8/9 | 1/13 non-degraded |
| pooled | 86/133 (64.7%) | 25/31 (80.6%) | 6/53 (11.3%) |

The fact check (fact_check_unsupported) was True in 0 of 164 non-degraded diagnoses, 53 of which were wrong.

### H. Precision of the predicted primary cause (pooled 168 cases)
CUSTODY_GAP 10/34 · DELAYED_SYNC 12/19 · RECIPIENT_UNAVAILABLE 4/12 · MISSED_MILESTONE 1/10 · PROOF_INSUFFICIENT 5/9 · WEIGHT_MISMATCH 20/20 · BARCODE_MISMATCH 15/15 · MANIFEST_CONFLICT 10/10 · DELIVERY_DISPUTE 10/10 · CONFLICTING_CUSTODY 8/8 · WRONG_GATE 8/8 · ADDRESS_CONFLICT 8/8 · None 0/4 · INSUFFICIENT_EVIDENCE 0/1

### I. Scoring sensitivity
| Variant | final | pooled |
|---|---|---|
| As scored | 26/41 | 111/168 |
| Accept snapshot-observable answers (RU for contractor_unreturned; CG/MM for absent_session_receipt and partial_packages; PI for report_different_location) | 31/41 (75.6%) | 131/168 (78.0%) |
| Same, excluding degraded | 31/39 (79.5%) | 131/164 |
| First case per shipment, as scored | 24/39 (61.5%) | 100/156 |
| Credited only by the second-cause DELAYED_SYNC | 0 | 1 / 2 / 2 / 0 (run2 / run3 / run4 / final) |
