"""Registered local operations ledger vocabulary; immutable imports remain a separate graph."""
from dataset_v2.contracts import instant
from datetime import datetime


def public_value(value):
    if hasattr(value, "to_native"):
        value = value.to_native()
    if isinstance(value, datetime):
        return instant(value.isoformat()).isoformat()
    if isinstance(value, dict):
        return {key: public_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [public_value(item) for item in value]
    return value

COMMON = frozenset(("entity_id", "dataset_id", "synthetic", "split", "shipment_id", "holdout_group",
                    "recorded_at", "occurred_at", "provenance"))
FIELDS = {
    "OpsControl": {"as_of", "initial_as_of", "end_at", "speed", "replay_mode", "simulator_state", "worker_state", "state_version",
                   "cursor_time", "cursor_id", "worker_claim", "claim_at", "processed_count", "event_count",
                   "claim_shipment_id", "last_case_id", "last_shipment_id", "last_workflow_state", "last_processed_at",
                   "case_source", "session_id", "session_started_at", "monitor_queue", "monitor_checked", "monitor_opened"},
    "OpsCase": {"opened_by", "session_id", "source_case_id", "workflow_state", "operational_status", "priority", "cause_codes", "symptom_codes", "city", "opened_at",
                "as_of", "state_version", "last_run_id", "recommendation_id", "issue_summary", "claim_id", "claim_at",
                "is_terminal", "closed_at", "verified_outcome_id", "outcome_checked_as_of", "snapshot_refreshes"},
    "OpsAudit": {"case_id", "event_type", "actor_id", "decision", "result", "from_state", "to_state", "run_id",
                 "stage", "stage_status", "sequence", "wall_recorded_at"},
    "OpsEventReceipt": {"source_event_id", "event_kind", "source_occurred_at", "case_id"},
    "OpsRun": {"case_id", "mode", "result_json", "iteration", "status", "context_hash"},
    "OpsRecommendation": {"case_id", "run_id", "action_code", "action", "action_en", "action_ar", "evidence_ids", "status", "requires_approval",
                          "action_type", "risk_class", "authority_reason", "agent_mode", "target_json"},
    "OpsReview": {"case_id", "run_id", "verdict", "feedback", "summary_en", "summary_ar", "iteration", "mode", "model_verdict", "degraded"},
    "OpsDecision": {"case_id", "recommendation_id", "decision", "actor_id", "expected_version", "idempotency_key"},
    "OpsExecution": {"case_id", "decision_id", "action_code", "receipt_ref", "status", "mode",
                     "action_type", "authority", "expected_result", "deadline_at", "idempotency_key", "target_device",
                     "expected_evidence_json", "adapter_result_json", "executed_at", "closure", "case_opened_at",
                     "decided_risk", "permission_rule"},
    "OpsOutcome": {"case_id", "execution_id", "action_code", "action_type", "success", "outcome_type", "evidence_ids",
                   "verification_status", "verified_at", "verifier_id", "invalidated", "observed_at", "reason", "rule_id", "expected_effect",
                   "exception_cleared", "remaining_symptoms"},
    "OpsNotification": {"case_id", "trigger", "status", "mode", "external_calls"},
    "OpsCommand": {"case_id", "idempotency_key", "request_hash", "result_json", "command_type"},
    "OpsRiskFlag": {"active", "certainty", "promise_at", "latest_estimate_at", "earliest_estimate_at", "evidence_ids", "checked_at"},
}
RELATIONSHIPS = frozenset(("OPS_ABOUT", "OPS_HAS_RUN", "OPS_PROPOSES", "OPS_REVIEWED_BY", "OPS_HAS_DECISION",
                         "OPS_INITIATES", "OPS_HAS_OUTCOME", "OPS_HAS_AUDIT", "OPS_HAS_RECEIPT", "OPS_CITES", "OPS_NOTIFIED"))
SCHEMA = {
    "ops_entity_id": ("CONSTRAINT", "OpsEntity", "entity_id"),
    "ops_case_state": ("INDEX", "OpsCase", "workflow_state"),
    "ops_case_order": ("INDEX", "OpsCase", "opened_at"),
    "ops_audit_order": ("INDEX", "OpsAudit", "occurred_at"),
    "ops_owner": ("INDEX", "OpsEntity", "shipment_id"),
}


def validate_node(labels, props, world):
    kinds = set(labels) - {"OpsEntity"}
    if "OpsEntity" not in labels or len(kinds) != 1 or not kinds <= FIELDS.keys():
        raise ValueError("Unregistered operations labels")
    kind = next(iter(kinds))
    if (set(props) - COMMON - FIELDS[kind] or not str(props.get("entity_id", "")).startswith("DEMO-OPS-")
            or props.get("synthetic") is not True or props.get("dataset_id") != world.config.dataset_id
            or props.get("split") != "development"):
        raise ValueError("Operations envelope/fields differ")
    owner = props.get("shipment_id")
    if kind == "OpsControl":
        if owner is not None or props.get("holdout_group") is not None:
            raise ValueError("Control cannot impersonate a shipment")
    else:
        shipment = world.nodes.get(owner)
        if (shipment is None or shipment.kind != "Shipment" or shipment.properties.get("split") != "development"
                or props.get("holdout_group") != owner):
            raise ValueError("Operations ownership must bind a development shipment")
    for key in ("recorded_at", "occurred_at", "as_of", "initial_as_of", "end_at", "opened_at", "verified_at",
                "observed_at", "source_occurred_at", "cursor_time", "claim_at"):
        if props.get(key) is not None:
            if not isinstance(props[key], datetime) and not hasattr(props[key], "to_native"):
                raise ValueError("Operations timestamps require temporal properties")
            instant(public_value(props[key]))
    return kind


def validate_edge(kind, props, start, end, ops, world):
    if (kind not in RELATIONSHIPS or set(props) - COMMON - {"edge_id"}
            or not str(props.get("edge_id", "")).startswith("DEMO-OPS-")):
        raise ValueError("Unregistered operations relationship")
    if props.get("dataset_id") != world.config.dataset_id or props.get("synthetic") is not True or props.get("split") != "development":
        raise ValueError("Operations relationship envelope differs")
    source = ops.get(start)
    if source is None:
        raise ValueError("Operations relationship requires an operations source")
    owner = source.get("shipment_id")
    if props.get("shipment_id") != owner or props.get("holdout_group") != owner:
        raise ValueError("Operations relationship owner differs")
    if end in ops:
        if ops[end].get("shipment_id") != owner:
            raise ValueError("Operations relationship crosses shipments")
    elif kind in {"OPS_ABOUT", "OPS_CITES", "OPS_HAS_RECEIPT"}:
        target = world.nodes.get(end)
        if target is None or target.properties.get("holdout_group") != owner or target.properties.get("split") != "development":
            raise ValueError("Operations source references foreign immutable evidence")
    else:
        raise ValueError("Operations relationship target is unregistered")
