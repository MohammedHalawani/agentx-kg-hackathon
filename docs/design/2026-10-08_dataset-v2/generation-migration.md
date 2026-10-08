# Data generation and safe migration/reset plan

Design 2026-10-08; **no generation/import/reset commands are executed here**.

## Generation stages

1. Freeze `dataset_id`, schema/policy/generator version, random seed, UTC simulation start
   and observation as-of clock. Catalog reference geography separately with license/hash.
   Generate synthetic IDs/contact refs (`.invalid`), not copied identities/addresses.
2. Build city/facility network and ownership/fulfillment inventory. Check every route's
   segment endpoints and ordered milestones form a connected path. Source/destination
   roles support Customer and Organization. Geographic connections are approximate.
3. Define service/type/handling profiles, DeliverySessions, vehicle payload/volume and
   assignment calendars. Choose compatible assignments with capacity reserved across
   overlapping intervals; reject impossible assignments rather than randomizing them away.
4. Generate shipment/package manifests, AddressVersions and baseline JourneyPlans. Expected
   windows derive from configured segment/handling/session/receiver rules. Store promise
   and plan version before perturbing the actual journey.
5. Generate physically plausible actual events: inventory release, custody acknowledgment,
   neutral raw scans, contact/attempt observations, vehicle observations and proof. Generate
   normal journeys first, then controlled perturbations (barcode value/weight/gate/address,
   dwell/traffic, missing reconciliation, contradictory proof) from scenario recipes.
6. Derive exceptions from observations with deterministic rule IDs/versions and evidence
   refs. Store private simulation truth, gold labels and expected safe-action sets in
   a scoring-only file; never embed gold into runtime event types/IDs/complaint text.
7. Generate completed historical action/outcome stories only when supporting external
   receipt and verification evidence exists. Failed outcomes also require observations.
   Pending, rejected, escalated and evidence-insufficient stories remain noneligible.
   No independent random success boolean and no AI self-verification.
8. Assign disjoint development/history/test shipment groups before generating retrieval
   summaries. Reserve hard ambiguous controls and whole multi-package/sibling cases. Produce
   AR/EN complaints from symptoms with varied phrasing; no explicit cause vocabulary hints.
9. Export deterministic JSONL/CSV plus schema/policy/network/split manifests, checksums,
   counts and validation report. Review24 narrative anchors before scaling600 shipments.
   Model-free generation/validation must be reproducible byte-for-byte where appropriate.

Proposed scripts for the next run (not present): `dataset_v2/generate.py`, `derive.py`,
`validate.py`, `load.py --dry-run`, and a reviewed shadow-only import manifest. Separate
pure generation from Neo4j loading; generating a file must never contact a database.

## Required validators

| Invariant | Required result |
|---|---|
| Stable identity/dedup |Business/source-event IDs unique within dataset; duplicate identical events replay safely; conflicting duplicates quarantined|
| Topology/roles |Every segment has connected endpoints; recipient/sender/package/facility references exist; ownership distinct from custody|
| Time |Offset-aware UTC; occurred vs recorded time distinct; no causally impossible load-before-pickup or delivery-before-load; late ingestion allowed|
| Assignment |Vehicle/driver interval valid; no exclusive overlapping assignments; package capacity/handling compatible; unload ends association|
| Expected journey |Service/type-specific windows reproducible; original promise retained; revision audit required; missing input yields unknown|
| Custody |Every confirmed transition references valid party/facility/vehicle; required acknowledgments; earliest gap and contradictory holders reproducible|
| Evidence-derived labels |Every gold cause has sufficient positive observation/policy references; missing/ambiguous controls allow insufficient-evidence rather than force a subtype|
| Delivery/dispute |POD/address/time/package compatibility checked; partial shipment not fully delivered; contradictory reports remain investigable|
| Lifecycle/learning |Only verified policy-supported outcome enters RESOLVED/precedent; pending/null not success/failure; reopen/invalidation retained|
| Evaluation isolation |All held-out shipment/package/case/failure/resolution/outcome siblings excluded; runtime lacks gold/retrospective answer fields|
| Privacy/external calls |Synthetic identity/contact data, no secrets/real recipients; dry notification mode zero network calls|

A label is not sufficient validation of its own observation. Derivation must fail when the
supporting barcode/weight/gate/contact/custody event is removed, and boundary controls
must flip only under the intended predicate. Assert supported alternative safe remedies,
not one randomly chosen action string.

## V1 → V2 adapter mapping

| V1 concept | V2 proposal | Migration constraint |
|---|---|---|
| Shipment/Order/Customer |Shipment, role-bearing Customer/Organization, Package/manifest|Keep old IDs/provenance; don't fabricate missing package measurements|
| Address(version property) |Address + immutable AddressVersion|Unknown effective times remain unknown, not invented history|
| Courier |Legacy courier reference / synthetic Driver assignment|V1 courier does not prove vehicle/driver identity or custody; no automatic mapping to Driver|
| Generic Event |Scan/Custody/Attempt/Contact/proof observations|Only translate available fields; status-only events remain assertions|
| FailureReason |Evidence-linked Exception + Case|V1 seeded category is retrospective synthetic annotation, not sufficient V2 observation|
| Resolution/Outcome |Recommendation/Review + pending/observed provenance adapter|V1 agent pending remains pending; seeded random outcomes are `synthetic_legacy`, not externally verified|
| EscalatedCase |Case state + AuditEvent|Preserve handoff reason/time and unknown verification; no false resolution|
| Policy SLA/retry |Versioned Policy/Service/JourneyPlan|V1 demo values preserved as synthetic assumptions, no SPL entitlement|

Keep V1 and V2 retrieval corpora separate initially. Never promote legacy random outcomes
to “verified operational evidence.” A compatibility read adapter can show V1 with explicit
provenance; embedding/backfill eligibility requires the V2 verification contract.

## Shadow migration and rollback

Prefer a new isolated `shipments_v2_demo` database on a verified local synthetic Neo4j
instance. Inspect installed edition/capabilities and all target labels/IDs before any DDL
or import. If isolated databases are unavailable, choose a separate Desktop DBMS after
operator review; do not silently fall back to clearing `shipments` or mixing schema versions.

1. Preserve V1 census, constraints/index definitions, canonical proof/evaluation artifacts
   and a supported backup/snapshot chosen for the installed Neo4j runtime. No secrets in
   the manifest. Test recoverability before any operation requiring an existing-data change.
2. Generate/export/validate offline; load only the exact approved new target/dataset_id.
   Import scripts default dry-run and refuse an existing nonempty target unless an explicit
   compatible manifest/replay identity matches. Replaying the same manifest adds no objects.
3. Create uniqueness constraints, load dependency-ordered batches with checkpoint hashes,
   compare counts/references/temporal invariants and run expected-vs-actual/custody queries.
   Build verified-history embeddings and confirm correct vector dimensions/ONLINE state.
4. Test the backend read adapter and feature-flagged V2 contract on the shadow target.
   Keep complaint writes disabled until operator/outcome/identity rules and rollback pass.
5. Switch only explicit shipment configuration after API/browser/data gates. Record the
   old/new dataset ID and model/prompt/evidence versions. Rollback changes configuration
   back to V1; V1 contents remain untouched. No migration is executed in this design run.

Reset means a reviewed operation against the isolated synthetic V2 target with exact
absolute host/database/dataset identity, backup/recovery evidence and explicit authorization.
It never means `MATCH(n) DETACH DELETE n` against a computed/default/unknown database.
Prefer a fresh versioned shadow dataset for scenario replay. Do not delete V1 to make a demo.
