"""Deterministic fact checks applied AFTER the agent concludes (never given to it beforehand).

They test whether the agent's primary cause is consistent with what the evidence rules compute at
the same snapshot, whether the case is sensitive, and whether a contractor holds the parcel. A
failed check does not overrule the model's text; it removes automatic authority, so a person
decides. The independent reviewer sees these checks next to the cited records.
"""
from datetime import timedelta

from dataset_v2.contracts import instant
from dataset_v2.derive import assess_shipment, custody_corroborated

# Rule families (computed by the evidence rules at the same snapshot) consistent with each cause.
CONSISTENT = {
    "DELAYED_SYNC": {"MISSED_MILESTONE", "CUSTODY_GAP", "JOURNEY_DELAY"},
    "HUB_DELAY": {"MISSED_MILESTONE", "JOURNEY_DELAY"},
    "ROUTE_DELAY": {"TRAFFIC_DELAY", "MISSED_MILESTONE", "JOURNEY_DELAY"},
    "JOURNEY_DELAY": {"JOURNEY_DELAY", "MISSED_MILESTONE"},
    "SLA_RISK": {"MISSED_MILESTONE", "JOURNEY_DELAY", "TRAFFIC_DELAY"},
    "POSSIBLE_MISDELIVERY": {"DELIVERY_DISPUTE"},
    "UNRECONCILED_CUSTODY": {"UNRECONCILED_CUSTODY", "CUSTODY_GAP"},
    "CUSTODY_GAP": {"CUSTODY_GAP", "UNRECONCILED_CUSTODY", "MISSED_MILESTONE"},
}
EXEMPT = {"UNKNOWN", "INSUFFICIENT_EVIDENCE"}
LATE_UPLOAD_MINUTES = 60


def _late_or_silent(inv, tools):
    """Evidence of delayed synchronization among the agent's cited records."""
    cited = {i for h in inv.get("hypotheses") or [] for i in h.get("supporting_evidence_ids", [])}
    for key in cited:
        node = tools.nodes.get(key)
        if node and node.properties.get("recorded_at") and node.properties.get("occurred_at"):
            lag = instant(node.properties["recorded_at"]) - instant(node.properties["occurred_at"])
            if lag >= timedelta(minutes=LATE_UPLOAD_MINUTES):
                return True, key
        beat = tools.external.get(key)
        if beat and (beat.get("pending_uploads") or 0) > 0:
            return True, key
    for device in tools.device_reports.values():
        if device.get("reporting_state") == "SILENT" or (device.get("largest_gap_hours") or 0) >= 4:
            return True, device["device_id"]
    return False, None


def fact_checks(inv, tools):
    assessment = assess_shipment(tools.world, tools.sid, tools.as_of)
    rule_codes = set(assessment["supported_codes"])
    primary = inv.get("primary_cause")
    checks = []
    unsupported = False
    if primary and primary not in EXEMPT:
        family = CONSISTENT.get(primary, {primary})
        consistent = bool(family & rule_codes)
        detail = "evidence rules at this snapshot show " + (", ".join(sorted(rule_codes)) or "no exception")
        if primary == "DELAYED_SYNC":
            late, ref = _late_or_silent(inv, tools)
            consistent = consistent and late
            detail += "; delayed upload or device silence " + ("found (" + ref + ")" if late else "not found among cited evidence")
        checks.append({"check": "cause_consistent_with_evidence_rules", "passed": consistent, "detail": detail})
        unsupported = not consistent
    reports = [n for n in tools.nodes.values() if n.kind == "RecipientReport" and n.properties.get("report_code") == "NOT_RECEIVED"]
    sensitive = bool(reports) or "CONFLICTING_CUSTODY" in rule_codes or "DELIVERY_DISPUTE" in rule_codes
    checks.append({"check": "sensitive_dispute_or_conflict", "passed": not sensitive,
                   "detail": "recipient non-receipt report or conflicting custody present" if sensitive else "none"})
    contractor = []
    for row in assessment["custody"]:
        holder = tools.nodes.get(row["last_corroborated_holder_id"])
        if holder is not None and holder.kind == "Vehicle" and holder.properties.get("ownership") in ("PRIVATE", "PROVIDER"):
            contractor.append(row["package_id"])
    checks.append({"check": "parcel_held_by_contractor", "passed": not contractor,
                   "detail": ("last corroborated holder is a contractor or independent vehicle for " + ", ".join(contractor)) if contractor else "no"})
    return {"checks": checks, "rule_codes": sorted(rule_codes), "unsupported": unsupported, "sensitive": sensitive,
            "contractor_custody": bool(contractor)}


def cited_records(inv, tools, limit=40):
    """The actual records behind the agent's citations, as the reviewer should read them."""
    skip = {"dataset_id", "schema_version", "synthetic", "provenance", "split", "holdout_group", "source_ref", "raw_payload_hash", "feed_id"}
    cited = []
    for h in inv.get("hypotheses") or []:
        for key in h.get("supporting_evidence_ids", []) + h.get("contradicting_evidence_ids", []):
            if key not in cited:
                cited.append(key)
    records = {}
    for key in cited[:limit]:
        node = tools.nodes.get(key)
        if key in tools.external:  # Telemetry summaries (a cited device) win over the bare catalog record.
            records[key] = {"kind": "DeviceHeartbeat", **tools.external[key]}
        elif node is not None:
            records[key] = {"kind": node.kind, **{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                                                  for k, v in node.properties.items() if k not in skip}}
    return records
