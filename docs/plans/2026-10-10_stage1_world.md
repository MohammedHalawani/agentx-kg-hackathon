# Stage 1 plan: a mechanism-based synthetic Saudi logistics world (world-1)

Date: 2026-10-10. Follows the Stage 0 assessment (`docs/assessments/2026-10-10_stage0/README.md`), requirements 1 to 7.
Everything generated here is synthetic, labelled synthetic, and is not SPL operational data.

## Goal

Replace per-shipment scenario recipes with a simulated network in which faults are mechanisms that act on every parcel they
physically touch. The same alert must be able to come from different mechanisms, and the evidence that separates them must
exist in the graph but only be reachable by investigation, often across shipments.

## What stays and what is new

- New package `chat/world/`. `chat/dataset_v2` generation is not changed: the S5 dataset regenerates with identical manifest,
  feed and truth hashes (a regression test checks this).
- Output is the existing V2 contract (`World` nodes and edges plus a separate truth file), so the import (`load.py`), the
  provider feed and gateway (`feed.py`, `ingestion.py`), the monitor (`derive.py`, `store.py`) and the current tools work on
  it unchanged. Additions to the contract are additive only (new kinds and relationships, shared observation kinds in the feed).
- New database `shipments-v2-world-1` (development) and `shipments-v2-world-1-heldout` (held-out twin), output directory
  `artifacts/world/world-1/`. `shipments-v2-demo-live` and every existing database stay untouched.

## Design

Two layers, kept strictly apart.

1. **Physical simulation (private).** A discrete-event simulation over simulated days. Each parcel has one true location at
   every moment (a facility, a container, a vehicle, a person). Mechanisms change what physically happens or what gets
   recorded. The result is a physical event log plus mechanism records. None of it is imported.
2. **Observation (public).** Devices, people and systems observe physical events, or fail to, through channels with latency.
   This layer writes the V2 evidence: scans, custody transfers, attempts, proofs, manifests, status events, heartbeats,
   vehicle positions, traffic, facility throughput and customer communications, each with `occurred_at` (when it happened)
   and `recorded_at` (when Suhail received it).

### Network

- Cities with real approximate coordinates: Riyadh, Jeddah, Makkah, Madinah, Dammam, Khobar, Dhahran, Al Ahsa (Hofuf),
  Buraydah (Qassim), Jubail, Taif, Tabuk, Abha. Demand weighted toward Riyadh, Jeddah and the Eastern Province.
- Facilities: pickup branches, fulfillment and customer warehouses, sorting centers, hubs and delivery depots, each with a
  processing capacity per hour, shifts and devices (handhelds, scales, sorter readers).
- Linehaul lanes between hubs: road distance from haversine times a road factor, transit time from distance and speed,
  scheduled departures with cutoffs, run by the in-house fleet or the contracted carrier.
- Last-mile: depots run delivery routes per shift. A driver (employee, contractor, or independent driver with a private car)
  carries many parcels from many shipments; vehicles and drivers are shared across shipments, with realistic capacity.
- Consolidation: parcels are bagged or caged into containers at sort, containers travel on linehaul trips, and are opened at
  the destination hub.
- Recipients have their own address points (districts, buildings, gates) with GPS noise, contact preferences and
  availability patterns.

### Normal variation

Processing and transit times are drawn from distributions; uploads usually arrive within minutes; some milestones are late
but inside the promise; some first attempts fail and the second succeeds within the promise; duplicate provider messages and
out-of-order arrival happen in normal operations. Healthy shipments must look normal, not identical.

### Mechanisms (world-level, each touching every parcel it physically affects)

| Mechanism | What physically happens | What gets observed | Case families |
|---|---|---|---|
| Device outage (handheld, driver app, sorter reader) | Parcels move normally | That device's records buffer and upload at reconnect; its heartbeats stop; every parcel it handled in the window is affected | A, B |
| Partial upload loss | Parcels move normally | Some records from an online device never arrive until a sync is requested | B, C |
| Scan skipped at receipt | Parcel is at the facility | No receipt; later scans appear without it | C |
| Facility backlog | Parcels wait past their connection | Throughput drops, many shipments miss the same connection | C, F |
| Late or broken-down linehaul trip | Containers arrive late | Truck positions stationary; carrier delay status; all containers on the trip late | C, F |
| Missort | Parcel or container goes on the wrong lane | Scan at an unexpected city hub; natural recovery takes a day unless rerouted | D |
| Assigned but not loaded | Parcel stays at the depot | On the manifest, no driver-app loading confirmation | A, C |
| Delivery scan skipped | Parcel delivered | Out for delivery overnight; proof missing or late | A |
| Return scan skipped | Parcel back at the depot | Session ends unreconciled; found on a depot check | A, C |
| Contractor retains parcel | Parcel with an independent driver | App silent after the last attempt; no return | A, C |
| Unrecorded handoff | Parcel moved between drivers | Custody reports conflict | C |
| Recipient unavailable | Nobody answers | Failed attempt, unanswered calls | H |
| Wrong or outdated address, wrong gate | Driver cannot complete | Failed attempt; later address correction message | H, F |
| OTP not received | Recipient present, code not delivered | Failed attempt; failed SMS delivery in communications (no code value is ever stored) | E, H |
| Neighbour or other person receives | Parcel handed to someone else | Proof shows another person; recipient reports non-receipt | E |
| Misdelivery | Parcel left at the wrong door | Proof location away from the address; report | E |
| Label misread, wrong label applied | One read wrong, or every read wrong | Barcode differs once, or consistently | (measurement) |
| Scale drift, declared weight wrong | Every weighing on that scale in the window is off, or the declaration is wrong | Weight differs, on many parcels or one | (measurement) |
| Manifest error | A revised manifest drops a loaded parcel | Manifest conflicts with confirmed custody | C |
| Traffic or road closure | Routes through a zone are slow | Shared traffic observations; several routes late | A, F |
| Customer complaint | A recipient asks or complains (sometimes about a healthy shipment) | Inbound message | H, G |

Multi-cause cases (family F) arise when two mechanisms overlap on one parcel, for example an outage during a backlog, or a
wrong address followed by an unavailable recipient. Healthy shipments (family G) have no mechanism.

### Truth (private, never imported)

For each shipment: whether any mechanism touched it, and for each mechanism its type, its cause code in the current cause
catalogue, when it started, the time its first evidence reached the gateway (`knowable_at`), the evidence ids it produced, and
the resolution it permits. Plus world-level mechanism records (outage windows, backlogs, missorts) and each parcel's true
location timeline, which the operational simulator will use in Stage 4. A truth row with no evidence is marked unobservable.

### Splits

By booking day in one connected world: days 1 to 4 are history (imported in full, with verified outcomes as precedents),
days 5 to 7 are development (fed live), days 8 and 9 are held out (absent from the development database; fed live in the twin
database). Stage 3 also uses fresh-seed worlds that are never looked at during development. Rare mechanisms are over-sampled
so that each has at least 10 affected shipments in the development split; the rates are recorded in the manifest and are not
claims about real frequencies.

### Size

Validate at about 600 shipments first, then generate world-1 at about 2,000 shipments over 9 simulated days. Scale further
only after the Stage 3 evaluation shows the tools and queries hold up.

## Validation (all must pass before import)

- The existing `validate_world` and live-bundle validation pass on the reconstituted world.
- Physics: each parcel in exactly one place at a time; custody continuity; vehicle capacity; a driver in one vehicle at a
  time; travel times consistent with distance; facility throughput within capacity.
- Observation: no record before its event; uploads only of recorded scans; heartbeats consistent with outages; duplicates
  share identity.
- Truth isolation: no truth field, mechanism id or mechanism name in any node, edge or feed message (the existing truth
  vocabulary scan, extended).
- Tell detector: for each mechanism, no single field value is both rare and near-perfectly predictive of it.
- Determinism: same seed, same hashes.
- Neo4j after import: counts match the manifest, no orphan references, indexes on device, driver, vehicle, session, trip,
  container and facility references, and query timings recorded for the cross-shipment lookups Stage 2 will use.

## Gate report

Counts by kind, mechanism and split; how many alerts of each type come from how many different mechanisms; validation and
isolation results; hashes; and a short sample of matched cases (same alert, different mechanisms).

## Running in parallel with Stage 1

Fixes that must land before the new interface is connected, in files Stage 1 does not touch: B1 (scripted GPS sentence),
B2 (rule triage shown as the diagnosis), M2 (approval rechecks authority, under the conditions Fahad set on 2026-10-10),
L10 (development reset behind a flag and confirmation), and the carried L items. B3 (reroute and return handlers, the
duplicate-events shipment) and L4 (per-device heartbeat answers) come with the new world's simulator in Stage 4.
