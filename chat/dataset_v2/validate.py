"""Pure domain and split validation for a reconstructed V2 export.

An observational contradiction may be represented; it may not be silently promoted
to physical truth. Validation is recomputed, never trusted from an exported report.
"""
from collections import Counter, defaultdict
from datetime import timedelta
import math

from dataset_v2.contracts import CASE_STATES, KINDS, Provenance, RELATIONSHIPS, SCHEMA_VERSION, SPLITS, UTC_FIELDS
from dataset_v2.derive import EvidenceIndex, assess_shipment, custody_corroborated, number, proof_assessment, timestamp


_FACILITIES = {"OrganizationWarehouse", "FulfillmentWarehouse", "Branch", "Hub", "SortingCenter", "DeliveryDepot"}
_CUSTODIANS = _FACILITIES | {"Vehicle", "Customer", "Organization"}
_EVENTS = {"ScanEvent", "CustodyEvent", "DeliveryAttempt", "ContactAttempt", "GPSObservation", "DeliveryProof",
           "AuthenticationEvidence", "SignatureEvidence", "PhotoEvidence", "HandoffEvidence", "RecipientReport",
           "DepotReconciliation", "StatusEvent"}
_GOLD_KEYS = {"scenario", "scenario_id", "recipe", "recipe_id", "gold", "gold_category", "expected_cause", "expected_codes", "ground_truth", "seeded_category"}
_REF_KINDS = {"package_id": {"Package"}, "attempt_id": {"DeliveryAttempt"}, "address_version_id": {"AddressVersion"},
              "used_address_version_id": {"AddressVersion"}, "current_address_version_id": {"AddressVersion"},
              "vehicle_id": {"Vehicle"}, "driver_id": {"Driver"}, "assignment_id": {"VehicleAssignment"},
              "session_id": {"DeliverySession"}, "segment_id": {"RouteSegment"}, "route_id": {"Route"},
              "journey_id": {"JourneyPlan"}, "policy_id": {"Policy"}, "service_id": {"ServiceLevel"},
              "recipient_id": {"Customer", "Organization"}, "authentication_id": {"AuthenticationEvidence"},
              "signature_id": {"SignatureEvidence"}, "photo_id": {"PhotoEvidence"}, "handoff_id": {"HandoffEvidence"},
              "proof_id": {"DeliveryProof"}, "receipt_id": {"CustodyEvent"}, "pin_id": {"LocationPin"},
              "address_id": {"Address"}, "authorized_recipient_id": {"Customer", "Organization"}}


def _contains_scoring_fields(value):
    if isinstance(value, dict):
        return bool(_GOLD_KEYS & set(value)) or any(_contains_scoring_fields(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_scoring_fields(item) for item in value)
    return False


def validate_world(world) -> dict:
    """Return {pass, errors, checks, statistics}; performs no I/O and does not mutate."""
    index = EvidenceIndex(world)
    errors, checked, assessments = [], Counter(), {}
    def check(condition, code, entity, message):
        checked[code] += 1
        if not condition:
            errors.append({"code": code, "entity_id": entity, "message": message})
        return bool(condition)
    def children(key, relationship, kind):
        return [world.nodes[e.end] for e in index.outgoing[key]
                if e.kind == relationship and e.end in world.nodes and world.nodes[e.end].kind == kind]
    nodes = world.nodes
    config_cutoff = timestamp(world.config.as_of)
    start = timestamp(world.config.start_at)
    for key, node in nodes.items():
        p, owner = node.properties, node.properties.get("holdout_group")
        check(key == node.id == p.get("entity_id") and key.startswith("DEMO-"), "NODE_IDENTITY", key, "Dictionary, node and DEMO entity identity must agree")
        check(node.kind in KINDS, "NODE_KIND", key, "Kind must be in frozen schema")
        check(p.get("dataset_id") == world.config.dataset_id and p.get("schema_version") == SCHEMA_VERSION and p.get("synthetic") is True,
              "NODE_CONTRACT", key, "Dataset/schema/synthetic contract mismatch")
        check(p.get("provenance") in {str(v) for v in Provenance} and bool(p.get("source_ref")), "PROVENANCE", key, "Evidence role and source must be explicit")
        check(not _contains_scoring_fields(p), "GOLD_RUNTIME_ISOLATION", key, "Scoring recipe/cause fields must not enter node properties, including nested metadata")
        if owner:
            shipment = nodes.get(owner)
            check(shipment is not None and shipment.kind == "Shipment", "OWNER_EXISTS", key, "Owner must be a shipment")
            check(p.get("shipment_id") == owner and shipment is not None and p.get("split") == shipment.properties.get("split") and p.get("split") in SPLITS,
                  "OWNED_SPLIT", key, "Owned node must retain shipment group and split")
        else:
            check(p.get("split") == "shared" and not p.get("shipment_id"), "SHARED_SPLIT", key, "Shared catalogs must have no shipment answer group")
        for field in UTC_FIELDS & set(p):
            if p[field] is not None:
                check(timestamp(p[field]) is not None, "UTC_TIMESTAMP", key, f"{field} must be offset-aware UTC")
        occurred, recorded = timestamp(p.get("occurred_at")), timestamp(p.get("recorded_at"))
        if node.kind in _EVENTS:
            check(occurred is not None and recorded is not None and start <= occurred <= config_cutoff and recorded >= occurred,
                  "OBSERVATION_CHRONOLOGY", key, "Observed/recorded evidence times must be valid and bounded by simulation as-of")
        for begin, end in (("valid_from", "valid_to"), ("start_at", "end_at"), ("earliest_at", "latest_at")):
            if begin in p and end in p and p[end] is not None:
                a, b = timestamp(p[begin]), timestamp(p[end])
                check(a is not None and b is not None and a < b, "INTERVAL_CHRONOLOGY", key, f"{begin} must precede {end}")
        for field, kinds in _REF_KINDS.items():
            ref = p.get(field)
            if ref is None:
                continue
            target = nodes.get(ref)
            check(target is not None and target.kind in kinds, "TYPED_REFERENCE", key, f"{field} must reference {sorted(kinds)}")
            if target and target.properties.get("holdout_group"):
                check(owner == target.properties.get("holdout_group"), "REFERENCE_HOLDOUT", key, f"{field} cannot reveal another shipment")
        if "lat" in p or "lng" in p:
            lat, lng = number(p.get("lat")), number(p.get("lng"))
            check(lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180,
                  "COORDINATES", key, "Coordinates must be finite degrees in range")
        if "accuracy_m" in p:
            accuracy = number(p["accuracy_m"])
            check(accuracy is not None and accuracy >= 0, "POINT_ACCURACY", key, "Point uncertainty must be explicit nonnegative metres")
        if node.kind == "GPSObservation":
            check("package_id" not in p and not any(k in p for k in ("parcel_location", "driver_blame", "lost")),
                  "GPS_SCOPE", key, "Vehicle observation cannot assert parcel location, loss or personal blame")
        if node.kind in ("ScanEvent", "TrafficObservation"):
            confidence = number(p.get("confidence"))
            check(confidence is not None and 0 <= confidence <= 1, "OBSERVATION_CONFIDENCE", key, "Observation confidence must be bounded, never manufactured certainty")
        if node.kind == "ScanEvent" and p.get("calibrated") is True and "measured_weight_kg" in p:
            measured = number(p["measured_weight_kg"])
            check(measured is not None and measured >= 0 and p.get("measurement_units", "kg") == "kg",
                  "WEIGHT_OBSERVATION_UNITS", key, "Calibrated weight must be a nonnegative finite kg observation")
        if node.kind in ("Recommendation", "Review"):
            decision_at = timestamp(p.get("occurred_at"))
            for ref in p.get("evidence_ids", []):
                evidence = nodes.get(ref)
                recorded_at = timestamp(evidence.properties.get("recorded_at")) if evidence else None
                happened_at = timestamp(evidence.properties.get("occurred_at")) if evidence else None
                check(evidence is not None and decision_at is not None and recorded_at is not None and recorded_at <= decision_at
                      and (happened_at is None or happened_at <= decision_at), "RECOMMENDATION_REVIEW_EVIDENCE_TIME", key,
                      "Recommendation/review cannot cite evidence occurring or recorded after its decision time")
        if node.kind == "TrafficObservation":
            delay = number(p.get("delay_seconds"))
            check(delay is not None and delay >= 0, "TRAFFIC_OBSERVATION_UNITS", key, "Traffic delay is nonnegative seconds, not a GPS diagnosis")
        if node.kind == "Case":
            state = p.get("state", p.get("status"))
            check(state in CASE_STATES, "CASE_STATE", key, "Case must retain explicit supported lifecycle state")
        if node.kind == "Outcome":
            if p.get("verification_status") == "VERIFIED":
                check(type(p.get("success")) is bool and timestamp(p.get("verified_at")) is not None and bool(p.get("evidence_ids"))
                      and type(p.get("invalidated")) is bool, "VERIFIED_OUTCOME_FIELDS", key,
                      "Verified outcome needs observed boolean result, timed evidence and explicit invalidation state")
                if type(p.get("success")) is bool:
                    check(p.get("status") == ("succeeded" if p["success"] else "failed"), "OUTCOME_STATUS_MEANING", key,
                          "Observed success/failure must agree with outcome status")
            elif p.get("status") in ("pending", "unconfirmed", "awaiting_outcome"):
                check(p.get("success") is None, "PENDING_NOT_SUCCESS", key, "Pending recommendation/execution cannot assert observed success or failure")
        if node.kind in ("Package", "Vehicle", "VehicleAssignment"):
            for field in ("weight_kg", "volume_m3", "length_m", "width_m", "height_m", "payload_kg"):
                if field in p:
                    value = number(p[field])
                    check(value is not None and value > 0, "PHYSICAL_UNITS", key, f"{field} must be positive finite SI units")
        if node.kind == "Package":
            sizes = [number(p.get(k)) for k in ("length_m", "width_m", "height_m", "volume_m3")]
            check(all(v is not None and v > 0 for v in sizes) and math.isclose(math.prod(sizes[:3]), sizes[3], rel_tol=1e-6, abs_tol=1e-9),
                  "PACKAGE_VOLUME", key, "Package volume must equal length*width*height in m3")
        if node.kind == "CustodyEvent":
            source = nodes.get(p.get("source_event_id"))
            check(source is not None and source.properties.get("package_id") == p.get("package_id") and source.kind in _EVENTS,
                  "CUSTODY_SOURCE", key, "Transition must bind a raw package observation")
            for field in ("from_id", "to_id"):
                target = nodes.get(p.get(field))
                check(target is not None and target.kind in _CUSTODIANS, "CUSTODIAN_TYPE", key, "Custodian endpoint must have a physical/party type")
            required, received = p.get("required_acknowledgments"), p.get("received_acknowledgments")
            check(type(required) is int and type(received) is int and required > 0 and 0 <= received <= required,
                  "CUSTODY_ACKNOWLEDGMENTS", key, "Acknowledgment counts must be explicit and within requirement")
            if type(required) is int and type(received) is int and received < required:
                check(p.get("source_quality") == "INCOMPLETE_ACK", "INCOMPLETE_ACK_OBSERVATION", key, "Unacknowledged custody must remain explicit incomplete observation")
        if node.kind == "DeliveryProof":
            proof = proof_assessment(world, node, config_cutoff)
            # Invalid proofs are allowable observed dispute evidence, not verified truth.
            if p.get("verification_status") == "VERIFIED":
                check(proof["corroborated"], "PROOF_VERIFICATION", key, "Verified proof requires bound valid corroboration")
        if node.kind == "AuthenticationEvidence":
            check(not any(field in p for field in ("otp", "otp_value", "pin", "secret", "token")), "NO_AUTH_SECRETS", key, "Synthetic authentication stores result/binding, never OTP secrets")
        if node.kind == "DeliveryAttempt":
            address = nodes.get(p.get("used_address_version_id"))
            session = nodes.get(p.get("session_id"))
            check(p.get("disposition") in ("FAILED", "DELIVERED") and address is not None and session is not None,
                  "ATTEMPT_BINDING", key, "Delivery attempt requires disposition, address version and session")
        if node.kind == "DepotReconciliation":
            rp, session = p, nodes.get(p.get("session_id"))
            check(rp.get("result") in ("DELIVERED", "RETURNED") and session is not None and occurred is not None
                  and timestamp(session.properties.get("start_at")) is not None and occurred >= timestamp(session.properties["start_at"]),
                  "RECONCILIATION_BINDING", key, "Reconciliation must bind a started session and explicit result")
            if rp.get("result") == "RETURNED":
                attempt, receipt = nodes.get(rp.get("attempt_id")), nodes.get(rp.get("receipt_id"))
                check(attempt is not None and receipt is not None and attempt.properties.get("disposition") == "FAILED"
                      and attempt.properties.get("package_id") == rp.get("package_id") == receipt.properties.get("package_id")
                      and session is not None and receipt.properties.get("to_id") == session.properties.get("depot_id")
                      and receipt.properties.get("received_acknowledgments") == receipt.properties.get("required_acknowledgments"),
                      "RETURN_RECEIPT", key, "Returned parcel requires failed attempt and acknowledged depot receipt")
                if attempt and receipt and occurred is not None:
                    times = [timestamp(n.properties.get("occurred_at")) for n in (attempt, receipt)]
                    check(all(at is not None and at <= occurred for at in times), "RETURN_CHRONOLOGY", key, "Return reconciliation cannot precede attempt or receipt")
            if rp.get("result") == "DELIVERED":
                proof = nodes.get(rp.get("proof_id"))
                check(proof is not None and proof.kind == "DeliveryProof" and proof.properties.get("package_id") == rp.get("package_id")
                      and (rp.get("verification_status") != "VERIFIED" or proof_assessment(world, proof, config_cutoff)["corroborated"]),
                      "DELIVERY_RECONCILIATION", key, "Reported delivery must bind proof; verified reconciliation additionally requires valid corroboration")
    for key, edge in world.edges.items():
        a, b, p = nodes.get(edge.start), nodes.get(edge.end), edge.properties
        if not check(a is not None and b is not None, "EDGE_ENDPOINT", key, "Every endpoint must exist"):
            continue
        owners = {n.properties.get("holdout_group") for n in (a, b)} - {None}
        owner = next(iter(owners), None)
        check(len(owners) <= 1, "EDGE_HOLDOUT", key, "Cross-shipment edges leak holdout context")
        check(p.get("holdout_group") == owner and p.get("split") == (nodes[owner].properties["split"] if owner in nodes else "shared"),
              "EDGE_SPLIT", key, "Edge group/split must propagate endpoint ownership")
        check(edge.kind in RELATIONSHIPS and edge.id == key == p.get("edge_id") and key.startswith("DEMO-"),
              "EDGE_CONTRACT", key, "Edge kind/identity must match frozen schema")
        check(p.get("dataset_id") == world.config.dataset_id and p.get("schema_version") == SCHEMA_VERSION and p.get("synthetic") is True,
              "EDGE_METADATA", key, "Every relationship must retain synthetic provenance contract")
        check(not _contains_scoring_fields(p), "GOLD_RUNTIME_ISOLATION", key, "Relationship properties cannot carry scoring-only labels")
        if edge.kind == "LOADED_ON":
            loaded = nodes.get(p.get("custody_event_id"))
            begin = timestamp(p.get("valid_from"))
            check(loaded is not None and loaded.kind == "CustodyEvent" and loaded.properties.get("event_type") == "LOADED"
                  and loaded.properties.get("to_id") == edge.end and loaded.properties.get("package_id") == p.get("package_id")
                  and begin == timestamp(loaded.properties.get("occurred_at")) and custody_corroborated(world, loaded, config_cutoff),
                  "LOADED_ON_START_EVIDENCE", key, "Parcel/vehicle interval begins only from a bound corroborated load")
            if p.get("valid_to") is not None:
                unloaded = nodes.get(p.get("end_evidence_id"))
                end = timestamp(p.get("valid_to"))
                check(unloaded is not None and unloaded.kind == "CustodyEvent" and unloaded.properties.get("from_id") == edge.end
                      and unloaded.properties.get("package_id") == p.get("package_id") and end == timestamp(unloaded.properties.get("occurred_at"))
                      and custody_corroborated(world, unloaded, config_cutoff), "LOADED_ON_END_EVIDENCE", key,
                      "Physical vehicle custody cannot end at planned session/assignment time without an observed corroborated handover")
    split_counts = Counter(n.properties.get("split") for n in index.kinds["Shipment"])
    check(dict(split_counts) == world.config.split_counts, "SHIPMENT_SPLITS", world.config.dataset_id, "Configured total and split counts must match actual shipments")
    check(set(world.gold) == {n.id for n in index.kinds["Shipment"]}, "SCORING_COVERAGE", world.config.dataset_id, "Every shipment has separate scoring record, never an imported gold node")
    for shipment in index.kinds["Shipment"]:
        sid, sp = shipment.id, shipment.properties
        packages = {n.id for n in index.owned(sid, "Package")}
        check(packages == set(sp.get("package_ids", [])) and bool(packages), "SHIPMENT_MANIFEST", sid, "Manifest package IDs must equal owned package nodes")
        address_versions = defaultdict(list)
        for version in index.owned(sid, "AddressVersion"):
            address_versions[version.properties.get("address_id")].append(version)
        for versions in address_versions.values():
            ordered = sorted(versions, key=lambda n: n.properties.get("version", -1))
            check(len({n.properties.get("version") for n in ordered}) == len(ordered), "ADDRESS_VERSION_ORDER", sid, "Logical address versions must be unique")
            for left, right in zip(ordered, ordered[1:]):
                finish, begin = timestamp(left.properties.get("valid_to")), timestamp(right.properties.get("valid_from"))
                check(finish is not None and begin is not None and finish <= begin, "ADDRESS_VERSION_INTERVAL", sid, "Superseded address effective intervals cannot overlap")
        routes = index.owned(sid, "Route")
        for route in routes:
            segments = [nodes.get(ref) for ref in route.properties.get("segment_ids", [])]
            valid = all(n and n.kind == "RouteSegment" and n.properties.get("holdout_group") == sid for n in segments)
            check(bool(segments) and valid, "ROUTE_SEGMENTS", route.id, "Route must own an ordered segment list")
            if not valid:
                continue
            check([n.properties.get("sequence") for n in segments] == list(range(1, len(segments) + 1)), "ROUTE_ORDER", route.id, "Segment sequences must be contiguous and ordered")
            for left, right in zip(segments, segments[1:]):
                check(left.properties.get("to_id") == right.properties.get("from_id"), "ROUTE_CONNECTED", route.id, "Adjacent physical route segments must connect")
            for pos, segment in enumerate(segments):
                p = segment.properties
                frm, to = nodes.get(p.get("from_id")), nodes.get(p.get("to_id"))
                check(frm is not None and frm.kind in _FACILITIES and to is not None and (to.kind in _FACILITIES or pos == len(segments)-1 and to.kind in ("Address", "AddressVersion")),
                      "ROUTE_LOCATIONS", segment.id, "Route facilities must connect before final destination")
                minimum, maximum = number(p.get("minimum_seconds")), number(p.get("maximum_seconds"))
                check(minimum is not None and maximum is not None and 0 < minimum <= maximum, "ROUTE_DURATION", segment.id, "Contextual travel duration bounds must be positive ordered seconds")
        for session in index.owned(sid, "DeliverySession"):
            p = session.properties
            begin, end = timestamp(p.get("start_at")), timestamp(p.get("end_at"))
            if begin and end:
                local_begin, local_end = begin + timedelta(hours=3), end + timedelta(hours=3)
                check(p.get("timezone") == "Asia/Riyadh" and local_begin.date() == local_end.date()
                      and local_begin.strftime("%H:%M") == world.config.session_start and local_end.strftime("%H:%M") == world.config.session_end,
                      "DELIVERY_SESSION", session.id, "Local delivery session must match configured Riyadh window")
        for package in index.owned(sid, "Package"):
            milestones = sorted((n for n in index.owned(sid, "ExpectedMilestone") if n.properties.get("package_id") == package.id), key=lambda n: n.properties.get("sequence", -1))
            check(bool(milestones), "PACKAGE_EXPECTATIONS", package.id, "Each package requires ordered contextual expected milestones")
            for left, right in zip(milestones, milestones[1:]):
                lp, rp = left.properties, right.properties
                check(lp.get("sequence", -1) < rp.get("sequence", -1) and timestamp(lp.get("earliest_at")) is not None and timestamp(rp.get("earliest_at")) is not None
                      and timestamp(lp["earliest_at"]) <= timestamp(rp["earliest_at"]), "MILESTONE_ORDER", package.id, "Milestone order and earliest windows must be chronological")
            custody = sorted((n for n in index.owned(sid, "CustodyEvent") if n.properties.get("package_id") == package.id),
                             key=lambda n: n.properties.get("occurred_at", ""))
            holder = None
            for event in custody:
                if not custody_corroborated(world, event, config_cutoff):
                    continue
                check(holder is None or holder == event.properties.get("from_id"), "PHYSICAL_CUSTODY_CHAIN", event.id, "Unflagged confirmed custody cannot teleport between custodians")
                holder = event.properties.get("to_id")
        try:
            assessment = assess_shipment(world, sid, _index=index)
        except (ValueError, TypeError, KeyError, OverflowError):
            check(False, "ASSESSMENT_INPUT", sid, "Malformed observation fields prevent deterministic assessment")
            continue
        assessments[sid] = assessment
        cases, exceptions = index.owned(sid, "Case"), index.owned(sid, "Exception")
        derived_codes = {n.properties.get("code") for n in exceptions if n.properties.get("provenance") == str(Provenance.DERIVED)}
        check(derived_codes == set(assessment["supported_codes"]), "DERIVED_EVIDENCE_AGREEMENT", sid, "Exception codes must be recomputable from snapshot evidence, never recipe")
        check(bool(cases) == bool(assessment["supported_codes"]), "NORMAL_CASE_SEPARATION", sid, "Healthy journeys must not receive fabricated remediation Cases")
        if "CONFLICTING_CUSTODY" in assessment["supported_codes"]:
            check(any(n.properties.get("state", n.properties.get("status")) in ("HUMAN_REVIEW", "RESOLVED", "REOPENED") for n in cases),
                  "CONFLICT_HUMAN_REVIEW", sid, "Conflicting observations require investigation, not a declared physical holder")
        for case in cases:
            state = case.properties.get("state", case.properties.get("status"))
            if state == "RESOLVED":
                resolutions = children(case.id, "RESOLVED_BY", "Resolution")
                outcomes = [n for resolution in resolutions for n in children(resolution.id, "HAS_OUTCOME", "Outcome")]
                runs = children(case.id, "HAS_RUN", "AnalysisRun")
                recommendations = [n for run in runs for n in children(run.id, "PROPOSES", "Recommendation")]
                reviews = [n for rec in recommendations for n in children(rec.id, "REVIEWED_BY", "Review")]
                decisions = [n for rec in recommendations for n in children(rec.id, "HAS_DECISION", "OperatorDecision")]
                executions = [n for decision in decisions for n in children(decision.id, "INITIATES", "ActionExecution")]
                eligible = [n for n in outcomes if n.properties.get("verification_status") == "VERIFIED" and type(n.properties.get("success")) is bool
                            and n.properties.get("invalidated") is False and timestamp(n.properties.get("verified_at")) is not None and bool(n.properties.get("evidence_ids"))]
                check(bool(resolutions) and any(n.properties.get("verdict") == "accept" for n in reviews)
                      and any(n.properties.get("decision") == "approve" and n.properties.get("provenance") == str(Provenance.OPERATOR_DECISION) for n in decisions)
                      and any(bool(n.properties.get("receipt_ref")) and n.properties.get("status") in ("ACKNOWLEDGED_FIXTURE", "ACKNOWLEDGED", "SUCCEEDED") for n in executions)
                      and bool(eligible), "RESOLVED_EVIDENCE_CHAIN", case.id, "Resolved case requires linked accepted review, operator decision, external action receipt and verified noninvalidated observation")
                for outcome in eligible:
                    p = outcome.properties
                    check(all(ref in nodes and nodes[ref].properties.get("holdout_group") in (None, sid) for ref in p["evidence_ids"]),
                          "OUTCOME_EVIDENCE", outcome.id, "Outcome evidence must exist in same held-out group")
                    check(p.get("success") is True and p.get("status") == "succeeded", "RESOLVED_SUCCESS", case.id, "Failed observed outcomes remain failed/reopened, never resolved success")
                    approved = {n.id for n in decisions if n.properties.get("decision") == "approve"}
                    check(any(n.id in approved for n in children(outcome.id, "VERIFIED_BY", "OperatorDecision")),
                          "OUTCOME_VERIFIER_LINK", outcome.id, "Verifier must be the linked synthetic operator decision")
                    verified = timestamp(p.get("verified_at"))
                    for execution in executions:
                        at = timestamp(execution.properties.get("occurred_at"))
                        check(at is not None and verified is not None and at <= verified,
                              "EXECUTION_OUTCOME_CHRONOLOGY", outcome.id, "Observed outcome cannot precede action receipt")
                        check(execution.properties.get("action_type") == p.get("action_type"), "ACTION_OUTCOME_TYPE", outcome.id, "Outcome and executed action must describe the same condition")
                    evidence = [nodes[ref] for ref in p["evidence_ids"] if ref in nodes]
                    check(verified is not None and all(timestamp(n.properties.get("occurred_at", n.properties.get("effective_at"))) is not None
                          and timestamp(n.properties.get("occurred_at", n.properties.get("effective_at"))) <= verified for n in evidence),
                          "OUTCOME_EVIDENCE_CHRONOLOGY", outcome.id, "Verification cannot use future or untimed evidence")
                    action = p.get("action_type", "")
                    if action in ("delivery_reconciliation", "delivery", "redelivery"):
                        proofs = [n for n in evidence if n.kind == "DeliveryProof"]
                        check(bool(proofs) and all(proof_assessment(world, proof, verified)["corroborated"] for proof in proofs),
                              "DELIVERY_OUTCOME_PROOF", outcome.id, "Delivery outcome requires valid bound proof, not merely a data correction or GPS")
                    elif "barcode" in action or "weight" in action:
                        scans = [n for n in evidence if n.kind == "ScanEvent"]
                        condition = bool(scans)
                        for scan in scans:
                            pkg = nodes.get(scan.properties.get("package_id"))
                            if "barcode" in action:
                                condition &= bool(pkg and scan.properties.get("readable") is True and scan.properties.get("observed_barcode") == pkg.properties.get("manifest_barcode"))
                            if "weight" in action:
                                condition &= bool(pkg and scan.properties.get("calibrated") is True and number(scan.properties.get("measured_weight_kg")) == number(pkg.properties.get("weight_kg")))
                        check(condition, "ADMINISTRATIVE_OUTCOME_EVIDENCE", outcome.id, "Administrative correction verifies its data field and does not assert parcel delivery")
    vehicle_intervals, driver_intervals, vehicle_routes = defaultdict(list), defaultdict(list), defaultdict(list)
    for assignment in index.kinds["VehicleAssignment"]:
        p = assignment.properties
        begin, end = timestamp(p.get("valid_from")), timestamp(p.get("valid_to"))
        vehicle = nodes.get(p.get("vehicle_id"))
        driver = nodes.get(p.get("driver_id"))
        packages = [nodes.get(ref) for ref in p.get("package_ids", [])]
        if not check(vehicle is not None and vehicle.kind == "Vehicle" and driver is not None and driver.kind == "Driver"
                     and begin is not None and end is not None and begin < end and bool(packages) and all(n and n.kind == "Package" for n in packages),
                     "ASSIGNMENT_BINDING", assignment.id, "Assignment requires vehicle, interval and allocated packages"):
            continue
        weight = sum(number(n.properties.get("weight_kg")) or 0 for n in packages)
        volume = sum(number(n.properties.get("volume_m3")) or 0 for n in packages)
        check(number(p.get("weight_kg")) is not None and number(p.get("volume_m3")) is not None and math.isclose(number(p["weight_kg"]), weight, abs_tol=1e-6) and math.isclose(number(p["volume_m3"]), volume, abs_tol=1e-9),
              "ASSIGNMENT_ALLOCATION", assignment.id, "Allocated kg/m3 must equal package manifest sums")
        vp = vehicle.properties
        check(p.get("mode") in vp.get("modes", []) and all(n.properties.get("handling") in vp.get("handling", []) for n in packages),
              "VEHICLE_SUITABILITY", assignment.id, "Mode/handling must fit assigned vehicle")
        check(all(n.properties.get("holdout_group") == p.get("holdout_group") for n in packages), "ALLOCATION_HOLDOUT", assignment.id, "Package allocation cannot cross shipment group")
        vehicle_intervals[vehicle.id].append((begin, end, weight, volume, assignment.id))
        driver_intervals[p.get("driver_id")].append((begin, end, vehicle.id, assignment.id))
        segment = nodes.get(p.get("segment_id"))
        if segment and segment.kind == "RouteSegment":
            route_key = (segment.properties.get("from_id"), segment.properties.get("to_id"), p.get("mode"))
            vehicle_routes[vehicle.id].append((begin, end, route_key, assignment.id))
        session = nodes.get(p.get("session_id"))
        if session:
            session_start, session_end = timestamp(session.properties.get("start_at")), timestamp(session.properties.get("end_at"))
            check(session_start is not None and session_end is not None and begin < session_end and end > session_start,
                  "ASSIGNMENT_SESSION_INTERVAL", assignment.id, "Session allocation must overlap its actual local session")
    for vid, intervals in vehicle_intervals.items():
        events = sorted([(at, sign, weight * sign, volume * sign, key) for begin, end, weight, volume, key in intervals
                         for at, sign in ((begin, 1), (end, -1))], key=lambda row: (row[0], row[1], row[4]))
        kg = m3 = 0.0
        vp = nodes[vid].properties
        for at, sign, weight, volume, aid in events:
            kg, m3 = kg + weight, m3 + volume
            check(kg <= (number(vp.get("payload_kg")) or 0) + 1e-6 and m3 <= (number(vp.get("volume_m3")) or 0) + 1e-9,
                  "AGGREGATE_VEHICLE_CAPACITY", aid, "Overlapping allocations exceed vehicle payload kg or volume m3")
    for did, intervals in driver_intervals.items():
        active = []
        for begin, end, vid, aid in sorted(intervals):
            active = [row for row in active if row[0] > begin]
            check(not any(other_vid != vid for _, other_vid, _ in active), "DRIVER_INTERVAL", aid, "One driver cannot simultaneously operate different vehicles")
            active.append((end, vid, aid))
    for vid, intervals in vehicle_routes.items():
        active = []
        for begin, end, route_key, aid in sorted(intervals):
            active = [row for row in active if row[0] > begin]
            check(not any(other_route != route_key for _, other_route, _ in active), "VEHICLE_ROUTE_INTERVAL", aid,
                  "One vehicle cannot occupy incompatible route legs at overlapping times")
            active.append((end, route_key, aid))
    eligible = [n for n in index.kinds["Outcome"] if n.properties.get("split") == "history"
                and n.properties.get("verification_status") == "VERIFIED" and type(n.properties.get("success")) is bool
                and n.properties.get("invalidated") is False]
    facilities = Counter(n.kind for n in nodes.values() if n.kind in _FACILITIES)
    healthy_count = sum(not a["supported_codes"] and not index.owned(sid, "Case") for sid, a in assessments.items())
    check(healthy_count >= math.ceil(world.config.total * .55), "MAJORITY_HEALTHY_PROFILE", world.config.dataset_id,
          "Foundation profile requires a majority of evidence-healthy journeys without invented remediation")
    statistics = {"shipments": len(index.kinds["Shipment"]), "nodes": len(nodes), "edges": len(world.edges),
                  "splits": dict(split_counts), "cases": len(index.kinds["Case"]), "exceptions": len(index.kinds["Exception"]),
                  "error_count": len(errors), "synthetic": True, "network_calls": 0,
                  "flows": dict(Counter(n.properties.get("flow_type", "unknown") for n in index.kinds["Shipment"])),
                  "healthy_no_case": healthy_count,
                  "exception_shipments": sum(bool(a["supported_codes"]) for a in assessments.values()),
                  "origin_cities": dict(Counter(n.properties.get("origin_city", "unknown") for n in index.kinds["Shipment"])),
                  "destination_cities": dict(Counter(n.properties.get("destination_city", "unknown") for n in index.kinds["Shipment"])),
                  "cities": len(index.kinds["City"]), "organizations": len(index.kinds["Organization"]),
                  "facility_types": dict(facilities), "vehicles": len(index.kinds["Vehicle"]),
                  "vehicle_types": dict(Counter(n.properties.get("type_id", "unknown") for n in index.kinds["Vehicle"])),
                  "drivers": len(index.kinds["Driver"]), "routes": len(index.kinds["Route"]), "route_segments": len(index.kinds["RouteSegment"]),
                  "custody_events": len(index.kinds["CustodyEvent"]), "gps_observations": len(index.kinds["GPSObservation"]),
                  "traffic_observations": len(index.kinds["TrafficObservation"]),
                  "exception_codes": dict(Counter(code for a in assessments.values() for code in a["supported_codes"])),
                  "delivery_disputes": dict(Counter(d["assessment"] for a in assessments.values() for d in a["delivery_assessment"] if d["recipient_report_ids"])),
                  "custody_gaps": sum(bool(c["gap_event_ids"]) for a in assessments.values() for c in a["custody"]),
                  "next_session_priority_shipments": sum(a["next_session_priority"] for a in assessments.values()),
                  "resolved_history_cases": sum(n.properties.get("split") == "history" and n.properties.get("state", n.properties.get("status")) == "RESOLVED" for n in index.kinds["Case"]),
                  "eligible_history_outcomes": len(eligible), "eligible_successes": sum(n.properties["success"] is True for n in eligible),
                  "eligible_failures": sum(n.properties["success"] is False for n in eligible),
                  "invalidated_outcomes": sum(n.properties.get("invalidated") is True for n in index.kinds["Outcome"])}
    return {"pass": not errors, "errors": errors, "checks": dict(sorted(checked.items())), "statistics": statistics}
