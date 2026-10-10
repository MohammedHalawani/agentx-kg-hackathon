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
from world.mechanisms import MECHANISM_TYPES, RULE_CODES
from world.monitor import Replica, by_specificity
from world.truth import canary_token, labels_at, labels_at_estimate, match_node, own_item, spec_estimate

ALLOWED_FOUNDATION = ("PHYSICAL_CUSTODY_CHAIN", "ADDRESS_VERSION_INTERVAL")
CUSTODY_RECORDING_FAULTS = {"SCAN_SKIPPED_AT_RECEIPT", "UNRECORDED_HANDOFF", "MISSORT", "DEVICE_OUTAGE", "PARTIAL_UPLOAD_LOSS",
                            "RETURN_SCAN_SKIPPED", "ASSIGNED_NOT_LOADED"}
FIXTURE_KINDS = {"Case", "Exception", "AnalysisRun", "Recommendation", "Review", "OperatorDecision", "ActionExecution", "Resolution",
                 "Outcome", "AuditEvent", "Notification"}
# Mechanisms whose effect on a shipment is a record of that shipment (as opposed to a record that is missing, or a
# shared resource running late): nothing about them is knowable before that record was made.
EFFECT_IS_A_RECORD = {"DEVICE_OUTAGE", "PARTIAL_UPLOAD_LOSS", "SCALE_DRIFT", "DECLARED_WEIGHT_WRONG", "MISSORT", "UNRECORDED_HANDOFF",
                      "LABEL_MISREAD", "WRONG_LABEL_APPLIED", "WRONG_GATE", "OTP_NOT_RECEIVED", "NEIGHBOUR_RECEIVES", "MISDELIVERY",
                      "MANIFEST_ERROR", "TRAFFIC_DISRUPTION", "RECIPIENT_UNAVAILABLE", "WRONG_ADDRESS", "ROUTINE_FAILED_ATTEMPT"}
TRUTH_FIELDS = ("knowable_at", "acceptable_causes", "root_cause", "expected_resolution", "mechanism_id", "physically_healthy",
                "shared_evidence_ids", "key_evidence", "secondary_issue", "booking_day", "final_location", "natural_recovery",
                "shares_opening_with", "alternative_mechanisms", "cancelled_by", "overdue_at", "truth_schema", "first_opening",
                "explains_opening", "opening_explained", "exposures")


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
            types = {m["type"] for m in build.truth[sid]["mechanisms"]} | {m["type"] for m in build.truth[sid]["exposures"]}
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
        for start, end, fraction, mid, release in windows:
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


def physical_state_vocabulary(build, live_split="development"):
    """Hygiene only: the physical world state the Stage 4 simulator reads carries no cause codes, mechanism names or
    ids, truth field names or the canary. This proves nothing about content: the state records what physically
    happened, so causes CAN be worked out from it (derivable by design). Its protection is where it lives (outside the
    repository, in the simulator-only root) and who may open it (tests/test_world_build.py checks the code)."""
    from world.export import _jsonable, private_physical
    import json
    substrings, words, causes, actions = vocabulary(build)
    word_re = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b") if words else None
    token_re = re.compile(r"[A-Z][A-Z0-9_]+")
    hits, scanned = defaultdict(int), Counter()
    for name, rows in private_physical(build, live_split).items():
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
    return {"pass": not hits, "records_scanned": dict(sorted(scanned.items())), "hits": dict(sorted(hits.items())),
            "labels_derivable_from_this_state": True,
            "protection": "location (outside the repository, simulator-only root) and access (no runtime module but the Stage 4 "
                          "simulator may open it); this scan is vocabulary hygiene, not an isolation proof"}


def import_cut(build, exports):
    """Nothing recorded after the live start sits in the import. The one documented exception is the booking-time
    context of a live shipment (its order, parcels, address and plan), which the foundation contract imports stamped
    at booking and every reader filters by recorded_at; it is counted, and it must be stamped exactly at booking."""
    r = Report()
    summary = {}
    from world.build import BOOKING_CONTEXT
    for live_split, (imported, items, truth, live_start) in exports.items():
        late, booking = 0, 0
        latest = live_start
        for node in imported.nodes.values():
            p = node.properties
            recorded = instant(p["recorded_at"])
            occurred = instant(p["occurred_at"]) if p.get("occurred_at") else None
            if recorded <= live_start and (occurred is None or occurred <= live_start):
                continue
            owner = p.get("holdout_group")
            live_booking = (owner is not None and p.get("split") == "development" and node.kind in BOOKING_CONTEXT
                            and p["recorded_at"] == imported.nodes[owner].properties["recorded_at"])
            booking += live_booking
            late += not live_booking
            r.check(live_booking, "NOTHING_IMPORTED_FROM_AFTER_THE_LIVE_START", node.id, f"{node.kind} recorded {p['recorded_at']}")
        for edge in imported.edges.values():
            for key in ("valid_from", "valid_to"):
                value = edge.properties.get(key)
                r.check(value is None or instant(value) <= live_start, "NO_IMPORTED_INTERVAL_AFTER_THE_LIVE_START", edge.id, key)
        first = min((instant(i["deliver_at"]) for i in items), default=None)
        r.check(first is None or first > live_start, "FEED_STARTS_AFTER_THE_LIVE_START", live_split)
        summary[live_split] = {"live_start": iso(live_start), "imported_nodes": len(imported.nodes),
                               "imported_after_live_start_other_than_live_booking_context": late,
                               "live_booking_context_records": booking, **getattr(build, "import_reports", {}).get(live_split, {})}
    return r.result(per_export=summary)


def forecasts(build):
    """No record states a future instant that equals what later happened: a carrier's estimated arrival is its own
    estimate, never the simulated arrival. Gating for estimate fields; other future-dated fields are plans and
    validity windows, listed by field for the record."""
    r = Report()
    nodes = build.world.nodes
    arrived = {}
    for node in nodes.values():
        if node.kind == "TripEvent" and node.properties.get("event_type") == "ARRIVED":
            arrived[node.properties["trip_id"]] = node.properties["occurred_at"]
    exact, compared, errors = 0, 0, []
    for node in nodes.values():
        p = node.properties
        if node.kind != "TripEvent" or not p.get("estimated_arrival_at"):
            continue
        actual = arrived.get(p["trip_id"])
        if actual is None or instant(p["occurred_at"]) >= instant(actual):
            continue
        compared += 1
        exact += p["estimated_arrival_at"] == actual
        errors.append(abs((instant(p["estimated_arrival_at"]) - instant(actual)).total_seconds()))
        r.check(p["estimated_arrival_at"] != actual, "ESTIMATE_IS_NOT_THE_LATER_ARRIVAL", node.id)
    held = [n for n in nodes.values() if n.kind == "TripEvent" and n.properties.get("event_type") == "HELD_AT_ORIGIN"]
    departed = {n.properties["trip_id"]: n.properties["occurred_at"] for n in nodes.values()
                if n.kind == "TripEvent" and n.properties.get("event_type") == "DEPARTED"}
    for n in held:
        left = departed.get(n.properties["trip_id"])
        r.check(left is None or n.properties["occurred_at"] < left, "DELAY_NOTICE_BEFORE_DEPARTURE", n.id)
    occurred = defaultdict(set)
    for node in nodes.values():
        if node.properties.get("occurred_at") and node.properties.get("holdout_group"):
            occurred[node.properties["holdout_group"]].add(node.properties["occurred_at"])
    future = Counter()
    for node in nodes.values():
        p = node.properties
        recorded = p.get("recorded_at")
        if not p.get("holdout_group"):
            continue
        for field in UTC_FIELDS & set(p):
            value = p[field]
            if field in ("occurred_at", "recorded_at") or not isinstance(value, str) or value <= recorded:
                continue
            if value in occurred[p.get("holdout_group")]:
                future[f"{node.kind}.{field}"] += 1
    errors.sort()
    return r.result(estimates_compared=compared, estimates_equal_to_arrival=exact, delay_notices=len(held),
                    estimate_error_seconds={"p50": errors[len(errors) // 2] if errors else None, "p90": errors[int(len(errors) * .9)] if errors else None},
                    future_dated_fields_equal_to_a_later_event_of_the_same_owner=dict(sorted(future.items())),
                    note="The fields listed under future_dated_fields are plan and validity fields (a session's end, an "
                         "assignment's window) that coincide with an event stamped at that planned instant; none is an estimate.")


def throughput_separation(build):
    """A backlog must be visible in the facility's own throughput reports: during a backlog that caused something, the
    oldest waiting item is older than in the facility's ordinary hours. Reported per backlog; gating on separation."""
    r = Report()
    rows = defaultdict(list)
    for node in build.world.nodes.values():
        if node.kind == "FacilityThroughput":
            p = node.properties
            rows[p["facility_id"]].append((instant(p["start_at"]), p["oldest_waiting_minutes"], p["processed_count"], p["queue_depth"],
                                           p["staffed_capacity_per_hour"], bool(build.observer.records[node.id]["mech"])))
    utilisation = sorted(processed / max(1.0, staffed) for facility_rows in rows.values() for _, _, processed, _, staffed, _ in facility_rows if processed)
    out = []
    for facility, windows in sorted(build.plan.backlog.items()):
        ordinary = sorted(age for _, age, _, _, _, shaped in rows.get(facility, []) if not shaped)
        p95 = ordinary[int(len(ordinary) * .95)] if ordinary else 0
        for start, end, factor, mid in windows:
            inside = [(age, processed, queue) for at, age, processed, queue, staffed, shaped in rows.get(facility, [])
                      if start - timedelta(hours=1) <= at < end + timedelta(hours=3)]
            worst = max((age for age, _, _ in inside), default=0)
            caused = len(build.caused.get(mid, ()))
            if caused:
                r.check(worst > p95, "BACKLOG_VISIBLE_IN_THROUGHPUT", mid, f"oldest wait {worst} min vs ordinary p95 {p95} min")
            out.append({"facility": facility, "capacity_factor": factor, "caused_shipments": caused, "exposed_shipments": len(build.exposed.get(mid, ())),
                        "oldest_waiting_minutes_max": worst, "ordinary_hours_p95": p95, "ordinary_hours_max": ordinary[-1] if ordinary else 0})
    quant = lambda q: round(utilisation[min(len(utilisation) - 1, int(q * len(utilisation)))], 2) if utilisation else None
    return r.result(backlogs=out, utilisation_of_staffed_capacity_in_working_hours={"hours": len(utilisation), "p50": quant(.5), "p90": quant(.9), "max": quant(1)},
                    ordinary_hours_with_a_queue=sum(1 for facility_rows in rows.values() for _, _, _, queue, _, shaped in facility_rows if queue and not shaped))


def consolidation(build):
    """Reported, not gating: how full containers, trips and routes are at this scale."""
    fills = sorted(len(c.parcels) for c in build.sim.containers.values())
    routes = sorted(len(r.loaded) for r in build.sim.routes.values())
    ran = [t for tid, t in build.sim.trips.items() if t.departed_at and not t.cancelled and t.plan.kind != "FIRST_MILE"]
    return {"containers": len(fills), "containers_with_one_parcel": sum(1 for n in fills if n == 1),
            "median_parcels_per_container": fills[len(fills) // 2] if fills else 0,
            "trips_run_with_containers": len(ran), "scheduled_departures_cancelled_empty": sum(1 for t in build.sim.trips.values() if t.cancelled),
            "route_runs": len(routes), "route_runs_with_one_parcel": sum(1 for n in routes if n <= 1),
            "median_parcels_per_route_run": routes[len(routes) // 2] if routes else 0}


def discrimination(build, truth=None, present=None):
    """Addendum A1: every discrimination spec is machine-checkable against the world's records.

    Record items name an observation that exists (and, for an export's truth, one that export contains); absence
    items name an expectation whose matching records, recomputed by a full scan, are exactly its cancelled_by list
    and empty (the absence is real); every group holds an item of the shipment's own (its record, or an absence about
    its parcel), so nothing is knowable from shared records alone; the estimate equals the spec evaluated at feed
    delivery times and is never before the mechanism started, before the shipment was booked, before its own linking
    record was delivered, or (for a mechanism whose effect is a record of the shipment) before that record was made."""
    from world.monitor import deliver_at
    r = Report()
    nodes = build.world.nodes
    truth = build.truth if truth is None else truth
    records = build.observer.records
    deliver = {nid: deliver_at(nodes[nid]) for nid in records if nid in nodes and nodes[nid].properties.get("recorded_at")}
    by_kind = defaultdict(list)
    for node in nodes.values():
        owner = node.properties.get("holdout_group")
        if present is None or owner is None or owner in present:
            by_kind[node.kind].append(node)
    empty, groups = Counter(), Counter()
    for sid, row in sorted(truth.items()):
        packages = {p.pid for p in build.shipments[sid].parcels}
        booked = instant(row["booked_at"])
        for m in row["mechanisms"]:
            spec = m["discrimination"]
            key = f"{sid}/{m['mechanism_id']}"
            if m["resolution"] != "NONE" and not spec["any_of"]:
                empty[m["type"]] += 1
            for group in spec["any_of"]:
                groups[len(group["all_of"])] += 1
                own = [i for i in group["all_of"] if own_item(i, sid, packages, lambda n: records[n]["sid"] if n in records else None)]
                r.check(bool(own), "EVERY_GROUP_HAS_AN_ITEM_OF_THE_SHIPMENT", key, m["type"])
                for item in group["all_of"]:
                    if "record" in item:
                        node = nodes.get(item["record"])
                        r.check(node is not None and bool(node.properties.get("recorded_at")) and item["record"] in records,
                                "RECORD_ITEM_IS_AN_OBSERVATION", key, item["record"])
                        owner = records[item["record"]]["sid"] if item["record"] in records else None
                        r.check(present is None or owner is None or owner in present, "RECORD_ITEM_IS_IN_THIS_EXPORT", key, item["record"])
                        if owner == sid:
                            r.check(deliver[item["record"]] >= booked, "OWN_RECORD_NOT_BEFORE_BOOKING", key, item["record"])
                    else:
                        absence = item["absence"]
                        found = sorted(n.id for n in by_kind[absence["match"]["kind"]] if match_node(n, absence["match"]))
                        r.check(found == absence["cancelled_by"], "ABSENCE_MATCHES_RECOMPUTED", key, absence["expected"])
                        r.check(not found, "ABSENCE_IS_REAL", key, absence["expected"])
                        if absence["match"].get("package_id") in packages:
                            r.check(instant(absence["overdue_at"]) >= booked, "OWN_ABSENCE_NOT_BEFORE_BOOKING", key, absence["expected"])
            estimate = spec_estimate(spec, deliver)
            r.check((iso(estimate) if estimate else None) == m["knowable_at_estimate"], "ESTIMATE_RECOMPUTES", key)
            if estimate and m["resolution"] != "NONE":
                if m["started_at"]:
                    r.check(estimate >= instant(m["started_at"]), "ESTIMATE_NOT_BEFORE_START", key, m["type"])
                r.check(estimate >= booked, "ESTIMATE_NOT_BEFORE_BOOKING", key, m["type"])
                made = [records[n]["occurred"] for n in m["evidence_ids"] if n in records and records[n]["occurred"] is not None]
                if m["type"] in EFFECT_IS_A_RECORD and made:
                    r.check(estimate >= min(made), "ESTIMATE_NOT_BEFORE_THE_SHIPMENT_WAS_AFFECTED", key, m["type"])
            r.check(row.get("canary") == canary_token(build.config), "CANARY_IN_EVERY_ROW", sid)
        # Scored at the first instant a run starts, with everything imported counted as ingested from its own time:
        # nothing can be identifiable before the shipment exists.
        r.check(labels_at(row, booked - timedelta(seconds=1), {n for n, t in deliver.items() if t < booked}) in ([], ["INSUFFICIENT_EVIDENCE"]),
                "NOTHING_IDENTIFIABLE_BEFORE_BOOKING", sid)
    actionable = sum(1 for row in truth.values() for m in row["mechanisms"] if m["resolution"] != "NONE")
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
ENVELOPE_FIELDS = {"entity_id", "dataset_id", "schema_version", "synthetic", "provenance", "split", "holdout_group", "shipment_id",
                   "recorded_at", "occurred_at"}
# Idempotency-only mechanisms are excluded: a retransmission is directly observable by design and never a case.
TELL_EXCLUDED = {"DUPLICATE_EVENTS"}
CATALOG_LINKED = {"Trip", "Container", "RouteRun", "Device", "Vehicle", "Driver", "Lane", "Branch", "Hub", "SortingCenter",
                  "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse", "Organization", "Provider"}
# From the shared records a shipment references, only their type-like fields count as features.
CATALOG_TYPE_FIELDS = {"trip_type", "container_type", "device_kind", "telemetry_stream", "ownership", "vehicle_class", "employment", "role",
                       "provider_type", "lane_type", "organization_type", "handling", "modes"}
NONE = "<none>"
# A value that predicts one mechanism is a tell unless it IS that mechanism's documented discriminator (truth.DISCRIMINATORS,
# README table): the observation an investigator is meant to find. (mechanism, record kind, field prefix, why).
ACCEPTED_DISCRIMINATORS = (
    ("MANIFEST_ERROR", "Manifest", "package_ids#", "the revised manifest line without the loaded parcel (empty for a one-parcel shipment)"),
    ("MANIFEST_ERROR", "Manifest", "manifest_status", "a revised manifest line is where the dropped parcel shows"),
    ("MANIFEST_ERROR", "Manifest", "version", "a revised manifest line is where the dropped parcel shows"),
    ("MISSORT", "VehicleAssignment", "segment_id", "an assignment to a lane that is not in the journey plan"),
    ("MISSORT", "VehicleAssignment", "mode", "an assignment to a lane that is not in the journey plan"),
    ("NEIGHBOUR_RECEIVES", "HandoffEvidence", "recipient_type", "the handoff names another person with no authorisation on record"),
    ("NEIGHBOUR_RECEIVES", "HandoffEvidence", "authorization_ref", "the handoff names another person with no authorisation on record"),
    ("MISDELIVERY", "HandoffEvidence", "recipient_type", "the proof names an occupant other than the recipient"),
    ("WRONG_LABEL_APPLIED", "ScanEvent", "<barcode>", "a read that returns another parcel's manifest barcode"),
    ("LABEL_MISREAD", "ScanEvent", "<barcode>", "a read one digit off the manifest barcode (it fails the check digit)"),
    ("WRONG_GATE", "DeliveryAttempt", "observed_gate", "the attempt's recorded gate differs from the instruction"),
    ("OTP_NOT_RECEIVED", "CommunicationEvent", "delivery_status", "a failed delivery report for the one-time code"),
    ("DEVICE_OUTAGE", "*", "<lag>", "a record arriving long after it happened is what a device that could not upload looks like"),
    ("PARTIAL_UPLOAD_LOSS", "*", "<lag>", "a record arriving long after it happened is what a device that could not upload looks like"),
    ("OTP_NOT_RECEIVED", "CommunicationEvent", "purpose", "a resent one-time code"),
    ("WRONG_ADDRESS", "AddressVersion", "", "the recipient's dated address correction"),
    ("WRONG_ADDRESS", "LocationPin", "", "the recipient's dated address correction"),
    ("WRONG_ADDRESS", "RecipientReport", "report_code", "the recipient's dated address correction"),
    ("CUSTOMER_COMPLAINT", "RecipientReport", "report_code", "the recipient's own message"),
    ("ROUTINE_FAILED_ATTEMPT", "DeliveryAttempt", "failed_reason", "the failed attempt's own reason (an ordinary failure is what its record says)"),
    ("RETURN_SCAN_SKIPPED", "ScanEvent", "observation_type", "the stock-check scan finding the parcel on the shelf"),
    ("ASSIGNED_NOT_LOADED", "ScanEvent", "observation_type", "the stock-check scan finding the parcel on the shelf"),
)


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


def _bucket(value):
    """Half-decade bucket of a magnitude: 3 kg and 4 kg share one, 3 kg and 30 kg do not."""
    if value == 0:
        return "0"
    return f"~1e{math.floor(math.log10(abs(value)) * 2) / 2:g}"


def _lag(seconds):
    for limit, name in ((60, "<1m"), (300, "<5m"), (900, "<15m"), (3600, "<1h"), (3 * 3600, "<3h"), (10 * 3600, "<10h")):
        if seconds < limit:
            return name
    return ">=10h"


def features(world, sid_nodes, barcodes=frozenset()):
    """Single-record observables of one shipment: categorical values, absent values, list lengths, bucketed numbers,
    how late each record arrived, how far a read barcode or a weighing is from the declaration, and pairs of one
    value with one absent field in the same record."""
    out = set()
    linked = set()
    packages = {n.id: n.properties for n in sid_nodes if n.kind == "Package"}
    for node in sid_nodes:
        p = node.properties
        values, absent = [], []
        for field, value in p.items():
            if field in ENVELOPE_FIELDS:
                continue
            if value is None:
                out.add((node.kind, field, NONE))
                absent.append(field)
                continue
            if isinstance(value, list):
                out.add((node.kind, field + "#", len(value)))
            for v in (value if isinstance(value, list) else [value]):
                if isinstance(v, str) and v.startswith("DEMO-") and v in world.nodes and world.nodes[v].kind in CATALOG_LINKED:
                    linked.add(v)
                elif _categorical(field, v):
                    out.add((node.kind, field, v))
                    if isinstance(v, str):
                        values.append((field, v))
                elif isinstance(v, (int, float)) and not isinstance(v, bool) and field not in ("lat", "lng") and field not in SKIP_FIELDS:
                    out.add((node.kind, field + "~", _bucket(v)))
        for field, v in values:
            for other in absent:
                out.add((node.kind, f"{field}={v} & {other}", NONE))
        if p.get("occurred_at") and p.get("recorded_at"):
            out.add((node.kind, "<lag>", _lag((instant(p["recorded_at"]) - instant(p["occurred_at"])).total_seconds())))
        package = packages.get(p.get("package_id"))
        if node.kind == "ScanEvent" and package:
            read = p.get("observed_barcode")
            if read:
                expected = package.get("manifest_barcode") or ""
                differs = sum(1 for x, y in zip(read, expected) if x != y) + abs(len(read) - len(expected))
                out.add((node.kind, "<barcode>", "another parcel's" if read != expected and read in barcodes else
                         "same" if differs == 0 else "1 off" if differs == 1 else "2-4 off" if differs <= 4 else "5+ off"))
            if p.get("measured_weight_kg") is not None and package.get("weight_kg"):
                off = abs(p["measured_weight_kg"] - package["weight_kg"]) / package["weight_kg"]
                out.add((node.kind, "<weight>", "<10%" if off < .1 else "10-20%" if off < .2 else "20-35%" if off < .35 else ">=35%"))
    for ref in linked:
        node = world.nodes[ref]
        for field, value in node.properties.items():
            if field not in CATALOG_TYPE_FIELDS:
                continue   # A shared resource's own attributes (a route's stop count, a hub's capacity) identify the resource, not a cause.
            for v in (value if isinstance(value, list) else [value]):
                if _categorical(field, v):
                    out.add((node.kind, field, v))
    return out


def _accepted(mechanism, feature):
    kind, field = feature[0], str(feature[1])
    return next((why for m, k, prefix, why in ACCEPTED_DISCRIMINATORS
                 if m == mechanism and k in (kind, "*") and (field.startswith(prefix) or prefix in field)), None)


def tells(build, *, rare=.20, precision=.90, support=5):
    world = build.world
    owned = defaultdict(list)
    barcodes = set()
    for node in world.nodes.values():
        sid = node.properties.get("holdout_group")
        if sid:
            owned[sid].append(node)
        if node.kind == "Package":
            barcodes.add(node.properties["manifest_barcode"])
    feats = {sid: features(world, nodes, barcodes) for sid, nodes in owned.items()}
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
        found, near, accepted = [], [], []
        for f, sids in holders.items():
            if len(sids) > rare * n:
                continue
            for mtype, msids in mech.items():
                hit = len(sids & msids)
                if hit >= support:
                    share = hit / len(sids)
                    row = {"feature": list(map(str, f)), "mechanism": mtype, "support": hit, "precision": round(share, 3), "holders": len(sids)}
                    why = _accepted(mtype, f)
                    if share >= precision and why:
                        accepted.append({**row, "documented_discriminator": why})
                    elif share >= precision:
                        found.append(row)
                    elif share >= .7 and not why:
                        near.append(row)
        order = lambda r: (-r["precision"], r["mechanism"], r["feature"])
        results[label] = {"population": n, "features": len(holders), "tells": sorted(found, key=order),
                          "documented_discriminators_found": sorted(accepted, key=order),
                          "near_misses_precision_0.7_to_0.9": sorted(near, key=order)[:25]}
    return {"pass": not any(v["tells"] for v in results.values()),
            "rule": f"a single-record observable (value, absent value, list length, bucketed number, arrival lag, barcode or weight "
                    f"gap, value-with-absent-field pair) held by <= {rare:.0%} of shipments with precision >= {precision} and "
                    f"support >= {support} for one mechanism is a tell, unless it is that mechanism's documented discriminator",
            "excluded_mechanisms": sorted(TELL_EXCLUDED), "skipped_fields": sorted(SKIP_FIELDS),
            "referenced_catalog_fields": sorted(CATALOG_TYPE_FIELDS), **results}


# ---------------------------------------------------------------------- monitor replay
def scheduled_fault(row):
    """A shipment carries a scenario-weighted fault (as opposed to none, or only ordinary causes)."""
    return any(m["origin"] == "scheduled" and m["resolution"] != "NONE" for m in row["mechanisms"])


def monitor_replay(build, imported, items, truth, live_start):
    """Hourly ticks from the live start, 900 s allowance, over the live shipments of this export."""
    full = reconstitute(imported, items)
    live = sorted(sid for sid, n in imported.nodes.items() if n.kind == "Shipment" and n.properties["split"] == "development")
    fed = {i["source_event_id"] for i in items}
    replica = Replica(full, live_start, evidence_ids=fed, gateway_lag=False)
    end = build.config.end_at
    # The scorer's ingestion log is time-aware: an imported record counts from its own recorded_at (a live shipment's
    # booking context is imported stamped at booking), a fed record from the first hourly tick at or after its delivery.
    stamped = sorted((instant(n.properties["recorded_at"]), nid) for nid, n in imported.nodes.items())
    by_tick = sorted((tick, nid) for nid, tick in replica.visible.items())

    def ingested(t):
        return {nid for at, nid in stamped if at <= t} | {nid for tick, nid in by_tick if tick <= t}
    everything = ingested(end)
    rows = {}
    for sid in live:
        timeline = replica.timeline(sid, end)
        opening = next(((t, c, s) for t, c, s in timeline if c), None)
        row = truth[sid]
        later = sorted({sym for t, c, s in timeline for sym in s} - set(opening[2] if opening else []))
        actionable = [m for m in row["mechanisms"] if m["resolution"] != "NONE"]
        explaining = [m for m in actionable if set(RULE_CODES[m["type"]]) & set(opening[1])] if opening else []
        rows[sid] = {"healthy": row["healthy"], "scheduled_fault": scheduled_fault(row), "mechanisms": sorted({m["type"] for m in actionable}),
                     "explaining_mechanisms": sorted({m["type"] for m in explaining}),
                     "exposures": sorted({m["type"] for m in row["exposures"]}),
                     "opened_at": iso(opening[0]) if opening else None, "opening_symptoms": opening[2] if opening else [],
                     "opening_codes": opening[1] if opening else [], "later_symptoms": later,
                     "acceptable_causes_at_opening": sorted({c for m in (explaining or actionable) for c in m["acceptable_causes"]}) if opening else None,
                     "ambiguous": any(m["discrimination"]["shares_opening_with"] for m in explaining),
                     "labels_at_opening": labels_at(row, opening[0], ingested(opening[0])) if opening else None,
                     "labels_at_end": labels_at(row, end, everything),
                     "labels_before_booking": labels_at(row, instant(row["booked_at"]) - timedelta(seconds=1),
                                                        ingested(instant(row["booked_at"]) - timedelta(seconds=1)))}
    healthy = [r for r in rows.values() if r["healthy"]]
    abnormal = [r for r in rows.values() if not r["healthy"]]
    fault_free = [r for r in rows.values() if not r["scheduled_fault"]]
    per_mech = defaultdict(lambda: {"caused_shipments": 0, "opened": 0, "opened_and_explaining": 0, "clean_cases": 0, "opening_symptoms": Counter()})
    for r in abnormal:
        for m in r["mechanisms"]:
            per_mech[m]["caused_shipments"] += 1
            if r["opened_at"]:
                per_mech[m]["opened"] += 1
                if m in r["explaining_mechanisms"]:
                    per_mech[m]["opened_and_explaining"] += 1
                    per_mech[m]["opening_symptoms"][" + ".join(r["opening_symptoms"])] += 1
                    # A clean case: the monitor opened it and this is the shipment's only cause.
                    per_mech[m]["clean_cases"] += len(r["mechanisms"]) == 1
    by_set = defaultdict(lambda: {"shipments": 0, "healthy": 0, "without_scheduled_fault": 0, "unexplained": 0, "mechanisms": Counter(),
                                  "single_mechanism_shipments": Counter()})
    for r in rows.values():
        if not r["opened_at"]:
            continue
        key = " + ".join(r["opening_symptoms"])
        by_set[key]["shipments"] += 1
        by_set[key]["healthy"] += r["healthy"]
        by_set[key]["without_scheduled_fault"] += not r["scheduled_fault"]
        by_set[key]["unexplained"] += not r["healthy"] and not r["explaining_mechanisms"]
        for m in r["explaining_mechanisms"]:
            by_set[key]["mechanisms"][m] += 1
        if len(r["mechanisms"]) == 1 and r["explaining_mechanisms"]:
            by_set[key]["single_mechanism_shipments"][r["mechanisms"][0]] += 1
    insufficient = sum(1 for r in rows.values() if r["opened_at"] and r["labels_at_opening"] == ["INSUFFICIENT_EVIDENCE"])
    opened_abnormal = [r for r in abnormal if r["opened_at"]]
    ambiguous = [r for r in opened_abnormal if r["ambiguous"]]
    identifiable = [r for r in ambiguous if r["labels_at_end"] != ["INSUFFICIENT_EVIDENCE"]]
    at_opening = [r for r in identifiable if r["labels_at_opening"] != ["INSUFFICIENT_EVIDENCE"]]
    early = sum(1 for r in rows.values() if r["labels_before_booking"] not in ([], ["INSUFFICIENT_EVIDENCE"]))
    return {"tick_origin": iso(live_start), "tick_seconds": 3600, "detection_allowance_seconds": 900, "live_shipments": len(rows),
            "pass": early == 0, "shipments_with_a_cause_identifiable_before_booking": early,
            "healthy": {"shipments": len(healthy), "opened": sum(bool(r["opened_at"]) for r in healthy),
                        "false_positive_rate": round(sum(bool(r["opened_at"]) for r in healthy) / max(1, len(healthy)), 3),
                        "opening_symptoms": dict(Counter(" + ".join(r["opening_symptoms"]) for r in healthy if r["opened_at"]))},
            "without_scheduled_fault": {"shipments": len(fault_free), "opened": sum(bool(r["opened_at"]) for r in fault_free),
                                        "with_an_ordinary_cause": sum(not r["healthy"] for r in fault_free),
                                        "opening_symptoms": dict(Counter(" + ".join(r["opening_symptoms"]) for r in fault_free if r["opened_at"]))},
            "abnormal": {"shipments": len(abnormal), "opened": sum(bool(r["opened_at"]) for r in abnormal),
                         "not_opened": sum(not r["opened_at"] for r in abnormal),
                         "opened_with_no_explaining_cause": sum(1 for r in opened_abnormal if not r["explaining_mechanisms"]),
                         "multi_cause": sum(len(r["mechanisms"]) >= 2 for r in abnormal),
                         "opened_before_any_cause_knowable": insufficient,
                         "identifiable_at_opening": sum(r["labels_at_opening"] != ["INSUFFICIENT_EVIDENCE"] for r in opened_abnormal),
                         "identifiable_by_horizon_end": sum(r["labels_at_end"] != ["INSUFFICIENT_EVIDENCE"] for r in opened_abnormal),
                         "acceptable_cause_codes_per_opened_case": dict(sorted(Counter(len(r["acceptable_causes_at_opening"]) for r in opened_abnormal).items()))},
            "ambiguity": {"rule": "an opened abnormal case is ambiguous when a mechanism that explains its opening shares that opening "
                                  "symptom set with another cause (truth shares_opening_with); identifiable when "
                                  "labels_at(row, t, ingested) names a cause",
                          "opened_abnormal": len(opened_abnormal), "ambiguous": len(ambiguous),
                          "identifiable_ambiguous": len(identifiable), "identifiable_ambiguous_at_opening": len(at_opening),
                          "identifiable_ambiguous_only_after_opening": len(identifiable) - len(at_opening),
                          "unidentifiable_ambiguous": len(ambiguous) - len(identifiable)},
            "per_mechanism": {m: {**{k: v[k] for k in ("caused_shipments", "opened", "opened_and_explaining", "clean_cases")},
                                  "opening_symptoms": dict(v["opening_symptoms"].most_common())} for m, v in sorted(per_mech.items())},
            "per_opening_symptom_set": {k: {"shipments": v["shipments"], "healthy_shipments": v["healthy"],
                                            "shipments_without_scheduled_fault": v["without_scheduled_fault"],
                                            "abnormal_unexplained": v["unexplained"],
                                            "distinct_mechanisms": len(v["mechanisms"]), "mechanisms": dict(v["mechanisms"].most_common()),
                                            "distinct_mechanisms_single_cause": len(v["single_mechanism_shipments"]),
                                            "single_cause_mechanisms": dict(v["single_mechanism_shipments"].most_common())}
                                        for k, v in sorted(by_set.items(), key=lambda kv: -kv[1]["shipments"])},
            "shipments": rows}


# ---------------------------------------------------------------------- coverage and counts
CLEAN_CASE_FLOOR = 10
# Case families (mission, section 12; docs/plans/2026-10-10_stage1_world.md) by causing mechanism. A also needs the
# case to open as "out for delivery overnight" (SESSION_END_UNRECONCILED); F is any multi-cause case; G is healthy.
FAMILIES = {"A": ("DEVICE_OUTAGE", "ASSIGNED_NOT_LOADED", "DELIVERY_SCAN_SKIPPED", "RETURN_SCAN_SKIPPED", "CONTRACTOR_RETAINS", "TRAFFIC_DISRUPTION"),
            "B": ("DEVICE_OUTAGE", "PARTIAL_UPLOAD_LOSS"),
            "C": ("PARTIAL_UPLOAD_LOSS", "SCAN_SKIPPED_AT_RECEIPT", "FACILITY_BACKLOG", "LATE_LINEHAUL", "ASSIGNED_NOT_LOADED",
                  "RETURN_SCAN_SKIPPED", "CONTRACTOR_RETAINS", "UNRECORDED_HANDOFF", "MANIFEST_ERROR"),
            "D": ("MISSORT",), "E": ("OTP_NOT_RECEIVED", "NEIGHBOUR_RECEIVES", "MISDELIVERY"),
            "H": ("RECIPIENT_UNAVAILABLE", "WRONG_ADDRESS", "WRONG_GATE", "OTP_NOT_RECEIVED", "CUSTOMER_COMPLAINT")}


def coverage(build):
    """Causes, not touches. Per mechanism: shipments it caused a deviation on, by split; in development, the cases the
    monitor opened that it explains, and the CLEAN cases among them (it is the shipment's only cause). The committed
    rate's target is gating (it scales with the world); the floor of CLEAN_CASE_FLOOR clean development cases per
    mechanism and per family is reported with the world size it needs, because it cannot be met by density."""
    truth = build.truth
    caused = defaultdict(Counter)
    dev = defaultdict(lambda: Counter())
    family = defaultdict(lambda: Counter())
    for sid, r in truth.items():
        actionable = [m for m in r["mechanisms"] if m["resolution"] != "NONE"]
        types = sorted({m["type"] for m in actionable})
        for m in {m["type"] for m in r["mechanisms"]}:
            caused[m][r["split"]] += 1
        if r["split"] != "development":
            continue
        opening = r["first_opening"]
        explaining = sorted({m["type"] for m in actionable if m["explains_opening"]})
        for m in types:
            dev[m]["caused"] += 1
            dev[m]["single_cause"] += len(types) == 1
            if opening and m in explaining:
                dev[m]["opened_and_explaining"] += 1
                dev[m]["clean"] += len(types) == 1
        if r["healthy"]:
            family["G"]["shipments"] += 1
            family["G"]["opened"] += bool(opening)
        elif opening and len(types) >= 2:
            family["F"]["opened"] += 1
        if opening and len(types) == 1 and explaining:
            for name, members in FAMILIES.items():
                if types[0] in members and (name != "A" or "SESSION_END_UNRECONCILED" in opening["symptoms"]):
                    family[name]["clean"] += 1
                    family[name][types[0]] += 1
    sizes = Counter(r["split"] for r in truth.values())
    targets = {m: build.config.target(m, "development", sizes["development"]) for m, _, _ in build.config.rates}
    # The brief's floor (10 caused shipments in development) for the full configuration; a smaller world uses its
    # committed-rate target.
    required = {m: min(10, t) for m, t in targets.items()}
    below = {m: dev[m]["caused"] for m in required if dev[m]["caused"] < required[m]}
    clean = {m: dev[m]["clean"] for m in sorted(required)}
    # Clean cases per caused shipment, as measured here: the development size that would reach the floor at these rates.
    worst = min(clean.values()) if clean else 0
    needed = {m: None if not clean[m] else math.ceil(sizes["development"] * CLEAN_CASE_FLOOR / clean[m]) for m in clean}
    multi = Counter(r["split"] for r in truth.values() if len({m["type"] for m in r["mechanisms"] if m["resolution"] != "NONE"}) >= 2)
    abnormal = Counter(r["split"] for r in truth.values() if not r["healthy"])
    faulty = Counter(r["split"] for r in truth.values() if scheduled_fault(r))
    return {"pass": not below, "counted": "shipments on which the mechanism caused a deviation (touches without consequence are exposures)",
            "minimum_required_in_development": min(required.values()), "development_targets": targets, "below_minimum": below,
            "caused_shipments": {m: dict(caused[m]) for m in sorted(caused)},
            "development": {m: dict(dev[m]) for m in sorted(dev)},
            "clean_case_floor": {"floor": CLEAN_CASE_FLOOR, "definition": "development cases the monitor opened whose only cause is the mechanism",
                                 "clean_cases_per_mechanism": clean, "met": bool(clean) and worst >= CLEAN_CASE_FLOOR,
                                 "mechanisms_below_floor": sorted(m for m, n in clean.items() if n < CLEAN_CASE_FLOOR),
                                 "gates_export": False,
                                 "why_not_gating": "At the committed rates a development split of this size holds fewer caused shipments per "
                                                   "mechanism than the floor, so the floor needs more shipment-days, not more faults per shipment.",
                                 "development_shipments_needed_at_these_rates": needed,
                                 "per_family": {name: dict(v) for name, v in sorted(family.items())}},
            "shares": {split: {"shipments": sizes[split], "abnormal": abnormal[split], "with_a_scheduled_fault": faulty[split],
                               "multi_cause": multi[split], "abnormal_share": round(abnormal[split] / max(1, sizes[split]), 3),
                               "scheduled_fault_share": round(faulty[split] / max(1, sizes[split]), 3)} for split in sorted(sizes)},
            "multi_cause_shipments": dict(multi)}


def run_all(build, exports):
    """exports: {live_split: (imported, items, truth, live_start)}"""
    report = {"physics": physics(build), "observation": None, "coverage": coverage(build), "tells": tells(build),
              "discrimination": discrimination(build), "import_cut": import_cut(build, exports), "forecasts": forecasts(build),
              "throughput_separation": throughput_separation(build), "consolidation": consolidation(build),
              "precedent_cutoff": precedent_cutoff(build, exports), "exports": {}}
    for live_split, (imported, items, truth, live_start) in exports.items():
        found = foundation(build, imported, items)
        raw = found.pop("raw")
        present = {sid for sid in truth}
        report["exports"][live_split] = {"foundation": found, "foundation_raw": raw, "isolation": isolation(build, imported, items),
                                         "discrimination": discrimination(build, truth, present),
                                         "physical_state_vocabulary": physical_state_vocabulary(build, live_split)}
        if report["observation"] is None:
            report["observation"] = observation(build, items)
    report["pass"] = all(report[name]["pass"] for name in ("physics", "observation", "coverage", "tells", "discrimination", "import_cut",
                                                           "forecasts", "throughput_separation", "precedent_cutoff")) and all(
        e["foundation"]["pass"] and e["isolation"]["pass"] and e["discrimination"]["pass"] and e["physical_state_vocabulary"]["pass"]
        for e in report["exports"].values())
    return report


# ---------------------------------------------------------------------- pre-run tell test (addendum B3)
OPENING_SKIP_FIELDS = {"entity_id", "dataset_id", "schema_version", "synthetic", "split", "holdout_group", "shipment_id"}


def opening_cases(build, split="development"):
    """Opening case data of every abnormal shipment of a split that the monitor opened: the opening symptom set,
    the rule codes, every visible property value of the shipment's evidence at the opening tick, the cause codes of
    the mechanisms that explain the opening (the training label) and the cause codes the truth accepts for the case
    (what a prediction is scored against, as in an evaluation run). Time fields are left out (unique per record).

    `features` leaves out the records the explaining mechanisms themselves shaped or that their discrimination specs
    cite (the documented discriminating evidence: the failed attempt and its calls, the handoff naming another person,
    the buffered record): reading that evidence is the investigator's task, not a tell. A tell is a value OUTSIDE it
    that still predicts the cause. `features_with_evidence` keeps everything, for the literal variant of the test."""
    replica = build.replica
    out = {}
    for sid, opening in sorted(build.first_opening.items()):
        row = build.truth[sid]
        if row["split"] != split or row["healthy"]:
            continue
        tick = instant(opening["at"])
        actionable = [m for m in row["mechanisms"] if m["resolution"] != "NONE"]
        explaining = [m for m in actionable if m["explains_opening"]] or actionable
        evidence = {n for m in explaining for n in m["evidence_ids"]} | {i["record"] for m in explaining for g in m["discrimination"]["any_of"]
                                                                         for i in g["all_of"] if "record" in i}
        features, everything = set(), set()
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
                            everything.add(f"{node.kind}.{field}={v}")
                            if node.id not in evidence:
                                features.add(f"{node.kind}.{field}={v}")
        out[sid] = {"symptoms": " + ".join(opening["symptoms"]), "codes": by_specificity(opening["codes"]),
                    "features": features, "features_with_evidence": everything, "causes": sorted({m["cause_code"] for m in explaining}),
                    "acceptable": sorted({c for m in explaining for c in m["acceptable_causes"]}),
                    # Ambiguous: the opening symptom set is shared with another cause. Whether the truth's own
                    # discriminating evidence had arrived by the opening splits the stratum for the report.
                    "ambiguous": any(m["discrimination"]["shares_opening_with"] for m in explaining),
                    "identifiable_at_opening": labels_at_estimate(row, tick) != ["INSUFFICIENT_EVIDENCE"]}
    return out


def tell_test(train, test, *, support=5):
    """Pre-run tell test of two built worlds (addendum B3), in both directions.

    Forward is the addendum's test: train on this world's development opening cases, evaluate on the other seed's.
    Reverse swaps the roles. The gate pools the two (lookup correct in both must not exceed baseline correct in both):
    one direction alone is about eighty non-independent cases and its sign flips with any change of seed, in either
    direction; both directions are reported so the forward result can be read on its own."""
    train_cases, test_cases = opening_cases(train), opening_cases(test)
    result = tell_test_cases(train_cases, test_cases, support=support)
    reverse = tell_test_cases(test_cases, train_cases, support=support)
    keys = ("cases", "baseline_correct", "lookup_correct", "single_code_baseline_correct")

    def literal(cases):
        return {k: {**c, "features": c["features_with_evidence"]} for k, c in cases.items()}
    # The literal variant (every visible value, the mechanism's own evidence included), both directions, reported.
    lit_forward = tell_test_cases(literal(train_cases), literal(test_cases), support=support, diagnostics=False)["ambiguous"]
    lit_reverse = tell_test_cases(literal(test_cases), literal(train_cases), support=support, diagnostics=False)["ambiguous"]
    result["with_the_mechanisms_own_evidence_as_features"] = {
        "note": "Not the gate: here the lookup also reads the records the cause itself shaped (the documented discriminators).",
        "forward": {**{k: lit_forward[k] for k in keys}, "features_behind_lookup_wins": lit_forward["discordant"]["features_behind_lookup_wins"]},
        "reverse": {**{k: lit_reverse[k] for k in keys}, "features_behind_lookup_wins": lit_reverse["discordant"]["features_behind_lookup_wins"]},
        "lookup_beats_baseline_pooled": lit_forward["lookup_correct"] + lit_reverse["lookup_correct"] > lit_forward["baseline_correct"] + lit_reverse["baseline_correct"]}
    forward = {k: result["ambiguous"][k] for k in keys}
    backward = {k: reverse["ambiguous"][k] for k in keys}
    pooled = {k: forward[k] + backward[k] for k in keys}
    result["forward_pass"] = result.pop("pass")
    result["reverse_direction"] = {"pass": reverse["pass"], **{name: {**{k: reverse[name][k] for k in keys}, "discordant": reverse[name]["discordant"]}
                                                                 for name in ("ambiguous", "ambiguous_not_identifiable_at_opening",
                                                                              "ambiguous_identifiable_at_opening", "all_opened_abnormal")},
                                   "without_identifier_values": reverse["diagnostic_without_identifier_values"]}
    result["pooled_ambiguous"] = pooled
    result["pass"] = pooled["lookup_correct"] <= pooled["baseline_correct"]
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
    A prediction is correct when the truth accepts it for the case (acceptable causes of the mechanisms that explain
    the opening), exactly as an evaluation run is scored."""
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

    def right_for(case, cause):
        return cause in case.get("acceptable", case["causes"])

    strata = {"ambiguous": [c for c in test_cases.values() if c["ambiguous"]],
              # Reported, not the criterion: the ambiguous stratum split by whether the discriminating evidence of the
              # truth's spec had arrived by the opening (where it had, reading it is the task; where it had not, a
              # lookup can still use the stage the shipment had reached, which rule codes do not carry).
              "ambiguous_not_identifiable_at_opening": [c for c in test_cases.values() if c["ambiguous"] and not c.get("identifiable_at_opening", True)],
              "ambiguous_identifiable_at_opening": [c for c in test_cases.values() if c["ambiguous"] and c.get("identifiable_at_opening", True)],
              "all_opened_abnormal": list(test_cases.values())}
    results = {}
    for name, cases in strata.items():
        base_hits = sum(right_for(c, baseline(c)) for c in cases)
        single_hits = sum(right_for(c, single_code(c)) for c in cases)
        decisions = [lookup(c) for c in cases]
        look_hits = sum(right_for(c, cause) for c, (cause, _) in zip(cases, decisions))
        used = Counter(feature for _, feature in decisions if feature)
        wins, losses = Counter(), Counter()
        for c, (cause, feature) in zip(cases, decisions):
            right, base_right = right_for(c, cause), right_for(c, baseline(c))
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
            "rule": "lookup classifier on opening data (symptom set + every visible property value outside the records the cause "
                    "itself shaped) must not beat the rule-code baseline (rule codes at opening, most specific first) on the "
                    "ambiguous stratum of another seed's world, pooled over both directions. Ambiguous: the opening symptom set "
                    "is shared with another cause.",
            "train_cases": len(train_cases), "test_cases": len(test_cases), "min_support": support, **results}
    if diagnostics:
        # Diagnostic only (not the criterion): the same test without values that are resource identifiers (DEMO-...).
        def strip(cases):
            return {k: {**c, "features": {f for f in c["features"] if not f.split("=", 1)[1].startswith("DEMO-")}} for k, c in cases.items()}
        plain = tell_test_cases(strip(train_cases), strip(test_cases), support=support, diagnostics=False)
        out["diagnostic_without_identifier_values"] = {k: plain["ambiguous"][k] for k in ("cases", "baseline_correct", "lookup_correct")}
    return out
