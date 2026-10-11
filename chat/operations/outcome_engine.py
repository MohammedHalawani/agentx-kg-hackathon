"""Independent, action-specific outcome verifier for executed actions.

Only evidence that Suhail ingested AFTER the action was executed, visible at the clock, and
causally relevant to that action counts. Each action type has its own success and failure rule;
an unrelated later event (for example a delivery after a rescan request) never verifies a
different action. Silence until the action's deadline is a failure, never a success. A recipient
non-receipt report after the action contradicts any success. Neither the model, the requester
nor an operator can declare success: callers only pass the execution and the clock.
"""

from datetime import timedelta

from dataset_v2.contracts import instant
from dataset_v2.derive import custody_corroborated, number, proof_assessment

FACILITIES = ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse")
# Kept for the operator path: these actions only gather evidence.
EVIDENCE_ACTIONS = {"REQUEST_RESCAN", "REQUEST_REWEIGH", "REQUEST_ADDITIONAL_EVIDENCE", "REQUEST_DEVICE_SYNC"}
# A facility's answer to a check request when the parcel is not there (a ScanEvent with no read and no facility of
# presence: it says where someone looked, never where the parcel is).
NOT_FOUND = "FACILITY_CHECK_NOT_FOUND"


def _ingested_after(node, start, cutoff):
    """Recorded (ingested) after the action and visible now; occurred_at may legitimately be earlier for late uploads."""
    recorded = node.properties.get("recorded_at")
    occurred = node.properties.get("occurred_at")
    # Strictly after: evidence ingested in the same instant the action was executed predates it.
    return bool(recorded) and start < instant(recorded) <= cutoff and (not occurred or instant(occurred) <= cutoff)


def _made_after(node, start):
    """The observation itself was made after the action (not an older record that merely arrived late)."""
    occurred = node.properties.get("occurred_at")
    return bool(occurred) and instant(occurred) > start


def _result(status, outcome_type, evidence, reason):
    return {"status": status, "outcome_type": outcome_type, "evidence_ids": sorted({n.id if hasattr(n, "id") else n for n in evidence}),
            "reason": reason}


def evaluate(world, sid, execution, cutoff_text):
    """Return {"status", "outcome_type", "evidence_ids", "reason", "rule_id", "expected_effect"}."""
    from operations.authority import ACTIONS
    verdict = _evaluate(world, sid, execution, cutoff_text)
    action = execution["action_type"]
    verdict["rule_id"] = f"VERIFY-{action}-{verdict['outcome_type'] or 'pending'}".replace("_", "-").lower()
    verdict["expected_effect"] = ACTIONS[action][3] if action in ACTIONS else None
    return verdict


def _evaluate(world, sid, execution, cutoff_text):
    cutoff, start = instant(cutoff_text), instant(execution["occurred_at"])
    action = execution["action_type"]
    nodes = world.nodes
    packages = {n.id: n for n in nodes.values() if n.kind == "Package"}
    later = [n for n in nodes.values() if (n.properties.get("shipment_id") == sid or n.id == sid) and _ingested_after(n, start, cutoff)]
    reports = [n for n in later if n.kind == "RecipientReport" and n.properties.get("report_code") == "NOT_RECEIVED"]
    if reports:
        return _result("failure", "dispute_unresolved", reports, "A recipient reported non-receipt after the action.")
    policy = nodes.get(nodes[sid].properties.get("policy_id")) if sid in nodes else None
    pp = policy.properties if policy else {}
    verdict = None
    if action == "REQUEST_RESCAN":
        minimum = number(pp.get("barcode_min_confidence")) or 0
        scans = [n for n in later if n.kind == "ScanEvent" and n.properties.get("package_id") in packages and n.properties.get("readable") is True
                 and (number(n.properties.get("confidence")) or 0) >= minimum and n.properties.get("observed_barcode") is not None
                 and _made_after(n, start)]
        good = [n for n in scans if n.properties["observed_barcode"] == packages[n.properties["package_id"]].properties.get("manifest_barcode")]
        bad = [n for n in scans if n not in good]
        if bad:
            verdict = _result("failure", "barcode_still_differs", bad, "A readable rescan after the request still differs from the manifest barcode.")
        elif packages and set(packages) <= {n.properties["package_id"] for n in good}:
            verdict = _result("success", "barcode_corrected", good, "A readable rescan after the request matches the manifest barcode for every package.")
    elif action == "REQUEST_REWEIGH":
        absolute, relative = number(pp.get("weight_absolute_kg")) or 0, number(pp.get("weight_relative_fraction")) or 0
        measured = [n for n in later if n.kind == "ScanEvent" and n.properties.get("calibrated") is True
                    and n.properties.get("measurement_units") == "kg" and n.properties.get("package_id") in packages
                    and _made_after(n, start)]
        def within(n):
            expected = number(packages[n.properties["package_id"]].properties.get("weight_kg"))
            value = number(n.properties.get("measured_weight_kg"))
            return expected is not None and value is not None and abs(value - expected) <= max(absolute, expected * relative) + 1e-9
        bad = [n for n in measured if not within(n)]
        if bad:
            verdict = _result("failure", "weight_still_differs", bad, "A calibrated reweigh after the request still differs beyond tolerance.")
        elif packages and set(packages) <= {n.properties["package_id"] for n in measured}:
            verdict = _result("success", "weight_remeasured", measured, "A calibrated reweigh after the request is within tolerance for every package.")
    elif action == "REQUEST_DEVICE_SYNC":
        # The specific observations that were missing must arrive late: occurred before the request,
        # ingested after it, uploaded by the device the action targeted, and corroborated.
        expected = execution.get("expected_evidence") or []
        device = execution.get("target_device")
        # Held back, not merely in flight: it occurred early enough that a timely upload would have been
        # visible when the case opened, and it arrived only after the request.
        opened = instant(execution["case_opened_at"]) if execution.get("case_opened_at") else start
        allowance = timedelta(minutes=15)
        def uploader(n):
            return (nodes.get(n.properties.get("source_event_id")) or n).properties.get("device_ref")
        # Credited only to the device the request targeted: a record another device uploaded on its own (its natural
        # reconnect) is not this action's effect, and a request with no target device can confirm nothing.
        late = [n for n in later if n.kind == "CustodyEvent" and instant(n.properties["occurred_at"]) + allowance <= opened
                and custody_corroborated(world, n, cutoff) and bool(device) and uploader(n) == device]
        def covers(item):
            return any(n.properties.get("package_id") == item["package_id"] and n.properties.get("event_type") == item["predicate"]
                       and item["location_id"] in (n.properties.get("to_id"), n.properties.get("facility_id")) for n in late)
        if expected and all(covers(item) for item in expected):
            sources = [nodes[n.properties["source_event_id"]] for n in late if n.properties.get("source_event_id") in nodes]
            verdict = _result("success", "delayed_upload_received", late + sources,
                              "The missing observations arrived as late uploads from the target device; they occurred before the request.")
        elif not expected and late:
            verdict = _result("success", "delayed_upload_received", late, "Late uploads from the target device arrived after the request.")
    elif action in ("REQUEST_HUB_CHECK", "INITIATE_CUSTODY_RECONCILIATION"):
        if action == "INITIATE_CUSTODY_RECONCILIATION":
            found = [n for n in later if n.kind == "CustodyEvent" and nodes.get(n.properties.get("to_id")) is not None
                     and nodes[n.properties["to_id"]].kind in FACILITIES and custody_corroborated(world, n, cutoff)]
            outcome_type, reason = "custody_reconciled", "Corroborated custody at a facility was recorded for every package after the request."
        else:
            found = [n for n in later if n.kind == "ScanEvent" and n.properties.get("readable") is True and n.properties.get("facility_id")
                     and n.properties.get("observed_barcode") == (packages.get(n.properties.get("package_id")).properties.get("manifest_barcode")
                                                                  if packages.get(n.properties.get("package_id")) else None)]
            outcome_type, reason = "parcel_located", "A readable scan at a facility located every package after the check request."
        # The check itself must have been made after the request: an older scan arriving late is not its answer.
        found = [n for n in found if _made_after(n, start)]
        absent = [n for n in later if n.kind == "ScanEvent" and n.properties.get("observation_type") == NOT_FOUND
                  and n.properties.get("package_id") in packages and _made_after(n, start)]
        if packages and set(packages) <= {n.properties.get("package_id") for n in found}:
            verdict = _result("success", outcome_type, found, reason)
        elif absent and not found:
            verdict = _result("failure", "parcel_not_found", absent, "The facility checked after the request and did not find the parcel.")
    elif action == "REQUEST_ADDRESS_CONFIRMATION":
        confirmed = [n for n in later if n.kind == "AddressVersion" and n.properties.get("verification_status") == "VERIFIED"
                     and n.properties.get("confirmed_by") and _made_after(n, start)]
        if confirmed:
            verdict = _result("success", "address_confirmed", confirmed, "The recipient confirmed the effective address after the request.")
    elif action in ("PRIORITIZE_NEXT_SESSION", "REROUTE_TO_CONFIRMED_DESTINATION"):
        attempts = [n for n in later if n.kind == "DeliveryAttempt" and _made_after(n, start)]
        proofs = [(n, proof_assessment(world, n, cutoff)) for n in later if n.kind == "DeliveryProof" and _made_after(n, start)]
        covered = {n.properties.get("package_id") for n, row in proofs if row["corroborated"]}
        if packages and set(packages) <= covered:
            verdict = _result("success", "delivery_verified", [i for n, row in proofs if row["corroborated"] for i in row["evidence_ids"]],
                              "A corroborated delivery proof for every package was recorded in a later session.")
        elif any(n.properties.get("disposition") == "FAILED" for n in attempts):
            verdict = _result("failure", "delivery_failed_again", [n for n in attempts if n.properties.get("disposition") == "FAILED"],
                              "The prioritized delivery attempt failed.")
    elif action == "RETURN_TO_SENDER":
        # Corroborated receipt of every package at the facility the shipment was first handed over at, made after the request.
        origin = {}
        for n in sorted((n for n in nodes.values() if n.kind == "CustodyEvent"), key=lambda n: n.properties["occurred_at"]):
            holder = nodes.get(n.properties.get("to_id"))
            if holder is not None and holder.kind in FACILITIES:
                origin.setdefault(n.properties.get("package_id"), holder.id)
        back = [n for n in later if n.kind == "CustodyEvent" and _made_after(n, start)
                and n.properties.get("to_id") == origin.get(n.properties.get("package_id"))
                and n.properties.get("event_type") == "RECEIVED" and custody_corroborated(world, n, cutoff)]
        if packages and set(packages) <= {n.properties.get("package_id") for n in back}:
            verdict = _result("success", "returned_to_origin", back, "Corroborated receipt of every package at its origin facility was recorded after the request.")
    elif action == "REQUEST_ADDITIONAL_EVIDENCE":
        # The specific observations that were missing arrive after the request (they were made before it and held back).
        expected = execution.get("expected_evidence") or []
        held = [n for n in later if n.kind == "CustodyEvent" and instant(n.properties["occurred_at"]) <= start
                and custody_corroborated(world, n, cutoff)]
        def supplied(item):
            return any(n.properties.get("package_id") == item["package_id"] and n.properties.get("event_type") == item["predicate"]
                       and item["location_id"] in (n.properties.get("to_id"), n.properties.get("facility_id")) for n in held)
        if expected and all(supplied(item) for item in expected):
            verdict = _result("success", "requested_evidence_received", held, "The missing observations arrived after the request.")
    if verdict:
        return verdict
    if cutoff >= instant(execution["deadline_at"]):
        return _result("failure", "no_confirming_evidence", [], "No causally relevant confirming evidence arrived before the action deadline.")
    return _result("pending", None, [], "Waiting for evidence relevant to this action.")
