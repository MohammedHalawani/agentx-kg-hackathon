"""Investigation tools: bounded, read-only, time-correct views of one shipment's evidence.

The investigator agent chooses which tool to call and with which arguments. Every tool reads only
what Suhail had ingested by the investigation's as-of time (the evidence snapshot, plus device
telemetry recorded by then), only for this shipment or shared reference data, and returns compact
records with their evidence ids. Tools compute facts (comparisons, chronologies, lags); they never
return a diagnosis or a cause code. Truth, gold and scenario data are not reachable from here.
"""
from datetime import timedelta
import json

from dataset_v2.contracts import instant
from dataset_v2.derive import custody_corroborated, number, proof_assessment
from operations.reasoning import evidence_world

MAX_ROWS = 30
MAX_RESULT_CHARS = 6000
OBSERVED_FIELDS = ("occurred_at", "recorded_at")


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _lag_minutes(p):
    try:
        return round((instant(p["recorded_at"]) - instant(p["occurred_at"])).total_seconds() / 60)
    except (KeyError, TypeError, ValueError):
        return None


class InvestigationTools:
    """One investigation's tool belt. `retrieved` accumulates every evidence id a tool returned."""

    def __init__(self, context, config, *, symptoms=(), heartbeats=None, precedents=None):
        self.context, self.config = context, config
        self.sid, self.as_of = context["shipment_id"], context["as_of"]
        self.world = evidence_world(context, config)
        self.nodes = self.world.nodes
        self.cutoff = instant(self.as_of)
        self.symptoms = list(symptoms)
        self._heartbeats = heartbeats or (lambda device_id, since, until: [])
        self._precedent_source = precedents or (lambda cause: [])
        self.retrieved = set()
        self.calls = []
        self.external = {}        # retrieved records that are not shipment evidence (device heartbeats), by id
        self.device_reports = {}  # last device_status result per device

    # ------------------------------------------------------------------ catalogue
    CATALOG = {
        "shipment_overview": ({}, "Service level, promise time, packages (barcode, weight), latest visible status, case symptoms."),
        "journey": ({"package_id": "optional"}, "Expected milestones vs corroborated observations (on time, late, missing after deadline, pending)."),
        "custody_chain": ({"package_id": "required"}, "Ordered custody transfers with holders, acknowledgments, source device, event and upload times."),
        "scans": ({"package_id": "optional"}, "Barcode reads and calibrated weights compared with the manifest and policy tolerance."),
        "delivery_attempts": ({}, "Attempts, contact logs, proof-of-delivery components with corroboration checks, recipient reports."),
        "vehicle_and_manifest": ({}, "Planned assignments (driver employment, provider, vehicle ownership), dispatch manifest versions, vehicle GPS (vehicle position only)."),
        "device_status": ({"device_id": "required", "hours": "optional, default 24"}, "Device heartbeats recorded by now: reporting state (REPORTING or SILENT), last seen, missed beats, pending uploads."),
        "address_and_instructions": ({}, "Address versions with validity intervals, delivery instructions and gate, recipient pins."),
        "policy": ({}, "Policy thresholds (barcode confidence, weight tolerance, retry limit) and service tolerance."),
        "precedents": ({"cause": "required cause code"}, "Verified historical outcomes for a hypothesized cause: actions tried and whether verification confirmed success."),
    }

    def describe(self):
        return [{"tool": name, "args": args, "returns": text} for name, (args, text) in self.CATALOG.items()]

    def call(self, tool, args):
        if tool not in self.CATALOG:
            return {"error": f"unknown tool {tool}"}
        args = args if isinstance(args, dict) else {}
        try:
            result = getattr(self, "_" + tool)(**{k: v for k, v in args.items() if k in ("package_id", "device_id", "hours", "cause")})
        except (TypeError, ValueError, KeyError) as error:
            result = {"error": f"invalid arguments ({type(error).__name__})"}
        ids = sorted(set(result.pop("evidence_ids", [])))
        self.retrieved.update(ids)
        text = json.dumps(result, default=str, ensure_ascii=False)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + '..."TRUNCATED"'
        text += " CITABLE_EVIDENCE_IDS: " + json.dumps(ids[:80])
        self.calls.append({"tool": tool, "args": args, "evidence_ids": ids})
        return {"result": text, "evidence_ids": ids}

    # ------------------------------------------------------------------ helpers
    def _kind(self, kind, package_id=None):
        rows = [n for n in self.nodes.values() if n.kind == kind and (package_id is None or n.properties.get("package_id") == package_id)]
        return sorted(rows, key=lambda n: (str(n.properties.get("occurred_at") or ""), n.id))

    def _times(self, p):
        return {"occurred_at": _iso(p.get("occurred_at")), "recorded_at": _iso(p.get("recorded_at")), "upload_lag_minutes": _lag_minutes(p)}

    def _packages(self):
        return [n for n in self.nodes.values() if n.kind == "Package"]

    def _package(self, package_id):
        node = self.nodes.get(package_id)
        if node is None or node.kind != "Package":
            raise ValueError("package_id is not a package of this shipment")
        return node

    # ------------------------------------------------------------------ tools
    def _shipment_overview(self):
        shipment = self.nodes[self.sid].properties
        plan = self.nodes.get(shipment.get("journey_id"))
        service = self.nodes.get((plan.properties if plan else {}).get("service_id"))
        statuses = self._kind("StatusEvent")
        ids = [self.sid, *[p.id for p in self._packages()]] + ([plan.id] if plan else []) + ([statuses[-1].id] if statuses else [])
        return {"shipment_id": self.sid, "as_of": self.as_of, "case_symptoms": self.symptoms,
                "flow_type": shipment.get("flow_type"), "origin_city": shipment.get("origin_city"), "destination_city": shipment.get("destination_city"),
                "service_level": (service.properties.get("name") if service else None), "promise_at": _iso((plan.properties if plan else {}).get("promise_at")),
                "latest_status": statuses[-1].properties.get("status") if statuses else "CREATED",
                "packages": [{"package_id": p.id, "manifest_barcode": p.properties.get("manifest_barcode"),
                              "weight_kg": p.properties.get("weight_kg"), "handling": p.properties.get("handling")} for p in self._packages()],
                "evidence_ids": ids}

    def _journey(self, package_id=None):
        rows, ids = [], []
        packages = [self._package(package_id)] if package_id else self._packages()
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
                facility = location is not None and location.kind in ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse")
                rows.append({"package_id": package.id, "milestone_id": milestone.id, "predicate": mp.get("predicate"),
                             "location_id": mp.get("location_id"), "location_kind": location.kind if location else None,
                             "facility_handheld": ("DEMO-DEV-HH-" + location.id.removeprefix("DEMO-")) if facility else None,
                             "latest_at": _iso(mp.get("latest_at")), "observed_at": _iso(observed), "state": state,
                             "observation_ids": [e.id for e in hits]})
                ids += [milestone.id, *[e.id for e in hits]]
        return {"milestones": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS, "evidence_ids": ids}

    def _custody_chain(self, package_id):
        package = self._package(package_id)
        rows, ids = [], []
        for event in self._kind("CustodyEvent", package.id):
            p = event.properties
            source = self.nodes.get(p.get("source_event_id"))
            holder = self.nodes.get(p.get("to_id"))
            rows.append({"event_id": event.id, "event_type": p.get("event_type"), "from_id": p.get("from_id"), "to_id": p.get("to_id"),
                         "to_kind": holder.kind if holder else None, "acknowledgments": f"{p.get('received_acknowledgments')}/{p.get('required_acknowledgments')}",
                         "source_quality": p.get("source_quality"), "corroborated": custody_corroborated(self.world, event, self.cutoff),
                         "source_scan_id": source.id if source else None, "device_ref": (source.properties.get("device_ref") if source else None),
                         "observation_type": (source.properties.get("observation_type") if source else None),
                         "channel": p.get("channel"), **self._times(p)})
            ids += [event.id] + ([source.id] if source else [])
        return {"package_id": package.id, "transfers": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS, "evidence_ids": ids}

    def _scans(self, package_id=None):
        policy = self.nodes.get(self.nodes[self.sid].properties.get("policy_id"))
        pp = policy.properties if policy else {}
        rows, ids = [], []
        for package in ([self._package(package_id)] if package_id else self._packages()):
            manifest = package.properties
            for scan in self._kind("ScanEvent", package.id):
                sp = scan.properties
                row = {"scan_id": scan.id, "package_id": package.id, "device_ref": sp.get("device_ref"), "observation_type": sp.get("observation_type"),
                       "readable": sp.get("readable"), "confidence": sp.get("confidence"), **self._times(sp)}
                if sp.get("observed_barcode") is not None:
                    row.update(observed_barcode=sp["observed_barcode"], manifest_barcode=manifest.get("manifest_barcode"),
                               barcode_matches=sp["observed_barcode"] == manifest.get("manifest_barcode"))
                measured, expected = number(sp.get("measured_weight_kg")), number(manifest.get("weight_kg"))
                if sp.get("calibrated") is True and measured is not None and expected is not None:
                    tolerance = max(number(pp.get("weight_absolute_kg")) or 0, expected * (number(pp.get("weight_relative_fraction")) or 0))
                    row.update(measured_weight_kg=measured, manifest_weight_kg=expected, tolerance_kg=round(tolerance, 3),
                               weight_within_tolerance=abs(measured - expected) <= tolerance + 1e-9)
                rows.append(row)
                ids.append(scan.id)
        return {"scans": rows[:MAX_ROWS], "barcode_min_confidence": pp.get("barcode_min_confidence"), "truncated": len(rows) > MAX_ROWS,
                "evidence_ids": ids}

    def _delivery_attempts(self):
        rows, ids = [], []
        for attempt in self._kind("DeliveryAttempt"):
            ap = attempt.properties
            contacts = [c for c in self._kind("ContactAttempt") if c.properties.get("attempt_id") == attempt.id]
            proofs = [p for p in self._kind("DeliveryProof") if p.properties.get("attempt_id") == attempt.id]
            assessed = [proof_assessment(self.world, p, self.cutoff) for p in proofs]
            rows.append({"attempt_id": attempt.id, "package_id": ap.get("package_id"), "disposition": ap.get("disposition"),
                         "failed_reason": ap.get("failed_reason"), "observed_gate": ap.get("observed_gate"),
                         "used_address_version_id": ap.get("used_address_version_id"), **self._times(ap),
                         "contacts": [{"contact_id": c.id, "result": c.properties.get("result"), "occurred_at": _iso(c.properties.get("occurred_at"))} for c in contacts],
                         "proofs": [{"proof_id": a["proof_id"], "corroborated": a["corroborated"], "reasons": a["reasons"]} for a in assessed]})
            ids += [attempt.id, *[c.id for c in contacts], *[e for a in assessed for e in a["evidence_ids"]]]
        reports = [{"report_id": r.id, "package_id": r.properties.get("package_id"), "report_code": r.properties.get("report_code"),
                    "statement_en": r.properties.get("statement_en"), **self._times(r.properties)} for r in self._kind("RecipientReport")]
        recon = [{"reconciliation_id": r.id, "package_id": r.properties.get("package_id"), "result": r.properties.get("result"),
                  "session_id": r.properties.get("session_id"), **self._times(r.properties)} for r in self._kind("DepotReconciliation")]
        ids += [r["report_id"] for r in reports] + [r["reconciliation_id"] for r in recon]
        return {"attempts": rows[:MAX_ROWS], "recipient_reports": reports, "depot_reconciliations": recon, "evidence_ids": ids}

    def _vehicle_and_manifest(self):
        rows, ids = [], []
        for assignment in sorted((n for n in self.nodes.values() if n.kind == "VehicleAssignment"), key=lambda n: str(n.properties.get("valid_from"))):
            ap = assignment.properties
            vehicle = self.nodes.get(ap.get("vehicle_id"))
            driver = self.nodes.get(ap.get("driver_id"))
            session = self.nodes.get(ap.get("session_id"))
            rows.append({"assignment_id": assignment.id, "mode": ap.get("mode"), "valid_from": _iso(ap.get("valid_from")), "valid_to": _iso(ap.get("valid_to")),
                         "vehicle_id": ap.get("vehicle_id"), "vehicle_ownership": (vehicle.properties.get("ownership") if vehicle else None),
                         "vehicle_class": (vehicle.properties.get("vehicle_class") if vehicle else None),
                         "driver_id": ap.get("driver_id"), "driver_employment": (driver.properties.get("employment") if driver else None),
                         "provider_id": (driver.properties.get("provider_id") if driver else None),
                         "driver_app_device": "DEMO-DEV-APP-" + ap["driver_id"].removeprefix("DEMO-") if ap.get("driver_id") else None,
                         "session_id": ap.get("session_id"), "session_end_at": _iso(session.properties.get("end_at")) if session else None,
                         "depot_id": session.properties.get("depot_id") if session else None})
            ids += [assignment.id] + ([session.id] if session else [])
        manifests = [{"manifest_id": m.id, "assignment_id": m.properties.get("assignment_id"), "version": m.properties.get("version"),
                      "status": m.properties.get("manifest_status"), "package_ids": m.properties.get("package_ids"),
                      "supersedes_id": m.properties.get("supersedes_id"), **self._times(m.properties)} for m in self._kind("Manifest")]
        gps = [{"gps_id": g.id, "vehicle_id": g.properties.get("vehicle_id"), "lat": g.properties.get("lat"), "lng": g.properties.get("lng"),
                "position_scope": g.properties.get("position_scope"), **self._times(g.properties)} for g in self._kind("GPSObservation")]
        ids += [m["manifest_id"] for m in manifests] + [g["gps_id"] for g in gps]
        return {"assignments": rows, "manifests": manifests, "vehicle_gps": gps[:MAX_ROWS],
                "note": "Vehicle GPS is the vehicle's position only; it never establishes where a parcel is.", "evidence_ids": ids}

    def _device_status(self, device_id, hours=24):
        hours = max(1, min(int(hours or 24), 72))
        since = self.cutoff - timedelta(hours=hours)
        beats = sorted(self._heartbeats(device_id, since.isoformat(), self.as_of), key=lambda b: str(b["occurred_at"]))[-MAX_ROWS:]
        times = [instant(_iso(b["occurred_at"])) for b in beats]
        gaps = [round((b - a).total_seconds() / 3600, 1) for a, b in zip(times, times[1:])]
        last = beats[-1] if beats else None
        for b in beats:
            self.external[b["entity_id"]] = {"device_id": device_id, "seen_at": _iso(b["occurred_at"]),
                                             "pending_uploads": b.get("pending_uploads"), "last_upload_at": _iso(b.get("last_upload_at"))}
        self.external[device_id] = {"device_id": device_id, "kind": "Device"}
        missed = None
        report = {"device_id": device_id, "window_hours": hours, "heartbeats": len(beats),
                "last_seen_at": _iso(last["occurred_at"]) if last else None,
                "hours_since_last_seen": round((self.cutoff - times[-1]).total_seconds() / 3600, 1) if times else None,
                "last_pending_uploads": last.get("pending_uploads") if last else None,
                "largest_gap_hours": max(gaps, default=None),
                "typical_interval_minutes": round(sorted(gaps)[len(gaps) // 2] * 60) if gaps else None,
                "expected_beats_missed_since_last_seen": (int((self.cutoff - times[-1]).total_seconds() // (sorted(gaps)[len(gaps) // 2] * 3600))
                                                          if gaps and sorted(gaps)[len(gaps) // 2] > 0 else None),
                "series": [{"id": b["entity_id"], "seen_at": _iso(b["occurred_at"]), "pending_uploads": b.get("pending_uploads")} for b in beats[-8:]],
                "evidence_ids": [device_id, *[b["entity_id"] for b in beats]]}
        missed = report["expected_beats_missed_since_last_seen"]
        report = {"reporting_state": ("NO_TELEMETRY" if not beats else "SILENT" if missed is not None and missed >= 3 else "REPORTING"),
                  **report, "telemetry_semantics": ("A SILENT device has sent nothing since last_seen_at. Scans it made since then are not visible "
                  "until it reconnects. pending_uploads values were reported before the silence began.")}
        self.device_reports[device_id] = {k: v for k, v in report.items() if k != "evidence_ids"}
        # A cited device id stands for this telemetry summary, so a reviewer reads the same facts.
        self.external[device_id] = {"kind": "Device", **{k: v for k, v in report.items() if k not in ("evidence_ids", "series")}}
        return report

    def _address_and_instructions(self):
        versions = [{"address_version_id": n.id, "version": n.properties.get("version"), "valid_from": _iso(n.properties.get("valid_from")),
                     "valid_to": _iso(n.properties.get("valid_to")), "verification_status": n.properties.get("verification_status")}
                    for n in self.nodes.values() if n.kind == "AddressVersion"]
        instructions = [{"instruction_id": n.id, "address_version_id": n.properties.get("address_version_id"), "gate": n.properties.get("gate"),
                         "valid_from": _iso(n.properties.get("valid_from"))} for n in self.nodes.values() if n.kind == "DeliveryInstruction"]
        pins = [{"pin_id": n.id, "address_version_id": n.properties.get("address_version_id"), **self._times(n.properties)} for n in self._kind("LocationPin")]
        return {"address_versions": versions, "instructions": instructions, "pins": pins,
                "evidence_ids": [v["address_version_id"] for v in versions] + [i["instruction_id"] for i in instructions] + [p["pin_id"] for p in pins]}

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
        rows = list(self._precedent_source(cause))[:8]
        tally = {}
        for row in rows:
            entry = tally.setdefault(row.get("action_type"), {"verified_success": 0, "verified_failure": 0})
            entry["verified_success" if row.get("success") else "verified_failure"] += 1
        return {"cause": cause, "verified_outcomes": [{"case_id": r.get("case_id"), "action_type": r.get("action_type"), "success": r.get("success"),
                                                        "verified_at": _iso(r.get("verified_at"))} for r in rows],
                "by_action": tally, "note": "Only independently verified, non-invalidated outcomes recorded before this investigation.",
                "evidence_ids": []}
