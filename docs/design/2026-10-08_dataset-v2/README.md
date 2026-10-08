# Dataset V2 — logistics intelligence foundation

Implementation update: the subsequent foundation request supersedes the proposed 600
size below with configurable generation and a main 2000 / 1200-history / 400-development /
400-held-out profile. See [frozen implementation contracts](../../dataset-v2/contracts.md).
The dated proposal below remains the original design record.

Proposal recorded 2026-10-08, Asia/Riyadh. **DESIGN ONLY.** No generator, new graph,
queue worker, GPS integration, outcome endpoint, email integration or major UI redesign
is implemented in this run. The current `shipments` graph remains V1. This proposal
replaces the earlier plan to implement product-expansion phases immediately.

The product question is: why is a shipment abnormal/stalled, which evidence explains it,
and what is the safest correct next action? Every proposed entity below serves custody,
expected-vs-actual reasoning, remedy review or verified learning. It does not introduce
fleet optimization or employee surveillance.

Read the artifacts in this order:

1. [Architecture and evidence rules](architecture.md).
2. [Complete graph schema proposal](graph-schema.md).
3. [Scenario matrix](scenario-matrix.md).
4. [Generation, migration and reset strategy](generation-migration.md).
5. [Evaluation V2 protocol](evaluation-v2.md).
6. [Next-run implementation batches](implementation-batches.md).

## Public facts versus demo assumptions

| Classification | Permitted use |
|---|---|
| PUBLICLY VERIFIED FACT |SPL documents six National Address components and a short-address form. These can inform address field names; they do not verify any generated recipient address. [Official address format](https://splonline.com.sa/en/door-step/).|
| PUBLICLY VERIFIED FACT |SPL publicly describes address/maps/lookups APIs. Availability of a public API does not establish credentials, production entitlement or this app's integration. [Official API description](https://splonline.com.sa/en/national-address-api/).|
| SYNTHETIC DEMO ASSUMPTION |Every facility, organization, warehouse, depot, shipment, route, segment duration, vehicle, assignment, session, SLA, weight tolerance, traffic observation and outcome.|
| PROVIDED REFERENCE GEOGRAPHY |The existing city/district dataset is reference input, not an SPL facility/route registry. Preserve its provenance, license and version; review coordinates before presentation.|
| FUTURE CONNECTABLE EVIDENCE |Enterprise custody, scans, contact results, GPS, traffic, proof-of-delivery, execution acknowledgments and outcome verification. Never claim universal SPL coverage.|

Use named cities from the requested scope: Riyadh, Jeddah, Makkah, Madinah, Dammam,
Khobar, Dhahran, Hofuf and Jubail, with optional Abha/Tabuk/Hail/Qassim scenarios after
coverage review. Facility IDs/names must start `DEMO-`, e.g. `DEMO-HUB-RUH-01`.
Do not copy corporate facility names or assert an actual road schedule. Coordinates
represent approximate synthetic facilities in a city, not disclosed SPL locations.

## Recommended bounded initial size

Propose 600 shipments across a connected network: 360 eligible synthetic observed histories,
120 development/validation shipments and 120 held-out test shipments. Within each split,
include C2C/B2C/B2B, normal and abnormal journeys, local/intercity, pickup/dropoff and
different handling classes. No random 85% success: outcome follows the generated action
and its verification evidence. Exact counts are configuration targets, not facts about SPL.

An initial 24-case narrative pack (one normal/one challenging case per core stratum) gives
authors something reviewable before generating 600 histories. Promote only after custody,
capacity, timestamps, derived labels, lifecycle and no-leakage validators pass. The costly
V2 model benchmark remains a separately authorized future step.

Manual choices before implementation: approve dataset size and synthetic policy examples;
confirm the local Neo4j edition supports an isolated database/DBMS; approve outcome
verification policy and authorized operator roles before exposing write endpoints; confirm
notification channel/consent before any live sending. None is needed to review this design.
