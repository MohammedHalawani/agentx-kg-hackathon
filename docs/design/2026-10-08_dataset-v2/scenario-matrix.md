# Realistic synthetic scenario matrix

Design 2026-10-08. Each row is a connected story, not a random cause label. Places/routes,
organizations/vehicles/times and tolerances are synthetic assumptions. Neutral IDs in
model inputs must not encode these scenario codes or expected conclusions. Gold is stored
separately from observations and never supplied as a retrospective FailureReason hint.

| Scenario / flow | Network / class | Minimum observations | Derived conclusion / safe action | Contrast case |
|---|---|---|---|---|
| S01 normal C2C dropoff |Riyadh branch → Riyadh depot, small standard|Sender receipt, correct barcode/weight, each custody handover, on-time session, valid delivery receipt|Accounted-for on-time delivery; no exception|Same statuses with one missing custody receipt: evidence incomplete|
| S02 normal B2C pickup |Jeddah organization warehouse → Makkah, express small|Organization inventory allocation, pickup, sorting/linehaul/unload, last-mile/POD|Verified delivery only after package-level corroboration|Manifest allocation without pickup does not mean shipped|
| S03 normal B2B bulky |Dammam company warehouse → Jubail organization receiver|Compatible bulky vehicle, weight/volume capacity, receiver window, receipt|Class-appropriate journey; no universal small-parcel delay|A van lacking payload/handling capacity fails assignment validator, not a random journey|
| S04 fulfillment B2C |Riyadh fulfillment facility → Madinah|Owner vs fulfillment operator, inventory reservation, custody release, intercity segments|Trace responsibility/custody separately; investigate missing release acknowledgment|Company-owned warehouse and managed inventory use different ownership edges|
| S05 barcode discrepancy |Khobar depot; standard small|Manifest barcode A, raw scan barcode B with source/time/confidence; no cause label in scan|BARCODE_MISMATCH; isolate/recheck package identity before relabel approval|Low-quality unreadable scan: needs evidence, not established mismatch|
| S06 weight discrepancy |Riyadh sorting → Dammam; heavy class|Expected/previous calibrated weight 20kg vs later 28kg, scale/units, synthetic absolute/relative tolerance|WEIGHT_DISCREPANCY; verify scale/package and records|20kg vs 20.1kg within configured tolerance: no discrepancy; unavailable calibration: uncertainty|
| S07 wrong gate |Madinah last-mile|AddressVersion instructions gate B, attempt observed gate A, attempted version/time, contact result|WRONG_GATE_OBSERVATION; verify access instructions and permitted changed approach|Recipient says “gate wrong” without observed gate: attributed report, human verification|
| S08 recipient unavailable |Makkah standard/session|Documented contact attempts/results and attempt outcome NO_RESPONSE; valid address; retry budget|RECIPIENT_UNAVAILABLE supported with scope; contact/reschedule only when policy allows|No contact result: unknown availability; don't infer from FAILED status alone|
| S09 address version conflict |Riyadh local B2C|Old/new AddressVersions and effective times; attempt used superseded version; differing pins/accuracy|ADDRESS_VERSION_CONFLICT; confirm authorized destination and redirect after approval|Same formatted address versions/overlapping uncertainty: not automatic conflict|
| S10 contextual hub dwell |Jeddah → Madinah; standard vs express|Confirmed hub receive/departure or missing departure; type-specific expected deadline/as-of|HUB_DWELL_DELAY only when relevant window exceeded; verify handling and next movement|Same dwell within bulky handling window: on-time for its class|
| S11 explained traffic delay |Dammam–Khobar–Dhahran last-mile session|Interval-scoped segment delay, remaining capacity, confirmed failed session/return-to-depot custody|EXPLAINED_ROUTE_DELAY; prioritize next eligible session and recommend notification|Traffic report on another route/time is irrelevant; no vehicle GPS means unknown movement|
| S12 custody gap after session |Hofuf depot/session|Confirmed load/OFD; session end+grace; no delivered/failed/return reconciliation event|UNRECONCILED_CUSTODY; obtain depot/package reconciliation, human review|Late return receipt resolves the gap through audit; don't call it LOST|
| S13 missed transfer receipt |Riyadh → Dammam linehaul|Load/departure confirmed, vehicle downstream arrival, missing package unload/receive|MISSING_TRANSFER_CUSTODY; package check/manifest reconciliation|Vehicle downstream GPS cannot prove package arrival; another package's scan is not this one|
| S14 delivered dispute, corroborated |Jeddah B2C|DELIVERED assertion, recipient NOT_RECEIVED report, valid synthetic authentication/receipt, compatible address/time|Strong corroborating delivery evidence, but dispute requires neutral human review|Never auto-deny report or accuse recipient; verification policy determines next evidence request|
| S15 likely misdelivery |Khobar local|Delivery proof/attempt references different address version or authorized-recipient context, accuracy bounds, contact report|LIKELY_MISDELIVERY hypothesis; investigate/verify handoff|GPS proximity alone or broad accuracy radius: insufficient evidence|
| S16 status/proof conflict |Madinah local|DELIVERED assertion but failed authentication or incompatible package/address/time proof|DELIVERY_CONFIRMATION_CONFLICT; human investigation|Missing POD is insufficient evidence, not proof of wrongdoing|
| S17 multi-cause exception |Dammam → Hofuf B2B|Old address used + calibrated weight discrepancy + exhausted attempts|Separate supported exceptions, action dependencies and higher-level review|Don't force one selected label to explain all observed facts|
| S18 failed attempt / accounted return |Makkah depot|OFD, documented failed attempt/contact, confirmed returned-to-depot package receipt|Accounted custody; next-session/remedy planning, outcome pending|Failed attempt without return receipt after grace becomes custody gap|
| S19 partial multi-package delivery |Riyadh B2B|Three-package manifest, two valid receipts, third custody gap|Partial fulfillment; investigate third package; shipment not fully delivered|Never extrapolate two package receipts to all three|
| S20 reopened case |Jeddah → Riyadh B2C|Prior verified outcome, later conflicting complaint/evidence, versioned invalidation event|REOPENED; retain prior decision/proof, reassess eligible learning|AI reconsideration alone cannot invalidate a verified outcome|
| S21 exhausted retry AFL |Jubail session|Attempt count equals/exceeds versioned limit; plain reschedule initially proposed|Actual hard reject → changed approach or escalation; explicit approval remains required|Verification/redirect is not automatically a plain retry; no rule weakening to force a demo|
| S22 contradictory custody |Dhahran depot/linehaul|Overlapping acknowledged package custody in two places with source/time conflict|HUMAN_REVIEW for conflicting evidence; no convenient chosen location|Out-of-order ingestion with compatible valid-time sequence is not contradiction|
| S23 delayed but not overdue |Riyadh → Madinah bulky/appointment|Longer class-specific handling/receiver window, actual events inside expected range|Within contextual plan, monitor; no unnecessary escalation|Same timeline on express class breaches promise: contextual comparison|
| S24 unknown evidence / graceful failure |Any flow|Missing timestamps, stale GPS, contact pending, malformed provider output or no eligible precedent|NEEDS_MORE_EVIDENCE / HUMAN_REVIEW; record failed attempt, no fabricated default cause|Complete same shipment evidence allows supported analysis; transport/provider failure is not a parcel cause|

At least one of every flow must cover successful delivery and failure/return. Each major
exception gets multiple cities/service classes and natural wording, not a single carrier
or template cue. Include controls at equality boundaries (deadline, retry limit, tolerance),
late ingestion, duplicate event IDs, missing evidence and contradictory sources.

## Four future presentation stories

1. AddressVersion conflict with attempted obsolete address, observed precedent, safe redirect
   proposal, explicit approval and still-pending execution/outcome.
2. Documented recipient/contact retry case where a plain retry is actually hard-rejected,
   feedback changes action or escalates; no manufactured reviewer behavior.
3. Session custody gap: vehicle at depot/downstream hub, missing parcel reconciliation;
   neutral evidence request and human approval point, never driver blame or exact GPS parcel pin.
4. Traffic/contextual-delay pair: small express vs bulky handling, safe confirmed depot return,
   next eligible session recommendation and dry-run notification; later verified receipt
   alone demonstrates OPEN→RESOLVED.

Each narrative has a known immutable starting snapshot, evidence IDs, expected vs actual
timeline, model hypothesis, eligible precedent, review, operator point, external receipt
and outcome-policy boundary. Run-to-run state changes are versioned; use fresh scenario
instances or explicit shadow-dataset restore, never an unnoticed reset of V1.
