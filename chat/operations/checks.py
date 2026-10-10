"""Deterministic checks applied AFTER the agent concludes (never given to it beforehand).

Fact checks test whether the agent's primary cause is consistent with what the evidence rules and the device
telemetry show at the same snapshot, whether the case is sensitive, and whether a contractor holds the parcel.
Citation validity tests, in code, that every cited id resolves to a record, was listed as citable by one of this
investigation's tool calls and was recorded at or before the snapshot. A failed check does not overrule or change
the model's diagnosis; it removes automatic authority, so a person decides. The independent reviewer sees these
checks next to the cited records.
"""
from datetime import timedelta

from dataset_v2.contracts import instant
from dataset_v2.derive import assess_shipment
from operations.tools import LATE_UPLOAD_SECONDS

# Rule families (computed by the evidence rules at the same snapshot) consistent with each cause.
CONSISTENT = {
    "DELAYED_SYNC": {"MISSED_MILESTONE", "CUSTODY_GAP", "JOURNEY_DELAY"},
    "HUB_DELAY": {"MISSED_MILESTONE", "JOURNEY_DELAY"},
    "ROUTE_DELAY": {"TRAFFIC_DELAY", "MISSED_MILESTONE", "JOURNEY_DELAY"},
    "JOURNEY_DELAY": {"JOURNEY_DELAY", "MISSED_MILESTONE"},
    "SLA_RISK": {"MISSED_MILESTONE", "JOURNEY_DELAY", "TRAFFIC_DELAY"},
    "POSSIBLE_MISDELIVERY": {"DELIVERY_DISPUTE"},
    "UNRECONCILED_CUSTODY": {"UNRECONCILED_CUSTODY", "CUSTODY_GAP"},
    # A custody gap needs the rule that reads the chain itself: an uncorroborated transfer, or one that does not follow
    # the last corroborated holder. A missing next step alone (an overdue milestone) is not a gap in the chain.
    "CUSTODY_GAP": {"CUSTODY_GAP"},
}
EXEMPT = {"UNKNOWN", "INSUFFICIENT_EVIDENCE"}
LATE_UPLOAD_MINUTES = LATE_UPLOAD_SECONDS // 60
DEVICE_RECORD_KINDS = ("ScanEvent", "CustodyEvent", "DeliveryAttempt", "DeliveryProof", "DepotReconciliation")
ENVELOPE = frozenset(("dataset_id", "schema_version", "synthetic", "provenance", "split", "holdout_group", "source_ref", "raw_payload_hash",
                      "feed_id", "feed_origin", "ingested_at", "ingest_lag_seconds"))


def _cited(inv):
    out = []
    for h in inv.get("hypotheses") or []:
        for key in [*(h.get("supporting_evidence_ids") or []), *(h.get("contradicting_evidence_ids") or [])]:
            if isinstance(key, str) and key not in out:
                out.append(key)
    return out


def delayed_sync_evidence(tools):
    """Whether a device the shipment's records depend on was silent or buffering at the time: a record of this shipment
    that reached Suhail late, or an expected device (for an observation that is missing or late) that stopped reporting
    at hours when it normally reports, had a heartbeat gap over the expected time, or reported pending uploads.
    Computed from the snapshot by code, whatever the investigator cited. Returns (found, description)."""
    for node in tools.nodes.values():
        p = node.properties
        if node.kind in DEVICE_RECORD_KINDS and p.get("holdout_group") == tools.sid and p.get("recorded_at") and p.get("occurred_at"):
            lag = instant(str(p["recorded_at"])) - instant(str(p["occurred_at"]))
            if lag >= timedelta(seconds=LATE_UPLOAD_SECONDS):
                return True, f"record {node.id} reached Suhail {round(lag.total_seconds() / 60)} minutes after it occurred"
    for row in tools._journey()["milestones"]:
        if row["state"] not in ("missing_after_deadline", "observed_late"):
            continue
        briefs = row.get("expected_device_telemetry")
        for brief in briefs if isinstance(briefs, list) else []:
            if brief.get("reporting_state") == "SILENT":
                return True, f"expected device {brief['device_id']} is silent (last seen {brief.get('last_seen_at')})"
            if brief.get("heartbeat_gap_over_expected_time"):
                return True, f"expected device {brief['device_id']} has a heartbeat gap over the expected time"
            if (brief.get("max_pending_uploads") or 0) > 0:
                return True, f"expected device {brief['device_id']} reported pending uploads"
    return False, "no late record of this shipment, and no expected device silent or buffering at the time"


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
            found, what = delayed_sync_evidence(tools)
            consistent = consistent and found
            detail += "; " + what
        if primary == "CUSTODY_GAP":
            gaps = sorted({key for row in assessment["custody"] for key in row["gap_event_ids"]})
            detail += "; " + ("uncorroborated or discontinuous transfer: " + ", ".join(gaps[:4]) if gaps else
                              "no uncorroborated or discontinuous transfer in the custody chain")
        checks.append({"check": "cause_consistent_with_evidence_rules", "passed": consistent, "detail": detail})
        unsupported = not consistent
    citations = citation_validity(inv, tools)
    if citations["cited"]:
        checks.append({"check": "citations_valid", "passed": citations["all_valid"],
                       "detail": "every cited id resolves, was retrieved in this investigation and was recorded by the snapshot"
                                 if citations["all_valid"] else "invalid citations: " + ", ".join(citations["invalid_ids"][:6])})
        unsupported = unsupported or not citations["all_valid"]
    reports = [n for n in tools.nodes.values() if n.kind == "RecipientReport" and n.properties.get("report_code") == "NOT_RECEIVED"]
    sensitive = bool(reports) or "CONFLICTING_CUSTODY" in rule_codes or "DELIVERY_DISPUTE" in rule_codes
    checks.append({"check": "sensitive_dispute_or_conflict", "passed": not sensitive,
                   "detail": "recipient non-receipt report or conflicting custody present" if sensitive else "none"})
    contractor = []
    for row in assessment["custody"]:
        holder = tools.nodes.get(row["last_corroborated_holder_id"])
        if holder is not None and holder.kind == "Vehicle" and holder.properties.get("ownership") in ("PRIVATE", "PROVIDER", "CONTRACTOR"):
            contractor.append(row["package_id"])
    checks.append({"check": "parcel_held_by_contractor", "passed": not contractor,
                   "detail": ("last corroborated holder is a contractor or independent vehicle for " + ", ".join(contractor)) if contractor else "no"})
    alternatives = alternative_tested(inv)
    checks.append({"check": "alternative_explanation_recorded", "passed": alternatives,
                   "detail": "a hypothesis other than the primary cause cites evidence" if alternatives else
                             "no hypothesis other than the primary cause cites evidence (informational; the reviewer judges it)"})
    return {"checks": checks, "rule_codes": sorted(rule_codes), "unsupported": unsupported, "sensitive": sensitive,
            "contractor_custody": bool(contractor), "citations": citations, "alternative_recorded": alternatives}


def alternative_tested(inv):
    """Whether the conclusion records an alternative to its primary cause with evidence for or against it."""
    primary = inv.get("primary_cause")
    return any(h.get("cause") != primary and (h.get("supporting_evidence_ids") or h.get("contradicting_evidence_ids"))
               for h in inv.get("hypotheses") or [])


def citation_validity(inv, tools):
    """Deterministic, per cited id: it resolves to a record this investigation holds, a tool call of this investigation
    listed it as citable, and it was recorded (and had occurred) at or before the snapshot."""
    rows = []
    for key in _cited(inv):
        meta = tools.index.get(key) or {}
        resolves = key in tools.nodes or key in tools.external
        retrieved = key in tools.retrieved
        in_time = resolves
        for field in ("recorded_at", "occurred_at"):
            value = meta.get(field)
            if value:
                try:
                    in_time = in_time and instant(str(value)) <= tools.cutoff
                except ValueError:
                    in_time = False
        if meta.get("kind") == "ComputedResult":
            in_time = in_time and (tools.computed.get(key) or {}).get("computed_as_of") == tools.as_of
        rows.append({"id": key, "kind": meta.get("kind"), "scope": meta.get("scope"), "resolves": resolves,
                     "retrieved_in_this_investigation": retrieved, "recorded_at_or_before_snapshot": bool(in_time),
                     "valid": bool(resolves and retrieved and in_time)})
    invalid = [r["id"] for r in rows if not r["valid"]]
    return {"snapshot_as_of": tools.as_of, "cited": len(rows), "valid": len(rows) - len(invalid), "invalid_ids": invalid,
            "all_valid": not invalid, "citations": rows}


def _record(key, tools):
    if key in tools.external:  # Telemetry summaries, computed results and other shipments' records as the tools showed them.
        record = tools.external[key]
        return {"kind": record.get("kind") or "DeviceHeartbeat", **{k: v for k, v in record.items() if k != "kind"}}
    node = tools.nodes.get(key)
    if node is not None:
        return {"kind": node.kind, **{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                                      for k, v in node.properties.items() if k not in ENVELOPE}}
    return None


def cited_records(inv, tools, limit=40):
    """The actual records behind the agent's citations, as the reviewer should read them."""
    records = {}
    for key in _cited(inv)[:limit]:
        record = _record(key, tools)
        if record is not None:
            records[key] = record
    return records


def review_context(inv, tools, citations, *, round_number=0, previous_reviews=(), computed_limit=40, uncited_limit=160):
    """What the reviewer receives besides the cited records: citation validity, the tool-computed results the investigator
    saw, the ids and kinds of what it retrieved but did not cite, the queries it made and, in a revision round, the
    reviewer's own earlier feedback and unsupported claims."""
    cited = set(_cited(inv))
    seen = [key for key in tools.computed if key in tools.retrieved]
    seen.sort(key=lambda key: key not in cited)
    computed = {key: {k: v for k, v in tools.computed[key].items() if k not in ("kind", "scope")} for key in seen[:computed_limit]}
    uncited = {}
    for key in sorted(tools.retrieved - cited):
        if key in tools.computed:
            continue
        kind = (tools.index.get(key) or {}).get("kind") or "record"
        uncited.setdefault(kind, []).append(key)
    shown, budget = {}, uncited_limit
    for kind in sorted(uncited):
        take = uncited[kind][:max(budget, 0)]
        shown[kind] = {"count": len(uncited[kind]), "ids": take}
        budget -= len(take)
    return {"review_round": round_number,
            "citation_validity": {k: citations[k] for k in ("snapshot_as_of", "cited", "valid", "invalid_ids", "all_valid")},
            "computed_results_seen": computed,
            "computed_results_not_shown": max(len(seen) - computed_limit, 0),
            "retrieved_but_uncited": shown,
            "tool_calls": [{"round": c["round"], "tool": c["tool"], "args": c["args"]} for c in tools.calls],
            **({"previous_reviews": [{"round": r.get("round"), "verdict": r.get("verdict"), "feedback": r.get("feedback"),
                                      "unsupported_claims": r.get("unsupported_claims") or [],
                                      "unaddressed_contradictions": r.get("unaddressed_contradictions") or []} for r in previous_reviews]}
               if previous_reviews else {})}
