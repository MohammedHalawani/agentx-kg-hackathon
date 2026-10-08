# Dataset V2 foundation contract

Frozen 2026-10-08 for the implementation request. The earlier 600-shipment proposal is
superseded: size is configurable; the main profile is 2000 shipments, split 1200 history,
400 development and 400 held-out. The default target is 70% healthy journeys; a normal
shipment does not receive a fabricated Exception, Case or remediation history.

`chat/dataset_v2/contracts.py` is the executable export contract. Generation, derivation,
validation and export are pure offline operations. Neither configuration nor generation
reads `.env`, contacts Neo4j, calls a model or sends a notification. All operational
locations, schedules, thresholds, vehicles and identities are explicitly synthetic.

Every node has a DEMO `entity_id`, `dataset_id`, schema version, `synthetic=true`, source
reference, provenance and recorded time. Seven provenance roles are distinct:
PUBLICLY_VERIFIED, REFERENCE_DATA, SYNTHETIC_DEMO_ASSUMPTION, DERIVED, AGENT_INFERENCE,
OPERATOR_DECISION and VERIFIED_OUTCOME. **Synthetic is orthogonal to provenance**: a
generated verified outcome or operator decision remains a synthetic fixture. No live
agent run, human approval endpoint or actual SPL verification is implied.

Shipment-owned packages, routes/plans/milestones, assignments, observations, proof,
exceptions, cases and historical outcomes carry one neutral `holdout_group` and split.
Shared facilities, parties, vehicles and policy catalogs contain no scenario/gold fields.
Relationships propagate the owner; cross-shipment links are refused. Runtime contexts
must select that group and a field/type allowlist, never expand a shared vehicle into
other shipments. Gold and recipe descriptions are scoring-only files, never DB imports.

JourneyPlan also has the ExpectedJourney label; Route also has ExpectedRoute. Each package
has ordered ExpectedMilestones with predicate, earliest/latest UTC and contextual grace.
Original promise and fixed as-of are retained. Local delivery sessions are configurable
Asia/Riyadh demo assumptions; overnight linehaul has separate planned intervals.

Required custody fields: package, from/to typed custodian, UTC occurred/recorded time,
source_event_id, required/received acknowledgments and observation refs. Only corroborated
transitions establish a holder. Missing transitions retain a gap, and conflicting evidence
requires human investigation. VehicleAssignment records driver, vehicle, valid interval,
segment/session and package allocation. Capacity is checked for overlapping intervals;
GPS is vehicle location with accuracy, never exact parcel position or personal blame.

| Evidence type | Binding and interpretation |
|---|---|
| LocationPin |Supplier/source, purpose, address version, time, accuracy and verification; recipient report is attributed|
| DeliveryInstruction |Gate/access, effective interval/version and address version; attempt references the version used|
| DeliveryProof |Package/attempt/address version/time, proof method, corroboration and verification policy|
| AuthenticationEvidence |Synthetic OTP/PIN method/result/binding/expiry; no actual OTP value or secret|
| SignatureEvidence |Synthetic proof type, package/recipient and capture time; no real signature|
| PhotoEvidence |Synthetic metadata, subject/address/time/point accuracy; no invented photograph or verdict in metadata|
| HandoffEvidence |Recipient type and explicit authorization reference for an alternate recipient|
| RecipientReport |Attributed complaint/report time, package and supplied pin; conflict can persist despite proof|
| DeliveryAttempt |Observed gate/address version, disposition and attributed failed reason; contact evidence is separate|
| DepotReconciliation |Session/package, valid delivery proof or failed attempt plus confirmed depot receipt; absence after end+grace derives UNRECONCILED_CUSTODY, never LOST|

Scan comparisons require a readable barcode or calibrated weight plus units/tolerances.
Expected-versus-actual compares observations, not a scenario label. Delay and safe depot
return can justify next-session priority without loss. Delivery proof conflicts have neutral
alternatives: corroborated delivery, possible misdelivery, conflicting or insufficient
evidence and human review; proof type alone never dismisses a recipient's report.

Historical resolved exception fixtures require a synthetic operator decision, external
receipt and action-specific evidence-backed outcome. Administrative correction is not
parcel delivery. Pending, failed, reopened or invalidated outcomes retain their distinct
meaning; only verified noninvalidated history is eligible, with failed observations retained
as failures. Normal completed shipments provide healthy journey examples, not fabricated
remediation precedent. Recommendations never independently establish RESOLVED.

Exports freeze seed, schema/generator/policy/rule versions, normalized size/split/mix,
simulation/as-of clock, units/timezone and content hashes. Import defaults to dry-run,
requires an explicit local shadow target, refuses active/default/system databases and
incompatible existing content, and replays an identical manifest without added objects.
No V1 schema/data/config switch, queue execution, model evaluation or email is authorized
by these modules.
