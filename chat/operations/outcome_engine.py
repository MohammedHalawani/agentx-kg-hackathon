"""Deterministic verifier for automatically executed synthetic actions.

Only evidence observed AFTER the action and visible at the scenario clock counts. No model
certifies success. Each action type has its own success and failure rule; silence until the
action's deadline is a failure, never a success.
"""
from dataset_v2.contracts import instant
from dataset_v2.derive import proof_assessment, custody_corroborated

EVIDENCE_ACTIONS = {"REQUEST_RESCAN", "REQUEST_REWEIGH", "REQUEST_ADDITIONAL_EVIDENCE"}


def _after(node, start, cutoff):
    when = node.properties.get("occurred_at")
    return bool(when) and start <= instant(when) <= cutoff


def evaluate(world, sid, execution, cutoff_text):
    """Return {"status": "success"|"failure"|"pending", "outcome_type", "evidence_ids", "reason"}."""
    cutoff, start = instant(cutoff_text), instant(execution["occurred_at"])
    action = execution["action_type"]
    owned = [n for n in world.nodes.values() if n.properties.get("shipment_id") == sid or n.id == sid]
    packages = {n.id: n for n in world.nodes.values() if n.kind == "Package"}
    later = [n for n in owned if _after(n, start, cutoff)]
    # Any new non-receipt report overrides everything: a person must look.
    reports = [n for n in later if n.kind == "RecipientReport" and n.properties.get("report_code") == "NOT_RECEIVED"]
    if reports:
        return {"status": "failure", "outcome_type": "dispute_unresolved", "evidence_ids": [n.id for n in reports],
                "reason": "A recipient reported non-receipt after the action."}
    scans = [n for n in later if n.kind == "ScanEvent" and n.properties.get("readable") is True and n.properties.get("package_id") in packages]
    if action == "REQUEST_RESCAN":
        good = [n for n in scans if n.properties.get("observed_barcode") == packages[n.properties["package_id"]].properties.get("manifest_barcode")]
        bad = [n for n in scans if n not in good and n.properties.get("observed_barcode")]
        if good:
            return {"status": "success", "outcome_type": "barcode_corrected", "evidence_ids": [n.id for n in good],
                    "reason": "A later readable scan matches the manifest barcode."}
        if bad:
            return {"status": "failure", "outcome_type": "insufficient_evidence", "evidence_ids": [n.id for n in bad],
                    "reason": "A later readable scan still conflicts with the manifest barcode."}
    if action == "REQUEST_REWEIGH":
        measured = [n for n in later if n.kind == "ScanEvent" and n.properties.get("calibrated") is True
                    and n.properties.get("measurement_units") == "kg" and n.properties.get("package_id") in packages]
        good = [n for n in measured if n.properties.get("measured_weight_kg") == packages[n.properties["package_id"]].properties.get("weight_kg")]
        if good:
            return {"status": "success", "outcome_type": "weight_remeasured", "evidence_ids": [n.id for n in good],
                    "reason": "A later calibrated measurement matches the manifest weight."}
        if measured:
            return {"status": "failure", "outcome_type": "insufficient_evidence", "evidence_ids": [n.id for n in measured],
                    "reason": "A later calibrated measurement still differs from the manifest weight."}
    if action == "REQUEST_ADDRESS_CONFIRMATION":
        confirmed = [n for n in later if n.kind == "AddressVersion" and n.properties.get("verification_status") == "VERIFIED"
                     and n.properties.get("confirmed_by")]
        if confirmed:
            return {"status": "success", "outcome_type": "address_corrected", "evidence_ids": [n.id for n in confirmed],
                    "reason": "The recipient confirmed the effective address after the request."}
    # Every action family is satisfied by corroborated delivery of every package after the action.
    proofs = [n for n in later if n.kind == "DeliveryProof"]
    rows = [(n, proof_assessment(world, n, cutoff)) for n in proofs]
    covered = {n.properties.get("package_id") for n, row in rows if row["corroborated"]}
    if packages and set(packages) <= covered:
        ids = sorted({i for n, row in rows if row["corroborated"] for i in [n.id, *row["evidence_ids"]]})
        return {"status": "success", "outcome_type": "delivery_verified", "evidence_ids": ids,
                "reason": "Corroborated delivery proof for every package after the action."}
    if action in ("INITIATE_CUSTODY_RECONCILIATION", "REQUEST_HUB_CHECK"):
        custody = [n for n in later if n.kind == "CustodyEvent" and custody_corroborated(world, n, cutoff)]
        if packages and set(packages) <= {n.properties.get("package_id") for n in custody}:
            return {"status": "success", "outcome_type": "custody_reconciled", "evidence_ids": [n.id for n in custody],
                    "reason": "Corroborated custody for every package was recorded after the request."}
    if cutoff >= instant(execution["deadline_at"]):
        return {"status": "failure", "outcome_type": "insufficient_evidence", "evidence_ids": [],
                "reason": "No confirming evidence arrived before the action deadline."}
    return {"status": "pending", "outcome_type": None, "evidence_ids": [], "reason": "Waiting for later evidence."}
