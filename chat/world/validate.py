"""World-1 validation: foundation rules, physics, observation, truth isolation, tells and the monitor replay.

Every check counts what it examined and lists what failed; nothing is trusted from a saved report.

Foundation rules that cannot apply to a world with real recording failures (documented in README):
  PHYSICAL_CUSTODY_CHAIN   assumes every handover is recorded. A skipped receipt scan, a container loaded
                           onto the wrong truck or parcels passed between drivers without a record leave a
                           corroborated discontinuity in the observed chain. Replacement: every such event is
                           flagged by derive as a CUSTODY_GAP, is explained by a truth mechanism that suppressed
                           or misrecorded a handover, and the private physical custody chain is continuous.
  ADDRESS_VERSION_INTERVAL assumes a superseded address version was closed when written. In world-1 an imported
                           version is never mutated; a later dated version supersedes it (supersedes_id).
                           Replacement: the newer version names the old one, starts after it, and was recorded
                           no earlier than it became valid.
"""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import timedelta
import math
import re

from dataset_v2.contracts import UTC_FIELDS, instant, iso
from dataset_v2.feed import reconstitute, validate_live_bundle
from dataset_v2.live_bundle import truth_state_words, truth_vocabulary
from operations.agents import CAUSES
from operations.authority import ACTIONS
from world.geo import haversine_km
from world.mechanisms import MECHANISM_TYPES
from world.monitor import Replica, by_specificity
from world.truth import canary_token, labels_at, match_node, spec_estimate

ALLOWED_FOUNDATION = ("PHYSICAL_CUSTODY_CHAIN", "ADDRESS_VERSION_INTERVAL")
CUSTODY_RECORDING_FAULTS = {"SCAN_SKIPPED_AT_RECEIPT", "UNRECORDED_HANDOFF", "MISSORT", "DEVICE_OUTAGE", "PARTIAL_UPLOAD_LOSS"}
FIXTURE_KINDS = {"Case", "Exception", "AnalysisRun", "Recommendation", "Review", "OperatorDecision", "ActionExecution", "Resolution",
                 "Outcome", "AuditEvent", "Notification"}
TRUTH_FIELDS = ("knowable_at", "acceptable_causes", "root_cause", "expected_resolution", "mechanism_id", "physically_healthy",
                "shared_evidence_ids", "key_evidence", "secondary_issue", "booking_day", "final_location", "natural_recovery",
                "shares_opening_with", "alternative_mechanisms", "cancelled_by", "overdue_at", "truth_schema", "first_opening")


class Report:
    def __init__(self):
        self.checked, self.failures = Counter(), defaultdict(list)

    def check(self, condition, code, entity, message=""):
        self.checked[code] += 1
        if not condition:
            if len(self.failures[code]) < 25:
                self.failures[code].append({"entity": entity, "message": message})
            self.failures[code + "#count"].append(1)
        return bool(condition)

    def result(self, **extra):
        failed = {code: len(rows) for code, rows in self.failures.items() if code.endswith("#count")}
        return {"pass": not failed, "checked": dict(sorted(self.checked.items())),
                "failed_counts": {k.removesuffix("#count"): v for k, v in sorted(failed.items())},
                "failure_examples": {k: v for k, v in sorted(self.failures.items()) if not k.endswith("#count")}, **extra}


# ---------------------------------------------------------------------- foundation
def foundation(build, imported, items):
    """dataset_v2 validate_live_bundle on the reconstituted world, with the documented replacements."""
    from dataset_v2.derive import assess_shipment
    result = validate_live_bundle(imported, items)
    codes = Counter(e["code"] for e in result["errors"])
    full = reconstitute(imported, items)
    for sid, row in full.gold.items():
        full.nodes[sid].properties.setdefault("as_of", row["initial_snapshot_at"])
    report = Report()
    cutoff = full.config.as_of
    gap_cache = {}
    for error in result["errors"]:
        code, entity = error["code"], error["entity_id"]
        report.check(code in ALLOWED_FOUNDATION, "ONLY_DOCUMENTED_FOUNDATION_EXCEPTIONS", entity, code)
        if code == "PHYSICAL_CUSTODY_CHAIN":
            node = full.nodes[entity]
            sid = node.properties["holdout_group"]
            if sid not in gap_cache:
                gap_cache[sid] = {e for row in assess_shipment(full, sid, cutoff)["custody"] for e in row["gap_event_ids"]}
            report.check(entity in gap_cache[sid], "CUSTODY_DISCONTINUITY_FLAGGED_BY_DERIVE", entity)
            types = {m["type"] for m in build.truth[sid]["mechanisms"]}
            report.check(bool(types & CUSTODY_RECORDING_FAULTS), "CUSTODY_DISCONTINUITY_EXPLAINED_BY_MECHANISM", entity, sorted(types))
        elif code == "ADDRESS_VERSION_INTERVAL":
            versions = sorted((n for n in full.nodes.values() if n.kind == "AddressVersion" and n.properties.get("holdout_group") == entity),
                              key=lambda n: n.properties["version"])
            for old, new in zip(versions, versions[1:]):
                op, np_ = old.properties, new.properties
                report.check(np_.get("supersedes_id") == old.id and op.get("valid_to") is None
                             and instant(np_["valid_from"]) > instant(op["valid_from"])
                             and instant(np_["recorded_at"]) >= instant(np_["valid_from"]), "ADDRESS_SUPERSEDED_BY_DATED_VERSION", new.id)
    return {"validate_live_bundle_pass": result["pass"], "error_codes": dict(codes), "checks": len(result["checks"]),
            "check_counts": result["checks"], "statistics": result["statistics"], "feed": result["feed"],
            "documented_exceptions": report.result(), "pass": report.result()["pass"], "raw": result}


# ---------------------------------------------------------------------- physics
def _at(timeline, t):
    """Location row in force at instant t (timeline rows [t, kind, ref], time-ordered)."""
    times = [row[0] for row in timeline]
    i = bisect_right(times, t) - 1
    return timeline[i] if i >= 0 else None


def physics(build):
    sim, net = build.sim, build.network
    r = Report()
    containers = sim.containers
    for pid, state in sorted(sim.p.items()):
        tl = state.timeline
        r.check(bool(tl) and tl[0][1:] == ["FACILITY", state.shipment.origin_facility], "PARCEL_STARTS_AT_ORIGIN", pid)
        for a, b in zip(tl, tl[1:]):
            r.check(a[0] <= b[0] and (a[1], a[2]) != (b[1], b[2]), "ONE_PLACE_AT_A_TIME", pid, f"{a} -> {b}")
        r.check(all(row[1] in ("FACILITY", "CONTAINER", "VEHICLE", "PERSON") for row in tl), "LOCATION_KIND", pid)
        # Custody holder agrees with location at every custody change.
        for t, holder in state.custody:
            row = _at(tl, t)
            if row is None:
                r.check(False, "CUSTODY_MATCHES_LOCATION", pid, f"no location at {t}")
                continue
            kind, ref = row[1], row[2]
            if kind == "CONTAINER":
                crow = _at(containers[ref].timeline, t)
                ok = crow is not None and crow[2] == holder
            else:
                ok = ref == holder
            r.check(ok, "CUSTODY_MATCHES_LOCATION", pid, f"{t} holder {holder} location {kind}:{ref}")
        for a, b in zip(state.custody, state.custody[1:]):
            r.check(a[0] <= b[0] and a[1] != b[1], "CUSTODY_CONTINUITY", pid)
        # Container membership consistent with the container's own life: a parcel enters a container after it
        # exists, leaves it only once it has been opened, and where the container then is.
        for i, row in enumerate(tl):
            if row[1] != "CONTAINER":
                continue
            c = containers.get(row[2])
            nxt = tl[i + 1] if i + 1 < len(tl) else None
            ok = c is not None and c.created_at <= row[0] and pid in c.parcels
            if ok and nxt is not None:
                where = _at(c.timeline, nxt[0])
                ok = c.opened_at is not None and nxt[0] >= c.opened_at and where is not None and nxt[1] == "FACILITY" and where[2] == nxt[2]
            r.check(ok, "CONTAINER_CONTENTS", pid, row[2])
    # Conservation: every booked parcel is somewhere at the end; facility stocks never go negative.
    final = Counter(state.timeline[-1][1] for state in sim.p.values())
    r.check(sum(final.values()) == sum(len(s.parcels) for s in build.shipments.values()), "PARCEL_CONSERVATION", "world", dict(final))
    stock = defaultdict(list)
    for state in sim.p.values():
        tl = state.timeline
        for i, row in enumerate(tl):
            if row[1] == "FACILITY":
                stock[row[2]].append((row[0], 1))
                if i + 1 < len(tl):
                    stock[row[2]].append((tl[i + 1][0], -1))
    for facility, events in stock.items():
        level = 0
        for _, delta in sorted(events, key=lambda e: (e[0], e[1])):
            level += delta
            if level < 0:
                break
        r.check(level >= 0, "FACILITY_STOCK_NON_NEGATIVE", facility)
    # Vehicle capacity at every load change (parcels directly in the vehicle or inside its containers).
    occupancy = defaultdict(list)
    for pid, state in sim.p.items():
        tl, p = state.timeline, state.parcel
        for i, row in enumerate(tl):
            end = tl[i + 1][0] if i + 1 < len(tl) else build.config.end_at
            if row[1] == "VEHICLE":
                occupancy[row[2]].append((row[0], end, p.true_kg, p.volume))
            elif row[1] == "CONTAINER":
                ctl = containers[row[2]].timeline
                for j, crow in enumerate(ctl):
                    cend = ctl[j + 1][0] if j + 1 < len(ctl) else build.config.end_at
                    a, b = max(row[0], crow[0]), min(end, cend)
                    if crow[1] == "VEHICLE" and a < b:
                        occupancy[crow[2]].append((a, b, p.true_kg, p.volume))
    for vid, rows in occupancy.items():
        v = net.vehicles[vid]
        events = sorted([(a, 1, kg, m3) for a, b, kg, m3 in rows] + [(b, -1, kg, m3) for a, b, kg, m3 in rows], key=lambda e: (e[0], e[1]))
        kg = m3 = peak_kg = peak_m3 = 0.0
        for t, sign, w, vol in events:
            kg += sign * w
            m3 += sign * vol
            peak_kg, peak_m3 = max(peak_kg, kg), max(peak_m3, m3)
        r.check(peak_kg <= v.payload_kg + 1e-6 and peak_m3 <= v.volume_m3 + 1e-6, "VEHICLE_CAPACITY", vid,
                f"peak {peak_kg:.1f} kg / {v.payload_kg}, {peak_m3:.2f} m3 / {v.volume_m3}")
    # A driver drives one vehicle at a time (actual intervals of trips and routes).
    intervals = defaultdict(list)
    for tid, state in sim.trips.items():
        if state.departed_at and state.arrived_at and not state.cancelled:
            back = state.arrived_at + ((state.arrived_at - state.departed_at) if state.plan.kind != "LINEHAUL" and not tid.endswith("-R") else timedelta(0))
            intervals[state.plan.driver].append((state.departed_at, back, state.plan.vehicle, tid))
    for rid, route in sim.routes.items():
        if route.departed_at:
            intervals[route.driver].append((route.departed_at, route.returned_at or build.config.end_at, route.vehicle, rid))
    for driver, rows in intervals.items():
        rows.sort()
        for (a1, b1, v1, k1), (a2, b2, v2, k2) in zip(rows, rows[1:]):
            r.check(not (a2 < b1 and v1 != v2), "DRIVER_ONE_VEHICLE", driver, f"{k1} overlaps {k2}")
    # Travel times consistent with distance.
    for tid, state in sim.trips.items():
        if state.departed_at and state.arrived_at and not state.cancelled:
            a, b = net.facilities[state.plan.origin], net.facilities[state.plan.destination]
            km = haversine_km(a.lat, a.lng, b.lat, b.lng)
            hours = (state.arrived_at - state.departed_at).total_seconds() / 3600
            r.check(hours * 110 >= km, "TRAVEL_TIME_VS_DISTANCE", tid, f"{km:.0f} km in {hours:.2f} h")
    for rid, route in sim.routes.items():
        for (t1, la1, ln1, _), (t2, la2, ln2, _) in zip(route.timeline, route.timeline[1:]):
            km = haversine_km(la1, ln1, la2, ln2)
            hours = (t2 - t1).total_seconds() / 3600
            r.check(hours * 90 >= km, "TRAVEL_TIME_VS_DISTANCE", rid, f"{km:.1f} km in {hours:.2f} h")
    # Facility throughput within capacity (per hour, with the capacity in force during that hour).
    for (facility, hour), count in sim.processed.items():
        capacity = max(sim.capacity(facility, hour + timedelta(minutes=m))[0] for m in (0, 20, 40, 59))
        r.check(count <= math.ceil(capacity * 1.15) + 1, "THROUGHPUT_WITHIN_CAPACITY", f"{facility}@{iso(hour)}", f"{count} > {capacity:.1f}")
    # Facility scans happen where the parcel is.
    for a in sim.acts:
        if a["type"] != "scan" or not a.get("facility"):
            continue
        state = sim.p[a["pid"]]
        ok = False
        for probe in (a["t"], a["t"] - timedelta(seconds=1)):
            row = _at(state.timeline, probe)
            if row is None:
                continue
            if row[1] == "FACILITY" and row[2] == a["facility"]:
                ok = True
            elif row[1] == "CONTAINER":
                crow = _at(containers[row[2]].timeline, probe)
                if crow and (crow[2] == a["facility"] or (crow[1] == "VEHICLE" and a.get("trip"))):
                    ok = True
            elif row[1] == "VEHICLE" and a.get("vehicle") in (row[2], None) and a["obs"] in ("LOAD_CONFIRMATION", "CONTAINER_SCAN"):
                ok = True
        r.check(ok, "SCAN_WHERE_PARCEL_IS", a["act"], f"{a['obs']} at {a['facility']}")
    return r.result(final_locations=dict(final))


# ---------------------------------------------------------------------- observation
def observation(build, items):
    world, records, sim, plan = build.world, build.observer.records, build.sim, build.plan
    r = Report()
    lags = defaultdict(list)
    for nid, meta in records.items():
        node = world.nodes[nid]
        p = node.properties
        if not p.get("occurred_at"):
            continue
        occurred, recorded = instant(p["occurred_at"]), instant(p["recorded_at"])
        r.check(occurred <= recorded, "OCCURRED_BEFORE_RECORDED", nid)
        if meta["act"]:
            act = sim.acts_by_id(meta["act"])
            r.check(occurred == act["t"], "RECORD_TIME_IS_EVENT_TIME", nid)
            if node.kind == "ScanEvent":
                r.check(p.get("device_ref") == act.get("device") and p.get("device_ref") in build.network.devices, "UPLOAD_ONLY_DEVICE_RECORDS", nid)
        lags["mechanism" if meta["mech"] else "ordinary"].append((recorded - occurred).total_seconds())
    by_id = {}
    for item in items:
        node = world.nodes.get(item["source_event_id"])
        r.check(node is not None and instant(item["deliver_at"]) >= instant(node.properties["recorded_at"]), "FEED_AFTER_RECORDED", item["feed_id"])
        by_id.setdefault(item["source_event_id"], []).append(item)
    retransmitted = 0
    for source, rows in by_id.items():
        if len(rows) > 1:
            retransmitted += len(rows) - 1
            r.check(len({x["payload_hash"] for x in rows}) == 1 and len({x["channel"] for x in rows}) == 1, "DUPLICATES_SHARE_IDENTITY", source)
    # Outages: silent heartbeats, correlated delays for every parcel the device handled, a truthful reconnect beat.
    beats = defaultdict(list)
    for nid, meta in records.items():
        node = world.nodes[nid]
        if node.kind == "DeviceHeartbeat":
            beats[node.properties["device_id"]].append((instant(node.properties["occurred_at"]), node.properties["pending_uploads"]))
    device_records = defaultdict(list)
    for nid, meta in records.items():
        if meta["device"] and meta["occurred"] is not None and meta["sid"]:
            device_records[meta["device"]].append((meta["occurred"], meta["recorded"], meta["sid"], nid))
    for device, windows in plan.device_down.items():
        for start, end, mid in windows:
            inside = [b for b in beats.get(device, []) if start <= b[0] < end]
            r.check(not inside, "NO_HEARTBEAT_DURING_OUTAGE", mid, f"{len(inside)} beats")
            affected = [row for row in device_records.get(device, []) if start <= row[0] < end]
            r.check(all(row[1] >= end for row in affected), "OUTAGE_DELAYS_EVERY_RECORD", mid)
            telemetry = build.network.devices[device].telemetry != "NONE"
            reconnect = [b for b in beats.get(device, []) if b[0] == end]
            if telemetry and affected:
                r.check(bool(reconnect) and reconnect[0][1] == len(affected), "RECONNECT_BEAT_REPORTS_BUFFER", mid,
                        f"beat {reconnect[:1]} buffered {len(affected)}")
    for device, windows in plan.device_loss.items():
        for start, end, fraction, mid in windows:
            stuck = [n for n, meta in records.items() if mid in meta["mech"] and meta["sid"]]
            r.check(all(records[n]["recorded"] >= end for n in stuck), "STUCK_RECORDS_ARRIVE_AFTER_WINDOW", mid)
            if stuck and build.network.devices[device].telemetry != "NONE":
                first_stuck = min(records[n]["occurred"] for n in stuck)
                last_upload = max(records[n]["recorded"] for n in stuck)
                visible = [b for b in beats.get(device, []) if first_stuck <= b[0] < last_upload]
                # A device that beats while records are stuck reports a non-empty queue.
                r.check(not visible or any(b[1] > 0 for b in visible), "PENDING_QUEUE_VISIBLE_IN_HEARTBEATS", mid)
    # Out-of-order arrival: records of one shipment received in a different order than they happened.
    per_ship = defaultdict(list)
    for nid, meta in records.items():
        if meta["sid"] and meta["occurred"] is not None:
            per_ship[meta["sid"]].append((meta["occurred"], meta["recorded"], nid))
    inverted, shipments_with = 0, 0
    for sid, rows in per_ship.items():
        rows.sort()
        count = sum(1 for a, b in zip(rows, rows[1:]) if b[1] < a[1])
        inverted += count
        shipments_with += bool(count)
    r.check(inverted > 0, "OUT_OF_ORDER_ARRIVALS_EXIST", "world", inverted)
    r.check(retransmitted > 0, "RETRANSMISSIONS_EXIST", "world", retransmitted)
    def quant(values, q):
        values = sorted(values)
        return round(values[min(len(values) - 1, int(q * len(values)))], 1) if values else None
    return r.result(out_of_order_pairs=inverted, shipments_with_out_of_order=shipments_with, retransmitted_messages=retransmitted,
                    upload_lag_seconds={k: {"n": len(v), "p50": quant(v, .5), "p90": quant(v, .9), "p99": quant(v, .99), "max": quant(v, 1)}
                                        for k, v in sorted(lags.items())})


# ---------------------------------------------------------------------- truth isolation
def vocabulary(build):
    truth = build.truth
    substrings = set(TRUTH_FIELDS) | {"w1m-", canary_token(build.config).lower()}
    for mtype in MECHANISM_TYPES:
        substrings |= {mtype.lower(), mtype.lower().replace("_", " ")}
    for mech in build.plan.items.values():
        if "_" in mech.subtype:
            substrings |= {mech.subtype.lower(), mech.subtype.lower().replace("_", " ")}
    for term in truth_vocabulary(truth):
        if term not in ("healthy",):
            substrings.add(term.lower())
    words = set(w.lower() for w in truth_state_words(truth))
    causes = {c for c in CAUSES if c != "INSUFFICIENT_EVIDENCE"} | {m for m in MECHANISM_TYPES}
    actions = set(ACTIONS)
    return sorted(substrings), sorted(words), sorted(causes), sorted(actions)


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _texts(item)


def isolation(build, imported, items):
    substrings, words, causes, actions = vocabulary(build)
    word_re = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b") if words else None
    token_re = re.compile(r"[A-Z][A-Z0-9_]+")
    cause_set, action_set = set(causes), set(actions)
    hits = defaultdict(list)
    scanned = Counter()

    def scan(origin, kind, texts, exempt):
        scanned[origin] += len(texts)
        raw = "\n".join(texts)
        lower = raw.lower()
        for term in substrings:
            if term in lower and not (exempt and term.upper().replace(" ", "_") in cause_set):
                hits[term].append(origin)
        if word_re:
            match = word_re.search(lower)
            if match:
                hits["word:" + match.group(1)].append(origin)
        if not exempt:
            for token in set(token_re.findall(raw)):
                if token in cause_set or token in action_set:
                    hits["token:" + token].append(origin)

    for node in imported.nodes.values():
        exempt = node.kind in FIXTURE_KINDS
        scan(f"node:{node.kind}", node.kind, list(_texts({k: v for k, v in node.properties.items()})), exempt)
    for edge in imported.edges.values():
        scan(f"edge:{edge.kind}", edge.kind, list(_texts(edge.properties)), edge.properties.get("provenance") == "DERIVED")
    for item in items:
        scan(f"feed:{item['channel']}", item["message_type"], [item["payload_json"], item["message_type"]], False)
    canary = canary_token(build.config).lower()
    return {"pass": not hits, "terms_scanned": {"substrings": len(substrings), "whole_words": len(words), "cause_and_type_tokens": len(causes),
                                                "action_tokens": len(actions)},
            "canary_checked": True, "canary_hits": len(hits.get(canary, [])), "mechanism_id_hits": len(hits.get("w1m-", [])),
            "texts_scanned": dict(scanned), "hits": {k: Counter(v).most_common(5) for k, v in sorted(hits.items())},
            "exemption": "Derived Case/Exception and history-outcome fixture nodes may carry catalogue cause and action codes "
                         "(derive emits them from observations); they are still scanned for mechanism words, ids and truth fields."}


def private_state_isolation(build):
    """Addendum B1a: the private physical state written under artifacts/ carries no cause codes, mechanism names or
    ids, truth field names or the canary (same vocabulary as the export scan)."""
    from world.export import _jsonable, private_physical
    import json
    substrings, words, causes, actions = vocabulary(build)
    word_re = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b") if words else None
    token_re = re.compile(r"[A-Z][A-Z0-9_]+")
    hits, scanned = defaultdict(int), Counter()
    for name, rows in private_physical(build).items():
        for row in rows:
            text = json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True, default=str)
            lower = text.lower()
            scanned[name] += 1
            for term in substrings:
                if term in lower:
                    hits[f"{term}@{name}"] += 1
            if word_re and word_re.search(lower):
                hits[f"word:{word_re.search(lower).group(1)}@{name}"] += 1
            for token in set(token_re.findall(text)):
                if token in set(causes):
                    hits[f"token:{token}@{name}"] += 1
    return {"pass": not hits, "records_scanned": dict(sorted(scanned.items())), "hits": dict(sorted(hits.items()))}


def discrimination(build):
    """Addendum A1: every discrimination spec is machine-checkable against the world's records.

    Record items name an observation that exists; absence items name an expectation whose matching records,
    recomputed by a full scan of the world, are exactly its cancelled_by list and empty (the absence is real);
    the estimate equals the spec evaluated at feed delivery times and is never before the mechanism started."""
    from world.monitor import deliver_at
    r = Report()
    nodes = build.world.nodes
    deliver = {nid: deliver_at(nodes[nid]) for nid in build.observer.records if nid in nodes and nodes[nid].properties.get("recorded_at")}
    by_kind = defaultdict(list)
    for node in nodes.values():
        by_kind[node.kind].append(node)
    empty = Counter()
    groups = Counter()
    for sid, row in sorted(build.truth.items()):
        for m in row["mechanisms"]:
            spec = m["discrimination"]
            key = f"{sid}/{m['mechanism_id']}"
            if m["resolution"] != "NONE" and not spec["any_of"]:
                empty[m["type"]] += 1
            for group in spec["any_of"]:
                groups[len(group["all_of"])] += 1
                for item in group["all_of"]:
                    if "record" in item:
                        node = nodes.get(item["record"])
                        r.check(node is not None and bool(node.properties.get("recorded_at")) and item["record"] in build.observer.records,
                                "RECORD_ITEM_IS_AN_OBSERVATION", key, item["record"])
                    else:
                        absence = item["absence"]
                        found = sorted(n.id for n in by_kind[absence["match"]["kind"]] if match_node(n, absence["match"]))
                        r.check(found == absence["cancelled_by"], "ABSENCE_MATCHES_RECOMPUTED", key, absence["expected"])
                        r.check(not found, "ABSENCE_IS_REAL", key, absence["expected"])
            estimate = spec_estimate(spec, deliver)
            r.check((iso(estimate) if estimate else None) == m["knowable_at_estimate"], "ESTIMATE_RECOMPUTES", key)
            if estimate and m["started_at"] and m["resolution"] != "NONE":
                r.check(estimate >= instant(m["started_at"]), "ESTIMATE_NOT_BEFORE_START", key, m["type"])
            r.check(row.get("canary") == canary_token(build.config), "CANARY_IN_EVERY_ROW", sid)
    actionable = sum(1 for row in build.truth.values() for m in row["mechanisms"] if m["resolution"] != "NONE")
    return r.result(actionable_instances=actionable, actionable_without_any_discriminator=dict(sorted(empty.items())),
                    groups_by_size=dict(sorted(groups.items())))


def precedent_cutoff(build, exports):
    """Addendum A2: no precedent leaks across the history/development cut-off. Every history outcome is verified
    before the live window starts, every authored precedent's shipment had no mechanism instance active at or after
    the cut-off (recomputed here), and nothing excluded or live was authored."""
    from world.build import CUTOFF_EXEMPT, mechanism_active_until
    r = Report()
    summary = {}
    for live_split, (imported, items, truth, live_start) in exports.items():
        outcomes = [n for n in imported.nodes.values() if n.kind == "Outcome"]
        authored = {n.properties["holdout_group"] for n in outcomes}
        report = build.history_reports.get(live_split, {})
        for n in outcomes:
            r.check(n.properties["split"] == "history", "OUTCOMES_ONLY_IN_HISTORY", n.id)
            r.check(instant(n.properties["verified_at"]) < live_start, "VERIFIED_BEFORE_LIVE_WINDOW", n.id, n.properties["verified_at"])
        for kind in ("Resolution", "AuditEvent", "Notification", "OperatorDecision", "ActionExecution"):
            for n in imported.nodes.values():
                if n.kind == kind and n.properties.get("split") == "history":
                    r.check(instant(n.properties["recorded_at"]) < live_start, "HISTORY_RECORD_BEFORE_LIVE_WINDOW", n.id, kind)
        for sid in sorted(authored):
            active = [mechanism_active_until(build, m, sid) for m in build.truth[sid]["mechanisms"] if m["type"] not in CUTOFF_EXEMPT]
            r.check(all(t is not None and t < live_start for t in active), "NO_MECHANISM_ACTIVE_AT_CUTOFF", sid)
            r.check(sid not in report.get("not_imported", {}), "EXCLUDED_NOT_AUTHORED", sid)
        cases = sum(1 for n in imported.nodes.values() if n.kind == "Case" and n.properties["split"] == "history")
        summary[live_split] = {"live_start": iso(live_start), "history_cases": cases, "precedents_authored": len(authored),
                               "not_imported_by_reason": dict(Counter(report.get("not_imported", {}).values())),
                               "precedents_succeeded": sum(1 for n in outcomes if n.properties["success"]),
                               "precedents_failed": sum(1 for n in outcomes if not n.properties["success"])}
    return r.result(per_export=summary)


# ---------------------------------------------------------------------- tell detector
# Identifier-like values (plates, references, free text with tracking numbers) are not field values a tell is made of.
SKIP_FIELDS = {"entity_id", "dataset_id", "schema_version", "synthetic", "provenance", "split", "holdout_group", "shipment_id",
               "recorded_at", "occurred_at", "media_ref", "statement_en", "statement_ar", "address_text", "display_name", "contact_ref",
               "package_ids", "evidence_ids", "segment_ids", "tracking_id", "template_ref", "plate_ref", "manifest_barcode",
               "observed_barcode", "authorization_ref", "name", "name_ar"}
# Idempotency-only mechanisms are excluded: a retransmission is directly observable by design and never a case.
TELL_EXCLUDED = {"DUPLICATE_EVENTS"}
CATALOG_LINKED = {"Trip", "Container", "RouteRun", "Device", "Vehicle", "Driver", "Lane", "Branch", "Hub", "SortingCenter",
                  "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse", "Organization", "Provider"}
# From the shared records a shipment references, only their type-like fields count as features.
CATALOG_TYPE_FIELDS = {"trip_type", "container_type", "device_kind", "telemetry_stream", "ownership", "vehicle_class", "employment", "role",
                       "provider_type", "lane_type", "organization_type", "handling", "modes"}


def _categorical(field, value):
    if field in SKIP_FIELDS or field in UTC_FIELDS or field.endswith("_at"):
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return abs(value) < 1000
    if isinstance(value, str):
        return not value.startswith("DEMO-") and len(value) <= 60
    return False


def features(world, sid_nodes):
    out = set()
    linked = set()
    for node in sid_nodes:
        for field, value in node.properties.items():
            values = value if isinstance(value, list) else [value]
            for v in values:
                if isinstance(v, str) and v.startswith("DEMO-") and v in world.nodes and world.nodes[v].kind in CATALOG_LINKED:
                    linked.add(v)
                elif _categorical(field, v):
                    out.add((node.kind, field, v))
    for ref in linked:
        node = world.nodes[ref]
        for field, value in node.properties.items():
            if field not in CATALOG_TYPE_FIELDS:
                continue   # A shared resource's own attributes (a route's stop count, a hub's capacity) identify the resource, not a cause.
            for v in (value if isinstance(value, list) else [value]):
                if _categorical(field, v):
                    out.add((node.kind, field, v))
    return out


def tells(build, *, rare=.20, precision=.90, support=5):
    world = build.world
    owned = defaultdict(list)
    for node in world.nodes.values():
        sid = node.properties.get("holdout_group")
        if sid:
            owned[sid].append(node)
    feats = {sid: features(world, nodes) for sid, nodes in owned.items()}
    results = {}
    for label, population in (("development", [s for s, r in build.truth.items() if r["split"] == "development"]),
                              ("world", list(build.truth))):
        n = len(population)
        holders = defaultdict(set)
        for sid in population:
            for f in feats[sid]:
                holders[f].add(sid)
        mech = defaultdict(set)
        for sid in population:
            for m in build.truth[sid]["mechanisms"]:
                if m["type"] not in TELL_EXCLUDED:
                    mech[m["type"]].add(sid)
        found, near = [], []
        for f, sids in holders.items():
            if len(sids) > rare * n:
                continue
            for mtype, msids in mech.items():
                hit = len(sids & msids)
                if hit >= support:
                    p = hit / len(sids)
                    row = {"feature": list(map(str, f)), "mechanism": mtype, "support": hit, "precision": round(p, 3), "holders": len(sids)}
                    if p >= precision:
                        found.append(row)
                    elif p >= .7:
                        near.append(row)
        results[label] = {"population": n, "features": len(holders), "tells": sorted(found, key=lambda r: (-r["precision"], r["mechanism"])),
                          "near_misses_precision_0.7_to_0.9": sorted(near, key=lambda r: (-r["precision"], r["mechanism"]))[:25]}
    return {"pass": not any(v["tells"] for v in results.values()),
            "rule": f"value held by <= {rare:.0%} of shipments with precision >= {precision} and support >= {support} for one mechanism",
            "excluded_mechanisms": sorted(TELL_EXCLUDED), "skipped_fields": sorted(SKIP_FIELDS),
            "referenced_catalog_fields": sorted(CATALOG_TYPE_FIELDS), **results}


# ---------------------------------------------------------------------- monitor replay
def monitor_replay(build, imported, items):
    """Hourly ticks from the first provider message, 900 s allowance, over the live shipments of this export."""
    full = reconstitute(imported, items)
    live = sorted(sid for sid, n in imported.nodes.items() if n.kind == "Shipment" and n.properties["split"] == "development")
    start = instant(min(i["deliver_at"] for i in items if i["origin"] == "PROVIDER")) - timedelta(seconds=1)
    fed = {i["source_event_id"] for i in items}
    replica = Replica(full, start, evidence_ids=fed, gateway_lag=False)
    end = build.config.end_at
    # The scorer's ingestion log: imported records are there from the start; a fed record is ingested at the first
    # hourly tick at or after its delivery (the replica's visibility).
    imported_ids = set(imported.nodes)
    by_tick = sorted((tick, nid) for nid, tick in replica.visible.items())

    def ingested(t):
        return imported_ids | {nid for tick, nid in by_tick if tick <= t}
    everything = ingested(end)
    rows = {}
    for sid in live:
        timeline = replica.timeline(sid, end)
        opening = next(((t, c, s) for t, c, s in timeline if c), None)
        truth = build.truth[sid]
        later = sorted({sym for t, c, s in timeline for sym in s} - set(opening[2] if opening else []))
        actionable = [m for m in truth["mechanisms"] if m["resolution"] != "NONE"]
        rows[sid] = {"healthy": truth["healthy"], "mechanisms": sorted({m["type"] for m in actionable}),
                     "background": sorted({m["type"] for m in truth["mechanisms"] if m["origin"] == "background"}),
                     "opened_at": iso(opening[0]) if opening else None, "opening_symptoms": opening[2] if opening else [],
                     "opening_codes": opening[1] if opening else [], "later_symptoms": later,
                     "ambiguous": any(m["discrimination"]["shares_opening_with"] for m in actionable),
                     "labels_at_opening": labels_at(truth, opening[0], ingested(opening[0])) if opening else None,
                     "labels_at_end": labels_at(truth, end, everything)}
    healthy = [r for r in rows.values() if r["healthy"]]
    abnormal = [r for r in rows.values() if not r["healthy"]]
    per_mech = defaultdict(lambda: {"shipments": 0, "opened": 0, "opening_symptoms": Counter()})
    for r in abnormal:
        for m in r["mechanisms"]:
            per_mech[m]["shipments"] += 1
            if r["opened_at"]:
                per_mech[m]["opened"] += 1
                per_mech[m]["opening_symptoms"][" + ".join(r["opening_symptoms"])] += 1
    by_set = defaultdict(lambda: {"shipments": 0, "healthy": 0, "mechanisms": Counter(), "single_mechanism_shipments": Counter()})
    for r in rows.values():
        if not r["opened_at"]:
            continue
        key = " + ".join(r["opening_symptoms"])
        by_set[key]["shipments"] += 1
        by_set[key]["healthy"] += r["healthy"]
        for m in r["mechanisms"]:
            by_set[key]["mechanisms"][m] += 1
        if len(r["mechanisms"]) == 1:
            by_set[key]["single_mechanism_shipments"][r["mechanisms"][0]] += 1
    insufficient = sum(1 for r in rows.values() if r["opened_at"] and r["labels_at_opening"] == ["INSUFFICIENT_EVIDENCE"])
    opened_abnormal = [r for r in abnormal if r["opened_at"]]
    ambiguous = [r for r in opened_abnormal if r["ambiguous"]]
    identifiable = [r for r in ambiguous if r["labels_at_end"] != ["INSUFFICIENT_EVIDENCE"]]
    at_opening = [r for r in identifiable if r["labels_at_opening"] != ["INSUFFICIENT_EVIDENCE"]]
    return {"tick_origin": iso(start), "tick_seconds": 3600, "detection_allowance_seconds": 900, "live_shipments": len(rows),
            "healthy": {"shipments": len(healthy), "opened": sum(bool(r["opened_at"]) for r in healthy),
                        "false_positive_rate": round(sum(bool(r["opened_at"]) for r in healthy) / max(1, len(healthy)), 3),
                        "opening_symptoms": dict(Counter(" + ".join(r["opening_symptoms"]) for r in healthy if r["opened_at"]))},
            "abnormal": {"shipments": len(abnormal), "opened": sum(bool(r["opened_at"]) for r in abnormal),
                         "not_opened": sum(not r["opened_at"] for r in abnormal),
                         "opened_before_any_cause_knowable": insufficient,
                         "identifiable_at_opening": sum(r["labels_at_opening"] != ["INSUFFICIENT_EVIDENCE"] for r in opened_abnormal),
                         "identifiable_by_horizon_end": sum(r["labels_at_end"] != ["INSUFFICIENT_EVIDENCE"] for r in opened_abnormal)},
            "ambiguity": {"rule": "an opened abnormal case is ambiguous when one of its mechanisms shares its opening symptom set with "
                                  "another cause (truth shares_opening_with); identifiable when labels_at(row, t, ingested) names a cause",
                          "opened_abnormal": len(opened_abnormal), "ambiguous": len(ambiguous),
                          "identifiable_ambiguous": len(identifiable), "identifiable_ambiguous_at_opening": len(at_opening),
                          "identifiable_ambiguous_only_after_opening": len(identifiable) - len(at_opening),
                          "unidentifiable_ambiguous": len(ambiguous) - len(identifiable)},
            "per_mechanism": {m: {"shipments": v["shipments"], "opened": v["opened"], "opening_symptoms": dict(v["opening_symptoms"].most_common())}
                              for m, v in sorted(per_mech.items())},
            "per_opening_symptom_set": {k: {"shipments": v["shipments"], "healthy_shipments": v["healthy"],
                                            "distinct_mechanisms": len(v["mechanisms"]), "mechanisms": dict(v["mechanisms"].most_common()),
                                            "distinct_mechanisms_single_cause": len(v["single_mechanism_shipments"]),
                                            "single_cause_mechanisms": dict(v["single_mechanism_shipments"].most_common())}
                                        for k, v in sorted(by_set.items(), key=lambda kv: -kv[1]["shipments"])},
            "shipments": rows}


# ---------------------------------------------------------------------- coverage and counts
def coverage(build):
    per = defaultdict(lambda: Counter())
    for sid, r in build.truth.items():
        for m in {m["type"] for m in r["mechanisms"]}:
            per[m][r["split"]] += 1
    sizes = Counter(r["split"] for r in build.truth.values())
    targets = {m: build.config.target(m, "development", sizes["development"]) for m, _, _ in build.config.rates}
    # The brief's floor (10) for the full configuration; a scaled-down test world uses its committed-rate target.
    required = {m: min(10, t) for m, t in targets.items()}
    dev = {m: per[m]["development"] for m in required}
    below = {m: v for m, v in dev.items() if v < required[m]}
    return {"pass": not below, "minimum_required_in_development": min(required.values()), "development_targets": targets,
            "below_minimum": below,
            "affected_shipments": {m: dict(per[m]) for m in sorted(per)},
            "multi_cause_shipments": dict(Counter(r["split"] for r in build.truth.values()
                                                  if len({m['type'] for m in r['mechanisms'] if m['resolution'] != 'NONE'}) >= 2))}


def run_all(build, exports):
    """exports: {live_split: (imported, items, truth, live_start)}"""
    report = {"physics": physics(build), "observation": None, "coverage": coverage(build), "tells": tells(build),
              "discrimination": discrimination(build), "private_state_isolation": private_state_isolation(build),
              "precedent_cutoff": precedent_cutoff(build, exports), "exports": {}}
    for live_split, (imported, items, truth, live_start) in exports.items():
        found = foundation(build, imported, items)
        raw = found.pop("raw")
        report["exports"][live_split] = {"foundation": found, "foundation_raw": raw, "isolation": isolation(build, imported, items)}
        if report["observation"] is None:
            report["observation"] = observation(build, items)
    report["pass"] = all(report[name]["pass"] for name in ("physics", "observation", "coverage", "tells", "discrimination",
                                                           "private_state_isolation", "precedent_cutoff")) and all(
        e["foundation"]["pass"] and e["isolation"]["pass"] for e in report["exports"].values())
    return report


# ---------------------------------------------------------------------- pre-run tell test (addendum B3)
OPENING_SKIP_FIELDS = {"entity_id", "dataset_id", "schema_version", "synthetic", "split", "holdout_group", "shipment_id"}


def opening_cases(build, split="development"):
    """Opening case data of every abnormal shipment of a split that the monitor opened: the opening symptom set,
    the rule codes, every visible property value of the shipment's evidence at the opening tick, and the cause
    codes of its actionable mechanisms (the label). Time fields are left out (unique per record)."""
    replica = build.replica
    out = {}
    for sid, opening in sorted(build.first_opening.items()):
        row = build.truth[sid]
        if row["split"] != split or row["healthy"]:
            continue
        tick = instant(opening["at"])
        features = set()
        for nodes in replica.index.groups[sid].values():
            for node in nodes:
                recorded = node.properties.get("recorded_at")
                if recorded is None or instant(recorded) > tick:
                    continue
                for field, value in node.properties.items():
                    if field in OPENING_SKIP_FIELDS or field in UTC_FIELDS or field.endswith("_at"):
                        continue
                    for v in (value if isinstance(value, list) else [value]):
                        if isinstance(v, (str, bool, int, float)):
                            features.add(f"{node.kind}.{field}={v}")
        actionable = [m for m in row["mechanisms"] if m["resolution"] != "NONE"]
        out[sid] = {"symptoms": " + ".join(opening["symptoms"]), "codes": by_specificity(opening["codes"]),
                    "features": features, "causes": sorted({m["cause_code"] for m in actionable}),
                    "ambiguous": any(m["discrimination"]["shares_opening_with"] for m in actionable)}
    return out


def tell_test(train, test, *, support=5):
    """Pre-run tell test of two built worlds (see tell_test_cases)."""
    train_cases, test_cases = opening_cases(train), opening_cases(test)
    result = tell_test_cases(train_cases, test_cases, support=support)
    reverse = tell_test_cases(test_cases, train_cases, support=support)
    # Diagnostic only: the same test with the two worlds' roles swapped.
    result["diagnostic_reverse_direction"] = {**{k: reverse["ambiguous"][k] for k in ("cases", "baseline_correct", "lookup_correct")},
                                              "without_identifier_values": reverse["diagnostic_without_identifier_values"]}
    result["train"] = {"seed": train.config.seed, "total": train.config.total, "cases": result.pop("train_cases")}
    result["test"] = {"seed": test.config.seed, "total": test.config.total, "cases": result.pop("test_cases")}
    return result


def tell_test_cases(train_cases, test_cases, *, support=5, diagnostics=True):
    """Train a lookup classifier on development opening cases of one world and evaluate it on another seed's
    development opening cases. It must not beat the rule-code baseline on the ambiguous stratum.

    baseline  the training majority cause for the rule codes at opening, most specific first: the full code tuple,
              backing off to the most specific code, then the overall majority (the single-code variant is reported
              too, as single_code_baseline_correct)
    lookup    keys (opening symptom set, feature value) with training support >= `support`; the key with the
              highest training precision (ties: support, then name) predicts its majority cause; no such key ->
              the baseline's prediction
    A prediction is correct when it is one of the case's cause codes."""
    # Counters hold, per key, the number of training cases carrying each cause, plus "#cases" (cases with the key).
    by_codes, by_code, by_key, overall = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter), Counter()
    for case in train_cases.values():
        codes, code = tuple(case["codes"]), case["codes"][0] if case["codes"] else ""
        by_codes[codes]["#cases"] += 1
        by_code[code]["#cases"] += 1
        for feature in case["features"]:
            by_key[(case["symptoms"], feature)]["#cases"] += 1
        for cause in case["causes"]:
            overall[cause] += 1
            by_codes[codes][cause] += 1
            by_code[code][cause] += 1
            for feature in case["features"]:
                by_key[(case["symptoms"], feature)][cause] += 1
    majority = min(overall.items(), key=lambda kv: (-kv[1], kv[0]))[0] if overall else None

    def top(counter):
        return min(((k, v) for k, v in counter.items() if k != "#cases"), key=lambda kv: (-kv[1], kv[0]))

    def single_code(case):
        counter = by_code.get(case["codes"][0] if case["codes"] else "")
        return top(counter)[0] if counter else majority

    def baseline(case):
        """The monitor's rule codes at opening, most specific first: the full code tuple, backing off to the most
        specific code, then to the overall majority."""
        counter = by_codes.get(tuple(case["codes"]))
        return top(counter)[0] if counter else single_code(case)

    def lookup(case):
        best = None
        for feature in case["features"]:
            counter = by_key.get((case["symptoms"], feature))
            if not counter:
                continue
            n = counter["#cases"]
            if n < support:
                continue
            cause, hits = top(counter)
            key = (-hits / n, -n, feature)
            if best is None or key < best[0]:
                best = (key, cause, feature)
        return (best[1], best[2]) if best else (baseline(case), None)

    strata = {"ambiguous": [c for c in test_cases.values() if c["ambiguous"]], "all_opened_abnormal": list(test_cases.values())}
    results = {}
    for name, cases in strata.items():
        base_hits = sum(baseline(c) in c["causes"] for c in cases)
        single_hits = sum(single_code(c) in c["causes"] for c in cases)
        decisions = [lookup(c) for c in cases]
        look_hits = sum(cause in c["causes"] for c, (cause, _) in zip(cases, decisions))
        used = Counter(feature for _, feature in decisions if feature)
        wins, losses = Counter(), Counter()
        for c, (cause, feature) in zip(cases, decisions):
            right, base_right = cause in c["causes"], baseline(c) in c["causes"]
            if right != base_right:
                (wins if right else losses)[feature or "(baseline)"] += 1
        results[name] = {"cases": len(cases), "baseline_correct": base_hits, "lookup_correct": look_hits,
                         "baseline_accuracy": round(base_hits / max(1, len(cases)), 3), "lookup_accuracy": round(look_hits / max(1, len(cases)), 3),
                         "single_code_baseline_correct": single_hits,
                         "lookup_used_a_feature": sum(1 for _, f in decisions if f), "most_used_features": used.most_common(10),
                         "discordant": {"lookup_right_baseline_wrong": sum(wins.values()), "baseline_right_lookup_wrong": sum(losses.values()),
                                        "features_behind_lookup_wins": wins.most_common(8),
                                        "features_behind_lookup_losses": losses.most_common(8)}}
    out = {"pass": results["ambiguous"]["lookup_correct"] <= results["ambiguous"]["baseline_correct"],
            "rule": "lookup classifier on opening data (symptom set + every visible property value) must not beat the rule-code "
                    "baseline (most specific code at opening) on the ambiguous stratum of another seed's world",
            "train_cases": len(train_cases), "test_cases": len(test_cases), "min_support": support, **results}
    if diagnostics:
        # Diagnostic only (not the criterion): the same test without values that are resource identifiers (DEMO-...).
        def strip(cases):
            return {k: {**c, "features": {f for f in c["features"] if not f.split("=", 1)[1].startswith("DEMO-")}} for k, c in cases.items()}
        plain = tell_test_cases(strip(train_cases), strip(test_cases), support=support, diagnostics=False)
        out["diagnostic_without_identifier_values"] = {k: plain["ambiguous"][k] for k in ("cases", "baseline_correct", "lookup_correct")}
    return out
