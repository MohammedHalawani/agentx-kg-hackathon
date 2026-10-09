"""Deterministic assessments from observations, never scoring recipes or gold causes.

All clocks come from the frozen shipment/config snapshot. No I/O or external authority
is implied by a derived exception, a synthetic proof or a human-review disposition.
"""
from collections import defaultdict
from datetime import timedelta
import math

from dataset_v2.contracts import DERIVATION_VERSION, Provenance, World, digest, instant


class EvidenceIndex:
    """Group once so a 2,000 shipment derivation does not repeatedly scan the world."""

    def __init__(self, world: World):
        self.world = world
        self.groups = defaultdict(lambda: defaultdict(list))
        self.kinds = defaultdict(list)
        self.outgoing = defaultdict(list)
        for node in world.nodes.values():
            self.kinds[node.kind].append(node)
            self.groups[node.properties.get("holdout_group")][node.kind].append(node)
        for edge in world.edges.values():
            self.outgoing[edge.start].append(edge)

    def owned(self, sid, kind):
        return self.groups[sid][kind]


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    try:
        return instant(value) if isinstance(value, str) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _observed(node, cutoff):
    p = node.properties
    at = timestamp(p.get("occurred_at", p.get("start_at")))
    recorded = timestamp(p.get("recorded_at"))
    return at is not None and recorded is not None and at <= recorded <= cutoff


def _bound(node, package_id, attempt_id=None):
    if node is None or node.properties.get("package_id") != package_id:
        return False
    return attempt_id is None or node.properties.get("attempt_id") == attempt_id


def point_distance_m(a, b):
    coordinates = [number(row.get(key)) for row in (a, b) for key in ("lat", "lng")]
    if any(value is None for value in coordinates):
        return None
    lat1, lng1, lat2, lng2 = map(math.radians, coordinates)
    x = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lng2-lng1)/2)**2
    return 6_371_000 * 2 * math.asin(min(1, math.sqrt(x)))


def proof_assessment(world, proof, cutoff):
    """Proof role is evidence, not an automatic denial of a recipient's report."""
    p = proof.properties
    package, attempt_id = p.get("package_id"), p.get("attempt_id")
    attempt = world.nodes.get(attempt_id)
    proof_at = timestamp(p.get("occurred_at"))
    reasons, evidence = [], [proof.id]
    if not _observed(proof, cutoff):
        reasons.append("proof_not_observed_at_snapshot")
    if (not _bound(attempt, package) or attempt.kind != "DeliveryAttempt"
            or attempt.properties.get("disposition") != "DELIVERED" or not _observed(attempt, cutoff)
            or proof_at is None or timestamp(attempt.properties.get("occurred_at")) > proof_at):
        reasons.append("missing_or_unbound_delivered_attempt")
    elif p.get("address_version_id") != attempt.properties.get("used_address_version_id"):
        reasons.append("attempt_address_binding_conflict")
    else:
        evidence.append(attempt.id)
    address = world.nodes.get(p.get("address_version_id"))
    if address is None or address.kind != "AddressVersion":
        reasons.append("missing_address_version")
    else:
        distance = point_distance_m(p, address.properties)
        uncertainty = [number(row.get("accuracy_m")) for row in (p, address.properties)]
        if distance is not None and all(value is not None for value in uncertainty) and distance > sum(uncertainty):
            reasons.append("proof_point_outside_bound_address_uncertainty")
    owner = world.nodes.get(p.get("holdout_group"))
    recipient = owner.properties.get("recipient_id") if owner else None
    handoff = world.nodes.get(p.get("handoff_id"))
    hp = handoff.properties if handoff else {}
    alternate = (hp.get("recipient_type") == "AUTHORIZED_ALTERNATE" and bool(hp.get("authorization_ref"))
                 and _bound(handoff, package, attempt_id))
    allowed_recipient = hp.get("recipient_id") if alternate else recipient
    valid_components = {}
    for field, kind in (("authentication_id", "AuthenticationEvidence"),
                        ("signature_id", "SignatureEvidence"), ("photo_id", "PhotoEvidence"),
                        ("handoff_id", "HandoffEvidence")):
        component = world.nodes.get(p.get(field))
        if component is None:
            continue
        evidence.append(component.id)
        cp = component.properties
        valid = component.kind == kind and _bound(component, package, attempt_id) and _observed(component, cutoff)
        if kind == "AuthenticationEvidence":
            expiry, captured = timestamp(cp.get("expires_at")), timestamp(cp.get("occurred_at"))
            valid = valid and cp.get("method") in ("SYNTHETIC_OTP", "SYNTHETIC_PIN") and cp.get("result") == "PASS" and expiry is not None and captured is not None and captured <= expiry
            valid = valid and bool(cp.get("authorized_recipient_id")) and cp.get("authorized_recipient_id") == allowed_recipient
        if kind == "SignatureEvidence":
            valid = valid and cp.get("recipient_id") == allowed_recipient and cp.get("proof_type") == "SYNTHETIC_ACKNOWLEDGMENT"
        if kind == "PhotoEvidence":
            valid = valid and cp.get("address_version_id") == p.get("address_version_id")
            if address:
                distance = point_distance_m(cp, address.properties)
                accuracy = [number(row.get("accuracy_m")) for row in (cp, address.properties)]
                valid = valid and distance is not None and all(value is not None for value in accuracy) and distance <= sum(accuracy)
        if kind == "HandoffEvidence" and cp.get("recipient_type") not in ("RECIPIENT", "PRIMARY", "ADDRESSEE", "EXPECTED_RECIPIENT"):
            valid = valid and bool(cp.get("authorization_ref"))
        elif kind == "HandoffEvidence":
            valid = valid and cp.get("recipient_id") == recipient
        captured, proof_at = timestamp(cp.get("occurred_at")), timestamp(p.get("occurred_at"))
        valid = valid and captured is not None and proof_at is not None and captured <= proof_at
        valid_components[kind] = bool(valid)
        if not valid:
            reasons.append(f"invalid_{kind}")
    # A photo alone cannot authenticate a recipient. All supplied components must bind.
    corroborated = any(valid_components.get(kind) for kind in ("AuthenticationEvidence", "SignatureEvidence", "HandoffEvidence"))
    if not corroborated:
        reasons.append("no_authenticated_or_signed_or_authorized_handoff")
    return {"proof_id": proof.id, "corroborated": not reasons, "reasons": reasons,
            "evidence_ids": sorted(set(evidence)), "synthetic": True}


def custody_corroborated(world, event, cutoff):
    p = event.properties
    required, received = p.get("required_acknowledgments"), p.get("received_acknowledgments")
    source = world.nodes.get(p.get("source_event_id"))
    valid = (type(required) is int and type(received) is int and required > 0 and received >= required
             and p.get("source_quality") == "CORROBORATED" and _observed(event, cutoff)
             and source is not None and _observed(source, cutoff) and source.properties.get("package_id") == p.get("package_id"))
    if p.get("event_type") == "DELIVERED":
        proof = world.nodes.get(p.get("proof_id")) or (source if source and source.kind == "DeliveryProof" else None)
        valid = valid and proof is not None and proof.kind == "DeliveryProof" and proof_assessment(world, proof, cutoff)["corroborated"]
    return bool(valid)


def assess_shipment(world: World, sid: str, as_of: str | None = None, *, _index=None, detection_allowance_seconds=0) -> dict:
    """detection_allowance_seconds: extra wait a live monitor gives provider uploads before calling an
    expected observation missing (normal ingestion lag must not open cases). Zero for offline use."""
    index = _index or EvidenceIndex(world)
    shipment = world.nodes.get(sid)
    if shipment is None or shipment.kind != "Shipment":
        raise ValueError("Unknown shipment")
    cutoff_text = as_of or shipment.properties.get("as_of") or world.config.as_of
    cutoff = instant(cutoff_text)
    flags, comparisons, custodians, disputes, next_priority = {}, [], [], [], False
    def fresh(node):
        """Recorded within the live detection allowance: its companion records may not have arrived yet."""
        recorded = timestamp(node.properties.get("recorded_at"))
        return bool(detection_allowance_seconds) and recorded is not None and cutoff - recorded < timedelta(seconds=detection_allowance_seconds)
    def flag(code, ids, reason, human=False):
        current = flags.setdefault(code, {"code": code, "evidence_ids": [], "reasons": [], "requires_human_review": False})
        current["evidence_ids"] = sorted(set(current["evidence_ids"]) | {key for key in ids if key in world.nodes})
        if reason not in current["reasons"]:
            current["reasons"].append(reason)
        current["requires_human_review"] |= human
    policy = world.nodes.get(shipment.properties.get("policy_id"))
    pp = policy.properties if policy else {}
    barcode_min = number(pp.get("barcode_min_confidence"))
    abs_tolerance, relative_tolerance = number(pp.get("weight_absolute_kg")), number(pp.get("weight_relative_fraction"))
    owned = index.groups[sid]
    observations = {kind: [node for node in nodes if _observed(node, cutoff)] for kind, nodes in owned.items()}
    package_ids = shipment.properties.get("package_ids", [])
    for package_id in package_ids:
        package = world.nodes.get(package_id)
        if package is None:
            flag("INSUFFICIENT_EVIDENCE", [sid], "Manifest package is missing", True)
            continue
        manifest = package.properties
        for scan in observations.get("ScanEvent", []):
            sp = scan.properties
            if sp.get("package_id") != package_id:
                continue
            confidence = number(sp.get("confidence"))
            readable = sp.get("readable") is True and confidence is not None and barcode_min is not None and confidence >= barcode_min
            if readable and sp.get("observed_barcode") is not None:
                equal = sp["observed_barcode"] == manifest.get("manifest_barcode")
                comparisons.append({"predicate": "BARCODE", "package_id": package_id, "evidence_id": scan.id,
                                    "expected": manifest.get("manifest_barcode"), "actual": sp["observed_barcode"], "matches": equal})
                if not equal:
                    flag("BARCODE_MISMATCH", [package_id, scan.id], "Readable high-confidence barcode differs from manifest")
            measured, expected = number(sp.get("measured_weight_kg")), number(manifest.get("weight_kg"))
            if sp.get("calibrated") is True and None not in (measured, expected, abs_tolerance, relative_tolerance):
                tolerance = max(abs_tolerance, expected * relative_tolerance)
                equal = abs(measured - expected) <= tolerance + 1e-9
                comparisons.append({"predicate": "WEIGHT_KG", "package_id": package_id, "evidence_id": scan.id,
                                    "expected": expected, "actual": measured, "tolerance_kg": tolerance, "matches": equal})
                if not equal:
                    flag("WEIGHT_MISMATCH", [package_id, scan.id], "Calibrated kg observation differs beyond contextual tolerance")
        events = sorted((n for n in observations.get("CustodyEvent", []) if n.properties.get("package_id") == package_id),
                        key=lambda n: (n.properties["occurred_at"], n.id))
        holder, last_id, gaps, conflicting = None, None, [], False
        confirmed_ids = set()
        simultaneous = defaultdict(list)
        for event in events:
            ep = event.properties
            simultaneous[(ep.get("occurred_at"), ep.get("from_id"))].append(event)
        conflicts = {}
        for reports in simultaneous.values():
            for left in reports:
                lp = left.properties
                for right in reports:
                    rp = right.properties
                    if (left.id != right.id and lp.get("to_id") != rp.get("to_id")
                            and lp.get("source_event_id") != rp.get("source_event_id")
                            and lp.get("source_ref") != rp.get("source_ref")):
                        conflicts.setdefault(left.id, set()).update((left.id, right.id))
        for event in events:
            ep = event.properties
            source = world.nodes.get(ep.get("source_event_id"))
            corroborated = custody_corroborated(world, event, cutoff)
            conflict = event.id in conflicts
            if conflict:
                conflicting = True
                flag("CONFLICTING_CUSTODY", [*conflicts[event.id], last_id], "Independent simultaneous reports name incompatible holders; human investigation required", True)
            elif not corroborated and fresh(event):
                continue  # Companion uploads (the source scan) may still be in flight; judge after the allowance.
            elif not corroborated:
                gaps.append(event.id)
                flag("CUSTODY_GAP", [event.id, source.id if source else None], "Transition lacks acknowledgments or bound source observation", True)
            elif holder is not None and ep.get("from_id") != holder:
                gaps.append(event.id)
                flag("CUSTODY_GAP", [event.id, last_id], "Missing transition between last corroborated holder and reported transfer source", True)
            else:
                holder, last_id = ep.get("to_id"), event.id
                confirmed_ids.add(event.id)
        # Dispatch manifests: the latest published version of an assignment's manifest must still list
        # a package whose physical loading onto that assignment was corroborated.
        latest = {}
        for manifest in observations.get("Manifest", []):
            key = manifest.properties.get("assignment_id")
            if key and (key not in latest or (manifest.properties.get("version") or 0) > (latest[key].properties.get("version") or 0)):
                latest[key] = manifest
        for event in events:
            manifest = latest.get(event.properties.get("assignment_id"))
            if (manifest is not None and event.id in confirmed_ids and event.properties.get("event_type") == "LOADED"
                    and package_id not in (manifest.properties.get("package_ids") or [])):
                flag("MANIFEST_CONFLICT", [manifest.id, event.id], "Latest dispatch manifest omits a package whose loading was corroborated", True)
        custodians.append({"package_id": package_id, "last_corroborated_holder_id": holder,
                           "last_corroborated_event_id": last_id, "gap_event_ids": gaps,
                           "conflicting": conflicting, "parcel_location_from_gps": None})
        for milestone in owned.get("ExpectedMilestone", []):
            mp = milestone.properties
            if mp.get("package_id") != package_id:
                continue
            latest, earliest = timestamp(mp.get("latest_at")), timestamp(mp.get("earliest_at"))
            candidates = [event for event in events if event.properties.get("event_type") == mp.get("predicate")
                          and (event.properties.get("to_id") == mp.get("location_id")
                               or event.properties.get("facility_id") == mp.get("location_id"))
                          and event.id in confirmed_ids]
            observed = min((timestamp(n.properties["occurred_at"]) for n in candidates), default=None)
            grace = number(mp.get("grace_seconds")) or 0
            due = latest is not None and cutoff > latest + timedelta(seconds=grace + detection_allowance_seconds)
            late = observed is not None and latest is not None and observed > latest + timedelta(seconds=grace)
            comparisons.append({"predicate": mp.get("predicate"), "package_id": package_id, "milestone_id": milestone.id,
                                "location_id": mp.get("location_id"), "earliest_at": mp.get("earliest_at"), "latest_at": mp.get("latest_at"),
                                "actual_at": observed.isoformat() if observed else None, "due": due, "late": late,
                                "missing_due": due and observed is None})
            if due and observed is None:
                flag("MISSED_MILESTONE", [milestone.id, last_id], "Expected observation absent after contextual deadline and grace")
            elif late:
                flag("JOURNEY_DELAY", [milestone.id, *[n.id for n in candidates]], "Observed milestone beyond contextual latest time and grace")
        attempts = [n for n in observations.get("DeliveryAttempt", []) if n.properties.get("package_id") == package_id]
        for attempt in attempts:
            ap = attempt.properties
            av = world.nodes.get(ap.get("used_address_version_id"))
            valid_at = timestamp(ap.get("occurred_at"))
            if av and (timestamp(av.properties.get("valid_from")) is not None and valid_at < timestamp(av.properties["valid_from"])
                       or timestamp(av.properties.get("valid_to")) is not None and valid_at >= timestamp(av.properties["valid_to"])):
                flag("ADDRESS_CONFLICT", [attempt.id, av.id], "Attempt used an address version outside its effective interval")
            for instruction in owned.get("DeliveryInstruction", []):
                ip = instruction.properties
                begin, end = timestamp(ip.get("valid_from")), timestamp(ip.get("valid_to"))
                if (ip.get("address_version_id") == ap.get("used_address_version_id") and begin is not None and begin <= valid_at
                        and (end is None or valid_at < end) and ap.get("observed_gate") is not None and ip.get("gate") != ap.get("observed_gate")):
                    flag("WRONG_GATE", [attempt.id, instruction.id], "Observed gate differs from instruction effective at attempt")
            contacts = [n for n in observations.get("ContactAttempt", []) if n.properties.get("attempt_id") == attempt.id]
            if ap.get("failed_reason") == "RECIPIENT_NOT_REACHED" and any(n.properties.get("result") == "NO_RESPONSE" for n in contacts):
                flag("RECIPIENT_UNAVAILABLE", [attempt.id, *[n.id for n in contacts]], "Attributed failed contact corroborated by separate no-response observations")
            if ap.get("failed_reason") == "SESSION_WINDOW_CLOSED" and any(n.properties.get("result") == "AGREED_NEXT_SESSION" for n in contacts):
                next_priority = True
        proofs = [proof_assessment(world, n, cutoff) for n in observations.get("DeliveryProof", []) if n.properties.get("package_id") == package_id]
        reports = [n for n in observations.get("RecipientReport", []) if n.properties.get("package_id") == package_id and n.properties.get("report_code") == "NOT_RECEIVED"]
        if reports:
            point_conflict = any("proof_point_outside_bound_address_uncertainty" in p["reasons"] for p in proofs)
            state = ("POSSIBLE_MISDELIVERY" if point_conflict else
                     "CONFLICTING_EVIDENCE" if any(p["corroborated"] for p in proofs) else "INSUFFICIENT_EVIDENCE")
            flag("DELIVERY_DISPUTE", [*[n.id for n in reports], *[p["proof_id"] for p in proofs]], "Attributed recipient report requires investigation despite proof type", True)
        elif proofs:
            state = "CORROBORATED_DELIVERY" if any(p["corroborated"] for p in proofs) else "INSUFFICIENT_EVIDENCE"
        else:
            state = "NO_DELIVERY_PROOF"
        if proofs and not any(p["corroborated"] for p in proofs) and not all(
                fresh(world.nodes[p["proof_id"]]) for p in proofs):
            flag("PROOF_INSUFFICIENT", [p["proof_id"] for p in proofs], "Proof requires bound recipient corroboration; method alone is insufficient", True)
        disputes.append({"package_id": package_id, "assessment": state, "proofs": proofs,
                         "recipient_report_ids": [n.id for n in reports], "alternatives": ["possible_misdelivery", "conflicting_evidence", "insufficient_evidence", "human_review"] if reports else []})
        for session in owned.get("DeliverySession", []):
            sp = session.properties
            # Only assess sessions actually allocated this package.
            assigned = any(n.properties.get("session_id") == session.id and package_id in n.properties.get("package_ids", []) for n in owned.get("VehicleAssignment", []))
            end = timestamp(sp.get("end_at"))
            if not assigned or end is None or cutoff <= end + timedelta(seconds=(number(sp.get("grace_seconds")) or 0) + detection_allowance_seconds):
                continue
            reconciled = False
            for reconciliation in observations.get("DepotReconciliation", []):
                rp = reconciliation.properties
                if rp.get("package_id") != package_id or rp.get("session_id") != session.id:
                    continue
                if rp.get("result") == "DELIVERED":
                    reconciled |= any(p["proof_id"] == rp.get("proof_id") and p["corroborated"] for p in proofs)
                if rp.get("result") == "RETURNED":
                    failed, receipt = world.nodes.get(rp.get("attempt_id")), world.nodes.get(rp.get("receipt_id"))
                    reconciled |= (failed is not None and failed.properties.get("package_id") == package_id and failed.properties.get("disposition") == "FAILED"
                                   and receipt is not None and receipt.id == last_id and holder == sp.get("depot_id"))
                    next_priority |= reconciled
            if not reconciled:
                flag("UNRECONCILED_CUSTODY", [session.id, last_id], "No valid delivery proof or failed attempt plus corroborated depot receipt after session grace", True)
    if any(code in flags for code in ("MISSED_MILESTONE", "JOURNEY_DELAY")):
        for traffic in observations.get("TrafficObservation", []):
            tp = traffic.properties
            delay, confidence = number(tp.get("delay_seconds")), number(tp.get("confidence"))
            if delay is not None and delay > 0 and confidence is not None and confidence >= .9:
                flag("TRAFFIC_DELAY", [traffic.id, tp.get("segment_id")], "Observed route traffic delay corroborates missed/late journey expectations; no parcel position or personal blame inferred")
    codes = sorted(flags)
    return {"shipment_id": sid, "as_of": cutoff_text, "derivation_version": DERIVATION_VERSION,
            "synthetic": True, "supported_codes": codes, "exceptions": [flags[key] for key in codes],
            "expected_vs_actual": comparisons, "custody": custodians, "delivery_assessment": disputes,
            "requires_human_review": any(v["requires_human_review"] for v in flags.values()),
            "next_session_priority": next_priority, "lost": False}


def derive_world(world: World) -> World:
    index = EvidenceIndex(world)
    for shipment in sorted(index.kinds["Shipment"], key=lambda n: n.id):
        sid = shipment.id
        assessment = assess_shipment(world, sid, _index=index)
        # Gold is an output sink only: no label/recipe influences assessment or Case state.
        world.gold.setdefault(sid, {})["assessment"] = assessment
        if not assessment["exceptions"]:
            continue
        split = shipment.properties["split"]
        case_id = "DEMO-CASE-" + digest([sid, DERIVATION_VERSION])[:24]
        if case_id not in world.nodes:
            world.node("Case", case_id, shipment_id=sid, split=split, provenance=Provenance.DERIVED,
                       state="HUMAN_REVIEW" if assessment["requires_human_review"] else "OPEN", opened_at=assessment["as_of"],
                       as_of=assessment["as_of"], recorded_at=assessment["as_of"], source_ref=f"{DERIVATION_VERSION}:derive",
                       codes=assessment["supported_codes"], derivation_version=DERIVATION_VERSION)
        world.edge(case_id, "ABOUT", sid, provenance=str(Provenance.DERIVED))
        for item in assessment["exceptions"]:
            eid = "DEMO-EXCEPTION-" + digest([sid, item["code"], DERIVATION_VERSION])[:24]
            if eid not in world.nodes:
                world.node("Exception", eid, shipment_id=sid, split=split, provenance=Provenance.DERIVED,
                           code=item["code"], evidence_ids=item["evidence_ids"], reasons=item["reasons"],
                           as_of=assessment["as_of"], recorded_at=assessment["as_of"], source_ref=f"{DERIVATION_VERSION}:derive",
                           requires_human_review=item["requires_human_review"], derivation_version=DERIVATION_VERSION)
            world.edge(sid, "HAS_EXCEPTION", eid, provenance=str(Provenance.DERIVED))
            world.edge(case_id, "HAS_EXCEPTION", eid, provenance=str(Provenance.DERIVED))
            for evidence_id in item["evidence_ids"]:
                world.edge(eid, "SUPPORTED_BY", evidence_id, provenance=str(Provenance.DERIVED))
    return world
