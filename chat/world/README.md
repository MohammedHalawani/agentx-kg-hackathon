# world-1: a mechanism-based synthetic Saudi logistics world

Stage 1 of the Suhail mission (plan: `docs/plans/2026-10-10_stage1_world.md`; why: `docs/assessments/2026-10-10_stage0/README.md`).
Everything here is synthetic and labelled synthetic (`synthetic: true` on every node and edge, ids start with `DEMO-`).
It is not SPL data and makes no claim about SPL networks, schedules, capacities or policies; every number below is a
documented assumption chosen to make a plausible, internally consistent world at a scale of about 75 to 100 shipments a day.

Current export: `artifacts/world/world-1-small-r4` (and `-heldout`), numbers in `docs/evals/2026-10-10_world1_small/`.
It replaces the first build (`world-1-small`) after an independent review; that build and two intermediate ones
(`world-1-small-r2` and `-r3`: the same bundle byte for byte, with earlier truth specs) stay on disk because exports are
immutable;
section 9 lists what the review changed and what is still open.

## 1. The model in one paragraph

Shipments are booked over simulated days. A discrete-event simulation (`physical.py`) moves every parcel through a
network of facilities, containers, trips and delivery routes; at every instant each parcel is in exactly one place (a
facility, a container, a vehicle or a person) and has exactly one physical custodian. Faults are **mechanisms** placed
on shared resources and on people's behaviour (a device, a facility, a trip, a scale, an SMS route, a road zone, a
driver on a route, a clerk in a shift, a label printer batch) and, where the cause really is local, on one parcel or
recipient. A mechanism acts on what it physically touches; it is a **cause** for a shipment only where it produced a
deviation there, and an **exposure** where it touched without consequence. The **observation layer** (`observe.py`)
then decides what devices, people and systems recorded, and when each record reached Suhail: an offline device buffers
and uploads at reconnect, a stuck outbox waits for a restart or the nightly sync, drivers file noisy reason codes,
carriers send their own estimates, providers retransmit. Only observations become V2 evidence. Truth labels and the
physical world state are written outside the repository and are never imported.

```
bookings.py  -> shipments, parcels, recipients, journey plan stamped at booking
schedule.py  -> ordinary variation (base rates) and scenario weighting (re-simulated until every split reaches its targets)
physical.py  -> private DES: locations, custody, acts (who scanned what, when, with which device), causes and exposures
observe.py   -> V2 nodes/edges: occurred_at = event time, recorded_at = provider send time (+ feed lag at the gateway)
truth.py     -> per-export truth labels: causes, exposures, discrimination specs, labels_at, canary, compatibility view
build.py     -> world build, retransmissions, ordinary failed attempts, snapshot times, cut-off rule, time-cut V2 export
history.py   -> label-free verified history outcomes for imported cases (the PRECEDENTS query returns real rows)
validate.py  -> foundation (with documented replacements), physics, observation, isolation, import cut, forecasts,
                throughput separation, tells, discrimination specs, precedent cut-off, coverage, monitor replay, tell test
pipeline.py  -> build + validate + write (bundles, external truth and state directories, evaluation JSON)
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
| Sorting center | 3 (RUH, JED, DMM) | 36 / 28 / 20 parcels/h per 100 shipments a day (27 / 21 / 15 in the 600-shipment world); 06-14 and 14-22 at 100%, 22-06 at 50% | handheld, sorter reader, 2 induction scales |
| Hub | 3 | cross-dock, 40 containers/h | dock handheld |
| Delivery depot | 14 (2 in Riyadh) | receipt 24 / 14 / 10 parcels/h by size per 100 shipments a day (18 / 10 / 8), 05-23 | handheld, check scale |
| Branch | 13 | counter drop-off | counter scanner (no telemetry in the 7 small cities) |
| Fulfillment warehouse | 3 | e-commerce origin | handheld |
| Merchant (customer) warehouse | 10 | merchant origin | handheld provided by SPL |

Capacities are sized to the world's volume (`network.py`): in the hour a truck is unloaded a facility works at up to
four fifths of what its shift can process (measured: median 0.28 and 90th percentile 0.88 of staffed capacity over 352
working hours), so a capacity cut leaves a queue for hours and an ordinary burst leaves one for minutes.

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
Ordinary variation: 8% of routes use a spare van, 30% get a revised manifest, 7% end early, 2% of stops are skipped
and recorded as not attempted, an end-of-day stock check at 21:30 scans every parcel on the shelf (a returned parcel
nobody scanned in sits in the returns cage and is missed half the time), Friday has no last-mile delivery, at most 3
attempts.

Bookings: B2C .60, C2C .25, B2B .15; EXPRESS 30% (B2C), 20% (C2C), 10% (B2B); 1-3 parcels (B2C/C2C), 2-5 (B2B), 15%
of B2B shipments bulky; weights lognormal by flow; declared weight within about 2.5% of the truth (2.5% of senders
guess: 5-30% off). Recipients have an
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

**Cause and exposure.** A mechanism is a cause for a shipment only where it produced a deviation: a missed connection,
route or plan deadline, a record held past a monitor deadline, a tolerance breach, a failed or misrecorded handover.
Everything else it touched is an exposure: recorded, never scored, never a label. The rule per mechanism is in the
table; `physical.py` decides it from the physical log (`mark` / `expose`), with a shadow queue per facility (the same
arrivals served as if no backlog had ever acted) and a shadow tour per route (the stops it would still have reached
without the time lost to an incident); `observe.held_past_deadline` decides it for device faults.

| Mechanism | Where it is placed (parameters) | It is a cause when | Cause code | Resolution / action | Natural recovery |
|---|---|---|---|---|---|
| DEVICE_OUTAGE | a driver app, a depot or hub handheld, a sorter reader: a window covering 2-3 shipments' records; a phone dies before the day's last stops and stays off until the next morning (60%) or for 0.5-6 h more; a facility device for 0.5-4 h more | a buffered record is held past a monitor deadline (the plan's latest time plus 900 s, the session end plus grace plus 900 s, or a later custody record of the parcel arriving first) at a monitor tick | DELAYED_SYNC | AUTO / REQUEST_DEVICE_SYNC | reconnect at window end; every buffered record uploads, the reconnect heartbeat reports the buffer |
| PARTIAL_UPLOAD_LOSS | a handheld or driver app, 35-60% of its records in the window stuck until the app is restarted (0.5-6 h later) or the nightly sync at 02:30 | as above | DELAYED_SYNC | AUTO / REQUEST_DEVICE_SYNC | restart or nightly sync; heartbeats show a pending queue meanwhile |
| SCAN_SKIPPED_AT_RECEIPT | a clerk shift: a window at a depot (each receipt not scanned with propensity 0.35-0.6) or at a hub dock (each container waved through with that propensity) | the receipt was not scanned | CUSTODY_GAP | AUTO / INITIATE_CUSTODY_RECONCILIATION | next handling scan shows the parcel moved on |
| FACILITY_BACKLOG | a sort before the evening cutoffs or a depot while the morning feeder is shelved, where parcels have under 2.2 h of slack; capacity x0.12-0.25 from the first arrival until 2.2-3.2 h after the last | the parcel misses the departure or the morning route it would have made, or the plan's deadline at that facility | HUB_DELAY | AUTO / REQUEST_HUB_CHECK | queue drains onto later departures |
| LATE_LINEHAUL | a linehaul or feeder trip: held at origin 2.5-6 h, or a breakdown of 3-8 h at 20-70% of the way | the parcel misses its onward connection, its morning route or the plan's deadline at the destination | ROUTE_DELAY | AUTO / PRIORITIZE_NEXT_SESSION | trip completes late; parcels take later connections |
| MISSORT | a container loaded onto another lane's truck (the dock scan records the intended trip), or a sorter chute mapped to another depot's bag for 1-5 h (each parcel inducted then with propensity 0.3-0.5) | the parcel went to the wrong site | HUB_DELAY | AUTO / REQUEST_HUB_CHECK | receiving hub or depot sends it back (about a day) |
| ASSIGNED_NOT_LOADED | a rushed loading of one route: each manifest parcel left on the shelf with propensity 0.12-0.28 | the parcel was left | CUSTODY_GAP | HUMAN / INITIATE_CUSTODY_RECONCILIATION | stock check scans it; re-planned next day |
| DELIVERY_SCAN_SKIPPED | a driver on a route who does not finish the app flow: each delivery with propensity 0.2-0.4 | delivered with no attempt, proof or scan | UNRECONCILED_CUSTODY | HUMAN / INITIATE_CUSTODY_RECONCILIATION | 40% of recipients later confirm receipt |
| RETURN_SCAN_SKIPPED | a check-in waved through: each returned parcel of the route with propensity 0.6-0.9 | back on the shelf without a return scan | UNRECONCILED_CUSTODY | HUMAN / INITIATE_CUSTODY_RECONCILIATION | a stock check finds it (that evening half the time), or it is loaded again |
| CONTRACTOR_RETAINS | a contractor's or independent driver's route: what is left on board is kept after the shift, or the driver leaves the route early with the last 1-4 stops (no attempts recorded for them) | the parcel stayed with the driver | UNRECONCILED_CUSTODY | HUMAN / PHYSICAL_CUSTODY_CHECK | 50%: returned 20-52 h later |
| UNRECORDED_HANDOFF | a depot-day: 1-3 of one driver's remaining stops passed to another driver | the parcel changed vehicle without a record | CUSTODY_GAP | AUTO / INITIATE_CUSTODY_RECONCILIATION | delivered by the other driver; custody record stays inconsistent |
| RECIPIENT_UNAVAILABLE | one recipient away for 2-4 days | an attempt failed because nobody was there (not when it failed for another reason) | RECIPIENT_UNAVAILABLE | AUTO / PRIORITIZE_NEXT_SESSION | later attempt succeeds or attempts run out |
| WRONG_ADDRESS | one booked address is outdated (recipient lives 2-9 km away) | an attempt was made at the old address | ADDRESS_CONFLICT | AUTO / REQUEST_ADDRESS_CONFIRMATION | 85%: a dated portal correction 0-30 h after the failed attempt |
| WRONG_GATE | one recipient's navigation pin at another compound gate | an attempt recorded the other gate | WRONG_GATE | AUTO / REQUEST_ADDRESS_CONFIRMATION | recipient guides the driver or fixes the instruction |
| OTP_NOT_RECEIVED | an SMS carrier-route outage window (shared) or one recipient's number | the code and its resend both failed | PROOF_INSUFFICIENT | AUTO / REQUEST_ADDITIONAL_EVIDENCE | gateway recovers; 35% of drivers override without a code |
| NEIGHBOUR_RECEIVES | a driver's habit on a route: where the recipient is out, the parcel goes to whoever is next door with propensity 0.6-0.9 (driver called first in 55%) | handed to a neighbour | DELIVERY_DISPUTE | HUMAN / DELIVERY_DISPUTE_REVIEW | 65%: non-receipt report 2-30 h later; else 21%: confirmation |
| MISDELIVERY | a driver new to an area: each consumer stop of the route left at a building 80-450 m away with propensity 0.12-0.25 | left at the wrong building | POSSIBLE_MISDELIVERY | HUMAN / DELIVERY_DISPUTE_REVIEW | 85%: non-receipt report 3-40 h later |
| LABEL_MISREAD | a reader that misreads for 1.5-8 h (a sorter reader 70%, a depot handheld 30%): each read with propensity 0.12-0.28; one to four digits wrong (50 / 25 / 15 / 10%) | the read differs from the manifest | BARCODE_MISMATCH | AUTO / REQUEST_RESCAN | next read is right |
| WRONG_LABEL_APPLIED | a label batch mixed up at an origin counter for 1-6 h: each parcel with propensity 0.3-0.6 gets the previous order's label (a real other parcel's barcode) or a label of an order outside this world (a near serial) | every read returns the other barcode | BARCODE_MISMATCH | HUMAN / REQUEST_RESCAN | none: every read is wrong |
| SCALE_DRIFT | an induction scale, +12-45% (70%) or -12-45%, 1.5-8 h | the weighing breaches the tolerance (max 0.5 kg, 10%) and a true weighing would not | WEIGHT_MISMATCH | AUTO / REQUEST_REWEIGH | recalibration; the depot check scale disagrees |
| DECLARED_WEIGHT_WRONG | one declaration x0.55-0.88 or x1.14-1.9 (the same range as a drifting scale) | the true weight breaches the tolerance | WEIGHT_MISMATCH | HUMAN / REQUEST_REWEIGH | none: every scale agrees with each other |
| MANIFEST_ERROR | a route revision drops a loaded parcel; every shipment on the route gets its version-2 line | the parcel was dropped | MANIFEST_CONFLICT | HUMAN / MANIFEST_RECONCILIATION_REVIEW | none |
| TRAFFIC_DISRUPTION | a road closure or accident shuts a district to vans from before the day's last 1-3 stops there until the evening | a stop left for later was still closed at the end of the route, or the route ran out of time over stops it would have reached without the time lost | TRAFFIC_DELAY | AUTO / PRIORITIZE_NEXT_SESSION | next session delivers |
| CUSTOMER_COMPLAINT | a non-receipt claim on a parcel handed to its recipient with complete proof | always (it needs a person) | DELIVERY_DISPUTE | HUMAN / DELIVERY_DISPUTE_REVIEW | 40% of claims followed by "found it" |
| DUPLICATE_EVENTS | provider retransmission (driver app 5%, carrier EDI 4%, SPL core 0.6%, telematics/messaging 1%) | never (an exposure) | none | NONE (idempotency only) | the gateway de-duplicates |
| ROUTINE_FAILED_ATTEMPT | never scheduled: every failed attempt no scheduled mechanism produced (not home, asked for another day, building not found, access refused, code not given, stop not attempted) | always a cause of that attempt; it needs an answer when the shipment misses its promise or the monitor's rules flag the attempt (unreached and an unanswered call) | by reason: RECIPIENT_UNAVAILABLE, ADDRESS_CONFLICT or ROUTE_DELAY | AUTO / PRIORITIZE_NEXT_SESSION, or NONE | next session |

Only six scheduled mechanisms are placed on one parcel or one recipient, because their cause is local: a wrong
declaration, an outdated address, a wrong navigation pin, a recipient away, a phone number that cannot be reached, a
customer's own claim. Every other fault belongs to an actor, a device, a facility or a window and touches several
parcels at a rate below one, so the other parcels of the same driver, route, shift, device or window are evidence.

**Ordinary operation** (origin `base`, real-frequency, never topped up; instances of the same mechanisms, mostly
exposures): a driver phone off the network for 15 min to 5 h (6% of driver-days) or from the afternoon until the next
morning (1.5%); a facility handheld off for 20-150 min (3% of days); upload retries until the app is restarted (3% of
driver-days, 15-35% of records); rush-hour congestion in the three large cities (70% of rush hours, travel x1.15-1.9);
a truck held at origin for 50-150 min (3% of trips); a misread by any reader (0.4% of reads); a sender's rough weight
estimate (2.5% of parcels, 5-30% off); a status question from a recipient (3%, never a cause). They give healthy
shipments long upload delays, heartbeat gaps and slow routes, and they are a cause only where something was missed.
The device-management agent also sleeps for 45-240 min on 5% of device-days (no heartbeat, records still upload, no
mechanism): a heartbeat gap alone is not an outage.

**Scenario weighting** (addendum B4). The over-sampling rates are committed in `config.py` (`MECHANISM_RATES`: 0.02
for every scheduled mechanism, the same in history and live splits, so history is a fair prior). A rate is the minimum
share of a split's shipments on which the mechanism must be the CAUSE of a deviation; the scheduler places instances
and re-simulates (up to eight rounds, because a fault changes the flows) until `max(1, round(rate x shipments))` is
reached in every split (600-shipment world: history 5 of 274, development 5 of 254, held-out 1 of 72). A shipment that
already carries a scheduled cause is avoided when the next one is placed, and a fault is placed on one of the
resources that fit the need at random, never by a rule such as "the smallest that fits" (which would tie a mechanism to
the same facilities in every world). `world_manifest.json` records the rates and targets; what they achieved is in the
truth directory. These are scenario weights, not real frequencies.

### Size and the clean-case floor

A clean case is a development case the monitor opened whose only cause is the mechanism. The review asked for at least
10 per mechanism and per family, reached by more shipment-days, not by density. `validate.coverage` reports it
(`clean_case_floor`). At 600 shipments (254 in development) no scheduled mechanism reaches 10: the counts are 0 to 6,
and five have none. A backlog or a late truck that makes a parcel miss a connection without breaching a plan deadline
opens no case on its own; a recipient away or a return nobody scanned always comes with the failed attempt before it;
a closed road leaves a stop unattempted, which no monitor rule flags. The same report estimates, from the measured
yield, the development size that would reach the floor at these rates: 424 to 2,540 shipments depending on the
mechanism. The brief's own floor (10 caused shipments per mechanism in development) needs a development split of 500
shipments at this rate; the planned 2,000 / 9-day world has about 650. Raising the rate instead would make nearly every
shipment faulty: at 0.02 about half of the development shipments already carry a scheduled fault, which is far above
any real rate and is the price of having every mechanism present in 254 shipments. The gate is therefore the
committed-rate target; both floors are reported, not met.

Ordinary variation that is not a mechanism: processing and transit jitter, 10% of trips leave 15-45 min late, uploads
take seconds to minutes (driver app median 45 s with 4% batched 8-40 min; handheld median 25 s with 2% batched 5-25
min), sorter no-reads (2%) go to a manual scan, SMS failures (2.5%; a failure receipt arrives only after the carrier's
retry window, lognormal median 2 h clipped to 40 min-8 h, a delivered receipt in 3-40 s), out-for-delivery messages at
route manifest publication, a call to the recipient's number in 55% of code failures, OTP resends (12%), a code not
given (3%), building not found (1.5%), access refused (5% at compounds, 1% elsewhere), 8% of driver reason codes filed
as OTHER, family members and authorised alternates, leave-at-door, GPS fixes that drift in dense blocks (1.2%), minor
address corrections (2.5%), routine reschedule requests and thank-you messages, retransmissions and out-of-order arrival.

## 4. Evidence schema

Every existing kind uses the property schema of `dataset_v2/generate.py` and `network.py`; additions are extra reference
properties. Every per-parcel observation is shipment-owned (`holdout_group` = shipment id). Sharing is expressed through
shared reference ids on those records and through shared nodes.

New kinds (all additive in `contracts.py`, `context.py`, `feed.py`, `operations/ingestion.py`). The gateway accepts the
mechanism world's wider set only for datasets whose id starts with `DEMO-SUHAIL-WORLD` (`feed.ingestible_kinds`); the
live-network gateway accepts exactly what it accepted before (tested):

| Kind | Group | Properties | Delivered by |
|---|---|---|---|
| Container | shared, dated | occurred_at (the WMS opens it a few minutes before the first parcel goes in), container_type (chosen then, from the lane), origin_facility_id, destination_facility_id | imported if recorded by the live start, else feed (SPL_CORE) |
| Trip | shared, dated | occurred_at (schedule publication, 72 h ahead), trip_type, lane_id, from/to_facility_id, start_at/end_at (scheduled), cutoff_at, vehicle_id, driver_id, provider_id, distance_km. Every scheduled departure is published, whether or not it later runs | imported if published by the live start, else feed |
| RouteRun | shared, dated | occurred_at (the morning's planning), depot_id, service_date, vehicle_id, driver_id, provider_id, device_ref, start_at/end_at, planned_stops | imported if planned by the live start, else feed |
| Lane | shared catalog | lane_type, from/to_facility_id, stop_facility_ids, distance_km, departures_local, nominal_transit_seconds | imported |
| FacilityThroughput | shared observation | facility_id, start_at/end_at (hour), processed_count, queue_depth, nominal_capacity_per_hour, staffed_capacity_per_hour (what the shift on duty could process; a staff shortage lowers it, a jam or a congested dock does not), oldest_waiting_minutes | feed (SPL_CORE) |
| TripEvent | shared observation | trip_id, vehicle_id, event_type (HELD_AT_ORIGIN, DEPARTED, ETA_REVISED, ARRIVED, CANCELLED), estimated_arrival_at (the carrier's own estimate: nominal driving time for the distance left, to five minutes, plus its guess of a hold or a repair; never the simulated arrival; absent on ARRIVED and CANCELLED), reason_code | feed (CARRIER_EDI or SPL_CORE) |
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
  TrafficEvent (ordinary congestion and closures alike, graded LOW / MODERATE / HIGH from the measured slow-down with
  noise) and slow vehicle positions, so derive's TRAFFIC_DELAY code never fires in world-1.

Dated per-shipment context (DeliverySession, VehicleAssignment, a corrected AddressVersion and its LocationPin, the
Customer node of a person who took a parcel) reaches a shipment through the feed when it is recorded after the live
start; booking-time records (shipment, packages, parties, address v1, plan, route, milestones) are imported. A
DeliveryAttempt or delivery CustodyEvent made by another driver's app (an unrecorded handoff) names its own route run,
driver and vehicle and the job the parcel was dispatched on (`assignment_id`), so the mismatch is a relation to find,
not an empty field. Custody DELIVERED always names the consignee; the
HandoffEvidence names who physically took the parcel. No code value is ever stored.

## 5. Truth labels and physical state (`truth.py`, `export.py`; never imported, never in the repository)

Two private outputs, kept apart (addendum B1) and both outside the repository. `truth_directory` and `state_directory`
refuse any path inside the repository or under an `artifacts` directory. No module under `chat/operations` or `backend`
imports the `world` package or names either path (tested).

- **Truth labels**: `<truth-root>/<dataset_id>/`, default `C:\Projects\suhail-eval-truth\<export name>\<dataset_id>\`
  (or `SUHAIL_EVAL_TRUTH_ROOT`, or `--truth-root`). World level: `mechanisms.jsonl` (every instance with window,
  parameters, the shipments it caused something on and the ones it only touched), `record_index.jsonl` (evidence id ->
  act, device, times, mechanisms), `acts.jsonl`, `physical_events.jsonl`, `precedents.json`, `validation.json` (the full
  validation report), `manifest.json` (canary, truth hashes). Per export (`development/`, `held_out/`): `truth.jsonl`
  (one row per shipment of that export), `truth_manifest.json` (what the weighting achieved), `monitor_replay.json` and
  `monitor_replay_rows.jsonl`. Truth is per export because a spec may cite only records that export contains.
- **Physical world state** for the Stage 4 operational simulator: `<state-root>/<dataset_id>/<live split>/`, default
  `C:\Projects\suhail-sim-state\<export name>\...` (or `SUHAIL_SIM_STATE_ROOT`, or `--state-root`): `parcels` (true
  location timeline, custody list, status, attempts, true and declared weight, manifest and physical label barcode),
  `containers`, `devices` (every device, most with no window; offline windows with reconnect time and the records each
  buffered, stuck-upload windows and their records, scale offsets), `facility_capacity`, `trips` and `routes` as they ran,
  `recipients` (home point, registered point, gates, the gate navigation leads to, availability, away windows,
  SMS-unreachable windows), `messaging_outages`, `traffic` and a physical `events` log. It holds only the shipments of
  that export (never a later booking day). It names no cause code, mechanism or label (`physical_state_vocabulary`, a
  hygiene scan), but it records what really happened, so **causes can be worked out from it**. Its protection is where
  it lives and who may open it: no runtime module but the simulator, and never the investigator, its tools, the reviewer
  or an API.

The bundle under `artifacts/` holds only what is imported or fed (section 6).

`truth.jsonl` row:

```
truth_schema ("world-truth-3"), canary, shipment_id, split (world split), booking_day, booked_at, promise_at, service, flow,
healthy (no cause that needs an answer), physically_healthy (no fault among its causes),
first_opening (monitor replica: at, rule codes, symptoms), opening_explained,
mechanisms: [{mechanism_id, type, subtype, origin (scheduled|base|background), cause_code, acceptable_causes,
              resolution (AUTO|APPROVAL|HUMAN|NONE), action, fault, explains_opening, started_at, ended_at,
              discrimination, knowable_at_estimate,
              evidence_ids (this shipment's records the mechanism shaped), shared_evidence_ids, packages}],
exposures: [{mechanism_id, type, subtype, origin}]     touched without consequence: never scored, never a label
compatibility view: recipe, root_cause, acceptable_causes, expected_resolution, physical, key_evidence,
                    secondary_issue, knowable_at_estimate; final_location
```

`mechanisms` lists causes only. A mechanism **explains the opening** when one of the case's opening rule codes is one
it can raise (`mechanisms.RULE_CODES`); `acceptable_causes` and `root_cause` are built from the explaining mechanisms
only (all causes when the monitor did not open a case or none explains it). In the development replay 58 opened cases
accept one cause code, 44 two, 15 three and 10 four or more. Every failed attempt has a cause: the scheduled mechanism
that produced it, or ROUTINE_FAILED_ATTEMPT with the cause read from the attempt's reason.

**Discrimination spec** (addendum A1). Knowable is not "first evidence reaching the gateway". For each mechanism on a
shipment, `discrimination` holds the evidence that separates it from the other mechanisms that open with the same
symptoms:

```
{"opening_symptoms": [...],                  the shipment's first opening in the monitor replica
 "shares_opening_with": [cause codes],       other causes that explain cases with that opening symptom set in this world
 "alternative_mechanisms": [types],
 "any_of": [{"all_of": [item, ...]}, ...]}
item = {"record": evidence_id}               satisfied once that record has been ingested
     | {"absence": {"expected", "match" (kind, equal properties, occurred window), "expected_by", "threshold_seconds": 900,
                    "overdue_at" (= expected_by + 900 s, the monitor's threshold), "cancelled_by" (every record in the
                    world matching `match`; validated empty, so the absence is real)}}
                                             satisfied at t when t >= overdue_at and nothing in cancelled_by was ingested
```

Every group holds at least one item of the shipment itself: one of its own records (its weighing on that scale, its
record made through that device or one that places its parcel with it, its scan at that facility, its record on that
trip, its not-attempted stop in that closure) or an absence about its own parcel. A shared record alone (a heartbeat, a
throughput report, another parcel's weighing) never makes a cause knowable, so nothing is knowable before the shipment
is booked or before its own linking record has arrived. A silent device or a pending upload queue counts for a
shipment only once the parcel's own record has been made through that device: for every mechanism whose effect is a
record of the shipment, nothing is knowable before that record was made (validated:
`EVERY_GROUP_HAS_AN_ITEM_OF_THE_SHIPMENT`, `ESTIMATE_NOT_BEFORE_BOOKING`, `NOTHING_IDENTIFIABLE_BEFORE_BOOKING`,
`ESTIMATE_NOT_BEFORE_THE_SHIPMENT_WAS_AFFECTED`).

`labels_at(row, t, ingested)` decides from a run's actual ingestion log: `ingested` is the set of evidence ids recorded
at or before `t`. The log is time-aware: an imported record counts from its own `recorded_at`, a fed record from its
ingestion. It returns the cause codes of the mechanisms with at least one fully satisfied group, `[]` for a healthy
shipment, and `INSUFFICIENT_EVIDENCE` for an abnormal shipment nothing discriminates yet, which is then the correct
answer. `knowable_at_estimate` is only a generator-side convenience (the spec evaluated with every record ingested at
its provider-feed delivery time); `labels_at_estimate` uses it.

**Canary** (addendum B2): every truth row carries `CNRY` + 24 hex characters derived from the seed and dataset id. The
export scan (nodes, edges, feed), the state scan and the database scan (`check`) require zero hits for the canary,
every mechanism id (`W1M-#####`) and every mechanism name (names that are also catalogue cause codes, such as
WRONG_GATE, are allowed only on derived case and history fixture nodes).

### Which mechanisms share opening symptoms, and what discriminates them (addendum A1)

From the committed 600-shipment world (seed 20261010; truth in the external directory). The first two columns are over
the whole world and count only cases the mechanism explains: the opening symptom sets of those cases, and the other
mechanisms that explain cases with the same opening symptom sets. The last column is the development monitor replay:
cases opened that the mechanism explains, of which ambiguous (another cause code shares the opening symptoms),
identifiable at the opening tick and by the end of the horizon under `labels_at` with the replay's own ingestion times.
DUPLICATE_EVENTS is never a case and is omitted.

| Mechanism | Opening symptom sets it explains (world) | Shares them with (world, most frequent first) | What discriminates it | Development: opened / ambiguous / identifiable at opening / by horizon end |
|---|---|---|---|---|
| ASSIGNED_NOT_LOADED | SESSION_END_UNRECONCILED (9); MILESTONE_OVERDUE (5) | ROUTINE_FAILED_ATTEMPT (25), PARTIAL_UPLOAD_LOSS (17), SCAN_SKIPPED_AT_RECEIPT (17), MISSORT (13), DELIVERY_SCAN_SKIPPED (12) | no load confirmation of the parcel by the route's departure (overdue by 900 s) while the route's other parcels were confirmed, or the evening stock-check scan finding it on the depot shelf | 5 / 5 / 5 / 5 |
| CONTRACTOR_RETAINS | SESSION_END_UNRECONCILED (5); MILESTONE_OVERDUE (4) | ROUTINE_FAILED_ATTEMPT (25), ASSIGNED_NOT_LOADED (14), DELIVERY_SCAN_SKIPPED (12), RETURN_SCAN_SKIPPED (9), MISSORT (9) | the parcel's load confirmation on the route, the driver app's heartbeats overdue and no check-in of the route by session end plus grace (both overdue by 900 s) | 5 / 5 / 2 / 5 |
| CUSTOMER_COMPLAINT | RECIPIENT_REPORTED_NOT_RECEIVED (8) | none | the recipient's message together with the delivery proof of the parcel | 4 / 0 / 4 / 4 |
| DECLARED_WEIGHT_WRONG | WEIGHT_READ_DIFFERS (10); CUSTODY_TRANSFER_UNCONFIRMED + WEIGHT_READ_DIFFERS (1) | SCALE_DRIFT (24), LABEL_MISREAD (3), DEVICE_OUTAGE (1) | the parcel's own sort weighing together with the destination check weigh agreeing with it, or with a nearby weighing on the same scale that agrees with its own declaration | 6 / 1 / 6 / 6 |
| DELIVERY_SCAN_SKIPPED | SESSION_END_UNRECONCILED (9); MILESTONE_OVERDUE (3) | ROUTINE_FAILED_ATTEMPT (25), ASSIGNED_NOT_LOADED (14), CONTRACTOR_RETAINS (9), RETURN_SCAN_SKIPPED (9), MISSORT (9) | the recipient's receipt confirmation, or: loaded on the route, the route checked in, no return scan of the parcel by session end and no stock-check scan of it that evening | 4 / 4 / 0 / 4 |
| DEVICE_OUTAGE | CUSTODY_TRANSFER_UNCONFIRMED (9); CUSTODY_TRANSFER_UNCONFIRMED + WEIGHT_READ_DIFFERS (1) | ROUTINE_FAILED_ATTEMPT (25), SCAN_SKIPPED_AT_RECEIPT (17), PARTIAL_UPLOAD_LOSS (15), MISSORT (13), UNRECORDED_HANDOFF (9) | a record of the shipment made through the device arriving long after it happened; or the device's heartbeats overdue (two intervals plus 900 s), or its reconnect heartbeat reporting the buffered queue, together with a record of the shipment that places its parcel with that device (its route, its facility, an inbound trip) | 4 / 4 / 4 / 4 |
| FACILITY_BACKLOG | MILESTONE_LATE (4); MILESTONE_OVERDUE (2) | ROUTINE_FAILED_ATTEMPT (25), MISSORT (9), LATE_LINEHAUL (6), ASSIGNED_NOT_LOADED (5), WRONG_ADDRESS (5) | the facility's throughput report for the hours of the backlog (processed far below what the shift could do, the oldest item waiting for hours), together with the parcel's own scan at that facility | 6 / 6 / 6 / 6 |
| LABEL_MISREAD | BARCODE_READ_DIFFERS (15); BARCODE_READ_DIFFERS + WEIGHT_READ_DIFFERS (3) | WRONG_LABEL_APPLIED (13), SCALE_DRIFT (2), DECLARED_WEIGHT_WRONG (1) | the next read of the same label, which returns the manifest barcode; at once when the read is one digit off the manifest barcode (it fails the check digit, so no printed label reads so) | 8 / 1 / 5 / 8 |
| LATE_LINEHAUL | MILESTONE_OVERDUE (5); SESSION_END_UNRECONCILED (2) | ROUTINE_FAILED_ATTEMPT (25), ASSIGNED_NOT_LOADED (14), DELIVERY_SCAN_SKIPPED (12), CONTRACTOR_RETAINS (9), RETURN_SCAN_SKIPPED (9) | the carrier's trip status (departure delay notice, ETA revision) or its stationary positions, together with the shipment's own record on that trip (its assignment, its container scan) | 3 / 3 / 3 / 3 |
| MANIFEST_ERROR | MANIFEST_CUSTODY_CONFLICT (8); DELIVERY_ATTEMPT_FAILED + MANIFEST_CUSTODY_CONFLICT (1) | ROUTINE_FAILED_ATTEMPT (1) | the revised route manifest without the parcel (for a one-parcel shipment: an empty line), together with the parcel's load confirmation on that route | 4 / 1 / 4 / 4 |
| MISDELIVERY | CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE (12) | NEIGHBOUR_RECEIVES (9), OTP_NOT_RECEIVED (5) | the proof or photo location away from the address, or the recipient's non-receipt report | 6 / 6 / 6 / 6 |
| MISSORT | MILESTONE_OVERDUE (9); CUSTODY_TRANSFER_UNCONFIRMED (4) | ROUTINE_FAILED_ATTEMPT (25), SCAN_SKIPPED_AT_RECEIPT (17), PARTIAL_UPLOAD_LOSS (15), DEVICE_OUTAGE (10), UNRECORDED_HANDOFF (9) | a receipt or handling scan of the parcel at a site other than its planned one; its assignment to a lane that is not in its journey plan | 3 / 3 / 3 / 3 |
| NEIGHBOUR_RECEIVES | CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE (9); CUSTODY_TRANSFER_UNCONFIRMED (2) | SCAN_SKIPPED_AT_RECEIPT (17), PARTIAL_UPLOAD_LOSS (14), MISDELIVERY (12), UNRECORDED_HANDOFF (9), DEVICE_OUTAGE (9) | the handoff evidence naming a person other than the recipient, with no authorisation on record | 5 / 5 / 3 / 5 |
| OTP_NOT_RECEIVED | CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE (5); MILESTONE_OVERDUE (3) | ROUTINE_FAILED_ATTEMPT (25), SCAN_SKIPPED_AT_RECEIPT (17), PARTIAL_UPLOAD_LOSS (15), MISSORT (13), MISDELIVERY (12) | a failed SMS delivery report for the one-time code | 5 / 5 / 3 / 5 |
| PARTIAL_UPLOAD_LOSS | CUSTODY_TRANSFER_UNCONFIRMED (14); SESSION_END_UNRECONCILED (2) | ROUTINE_FAILED_ATTEMPT (25), SCAN_SKIPPED_AT_RECEIPT (17), ASSIGNED_NOT_LOADED (15), MISSORT (13), DELIVERY_SCAN_SKIPPED (12) | the stuck record of the shipment arriving late; or heartbeats that keep arriving but report a pending upload queue, together with a record of the shipment that places its parcel with that device | 11 / 11 / 11 / 11 |
| RECIPIENT_UNAVAILABLE | DELIVERY_ATTEMPT_FAILED (7); MILESTONE_OVERDUE (1) | ROUTINE_FAILED_ATTEMPT (49), WRONG_GATE (10), MISSORT (9), FACILITY_BACKLOG (6), WRONG_ADDRESS (6) | the unanswered contact attempts recorded with the failed attempt | 3 / 3 / 2 / 3 |
| RETURN_SCAN_SKIPPED | SESSION_END_UNRECONCILED (5); MILESTONE_OVERDUE (4) | ROUTINE_FAILED_ATTEMPT (25), ASSIGNED_NOT_LOADED (14), DELIVERY_SCAN_SKIPPED (12), MISSORT (9), CONTRACTOR_RETAINS (9) | the stock-check scan finding the parcel back on the depot shelf, or its load confirmation on a later route | 3 / 3 / 1 / 3 |
| ROUTINE_FAILED_ATTEMPT | MILESTONE_OVERDUE (25); DELIVERY_ATTEMPT_FAILED (24) | WRONG_GATE (10), MISSORT (9), RECIPIENT_UNAVAILABLE (8), WRONG_ADDRESS (6), ASSIGNED_NOT_LOADED (5) | the failed attempt record itself (reason and contact attempts); no fault elsewhere | 25 / 25 / 24 / 25 |
| SCALE_DRIFT | WEIGHT_READ_DIFFERS (22); BARCODE_READ_DIFFERS + WEIGHT_READ_DIFFERS (2) | DECLARED_WEIGHT_WRONG (11), LABEL_MISREAD (3) | the parcel's own weighing together with another parcel weighed on the same scale in the window, also off its declaration, or with the destination check weigh agreeing with the declaration | 8 / 0 / 7 / 8 |
| SCAN_SKIPPED_AT_RECEIPT | CUSTODY_TRANSFER_UNCONFIRMED (17) | PARTIAL_UPLOAD_LOSS (14), UNRECORDED_HANDOFF (9), DEVICE_OUTAGE (9), MISSORT (4), NEIGHBOUR_RECEIVES (2) | the parcel's next handling scan after the skipped receipt (it is physically there), together with the on-time receipt scans of the other parcels in the same container (the device worked) | 9 / 9 / 9 / 9 |
| TRAFFIC_DISRUPTION | MILESTONE_OVERDUE (4) | ROUTINE_FAILED_ATTEMPT (25), MISSORT (9), ASSIGNED_NOT_LOADED (5), WRONG_ADDRESS (5), LATE_LINEHAUL (5) | the traffic incident report for the district together with the shipment's not-attempted stop in it | 1 / 1 / 1 / 1 |
| UNRECORDED_HANDOFF | CUSTODY_TRANSFER_UNCONFIRMED (9) | SCAN_SKIPPED_AT_RECEIPT (17), PARTIAL_UPLOAD_LOSS (14), DEVICE_OUTAGE (9), MISSORT (4), NEIGHBOUR_RECEIVES (2) | another driver's app recording the parcel the first driver loaded (the attempt names a route run, driver and vehicle other than those of the job it was dispatched on) | 4 / 4 / 3 / 3 |
| WRONG_ADDRESS | MILESTONE_OVERDUE (5); DELIVERY_ATTEMPT_FAILED (1) | ROUTINE_FAILED_ATTEMPT (49), WRONG_GATE (10), MISSORT (9), RECIPIENT_UNAVAILABLE (8), ASSIGNED_NOT_LOADED (5) | the recipient's dated address correction (or address report) | 2 / 2 / 2 / 2 |
| WRONG_GATE | DELIVERY_ATTEMPT_FAILED (10) | ROUTINE_FAILED_ATTEMPT (24), RECIPIENT_UNAVAILABLE (7), WRONG_ADDRESS (1) | the attempt's recorded gate, which differs from the delivery instruction's gate | 5 / 5 / 5 / 5 |
| WRONG_LABEL_APPLIED | BARCODE_READ_DIFFERS (13) | LABEL_MISREAD (15) | the next read of the same label, which returns the same other-order barcode; at once when the barcode read is the manifest barcode of another parcel | 7 / 0 / 3 / 7 |

Two actionable instances of 446 in this world have no discriminator: an UNRECORDED_HANDOFF in development and an
ordinary DECLARED_WEIGHT_WRONG in held-out, whose records hold nothing the spec accepts. For them
INSUFFICIENT_EVIDENCE stays the correct answer.

Documented discriminators that a single record shows are listed in `validate.ACCEPTED_DISCRIMINATORS`; the tell
detector reports them apart from tells (in this world: a read one digit off the manifest barcode; a read returning
another parcel's barcode; an assignment to a lane outside the journey plan; a handoff to an "authorised alternate" with
no authorisation on record; an access failure with no gate recorded).

## 6. Splits and exports

One connected world, split by booking day (default 8 days from Thursday 2026-09-10: history days 1-4, development days
5-7 (Monday to Wednesday), held-out day 8; 9 days: 4/3/2; otherwise a third history, a sixth held-out). Four history
days let history cases be acted on and verified before the development window opens.

`export_bundle(build, live_split)` cuts by **time**, not by split:
- Everything recorded at or before the live start (local midnight of the live split's first day) is imported. Earlier
  booking days are the V2 split `history`; a history shipment is known as far as the live start, never later: its case,
  if the monitor would have opened one by then, is the case at its opening, and parcel-on-vehicle intervals are derived
  from the imported custody records only.
- Everything recorded after the live start travels the provider feed, whoever it belongs to: the live split's evidence,
  the later evidence of earlier booking days (most history shipments are still moving), and every later shared record
  (heartbeats, positions, throughput, trip and traffic status, and the dated transport records Trip, Container, RouteRun).
- Later booking days are absent from the export, from its truth and from its physical state.
- One documented exception: the booking-time context of a live shipment (its order, parcels, parties, address, plan and
  milestones) is imported stamped exactly at its booking, which is after the live start. That is the foundation
  contract the gateway, the monitor and the read model are built on (a booking is not a provider message, and the
  gateway accepts evidence only for shipments it already knows), and every existing reader filters by `recorded_at`.
  `validate.import_cut` and the `check` command count these records and fail on any other imported record from after
  the live start. Moving bookings into the feed needs a gateway change outside this stage's additive scope (section 9).

The bundle under `artifacts/world/<name>/` has the shape of `dataset_v2.live_bundle.export_live` (nodes, edges, gold,
feed jsonl; manifest, validation, statistics, feed_manifest json) without `truth.jsonl`, plus `world_manifest.json`
(configuration, committed rates and targets, counts, hashes) and `world_validation.json` (the verdict and the checks of
the importable data). It holds nothing private and nothing that names a mechanism's outcome: the scoring row of a live
shipment carries no assessment and no opening time (its snapshot is the end of the horizon for every live shipment),
and the monitor replay, the coverage and the tell reports are in the truth directory and in `docs/evals/`.

History precedents (`history.py`, addenda A2 and B5). Label-free: nothing in `history.py` reads truth labels. For every
history case the monitor opened by the live start, the action is the operations policy's default action for the
case's most specific rule code (15%: the default action of another code the case carried), and the outcome is verified
from the shipment's own evidence recorded between the action and verification: succeeded when re-assessing the
shipment no longer raises a rule code that opened the case, or when the evidence shows what the action was for
(`ACTION_EVIDENCE`); otherwise failed. Verification happens at most 20 h after the action and at least 30 min before
the live window starts. A history case is not imported as a precedent when its verification cannot finish before the
cut-off or when a mechanism instance that caused something on its shipment is still active at or after the cut-off
(`build.mechanism_active_until`: the end of the mechanism's window, the arrival of every record it shaped for the
shipment and of its discrimination evidence, and, for faults with no natural recovery, the moment the parcels left the
network). Provider retransmissions are exempt. The exclusion decision uses the generator's private record and is never
written into the graph. Development export: 59 history cases, 39 precedents (14 succeeded, 25 failed), 20 excluded.

## 7. Build, validate, export, import

From `chat/`:

```
uv run python -m world.export export --output ../artifacts/world/world-1-small-r4 --with-heldout --determinism \
    --eval-dir ../docs/evals/2026-10-10_world1_small [--truth-root DIR] [--state-root DIR] [--tell-seed N]
uv run python -m world.export apply ../artifacts/world/world-1-small-r4 --database shipments-v2-world-1-small [--replace]
uv run python -m world.export check ../artifacts/world/world-1-small-r4 --database shipments-v2-world-1-small \
    --ingest --out ../docs/evals/2026-10-10_world1_small/cypher.json
```

`export` refuses an existing export, truth or state directory and writes nothing unless every gating validation
passes; the truth directory is written first, then the state, then the bundles. `apply` only accepts database names
starting with `shipments-v2-world-` (and never the protected ones), reuses `apply_bundle`, `load_feed` and
`target_guard`, recomputes the foundation validation before importing, and creates the `world_*` lookup indexes.
`--replace` recreates that world database. `check` compares node and relationship counts with the bundle, resolves
every shared reference id, runs temporal checks (among them: nothing imported from after the live start but live
booking context), times the cross-shipment traversals and the PRECEDENTS query, and scans every node and relationship
property in the database (provider feed payloads included) for the canary, mechanism ids and mechanism names. With
`--ingest` it replays the whole feed through the real `operations.ingestion.Gateway` in six-hour steps, repeats the
checks and the scan on live evidence, and resets the live session.

**The time-correct predicate.** Every cross-shipment lookup must filter each record it returns through
`export.visible(alias)`: `recorded_at <= $as_of AND (occurred_at IS NULL OR occurred_at <= $as_of)`. Without it a
query reads the future (the later upload of a buffered record, a later day's route run). `export.traversals` uses it
for every node it matches (a test checks the source), and `check --ingest` proves it on the database: the traversals
run with the clock at a mid-simulation instant, then again AS OF that instant after the whole feed is in, and must
return the same rows, none recorded after it. Stage 2 tools must use the same predicate.

Validation (`validate.py`, all recomputed; everything gates the export unless marked reported):
- foundation: `dataset_v2.feed.validate_live_bundle` (which runs `validate_world`) on the reconstituted world. Two
  foundation rules cannot apply and have world replacements: PHYSICAL_CUSTODY_CHAIN (every violation must be flagged by
  derive as a CUSTODY_GAP and explained by a recording-fault mechanism on the shipment; the private chain must be
  continuous) and ADDRESS_VERSION_INTERVAL (a superseded version is never mutated; the newer dated version names it via
  supersedes_id, starts later and was recorded no earlier than it became valid). Any other failing rule fails the export.
- physics: one place at a time, custody matches location, custody continuity, container contents, conservation,
  facility stock never negative, vehicle capacity, one vehicle per driver, travel time vs distance, throughput within
  capacity, scans happen where the parcel is.
- observation: occurred <= recorded <= gateway; record time = event time; scans only from the device that made them;
  no heartbeat during an outage; every record of an offline device delayed; reconnect beat reports the buffer; stuck
  records arrive after the window and the queue is visible; duplicates share identity; out-of-order arrivals exist.
- isolation: no mechanism type, subtype, mechanism id, truth field, compatibility physical value, cause code or action
  name in any imported node or edge property (keys and values, including source_ref) or feed payload, and no canary.
  Derived Case/Exception and history-outcome nodes may carry catalogue codes (derive emits them from observations).
- import cut: nothing recorded or occurring after the live start is imported, except live booking context (counted);
  no imported interval reaches past it; the feed starts after it.
- forecasts: no carrier estimate equals the later arrival; a delay notice precedes the late departure. Other
  future-dated fields that coincide with a later event of the same shipment are listed (plan and validity fields).
- throughput separation: for every backlog that caused something, the oldest waiting item in its hours is older than
  in 95% of the facility's ordinary hours. Utilisation of staffed capacity is reported.
- tells: for each mechanism (except DUPLICATE_EVENTS), no single-record observable of a shipment (a categorical
  value, an absent value, a list length, a half-decade number bucket, an arrival-lag bucket, the gap between a read
  barcode or a weighing and the declaration, a value paired with an absent field of the same record) held by at most
  20% of shipments with precision >= 0.9 and support >= 5, in the development split or the whole world, unless it is
  that mechanism's documented discriminator (`ACCEPTED_DISCRIMINATORS`, reported apart).
- discrimination specs (world truth and each export's truth): every record item is an observation and is in that
  export; every absence item's `cancelled_by` equals a full-scan recomputation of its `match` and is empty; every group
  has an item of the shipment; every estimate recomputes and is never before the mechanism started or the shipment was
  booked; nothing is identifiable one second before booking with everything delivered by then counted as ingested.
- precedent cut-off: every history outcome verified (and every history fixture recorded) before the live window, and
  no authored precedent whose shipment had a mechanism active at or after the cut-off (recomputed).
- coverage: each scheduled mechanism is the cause of a deviation on at least min(10, target) development shipments.
  Reported: clean cases per mechanism and per family against the floor of 10, and the size that would reach it.
- monitor replay (hourly ticks from the live start, 900 s allowance): gating on "no cause identifiable before a
  shipment's booking" under the time-aware ingestion log. Reported: healthy false openings, openings without a
  scheduled fault, per-mechanism caused / opened / explained / clean, per opening symptom set, ambiguity.
- pre-run tell test (addendum B3, `tell_test`, gating): section 8.
- determinism: a rebuild gives identical hashes. Consolidation (container and route fill) is reported.

Tests: `tests/test_world_contracts.py` (S5 byte-identical regeneration, additive contract, the gateway rejecting
mechanism-world kinds for the live-network dataset, round trips) and `tests/test_world_build.py` (a 240-shipment
world plus a second seed: every validation section, causes versus exposures, a cause for every failed attempt,
acceptable causes from explaining mechanisms, own-item specs, nothing identifiable before booking, per-export truth, the
import cut, hindsight-free scoring rows, estimates, throughput reports, detector negative controls, the bundle, truth
and state directories and their guards, no truth or state path in backend or operations, the time-correct predicate in
every traversal, determinism).

## 8. Pre-run tell test (addendum B3)

A lookup classifier is trained on the development opening cases of this world and evaluated on those of a second
world built with another seed (default seed + 1). Keys are (opening symptom set, value) with training support of at
least 5 cases; the key with the highest training precision predicts its majority cause, else the baseline does. The
baseline predicts the training majority cause for the rule codes at opening, most specific first
(`monitor.SPECIFICITY`): the full code tuple, backing off to the most specific code, then the overall majority. A
prediction is correct when the truth accepts it for the case (the acceptable causes of the mechanisms that explain the
opening), as an evaluation run is scored. The stratum is the ambiguous cases: those whose opening symptom set another
cause code shares.

Three choices differ from the first build and need the product owner's confirmation; each is reported next to the
literal variant so the difference can be read:
1. **Features exclude the cause's own evidence.** The lookup sees every visible property value of the shipment at the
   opening except the records the explaining mechanisms themselves shaped or their specs cite (the failed attempt and
   its calls, the handoff naming another person, the buffered record). Reading that evidence is the investigator's
   task; a tell is a value outside it that still predicts the cause. The literal variant (all values) is reported as
   `with_the_mechanisms_own_evidence_as_features`.
2. **Both directions, pooled.** One direction is about 85 non-independent cases and its sign flips with any change of
   seed. The gate is: lookup correct in both directions together must not exceed baseline correct in both. Each
   direction is reported.
3. **Scored against acceptable causes** per opening, as the truth now defines them.

Result on the committed world (seed 20261010 against 20261011): forward lookup 43, baseline 45 of 84; reverse lookup
57, baseline 59 of 96; pooled lookup 100, baseline 104 of 180: pass. The literal variant also does not beat the
baseline here (forward 43 against 45, reverse 59 against 59).

What the report shows and the gate does not close: among the 12 forward ambiguous cases in which, by the truth's own
specs, nothing discriminating had arrived at the opening, the lookup is right in 9 and the baseline in 3. The features
behind it are the stage the shipment had reached (a tracking status of OUT_FOR_DELIVERY, a hub the parcel was planned
through): real context that the coarse rule codes do not carry, not a field planted by the generator. Among the 72
cases where discriminating evidence had arrived the lookup is worse than the baseline (34 against 42). Whether stage
context should count as part of what the monitor shows, or be balanced out of the generator, is the decision the first
build already asked for; it is still open.

Generator artifacts this test and the review exposed, all fixed in the generator: a neighbour handoff always followed
a call and a misdelivery never did; SMS failure receipts arrived within minutes; template versions drawn per message;
misdelivery and neighbour handoff on any delivery while code failures can only hit OTP deliveries; a fixed van per
collection run; the out-for-delivery message tied to the load record; a mechanism tied to the same facilities in every
world by a deterministic choice rule; arrival lags that separated an outage from a stuck outbox; a null job reference
on an attempt made by another driver.

## 9. What the independent review changed, and what is still open

Changed (details in the sections above): cause versus exposure and a cause for every failed attempt; acceptable causes
per opening; behaviour faults on actors and windows instead of sampled parcels; the same rate in history and live
splits, four history days and a lower density; capacity sized to demand and throughput reports that show a backlog;
carrier estimates from what the carrier knows, delay notices, cancellations; the import cut by time and the
time-correct predicate; ordinary operation with long upload delays, heartbeat gaps, held trucks, misreads and rough
weight estimates; specs that need an item of the shipment and a time-aware ingestion log; an extended tell detector;
overlapping misread and wrong-label reads and weight gaps; the physical state outside the repository, cut to the export,
listing every device; truth per export; no hindsight in the bundle; the gateway's wider kind set scoped to
mechanism-world datasets; the tell test gating.

Still open:
- **Clean-case floor not met at this size** (section 3). The 600-shipment world is a pipeline-proving world; the floor
  of 10 clean development cases per mechanism and per family needs the 2,000-shipment world or larger, and four
  mechanisms open no clean case under the present monitor rules at any size without a change of placement or of rules.
- **Density** is lower than the first build but still far above reality: 54% of development shipments have a cause
  that needs an answer (49% a scheduled fault, the rest ordinary failed attempts and the like), and 54 of 137 abnormal
  development shipments carry more than one cause (34 with two or more scheduled faults; 23 include an ordinary failed
  attempt). Shared faults still land on shipments that already carry one.
- **Booking context of live shipments is imported before its time** (8,501 records in the development export), by the
  foundation contract. Feeding bookings needs the gateway to accept new shipments, in `chat/operations`.
- **Tools** (Stage 2, `chat/operations`, not changed here): the existing investigation tools cannot reach evidence
  owned by another shipment or shared records (co-parcels on a device, scale, route run, container or trip; facility
  throughput; trip and traffic status; a shipment's communications), and truncate long results. Until Stage 2 adds
  them, with the time-correct predicate, no evaluation on this world can credit shared-cause diagnoses. The operations
  layer also still accepts only `shipments-v2-demo*` databases and the foundation `Config`.
- **Tell test**: the stage-context question in section 8, and the three choices listed there.
- Not every opening symptom set occurs without a scheduled fault. In the development replay it does for failed
  attempts, overdue milestones, weight differences, an unreconciled session and incomplete proof; it does not for a
  barcode difference alone, an unconfirmed custody transfer alone, a manifest conflict, a late milestone and a
  non-receipt report.
- Consolidation is thin at this volume (282 containers, 110 with one parcel, median 2; 361 scheduled departures
  cancelled empty, each with a dated cancellation).

## 10. Known limitations

- Scale and topology are simplified: 75 to 100 shipments a day, one sort and one hub per region, direct bagging to the
  destination depot, one morning dispatch, straight-line positions, no road graph, no returns-to-sender flow (parcels
  are held after three attempts), Fridays without last mile. Truck capacity never binds at this volume.
- The causal rules are explicit per effect, not a re-simulation without the mechanism. They cover what each mechanism
  is known to do; a consequence nobody wrote a rule for stays an exposure. In the development replay one opened
  abnormal case of 127 is explained by none of its shipment's causes, and two healthy shipments open a case (a parcel
  shelved too late for the route it was assigned to; a delivery proof whose GPS fix drifted).
- A wrong label and a chute error do not change where the parcel physically goes beyond what the table says: a parcel
  with another order's label is still routed by its own booking (the exception desk scans it by hand).
- History outcomes are authored after the fact from the world's own later evidence; the simulated world does not react
  to history actions. Precedents are a sample biased towards problems that surfaced and settled within the history days.
- Discrimination specs encode what separates a mechanism from the ones that share its opening symptoms in this world,
  as judged by the generator's author; they are machine-checkable but not exhaustive, and `shares_opening_with` is
  computed from one world's openings. `RULE_CODES` (which rule codes a mechanism can raise) is an authored table too.
- The backend's existing S5 simulator hook (`backend/operations_api.py attach_simulator`) reads `truth.jsonl` from the
  live-network bundle; world bundles have no such file, so it stays disabled for world data until Stage 4 reads the
  physical state.
- derive's ADDRESS_CONFLICT cannot fire (imported address versions are never closed) and TRAFFIC_DELAY never fires
  (no shipment-owned traffic records); a not-attempted stop raises no rule code. Outdated addresses and closed roads are
  therefore visible to the monitor only through a missed promise.
- The tell detector looks at single records of a shipment (and pairs of a value with an absent field); it does not test
  combinations across records, sequences or shared observations. The tell test covers value combinations only through
  the symptom set and uses one second seed.
- The export with the held-out bundle, the second-seed world and the determinism rebuild takes about 7.5 minutes; the
  database check with full ingestion takes 15 to 18 minutes (the gateway ingests about 70 to 85 messages a second).
