# Graph schema proposal — V2

Design-only 2026-10-08. Every entity has `dataset_id`, `schema_version`, stable business ID,
`synthetic`, source/ref and UTC `recorded_at`. Observations additionally have UTC
`occurred_at`, source event ID, verification/quality status and explicit units. Never use
Neo4j element IDs as durable external identities. Do not create generic nodes without a
query/reasoning role. Facility sublabels share `:Facility`; Custodian references are
typed facility/vehicle/party nodes. The logical classes below need not each have a separate
creation table; sublabels retain common identity and are never duplicated for appearance.

| Label / ID | Essential properties | Reasoning role |
|---|---|---|
| Customer/customer_id |synthetic contact ref, locale; no real PII|Sender/recipient roles and attributed complaints|
| Organization/organization_id |synthetic name/type|B2C/B2B sender/receiver; inventory ownership|
| OrganizationWarehouse/facility_id |:Facility, city/approx point, owner_org_id|Company-owned inventory/custody source|
| FulfillmentWarehouse/facility_id |:Facility, operator_org_id, capabilities|Managed fulfillment vs ownership distinction|
| Branch/facility_id |:Facility, city, dropoff capability|Sender handover evidence|
| Hub/facility_id |:Facility, city, transfer capabilities|Intercity transfers and expected dwell|
| SortingCenter/facility_id |:Facility, city, processing classes|Sorting milestones and measured dwell|
| DeliveryDepot/facility_id |:Facility, city, eligible sessions|Last-mile load/return reconciliation|
| Shipment/shipment_id |tracking_id, flow_type, sender/recipient refs, asserted status|Operational subject; status is not proof|
| ShipmentType/type_id |class, weight/dimension/handling limits|Contextual journey and compatible transport|
| ServiceLevel/service_id |synthetic promise policy/version|Class-specific windows and remedy urgency|
| Package/package_id |manifest barcode, expected weight_kg/dimensions_m, declared content class|Measured barcode/weight comparisons; multi-package custody|
| HandlingRequirement/handling_id |allowed handling/vehicle capabilities, limits|Bulky/special handling without arbitrary timer|
| InventoryRecord/inventory_id |package/organization/facility, available/reserved quantity|Separate inventory ownership/allocation from transport custody|
| Address/address_id |immutable logical destination identity, public component fields|Destination identity without silently changing old versions|
| AddressVersion/address_version_id |version, effective interval, building/street/district/city/postal/secondary/short-address fields, point accuracy, gate/instructions|Version/attempt conflict and recipient pin provenance|
| Route/route_id |ordered versioned synthetic topology|Expected network path, not actual traveled trace|
| RouteSegment/segment_id |from/to facility, planned duration range, transport/handling capability|Linehaul/last-mile and traffic accumulation|
| RouteMilestone/milestone_id |sequence, facility, event predicate, handling duration|Expected custody/scan arrival and missing-event reasoning|
| JourneyPlan/plan_id |version, promise_at, effective_at, policy_version, as_of basis|Frozen original vs revised expected journey|
| ExpectedMilestone/expected_id |earliest/latest UTC, match rule, sequence, grace policy|Shipment-specific deadlines, no universal SLA|
| DeliverySession/session_id |depot, timezone, eligible start/end, capacity, synthetic=true|Session-aware assignment/reconciliation/next delivery|
| Vehicle/vehicle_id |synthetic display ID, payload_kg, usable_volume_m3, capability refs|Compatible transport and interval custody context|
| VehicleType/vehicle_type_id |last-mile/linehaul/bulky class, capability defaults|Plausible assignment constraints|
| Driver/driver_id |synthetic pseudonym only|Who was assigned at event time, without blame/scoring|
| VehicleAssignment/assignment_id |valid_from/to, session/segment, status, capacity allocation|Time-scoped driver/vehicle/package association|
| ScanEvent/scan_id |scanned_barcode, measured_weight_kg, facility, device ref, confidence|Actual observations, not cause labels|
| CustodyEvent/custody_id |event type, from/to custodian, acknowledgment, package, verification refs|Last corroborated custody/gap detection|
| DeliveryAttempt/attempt_id |arrival/attempt time, referenced address version, observed gate, disposition|Attempt count/outcome and wrong-gate observations|
| ContactAttempt/contact_id |channel, attempted_at, result code, attributed actor/consent evidence|Unavailable vs unknown; avoid unsupported recipient blame|
| GPSObservation/gps_id |vehicle, point, accuracy_m, observed_at, source|Vehicle-only location with quality/interval bounds|
| TrafficObservation/traffic_id |segment, interval, delay_min/max_seconds, attributed source/confidence|Explained lateness vs missing custody|
| DeliveryProof/proof_id |type, address version/location accuracy, synthetic authentication/receipt refs, verification status|Delivered/not-received dispute without declaring a person dishonest|
| Policy/policy_id |version, effective interval, rule kind, synthetic thresholds/units|Deterministic retry, discrepancy and outcome eligibility|
| Exception/exception_id |derived type, rule/version, first observed time, risk, evidence_missing|Abnormal observation/relationship; no bare fabricated FailureReason|
| Case/case_id |state, operationally_resolved, opened_at, state_version, evidence_version|Investigation lifecycle and concurrency|
| EvidenceSnapshot/snapshot_id |as_of, included evidence IDs/versions/hash|Reproducible model/reviewer/approval context|
| AnalysisRun/run_id |model/prompt/provider versions, iteration, timing/diagnostics|Audit and performance without raw thinking|
| Recommendation/recommendation_id |action code/text, applicability/unknowns, proposal version, status|Proposed remedy, separate from execution|
| Review/review_id |verdict/score, deterministic findings, evidence/version refs|AFL feedback and policy review; not correctness certification|
| OperatorDecision/decision_id |actor/role, approve/reject, current proposal/evidence version, reason/time|Explicit authorized human command|
| ActionExecution/execution_id |command idempotency key, external receipt/status, occurred_at|Authorized handoff/acknowledgment; no fake physical result|
| Resolution/resolution_id |action/problem type, verified evidence, resolved_at, verifier/policy|Verified remedy; distinguishes admin fix from delivery|
| Outcome/outcome_id |pending/succeeded/failed/invalidated, success nullable, action_type, verification provenance|Eligible learning; no model self-certification|
| Notification/notification_id |event/template version, recipient ref, mode/status, outbox key|Dry-run/live delivery state, separate from parcel outcome|
| AuditEvent/audit_id |actor, entity/run/event IDs, state transition/version, occurred/recorded times, reason code|Append-only trace of every important transition|

## Relationships and cardinality

| From → relationship → To | Constraint / interval semantics |
|---|---|
| Customer/Organization → SENDS/RECEIVES → Shipment |Explicit sender/recipient role; organization recipient supported|
| Organization → OWNS → OrganizationWarehouse/InventoryRecord |Ownership does not establish custody|
| InventoryRecord → STORED_AT → Facility; ALLOCATES → Package |Quantity/allocation validation; pickup event starts movement|
| Shipment → HAS_PACKAGE → Package |One or more; avoid inferring whole-shipment delivery from one package|
| Shipment → HAS_TYPE/USES_SERVICE/REQUIRES → ShipmentType/ServiceLevel/HandlingRequirement |Applicable policy version fixed by JourneyPlan|
| Shipment → HAS_ADDRESS_VERSION → AddressVersion → VERSION_OF → Address |Non-overlapping effective history; supersession preserved|
| Shipment → EXPECTED_ROUTE → Route; HAS_PLAN → JourneyPlan |Exactly one current plan, older plans preserved|
| Route → CONTAINS → RouteSegment/RouteMilestone |Sequence unique within route/version; connected from/to endpoints|
| JourneyPlan → EXPECTS → ExpectedMilestone → BASED_ON → RouteMilestone |Deadline/predicate frozen for this shipment/version|
| RouteSegment → FROM/TO → Facility; PASSES_THROUGH → Facility |Intermediate hubs explicit, never create a traveled route from a line|
| Shipment/Package → HAS_SCAN/HAS_CUSTODY_EVENT/HAS_ATTEMPT → event nodes |Event belongs to one package or declared whole-shipment scope|
| DeliveryAttempt → USED_ADDRESS → AddressVersion; HAS_CONTACT → ContactAttempt; HAS_PROOF → DeliveryProof |Proof/disposition may be absent; do not fill unknowns|
| CustodyEvent → FROM_CUSTODIAN/TO_CUSTODIAN → Facility/Vehicle/Customer/Organization |Valid custodian type; bilateral acknowledgment per policy|
| Shipment → LOADED_ON → Vehicle |Derived, evidence-backed valid_from/to and custody_event_id, never a timeless planning edge|
| Vehicle → HAS_ASSIGNMENT → VehicleAssignment → ASSIGNED_DRIVER → Driver |No impossible overlapping exclusive driver intervals|
| VehicleAssignment → IN_SESSION/ON_SEGMENT → DeliverySession/RouteSegment; CARRIES → Package |Capacity/compatibility and temporal validation|
| Vehicle → HAS_TELEMETRY → GPSObservation |No direct parcel-position proof edge|
| RouteSegment → HAS_DELAY_EVIDENCE → TrafficObservation |Interval-scoped, confidence and source required|
| Case → ABOUT → Shipment; HAS_EXCEPTION → Exception; USES_SNAPSHOT → EvidenceSnapshot |Multiple cases possible; one current case per exception episode|
| Exception → SUPPORTED_BY → observation/ExpectedMilestone |Derived rule must reproduce from these evidence IDs|
| Case → HAS_RUN → AnalysisRun → PROPOSES → Recommendation → REVIEWED_BY → Review |Immutable proposal/review iterations; no overwriting rejected history|
| Recommendation → CITES → Resolution; SUPPORTED_BY → observation |Only verified eligible histories, whole-shipment holdout in evaluation|
| Recommendation → HAS_DECISION → OperatorDecision → INITIATES → ActionExecution |Approve current version; idempotent external command|
| Case → RESOLVED_BY → Resolution → HAS_OUTCOME → Outcome |Verification gate, distinct admin/delivery outcome type|
| Outcome/Resolution → VERIFIED_BY → OperatorDecision/DeliveryProof/CustodyEvent |Explicit verifier/evidence/policy provenance; no model-generated verification|
| Case → HAS_NOTIFICATION/HAS_AUDIT → Notification/AuditEvent |Append-only causal links, include run/transition IDs|

## Storage and validation

Use named compound uniqueness `(dataset_id,business_id)` for each concrete business
identity, plus idempotent event-source IDs and outbox/command IDs. Suggested nonexecuted
syntax: `CREATE CONSTRAINT shipment_v2_id IF NOT EXISTS FOR (s:Shipment) REQUIRE
(s.dataset_id,s.shipment_id) IS UNIQUE`. All required fields/types/cardinality/temporal
invariants also pass application validators; property existence/type/key constraints may
depend on Neo4j edition/version. Verify installed capabilities before choosing DDL.
[Current Neo4j constraint syntax](https://neo4j.com/docs/cypher-manual/current/schema/syntax/).

Use UTC zoned datetimes for storage, Asia/Riyadh for operational display/sessions, and SI
units. Reject timestamps without offset at ingestion rather than mixing naive/aware time.
Keep valid_time and recorded_time distinct for late-arriving evidence.
[Neo4j temporal functions](https://neo4j.com/docs/cypher-manual/current/functions/temporal/).

Index Case state/opened_at, observation occurred_at/source IDs, tracking IDs, current plan
and assignment intervals according to profiled queries. Spatial predicates consider point
accuracy, not raw equality. Vector case summaries include only eligible verified outcome
histories; holdout filtering is still mandatory and happens before final ranking. Avoid
embedding PII, pending proposals, mutable status-only text or gold derivation labels.

Do not apply these DDL/relationships to V1 in this run. The minimal first implementation
can deliver Facility, Package, versioned addresses, route/plan/milestones and events before
adding optional inventory/POD/traffic adapters, but their contracts must remain compatible.
