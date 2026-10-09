"""Action-bound evidence gates; only an independent local operator verifies outcomes."""
from dataset_v2.contracts import instant
from dataset_v2.derive import proof_assessment, custody_corroborated
from operations.reasoning import evidence_world
from operations.lifecycle import OperationsConflict, require_actor

OUTCOME_TYPES = frozenset(("delivery_verified", "address_corrected", "barcode_corrected", "weight_remeasured",
                          "returned_to_depot", "dispute_unresolved", "insufficient_evidence", "custody_reconciled"))


def validate_observation(context, evidence_ids, outcome_type, success):
    nodes = {node["id"]: node for node in context["nodes"]}
    if (outcome_type not in OUTCOME_TYPES or type(success) is not bool or not isinstance(evidence_ids, list)
            or not 0 < len(evidence_ids) <= 100 or len(set(evidence_ids)) != len(evidence_ids)
            or not set(evidence_ids) <= nodes.keys()):
        raise OperationsConflict("Outcome requires visible own evidence and an explicit observed success/failure")
    if success and outcome_type in {"dispute_unresolved", "insufficient_evidence"}:
        raise OperationsConflict("Unresolved/insufficient evidence cannot be successful resolution")
    return nodes


def verify(context, config, outcome, execution, actor_id, authority):
    require_actor(actor_id, authority)
    nodes = validate_observation(context, outcome["evidence_ids"], outcome["outcome_type"], outcome["success"])
    if not execution or not execution.get("receipt_ref") or execution.get("status") != "ACKNOWLEDGED":
        raise OperationsConflict("Outcome verification requires an operator-approved execution receipt")
    if outcome.get("invalidated") or outcome.get("verification_status") != "OBSERVED":
        raise OperationsConflict("Outcome is stale or already verified")
    if not outcome["success"]:
        return {"resolved": False, "workflow_state": "HUMAN_REVIEW"}
    world = evidence_world(context, config)
    selected = [world.nodes[key] for key in outcome["evidence_ids"]]
    kind, action = outcome["outcome_type"], execution["action_code"]
    cutoff = instant(context["as_of"])
    accepted = False
    if kind == "delivery_verified" and action in {"DELIVERY_DISPUTE", "PROOF_INSUFFICIENT", "UNRECONCILED_CUSTODY", "CUSTODY_GAP",
                                                 "MISSED_MILESTONE", "JOURNEY_DELAY", "TRAFFIC_DELAY", "SLA_RISK"}:
        assessments = [proof_assessment(world, node, cutoff) for node in selected if node.kind == "DeliveryProof"]
        packages = {node.id for node in world.nodes.values() if node.kind == "Package"}
        covered = {node.properties.get("package_id") for node in selected if node.kind == "DeliveryProof"
                   and instant(node.properties["occurred_at"]) >= instant(execution["occurred_at"])}
        # Every component used to certify delivery must be explicitly included in operator evidence.
        accepted = bool(packages) and packages <= covered and bool(assessments) and all(row["corroborated"] and set(row["evidence_ids"]) <= set(outcome["evidence_ids"])
                                             for row in assessments)
        reports = [node for node in world.nodes.values() if node.kind == "RecipientReport" and node.properties.get("report_code") == "NOT_RECEIVED"]
        if reports:
            accepted = False  # Existing contradictory recipient reports require new independent evidence, not dismissal.
    elif kind == "address_corrected" and action in {"ADDRESS_CONFLICT", "WRONG_GATE"}:
        accepted = any(node.kind == "AddressVersion" and node.properties.get("verification_status") == "VERIFIED"
                       and node.properties.get("confirmed_by") for node in selected)
    elif kind == "barcode_corrected" and action == "BARCODE_MISMATCH":
        accepted = any(node.kind == "ScanEvent" and node.properties.get("readable") is True
                       and world.nodes.get(node.properties.get("package_id"))
                       and node.properties.get("observed_barcode") == world.nodes[node.properties["package_id"]].properties.get("manifest_barcode")
                       and instant(node.properties["occurred_at"]) >= instant(execution["occurred_at"]) for node in selected)
    elif kind == "weight_remeasured" and action == "WEIGHT_MISMATCH":
        accepted = any(node.kind == "ScanEvent" and node.properties.get("calibrated") is True
                       and node.properties.get("measurement_units") == "kg" and world.nodes.get(node.properties.get("package_id"))
                       and node.properties.get("measured_weight_kg") == world.nodes[node.properties["package_id"]].properties.get("weight_kg")
                       and instant(node.properties["occurred_at"]) >= instant(execution["occurred_at"]) for node in selected)
    elif kind == "returned_to_depot" and action in {"TRAFFIC_DELAY", "UNRECONCILED_CUSTODY", "CUSTODY_GAP"}:
        returned = [node for node in selected if node.kind == "CustodyEvent" and node.properties.get("event_type") == "RETURNED"
                       and world.nodes.get(node.properties.get("to_id"))
                       and world.nodes[node.properties["to_id"]].kind == "DeliveryDepot"
                       and custody_corroborated(world, node, cutoff)
                       and instant(node.properties["occurred_at"]) >= instant(execution["occurred_at"])]
        packages = {node.id for node in world.nodes.values() if node.kind == "Package"}
        covered = {node.properties.get("package_id") for node in returned}
        reconciled = {node.properties.get("package_id") for node in selected if node.kind == "DepotReconciliation"
                      and node.properties.get("receipt_id") in {event.id for event in returned}
                      and world.nodes.get(node.properties.get("attempt_id"))
                      and world.nodes[node.properties["attempt_id"]].properties.get("disposition") == "FAILED"}
        accepted = bool(packages) and packages <= covered and packages <= reconciled
    if not accepted:
        raise OperationsConflict("Selected evidence does not independently verify this action-specific outcome")
    return {"resolved": True, "workflow_state": "RESOLVED"}
