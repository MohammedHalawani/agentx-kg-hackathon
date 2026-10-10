"""A small mechanism world as Suhail would hold it, and an in-memory reference for the reader's world queries.

No database. The world is built once per test process (about half a minute), cut into the development export,
and every feed message is decoded onto the import with recorded_at = its delivery time (what the gateway records).
Relationships of fed records are created by the gateway's own EDGE_RULES, so a shipment's evidence context holds
what the read model would load from Neo4j.

  small_world()    the cached world with its truth rows (tests only; nothing here is reachable from operations)
  ReaderLike       evidence(), heartbeats(), precedents() and fetch() with the read model's semantics
  MemoryPort       every operations.cross_shipment query, implemented over the in-memory records. It is the
                   reference the Neo4j integration tests compare the Cypher against.
"""
from collections import defaultdict
from functools import lru_cache
from types import SimpleNamespace

from dataset_v2.contracts import Edge, World, digest, instant
from dataset_v2.context import CATALOG, CONTEXT, OBSERVATIONS
from operations import cross_shipment
from operations.reasoning import public_evidence

SCOPE = ("development", "history", "shared")


def world_config():
    from world.config import WorldConfig, uniform_rates
    return WorldConfig(total=240, seed=11, dataset_id="DEMO-SUHAIL-WORLD-TEST", rates=uniform_rates(.012, .012))


def link_like_gateway(full, imported):
    """Relationships the gateway creates when it ingests a record (operations.ingestion.EDGE_RULES)."""
    from operations.ingestion import EDGE_RULES
    for key in set(full.nodes) - set(imported.nodes):
        node = full.nodes[key]
        sid = node.properties.get("holdout_group")
        for rule_kind, prop, rel, outward in EDGE_RULES:
            if rule_kind != node.kind:
                continue
            targets = node.properties.get(prop) if prop != "shipment_id" else sid
            for target in (targets if isinstance(targets, list) else [targets]):
                if isinstance(target, str) and target.startswith("DEMO-") and target in full.nodes:
                    start, end = (key, target) if outward else (target, key)
                    edge_id = "DEMO-EDGE-" + digest([start, rel, end, "live-ingestion-1"])[:24]
                    full.edges[edge_id] = Edge(edge_id, rel, start, end, {"edge_id": edge_id, "holdout_group": sid,
                                                                         "recorded_at": node.properties["recorded_at"]})
    return full


@lru_cache(maxsize=1)
def small_world():
    from dataset_v2.feed import reconstitute
    from world.build import build_world, export_bundle
    build = build_world(world_config())
    imported, items, truth, live_start = export_bundle(build, "development")
    full = link_like_gateway(reconstitute(imported, items), imported)
    return SimpleNamespace(build=build, imported=imported, items=items, truth=truth, live_start=live_start, world=full,
                           reader=ReaderLike(full))


def _at(value):
    return instant(value) if isinstance(value, str) else value


def _visible(p, as_of):
    return _at(p["recorded_at"]) <= as_of and (p.get("occurred_at") is None or _at(p["occurred_at"]) <= as_of)


def _props(node):
    return {k: v for k, v in node.properties.items() if v is not None}


class MemoryPort:
    """operations.cross_shipment.QUERIES over in-memory records: same parameters, scope, time predicate, order, limit."""

    def __init__(self, world, clock=None):
        self.world = world
        self.clock = clock or (lambda: world.config.as_of)
        self.kinds = defaultdict(list)
        self.owned = defaultdict(list)
        for node in world.nodes.values():
            if node.properties.get("split") in SCOPE:
                self.kinds[node.kind].append(node)
                if node.properties.get("holdout_group"):
                    self.owned[node.properties["holdout_group"]].append(node)
        self.calls = []

    def fetch(self, name, **params):
        cleaned = cross_shipment.clean_params(name, params, self.clock())
        self.calls.append((name, cleaned))
        as_of = instant(cleaned.pop("as_of"))
        for key in ("from_at", "to_at"):
            if key in cleaned:
                cleaned[key] = instant(cleaned[key])
        return getattr(self, "_" + name)(as_of=as_of, **cleaned)

    __call__ = fetch

    # ------------------------------------------------------------------ helpers
    def _rows(self, kind, as_of, where, *, order, limit):
        nodes = [n for n in self.kinds[kind] if _visible(n.properties, as_of) and where(n.properties)]
        return [{"props": _props(n)} for n in sorted(nodes, key=order)[:limit]]

    @staticmethod
    def _time_id(field="occurred_at", reverse=False):
        return lambda n: (_at(n.properties[field]), n.id)

    def _by_reference(self, kind, prop, ref, as_of, limit, order=None):
        return self._rows(kind, as_of, lambda p: p.get(prop) == ref, order=order or self._time_id(), limit=limit)

    def _device_window(self, ref, from_at, to_at, as_of):
        return [n for n in self.kinds["ScanEvent"] if n.properties.get("device_ref") == ref and _visible(n.properties, as_of)
                and from_at <= _at(n.properties["occurred_at"]) <= to_at]

    @staticmethod
    def _late(p, late_seconds):
        return (_at(p["recorded_at"]) - _at(p["occurred_at"])).total_seconds() >= late_seconds

    # ------------------------------------------------------------------ shared records
    def _shared_record(self, ref, as_of, kinds, limit):
        node = self.world.nodes.get(ref)
        if node is None or node.properties.get("split") != "shared" or node.kind not in kinds or not _visible(node.properties, as_of):
            return []
        return [{"props": _props(node), "kind": node.kind}]

    def _facility_devices(self, ref, as_of, limit):
        return self._rows("Device", as_of, lambda p: p.get("facility_id") == ref, order=lambda n: n.id, limit=limit)

    def _package_by_barcode(self, text, as_of, limit):
        nodes = sorted((n for n in self.kinds["Package"] if n.properties.get("manifest_barcode") == text and _visible(n.properties, as_of)),
                       key=lambda n: n.id)[:limit]
        return [{"package_id": n.id, "shipment_id": n.properties.get("shipment_id"), "recorded_at": n.properties["recorded_at"]} for n in nodes]

    # ------------------------------------------------------------------ one device
    def _device_heartbeats(self, ref, from_at, to_at, as_of, limit):
        nodes = [n for n in self.kinds["DeviceHeartbeat"] if n.properties.get("device_id") == ref and _visible(n.properties, as_of)
                 and from_at <= _at(n.properties["occurred_at"]) <= to_at]
        nodes.sort(key=lambda n: (_at(n.properties["occurred_at"]), n.id), reverse=True)
        return [{"entity_id": n.id, "occurred_at": n.properties["occurred_at"], "recorded_at": n.properties["recorded_at"],
                 "pending_uploads": n.properties.get("pending_uploads"), "last_upload_at": n.properties.get("last_upload_at"),
                 "connectivity": n.properties.get("connectivity")} for n in nodes[:limit]]

    def _device_scan_counts(self, ref, from_at, to_at, late_seconds, as_of, limit):
        nodes = self._device_window(ref, from_at, to_at, as_of)
        late = [n for n in nodes if self._late(n.properties, late_seconds)]
        return [{"records": len(nodes), "shipments": len({n.properties.get("shipment_id") for n in nodes}), "late_records": len(late),
                 "late_shipments": len({n.properties.get("shipment_id") for n in late}),
                 "first_occurred_at": min((n.properties["occurred_at"] for n in nodes), key=_at, default=None),
                 "last_occurred_at": max((n.properties["occurred_at"] for n in nodes), key=_at, default=None),
                 "latest_recorded_at": max((n.properties["recorded_at"] for n in nodes), key=_at, default=None)}]

    def _device_scans(self, ref, from_at, to_at, as_of, limit):
        nodes = sorted(self._device_window(ref, from_at, to_at, as_of), key=self._time_id(), reverse=True)
        return [{"props": _props(n)} for n in nodes[:limit]]

    def _device_late_scans(self, ref, from_at, to_at, late_seconds, as_of, limit):
        nodes = sorted((n for n in self._device_window(ref, from_at, to_at, as_of) if self._late(n.properties, late_seconds)), key=self._time_id())
        return [{"props": _props(n)} for n in nodes[:limit]]

    def _device_measurements(self, ref, from_at, to_at, as_of, limit):
        rows = []
        for n in sorted(self._device_window(ref, from_at, to_at, as_of), key=self._time_id()):
            p = n.properties
            package = self.world.nodes.get(p.get("package_id"))
            if (p.get("observed_barcode") is None and p.get("measured_weight_kg") is None) or package is None \
                    or package.properties.get("split") not in SCOPE or _at(package.properties["recorded_at"]) > as_of:
                continue
            rows.append({"scan_id": n.id, "shipment_id": p.get("shipment_id"), "package_id": p.get("package_id"), "occurred_at": p["occurred_at"],
                         "recorded_at": p["recorded_at"], "observation_type": p.get("observation_type"), "readable": p.get("readable"),
                         "confidence": p.get("confidence"), "calibrated": p.get("calibrated"), "observed_barcode": p.get("observed_barcode"),
                         "manifest_barcode": package.properties.get("manifest_barcode"), "measured_weight_kg": p.get("measured_weight_kg"),
                         "declared_weight_kg": package.properties.get("weight_kg")})
        return rows[:limit]

    def _device_route_runs(self, ref, from_at, to_at, as_of, limit):
        nodes = [n for n in self.kinds["RouteRun"] if n.properties.get("device_ref") == ref and _visible(n.properties, as_of)
                 and _at(n.properties["start_at"]) <= to_at and _at(n.properties["end_at"]) >= from_at]
        nodes.sort(key=lambda n: n.id)
        nodes.sort(key=lambda n: _at(n.properties["start_at"]), reverse=True)
        return [{"props": _props(n)} for n in nodes[:limit]]

    # ------------------------------------------------------------------ one facility
    def _overdue(self, ref, shipment_id, from_at, allowance, as_of):
        from datetime import timedelta
        rows = []
        for m in self.kinds["ExpectedMilestone"]:
            p = m.properties
            if p.get("location_id") != ref or _at(p["recorded_at"]) > as_of or p.get("shipment_id") == shipment_id:
                continue
            latest = _at(p["latest_at"])
            if latest < from_at or not latest + timedelta(seconds=(p.get("grace_seconds") or 0) + allowance) < as_of:
                continue
            seen = any(e.kind == "CustodyEvent" and e.properties.get("package_id") == p.get("package_id")
                       and e.properties.get("event_type") == p.get("predicate")
                       and ref in (e.properties.get("facility_id"), e.properties.get("to_id")) and _visible(e.properties, as_of)
                       for e in self.owned[p.get("holdout_group")])
            if not seen:
                rows.append(m)
        return rows

    def _overdue_at_facility(self, ref, shipment_id, from_at, allowance, as_of, limit):
        rows = sorted(self._overdue(ref, shipment_id, from_at, allowance, as_of), key=lambda m: m.id)
        rows.sort(key=lambda m: _at(m.properties["latest_at"]), reverse=True)
        return [{"milestone_id": m.id, "shipment_id": m.properties.get("shipment_id"), "package_id": m.properties.get("package_id"),
                 "predicate": m.properties.get("predicate"), "latest_at": m.properties["latest_at"], "recorded_at": m.properties["recorded_at"]}
                for m in rows[:limit]]

    def _overdue_at_facility_counts(self, ref, shipment_id, from_at, allowance, as_of, limit):
        groups = defaultdict(list)
        for m in self._overdue(ref, shipment_id, from_at, allowance, as_of):
            groups[m.properties.get("predicate")].append(m)
        return [{"predicate": k, "milestones": len(v), "shipments": len({m.properties.get("shipment_id") for m in v})} for k, v in sorted(groups.items())][:limit]

    def _facility_throughput(self, ref, from_at, to_at, as_of, limit):
        return self._rows("FacilityThroughput", as_of, lambda p: p.get("facility_id") == ref and from_at <= _at(p["start_at"]) <= to_at,
                          order=self._time_id("start_at"), limit=limit)

    def _facility_custody_counts(self, ref, from_at, to_at, as_of, limit):
        groups = defaultdict(list)
        for n in self.kinds["CustodyEvent"]:
            p = n.properties
            if p.get("facility_id") == ref and _visible(p, as_of) and from_at <= _at(p["occurred_at"]) <= to_at:
                groups[p.get("event_type")].append(p)
        return [{"event_type": k, "parcels": len({p.get("package_id") for p in v}), "shipments": len({p.get("shipment_id") for p in v}),
                 "latest_recorded_at": max((p["recorded_at"] for p in v), key=_at)} for k, v in sorted(groups.items())][:limit]

    # ------------------------------------------------------------------ one route run, container, trip
    def _route_run_assignments(self, ref, as_of, limit):
        return self._by_reference("VehicleAssignment", "route_run_id", ref, as_of, limit, order=lambda n: (n.properties.get("shipment_id"), n.id))

    def _route_run_custody(self, ref, as_of, limit):
        return self._by_reference("CustodyEvent", "route_run_id", ref, as_of, limit)

    def _route_run_attempts(self, ref, as_of, limit):
        return self._by_reference("DeliveryAttempt", "route_run_id", ref, as_of, limit)

    def _route_run_scans(self, ref, as_of, limit):
        return self._by_reference("ScanEvent", "route_run_id", ref, as_of, limit)

    def _route_run_reconciliations(self, ref, as_of, limit):
        return self._by_reference("DepotReconciliation", "route_run_id", ref, as_of, limit)

    def _route_run_manifests(self, ref, as_of, limit):
        return self._by_reference("Manifest", "route_manifest_ref", ref, as_of, limit, order=lambda n: (n.properties.get("version"), n.id))

    def _container_scans(self, ref, as_of, limit):
        return self._by_reference("ScanEvent", "container_id", ref, as_of, limit)

    def _trip_events(self, ref, as_of, limit):
        return self._by_reference("TripEvent", "trip_id", ref, as_of, limit)

    def _trip_positions(self, ref, as_of, limit):
        return self._by_reference("GPSObservation", "trip_id", ref, as_of, limit)

    def _trip_custody(self, ref, as_of, limit):
        return self._by_reference("CustodyEvent", "trip_id", ref, as_of, limit)

    def _trip_containers(self, ref, as_of, limit):
        groups = defaultdict(list)
        for n in self.kinds["ScanEvent"]:
            p = n.properties
            if p.get("trip_id") == ref and p.get("container_id") is not None and _visible(p, as_of):
                groups[p["container_id"]].append(p)
        return [{"container_id": k, "parcels": len({p.get("package_id") for p in v}), "shipments": len({p.get("shipment_id") for p in v}),
                 "first_scan_at": min((p["occurred_at"] for p in v), key=_at), "last_scan_at": max((p["occurred_at"] for p in v), key=_at),
                 "latest_recorded_at": max((p["recorded_at"] for p in v), key=_at)} for k, v in sorted(groups.items())][:limit]

    def _last_custody(self, shipment_ids, as_of, limit):
        latest = {}
        for sid in shipment_ids:
            for n in self.owned[sid]:
                if n.kind == "CustodyEvent" and _visible(n.properties, as_of):
                    key = n.properties.get("package_id")
                    if key not in latest or (_at(n.properties["occurred_at"]), n.id) > (_at(latest[key].properties["occurred_at"]), latest[key].id):
                        latest[key] = n
        return [{"props": _props(latest[k])} for k in sorted(latest)][:limit]

    # ------------------------------------------------------------------ messaging route, road conditions
    def _sms(self, text, from_at, to_at, as_of):
        return [n for n in self.kinds["CommunicationEvent"] if n.properties.get("carrier_route") == text and _visible(n.properties, as_of)
                and from_at <= _at(n.properties["occurred_at"]) <= to_at]

    def _sms_route_counts(self, text, from_at, to_at, as_of, limit):
        groups = defaultdict(list)
        for n in self._sms(text, from_at, to_at, as_of):
            groups[(n.properties.get("purpose"), n.properties.get("delivery_status"))].append(n.properties)
        return [{"purpose": k[0], "delivery_status": k[1], "messages": len(v), "shipments": len({p.get("shipment_id") for p in v}),
                 "latest_recorded_at": max((p["recorded_at"] for p in v), key=_at)} for k, v in sorted(groups.items())][:limit]

    def _sms_route_failures(self, text, from_at, to_at, as_of, limit):
        nodes = sorted((n for n in self._sms(text, from_at, to_at, as_of) if n.properties.get("delivery_status") == "FAILED"), key=self._time_id())
        return [{"props": _props(n)} for n in nodes[:limit]]

    def _traffic_events(self, ref, from_at, as_of, limit):
        nodes = [n for n in self.kinds["TrafficEvent"] if n.properties.get("city_id") == ref and _visible(n.properties, as_of)
                 and _at(n.properties["start_at"]) <= as_of and _at(n.properties["end_at"]) >= from_at]
        nodes.sort(key=lambda n: n.id)
        nodes.sort(key=lambda n: _at(n.properties["start_at"]), reverse=True)
        return [{"props": _props(n)} for n in nodes[:limit]]


class ReaderLike:
    """The read model's evidence loading over the in-memory world: a shipment's own records plus the shared catalogue
    records its visible records reference (and their type and city), recorded by the snapshot."""

    def __init__(self, world):
        self.world = world
        self.port = MemoryPort(world)
        self.owned = defaultdict(list)
        self.links = defaultdict(list)
        for node in world.nodes.values():
            if node.properties.get("holdout_group"):
                self.owned[node.properties["holdout_group"]].append(node)
        for edge in world.edges.values():
            self.links[edge.start].append(edge)
            self.links[edge.end].append(edge)

    def evidence(self, sid, as_of):
        full = self.world
        owned = [n for n in self.owned[sid] if n.kind in CONTEXT | OBSERVATIONS]
        visible = [n for n in owned if n.properties["recorded_at"] <= as_of
                   and (n.kind not in OBSERVATIONS or n.properties.get("occurred_at", "") <= as_of)]
        references = set()
        for node in visible:
            for value in node.properties.values():
                for candidate in (value if isinstance(value, list) else [value]):
                    if isinstance(candidate, str) and candidate.startswith("DEMO-"):
                        references.add(candidate)

        def catalog(node):
            return node.properties.get("split") == "shared" and node.kind in CATALOG and node.properties["recorded_at"] <= as_of
        shared = {r: full.nodes[r] for r in references if r in full.nodes and catalog(full.nodes[r])}
        frontier = [r for r in references if r in full.nodes and full.nodes[r].properties.get("split") == "shared"]
        for _ in range(2):
            following = []
            for root in frontier:
                for edge in self.links[root]:
                    if edge.start == root and edge.kind in ("HAS_TYPE", "IN_CITY"):
                        target = full.nodes[edge.end]
                        if target.properties.get("split") == "shared":
                            following.append(target.id)
                            if catalog(target):
                                shared[target.id] = target
            frontier = following
        world = World(full.config)
        for node in [*owned, *shared.values()]:
            world.nodes[node.id] = node
        for key in list(world.nodes):
            for edge in self.links[key]:
                if edge.start in world.nodes and edge.end in world.nodes and edge.properties.get("holdout_group") in (None, sid):
                    world.edges[edge.id] = edge
        return public_evidence(world, sid, as_of)

    def heartbeats(self, device_id, since, until):
        return [{"entity_id": r["entity_id"], **{k: v for k, v in r.items() if k != "entity_id"}}
                for r in self.port.fetch("device_heartbeats", ref=device_id, from_at=since, to_at=until, as_of=until, limit=240)]

    def fetch(self, name, **params):
        return self.port.fetch(name, **params)

    def historical_precedents(self, sid, codes, as_of=None):
        return []

    def precedents(self, sid, codes, as_of=None):
        return []
