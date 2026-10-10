# world-1 small (600 shipments): evaluation outputs

Synthetic data only (`DEMO-SUHAIL-WORLD-1`, seed 20261010, 600 shipments booked over 6 days from 2026-09-12, 4-day
horizon). Generator and method: `chat/world/README.md`. Everything here was recomputed by the export and check commands
on 2026-10-10:

```
cd chat
uv run python -m world.export export --output ../artifacts/world/world-1-small --with-heldout --determinism \
    --eval-dir ../docs/evals/2026-10-10_world1_small            # 7 min 08 s wall, includes the determinism rebuild
uv run python -m world.export apply ../artifacts/world/world-1-small --database shipments-v2-world-1-small --replace
uv run python -m world.export check ../artifacts/world/world-1-small --database shipments-v2-world-1-small \
    --ingest --out ../docs/evals/2026-10-10_world1_small/cypher.json
```

| File | What |
|---|---|
| `validation.json` | every validation section of the development export (and the held-out export's foundation and isolation), digests, timings |
| `monitor_replay.json` | the monitor replay over the 305 live development shipments (aggregates only; per-shipment rows name mechanisms and live in the truth directory) |
| `monitor_replay_heldout.json` | the same for the held-out export (87 live shipments) |
| `cypher.json` | Neo4j counts, referential, temporal and isolation checks, timed traversals, PRECEDENTS, live ingestion |

Truth labels are in `C:\Projects\suhail-eval-truth\DEMO-SUHAIL-WORLD-1\` (outside the repository); bundles are in
`artifacts/world/world-1-small` and `artifacts/world/world-1-small-heldout` (not committed).

## Overall

All gating sections pass: physics, observation, foundation (documented exceptions only), coverage, single-value tell
detector, export isolation, private-state isolation, discrimination specs, precedent cut-off, determinism. **The pre-run
tell test (addendum B3) fails and is reported, not gating** (section "Pre-run tell test").

Digests: development feed `59660f2b...1095`, development V2 manifest `6c7b164e...8357`, held-out feed `a6204ec2...14cb`,
held-out V2 manifest `564d4246...b2`, truth `73fafed5...9c2b`, mechanisms `15f62791...c1c2`. A second build from the same
configuration reproduced every digest.

## Counts

| Split | Shipments | Healthy (no actionable mechanism) | With an actionable mechanism | Multi-cause |
|---|---|---|---|---|
| history (days 1-2) | 208 | 161 | 47 | 7 |
| development (days 3-5) | 305 | 96 | 209 | 78 |
| held-out (day 6) | 87 | 33 | 54 | 21 |

Development export: 38,743 imported nodes, 78,110 relationships, 53,902 feed messages (MDM 28,694, SPL_CORE 19,171,
DRIVER_APP 2,119, TELEMATICS 1,704, CARRIER_EDI 1,097, MESSAGING 956, RECIPIENT_PORTAL 124, TRAFFIC 37; 298 provider
retransmissions). 66 node kinds; largest: DeviceHeartbeat 6,683, ExpectedMilestone 4,999, RouteMilestone 4,999, ScanEvent
3,874, CustodyEvent 3,070, RouteSegment 2,407, StatusEvent 1,578. Held-out export: 25,573 feed messages.

Affected shipments per mechanism (history / development / held-out). Committed rates: history 0.005, live 0.036 per
scheduled mechanism, giving targets 1 / 11 / 3.

| Mechanism | H | D | HO | Mechanism | H | D | HO |
|---|---|---|---|---|---|---|---|
| ASSIGNED_NOT_LOADED | 1 | 11 | 3 | NEIGHBOUR_RECEIVES | 1 | 11 | 3 |
| CONTRACTOR_RETAINS | 2 | 12 | 3 | OTP_NOT_RECEIVED | 10 | 11 | 4 |
| CUSTOMER_COMPLAINT | 1 | 12 | 3 | PARTIAL_UPLOAD_LOSS | 1 | 15 | 3 |
| DECLARED_WEIGHT_WRONG | 1 | 11 | 3 | RECIPIENT_UNAVAILABLE | 1 | 11 | 3 |
| DELIVERY_SCAN_SKIPPED | 1 | 11 | 3 | RETURN_SCAN_SKIPPED | 1 | 11 | 4 |
| DEVICE_OUTAGE | 1 | 15 | 3 | ROUTINE_FAILED_ATTEMPT (background) | 5 | 8 | 0 |
| DUPLICATE_EVENTS (base rate) | 101 | 131 | 37 | SCALE_DRIFT | 4 | 24 | 3 |
| FACILITY_BACKLOG | 3 | 38 | 3 | SCAN_SKIPPED_AT_RECEIPT | 2 | 11 | 4 |
| LABEL_MISREAD | 1 | 11 | 3 | TRAFFIC_DISRUPTION | 7 | 14 | 5 |
| LATE_LINEHAUL | 1 | 14 | 4 | UNRECORDED_HANDOFF | 3 | 11 | 5 |
| MANIFEST_ERROR | 1 | 12 | 3 | WRONG_ADDRESS | 1 | 11 | 3 |
| MISDELIVERY | 1 | 11 | 3 | WRONG_GATE | 1 | 11 | 3 |
| MISSORT | 4 | 11 | 4 | WRONG_LABEL_APPLIED | 1 | 11 | 3 |

## Validation (development export unless noted)

- Physics: pass. 10,713 scans where the parcel was, 9,055 custody-location agreements, 5,861 location changes, 921
  containers' contents, 1,143 travel times, 250 hourly throughputs, 85 vehicle loads, 323 driver-vehicle checks; final
  locations: 889 parcels with a person, 19 on a vehicle, 13 in a facility.
- Observation: pass. 82,050 records occurred before recorded, 53,902 feed messages after recording, 298 duplicates share
  identity, 5 outages (no heartbeat during, every record delayed, reconnect beat reports the buffer), 4 stuck-upload
  windows (queue visible, records after the window); 2,596 out-of-order pairs on 592 shipments. Upload lag p50 / p90 /
  p99: ordinary 6 / 111 / 790 s; records shaped by a mechanism 39 / 8,879 / 49,825 s.
- Foundation (`validate_live_bundle`, 66 checks): only the two documented rules fail (PHYSICAL_CUSTODY_CHAIN 39,
  ADDRESS_VERSION_INTERVAL 23); all 39 custody discontinuities are flagged by derive and explained by a recording-fault
  mechanism; all 23 address versions are superseded by a dated version. Statistics: 296 of 513 shipments healthy with no
  case, 217 cases. Held-out export: same two rules only (52 and 27), 336 of 600 healthy with no case.
- Coverage: every scheduled mechanism reaches its development target of 11 (minimum required 10).
- Single-value tell detector (held by at most 20% of shipments, precision >= 0.9, support >= 5): no tells in the
  development split (305 shipments, 382 categorical features) or the whole world; no near misses at precision 0.7-0.9.
- Export isolation: no hit for 203 truth substrings (mechanism names and subtypes, `w1m-`, truth field names, physical
  truth values, the canary), 9 whole words, 43 cause/type tokens and 16 action tokens over 2,504,691 texts of nodes,
  relationships and feed payloads; canary hits 0, mechanism-id hits 0 (held-out export: pass, canary 0).
- Private physical state: no hit over 921 parcels, 248 containers, 12 devices, 126 routes, 284 trips, 600 recipients,
  1,271 events and the capacity, messaging and traffic windows.
- Discrimination specs (addendum A1): pass. 740 mechanism instances (463 actionable); 879 record items are observations of
  the world; 98 absence items recompute exactly and are real (no matching record exists); 740 estimates recompute; no
  estimate precedes its mechanism; the canary is in every row. Groups: 776 single-item, 71 two-item, 1 three-item, 14
  four-item. Two actionable instances have no discriminator (see `chat/world/README.md`).
- Precedent cut-off (addendum A2): pass. Development export: 46 history cases, 3 precedents authored (0 succeeded, 3
  failed), 43 not imported (32 with a mechanism active at or after the cut-off 2026-09-13T21:00Z, 11 not verifiable
  before it). Held-out export (cut-off 2026-09-16T21:00Z): 217 history cases, 86 precedents (34 succeeded, 52 failed),
  123 + 8 not imported. Every outcome verified, and every history fixture recorded, before the cut-off.

## Pre-run tell test (addendum B3): fails, reported

Lookup classifier trained on the 167 development opening cases of this world, evaluated on the development opening cases
of a second world (seed 20261011, 153 cases). Ambiguous stratum (another cause shares the opening symptoms): 150 cases.

| | Correct of 150 |
|---|---|
| Rule-code baseline (full code tuple, most specific first) | 82 (0.547) |
| Single most specific code baseline | 82 |
| Lookup (symptom set + every visible value, support >= 5) | **107 (0.713)** |
| Lookup without identifier values (diagnostic) | 102 |
| Reverse direction (train on seed 20261011, test here; 167 cases): baseline / lookup / lookup without identifiers | 101 / 104 / 101 |

Discordant cases: lookup right and baseline wrong 40, the reverse 15. Values behind the lookup's wins: out-for-delivery or
other SMS delivered at opening (14 wins, 4 losses; it marks a custody gap found mid-route, where handoffs happen,
rather than at depot receipt, where outages happen), one linehaul truck id (11, all from a single late-linehaul cluster
whose truck was also late in the training world), handoff evidence naming another person (6 wins, 4 losses), a
recipient report present (5), scan confidences (losses and wins, noise). The first run of this test exposed six
generator artifacts, all fixed in the generator (listed in `chat/world/README.md`, "Pre-run tell test: findings"); what
remains is stage context the coarse rule codes do not carry and small-pool resource coincidences. It needs a decision
(rebalance fault placement per stage, or accept stage context as part of what the monitor shows); until then it is a
known blocking finding.

## Monitor replay (development, hourly ticks, 900 s allowance)

305 live shipments. Healthy: 96, of which 4 opened a case (false-positive rate 4.2%), all with CUSTODY_TRANSFER_UNCONFIRMED
+ DELIVERY_PROOF_INCOMPLETE. Abnormal: 209, of which 167 opened and 42 never did; per mechanism the largest unopened
shares are shared mechanisms (backlog 17 of 38 touched shipments, scale drift 7 of 24, traffic 6 of 14, late linehaul 5
of 14; a shipment can count under several). Of the 167 opened: 40 unidentifiable at the opening tick (`labels_at` gives INSUFFICIENT_EVIDENCE), 127
identifiable at opening, all 167 identifiable by the end of the horizon.

Identifiable ambiguous cases (addendum B4): every opened abnormal case here is ambiguous (each opening symptom set is
shared by several causes), so a 600-shipment world yields **167 identifiable ambiguous development cases**, 40 of them
identifiable only after the opening. An evaluation world needs about 600 shipments (6 days) for 150 such cases, or about
2,250 shipments (scaled at the same committed rates) for 150 cases that are unidentifiable at the opening and become
identifiable later.

Alert-to-mechanism table (opening symptom set: shipments; distinct mechanisms on them; mechanisms on the single-cause
shipments):

| Opening symptoms | Shipments (healthy) | Distinct mechanisms | Single-cause shipments by mechanism |
|---|---|---|---|
| DELIVERY_ATTEMPT_FAILED | 35 (0) | 19 | WRONG_GATE 5, CONTRACTOR_RETAINS 3, ROUTINE_FAILED_ATTEMPT 3, WRONG_ADDRESS 2, nine others 1 each |
| CUSTODY_TRANSFER_UNCONFIRMED | 27 (0) | 14 | MISSORT 5, PARTIAL_UPLOAD_LOSS 4, UNRECORDED_HANDOFF 4, DEVICE_OUTAGE 2, SCAN_SKIPPED_AT_RECEIPT 1 |
| BARCODE_READ_DIFFERS | 21 (0) | 17 | WRONG_LABEL_APPLIED 6, LABEL_MISREAD 4 |
| CUSTODY_TRANSFER_UNCONFIRMED + DELIVERY_PROOF_INCOMPLETE | 21 (4) | 8 | MISDELIVERY 5, NEIGHBOUR_RECEIVES 4, OTP_NOT_RECEIVED 2 |
| MILESTONE_OVERDUE | 20 (0) | 14 | ROUTINE_FAILED_ATTEMPT 5, MISSORT 2, five others 1 each |
| WEIGHT_READ_DIFFERS | 17 (0) | 14 | DECLARED_WEIGHT_WRONG 4, SCALE_DRIFT 2 |
| SESSION_END_UNRECONCILED | 16 (0) | 11 | DELIVERY_SCAN_SKIPPED 5, ASSIGNED_NOT_LOADED 4 |
| MANIFEST_CUSTODY_CONFLICT | 5 (0) | 4 | MANIFEST_ERROR 3 |
| RECIPIENT_REPORTED_NOT_RECEIVED | 5 (0) | 1 | CUSTOMER_COMPLAINT 5 |
| four rarer combinations | 4 (0) | 1-3 each | NEIGHBOUR_RECEIVES 1 |

Every frequent opening symptom set is produced by several mechanisms; within single-cause shipments the pairs that must be
told apart by investigation are WRONG_LABEL_APPLIED vs LABEL_MISREAD, DECLARED_WEIGHT_WRONG vs SCALE_DRIFT,
DELIVERY_SCAN_SKIPPED vs ASSIGNED_NOT_LOADED, MISDELIVERY vs NEIGHBOUR_RECEIVES vs OTP_NOT_RECEIVED, and the custody-gap
family (MISSORT, PARTIAL_UPLOAD_LOSS, UNRECORDED_HANDOFF, DEVICE_OUTAGE, SCAN_SKIPPED_AT_RECEIPT).

## Neo4j (`shipments-v2-world-1-small`, the only database written)

Import (`apply --replace`): 38,743 nodes plus the import marker, 78,110 relationships and 53,902 pending provider-feed
items; 22 `world_*` lookup indexes; read and validate 23.6 s, import and feed 213.3 s (4 min 01 s wall). The check
(`check --ingest`, 18 min 28 s wall) passed:

- Counts: nodes 38,743 = manifest, relationships 78,110 = manifest, feed items 53,902 = bundle; per-kind and
  per-relationship counts match.
- Referential: 66,167 shared reference ids resolved, none missing, no cross-shipment relationship; after live
  ingestion 202,008 resolved, none missing.
- Temporal (before and after ingestion): 0 records recorded before they occurred, 0 inverted milestone, interval or
  assignment windows, 0 development records imported after booking, 0 custody events recorded before their source scan,
  0 feed items delivered before their event, 0 nodes ingested before they occurred.
- Isolation scan (addendum B2): every node and relationship property, provider-feed payloads included, scanned for the
  canary, the 584 mechanism ids (and the `W1M-#####` pattern) and 50 mechanism-name forms: 0 hits over 170,756 records
  as imported (85.7 s) and 0 over 308,007 after ingesting the whole feed (188.1 s).
- Live ingestion through `operations.ingestion.Gateway` to the end of the horizon: 53,902 messages, 53,604 ingested,
  298 duplicates recognised, 0 conflicting duplicates, 0 rejected, 798.3 s (about 67.5 messages/s). The live session was
  reset afterwards (0 live nodes left, all feed items pending again).
- PRECEDENTS (`operations.read_model.PRECEDENTS`, all causes, far snapshot): 3 rows (INITIATE_CUSTODY_RECONCILIATION 2,
  REQUEST_RESCAN 1; all failed), median 11.7 ms.

Timed cross-shipment traversals (median / max of 5 runs, ms):

| Traversal | Imported history | After live ingestion |
|---|---|---|
| scans by one device in an offline window | 4.1 / 25.7 (1 shipment) | 5.9 / 8.4 (DEMO-DEV-HH-DEPOT-TUU-01: 10 scans, 5 shipments) |
| that device's heartbeats around the window | 3.8 / 20.4 (none imported) | 8.2 / 9.5 (7 beats, max pending 20) |
| shipments on one route run | 5.5 / 31.8 (11) | 9.0 / 16.7 (12) |
| parcels in one container | 4.7 / 22.5 (16 parcels, 9 shipments) | 8.2 / 8.6 (21 parcels, 14 shipments) |
| shipments on one trip and its trip events | 3.8 / 26.5 (36, 2 events) | 5.6 / 145.5 (36, 2 events) |
| custody events at one depot in 12 h | 4.2 / 21.7 | 5.5 / 6.1 |
| messages on one SMS carrier route around an outage | 4.0 / 21.1 (28 delivered, 32 failed) | 5.9 / 6.2 (33 delivered, 48 failed) |

## Tests

`tests/test_world_contracts.py` and `tests/test_world_build.py`: 33 passed. Full backend suite (`uv run python -m pytest tests -q -p no:cacheprovider`, Neo4j tests not enabled): 382 passed, 10 skipped, 113 subtests passed, 13 min 14 s.

