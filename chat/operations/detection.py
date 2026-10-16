"""Why the monitor flagged a shipment, and whether that flag still stands: deterministic, from visible evidence only.

detection_summary() keeps what the rule engine (dataset_v2.derive.assess_shipment) already computed and the monitor
used to discard: each rule's reason and evidence ids, the milestone it compared (expected location, deadline, grace,
observed time), the identity or weight comparison that differed, and the last corroborated custody event. It is a
record of the detection, not a diagnosis: no cause, no recommendation, nothing from truth or from the future (the
assessment it reads was made on the evidence visible at the monitor's clock).

alert_state() compares the symptoms a case was opened or updated with to a fresh assessment. A cleared alert is not a
resolution: it never changes the workflow state, never closes the case and never counts as a verified outcome.
"""
import json

from dataset_v2.contracts import instant

DETECTION_VERSION = "monitor-detection-1"
MAX_EVIDENCE_IDS = 12
MAX_ROWS = 12
FACILITY_KINDS = ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse")
ALERT_ACTIVE, ALERT_PARTLY_CLEARED, ALERT_CLEARED = "ACTIVE", "PARTLY_CLEARED", "CLEARED"


def _location(world, location_id):
    node = world.nodes.get(location_id) if location_id else None
    if node is None:
        return {"id": location_id, "kind": None, "name": None}
    return {"id": location_id, "kind": node.kind if node.kind in FACILITY_KINDS else "Recipient" if node.kind in ("Customer", "Organization") else node.kind,
            "name": node.properties.get("name") or node.properties.get("display_name")}


def _deadline(world, row):
    milestone = world.nodes.get(row.get("milestone_id"))
    grace = (milestone.properties.get("grace_seconds") if milestone else None) or 0
    latest = row.get("latest_at")
    if not latest:
        return grace, None
    from datetime import timedelta
    return grace, (instant(latest) + timedelta(seconds=grace)).isoformat()


def detection_summary(assessment, world, symptom_of):
    """The monitor's evidence for its finding. symptom_of: rule code -> neutral symptom (operations.store.SYMPTOMS)."""
    rules = []
    for item in assessment.get("exceptions", []):
        rules.append({"code": item["code"], "symptom": symptom_of(item["code"]), "reasons": list(item.get("reasons") or [])[:4],
                      "evidence_ids": list(item.get("evidence_ids") or [])[:MAX_EVIDENCE_IDS],
                      "requires_human_review": bool(item.get("requires_human_review"))})
    milestones, comparisons = [], []
    for row in assessment.get("expected_vs_actual", []):
        if row.get("milestone_id") and (row.get("missing_due") or row.get("late")):
            grace, deadline = _deadline(world, row)
            milestones.append({"package_id": row.get("package_id"), "milestone_id": row["milestone_id"], "predicate": row.get("predicate"),
                               # The DELIVERED milestone's deadline is the journey plan's delivery promise in the V3 world.
                               "delivery_promise": row.get("predicate") == "DELIVERED",
                               "expected_location": _location(world, row.get("location_id")),
                               "earliest_at": row.get("earliest_at"), "latest_at": row.get("latest_at"), "grace_seconds": grace,
                               "deadline_at": deadline, "observed_at": row.get("actual_at"),
                               "state": "missing_after_deadline" if row.get("missing_due") else "observed_late"})
        elif row.get("predicate") in ("BARCODE", "WEIGHT_KG") and row.get("matches") is False:
            comparisons.append({k: row.get(k) for k in ("predicate", "package_id", "evidence_id", "expected", "actual", "tolerance_kg") if k in row})
    custody = []
    involved = {m["package_id"] for m in milestones} | {c["package_id"] for c in comparisons}
    for row in assessment.get("custody", []):
        if row.get("gap_event_ids") or row.get("conflicting") or row.get("package_id") in involved or not involved:
            holder = row.get("last_corroborated_holder_id")
            custody.append({"package_id": row.get("package_id"), "last_corroborated_event_id": row.get("last_corroborated_event_id"),
                            "last_corroborated_holder": _location(world, holder) if holder else None,
                            "unconfirmed_event_ids": list(row.get("gap_event_ids") or [])[:MAX_EVIDENCE_IDS],
                            "conflicting": bool(row.get("conflicting")),
                            # Vehicle GPS is never parcel position.
                            "parcel_location_from_gps": None})
    return {"version": DETECTION_VERSION, "as_of": assessment.get("as_of"), "source": "deterministic_monitor_rules",
            "rules": rules, "milestones": milestones[:MAX_ROWS], "comparisons": comparisons[:MAX_ROWS], "custody": custody[:MAX_ROWS],
            "model_calls": 0}


def merge_detection(previous_json, current):
    """A case keeps every rule it was ever detected with (later checks add, never erase), with the latest evidence."""
    try:
        previous = json.loads(previous_json) if previous_json else None
    except (TypeError, ValueError):
        previous = None
    if not previous:
        return {**current, "first_as_of": current.get("as_of")}
    rules = {r["code"]: r for r in previous.get("rules", [])}
    rules.update({r["code"]: r for r in current.get("rules", [])})
    def rows(key, ident):
        merged = {ident(r): r for r in previous.get(key, [])}
        merged.update({ident(r): r for r in current.get(key, [])})
        return list(merged.values())[:MAX_ROWS]
    return {**current, "first_as_of": previous.get("first_as_of") or previous.get("as_of"),
            "rules": sorted(rules.values(), key=lambda r: r["code"]),
            "milestones": rows("milestones", lambda r: r.get("milestone_id")),
            "comparisons": rows("comparisons", lambda r: (r.get("predicate"), r.get("evidence_id"))),
            "custody": current.get("custody") or previous.get("custody", [])}


def detection_text(detection, symptoms=None):
    """One plain sentence of the evidence behind the given symptoms (all when None), for the audit trail."""
    if not detection:
        return ""
    wanted = set(symptoms or [])
    parts = []
    for row in detection.get("milestones", [])[:3]:
        place = row["expected_location"]
        where = " at " + (place.get("kind") or "location") + " " + str(place.get("id")) if place and place.get("id") else ""
        what = "delivery promise" if row.get("delivery_promise") else str(row.get("predicate")).lower() + " milestone"
        if row["state"] == "missing_after_deadline":
            parts.append(f"{what}{where} due by {row.get('deadline_at')} (grace {row.get('grace_seconds')} s) not observed")
        else:
            parts.append(f"{what}{where} due by {row.get('deadline_at')} observed at {row.get('observed_at')}")
    for row in detection.get("comparisons", [])[:2]:
        parts.append(f"{row.get('predicate')} read {row.get('actual')} where the manifest says {row.get('expected')} ({row.get('evidence_id')})")
    for rule in detection.get("rules", []):
        if (not wanted or rule["symptom"] in wanted) and rule["code"] not in ("MISSED_MILESTONE", "JOURNEY_DELAY", "BARCODE_MISMATCH", "WEIGHT_MISMATCH"):
            parts.append(f"{rule['code']}: {rule['reasons'][0] if rule['reasons'] else 'rule matched'}")
    last = next((row for row in detection.get("custody", []) if row.get("last_corroborated_event_id")), None)
    if last:
        parts.append(f"last corroborated custody {last['last_corroborated_event_id']}")
    return ("Detected on evidence visible at " + str(detection.get("as_of")) + ": " + "; ".join(parts[:6]) + ".") if parts else ""


def alert_state(case_symptoms, fresh_symptoms):
    """(state, cleared symptoms). CLEARED: the fresh assessment finds nothing; PARTLY_CLEARED: some of the case's
    symptoms are no longer found; ACTIVE otherwise. Past-event symptoms (a misread, a late scan) stay in the record and
    so stay found: only conditions that later evidence actually removed can clear."""
    recorded, fresh = set(case_symptoms or []), set(fresh_symptoms or [])
    cleared = sorted(recorded - fresh)
    if not fresh:
        return ALERT_CLEARED, sorted(recorded)
    return (ALERT_PARTLY_CLEARED if cleared else ALERT_ACTIVE), cleared
