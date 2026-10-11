"""Whether evidence that became visible after an investigation's snapshot is material to its conclusion.

Deterministic, from visible evidence only (no model, no truth). A finished or running investigation is superseded
only by a material change; routine new records for the shipment (the next scan, a GPS fix, a status event) are not one.

A newly visible record is material when it

  cited_record_superseded   names a record the conclusion cites as the one it supersedes (supersedes_id);
  cited_record_new_version  is a new version (it carries `version`) of a kind of record the conclusion cites;
  late_upload               is an observation that happened more than the normal upload allowance before the
                            snapshot and was not visible at it: the conclusion was reached without an observation
                            from the period it examined (the late upload of an observation it calls missing);

and the new records together are material when they

  finding_added             add a monitor finding that the same evidence without them does not show at the same clock;
  finding_cleared           clear a monitor finding the investigation saw at its snapshot and that would still stand
                            without them.

Findings are compared at one clock, with and without the new records, so a deadline that merely passed is not counted
here (the monitor records that as a new symptom on the case, which is itself a material change).
"""
from datetime import timedelta

from dataset_v2.context import OBSERVATIONS
from dataset_v2.contracts import instant
from operations.identifiers import storage_value

SNAPSHOT_SUPERSEDED_KIND = "snapshot_superseded"


def cited_evidence_ids(analysis):
    """Every evidence id the run's conclusion, diagnoses and proposal cite (any `...evidence_ids` list)."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("evidence_ids") and isinstance(item, (list, tuple)):
                    found.update(storage_value(x) for x in item if isinstance(x, str))
                else:
                    walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    analysis = analysis or {}
    walk({key: analysis.get(key) for key in ("investigation", "proposal")})
    walk((analysis.get("result") or {}).get("diagnoses"))
    return found


def _moment(value):
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    try:
        return instant(value) if isinstance(value, str) else None
    except (ValueError, TypeError, OverflowError):
        return None


def new_records(before, after):
    """The evidence rows visible in `after` and not in `before` (both are read-model evidence contexts)."""
    known = {row["id"] for row in before["nodes"]}
    return sorted((row for row in after["nodes"] if row["id"] not in known), key=lambda row: row["id"])


def finding_codes(context, config, at, allowance):
    from dataset_v2.derive import assess_shipment
    from operations.reasoning import evidence_world
    assessment = assess_shipment(evidence_world(context, config), context["shipment_id"], at, detection_allowance_seconds=allowance)
    return {item["code"] for item in assessment.get("exceptions", [])}


def material_evidence(before, after, *, snapshot_at, cited, config, allowance):
    """The material changes among the records visible in `after` and not in `before`; [] when there are none.

    before, after   evidence contexts of one shipment (before: what was already considered; after: visible now)
    snapshot_at     the snapshot of the investigation whose conclusion is being checked
    cited           the evidence ids that conclusion cites (cited_evidence_ids)
    allowance       normal upload lag in seconds (the monitor's detection allowance)
    """
    new = new_records(before, after)
    if not new:
        return []
    cited = {storage_value(x) for x in cited}
    kinds = {row["id"]: row["kind"] for row in before["nodes"]}
    cited_kinds = {kinds[key] for key in cited if key in kinds}
    late_before = instant(snapshot_at) - timedelta(seconds=allowance)
    reasons = []
    for row in new:
        props = row["properties"]
        replaced = storage_value(props.get("supersedes_id"))
        if replaced and replaced in cited:
            reasons.append({"reason": "cited_record_superseded", "entity_id": row["id"], "kind": row["kind"], "supersedes_id": replaced})
        elif props.get("version") is not None and row["kind"] in cited_kinds:
            reasons.append({"reason": "cited_record_new_version", "entity_id": row["id"], "kind": row["kind"]})
        elif row["kind"] in OBSERVATIONS:
            at = _moment(props.get("occurred_at", props.get("start_at")))
            if at is not None and at <= late_before:
                reasons.append({"reason": "late_upload", "entity_id": row["id"], "kind": row["kind"], "occurred_at": at.isoformat()})
    seen = finding_codes(before, config, before["as_of"], allowance)
    without = finding_codes(before, config, after["as_of"], allowance)
    now = finding_codes(after, config, after["as_of"], allowance)
    if now - without:
        reasons.append({"reason": "finding_added", "codes": sorted(now - without)})
    if (seen & without) - now:
        reasons.append({"reason": "finding_cleared", "codes": sorted((seen & without) - now)})
    return reasons


def describe(reasons):
    """One line for the audit trail."""
    parts = []
    for item in reasons:
        detail = (", ".join(item.get("codes") or []) or ", ".join([*(item.get("added") or []), *(item.get("cleared") or [])])
                  or item.get("entity_id") or "")
        parts.append(item["reason"] + (f" ({detail})" if detail else ""))
    return "; ".join(parts)
