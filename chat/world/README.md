# world-1: a mechanism-based synthetic Saudi logistics world

Stage 1 of the Suhail mission (plan: `docs/plans/2026-10-10_stage1_world.md`; why: `docs/assessments/2026-10-10_stage0/README.md`).
Everything here is synthetic and labelled synthetic (`synthetic: true` on every node and edge, ids start with `DEMO-`).
It is not SPL data and makes no claim about SPL networks, schedules, capacities or policies; every number below is a
documented assumption chosen to make a plausible, internally consistent world at a scale of about 100 shipments a day.

## 1. The model in one paragraph

Shipments are booked over simulated days. A discrete-event simulation (`physical.py`) moves every parcel through a
network of facilities, containers, trips and delivery routes; at every instant each parcel is in exactly one place (a
facility, a container, a vehicle or a person) and has exactly one physical custodian. Faults are **mechanisms** placed
on shared resources (a device, a facility, a trip, a driver's route, a scale, an SMS route, a road zone, a recipient or a
label) and they act on every parcel they physically touch. The **observation layer** (`observe.py`) then decides what
devices, people and systems recorded, and when each record reached Suhail: an offline device buffers and uploads at
reconnect, a stuck outbox waits for the nightly sync, drivers file noisy reason codes, carriers send EDI status late,
providers retransmit. Only observations become V2 evidence. The physical state stays in label-free private files next
to the bundle; the mechanism records and truth labels go to a directory outside the repository. Neither is imported.

```
bookings.py  -> shipments, parcels, recipients, journey plan stamped at booking
schedule.py  -> mechanism instances (scenario weighting, re-simulated until every split reaches its targets)
physical.py  -> private DES: locations, custody, acts (who scanned what, when, with which device)
observe.py   -> V2 nodes/edges: occurred_at = event time, recorded_at = provider send time (+ feed lag at the gateway)
truth.py     -> per-shipment truth labels: mechanisms, cause codes, discrimination specs, labels_at, canary, compatibility view
build.py     -> world build, retransmissions, background (routine) failures, snapshot times, cut-off rule, V2 export per live split
history.py   -> label-free verified history outcomes for imported cases (the PRECEDENTS query returns real rows)
validate.py  -> foundation (with documented replacements), physics, observation, isolation, tells, discrimination specs,
                precedent cut-off, coverage, monitor replay, pre-run tell test
pipeline.py  -> build + validate + write (bundles, external truth directory, evaluation JSON)
export.py    -> CLI: export / apply / check (Neo4j)
```

## 2. Network and operations (`network.py`, `geo.py`, `bookings.py`)

Cities (approximate public centres, English and Arabic): Riyadh, Jeddah, Makkah, Madinah, Dammam, Khobar, Dhahran,
Al Ahsa (Hofuf), Buraydah (Qassim), Jubail, Taif, Tabuk, Abha. Destination demand weights: Riyadh .30, Jeddah .19,
Dammam .09, Khobar .07, Makkah .07, Madinah .06, others .025-.04. Origin weights favour Riyadh (.40), Jeddah (.25) and
Dammam (.12). Districts: real public district names with approximate centres for the large cities, compass districts
elsewhere. Regions and hubs: central (Riyadh), west (Jeddah), east (Dammam).

| Facility | Count | Capacity and shifts | Devices |
|---|---|---|---|
| Sorting center | 3 (RUH, JED, DMM) | 90 / 70 / 50 parcels/h; 06-14 and 14-22 at 100%, 22-06 at 50% | handheld, sorter reader, 2 induction scales |
| Hub | 3 | cross-dock, 40 containers/h | dock handheld |
| Delivery depot | 14 (2 in Riyadh) | receipt 60 / 40 / 25 parcels/h by size, 05-23 | handheld, check scale |
| Branch | 13 | counter drop-off | counter scanner (no telemetry in the 7 small cities) |
| Fulfillment warehouse | 3 | e-commerce origin | handheld |
| Merchant (customer) warehouse | 10 | merchant origin | handheld provided by SPL |

Lanes: road distance = haversine x 1.18 (intercity) or x 1.35 (urban); transit = distance / speed (82 km/h linehaul,
72 feeder, 75 intercity collection, 30 urban) + 40 min rest per 4.5 h + 10 min yard time. Linehaul departures (local):
RUH-JED 21:30, 02:30; JED-RUH 21:00, 02:00; RUH-DMM 23:00, 04:00; DMM-RUH 22:30, 03:30; JED-DMM 19:00; DMM-JED 19:30.
Cutoff 60 min before a linehaul and 45 min before a feeder. Feeders leave each hub to reach every depot of the region by
05:45, plus a 12:30 run for depots within 5 h. Collection runs visit the origin facilities of a city at 13:30 and 18:30
(16:00 for cities more than 120 km from the sort). Lanes touching Dammam and the east-region feeders are run by the
contracted carrier (EDI channel); the rest by the in-house fleet. Vehicles and drivers are allocated to scheduled trips by
planned availability (one driver one vehicle at a time), dispatch rotating among those free (seeded per trip, so a run
is not tied to one vehicle from day to day); a late truck delays its next run.

Consolidation: at induction each parcel is weighed and read, then bagged into the container for its destination depot
and the next trip whose cutoff it can make. Containers move sort -> hub (yard) -> linehaul -> destination hub
(cross-dock) -> feeder -> depot, where they are opened and every parcel is scanned in. A parcel weighing outside the
declared weight's tolerance (and an 8% audit sample) is re-weighed on the depot check scale.

Last mile: at 07:15 each depot plans routes for parcels on its shelf or arriving by 07:45 (about 12 shipments a route,
at most 20 for a van and 14 for a private car, no bulky parcels in private cars), publishes the route manifest at 07:30,
loads 08:00-08:50 (each parcel confirmed by the driver app), drives a nearest-neighbour tour at urban speed (slower in
rush hours), attempts each stop, returns, scans returns in and reconciles the session. Drivers: employees in company
vans, contractor drivers in contractor vans, independent drivers in private cars (2 to 5 per depot, weekly day off).
Ordinary variation: 8% of routes use a spare van, 12% get a revised manifest, 4% end early, an end-of-day stock check
at 21:30 scans every parcel on the shelf, Friday has no last-mile delivery, at most 3 attempts.

Bookings: B2C .60, C2C .25, B2B .15; EXPRESS 30% (B2C), 20% (C2C), 10% (B2B); 1-3 parcels (B2C/C2C), 2-5 (B2B), 15%
of B2B shipments bulky; weights lognormal by flow; declared weight within about 2.5% of the truth. Recipients have an
address point (district + offset, geocode accuracy 8-30 m), building, street, unit, an 18% (consumer) / 40% (business)
chance of a compound with named gates, a contact preference, a delivery preference (standard, leave at door, reception,
authorised neighbour), an SMS carrier route and an availability pattern (home .96, irregular .82, evenings .45 before
15:00 / .93 after, business hours .97 / .15; at least .90 after a failed attempt).

The journey plan is stamped at booking from the published schedule: the nominal journey and the latest journey that
still meets the promise (EXPRESS: the nominal delivery day; STANDARD: one more delivery day). ExpectedMilestone windows
run from 15 min before the nominal time to the latest feasible time plus the service tolerance (EXPRESS 30 min,
STANDARD 60 min) and one hour of handling slack; DELIVERED is due at the promise. A parcel that misses one connection
but still makes its promise is late against plan without breaching a milestone.

## 3. Mechanisms (`mechanisms.py`, `schedule.py`)

Each mechanism has a physical effect, an observation effect, a truth record and a natural recovery (what happens if
nobody acts). Cause codes are from `operations/agents.py` CAUSES; actions from `operations/authority.py` ACTIONS.

| Mechanism | Where it is placed (parameters) | Cause code | Resolution / action | Natural recovery |
|---|---|---|---|---|
| DEVICE_OUTAGE | a depot or hub handheld, a sorter reader or a driver app; window sized to the busy period it covers, +0.25-1.5 h (+0.5-8 h for a phone) | DELAYED_SYNC | AUTO / REQUEST_DEVICE_SYNC | reconnect at window end; every buffered record uploads, reconnect heartbeat reports the buffer |
| PARTIAL_UPLOAD_LOSS | a handheld or driver app, 1.5-8 h, 35-60% of its records stuck | DELAYED_SYNC | AUTO / REQUEST_DEVICE_SYNC | nightly full sync at 02:30; heartbeats show a pending queue meanwhile |
| SCAN_SKIPPED_AT_RECEIPT | one parcel at depot receipt (80%) or hub receipt | CUSTODY_GAP | AUTO / INITIATE_CUSTODY_RECONCILIATION | next handling scan shows the parcel moved on |
| FACILITY_BACKLOG | a sort (evening, capacity x0.15-0.3) or depot receipt (x0.12-0.3), 1-4 h | HUB_DELAY | AUTO / REQUEST_HUB_CHECK | queue drains onto later departures |
| LATE_LINEHAUL | a linehaul or feeder trip: departure delay 2-6 h, or breakdown 3-8 h at 20-70% of the way | ROUTE_DELAY | AUTO / PRIORITIZE_NEXT_SESSION | trip completes late; parcels take later connections |
| MISSORT | a container loaded onto another lane's truck (scan records the intended trip), or one parcel into another depot's bag | HUB_DELAY | AUTO / REQUEST_HUB_CHECK | receiving hub/depot sends it back (about a day) |
| ASSIGNED_NOT_LOADED | one parcel on a route manifest left on the shelf | CUSTODY_GAP | HUMAN / INITIATE_CUSTODY_RECONCILIATION | stock check scans it; re-planned next day |
| DELIVERY_SCAN_SKIPPED | delivered, but no attempt/proof/scan recorded | UNRECONCILED_CUSTODY | HUMAN / INITIATE_CUSTODY_RECONCILIATION | 40% of recipients later confirm receipt |
| RETURN_SCAN_SKIPPED | returned to the shelf without a return scan | UNRECONCILED_CUSTODY | HUMAN / INITIATE_CUSTODY_RECONCILIATION | 21:30 stock check finds it; session reconciled late |
| CONTRACTOR_RETAINS | an independent driver's route: undelivered parcels kept, no check-in, app silent | UNRECONCILED_CUSTODY | HUMAN / PHYSICAL_CUSTODY_CHECK | 50%: returned 20-52 h later |
| UNRECORDED_HANDOFF | a depot-day: 2-3 of one driver's remaining stops passed to another driver | CUSTODY_GAP | AUTO / INITIATE_CUSTODY_RECONCILIATION | delivered by the other driver; custody record stays inconsistent |
| RECIPIENT_UNAVAILABLE | a recipient away for 2-4 days | RECIPIENT_UNAVAILABLE | AUTO / PRIORITIZE_NEXT_SESSION | later attempt succeeds or attempts run out |
| WRONG_ADDRESS | the booked address is outdated (recipient lives 2-9 km away) | ADDRESS_CONFLICT | AUTO / REQUEST_ADDRESS_CONFIRMATION | 85%: a dated portal correction 0-30 h after the failed attempt |
| WRONG_GATE | navigation pin at another compound gate | WRONG_GATE | AUTO / REQUEST_ADDRESS_CONFIRMATION | recipient guides the driver or fixes the instruction |
| OTP_NOT_RECEIVED | an SMS carrier-route outage window (shared) or one recipient's number | PROOF_INSUFFICIENT | AUTO / REQUEST_ADDITIONAL_EVIDENCE | gateway recovers; 35% of drivers override without a code |
| NEIGHBOUR_RECEIVES | an OTP-protected consumer delivery: recipient stepped out; an unauthorised neighbour takes it (driver called first in 55%) | DELIVERY_DISPUTE | HUMAN / DELIVERY_DISPUTE_REVIEW | 65%: non-receipt report 2-30 h later; else 21%: confirmation |
| MISDELIVERY | an OTP-protected consumer delivery left at a building 80-450 m away (driver called first in 55%) | POSSIBLE_MISDELIVERY | HUMAN / DELIVERY_DISPUTE_REVIEW | 85%: non-receipt report 3-40 h later |
| LABEL_MISREAD | one read wrong (one digit), at the sorter (70%) or depot | BARCODE_MISMATCH | AUTO / REQUEST_RESCAN | next read is right |
| WRONG_LABEL_APPLIED | another order's label from booking | BARCODE_MISMATCH | HUMAN / REQUEST_RESCAN | none: every read is wrong |
| SCALE_DRIFT | an induction scale, +15-40% (70%) or -15-40%, 1.5-8 h | WEIGHT_MISMATCH | AUTO / REQUEST_REWEIGH | recalibration; the depot check scale disagrees |
| DECLARED_WEIGHT_WRONG | declaration x0.45-0.72 or x1.45-2.2 | WEIGHT_MISMATCH | HUMAN / REQUEST_REWEIGH | none: every scale agrees with each other |
| MANIFEST_ERROR | a route revision drops a loaded parcel; every shipment on the route gets its version-2 line | MANIFEST_CONFLICT | HUMAN / MANIFEST_RECONCILIATION_REVIEW | none |
| TRAFFIC_DISRUPTION | a district for 3-6 h, travel x2.5-4 (closure, collision, congestion) | TRAFFIC_DELAY | AUTO / PRIORITIZE_NEXT_SESSION | next session delivers |
| CUSTOMER_COMPLAINT | a status question (no action) or a non-receipt claim on a delivered parcel | DELIVERY_DISPUTE (claim) | HUMAN for a claim, NONE for a question | 40% of claims followed by "found it" |
| DUPLICATE_EVENTS | provider retransmission (driver app 5%, carrier EDI 4%, SPL core 0.6%, telematics/messaging 1%) | none | NONE (idempotency only) | the gateway de-duplicates |
| ROUTINE_FAILED_ATTEMPT | background, never scheduled: an ordinary failed attempt that pushes delivery past the promise | by reason | AUTO / PRIORITIZE_NEXT_SESSION | next session |

Scenario weighting (addendum B4): the over-sampling rates are committed in `config.py` (`MECHANISM_RATES`: every
scheduled mechanism has a history rate of 0.005 and a live rate of 0.036, live meaning development and held-out). The
scheduler places instances until each mechanism touches at least `max(1, round(rate x shipments in the split))`
shipments of every world split (600-shipment world: history 1 of 208, development 11 of 305, held-out 3 of 87),
re-simulating up to five rounds, because a fault changes the flows. Shared mechanisms usually touch more (a backlog
delays a whole batch). `world_manifest.json` records the rates, the targets they give and the achieved counts as
scenario weighting, not real frequencies; evaluation worlds of any size use the same rates. Multi-cause cases arise
where mechanisms overlap on a parcel (78 of 305 development shipments in the default world).

Ordinary variation (not mechanisms): processing and transit jitter, 10% of trips leave 15-45 min late, uploads take
seconds to minutes (driver app median 45 s with 4% batched 8-40 min; handheld median 25 s with 2% batched 5-25 min),
sorter no-reads (2%) go to a manual scan, SMS failures (2.5%; a failure receipt arrives only after the carrier's retry
window, lognormal median 2 h clipped to 40 min-8 h, a delivered receipt in 3-40 s), out-for-delivery messages at route
manifest publication, a call to the recipient's number in 55% of code failures, OTP resends (12%), a code not given (3%), building not
found (1.5%), access refused (5% at compounds, 1% elsewhere), 8% of driver reason codes filed as OTHER, family members
and authorised alternates, leave-at-door, GPS fixes that drift in dense blocks (1.2%), minor address corrections (2.5%),
rush-hour congestion reports, routine reschedule requests and thank-you messages, retransmissions and out-of-order
arrival.

## 4. Evidence schema

Every existing kind uses the property schema of `dataset_v2/generate.py` and `network.py`; additions are extra reference
properties. Every per-parcel observation is shipment-owned (`holdout_group` = shipment id). Sharing is expressed through
shared reference ids on those records and through shared nodes.

New kinds (all additive in `contracts.py`, `context.py`, `feed.py`, `operations/ingestion.py`):

| Kind | Group | Properties | Delivered by |
|---|---|---|---|
| Container | shared catalog | container_type, origin_facility_id, destination_facility_id (the label) | imported, recorded_at = creation |
| Trip | shared catalog | trip_type, lane_id, from/to_facility_id, start_at/end_at (scheduled), cutoff_at, vehicle_id, driver_id, provider_id, distance_km | imported, recorded_at = schedule publication (36 h ahead) |
| RouteRun | shared catalog | depot_id, service_date, vehicle_id, driver_id, provider_id, device_ref, start_at/end_at, planned_stops | imported, recorded_at = 07:15 planning |
| Lane | shared catalog | lane_type, from/to_facility_id, stop_facility_ids, distance_km, departures_local, nominal_transit_seconds | imported |
| FacilityThroughput | shared observation | facility_id, start_at/end_at (hour), processed_count, queue_depth, nominal_capacity_per_hour | feed (SPL_CORE) |
| TripEvent | shared observation | trip_id, vehicle_id, event_type (DEPARTED, ETA_REVISED, ARRIVED), estimated_arrival_at, reason_code | feed (CARRIER_EDI or SPL_CORE) |
| TrafficEvent | shared observation | city_id, district, lat/lng, radius_km, start_at/end_at, event_type, severity, confidence | feed (TRAFFIC) |
| CommunicationEvent | shipment-owned | direction, channel_type, purpose (OUT_FOR_DELIVERY, OTP, OTP_RESEND, ATTEMPT_FAILED, DELIVERED), delivery_status, carrier_route, recipient_id, template_ref, secret_value_stored=false for codes | feed (new MESSAGING channel, its own field names and epoch time) |

Shared observations that already existed are used as shared nodes too: DeviceHeartbeat (every device with a telemetry
stream; facility devices every 30 min, driver apps every 15 min while logged in, a LOGGED_OUT beat at check-in, silence
during an outage and a reconnect beat reporting the buffered count) and GPSObservation (vehicle positions every 30 min
with trip_id or route_run_id; `position_scope` VEHICLE_ONLY). `Device.telemetry_stream` is MDM_HEARTBEAT or NONE, so
"no telemetry stream" is distinguishable from "silent".

New reference properties on existing kinds: ScanEvent `container_id`, `trip_id`, `route_run_id`, `vehicle_id`;
CustodyEvent `trip_id`, `route_run_id`; DeliveryAttempt `route_run_id`, `driver_id`, `vehicle_id`; DeliverySession and
VehicleAssignment `route_run_id` (and `trip_id`); Manifest `route_manifest_ref` (the RouteRun id); RecipientReport
`channel`; AddressVersion `supersedes_id`; ExpectedMilestone `nominal_at`; Shipment `service_level`. New relationships:
IN_CONTAINER, ON_TRIP, ON_ROUTE_RUN, ON_LANE, HAS_COMMUNICATION, HAS_THROUGHPUT, HAS_TRIP_EVENT (created by the generator
for imported records and by the gateway's new EDGE_RULES for live ones).

Shared facts duplicated into shipment-owned records, and why (each is required by an existing consumer):
- Container moves (hub receipt, linehaul and feeder loads, destination hub receipt) are per-parcel CustodyEvents with a
  per-parcel `CONTAINER_SCAN` ScanEvent source carrying `container_id` and `trip_id`. `derive.assess_shipment` matches
  ExpectedMilestones only against per-package custody events and judges custody continuity per package.
- Each shipment on a route has its own DeliverySession (the depot-day session window), VehicleAssignment and Manifest
  line (version 1 at 07:30, version 2 for everyone on the route when the route is revised). `derive` evaluates
  reconciliation and manifest conflicts from the shipment's own sessions, assignments and manifests.
- No shipment-owned TrafficObservation is produced: a traffic feed knows roads, not parcels. Traffic is only the shared
  TrafficEvent (and slow vehicle positions), so derive's TRAFFIC_DELAY code never fires in world-1.

Dated per-shipment context (DeliverySession, VehicleAssignment, a corrected AddressVersion and its LocationPin, the
Customer node of a person who took a parcel) reaches a live shipment through the feed; booking-time records (shipment,
packages, parties, address v1, plan, route, milestones) are imported. Custody DELIVERED always names the consignee; the
HandoffEvidence names who physically took the parcel. No code value is ever stored.

## 5. Truth labels and private state (`truth.py`, `export.py`; never imported)

Two private outputs, kept apart (addendum B1):

- **Physical world state**, label-free, next to the bundle in `private/`: `parcels` (true location timeline, custody
  list, status, attempts, true and declared weight, manifest and physical label barcode), `containers`, `devices`
  (offline windows with reconnect time and the records each buffered, stuck-upload windows and their records, scale
  offsets), `facility_capacity`, `trips` and `routes` as they ran (who kept parcels, who passed parcels to whom),
  `recipients` (home point, registered point, gates, the gate navigation leads to, availability profile, away windows,
  SMS-unreachable windows), `messaging_outages`, `traffic` and a physical `events` log with neutral names. This is what
  the Stage 4 operational simulator may read. It contains no cause code, mechanism name, mechanism id, truth field name
  or the canary (validated: `private_state_isolation`).
- **Truth labels**, written only to `<truth-root>/<dataset_id>/`, outside the repository and outside `artifacts/`
  (default `C:\Projects\suhail-eval-truth`, or `SUHAIL_EVAL_TRUTH_ROOT`, or `--truth-root`; `truth_directory` refuses
  any path inside the repository or under an `artifacts` directory): `truth.jsonl` (one row per shipment of the world),
  `mechanisms.jsonl` (every instance with window, parameters, touched shipments and parcels), `record_index.jsonl`
  (evidence id -> act, device, times, mechanisms), `acts.jsonl`, `physical_events.jsonl`, `monitor_replay_rows_<split>.jsonl`
  (per-shipment replay rows, which name mechanisms), `precedents.json` and `manifest.json`. No module under
  `chat/operations` or `backend` imports the `world` package or names this path (tested). The bundle carries only the
  truth hash.

`truth.jsonl` row:

```
truth_schema ("world-truth-2"), canary, shipment_id, split (world split), booking_day, booked_at, promise_at, service, flow,
healthy (no mechanism with a resolution), physically_healthy (no fault mechanism), first_opening (monitor replica),
mechanisms: [{mechanism_id, type, subtype, origin (scheduled|base|background), cause_code, acceptable_causes,
              resolution (AUTO|APPROVAL|HUMAN|NONE), action, fault, started_at, ended_at,
              discrimination, knowable_at_estimate,
              evidence_ids (this shipment's records the mechanism shaped), shared_evidence_ids, packages}],
compatibility view: recipe, root_cause, acceptable_causes, expected_resolution, physical, key_evidence,
                    secondary_issue, knowable_at_estimate; final_location
```

**Discrimination spec** (addendum A1). Knowable is not "first evidence reaching the gateway". For each mechanism on a
shipment, `discrimination` holds the evidence that separates it from the other mechanisms that open with the same
symptoms:

```
{"opening_symptoms": [...],                  the shipment's first opening in the monitor replica
 "shares_opening_with": [cause codes],       other causes seen with that opening symptom set in this world
 "alternative_mechanisms": [types],
 "any_of": [{"all_of": [item, ...]}, ...]}
item = {"record": evidence_id}               satisfied once that record has been ingested
     | {"absence": {"expected", "match" (kind, equal properties, occurred window), "expected_by", "threshold_seconds": 900,
                    "overdue_at" (= expected_by + 900 s, the monitor's threshold), "cancelled_by" (every record in the
                    world matching `match`; validated empty, so the absence is real)}}
                                             satisfied at t when t >= overdue_at and nothing in cancelled_by was ingested
```

`labels_at(row, t, ingested)` decides from a run's actual ingestion log: `ingested` is the set of evidence ids recorded
at or before `t` (imported records count from the start). It returns the cause codes of the mechanisms with at least one
fully satisfied group, `[]` for a healthy shipment, and `INSUFFICIENT_EVIDENCE` for an abnormal shipment nothing
discriminates yet, which is then the correct answer. `knowable_at_estimate` is only a generator-side convenience (the
spec evaluated with every record ingested at its provider-feed delivery time); `labels_at_estimate` uses it. The
compatibility view takes the actionable mechanism with the earliest estimate as `root_cause`.

**Canary** (addendum B2): every truth row carries `CNRY` + 24 hex characters derived from the seed and dataset id. The
export scan (nodes, edges, feed), the private-state scan and the database scan (`check`) require zero hits for the
canary, every mechanism id (`W1M-#####`) and every mechanism name (names that are also catalogue cause codes, such as
WRONG_GATE, are allowed only on derived case and history fixture nodes).

### Which mechanisms share opening symptoms, and what discriminates them (addendum A1)

From the committed 600-shipment world (seed 20261010; truth in the external directory). "Shares opening symptoms with"
counts, over the whole world, how often each other mechanism appeared on shipments that opened with the same symptom
set (multi-cause shipments included). The last column comes from the development monitor replay: cases opened, of
which ambiguous (another cause shares the opening symptoms), identifiable at the opening tick and by the end of the
horizon under `labels_at` with the replay's own ingestion times. DUPLICATE_EVENTS is never a case and is omitted.

| Mechanism | Most frequent opening symptom sets (world) | Shares opening symptoms with (world, most frequent first) | What discriminates it | Development: opened / ambiguous / identifiable at opening / by horizon end |
|---|---|---|---|---|
| ASSIGNED_NOT_LOADED | SESSION_END_UNRECONCILED (9); WEIGHT_READ_DIFFERS (2) | FACILITY_BACKLOG (15), RECIPIENT_UNAVAILABLE (15), CONTRACTOR_RETAINS (14), LATE_LINEHAUL (13), OTP_NOT_RECEIVED (13), WRONG_ADDRESS (13) | no load confirmation of the parcel by the route's departure (overdue by 900 s) while the route's other parcels were confirmed, or the evening stock-check scan finding it on the depot shelf | 11 / 11 / 11 / 11 |
| CONTRACTOR_RETAINS | DELIVERY_ATTEMPT_FAILED (10); SESSION_END_UNRECONCILED (3) | ASSIGNED_NOT_LOADED (17), FACILITY_BACKLOG (17), RECIPIENT_UNAVAILABLE (17), DELIVERY_SCAN_SKIPPED (16), LATE_LINEHAUL (16), OTP_NOT_RECEIVED (16) | the driver app's heartbeats overdue and no check-in of the route by session end plus grace (both overdue by 900 s) | 12 / 12 / 8 / 12 |
| CUSTOMER_COMPLAINT | RECIPIENT_REPORTED_NOT_RECEIVED (6); WEIGHT_READ_DIFFERS (1) | SCAN_SKIPPED_AT_RECEIPT (8), ASSIGNED_NOT_LOADED (2), CONTRACTOR_RETAINS (2), DEVICE_OUTAGE (2), FACILITY_BACKLOG (2), MANIFEST_ERROR (2) | the recipient's message together with the delivery proof of the parcel | 7 / 7 / 7 / 7 |
| DECLARED_WEIGHT_WRONG | WEIGHT_READ_DIFFERS (13); CUSTODY_TRANSFER_UNCONFIRMED (1) | DEVICE_OUTAGE (14), FACILITY_BACKLOG (14), MANIFEST_ERROR (14), NEIGHBOUR_RECEIVES (14), PARTIAL_UPLOAD_LOSS (14), SCALE_DRIFT (14) | the destination check weigh agreeing with the sort scale, or a nearby weighing on the same scale that agrees with its own declaration | 11 / 11 / 11 / 11 |
| DELIVERY_SCAN_SKIPPED | SESSION_END_UNRECONCILED (10); CUSTODY_TRANSFER_UNCONFIRMED (2) | FACILITY_BACKLOG (15), OTP_NOT_RECEIVED (15), UNRECORDED_HANDOFF (15), WRONG_ADDRESS (15), ASSIGNED_NOT_LOADED (13), CONTRACTOR_RETAINS (13) | the recipient's receipt confirmation, or: loaded on the route, the route checked in, no return scan of the parcel by session end and no stock-check scan of it that evening | 11 / 11 / 3 / 11 |
| DEVICE_OUTAGE | CUSTODY_TRANSFER_UNCONFIRMED (5); DELIVERY_ATTEMPT_FAILED (3) | FACILITY_BACKLOG (14), SCALE_DRIFT (14), TRAFFIC_DISRUPTION (14), DELIVERY_SCAN_SKIPPED (12), MISDELIVERY (12), OTP_NOT_RECEIVED (12) | the device's heartbeats overdue (two intervals plus 900 s), or a buffered record of the shipment arriving long after it happened, or the reconnect heartbeat reporting the buffered queue | 11 / 11 / 10 / 11 |
| FACILITY_BACKLOG | WEIGHT_READ_DIFFERS (7); CUSTODY_TRANSFER_UNCONFIRMED (3) | SCALE_DRIFT (21), TRAFFIC_DISRUPTION (21), ASSIGNED_NOT_LOADED (17), DEVICE_OUTAGE (17), RECIPIENT_UNAVAILABLE (17), MANIFEST_ERROR (16) | the facility's throughput report showing the drop and growing queue (else its other shared records) | 21 / 21 / 20 / 21 |
| LABEL_MISREAD | BARCODE_READ_DIFFERS (14); BARCODE_READ_DIFFERS + WEIGHT_READ_DIFFERS (1) | MANIFEST_ERROR (15), ASSIGNED_NOT_LOADED (14), CONTRACTOR_RETAINS (14), DELIVERY_SCAN_SKIPPED (14), DEVICE_OUTAGE (14), FACILITY_BACKLOG (14) | the next read of the same label, which returns the manifest barcode | 11 / 11 / 7 / 11 |
| LATE_LINEHAUL | MILESTONE_OVERDUE (7); DELIVERY_ATTEMPT_FAILED (3) | ASSIGNED_NOT_LOADED (13), FACILITY_BACKLOG (13), OTP_NOT_RECEIVED (13), RECIPIENT_UNAVAILABLE (13), WRONG_ADDRESS (13), CONTRACTOR_RETAINS (12) | the carrier's trip events (ETA revision, delay report) for the trip the parcel is on, or its stationary positions | 9 / 9 / 7 / 9 |
| MANIFEST_ERROR | MANIFEST_CUSTODY_CONFLICT (9); BARCODE_READ_DIFFERS (2) | FACILITY_BACKLOG (14), SCALE_DRIFT (14), TRAFFIC_DISRUPTION (14), UNRECORDED_HANDOFF (14), ASSIGNED_NOT_LOADED (5), CONTRACTOR_RETAINS (5) | the revised route manifest without the parcel, together with the parcel's load confirmation on that route | 12 / 12 / 9 / 12 |
| MISDELIVERY | CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE (11); DELIVERY_ATTEMPT_FAILED (1) | FACILITY_BACKLOG (15), OTP_NOT_RECEIVED (15), SCALE_DRIFT (15), TRAFFIC_DISRUPTION (15), WRONG_ADDRESS (15), ASSIGNED_NOT_LOADED (14) | the proof or photo location away from the address, or the recipient's non-receipt report | 11 / 11 / 6 / 11 |
| MISSORT | CUSTODY_TRANSFER_UNCONFIRMED (14); MILESTONE_OVERDUE (6) | DELIVERY_SCAN_SKIPPED (21), DEVICE_OUTAGE (21), FACILITY_BACKLOG (21), MISDELIVERY (21), OTP_NOT_RECEIVED (21), RETURN_SCAN_SKIPPED (21) | a receipt or handling scan of the parcel at a site other than its planned one | 11 / 11 / 11 / 11 |
| NEIGHBOUR_RECEIVES | CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE (11); WEIGHT_READ_DIFFERS (2) | FACILITY_BACKLOG (15), SCALE_DRIFT (14), TRAFFIC_DISRUPTION (14), ASSIGNED_NOT_LOADED (14), RECIPIENT_UNAVAILABLE (14), OTP_NOT_RECEIVED (13) | the handoff evidence naming a person other than the recipient | 11 / 11 / 11 / 11 |
| OTP_NOT_RECEIVED | CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE (7); MILESTONE_OVERDUE (4) | FACILITY_BACKLOG (21), WRONG_ADDRESS (21), ASSIGNED_NOT_LOADED (19), LATE_LINEHAUL (19), MISDELIVERY (19), RECIPIENT_UNAVAILABLE (19) | a failed SMS delivery report for the one-time code | 9 / 9 / 6 / 9 |
| PARTIAL_UPLOAD_LOSS | CUSTODY_TRANSFER_UNCONFIRMED (11); MILESTONE_OVERDUE (2) | FACILITY_BACKLOG (15), DELIVERY_SCAN_SKIPPED (14), DEVICE_OUTAGE (14), OTP_NOT_RECEIVED (14), SCALE_DRIFT (14), TRAFFIC_DISRUPTION (14) | heartbeats that keep arriving but report a pending upload queue, or the stuck record arriving with the nightly sync | 12 / 12 / 12 / 12 |
| RECIPIENT_UNAVAILABLE | DELIVERY_ATTEMPT_FAILED (10); MILESTONE_OVERDUE (1) | ASSIGNED_NOT_LOADED (15), FACILITY_BACKLOG (15), CONTRACTOR_RETAINS (14), LATE_LINEHAUL (14), OTP_NOT_RECEIVED (14), SCALE_DRIFT (14) | the unanswered contact attempts recorded with the failed attempt | 11 / 11 / 11 / 11 |
| RETURN_SCAN_SKIPPED | DELIVERY_ATTEMPT_FAILED (11); MILESTONE_OVERDUE (4) | DELIVERY_SCAN_SKIPPED (17), DEVICE_OUTAGE (17), FACILITY_BACKLOG (17), MISDELIVERY (17), OTP_NOT_RECEIVED (17), SCALE_DRIFT (17) | the evening stock-check scan finding the parcel back on the depot shelf | 10 / 10 / 8 / 10 |
| ROUTINE_FAILED_ATTEMPT | MILESTONE_OVERDUE (7); DELIVERY_ATTEMPT_FAILED (6) | ASSIGNED_NOT_LOADED (13), CONTRACTOR_RETAINS (13), DELIVERY_SCAN_SKIPPED (13), DEVICE_OUTAGE (13), FACILITY_BACKLOG (13), LATE_LINEHAUL (13) | the failed attempt record itself (reason and contact attempts); no fault elsewhere | 8 / 8 / 8 / 8 |
| SCALE_DRIFT | WEIGHT_READ_DIFFERS (11); MILESTONE_OVERDUE (2) | FACILITY_BACKLOG (21), TRAFFIC_DISRUPTION (21), ASSIGNED_NOT_LOADED (19), RECIPIENT_UNAVAILABLE (19), DEVICE_OUTAGE (18), MANIFEST_ERROR (18) | another parcel weighed on the same scale in the window, also off its declaration, or the destination check weigh agreeing with the declaration | 17 / 17 / 17 / 17 |
| SCAN_SKIPPED_AT_RECEIPT | CUSTODY_TRANSFER_UNCONFIRMED (8); DELIVERY_ATTEMPT_FAILED (2) | FACILITY_BACKLOG (12), DEVICE_OUTAGE (11), SCALE_DRIFT (11), TRAFFIC_DISRUPTION (11), WRONG_GATE (11), DELIVERY_SCAN_SKIPPED (11) | the parcel's next handling scan after the skipped receipt (it is physically there), together with the on-time receipt scans of the other parcels in the same container (the device worked) | 8 / 8 / 8 / 8 |
| TRAFFIC_DISRUPTION | WEIGHT_READ_DIFFERS (3); MILESTONE_OVERDUE (2) | FACILITY_BACKLOG (12), SCALE_DRIFT (12), ASSIGNED_NOT_LOADED (9), DEVICE_OUTAGE (9), RECIPIENT_UNAVAILABLE (9), MANIFEST_ERROR (8) | the traffic incident report for the district, or the routes' slow positions | 8 / 8 / 8 / 8 |
| UNRECORDED_HANDOFF | CUSTODY_TRANSFER_UNCONFIRMED (11); DELIVERY_ATTEMPT_FAILED (2) | FACILITY_BACKLOG (17), DELIVERY_SCAN_SKIPPED (16), OTP_NOT_RECEIVED (16), SCALE_DRIFT (16), TRAFFIC_DISRUPTION (16), WRONG_ADDRESS (16) | another driver's app recording the parcel the first driver loaded | 11 / 11 / 9 / 11 |
| WRONG_ADDRESS | DELIVERY_ATTEMPT_FAILED (5); MILESTONE_OVERDUE (3) | FACILITY_BACKLOG (13), OTP_NOT_RECEIVED (13), ASSIGNED_NOT_LOADED (12), DELIVERY_SCAN_SKIPPED (12), LATE_LINEHAUL (12), MISDELIVERY (12) | the recipient's dated address correction (or address report) | 9 / 9 / 7 / 9 |
| WRONG_GATE | DELIVERY_ATTEMPT_FAILED (12); CUSTODY_TRANSFER_UNCONFIRMED (1) | DEVICE_OUTAGE (15), FACILITY_BACKLOG (15), SCALE_DRIFT (15), TRAFFIC_DISRUPTION (15), ASSIGNED_NOT_LOADED (14), CONTRACTOR_RETAINS (14) | the attempt's recorded gate, which differs from the delivery instruction's gate | 11 / 11 / 11 / 11 |
| WRONG_LABEL_APPLIED | BARCODE_READ_DIFFERS (15) | ASSIGNED_NOT_LOADED (15), CONTRACTOR_RETAINS (15), DELIVERY_SCAN_SKIPPED (15), DEVICE_OUTAGE (15), FACILITY_BACKLOG (15), LABEL_MISREAD (15) | the next read of the same label, which returns the same other-order barcode | 11 / 11 / 1 / 11 |

Two actionable instances in this world (of 463) have no discriminator at all: a MISDELIVERY on a history shipment whose
records include the attempt and custody event but no proof, photo or non-receipt report shaped by it, and an
UNRECORDED_HANDOFF on a held-out shipment that left no record of the handoff. For them INSUFFICIENT_EVIDENCE stays the
correct answer.

## 6. Splits and exports

One connected world, split by booking day (default 6 days: history days 1-2, development days 3-5, held-out day 6;
9 days: 4/3/2). `export_bundle(build, live_split)`:
- development export: history imported in full (cases derived at the monitor's first opening, verified outcomes authored
  by `history.py`), development fed live (booking-time records imported; everything later is a provider message),
  held-out days absent. V2 split counts: history and development (held_out = 0, hence `WorldV2Config`).
- held-out export: history and development imported in full as V2 `history`, held-out fed live.
Shared observations recorded before the live start are imported; later ones are fed.

The bundle has the shape of `dataset_v2.live_bundle.export_live` (nodes, edges, gold, feed jsonl; manifest, validation,
statistics, feed_manifest json) except that `truth.jsonl` is not in it (addendum B1; `feed_manifest.json` keeps the truth
hash), plus `world_manifest.json` (rates, targets, achieved counts, precedent counts, hashes, timings),
`world_validation.json`, an aggregate `monitor_replay.json` (no per-shipment rows) and the label-free `private/`.

History precedents (`history.py`, addenda A2 and B5). Label-free: nothing in `history.py` reads truth labels. For every
history case the monitor opened, the action is the operations policy's default action for the case's most specific
rule code (15%: the default action of another code the case carried), and the outcome is verified from the shipment's
own evidence recorded between the action and verification: succeeded when re-assessing the shipment no longer raises a
rule code that opened the case, or when the evidence shows what the action was for (`ACTION_EVIDENCE`: buffered records
arrived, the parcel was scanned again, a rescan read the manifest barcode, a reweigh agreed with the declaration, a
delivered attempt, a receipt confirmation); otherwise failed. Verification happens at most 20 h after the action and
always at least 30 min before the live window starts. A history case is not imported as a precedent (no action,
resolution or outcome is authored; the derived Case and Exception stay) when its verification cannot finish before the
cut-off or when a mechanism instance touching its shipment is still active at or after the cut-off. "Active" is
`build.mechanism_active_until`: the end of the mechanism's window, the arrival of every record it shaped for the
shipment and of its discrimination evidence, and, for faults with no natural recovery (wrong label, declared weight,
manifest error, misdelivery, retained parcels, unrecorded handoff, delivery scan skipped), the moment the parcels left
the network. Provider retransmissions (DUPLICATE_EVENTS) are exempt: an identical copy of a record carries nothing about
a case's outcome. The exclusion decision uses the generator's private record and is never written into the graph.

## 7. Build, validate, export, import

From `chat/`:

```
uv run python -m world.export export --output ../artifacts/world/world-1-small --with-heldout --determinism \
    --eval-dir ../docs/evals/2026-10-10_world1_small [--truth-root C:\Projects\suhail-eval-truth] [--tell-seed N]
uv run python -m world.export apply ../artifacts/world/world-1-small --database shipments-v2-world-1-small [--replace]
uv run python -m world.export check ../artifacts/world/world-1-small --database shipments-v2-world-1-small \
    --ingest --out ../docs/evals/2026-10-10_world1_small/cypher.json
```

`export` refuses an existing export or truth directory and writes nothing unless every gating validation passes (all
sections below except the pre-run tell test, which is reported but not gating); the truth directory is written first,
then the bundles. `apply` only accepts
database names starting with `shipments-v2-world-` (and never the protected ones), reuses `apply_bundle`, `load_feed`
and `target_guard`, recomputes the foundation validation before importing, and creates the `world_*` lookup indexes.
`--replace` recreates that world database. `check` compares node and relationship counts with the bundle, resolves every
shared reference id, runs temporal checks, times the cross-shipment traversals (example windows come from the
label-free `private/` state) and the PRECEDENTS query, scans every node and relationship property in the database
(provider feed payloads included) for the canary, mechanism ids and mechanism names, and with `--ingest` replays the
whole feed through the real `operations.ingestion.Gateway`, repeats the checks and the scan on live evidence, then resets
the live session. The scan reads the canary and mechanism ids from the truth directory (evaluation tooling only). Neo4j settings come from `chat/config.py`; credentials are never printed or written.

Validation (`validate.py`, all recomputed):
- foundation: `dataset_v2.feed.validate_live_bundle` (which runs `validate_world`) on the reconstituted world. Two
  foundation rules cannot apply and have world replacements: PHYSICAL_CUSTODY_CHAIN (every violation must be flagged by
  derive as a CUSTODY_GAP and explained by a recording-fault mechanism; the private chain must be continuous) and
  ADDRESS_VERSION_INTERVAL (a superseded version is never mutated; the newer dated version names it via supersedes_id,
  starts later and was recorded no earlier than it became valid). Any other failing rule fails the export.
- physics: one place at a time, custody matches location, custody continuity, container contents, conservation,
  facility stock never negative, vehicle capacity, one vehicle per driver, travel time vs distance, throughput within
  capacity, scans happen where the parcel is.
- observation: occurred <= recorded <= gateway; record time = event time; scans only from the device that made them;
  no heartbeat during an outage; every record of an offline device delayed; reconnect beat reports the buffer; stuck
  records arrive after the window and the queue is visible; duplicates share identity; out-of-order arrivals exist.
- isolation: no mechanism type, subtype, mechanism id, truth field, compatibility physical value, cause code or action
  name in any imported node or edge property (keys and values, including source_ref) or feed payload. Derived
  Case/Exception and history-outcome nodes may carry catalogue codes (derive emits them from observations) and are
  scanned for everything else.
  The canary is scanned for too.
- private state isolation: the same vocabulary, the canary and mechanism ids over every `private/` record.
- tells: for each mechanism (except DUPLICATE_EVENTS, directly observable by design), no categorical value on a
  shipment's own records or the catalog records they reference (identifier-like fields excluded) that is held by at most
  20% of shipments with precision >= 0.9 and support >= 5, in the development split or the whole world.
- pre-run tell test (addendum B3, `tell_test`): a lookup classifier is trained on the development opening cases of
  this world (opening symptom set plus every visible property value of the shipment's evidence at the opening tick, time
  fields left out; label: the cause codes of its actionable mechanisms) and evaluated on the development opening cases
  of a second world built with another seed (default seed + 1). Keys are (symptom set, value) with training support of
  at least 5 cases; the key with the highest training precision predicts its majority cause, else the baseline does.
  The baseline predicts the training majority cause for the rule codes at opening, most specific first
  (`monitor.SPECIFICITY`): the full code tuple, backing off to the most specific code, then the overall majority. The
  criterion: the lookup must not beat the baseline on the ambiguous stratum (cases whose opening symptoms another cause
  shares). Reported with the discordant cases and the features behind them, a variant without identifier values and
  the reverse direction (diagnostics only). **It is reported, not gating, and it currently fails on the 600-shipment
  world**; see "Pre-run tell test: findings" below.
- discrimination specs: every record item is an observation of the world, every absence item's `cancelled_by` equals a
  full-scan recomputation of its `match` and is empty, every estimate recomputes from the spec and is never before the
  mechanism started, every row carries the canary.
- precedent cut-off: every history outcome verified (and every history fixture recorded) before the live window, and no
  authored precedent whose shipment had a mechanism active at or after the cut-off (recomputed).
- coverage (each scheduled mechanism reaches min(10, target) development shipments), determinism (rebuild, compare
  hashes) and the monitor replay (hourly ticks from the first provider message, 900 s allowance, as in the Stage 0
  replica), which also counts ambiguous cases and how many are identifiable at opening and by the end of the horizon
  under `labels_at` with the replay's own ingestion times.

Tests: `tests/test_world_contracts.py` (S5 byte-identical regeneration, additive contract, messaging round trip) and
`tests/test_world_build.py` (a 240-shipment world plus a second seed: every validation section, detector negative
controls including an injected canary and a crafted opening tell, truth format and discrimination specs, `labels_at`
from an ingestion log, splits, exact feed round trip, the cut-off and label-free history, the bundle reader without
truth, the external truth directory and its guard, no truth path in backend or operations, committed rates, database
guard, determinism).

### Pre-run tell test: findings

The first run on the 600-shipment world (seed 20261010 against 20261011) failed, and the discordant cases showed
generator artifacts, which were fixed in the generator: (1) a neighbour handoff always followed a call to the recipient
and a misdelivery never did (now both 55%, same answered/no-response mix); (2) failure receipts for SMS arrived 2-10 min
after sending, so a failed one-time code was visible at the opening (now after the carrier retry window, as real
gateways report failures); (3) message template versions were drawn per message (now fixed per purpose); (4) misdelivery
and neighbour handoff were placed on any consumer delivery while code failures can only hit OTP deliveries, so "uses a
code" named the cause (now all three on OTP-protected deliveries); (5) a collection run always used the same van, so a
van id named the backlog that recurs at the busiest evening sort (dispatch now rotates); (6) the out-for-delivery message
followed the load record, which an offline app suppresses (now sent at manifest publication). The baseline was also
corrected from the single most specific code to the full code tuple (the single-code variant is still reported).

The test still fails after these fixes (numbers in `docs/evals/2026-10-10_world1_small/README.md`). What remains is not
an artifact of a single field: it is the stage at which a rule code fires (a custody gap found at depot receipt before
dispatch versus one found mid-route), which the coarse rule codes do not carry, plus coincidences of shared resources in
small pools (a late-linehaul cluster on a truck that was also late in the other world). The reverse direction and the
identifier-free variant are much closer to the baseline, which shows how much one seed pair with clustered shared
mechanisms moves the result. Closing the gap needs a decision this stage should not take alone: rebalance fault
placement per stage so the stage carries no cause information, or accept stage context as part of what the monitor
shows. Until then B3 is a known blocking finding, reported in every validation report.

## 8. Known limitations

- Scale and topology are simplified: about 100 shipments a day, one sort and one hub per region, direct bagging to the
  destination depot, one morning dispatch, straight-line positions, no road graph, no returns-to-sender flow (parcels
  are held after three attempts), Fridays without last mile. Truck capacity never binds at this volume.
- History outcomes are authored after the fact from the world's own later evidence; the simulated world does not react
  to history actions. The live operational simulator (Stage 4) will need `private/` to respond causally.
- The cut-off leaves few precedents: history is two booking days and most history cases open, or still have an active
  mechanism, after the development window starts (development export: 46 history cases, 3 precedents authored, all three failed; held-out export: 217 history cases, 86 precedents, 34 succeeded and 52 failed). Precedents are a sample biased towards
  problems that surfaced and settled within the history days.
- Discrimination specs encode what separates a mechanism from the ones that share its opening symptoms in this world,
  as judged by the generator's author; they are machine-checkable but not exhaustive (another valid line of evidence
  may exist that the spec does not list), and `shares_opening_with` is computed from one world's openings.
- The backend's existing S5 simulator hook (`backend/operations_api.py attach_simulator`) reads `truth.jsonl` from the
  live-network bundle; world bundles have no such file, so it stays disabled for world data until Stage 4 moves it to
  the physical state.
- Catalog records of later days (Trip, Container, RouteRun) are imported up front with their creation time as
  recorded_at; they hold plan data only, and consumers must filter by recorded_at (the read model's SHARED_NODES does).
- The existing operations layer accepts only `shipments-v2-demo*` databases and the foundation `Config` (three positive
  split counts). Using a world database needs Stage 2 to allow `shipments-v2-world-*` and construct `WorldV2Config`.
- derive's ADDRESS_CONFLICT cannot fire (imported versions are never closed) and TRAFFIC_DELAY never fires (no
  shipment-owned traffic records); both conditions are visible only through investigation.
- The tell detector checks single categorical values; it does not test combinations, numeric thresholds, timing
  patterns or shared observations. The pre-run tell test covers value combinations only through the symptom set and
  uses one second seed; at this size its ambiguous stratum has about 150 cases, so small accuracy differences are
  noise.
- Scenario weighting makes the development and held-out days dense in faults (209 of 305 development shipments, 69%, carry an actionable mechanism); overlaps come
  partly from independent quota sampling, and two placements are deliberately paired (a contractor route with no
  failure gets an unavailable recipient; a handoff day may get a second route).
- Throughput of the real gateway on a local Neo4j is about 67 messages/s (the 53,902-message development feed took 798 s).
