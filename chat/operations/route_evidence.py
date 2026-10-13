"""Bounded vehicle telemetry connected to a shipment's visible transport records.

This projection contains observations and plans only. It never locates a parcel or
certifies delivery. ``fetch`` accepts names from the fixed cross-shipment catalogue.
"""
from __future__ import annotations

import math
from datetime import timedelta

from dataset_v2.contracts import instant


BOUND_KINDS = {"VehicleAssignment", "CustodyEvent", "DeliveryAttempt", "Manifest"}
PLAN_KINDS = {"RouteRun", "Trip", "RouteSegment", "ExpectedMilestone", "RouteMilestone"}
POINT_KEYS = ("entity_id", "vehicle_id", "route_run_id", "trip_id", "lat", "lng", "accuracy_m",
              "speed_kmh", "occurred_at", "recorded_at", "ingested_at", "source_ref", "source_event_id")


def _at(value):
    try:
        return instant(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _visible(row, cutoff):
    p = row["properties"]
    recorded, occurred = _at(p.get("recorded_at")), _at(p.get("occurred_at"))
    return recorded is not None and recorded <= cutoff and (occurred is None or occurred <= cutoff)


def _coordinate(value, lower, upper):
    return type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper


def _nonnegative(value):
    return value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0)


def _source(row):
    return {"id": row["id"], "kind": row["kind"], "properties": dict(row["properties"])}


def build_route_evidence(context, fetch, *, max_points=160, max_runs=4):
    """Project only GPS from a visible assignment for this shipment and its valid interval.

    A route or trip named only in shared plan data cannot authorize access. A bound
    assignment supplies the vehicle and interval. Other owned records may corroborate
    that binding but do not expand it. Query results are rechecked after retrieval.
    """
    if not 1 <= max_points <= 160 or not 1 <= max_runs <= 4:
        raise ValueError("Route evidence bounds exceed frozen contract")
    sid, as_of = context["shipment_id"], context["as_of"]
    cutoff = instant(as_of)
    nodes = {r["id"]: r for r in context.get("nodes", []) if _visible(r, cutoff)}
    dataset_id = nodes[sid]["properties"]["dataset_id"] if sid in nodes else None
    owned = [r for r in nodes.values() if r["kind"] in BOUND_KINDS
             and r["properties"].get("shipment_id") == sid]
    assignments = sorted((r for r in owned if r["kind"] == "VehicleAssignment"), key=lambda r: r["id"])
    candidates = []
    for assignment in assignments:
        p = assignment["properties"]
        vehicle = p.get("vehicle_id")
        start, end = _at(p.get("valid_from")), _at(p.get("valid_to"))
        if not vehicle or not start or not end or end < start:
            continue
        for field, plan_kind in (("route_run_id", "RouteRun"), ("trip_id", "Trip")):
            ref = p.get(field)
            plan = nodes.get(ref)
            if not ref or not plan or plan["kind"] != plan_kind or plan["properties"].get("vehicle_id") != vehicle:
                continue
            # A route run/trip must have been visible when the assignment was visible.
            supporting = [r for r in owned if r["properties"].get(field) == ref]
            plan_ids = [r["id"] for r in supporting if r["kind"] in {"VehicleAssignment", "Manifest"}]
            custody_ids = [r["id"] for r in supporting if r["kind"] == "CustodyEvent"]
            candidates.append({"route_run_id": ref if field == "route_run_id" else None,
                               "trip_id": ref if field == "trip_id" else None,
                               "assignment_id": assignment["id"], "vehicle_id": vehicle,
                               "device_id": plan["properties"].get("device_ref"),
                               "valid_from": p["valid_from"], "valid_to": p["valid_to"],
                               "plan_source_ids": sorted(set([plan["id"], *plan_ids])),
                               "custody_source_ids": sorted(set(custody_ids))})
    candidates.sort(key=lambda c: (c["vehicle_id"], c["route_run_id"] or c["trip_id"], c["assignment_id"]))
    # One assignment can be duplicated in the evidence context; keep its first binding.
    unique = list({(c["assignment_id"], c["route_run_id"], c["trip_id"]): c for c in candidates}.values())
    contexts = unique[:max_runs]
    observations, source_rows = [], {}
    more = False
    for bound in contexts:
        ref = bound["route_run_id"] or bound["trip_id"]
        query = "route_run_positions" if bound["route_run_id"] else "trip_evidence_positions"
        from_at = _at(bound["valid_from"])
        to_at = min(_at(bound["valid_to"]), cutoff)
        if from_at > to_at:
            continue
        parameters = {"ref": ref, "vehicle_id": bound["vehicle_id"],
                      "from_at": from_at.isoformat(), "to_at": to_at.isoformat()}
        rows = fetch(query, **parameters, limit=max_points + 1)
        if len(rows) > max_points:
            more = True
            rows = [*rows, *fetch(query + "_tail", **parameters, limit=1)]
            events = sorted((r for r in owned if r["kind"] in {"CustodyEvent", "DeliveryAttempt"}
                             and r["properties"].get("route_run_id") == bound["route_run_id"]
                             and r["properties"].get("trip_id") == bound["trip_id"]
                             and _at(r["properties"].get("occurred_at"))),
                            key=lambda r: (r["properties"]["occurred_at"], r["id"]))
            if len(events) > 8:
                events = [events[round(i * (len(events) - 1) / 7)] for i in range(8)]
            for event in events:
                when = _at(event["properties"]["occurred_at"])
                low = max(_at(bound["valid_from"]), when - timedelta(minutes=30))
                high = min(_at(bound["valid_to"]), cutoff, when + timedelta(minutes=30))
                if low <= high:
                    rows.extend(fetch(query + "_window", ref=ref, vehicle_id=bound["vehicle_id"], from_at=low.isoformat(),
                                      to_at=high.isoformat(), limit=16))
        for row in rows:
            p = row.get("props", {})
            at, received = _at(p.get("occurred_at")), _at(p.get("recorded_at"))
            if (p.get("dataset_id") != dataset_id or p.get("split") not in ("development", "history", "shared")
                    or p.get("position_scope") != "VEHICLE_ONLY"
                    or p.get("vehicle_id") != bound["vehicle_id"] or p.get("route_run_id") != bound["route_run_id"]
                    or p.get("trip_id") != bound["trip_id"] or not at or not received
                    or at < _at(bound["valid_from"]) or at > _at(bound["valid_to"])
                    or at > cutoff or received > cutoff or received < at
                    or not _coordinate(p.get("lat"), -90, 90) or not _coordinate(p.get("lng"), -180, 180)
                    or not _nonnegative(p.get("accuracy_m")) or not _nonnegative(p.get("speed_kmh"))
                    or not p.get("entity_id") or not p.get("source_ref")):
                continue
            ingested = _at(p.get("ingested_at"))
            if p.get("ingested_at") is not None and (not ingested or ingested < received):
                continue
            point = {key: p.get(key) for key in POINT_KEYS}
            point.update(evidence_id=p["entity_id"], position_scope="VEHICLE_ONLY", classification="observed_vehicle")
            if p["entity_id"] in source_rows:
                continue
            observations.append(point)
            source_rows[p["entity_id"]] = {"id": p["entity_id"], "kind": "GPSObservation",
                                            "properties": {key: p.get(key) for key in POINT_KEYS if p.get(key) is not None}
                                            | {"position_scope": "VEHICLE_ONLY"}}
    observations.sort(key=lambda p: (p["vehicle_id"], p["route_run_id"] or p["trip_id"], p["occurred_at"], p["evidence_id"]))
    # Preserve first/last within each context and observations nearest actual
    # shipment transition records before spreading the remaining budget.
    if len(observations) > max_points:
        more = True
        groups = {}
        for i, point in enumerate(observations):
            groups.setdefault((point["vehicle_id"], point["route_run_id"], point["trip_id"]), []).append(i)
        endpoints, transitions = set(), set()
        for group, indices in groups.items():
            endpoints.update((indices[0], indices[-1]))
            for record in owned:
                p = record["properties"]
                when = _at(p.get("occurred_at"))
                if (when and p.get("vehicle_id") == group[0]
                        and p.get("route_run_id") == group[1] and p.get("trip_id") == group[2]
                        and record["kind"] in {"CustodyEvent", "DeliveryAttempt"}):
                    transitions.add(min(indices, key=lambda i: (abs((_at(observations[i]["occurred_at"]) - when).total_seconds()), i)))
        selected = sorted(endpoints)[:max_points]
        selected.extend(i for i in sorted(transitions - endpoints)[:max_points - len(selected)])
        if len(selected) < max_points:
            for j in range(max_points):
                selected.append(round(j * (len(observations) - 1) / max(1, max_points - 1)))
                selected = sorted(set(selected))
                if len(selected) >= max_points:
                    break
        if len(selected) < max_points:
            selected.extend(i for i in range(len(observations)) if i not in selected)
        observations = [observations[i] for i in sorted(set(selected[:max_points]))]
    source_ids = {p["evidence_id"] for p in observations}
    for bound in contexts:
        source_ids.update([bound["assignment_id"], *bound["plan_source_ids"], *bound["custody_source_ids"]])
    source_nodes = [_source(nodes[key]) if key in nodes else source_rows[key] for key in sorted(source_ids) if key in nodes or key in source_rows]
    source_relationships = [dict(r) for r in context.get("edges", []) if r.get("start") in source_ids
                            and r.get("end") in source_ids and _visible(r, cutoff)]
    source_relationships.sort(key=lambda r: r["id"])
    intervals = []
    for a, b in zip(observations, observations[1:]):
        if (a["vehicle_id"], a["route_run_id"], a["trip_id"]) != (b["vehicle_id"], b["route_run_id"], b["trip_id"]):
            continue
        gap = (_at(b["occurred_at"]) - _at(a["occurred_at"])).total_seconds()
        if (a["speed_kmh"] is not None and b["speed_kmh"] is not None
                and a["speed_kmh"] < 3 and b["speed_kmh"] < 3 and 0 < gap <= 300):
            intervals.append({"vehicle_id": a["vehicle_id"], "route_run_id": a["route_run_id"],
                              "trip_id": a["trip_id"], "first_observed_at": a["occurred_at"],
                              "last_observed_at": b["occurred_at"], "threshold_kmh": 3,
                              "gap_limit_seconds": 300, "input_evidence_ids": [a["evidence_id"], b["evidence_id"]]})
    # ``observations`` stays grouped by vehicle/context (interval pairing above depends on that
    # adjacency), so list position is not time order across contexts. The summary spans the
    # chronological extremes of the returned points.
    chronological = sorted(observations, key=lambda p: (_at(p["occurred_at"]), p["evidence_id"]))
    return {"schema": "route-evidence-v3-1", "shipment_id": sid, "as_of": as_of,
            "contexts": contexts, "observations": observations,
            "summary": {"points_returned": len(observations), "sampled": more,
                        "first_observed_at": chronological[0]["occurred_at"] if chronological else None,
                        "last_observed_at": chronological[-1]["occurred_at"] if chronological else None,
                        "stationary_intervals": intervals[:4], "timing_comparisons": [],
                        "input_evidence_ids": [p["evidence_id"] for p in observations],
                        "note": "Vehicle observations only; gaps do not establish continuous stopping or parcel custody."},
            "source_nodes": source_nodes, "source_relationships": source_relationships,
            "truncated": {"contexts": len(unique) > max_runs, "observations": more,
                          "source_relationships": False}}
