"""Investigation tools: bounded, read-only, time-correct views of a shipment's evidence and of the shared
devices, route runs, containers, trips and facilities it touched.

The investigator agent chooses which tool to call and with which arguments. Every tool reads only what Suhail
had recorded by the investigation's as-of time (the evidence snapshot), only in this case's dataset (its live
and history shipments and shared records, never a held-out split), through fixed parameterised queries. Tools
compute facts (comparisons, chronologies, lags, counts); they never return a diagnosis or a cause code. Where
there is no evidence a tool says so explicitly (UNKNOWN / NO_EVIDENCE) instead of filling a gap. Truth, gold
and scenario data are not reachable from here.

Every returned fact carries the ids of the records it came from. A comparison or count a tool computed gets a
stable id of its own (DEMO-CMP-...), recorded for the run, so the investigator can cite it and the reviewer
reads exactly what the investigator saw. Long results keep the rows that deviate and leave out routine ones;
the ids of rows that were left out are never listed as citable.
"""
from datetime import timedelta
import json

from dataset_v2.contracts import digest, instant
from dataset_v2.derive import custody_corroborated, number, point_distance_m, proof_assessment
from operations.reasoning import evidence_world

MAX_ROWS = 30
MAX_RESULT_CHARS = 6000
MAX_CITABLE_IDS = 120
# A record that reached Suhail this long after it happened is a late upload (ordinary uploads take seconds to minutes).
LATE_UPLOAD_SECONDS = 3600
# The monitor waits this long past a deadline before it calls an expected observation missing (store.DETECTION_ALLOWANCE_SECONDS).
OVERDUE_ALLOWANCE_SECONDS = 900
FACILITY_KINDS = ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse")
ENVELOPE = frozenset(("dataset_id", "schema_version", "synthetic", "provenance", "split", "holdout_group", "source_ref", "raw_payload_hash",
                      "feed_id", "feed_origin", "ingested_at", "ingest_lag_seconds"))
CROSS_SHIPMENT_TOOLS = ("same_device_activity", "same_route_run", "container_and_trip", "facility_window")
NO_PORT = "UNKNOWN: evidence beyond this shipment's own records is not available in this deployment."
TELEMETRY_SEMANTICS = ("REPORTING: heartbeats keep arriving. SILENT: heartbeats stopped before the window's end with no log-out, at hours "
                       "when this device was reporting on previous days. QUIET_AS_ON_PREVIOUS_DAYS: it stopped without a log-out at about "
                       "the time it also stopped on previous days (a device that is switched off outside working hours). LOGGED_OUT: the "
                       "last heartbeat is a log-out. NO_HEARTBEATS_IN_WINDOW: a telemetry stream exists but sent nothing in this window (a "
                       "driver app reports only while logged in). NO_TELEMETRY_STREAM: this device class sends no heartbeats, so silence "
                       "cannot be judged. NO_TELEMETRY: no heartbeat on record and no declared stream. Records a silent device made are "
                       "not visible until it uploads them; a heartbeat gap alone does not show that records were held back.")
BASELINE_HOURS = 50   # Heartbeats this far back show whether a device usually stops at this time of day.


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _when(value):
    """An instant from a stored value (string or datetime), or None."""
    try:
        return instant(_iso(value)) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def _lag_minutes(p):
    recorded, occurred = _when(p.get("recorded_at")), _when(p.get("occurred_at"))
    return round((recorded - occurred).total_seconds() / 60) if recorded and occurred else None


def _minutes(later, earlier):
    return round((later - earlier).total_seconds() / 60) if later and earlier else None


def _public(props):
    return {k: _iso(v) for k, v in props.items() if k not in ENVELOPE and v is not None}


class InvestigationTools:
    """One investigation's tool belt, kept across review rounds.

    retrieved  every evidence id a tool listed as citable
    index      id -> {kind, scope, recorded_at, occurred_at} for every such id (citation validity is checked against it)
    external   citable records that are not this shipment's own evidence nodes: shared and other shipments' records,
               device telemetry, verified precedents and tool-computed results
    computed   tool-computed comparisons and counts by their stable id
    calls      every call: round, tool, arguments, evidence ids and computed-result ids returned
    """

    def __init__(self, context, config, *, symptoms=(), heartbeats=None, precedents=None, port=None, disabled=()):
        self.context, self.config = context, config
        self.sid, self.as_of = context["shipment_id"], context["as_of"]
        self.world = evidence_world(context, config)
        self.nodes = self.world.nodes
        self.cutoff = instant(self.as_of)
        self.symptoms = list(symptoms)
        self._heartbeats = heartbeats or (lambda device_id, since, until: [])
        self._precedent_source = precedents or (lambda cause: [])
        self.port = port                 # fetch(name, **params): the fixed cross-shipment queries, or None
        self.disabled = frozenset(disabled)
        self.retrieved = set()
        self.calls = []
        self.external = {}
        self.index = {}
        self.computed = {}
        self.device_reports = {}         # last telemetry report per device
        self.round = 0
        self._tool = None
        self._cache = {}

    # ------------------------------------------------------------------ catalogue
    CATALOG = {
        "shipment_overview": ({}, "Start here. Service, promise, packages, status history, case symptoms, and the ids of the devices, "
                                  "route runs, trips, containers and facilities this shipment's records name (arguments for the other tools)."),
        "journey": ({"package_id": "optional"}, "Expected milestones vs corroborated observations (on time, late, missing after deadline, pending). "
                                                "Next to each missing or late milestone: the telemetry state of the device expected to record it."),
        "custody_chain": ({"package_id": "required"}, "Ordered custody transfers with holders, acknowledgments, source scan and device, event and upload times; "
                                                      "the last corroborated holder; the delivery session's end and its reconciliation state."),
        "scans": ({"package_id": "optional"}, "Barcode reads and calibrated weighings compared with the manifest barcode, declared weight and policy "
                                              "tolerance (each comparison is citable); whose label a differing barcode is."),
        "delivery_attempts": ({}, "Attempts (route run, driver, vehicle, reason, gate), calls, proof-of-delivery components with their "
                                  "corroboration checks and reasons, who took the parcel, recipient reports, depot reconciliations."),
        "vehicle_and_manifest": ({}, "Planned assignments (driver, employment, provider, vehicle, ownership, route run or trip), dispatch manifest "
                                     "versions compared with confirmed loading, vehicle positions (vehicle position only)."),
        "device_status": ({"device_id": "required", "hours": "optional, default 24"}, "One device's heartbeats recorded by now: reporting state, last seen, gaps, pending uploads."),
        "same_device_activity": ({"device_id": "required", "hours": "optional, default 12", "end_at": "optional UTC time, default now"},
                                 "Everything one device did in a window, across shipments: heartbeats and gaps, pending uploads, how many of its "
                                 "records arrived late, how its reads and weighings compare with declarations, and other shipments whose expected "
                                 "observation at it or its facility is overdue."),
        "same_route_run": ({"route_run_id": "required"}, "The other parcels on a delivery route run and their outcomes so far (delivered with proof, "
                                                        "failed, returned, no outcome), load confirmations, the driver app's reporting state, manifest versions."),
        "container_and_trip": ({"container_id": "one of the two", "trip_id": "one of the two"},
                               "A container: its other parcels and where each was last recorded. A trip: schedule, carrier status messages, "
                               "vehicle positions summary, containers and parcels on it and whether they were received."),
        "facility_window": ({"facility_id": "required", "hours": "optional, default 12", "end_at": "optional UTC time, default now"},
                            "A facility over a window: hourly throughput (processed, queue, staffed capacity, oldest wait), parcels handled, "
                            "how many shipments are overdue to be received or to leave there, its devices' reporting state."),
        "communications": ({}, "Messages to the recipient with delivery status and times (one-time-code messages show status only, never a code), "
                               "calls, recipient reports and address corrections, and how other messages on the same carrier route fared."),
        "route_conditions": ({"hours": "optional, default 48"}, "Traffic incidents reported for the destination city and how far each is from the "
                                                                "delivery address; planned route segments; stops not attempted."),
        "address_and_instructions": ({}, "Address versions with validity intervals and coordinates, delivery instructions and gate, recipient pins, "
                                         "and each attempt's recorded gate compared with the instruction."),
        "policy": ({}, "Policy thresholds (barcode confidence, weight tolerance, retry limit) and service tolerance."),
        "precedents": ({"cause": "required cause code"}, "Verified historical outcomes for a hypothesized cause, verified before now: action tried, "
                                                        "whether verification confirmed it and whether the exception cleared."),
    }

    def describe(self):
        return [{"tool": name, "args": args, "returns": text} for name, (args, text) in self.CATALOG.items() if name not in self.disabled]

    def begin_round(self, number_):
        """A review round starts: the same belt, records and computed results carry over."""
        self.round = number_

    def round_calls(self, number_=None):
        return [c for c in self.calls if c["round"] == (self.round if number_ is None else number_)]

    def call(self, tool, args):
        if tool not in self.CATALOG or tool in self.disabled:
            return {"error": f"unknown tool {tool}"}
        allowed = self.CATALOG[tool][0]
        args = {k: v for k, v in (args if isinstance(args, dict) else {}).items() if k in allowed}
        self._tool, failure = tool, None
        try:
            result = getattr(self, "_" + tool)(**args)
        except (TypeError, ValueError, KeyError) as error:
            result, failure = {"error": f"invalid arguments ({type(error).__name__})"}, "invalid_arguments"
        except Exception as error:  # A failed evidence query is reported as such (type only), never as "no evidence".
            result, failure = {"error": f"evidence query failed ({type(error).__name__}); this is not evidence of absence"}, "query_failed"
        text, ids, omitted = self._render(result)
        computed = [i for i in ids if i in self.computed]
        self.retrieved.update(ids)
        self.calls.append({"round": self.round, "tool": tool, "args": args, "evidence_ids": ids, "computed_ids": computed,
                           "omitted_rows": omitted, "failure": failure})
        self._tool = None
        return {"result": text, "evidence_ids": ids, "computed_ids": computed}

    # ------------------------------------------------------------------ rendering and truncation
    def _render(self, result):
        """JSON text within the size cap, the ids citable from it, and how many rows of each list were left out.
        Row lists arrive ordered with deviations first; rows are dropped from the end, and only the ids of rows
        that are shown (plus the result's own head ids) are citable."""
        result = dict(result)
        head = list(result.pop("evidence_ids", []))
        lists = [k for k, v in result.items() if isinstance(v, list) and v and all(isinstance(r, dict) and "_ids" in r for r in v)]
        omitted = {}
        for key in lists:
            if len(result[key]) > MAX_ROWS:
                omitted[key] = len(result[key]) - MAX_ROWS
                result[key] = result[key][:MAX_ROWS]

        def dump():
            body = {k: ([{f: x for f, x in r.items() if f != "_ids"} for r in v] if k in lists else v) for k, v in result.items()}
            if omitted:
                body["omitted_rows"] = dict(omitted)
                body["omitted_note"] = "Lower-priority rows were left out and are not citable from this result; narrow the call to see them."
            return json.dumps(body, default=str, ensure_ascii=False)

        text = dump()
        while len(text) > MAX_RESULT_CHARS:
            key = max((k for k in lists if len(result[k]) > 1), key=lambda k: len(json.dumps(result[k], default=str)), default=None)
            if key is None:
                break
            result[key] = result[key][:-1]
            omitted[key] = omitted.get(key, 0) + 1
            text = dump()
        ids = list(dict.fromkeys([*head, *[i for k in lists for r in result[k] for i in r["_ids"]]]))
        ids = [i for i in ids if isinstance(i, str)]
        if len(text) > MAX_RESULT_CHARS:
            # Nothing left to drop row by row: cut the text and keep only ids that are still readable in it.
            text = text[:MAX_RESULT_CHARS] + '..."TRUNCATED"'
            ids = [i for i in ids if i in text]
        ids = ids[:MAX_CITABLE_IDS]
        for key in ids:
            self._indexed(key)
        return text + " CITABLE_EVIDENCE_IDS: " + json.dumps(ids), ids, omitted

    def _semantics(self):
        """The telemetry vocabulary, spelled out the first time a result uses it."""
        if self._cache.get("semantics_shown"):
            return "As explained with the first telemetry result."
        self._cache["semantics_shown"] = True
        return TELEMETRY_SEMANTICS

    def _indexed(self, key):
        if key in self.index:
            return
        node = self.nodes.get(key)
        if node is not None:
            p = node.properties
            self.index[key] = {"kind": node.kind, "scope": "shipment" if p.get("holdout_group") == self.sid else "shared",
                               "recorded_at": _iso(p.get("recorded_at")), "occurred_at": _iso(p.get("occurred_at"))}
        elif key in self.external:
            record = self.external[key]
            self.index[key] = {"kind": record.get("kind"), "scope": record.get("scope", "shared"),
                               "recorded_at": _iso(record.get("recorded_at")), "occurred_at": _iso(record.get("occurred_at"))}

    # ------------------------------------------------------------------ helpers: own evidence
    def _kind(self, kind, package_id=None):
        rows = [n for n in self.nodes.values() if n.kind == kind and (package_id is None or n.properties.get("package_id") == package_id)]
        return sorted(rows, key=lambda n: (str(n.properties.get("occurred_at") or ""), n.id))

    def _times(self, p):
        return {"occurred_at": _iso(p.get("occurred_at")), "recorded_at": _iso(p.get("recorded_at")), "upload_lag_minutes": _lag_minutes(p)}

    def _packages(self):
        return sorted((n for n in self.nodes.values() if n.kind == "Package"), key=lambda n: n.id)

    def _package(self, package_id):
        node = self.nodes.get(package_id)
        if node is None or node.kind != "Package":
            raise ValueError("package_id is not a package of this shipment")
        return node

    def _policy_values(self):
        policy = self.nodes.get(self.nodes[self.sid].properties.get("policy_id"))
        return policy, (policy.properties if policy else {})

    # ------------------------------------------------------------------ helpers: computed results and external records
    def _compute(self, computation, inputs, **values):
        """Register a tool-computed fact under a stable id: the same comparison at the same snapshot has the same id."""
        inputs = sorted({i for i in inputs if isinstance(i, str)})
        key = "DEMO-CMP-" + digest([self.sid, self.as_of, computation, inputs, sorted((k, str(v)) for k, v in values.items())])[:20]
        self.computed[key] = {"kind": "ComputedResult", "scope": "computed", "computation": computation, "tool": self._tool,
                              "computed_as_of": self.as_of, "input_ids": inputs, **values}
        self.external[key] = self.computed[key]
        return key

    def _remember(self, props, kind, *, scope=None):
        """A record that is not one of this shipment's evidence nodes, kept as the reviewer will read it."""
        key = props.get("entity_id")
        if not key or key in self.nodes:
            return key
        owner = props.get("holdout_group") or props.get("shipment_id")
        self.external.setdefault(key, {"kind": kind, "scope": scope or ("other_shipment" if owner and owner != self.sid else "shared"),
                                       **_public(props)})
        return key

    def _fetch(self, name, **params):
        if self.port is None:
            raise LookupError(NO_PORT)
        return self.port(name, as_of=self.as_of, **params)

    def _shared(self, entity_id):
        """A shared record (device, facility, route run, trip, container...) as (properties, kind), or (None, None)."""
        if not isinstance(entity_id, str) or not entity_id.startswith("DEMO-"):
            raise ValueError("not a record identity")
        node = self.nodes.get(entity_id)
        if node is not None:
            return (dict(node.properties), node.kind) if not node.properties.get("holdout_group") else (None, None)
        if ("shared", entity_id) not in self._cache:
            rows = self._fetch("shared_record", ref=entity_id) if self.port is not None else []
            self._cache[("shared", entity_id)] = (rows[0]["props"], rows[0]["kind"]) if rows else (None, None)
            if rows:
                self._remember(rows[0]["props"], rows[0]["kind"], scope="shared")
        return self._cache[("shared", entity_id)]

    def _window(self, hours, end_at, default_hours, maximum=72):
        hours = max(1, min(int(hours or default_hours), maximum))
        end = min(_when(end_at) or self.cutoff, self.cutoff) if end_at else self.cutoff
        return end - timedelta(hours=hours), end, hours

    # ------------------------------------------------------------------ helpers: device telemetry
    def _beats(self, device_id, since, until):
        if self.port is not None:
            rows = self._fetch("device_heartbeats", ref=device_id, from_at=since.isoformat(), to_at=until.isoformat(), limit=240)
        else:
            rows = [b for b in self._heartbeats(device_id, since.isoformat(), until.isoformat())
                    if (_when(b.get("occurred_at")) or since) <= until]
        return sorted(rows, key=lambda b: str(_iso(b["occurred_at"])))

    def _device_report(self, device_id, since, until):
        """Telemetry facts for one device over [since, until] (until <= the snapshot). Heartbeats are citable records."""
        if not isinstance(device_id, str) or not device_id.startswith("DEMO-DEV-") or len(device_id) > 120:
            raise ValueError("Invalid device identity")
        device, _ = self._shared(device_id) if (self.port is not None or device_id in self.nodes) else (None, None)
        device = device or {}
        history = self._beats(device_id, min(since, until - timedelta(hours=BASELINE_HOURS)), until)
        beats = [b for b in history if _when(b["occurred_at"]) >= since]
        times = [_when(b["occurred_at"]) for b in beats]
        gaps_h = [(b - a).total_seconds() / 3600 for a, b in zip(times, times[1:])]
        declared = number(device.get("heartbeat_interval_seconds"))
        median = sorted(gaps_h)[len(gaps_h) // 2] * 3600 if gaps_h else None
        interval = declared or median
        stream = device.get("telemetry_stream")
        last = beats[-1] if beats else None
        missed = int((until - times[-1]).total_seconds() // interval) if times and interval else None
        if stream == "NONE":
            state = "NO_TELEMETRY_STREAM"
        elif not beats:
            state = "NO_HEARTBEATS_IN_WINDOW" if stream else "NO_TELEMETRY"
        elif last.get("connectivity") == "LOGGED_OUT":
            state = "LOGGED_OUT"
        elif missed is not None and missed >= 3:
            state = "SILENT"
        else:
            state = "REPORTING"
        usual = None
        if state == "SILENT" and interval:
            # Did it also stop, without a log-out, at about this time on the previous days and stay quiet as long?
            usual = []
            margin = timedelta(seconds=1.5 * interval)
            for days in (1, 2):
                stop, end = times[-1] - timedelta(days=days), until - timedelta(days=days)
                near = [b for b in history if abs(_when(b["occurred_at"]) - stop) <= margin]
                later = [b for b in history if stop + margin < _when(b["occurred_at"]) <= end]
                earlier = [b for b in history if stop - timedelta(hours=6) <= _when(b["occurred_at"]) < stop - margin]
                if near or later or earlier:
                    usual.append({"days_before": days, "also_stopped_without_log_out": bool(near) and not later
                                  and all(b.get("connectivity") != "LOGGED_OUT" for b in near),
                                  "heartbeats_in_the_same_hours": len(later)})
            if usual and all(u["also_stopped_without_log_out"] for u in usual):
                state = "QUIET_AS_ON_PREVIOUS_DAYS"
        for b in beats:
            self.external.setdefault(b["entity_id"], {"kind": "DeviceHeartbeat", "scope": "shared", "device_id": device_id,
                                                      "occurred_at": _iso(b["occurred_at"]), "recorded_at": _iso(b.get("recorded_at") or b["occurred_at"]),
                                                      "pending_uploads": b.get("pending_uploads"), "last_upload_at": _iso(b.get("last_upload_at")),
                                                      "connectivity": b.get("connectivity")})
        if device_id not in self.nodes:
            self.external.setdefault(device_id, {"kind": "Device", "scope": "shared", "device_id": device_id, **_public(device)})
        gaps = [{"from": _iso(a), "to": _iso(b), "hours": round((b - a).total_seconds() / 3600, 1), "between_heartbeats": [x["entity_id"], y["entity_id"]]}
                for (a, x), (b, y) in zip(zip(times, beats), zip(times[1:], beats[1:])) if interval and (b - a).total_seconds() > 2.5 * interval]
        if state in ("SILENT", "QUIET_AS_ON_PREVIOUS_DAYS"):
            gaps.append({"from": _iso(times[-1]), "to": None, "hours": round((until - times[-1]).total_seconds() / 3600, 1),
                         "between_heartbeats": [last["entity_id"], None]})
        pending = [b.get("pending_uploads") or 0 for b in beats]
        report = {"device_id": device_id, "reporting_state": state, "device_kind": device.get("device_kind"), "telemetry_stream": stream,
                  "facility_id": device.get("facility_id"), "driver_id": device.get("driver_id"),
                  "window_from": _iso(since), "window_to": _iso(until), "heartbeats": len(beats),
                  "expected_interval_minutes": round(interval / 60) if interval else None,
                  "last_seen_at": _iso(last["occurred_at"]) if last else None, "last_connectivity": last.get("connectivity") if last else None,
                  "hours_since_last_seen": round((until - times[-1]).total_seconds() / 3600, 1) if times else None,
                  "expected_beats_missed_since_last_seen": missed,
                  "last_pending_uploads": last.get("pending_uploads") if last else None, "max_pending_uploads": max(pending, default=None),
                  "largest_gap_hours": round(max([*gaps_h, *(g["hours"] for g in gaps[-1:] if g["to"] is None)], default=0), 1) if times else None,
                  "typical_interval_minutes": round(median / 60) if median else None,
                  "same_hours_on_previous_days": usual,
                  "gaps": gaps[-5:],
                  "series": [{"id": b["entity_id"], "seen_at": _iso(b["occurred_at"]), "pending_uploads": b.get("pending_uploads"),
                              **({"connectivity": b["connectivity"]} if b.get("connectivity") not in (None, "ONLINE") else {})} for b in beats[-6:]]}
        ids = [device_id, *[b["entity_id"] for b in beats[-6:]], *[i for g in gaps[-5:] for i in g["between_heartbeats"] if i]]
        report["computed_id"] = self._compute("DEVICE_TELEMETRY", ids, device_id=device_id, reporting_state=state, window_from=_iso(since),
                                              window_to=_iso(until), heartbeats=len(beats), last_seen_at=report["last_seen_at"],
                                              hours_since_last_seen=report["hours_since_last_seen"], max_pending_uploads=report["max_pending_uploads"],
                                              last_pending_uploads=report["last_pending_uploads"], gaps=[[g["from"], g["to"]] for g in gaps[-5:]],
                                              telemetry_stream=stream, same_hours_on_previous_days=usual)
        self.device_reports[device_id] = dict(report)
        # A cited device id stands for this telemetry summary, so a reviewer reads the same facts.
        self.external[device_id] = {"kind": "Device", "scope": "shared", **{k: v for k, v in report.items() if k != "series"}}
        return report, list(dict.fromkeys([*ids, report["computed_id"]]))

    def _telemetry_brief(self, device_id, since, until, *, covering=None):
        """Compact telemetry next to another fact. covering: (start, end) to say whether a heartbeat gap spans it."""
        try:
            report, ids = self._device_report(device_id, since, until)
        except LookupError:
            return {"device_id": device_id, "reporting_state": "UNKNOWN", "note": NO_PORT}, []
        brief = {k: report[k] for k in ("device_id", "device_kind", "reporting_state", "last_seen_at", "hours_since_last_seen",
                                        "last_pending_uploads", "max_pending_uploads", "computed_id")}
        if covering:
            start, end = covering
            spans = [g for g in report["gaps"] if (_when(g["from"]) or start) <= end and (_when(g["to"]) or until) >= start]
            brief["heartbeat_gap_over_expected_time"] = bool(spans)
        return brief, [device_id, report["computed_id"]]

    def _expected_devices(self, location_id):
        """Devices that record observations at a facility: its device records, else the handheld naming convention."""
        if self.port is not None:
            key = ("devices", location_id)
            if key not in self._cache:
                self._cache[key] = [r["props"] for r in self._fetch("facility_devices", ref=location_id, limit=12)]
                for props in self._cache[key]:
                    self._remember(props, "Device", scope="shared")
            devices = self._cache[key]
            if devices:
                return [d["entity_id"] for d in devices if d.get("device_kind") != "SCALE"], [d["entity_id"] for d in devices if d.get("device_kind") == "SCALE"]
        return ["DEMO-DEV-HH-" + location_id.removeprefix("DEMO-")], []

    def _driver_app(self, assignment):
        """The driver app a last-mile assignment's records come from: the route run's device, else the naming convention."""
        p = assignment.properties
        run, _ = self._shared(p["route_run_id"]) if p.get("route_run_id") and (self.port is not None or p["route_run_id"] in self.nodes) else (None, None)
        if run and run.get("device_ref"):
            return run["device_ref"]
        return "DEMO-DEV-APP-" + p["driver_id"].removeprefix("DEMO-") if p.get("driver_id") else None

    # ------------------------------------------------------------------ tools: this shipment
    def _shipment_overview(self):
        shipment = self.nodes[self.sid].properties
        plan = self.nodes.get(shipment.get("journey_id"))
        service = self.nodes.get((plan.properties if plan else {}).get("service_id"))
        statuses = self._kind("StatusEvent")
        references = {"device_ids": set(), "route_run_ids": set(), "trip_ids": set(), "container_ids": set(), "facility_ids": set()}
        for node in self.nodes.values():
            p = node.properties
            if p.get("holdout_group") != self.sid:
                continue
            for field, bucket in (("device_ref", "device_ids"), ("route_run_id", "route_run_ids"), ("route_manifest_ref", "route_run_ids"),
                                  ("trip_id", "trip_ids"), ("container_id", "container_ids"), ("facility_id", "facility_ids"), ("depot_id", "facility_ids")):
                if isinstance(p.get(field), str):
                    references[bucket].add(p[field])
            if node.kind == "ExpectedMilestone" and (self.nodes.get(p.get("location_id")) is not None and self.nodes[p["location_id"]].kind in FACILITY_KINDS):
                references["facility_ids"].add(p["location_id"])
        ids = [self.sid, *[p.id for p in self._packages()]] + ([plan.id] if plan else []) + [s.id for s in statuses[-8:]]
        return {"shipment_id": self.sid, "as_of": self.as_of, "case_symptoms": self.symptoms,
                "flow_type": shipment.get("flow_type"), "origin_city": shipment.get("origin_city"), "destination_city": shipment.get("destination_city"),
                "booked_at": _iso(shipment.get("recorded_at")),
                "service_level": (service.properties.get("name") if service else shipment.get("service_level")),
                "promise_at": _iso((plan.properties if plan else {}).get("promise_at")),
                "latest_status": statuses[-1].properties.get("status") if statuses else "CREATED",
                "status_history": [{"status_id": s.id, "status": s.properties.get("status"), **self._times(s.properties)} for s in statuses[-8:]],
                "packages": [{"package_id": p.id, "manifest_barcode": p.properties.get("manifest_barcode"),
                              "weight_kg": p.properties.get("weight_kg"), "handling": p.properties.get("handling")} for p in self._packages()],
                "references_in_this_shipments_records": {k: sorted(v)[:12] for k, v in references.items()},
                "evidence_ids": ids}

    def _journey(self, package_id=None):
        rows, checked = [], {}
        order = {"missing_after_deadline": 0, "observed_late": 1, "pending": 2, "observed_on_time": 3}
        packages = [self._package(package_id)] if package_id else self._packages()
        last_mile = [a for a in self._kind("VehicleAssignment") if a.properties.get("mode") == "last_mile" or a.properties.get("session_id")]
        for package in packages:
            events = [e for e in self._kind("CustodyEvent", package.id) if custody_corroborated(self.world, e, self.cutoff)]
            for milestone in sorted((m for m in self.nodes.values() if m.kind == "ExpectedMilestone" and m.properties.get("package_id") == package.id),
                                    key=lambda m: m.properties.get("sequence", 0)):
                mp = milestone.properties
                hits = [e for e in events if e.properties.get("event_type") == mp.get("predicate")
                        and mp.get("location_id") in (e.properties.get("to_id"), e.properties.get("facility_id"))]
                latest = instant(mp["latest_at"]) + timedelta(seconds=number(mp.get("grace_seconds")) or 0)
                observed = min((instant(e.properties["occurred_at"]) for e in hits), default=None)
                state = ("observed_on_time" if observed and observed <= latest else "observed_late" if observed
                         else "missing_after_deadline" if self.cutoff > latest else "pending")
                location = self.nodes.get(mp.get("location_id"))
                facility = location is not None and location.kind in FACILITY_KINDS
                row = {"package_id": package.id, "milestone_id": milestone.id, "sequence": mp.get("sequence"), "predicate": mp.get("predicate"),
                       "location_id": mp.get("location_id"), "location_kind": location.kind if location else None,
                       "facility_handheld": ("DEMO-DEV-HH-" + location.id.removeprefix("DEMO-")) if facility else None,
                       "nominal_at": _iso(mp.get("nominal_at")), "latest_at": _iso(mp.get("latest_at")), "observed_at": _iso(observed), "state": state,
                       "observation_ids": [e.id for e in hits], "_ids": [milestone.id, *[e.id for e in hits]]}
                if state in ("missing_after_deadline", "observed_late"):
                    row["computed_id"] = self._compute("MILESTONE_STATE", row["_ids"], package_id=package.id, predicate=mp.get("predicate"),
                                                       location_id=mp.get("location_id"), latest_at=_iso(mp.get("latest_at")),
                                                       observed_at=_iso(observed), state=state)
                    row["_ids"].append(row["computed_id"])
                    # The device expected to record it, and what its telemetry shows around the expected time.
                    key = mp.get("location_id") if facility else "last-mile"
                    if key not in checked and len(checked) < 3:
                        expected_from = _when(mp.get("nominal_at")) or _when(mp.get("earliest_at")) or latest
                        since = max(min(expected_from, self.cutoff) - timedelta(hours=2), self.cutoff - timedelta(hours=48))
                        devices = (self._expected_devices(mp["location_id"])[0] if facility else
                                   [d for d in dict.fromkeys(self._driver_app(a) for a in last_mile if package.id in (a.properties.get("package_ids") or [])) if d])
                        briefs = [self._telemetry_brief(d, since, self.cutoff, covering=(expected_from, min(latest, self.cutoff))) for d in devices[:3]]
                        checked[key] = ([b for b, _ in briefs], [i for _, ids in briefs for i in ids])
                    if key in checked:
                        row["expected_device_telemetry"] = checked[key][0] or "UNKNOWN: no device is on record for this location"
                        row["_ids"] += checked[key][1]
                    else:
                        row["expected_device_telemetry"] = "NOT_CHECKED_HERE: call same_device_activity for this location's device"
                if state == "observed_on_time":
                    row = {k: row[k] for k in ("package_id", "milestone_id", "sequence", "predicate", "location_id", "observed_at", "state",
                                                "observation_ids", "_ids")}
                rows.append(row)
        rows.sort(key=lambda r: (order[r["state"]], r["package_id"], r["sequence"] or 0))
        counts = {}
        for r in rows:
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        return {"state_counts": counts, "milestones": rows, **({"telemetry_semantics": self._semantics()} if any(v[0] for v in checked.values()) else {}),
                "note": "Rows are ordered missing, late, pending, on time. A milestone counts as observed only on a corroborated custody record.",
                "evidence_ids": []}

    def _custody_chain(self, package_id):
        package = self._package(package_id)
        rows, holder, last_id, last_at = [], None, None, None
        for event in self._kind("CustodyEvent", package.id):
            p = event.properties
            source = self.nodes.get(p.get("source_event_id"))
            to = self.nodes.get(p.get("to_id"))
            corroborated = custody_corroborated(self.world, event, self.cutoff)
            continuous = holder is None or p.get("from_id") == holder
            row = {"event_id": event.id, "event_type": p.get("event_type"), "from_id": p.get("from_id"), "to_id": p.get("to_id"),
                   "to_kind": to.kind if to else None, "facility_id": p.get("facility_id"),
                   "acknowledgments": f"{p.get('received_acknowledgments')}/{p.get('required_acknowledgments')}",
                   "source_quality": p.get("source_quality"), "corroborated": corroborated,
                   "follows_last_corroborated_holder": continuous,
                   "source_scan_id": source.id if source else None, "device_ref": (source.properties.get("device_ref") if source else None),
                   "observation_type": (source.properties.get("observation_type") if source else None),
                   **{k: p[k] for k in ("route_run_id", "trip_id", "vehicle_id", "assignment_id", "channel") if p.get(k)},
                   **self._times(p), "_ids": [event.id] + ([source.id] if source else [])}
            if not corroborated or not continuous:
                reasons = []
                if not corroborated:
                    reasons.append("acknowledgments below the required number" if (p.get("received_acknowledgments") or 0) < (p.get("required_acknowledgments") or 1)
                                   else "no source scan of this package visible yet" if source is None
                                   else "the delivery proof behind it is not corroborated" if p.get("event_type") == "DELIVERED"
                                   else "source record not corroborated")
                if not continuous:
                    reasons.append("transfer starts from a holder other than the last corroborated one")
                row["computed_id"] = self._compute("CUSTODY_TRANSFER_CHECK", row["_ids"] + ([last_id] if last_id else []), event_id=event.id,
                                                   corroborated=corroborated, follows_last_corroborated_holder=continuous,
                                                   last_corroborated_holder_id=holder, reasons=reasons)
                row["check_reasons"] = reasons
                row["_ids"].append(row["computed_id"])
            elif corroborated:
                holder, last_id, last_at = p.get("to_id"), event.id, p.get("occurred_at")
                row = {k: v for k, v in row.items() if k not in ("acknowledgments", "source_quality", "corroborated",
                                                                  "follows_last_corroborated_holder", "recorded_at", "to_kind")}
                row["checks"] = "corroborated, follows the last corroborated holder"
            rows.append(row)
        sessions = []
        for session in self._kind("DeliverySession"):
            sp = session.properties
            assigned = any(a.properties.get("session_id") == session.id and package.id in (a.properties.get("package_ids") or [])
                           for a in self._kind("VehicleAssignment"))
            if not assigned:
                continue
            end = _when(sp.get("end_at"))
            grace_end = end + timedelta(seconds=number(sp.get("grace_seconds")) or 0) if end else None
            recon = [r for r in self._kind("DepotReconciliation", package.id) if r.properties.get("session_id") == session.id]
            state = (("RECONCILED_" + str(recon[-1].properties.get("result"))) if recon else
                     "NOT_RECONCILED_AFTER_SESSION_END_AND_GRACE" if grace_end and self.cutoff > grace_end else
                     "SESSION_ENDED_WITHIN_GRACE" if end and self.cutoff > end else "SESSION_OPEN")
            ids = [session.id, *[r.id for r in recon]]
            computed = self._compute("SESSION_RECONCILIATION", ids, session_id=session.id, package_id=package.id, session_end_at=_iso(sp.get("end_at")),
                                     grace_ends_at=_iso(grace_end), reconciliation_state=state)
            sessions.append({"session_id": session.id, "depot_id": sp.get("depot_id"), "route_run_id": sp.get("route_run_id"),
                             "start_at": _iso(sp.get("start_at")), "end_at": _iso(sp.get("end_at")), "grace_ends_at": _iso(grace_end),
                             "reconciliation_state": state,
                             "reconciliations": [{"reconciliation_id": r.id, "result": r.properties.get("result"), **self._times(r.properties)} for r in recon],
                             "computed_id": computed, "_ids": [*ids, computed]})
        # Transfers that fail a check first, then the most recent.
        ordered = [r for r in rows if "computed_id" in r] + [r for r in reversed(rows) if "computed_id" not in r]
        return {"package_id": package.id, "transfers_recorded": len(rows),
                "last_corroborated_holder": {"holder_id": holder, "holder_kind": self.nodes[holder].kind if holder in self.nodes else None,
                                             "since": _iso(last_at), "event_id": last_id} if last_id else "UNKNOWN: no corroborated transfer is visible",
                "transfers": ordered, "delivery_sessions": sessions or "NONE: no delivery session has been planned for this package yet",
                "note": "Transfers failing a check come first, then the most recent. An assignment or a manifest line is not custody.",
                "evidence_ids": [package.id] + ([last_id] if last_id else [])}

    def _scans(self, package_id=None):
        policy, pp = self._policy_values()
        rows, lookups = [], {}
        for package in ([self._package(package_id)] if package_id else self._packages()):
            manifest = package.properties
            for scan in self._kind("ScanEvent", package.id):
                sp = scan.properties
                row = {"scan_id": scan.id, "package_id": package.id, "device_ref": sp.get("device_ref"), "facility_id": sp.get("facility_id"),
                       "observation_type": sp.get("observation_type"), "readable": sp.get("readable"), "confidence": sp.get("confidence"),
                       **{k: sp[k] for k in ("container_id", "trip_id", "route_run_id") if sp.get(k)}, **self._times(sp), "_ids": [scan.id]}
                deviates = False
                if sp.get("observed_barcode") is not None:
                    matches = sp["observed_barcode"] == manifest.get("manifest_barcode")
                    expected = str(manifest.get("manifest_barcode") or "")
                    differing = (sum(a != b for a, b in zip(sp["observed_barcode"], expected)) + abs(len(sp["observed_barcode"]) - len(expected))) if not matches else 0
                    row.update(observed_barcode=sp["observed_barcode"], manifest_barcode=manifest.get("manifest_barcode"), barcode_matches=matches)
                    if not matches:
                        deviates = True
                        row["characters_differing"] = differing
                        if sp["observed_barcode"] not in lookups and len(lookups) < 3:
                            lookups[sp["observed_barcode"]] = self._barcode_owner(sp["observed_barcode"])
                        owner = lookups.get(sp["observed_barcode"])
                        row["observed_barcode_is_the_label_of"] = owner[0] if owner else "NOT_LOOKED_UP"
                        row["_ids"] += owner[1] if owner else []
                    row["barcode_computed_id"] = self._compute("BARCODE_COMPARISON", [scan.id, package.id], scan_id=scan.id, package_id=package.id,
                                                               observed_barcode=sp["observed_barcode"], manifest_barcode=manifest.get("manifest_barcode"),
                                                               barcode_matches=matches, characters_differing=differing, readable=sp.get("readable"),
                                                               confidence=sp.get("confidence"), barcode_min_confidence=pp.get("barcode_min_confidence"))
                    row["_ids"] += [package.id, row["barcode_computed_id"]]
                measured, expected_kg = number(sp.get("measured_weight_kg")), number(manifest.get("weight_kg"))
                if sp.get("calibrated") is True and measured is not None and expected_kg is not None:
                    tolerance = max(number(pp.get("weight_absolute_kg")) or 0, expected_kg * (number(pp.get("weight_relative_fraction")) or 0))
                    within = abs(measured - expected_kg) <= tolerance + 1e-9
                    deviates = deviates or not within
                    row.update(measured_weight_kg=measured, manifest_weight_kg=expected_kg, tolerance_kg=round(tolerance, 3), weight_within_tolerance=within,
                               difference_kg=round(measured - expected_kg, 3))
                    row["weight_computed_id"] = self._compute("WEIGHT_COMPARISON", [scan.id, package.id, policy.id if policy else None], scan_id=scan.id,
                                                              package_id=package.id, measured_weight_kg=measured, declared_weight_kg=expected_kg,
                                                              tolerance_kg=round(tolerance, 3), weight_within_tolerance=within,
                                                              difference_kg=round(measured - expected_kg, 3), scale_device=sp.get("device_ref"))
                    row["_ids"] += [package.id, row["weight_computed_id"]] + ([policy.id] if policy else [])
                row["_deviates"] = deviates
                rows.append(row)
        rows.sort(key=lambda r: (not r["_deviates"], str(r["occurred_at"])))
        differing_reads = any(r.get("barcode_matches") is False for r in rows)
        outside = any(r.get("weight_within_tolerance") is False for r in rows)
        for r in rows:
            if r["_deviates"]:
                continue
            # A routine row keeps its comparison id only where it contrasts with a differing read or weighing.
            for flag, key, fields in ((differing_reads, "barcode_computed_id", ("observed_barcode", "manifest_barcode")),
                                      (outside, "weight_computed_id", ("manifest_weight_kg", "tolerance_kg", "difference_kg"))):
                if key in r and not flag:
                    r["_ids"] = [i for i in r["_ids"] if i != r[key]]
                    del r[key]
                    for field in fields:
                        r.pop(field, None)
            for field in ("recorded_at", "readable"):
                r.pop(field, None)
        summary = {"scans": len(rows), "barcode_reads": sum("barcode_matches" in r for r in rows),
                   "barcode_reads_differing": sum(r.get("barcode_matches") is False for r in rows),
                   "weighings": sum("weight_within_tolerance" in r for r in rows),
                   "weighings_outside_tolerance": sum(r.get("weight_within_tolerance") is False for r in rows)}
        for r in rows:
            del r["_deviates"]
        return {"summary": summary, "scans": rows, "barcode_min_confidence": pp.get("barcode_min_confidence"),
                "weight_tolerance": {"absolute_kg": pp.get("weight_absolute_kg"), "relative_fraction": pp.get("weight_relative_fraction"),
                                     "policy_id": policy.id if policy else None},
                "note": "Reads and weighings that differ from the declaration come first. To see how the same reader or scale treated other "
                        "parcels, call same_device_activity with its device_ref.",
                "evidence_ids": [p.id for p in self._packages()] + ([policy.id] if policy else [])}

    def _barcode_owner(self, barcode):
        """Which parcel's manifest barcode a differing read is: (description, ids)."""
        own = next((p for p in self._packages() if p.properties.get("manifest_barcode") == barcode), None)
        if own is not None:
            return {"package_id": own.id, "shipment_id": self.sid, "relation": "another package of this shipment"}, [own.id]
        if self.port is None:
            return "UNKNOWN: other shipments' labels cannot be looked up in this deployment", []
        rows = self._fetch("package_by_barcode", text=str(barcode)[:80], limit=3)
        if not rows:
            return "NO_PARCEL_ON_RECORD: no parcel known at this time carries this barcode", []
        row = rows[0]
        self.external.setdefault(row["package_id"], {"kind": "Package", "scope": "other_shipment", "entity_id": row["package_id"],
                                                     "shipment_id": row["shipment_id"], "manifest_barcode": barcode, "recorded_at": _iso(row.get("recorded_at"))})
        return {"package_id": row["package_id"], "shipment_id": row["shipment_id"], "relation": "a parcel of another shipment"}, [row["package_id"]]

    def _delivery_attempts(self):
        shipment = self.nodes[self.sid].properties
        rows = []
        for attempt in self._kind("DeliveryAttempt"):
            ap = attempt.properties
            contacts = [c for c in self._kind("ContactAttempt") if c.properties.get("attempt_id") == attempt.id]
            proofs = [p for p in self._kind("DeliveryProof") if p.properties.get("attempt_id") == attempt.id]
            assignment = self.nodes.get(ap.get("assignment_id"))
            dispatched_run = assignment.properties.get("route_run_id") if assignment else None
            row = {"attempt_id": attempt.id, "package_id": ap.get("package_id"), "disposition": ap.get("disposition"),
                   "failed_reason": ap.get("failed_reason"), "observed_gate": ap.get("observed_gate"),
                   "used_address_version_id": ap.get("used_address_version_id"),
                   **{k: ap[k] for k in ("route_run_id", "driver_id", "vehicle_id", "session_id", "assignment_id") if ap.get(k)}, **self._times(ap),
                   "contacts": [{"contact_id": c.id, "channel": c.properties.get("channel"), "result": c.properties.get("result"),
                                 "occurred_at": _iso(c.properties.get("occurred_at"))} for c in contacts],
                   "_ids": [attempt.id, *[c.id for c in contacts]]}
            if ap.get("route_run_id") and dispatched_run:
                same = ap["route_run_id"] == dispatched_run
                row["dispatched_on_route_run_id"] = dispatched_run
                row["attempt_recorded_by_the_dispatched_route_run"] = same
                if not same:
                    row["route_computed_id"] = self._compute("ATTEMPT_VS_DISPATCH", [attempt.id, assignment.id], attempt_id=attempt.id,
                                                             attempt_route_run_id=ap["route_run_id"], dispatched_route_run_id=dispatched_run,
                                                             attempt_driver_id=ap.get("driver_id"), dispatched_driver_id=assignment.properties.get("driver_id"),
                                                             same_route_run=False)
                    row["_ids"] += [assignment.id, row["route_computed_id"]]
            row["proofs"] = []
            for proof in proofs:
                assessed = proof_assessment(self.world, proof, self.cutoff)
                pp = proof.properties
                address = self.nodes.get(pp.get("address_version_id"))
                distance = point_distance_m(pp, address.properties) if address else None
                handoff, auth = self.nodes.get(pp.get("handoff_id")), self.nodes.get(pp.get("authentication_id"))
                photo = self.nodes.get(pp.get("photo_id"))
                hp = handoff.properties if handoff else {}
                detail = {"proof_id": proof.id, "corroborated": assessed["corroborated"], "reasons": assessed["reasons"],
                          "proof_point_distance_to_address_m": round(distance) if distance is not None else None,
                          "location_uncertainty_m": (number(pp.get("accuracy_m")) or 0) + (number(address.properties.get("accuracy_m")) or 0) if address else None,
                          "authentication": {"id": auth.id, "method": auth.properties.get("method"), "result": auth.properties.get("result"),
                                             "code_value_stored": False} if auth else None,
                          "signature_id": pp.get("signature_id"),
                          "photo": {"id": photo.id, "subject": photo.properties.get("subject"),
                                    "distance_to_address_m": (round(point_distance_m(photo.properties, address.properties))
                                                              if address and point_distance_m(photo.properties, address.properties) is not None else None)} if photo else None,
                          "handed_to": {"id": handoff.id, "recipient_type": hp.get("recipient_type"), "person_id": hp.get("recipient_id"),
                                        "is_the_consignee": hp.get("recipient_id") == shipment.get("recipient_id"),
                                        "authorization_on_record": bool(hp.get("authorization_ref"))} if handoff else None,
                          **self._times(pp)}
                detail["computed_id"] = self._compute("PROOF_CORROBORATION", assessed["evidence_ids"], proof_id=proof.id, corroborated=assessed["corroborated"],
                                                      reasons=assessed["reasons"], proof_point_distance_to_address_m=detail["proof_point_distance_to_address_m"],
                                                      location_uncertainty_m=detail["location_uncertainty_m"],
                                                      handed_to=detail["handed_to"] and {k: v for k, v in detail["handed_to"].items() if k != "id"},
                                                      authentication=detail["authentication"] and {k: v for k, v in detail["authentication"].items() if k != "id"})
                row["proofs"].append(detail)
                row["_ids"] += [*assessed["evidence_ids"], detail["computed_id"]] + ([address.id] if address else [])
            rows.append(row)
        rows.sort(key=lambda r: (r["disposition"] == "DELIVERED" and all(p["corroborated"] for p in r["proofs"]) and bool(r["proofs"]), str(r["occurred_at"])))
        reports = [{"report_id": r.id, "package_id": r.properties.get("package_id"), "report_code": r.properties.get("report_code"),
                    "channel": r.properties.get("channel"), "statement_en": str(r.properties.get("statement_en") or "")[:240],
                    **self._times(r.properties), "_ids": [r.id]} for r in self._kind("RecipientReport")]
        recon = [{"reconciliation_id": r.id, "package_id": r.properties.get("package_id"), "result": r.properties.get("result"),
                  "session_id": r.properties.get("session_id"), **self._times(r.properties), "_ids": [r.id]} for r in self._kind("DepotReconciliation")]
        return {"attempts": rows or "NONE: no delivery attempt is on record at this time", "recipient_reports": reports, "depot_reconciliations": recon,
                "consignee_id": shipment.get("recipient_id"),
                "note": "Failed attempts and uncorroborated proofs come first. A delivered status is not proof of correct delivery.",
                "evidence_ids": [self.sid]}

    def _vehicle_and_manifest(self):
        rows = []
        loaded = {}
        for event in self._kind("CustodyEvent"):
            p = event.properties
            if p.get("event_type") == "LOADED" and p.get("assignment_id") and custody_corroborated(self.world, event, self.cutoff):
                loaded.setdefault(p["assignment_id"], {})[p.get("package_id")] = event.id
        for assignment in sorted((n for n in self.nodes.values() if n.kind == "VehicleAssignment"), key=lambda n: str(n.properties.get("valid_from"))):
            ap = assignment.properties
            vehicle = self.nodes.get(ap.get("vehicle_id"))
            driver = self.nodes.get(ap.get("driver_id"))
            session = self.nodes.get(ap.get("session_id"))
            provider_id = driver.properties.get("provider_id") if driver else None
            provider = self.nodes.get(provider_id)
            rows.append({"assignment_id": assignment.id, "mode": ap.get("mode"), "valid_from": _iso(ap.get("valid_from")), "valid_to": _iso(ap.get("valid_to")),
                         "package_ids": ap.get("package_ids"), "route_run_id": ap.get("route_run_id"), "trip_id": ap.get("trip_id"),
                         "vehicle_id": ap.get("vehicle_id"), "vehicle_ownership": (vehicle.properties.get("ownership") if vehicle else None),
                         "vehicle_class": (vehicle.properties.get("vehicle_class") if vehicle else None),
                         "driver_id": ap.get("driver_id"), "driver_employment": (driver.properties.get("employment") if driver else None),
                         "provider_id": provider_id, "provider_type": provider.properties.get("provider_type") if provider else None,
                         "driver_app_device": self._driver_app(assignment) if (ap.get("mode") == "last_mile" or ap.get("session_id")) else
                                              ("DEMO-DEV-APP-" + ap["driver_id"].removeprefix("DEMO-") if ap.get("driver_id") else None),
                         "session_id": ap.get("session_id"), "session_end_at": _iso(session.properties.get("end_at")) if session else None,
                         "depot_id": session.properties.get("depot_id") if session else None,
                         "packages_with_corroborated_loading": sorted(loaded.get(assignment.id, {})),
                         **self._times(ap),
                         "_ids": [assignment.id, *[n.id for n in (session, vehicle, driver, provider) if n is not None], *loaded.get(assignment.id, {}).values()]})
        latest = {}
        for m in self._kind("Manifest"):
            key = m.properties.get("assignment_id")
            if key not in latest or (m.properties.get("version") or 0) > (latest[key].properties.get("version") or 0):
                latest[key] = m
        manifests = []
        for m in self._kind("Manifest"):
            mp = m.properties
            row = {"manifest_id": m.id, "assignment_id": mp.get("assignment_id"), "route_run_id": mp.get("route_manifest_ref"), "version": mp.get("version"),
                   "status": mp.get("manifest_status"), "package_ids": mp.get("package_ids"), "supersedes_id": mp.get("supersedes_id"),
                   "is_latest_version": latest.get(mp.get("assignment_id")) is m, **self._times(mp), "_ids": [m.id]}
            if row["is_latest_version"]:
                missing = sorted(set(loaded.get(mp.get("assignment_id"), {})) - set(mp.get("package_ids") or []))
                row["loaded_packages_missing_from_this_version"] = missing
                if missing:
                    load_ids = [loaded[mp["assignment_id"]][p] for p in missing]
                    row["computed_id"] = self._compute("MANIFEST_VS_LOADING", [m.id, *load_ids], manifest_id=m.id, version=mp.get("version"),
                                                       loaded_packages_missing_from_manifest=missing)
                    row["_ids"] += [*load_ids, row["computed_id"]]
            manifests.append(row)
        manifests.sort(key=lambda r: (not r.get("loaded_packages_missing_from_this_version"), -(r["version"] or 0)))
        gps = [{"gps_id": g.id, "vehicle_id": g.properties.get("vehicle_id"), "lat": g.properties.get("lat"), "lng": g.properties.get("lng"),
                "position_scope": g.properties.get("position_scope"), **self._times(g.properties), "_ids": [g.id]} for g in self._kind("GPSObservation")]
        return {"assignments": rows or "NONE: no vehicle or route assignment is on record at this time", "manifests": manifests,
                "vehicle_gps": gps or "NONE in this shipment's own records; vehicle positions of a trip are in container_and_trip",
                "note": "Vehicle GPS is the vehicle's position only; it never establishes where a parcel is. An assignment or a manifest line "
                        "is a plan, not custody.", "evidence_ids": []}

    def _device_status(self, device_id, hours=24):
        hours = max(1, min(int(hours or 24), 72))
        report, ids = self._device_report(device_id, self.cutoff - timedelta(hours=hours), self.cutoff)
        return {**report, "window_hours": hours, "telemetry_semantics": self._semantics(), "evidence_ids": ids}

    def _address_and_instructions(self):
        versions = [{"address_version_id": n.id, "version": n.properties.get("version"), "valid_from": _iso(n.properties.get("valid_from")),
                     "valid_to": _iso(n.properties.get("valid_to")), "verification_status": n.properties.get("verification_status"),
                     "supersedes_id": n.properties.get("supersedes_id"), "address_text": n.properties.get("address_text"),
                     "lat": n.properties.get("lat"), "lng": n.properties.get("lng"), "accuracy_m": n.properties.get("accuracy_m"),
                     "recorded_at": _iso(n.properties.get("recorded_at")), "_ids": [n.id]}
                    for n in sorted((n for n in self.nodes.values() if n.kind == "AddressVersion"), key=lambda n: n.properties.get("version") or 0)]
        for row, previous in zip(versions[1:], versions):
            distance = point_distance_m(row, previous)
            row["distance_from_previous_version_m"] = round(distance) if distance is not None else None
        instructions = {n.id: n for n in self.nodes.values() if n.kind == "DeliveryInstruction"}
        rows = [{"instruction_id": n.id, "address_version_id": n.properties.get("address_version_id"), "gate": n.properties.get("gate"),
                 "valid_from": _iso(n.properties.get("valid_from")), "valid_to": _iso(n.properties.get("valid_to")), "_ids": [n.id]} for n in instructions.values()]
        pins = [{"pin_id": n.id, "address_version_id": n.properties.get("address_version_id"), "purpose": n.properties.get("purpose"),
                 "lat": n.properties.get("lat"), "lng": n.properties.get("lng"), **self._times(n.properties), "_ids": [n.id]} for n in self._kind("LocationPin")]
        gates = []
        for attempt in self._kind("DeliveryAttempt"):
            ap = attempt.properties
            at = _when(ap.get("occurred_at"))
            for n in instructions.values():
                ip = n.properties
                begin, end = _when(ip.get("valid_from")), _when(ip.get("valid_to"))
                if (ip.get("address_version_id") == ap.get("used_address_version_id") and at and begin and begin <= at and (end is None or at < end)
                        and ap.get("observed_gate") is not None):
                    same = ip.get("gate") == ap.get("observed_gate")
                    computed = self._compute("GATE_COMPARISON", [attempt.id, n.id], attempt_id=attempt.id, instruction_id=n.id,
                                             observed_gate=ap.get("observed_gate"), instructed_gate=ip.get("gate"), same_gate=same)
                    gates.append({"attempt_id": attempt.id, "observed_gate": ap.get("observed_gate"), "instructed_gate": ip.get("gate"), "same_gate": same,
                                  "computed_id": computed, "_ids": [attempt.id, n.id, computed]})
        used = [{"attempt_id": a.id, "used_address_version_id": a.properties.get("used_address_version_id"), "occurred_at": _iso(a.properties.get("occurred_at")),
                 "address_version_valid_at_attempt": self._valid_at(a), "_ids": [a.id]} for a in self._kind("DeliveryAttempt")]
        gates.sort(key=lambda r: r["same_gate"])
        return {"address_versions": versions, "instructions": rows, "pins": pins, "attempt_gate_vs_instruction": gates, "attempt_address_versions": used,
                "evidence_ids": []}

    def _valid_at(self, attempt):
        version = self.nodes.get(attempt.properties.get("used_address_version_id"))
        at = _when(attempt.properties.get("occurred_at"))
        if version is None or at is None:
            return None
        begin, end = _when(version.properties.get("valid_from")), _when(version.properties.get("valid_to"))
        return not ((begin is not None and at < begin) or (end is not None and at >= end))

    def _policy(self):
        shipment = self.nodes[self.sid].properties
        policy = self.nodes.get(shipment.get("policy_id"))
        plan = self.nodes.get(shipment.get("journey_id"))
        service = self.nodes.get((plan.properties if plan else {}).get("service_id"))
        keep = ("barcode_min_confidence", "weight_absolute_kg", "weight_relative_fraction", "retry_limit", "reconciliation_grace_seconds", "scope")
        return {"policy": {k: policy.properties.get(k) for k in keep} if policy else None,
                "service": {"name": service.properties.get("name"), "milestone_tolerance_seconds": service.properties.get("milestone_tolerance_seconds")} if service else None,
                "evidence_ids": [n.id for n in (policy, service) if n]}

    def _precedents(self, cause):
        rows = []
        for row in list(self._precedent_source(cause))[:8]:
            verified = _when(row.get("verified_at"))
            if verified is None or verified > self.cutoff or type(row.get("success")) is not bool:
                continue  # Only outcomes verified at or before this investigation's snapshot.
            key = row.get("outcome_id") or row.get("case_id")
            source = row.get("source") or "history_verified"
            item = {"precedent_id": key, "case_id": row.get("case_id"), "shipment_id": row.get("shipment_id"), "action_type": row.get("action_type"),
                    "verified_success": row.get("success"), "exception_cleared": row.get("exception_cleared"), "outcome_source": source,
                    "verified_at": _iso(row.get("verified_at")), "exception_codes": row.get("exception_codes")}
            if isinstance(key, str):
                self.external.setdefault(key, {"kind": "VerifiedPrecedent", "scope": "precedent", "recorded_at": _iso(row.get("verified_at")),
                                               **{k: v for k, v in item.items() if k != "precedent_id"}})
            rows.append({**item, "_ids": [key] if isinstance(key, str) else []})
        tally = {}
        for row in rows:
            entry = tally.setdefault(row["action_type"], {"verified_success": 0, "verified_failure": 0, "exception_cleared": 0})
            entry["verified_success" if row["verified_success"] else "verified_failure"] += 1
            entry["exception_cleared"] += bool(row["exception_cleared"])
        return {"cause": cause, "verified_outcomes": rows or "NONE: no verified outcome for this cause was recorded before this investigation",
                "by_action": tally,
                "note": "Only independently verified, non-invalidated outcomes verified before this investigation's snapshot. A precedent says what "
                        "was tried elsewhere; it is not evidence about this shipment.", "evidence_ids": []}

    def _communications(self):
        shipment = self.nodes[self.sid].properties
        messages = [{"message_id": n.id, "purpose": n.properties.get("purpose"), "channel_type": n.properties.get("channel_type"),
                     "carrier_route": n.properties.get("carrier_route"), "direction": n.properties.get("direction"),
                     "delivery_status": n.properties.get("delivery_status"), "package_id": n.properties.get("package_id"),
                     "sent_at": _iso(n.properties.get("occurred_at")), "status_report_received_at": _iso(n.properties.get("recorded_at")),
                     **({"code_value_stored": False} if str(n.properties.get("purpose") or "").startswith("OTP") else {}), "_ids": [n.id]}
                    for n in self._kind("CommunicationEvent")]
        messages.sort(key=lambda r: (r["delivery_status"] != "FAILED", not str(r["purpose"] or "").startswith("OTP"), str(r["sent_at"])))
        codes = [{"authentication_id": n.id, "attempt_id": n.properties.get("attempt_id"), "method": n.properties.get("method"),
                  "result": n.properties.get("result"), "code_value_stored": False, **self._times(n.properties), "_ids": [n.id]}
                 for n in self._kind("AuthenticationEvidence")]
        calls = [{"contact_id": n.id, "attempt_id": n.properties.get("attempt_id"), "channel": n.properties.get("channel"),
                  "result": n.properties.get("result"), **self._times(n.properties), "_ids": [n.id]} for n in self._kind("ContactAttempt")]
        reports = [{"report_id": n.id, "report_code": n.properties.get("report_code"), "channel": n.properties.get("channel"),
                    "package_id": n.properties.get("package_id"), "statement_en": str(n.properties.get("statement_en") or "")[:240],
                    "verification_status": n.properties.get("verification_status"), **self._times(n.properties), "_ids": [n.id]}
                   for n in self._kind("RecipientReport")]
        corrections = [{"address_version_id": n.id, "version": n.properties.get("version"), "supersedes_id": n.properties.get("supersedes_id"),
                        "valid_from": _iso(n.properties.get("valid_from")), "recorded_at": _iso(n.properties.get("recorded_at")), "_ids": [n.id]}
                       for n in self.nodes.values() if n.kind == "AddressVersion" and (n.properties.get("version") or 1) > 1]
        route_view = []
        failed_routes = {}
        for node in self._kind("CommunicationEvent"):
            p = node.properties
            if p.get("carrier_route") and str(p.get("purpose") or "").startswith("OTP"):
                failed_routes.setdefault(p["carrier_route"], []).append(node)
        for route, nodes in sorted(failed_routes.items())[:2]:
            if self.port is None:
                route_view.append({"carrier_route": route, "other_messages_on_this_route": NO_PORT, "_ids": []})
                continue
            first = min(_when(n.properties["occurred_at"]) for n in nodes)
            last = max(_when(n.properties["occurred_at"]) for n in nodes)
            since, until = first - timedelta(hours=3), min(last + timedelta(hours=3), self.cutoff)
            counts = self._fetch("sms_route_counts", text=route, from_at=since.isoformat(), to_at=until.isoformat(), limit=24)
            failures = self._fetch("sms_route_failures", text=route, from_at=since.isoformat(), to_at=until.isoformat(), limit=8)
            other = [f["props"] for f in failures if f["props"].get("shipment_id") != self.sid]
            for props in other:
                self._remember(props, "CommunicationEvent")
            table = [{"purpose": c["purpose"], "delivery_status": c["delivery_status"], "messages": c["messages"], "shipments": c["shipments"]} for c in counts]
            computed = self._compute("CARRIER_ROUTE_DELIVERY_COUNTS", [n.id for n in nodes] + [p["entity_id"] for p in other], carrier_route=route,
                                     window_from=_iso(since), window_to=_iso(until), counts=table,
                                     other_shipments_with_failed_messages=len({p.get("shipment_id") for p in other}))
            route_view.append({"carrier_route": route, "window_from": _iso(since), "window_to": _iso(until), "messages_by_purpose_and_status": table,
                               "failed_messages_of_other_shipments": [{"message_id": p["entity_id"], "shipment_id": p.get("shipment_id"),
                                                                       "purpose": p.get("purpose"), "sent_at": _iso(p.get("occurred_at"))} for p in other],
                               "computed_id": computed, "_ids": [computed, *[p["entity_id"] for p in other]]})
        return {"recipient_id": shipment.get("recipient_id"),
                "messages_to_recipient": messages or "NONE: no message to the recipient is on record at this time",
                "one_time_code_checks": codes, "calls": calls,
                "messages_from_recipient": reports or "NONE: no report, complaint or correction from the recipient is on record at this time",
                "address_corrections": corrections, "same_carrier_route": route_view,
                "note": "Failed messages come first. A message's status report can arrive long after it was sent. A recipient's statement is an "
                        "attributed report, not an established fact. No code value is ever stored.", "evidence_ids": [self.sid]}

    def _route_conditions(self, hours=48):
        since, until, hours = self._window(hours, None, 48, maximum=96)
        shipment = self.nodes[self.sid].properties
        versions = sorted((n for n in self.nodes.values() if n.kind == "AddressVersion"), key=lambda n: n.properties.get("version") or 0)
        address = versions[-1] if versions else None
        base = next((n for n in self.nodes.values() if n.kind == "Address"), None)
        city = next((n for n in self.nodes.values() if n.kind == "City" and n.properties.get("name") == shipment.get("destination_city")), None)
        attempts = self._kind("DeliveryAttempt")
        incidents, note = [], None
        if city is None:
            note = "UNKNOWN: the destination city's record is not among this shipment's references, so traffic reports cannot be looked up."
        elif self.port is None:
            note = NO_PORT
        else:
            for row in self._fetch("traffic_events", ref=city.id, from_at=since.isoformat(), limit=30):
                p = row["props"]
                key = self._remember(p, "TrafficEvent", scope="shared")
                distance = point_distance_m(p, address.properties) if address else None
                start, end = _when(p.get("start_at")), _when(p.get("end_at"))
                during = [a.id for a in attempts if start and end and start <= (_when(a.properties.get("occurred_at")) or start) <= end]
                within = distance is not None and number(p.get("radius_km")) is not None and distance / 1000 <= number(p["radius_km"])
                computed = self._compute("TRAFFIC_VS_ADDRESS", [key] + ([address.id] if address else []) + during, traffic_event_id=key,
                                         distance_from_address_km=round(distance / 1000, 1) if distance is not None else None,
                                         radius_km=p.get("radius_km"), address_within_radius=within, attempts_during_incident=during)
                incidents.append({"traffic_event_id": key, "event_type": p.get("event_type"), "severity": p.get("severity"), "district": p.get("district"),
                                  "start_at": _iso(p.get("start_at")), "end_at": _iso(p.get("end_at")), "confidence": p.get("confidence"),
                                  "radius_km": p.get("radius_km"), "reported_at": _iso(p.get("recorded_at")),
                                  "distance_from_address_km": round(distance / 1000, 1) if distance is not None else None,
                                  "address_within_radius": within, "attempts_during_incident": during, "computed_id": computed,
                                  "_ids": [key, computed, *during] + ([address.id] if address else [])})
            incidents.sort(key=lambda r: (not r["address_within_radius"], not r["attempts_during_incident"], str(r["start_at"])), reverse=False)
        observations = [{"traffic_observation_id": n.id, "segment_id": n.properties.get("segment_id"), "delay_seconds": n.properties.get("delay_seconds"),
                         "confidence": n.properties.get("confidence"), "start_at": _iso(n.properties.get("start_at")), "end_at": _iso(n.properties.get("end_at")),
                         **self._times(n.properties), "_ids": [n.id, *([n.properties["segment_id"]] if n.properties.get("segment_id") in self.nodes else [])]}
                        for n in self._kind("TrafficObservation")]
        segments = [{"segment_id": n.id, "sequence": n.properties.get("sequence"), "mode": n.properties.get("mode"), "from_id": n.properties.get("from_id"),
                     "to_id": n.properties.get("to_id"), "minimum_seconds": n.properties.get("minimum_seconds"),
                     "maximum_seconds": n.properties.get("maximum_seconds"), "_ids": [n.id]}
                    for n in sorted((n for n in self.nodes.values() if n.kind == "RouteSegment"), key=lambda n: n.properties.get("sequence") or 0)]
        skipped = [{"attempt_id": a.id, "failed_reason": a.properties.get("failed_reason"), **self._times(a.properties), "_ids": [a.id]}
                   for a in attempts if str(a.properties.get("failed_reason") or "").startswith(("NOT_ATTEMPTED", "SESSION_"))]
        return {"destination_city": shipment.get("destination_city"), "district": base.properties.get("district") if base else None,
                "window_hours": hours, "traffic_incidents_reported_for_the_city": incidents or (note or "NONE: no traffic incident was reported for this city in the window"),
                "traffic_observations_on_this_shipments_segments": observations or "NONE on record",
                "stops_not_attempted": skipped, "planned_route_segments": segments,
                "note": "A traffic report describes roads, not parcels. Incidents within their radius of the address, or overlapping an attempt, come first.",
                "evidence_ids": ([address.id] if address else []) + ([city.id] if city else [])}

    # ------------------------------------------------------------------ tools: beyond this shipment
    def _same_device_activity(self, device_id, hours=12, end_at=None):
        since, until, hours = self._window(hours, end_at, 12, maximum=48)
        if self.port is None:
            report, ids = self._device_report(device_id, since, until)
            return {"telemetry": report, "records_made_through_device": NO_PORT, "other_shipments_overdue": NO_PORT,
                    "telemetry_semantics": self._semantics(), "evidence_ids": ids}
        report, ids = self._device_report(device_id, since, until)
        window = {"ref": device_id, "from_at": since.isoformat(), "to_at": until.isoformat()}
        counts = (self._fetch("device_scan_counts", **window, late_seconds=LATE_UPLOAD_SECONDS, limit=1) or [{}])[0]
        late = [r["props"] for r in self._fetch("device_late_scans", **window, late_seconds=LATE_UPLOAD_SECONDS, limit=12)]
        recent = [r["props"] for r in self._fetch("device_scans", **window, limit=8)]
        def scan_row(p):
            key = self._remember(p, "ScanEvent")
            return {"scan_id": key, "shipment_id": p.get("shipment_id"), "package_id": p.get("package_id"), "observation_type": p.get("observation_type"),
                    "this_shipment": p.get("shipment_id") == self.sid, **self._times(p), "_ids": [key]}
        late_rows, recent_rows = [scan_row(p) for p in late], [scan_row(p) for p in recent]
        records = {"records": counts.get("records", 0), "shipments": counts.get("shipments", 0),
                   "late_threshold_minutes": LATE_UPLOAD_SECONDS // 60, "late_records": counts.get("late_records", 0),
                   "late_shipments": counts.get("late_shipments", 0), "first_record_at": _iso(counts.get("first_occurred_at")),
                   "last_record_at": _iso(counts.get("last_occurred_at"))}
        records["computed_id"] = self._compute("DEVICE_RECORD_COUNTS", [device_id, *[r["scan_id"] for r in late_rows]], device_id=device_id,
                                               window_from=_iso(since), window_to=_iso(until), **{k: v for k, v in records.items()})
        measurements = self._fetch("device_measurements", **window, limit=400)
        compared, compared_ids = self._measurement_summary(device_id, measurements, since, until)
        device = self.device_reports[device_id]
        overdue, runs = None, None
        if device.get("facility_id"):
            overdue = self._overdue_at(device["facility_id"], since)
        elif device.get("device_kind") == "DRIVER_APP" or device_id.startswith("DEMO-DEV-APP-"):
            runs = []
            for row in self._fetch("device_route_runs", **window, limit=6):
                key = self._remember(row["props"], "RouteRun", scope="shared")
                runs.append({"route_run_id": key, "service_date": row["props"].get("service_date"), "start_at": _iso(row["props"].get("start_at")),
                             "end_at": _iso(row["props"].get("end_at")), "_ids": [key]})
        mine = [n.id for n in self._kind("ScanEvent") if n.properties.get("device_ref") == device_id]
        return {"window_hours": hours, "telemetry": report, "records_made_through_device": records,
                "late_records_sample": late_rows, "latest_records_sample": recent_rows, **compared,
                "other_shipments_overdue_at_its_facility": ({k: v for k, v in overdue.items() if k != "sample_ids"} if overdue is not None
                                                            else "NOT_APPLICABLE: this device is not a facility device"),
                "route_runs_using_this_device": runs if runs is not None else "NOT_APPLICABLE: this device is not a driver app",
                "this_shipments_records_through_device": mine[:12] or "NONE: no visible record of this shipment was made through this device",
                "telemetry_semantics": self._semantics(),
                "note": "Records are counted when they happened in the window; a record still held back by the device is not visible and not counted.",
                "evidence_ids": [*ids, records["computed_id"], *compared_ids, *mine[:12]]
                                + ([overdue["computed_id"], *overdue["sample_ids"]] if isinstance(overdue, dict) else [])}

    def _measurement_summary(self, device_id, rows, since, until):
        """How one reader or scale's reads and weighings in a window compare with the declarations, across parcels."""
        _, pp = self._policy_values()
        reads = [r for r in rows if r.get("observed_barcode") is not None]
        differing = [r for r in reads if r["observed_barcode"] != r.get("manifest_barcode")]
        weighings, outside = [], []
        for r in rows:
            measured, declared = number(r.get("measured_weight_kg")), number(r.get("declared_weight_kg"))
            if r.get("calibrated") is True and measured is not None and declared is not None:
                tolerance = max(number(pp.get("weight_absolute_kg")) or 0, declared * (number(pp.get("weight_relative_fraction")) or 0))
                weighings.append(r)
                if abs(measured - declared) > tolerance + 1e-9:
                    outside.append({**r, "difference_kg": round(measured - declared, 3), "relative_difference": round((measured - declared) / declared, 3) if declared else None})
        out = {}
        def keep(r):
            self.external.setdefault(r["scan_id"], {"kind": "ScanEvent", "scope": "other_shipment" if r.get("shipment_id") != self.sid else "shipment",
                                                    **{k: _iso(v) for k, v in r.items() if k != "scan_id" and v is not None}, "device_ref": device_id})
            return r["scan_id"]
        if reads:
            sample = [{"scan_id": keep(r), "shipment_id": r.get("shipment_id"), "this_shipment": r.get("shipment_id") == self.sid,
                       "observed_barcode": r["observed_barcode"], "manifest_barcode": r.get("manifest_barcode"),
                       "characters_differing": sum(a != b for a, b in zip(str(r["observed_barcode"]), str(r.get("manifest_barcode") or ""))),
                       "occurred_at": _iso(r.get("occurred_at")), "_ids": [r["scan_id"]]} for r in differing[:8]]
            computed = self._compute("DEVICE_BARCODE_READS", [device_id, *[s["scan_id"] for s in sample]], device_id=device_id, window_from=_iso(since),
                                     window_to=_iso(until), barcode_reads=len(reads), reads_differing_from_manifest=len(differing),
                                     shipments_with_differing_reads=len({r.get("shipment_id") for r in differing}))
            out["barcode_reads_by_this_device"] = {"reads": len(reads), "differing_from_manifest": len(differing),
                                                  "shipments_with_differing_reads": len({r.get("shipment_id") for r in differing}), "computed_id": computed}
            out["differing_reads_sample"] = sample
            out.setdefault("_ids", []).append(computed)
        if weighings:
            sample = [{"scan_id": keep(r), "shipment_id": r.get("shipment_id"), "this_shipment": r.get("shipment_id") == self.sid,
                       "measured_weight_kg": r.get("measured_weight_kg"), "declared_weight_kg": r.get("declared_weight_kg"),
                       "difference_kg": r["difference_kg"], "relative_difference": r["relative_difference"],
                       "occurred_at": _iso(r.get("occurred_at")), "_ids": [r["scan_id"]]} for r in outside[:8]]
            signs = [r["difference_kg"] > 0 for r in outside]
            computed = self._compute("DEVICE_WEIGHINGS", [device_id, *[s["scan_id"] for s in sample]], device_id=device_id, window_from=_iso(since),
                                     window_to=_iso(until), weighings=len(weighings), outside_tolerance=len(outside),
                                     shipments_outside_tolerance=len({r.get("shipment_id") for r in outside}),
                                     outside_tolerance_heavier=sum(signs), outside_tolerance_lighter=len(signs) - sum(signs))
            out["weighings_by_this_device"] = {"weighings": len(weighings), "outside_tolerance": len(outside),
                                               "shipments_outside_tolerance": len({r.get("shipment_id") for r in outside}),
                                               "outside_tolerance_heavier_than_declared": sum(signs),
                                               "outside_tolerance_lighter_than_declared": len(signs) - sum(signs), "computed_id": computed}
            out["weighings_outside_tolerance_sample"] = sample
            out.setdefault("_ids", []).append(computed)
        ids = out.pop("_ids", [])
        if not reads and not weighings:
            out["reads_and_weighings_by_this_device"] = "NONE in this window"
        return out, ids

    def _overdue_at(self, facility_id, since):
        """Other shipments whose expected observation at a facility is overdue at the snapshot: counts plus a sample."""
        params = {"ref": facility_id, "shipment_id": self.sid, "from_at": since.isoformat(), "allowance": OVERDUE_ALLOWANCE_SECONDS}
        counts = self._fetch("overdue_at_facility_counts", **params, limit=8)
        sample = self._fetch("overdue_at_facility", **params, limit=10)
        for row in sample:
            self.external.setdefault(row["milestone_id"], {"kind": "ExpectedMilestone", "scope": "other_shipment", "shipment_id": row["shipment_id"],
                                                           "package_id": row["package_id"], "predicate": row["predicate"], "location_id": facility_id,
                                                           "latest_at": _iso(row["latest_at"]), "recorded_at": _iso(row.get("recorded_at"))})
        by = {c["predicate"]: {"milestones": c["milestones"], "shipments": c["shipments"]} for c in counts}
        computed = self._compute("OVERDUE_AT_FACILITY", [facility_id, *[r["milestone_id"] for r in sample]], facility_id=facility_id,
                                 deadlines_from=_iso(since), overdue_by_expected_step=by,
                                 meaning="expected step with its deadline in the window, overdue by 15 minutes or more, and no custody record of it visible")
        return {"facility_id": facility_id, "deadlines_from": _iso(since),
                "overdue_to_be_received": by.get("RECEIVED", {"milestones": 0, "shipments": 0}),
                "overdue_to_leave": by.get("LOADED", {"milestones": 0, "shipments": 0}),
                "other_expected_steps_overdue": {k: v for k, v in by.items() if k not in ("RECEIVED", "LOADED")},
                "sample": [{"milestone_id": r["milestone_id"], "shipment_id": r["shipment_id"], "package_id": r["package_id"], "expected_step": r["predicate"],
                            "latest_at": _iso(r["latest_at"])} for r in sample],
                "computed_id": computed, "sample_ids": [r["milestone_id"] for r in sample]}

    def _same_route_run(self, route_run_id):
        if self.port is None:
            return {"route_run_id": route_run_id, "result": NO_PORT, "evidence_ids": []}
        run, kind = self._shared(route_run_id)
        if run is None or kind != "RouteRun":
            return {"route_run_id": route_run_id, "result": "UNKNOWN: no route run with this id is on record at this time", "evidence_ids": []}
        kinds = {}
        def fetch(name, kind_, limit):
            rows_ = [r["props"] for r in self._fetch(name, ref=route_run_id, limit=limit)]
            kinds.update({r["entity_id"]: kind_ for r in rows_})
            return rows_
        assignments, custody = fetch("route_run_assignments", "VehicleAssignment", 80), fetch("route_run_custody", "CustodyEvent", 300)
        attempts, scans = fetch("route_run_attempts", "DeliveryAttempt", 200), fetch("route_run_scans", "ScanEvent", 300)
        recon, manifests = fetch("route_run_reconciliations", "DepotReconciliation", 200), fetch("route_run_manifests", "Manifest", 200)
        planned = {}
        for a in assignments:
            for package in a.get("package_ids") or []:
                planned[package] = a
        parcels = dict.fromkeys([*planned, *[x.get("package_id") for x in (*custody, *attempts, *scans, *recon) if x.get("package_id")]])
        def of(rows, package, **match):
            return sorted((r for r in rows if r.get("package_id") == package and all(r.get(k) == v for k, v in match.items())),
                          key=lambda r: str(_iso(r.get("occurred_at"))))
        order = {"NO_OUTCOME_RECORDED": 0, "FAILED_NO_RETURN_RECORDED": 1, "FAILED_AND_RETURNED": 2, "RETURNED_TO_DEPOT": 3,
                 "DELIVERED_PROOF_NOT_ON_RECORD": 4, "DELIVERED_WITH_PROOF": 5}
        rows, tally, late_total = [], {}, 0
        for package in parcels:
            loads = of(custody, package, event_type="LOADED") or of(scans, package, observation_type="LOAD_CONFIRMATION")
            delivered = of(custody, package, event_type="DELIVERED")
            delivered_attempts = of(attempts, package, disposition="DELIVERED")
            failed = of(attempts, package, disposition="FAILED")
            returned = of(custody, package, event_type="RETURNED") or of(scans, package, observation_type="RETURN_SCAN")
            reconciled = of(recon, package)
            proof = any(d.get("proof_id") for d in delivered) or any(r.get("result") == "DELIVERED" and r.get("proof_id") for r in reconciled)
            outcome = ("DELIVERED_WITH_PROOF" if (delivered or delivered_attempts) and proof else
                       "DELIVERED_PROOF_NOT_ON_RECORD" if delivered or delivered_attempts else
                       "FAILED_AND_RETURNED" if failed and returned else "FAILED_NO_RETURN_RECORDED" if failed else
                       "RETURNED_TO_DEPOT" if returned else "NO_OUTCOME_RECORDED")
            records = [*loads[:1], *delivered[:1], *delivered_attempts[:1], *failed[-2:], *returned[:1], *reconciled[-1:]]
            lags = [_lag_minutes(r) for r in records if _lag_minutes(r) is not None]
            late_total += sum(1 for lag in lags if lag * 60 >= LATE_UPLOAD_SECONDS)
            owner = (planned.get(package) or (records[0] if records else {})).get("shipment_id")
            ids = [self._remember(r, kinds[r["entity_id"]]) for r in records]
            tally[outcome] = tally.get(outcome, 0) + 1
            rows.append({"package_id": package, "shipment_id": owner, "this_shipment": owner == self.sid,
                         "on_this_runs_dispatch_plan": package in planned, "load_confirmed": bool(loads),
                         "outcome": outcome, "failed_reasons": [f.get("failed_reason") for f in failed] or None,
                         "reconciliation": reconciled[-1].get("result") if reconciled else None,
                         "last_record_at": max((str(_iso(r.get("occurred_at"))) for r in records), default=None),
                         "max_upload_lag_minutes": max(lags, default=None), "record_ids": ids, "_ids": ids})
        rows.sort(key=lambda r: (not r["this_shipment"], order[r["outcome"]], r["load_confirmed"], str(r["package_id"])))
        versions = {}
        for m in manifests:
            entry = versions.setdefault(m.get("version"), {"lines": 0, "parcels": set(), "status": m.get("manifest_status"), "published_at": _iso(m.get("occurred_at"))})
            entry["lines"] += 1
            entry["parcels"].update(m.get("package_ids") or [])
        ordered = sorted(v for v in versions if v is not None)
        dropped = sorted(versions[ordered[0]]["parcels"] - versions[ordered[-1]]["parcels"]) if len(ordered) > 1 else []
        mine = [self._remember(m, "Manifest") for m in manifests if m.get("shipment_id") == self.sid]
        end = _when(run.get("end_at"))
        start = _when(run.get("start_at")) or self.cutoff
        telemetry, tids = (self._telemetry_brief(run["device_ref"], max(min(start, self.cutoff) - timedelta(hours=1), self.cutoff - timedelta(hours=48)), self.cutoff)
                           if run.get("device_ref") else ({"reporting_state": "UNKNOWN", "note": "no driver app is named on this route run"}, []))
        summary = {"parcels": len(rows), "shipments": len({r["shipment_id"] for r in rows}), "by_outcome": tally,
                   "load_confirmed": sum(r["load_confirmed"] for r in rows), "not_load_confirmed": sum(not r["load_confirmed"] for r in rows),
                   "records_uploaded_late": late_total, "late_threshold_minutes": LATE_UPLOAD_SECONDS // 60}
        summary["computed_id"] = self._compute("ROUTE_RUN_OUTCOMES", [route_run_id], route_run_id=route_run_id, **summary)
        return {"route_run": {"route_run_id": route_run_id, **{k: _iso(run.get(k)) for k in ("depot_id", "service_date", "vehicle_id", "driver_id",
                                                                                              "provider_id", "device_ref", "start_at", "end_at", "planned_stops")},
                              "planned_end_passed": bool(end and self.cutoff > end)},
                "driver_app": telemetry, "summary": summary, "parcels": rows,
                "manifest_versions": {str(v): {"lines": versions[v]["lines"], "parcels": len(versions[v]["parcels"]), "status": versions[v]["status"],
                                               "published_at": versions[v]["published_at"]} for v in ordered} or "NONE on record",
                "parcels_in_first_manifest_version_but_not_in_latest": dropped[:12],
                "this_shipments_manifest_lines": mine,
                "note": "This shipment's parcels come first, then parcels without an outcome, failed, returned, delivered. An outcome is what the "
                        "records show so far; a record still held back by a device is not visible.",
                "evidence_ids": [route_run_id, summary["computed_id"], *tids, *mine]}

    def _container_and_trip(self, container_id=None, trip_id=None):
        if not container_id and not trip_id:
            raise ValueError("container_id or trip_id is required")
        if self.port is None:
            return {"result": NO_PORT, "evidence_ids": []}
        out, head = {}, []
        if container_id:
            record, kind = self._shared(container_id)
            if record is None or kind != "Container":
                out["container"] = "UNKNOWN: no container with this id is on record at this time"
            else:
                scans = [r["props"] for r in self._fetch("container_scans", ref=container_id, limit=300)]
                by_package = {}
                for s in scans:
                    by_package.setdefault(s.get("package_id"), []).append(s)
                shipments = sorted({s.get("shipment_id") for s in scans if s.get("shipment_id")})
                last = {r["props"].get("package_id"): r["props"] for r in self._fetch("last_custody", shipment_ids=shipments[:60], limit=120)} if shipments else {}
                rows, places = [], {}
                for package, items in by_package.items():
                    items.sort(key=lambda s: str(_iso(s.get("occurred_at"))))
                    seen = last.get(package)
                    place = (seen.get("facility_id") or seen.get("to_id")) if seen else None
                    places[place or "UNKNOWN"] = places.get(place or "UNKNOWN", 0) + 1
                    ids = [self._remember(items[-1], "ScanEvent")] + ([self._remember(seen, "CustodyEvent")] if seen else [])
                    rows.append({"package_id": package, "shipment_id": items[0].get("shipment_id"), "this_shipment": items[0].get("shipment_id") == self.sid,
                                 "container_scans": len(items), "last_container_scan": {"scan_id": items[-1].get("entity_id"), "facility_id": items[-1].get("facility_id"),
                                                                                        "trip_id": items[-1].get("trip_id"), "occurred_at": _iso(items[-1].get("occurred_at"))},
                                 "last_recorded": {"event_id": seen.get("entity_id"), "event_type": seen.get("event_type"), "location_id": place,
                                                   **self._times(seen)} if seen else "UNKNOWN: no custody record visible",
                                 "_last": str(_iso(seen.get("occurred_at"))) if seen else "", "_ids": ids})
                rows.sort(key=lambda r: (not r["this_shipment"], r["_last"]))
                for r in rows:
                    del r["_last"]
                trips = {}
                for s in scans:
                    if s.get("trip_id"):
                        trips.setdefault(s["trip_id"], []).append(str(_iso(s.get("occurred_at"))))
                computed = self._compute("CONTAINER_PARCELS", [container_id], container_id=container_id, parcels=len(rows), shipments=len(shipments),
                                         parcels_by_last_recorded_location=places)
                out["container"] = {"container_id": container_id, **{k: _iso(record.get(k)) for k in ("container_type", "origin_facility_id",
                                                                                                        "destination_facility_id", "occurred_at")},
                                    "parcels": len(rows), "shipments": len(shipments), "parcels_by_last_recorded_location": places,
                                    "trips_it_was_scanned_on": [{"trip_id": t, "first_scan_at": min(v), "last_scan_at": max(v)} for t, v in sorted(trips.items())],
                                    "computed_id": computed}
                out["container_parcels"] = rows
                head += [container_id, computed]
        if trip_id:
            record, kind = self._shared(trip_id)
            if record is None or kind != "Trip":
                out["trip"] = "UNKNOWN: no trip with this id is on record at this time"
            else:
                events = [r["props"] for r in self._fetch("trip_events", ref=trip_id, limit=40)]
                positions = [r["props"] for r in self._fetch("trip_positions", ref=trip_id, limit=160)]
                custody = [r["props"] for r in self._fetch("trip_custody", ref=trip_id, limit=400)]
                containers = self._fetch("trip_containers", ref=trip_id, limit=40)
                start, end = _when(record.get("start_at")), _when(record.get("end_at"))
                def first(kind_):
                    return next((e for e in events if e.get("event_type") == kind_), None)
                departed, arrived = first("DEPARTED"), first("ARRIVED")
                schedule = {"scheduled_departure": _iso(record.get("start_at")), "scheduled_arrival": _iso(record.get("end_at")),
                            "departure_recorded_at": _iso(departed.get("occurred_at")) if departed else None,
                            "arrival_recorded_at": _iso(arrived.get("occurred_at")) if arrived else None,
                            "departure_delay_minutes": _minutes(_when(departed.get("occurred_at")), start) if departed else None,
                            "arrival_delay_minutes": _minutes(_when(arrived.get("occurred_at")), end) if arrived else None,
                            "scheduled_arrival_passed": bool(end and self.cutoff > end)}
                event_ids = [self._remember(e, "TripEvent", scope="shared") for e in events]
                schedule["computed_id"] = self._compute("TRIP_SCHEDULE_COMPARISON", [trip_id, *event_ids], trip_id=trip_id, **schedule)
                loaded = {c.get("package_id"): c for c in custody if c.get("event_type") == "LOADED"}
                received = {c.get("package_id") for c in custody if c.get("event_type") == "RECEIVED"}
                unreceived = [c for p, c in loaded.items() if p not in received]
                unreceived.sort(key=lambda c: (c.get("shipment_id") != self.sid, str(c.get("package_id"))))
                parcels = {"parcels_with_records_on_trip": len({c.get("package_id") for c in custody}),
                           "shipments": len({c.get("shipment_id") for c in custody}), "loaded_on_trip": len(loaded),
                           "received_with_this_trip_on_record": len(received & set(loaded)),
                           "loaded_without_a_receipt_on_record": len(unreceived)}
                sample = [{"package_id": c.get("package_id"), "shipment_id": c.get("shipment_id"), "this_shipment": c.get("shipment_id") == self.sid,
                           "load_event_id": self._remember(c, "CustodyEvent"), "loaded_at": _iso(c.get("occurred_at")), "_ids": [c.get("entity_id")]}
                          for c in unreceived[:10]]
                parcels["computed_id"] = self._compute("TRIP_PARCEL_COUNTS", [trip_id, *[s["load_event_id"] for s in sample]], trip_id=trip_id, **parcels)
                speeds = [number(p.get("speed_kmh")) for p in positions]
                stationary = [p for p, speed in zip(positions, speeds) if speed is not None and speed < 3]
                fix_ids = [self._remember(p, "GPSObservation", scope="shared") for p in ([positions[0], positions[-1]] if positions else [])]
                fix_ids += [self._remember(p, "GPSObservation", scope="shared") for p in stationary[:2] + stationary[-2:]]
                out["trip"] = {"trip_id": trip_id, **{k: _iso(record.get(k)) for k in ("trip_type", "lane_id", "from_facility_id", "to_facility_id", "cutoff_at",
                                                                                         "vehicle_id", "driver_id", "provider_id", "distance_km")},
                               "schedule": schedule, "parcels": parcels,
                               "vehicle_positions": {"fixes": len(positions), "first_at": _iso(positions[0].get("occurred_at")) if positions else None,
                                                     "last_at": _iso(positions[-1].get("occurred_at")) if positions else None,
                                                     "last_position": {k: positions[-1].get(k) for k in ("lat", "lng", "speed_kmh")} if positions else None,
                                                     "fixes_nearly_stationary": len(stationary),
                                                     "first_stationary_at": _iso(stationary[0].get("occurred_at")) if stationary else None,
                                                     "last_stationary_at": _iso(stationary[-1].get("occurred_at")) if stationary else None,
                                                     "sample_ids": list(dict.fromkeys(fix_ids)),
                                                     "note": "Vehicle position only; it never establishes where a parcel is."}
                                                    if positions else "NONE: no vehicle position for this trip is on record at this time"}
                out["trip_status_messages"] = [{"trip_event_id": key, "event_type": e.get("event_type"), "reason_code": e.get("reason_code"),
                                                "estimated_arrival_at": _iso(e.get("estimated_arrival_at")), **self._times(e), "_ids": [key]}
                                               for key, e in zip(event_ids, events)] or "NONE: the carrier has sent no status message for this trip"
                out["trip_containers"] = [{"container_id": c["container_id"], "parcels": c["parcels"], "shipments": c["shipments"],
                                           "first_scan_at": _iso(c["first_scan_at"]), "last_scan_at": _iso(c["last_scan_at"]), "_ids": []} for c in containers]
                out["trip_parcels_loaded_without_a_receipt_on_record"] = sample
                head += [trip_id, schedule["computed_id"], parcels["computed_id"], *list(dict.fromkeys(fix_ids))]
        out["note"] = ("This shipment's parcels come first. 'Last recorded' is the latest custody record visible now; a record still held back by a "
                       "device is not visible.")
        return {**out, "evidence_ids": head}

    def _facility_window(self, facility_id, hours=12, end_at=None):
        since, until, hours = self._window(hours, end_at, 12, maximum=72)
        if self.port is None:
            return {"facility_id": facility_id, "result": NO_PORT, "evidence_ids": []}
        record, kind = self._shared(facility_id)
        if record is None or kind not in FACILITY_KINDS:
            return {"facility_id": facility_id, "result": "UNKNOWN: no facility with this id is on record", "evidence_ids": []}
        window = {"ref": facility_id, "from_at": since.isoformat(), "to_at": until.isoformat()}
        hours_rows = [r["props"] for r in self._fetch("facility_throughput", **window, limit=72)]
        rows = []
        for p in hours_rows:
            key = self._remember(p, "FacilityThroughput", scope="shared")
            staffed = number(p.get("staffed_capacity_per_hour"))
            rows.append({"throughput_id": key, "hour_start": _iso(p.get("start_at")), "processed": p.get("processed_count"), "queue_depth": p.get("queue_depth"),
                         "staffed_capacity_per_hour": p.get("staffed_capacity_per_hour"), "nominal_capacity_per_hour": p.get("nominal_capacity_per_hour"),
                         "oldest_waiting_minutes": p.get("oldest_waiting_minutes"),
                         "processed_share_of_staffed_capacity": round((number(p.get("processed_count")) or 0) / staffed, 2) if staffed else None,
                         "_ids": [key]})
        rows.sort(key=lambda r: (-(number(r["oldest_waiting_minutes"]) or 0), -(number(r["queue_depth"]) or 0), str(r["hour_start"])))
        waits = [number(r["oldest_waiting_minutes"]) or 0 for r in rows]
        summary = {"hours_reported": len(rows), "processed_total": sum(number(r["processed"]) or 0 for r in rows),
                   "max_queue_depth": max((number(r["queue_depth"]) or 0 for r in rows), default=None),
                   "max_oldest_waiting_minutes": max(waits, default=None),
                   "hours_with_a_queue_at_hour_end": sum(1 for r in rows if (number(r["queue_depth"]) or 0) > 0),
                   "hours_with_oldest_wait_over_60_minutes": sum(1 for w in waits if w > 60)}
        summary["computed_id"] = self._compute("FACILITY_THROUGHPUT_SUMMARY", [facility_id, *[r["throughput_id"] for r in rows[:6]]], facility_id=facility_id,
                                               window_from=_iso(since), window_to=_iso(until), **summary)
        handled = {c["event_type"]: {"parcels": c["parcels"], "shipments": c["shipments"]} for c in self._fetch("facility_custody_counts", **window, limit=8)}
        overdue = self._overdue_at(facility_id, since)
        handhelds, scales = self._expected_devices(facility_id)
        devices, device_ids = [], []
        for device in handhelds[:4]:
            brief, ids = self._telemetry_brief(device, since, until)
            devices.append(brief)
            device_ids += ids
        return {"facility": {"facility_id": facility_id, "kind": kind, "city": record.get("city"), "name": record.get("name"),
                             "capacity_per_hour": record.get("capacity_per_hour")},
                "window_hours": hours, "window_from": _iso(since), "window_to": _iso(until),
                "throughput_summary": summary if rows else "NONE: this facility sent no throughput report in the window",
                "throughput_hours": rows, "parcels_with_custody_records_here_in_window": handled or "NONE on record",
                "other_shipments_overdue_here": {k: v for k, v in overdue.items() if k != "sample_ids"},
                "devices": devices, "scales": scales[:4], "telemetry_semantics": self._semantics(),
                "note": "Throughput hours with the longest waits come first. A throughput report describes the facility, not one parcel.",
                "evidence_ids": [facility_id, overdue["computed_id"], *overdue["sample_ids"], *device_ids] + ([summary["computed_id"]] if rows else [])}
