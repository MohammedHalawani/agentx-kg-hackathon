"""Fixed, parameterised, read-only Cypher for evidence beyond one shipment's own records.

The investigation tools ask their questions through `OperationsReader.fetch(name, **params)`; the model never
supplies Cypher, labels or property names. Every query here

- reads one dataset and only its live (development), history and shared records, never a held-out split;
- returns a record only when Suhail had recorded it by the investigation snapshot and it had happened by then
  (`visible()`, the one time-correct predicate; the same text as the world package's);
- is bounded by a LIMIT whose value the reader clamps.

`QUERIES` is the whole catalogue. `clean_params` validates the arguments of one call. Tests run every query
against an in-memory reference port and, when a Neo4j server is available, against the database.
"""
from dataclasses import dataclass

from dataset_v2.contracts import instant

MAX_LIMIT = 400
# Shared records a tool may look up by id (plan and catalogue data several shipments reference).
SHARED_KINDS = ("Branch", "City", "Container", "DeliveryDepot", "Device", "Driver", "FulfillmentWarehouse", "Hub", "Lane",
                "OrganizationWarehouse", "Provider", "RouteRun", "SortingCenter", "Trip", "Vehicle")


def visible(alias):
    """THE time-correct predicate: recorded by Suhail at or before the snapshot, and occurred at or before it."""
    return f"{alias}.recorded_at <= $as_of AND ({alias}.occurred_at IS NULL OR {alias}.occurred_at <= $as_of)"


def in_scope(alias):
    """This dataset; live, history and shared records only (a held-out split is never read)."""
    return f"{alias}.dataset_id = $dataset_id AND {alias}.split IN ['development','history','shared']"


@dataclass(frozen=True)
class Query:
    cypher: str
    ids: tuple = ()        # parameters that must be DEMO- identities
    times: tuple = ()      # parameters that must be UTC instants at or before the snapshot
    numbers: tuple = ()    # non-negative integers
    texts: tuple = ()      # short plain strings (a barcode, a carrier route)
    id_lists: tuple = ()   # bounded lists of DEMO- identities
    limit: int = 100       # the most rows a caller may ask for


def _by_reference(label, prop, *, order="n.occurred_at, n.entity_id", limit=200):
    """Records of one kind that name a shared reference (a route run, trip, container, device or facility)."""
    return Query(f"MATCH (n:V2Entity:{label}) WHERE n.{prop} = $ref AND {in_scope('n')} AND {visible('n')} "
                 f"RETURN properties(n) AS props ORDER BY {order} LIMIT $limit", ids=("ref",), limit=limit)


def _in_window(label, prop, time, *, limit=200, order=None):
    return Query(f"MATCH (n:V2Entity:{label}) WHERE n.{prop} = $ref AND n.{time} >= $from_at AND n.{time} <= $to_at "
                 f"AND {in_scope('n')} AND {visible('n')} "
                 f"RETURN properties(n) AS props ORDER BY {order or 'n.' + time + ', n.entity_id'} LIMIT $limit",
                 ids=("ref",), times=("from_at", "to_at"), limit=limit)


_LATE = "n.recorded_at >= n.occurred_at + duration({seconds:$late_seconds})"
_OVERDUE = (f"MATCH (m:V2Entity:ExpectedMilestone) WHERE m.location_id = $ref AND {in_scope('m')} AND m.recorded_at <= $as_of "
            "AND m.shipment_id <> $shipment_id AND m.latest_at >= $from_at "
            "AND m.latest_at + duration({seconds:coalesce(m.grace_seconds,0) + $allowance}) < $as_of "
            "AND NOT EXISTS { MATCH (e:V2Entity:CustodyEvent {holdout_group:m.holdout_group}) "
            "WHERE e.package_id = m.package_id AND e.event_type = m.predicate "
            f"AND (e.facility_id = m.location_id OR e.to_id = m.location_id) AND {in_scope('e')} AND {visible('e')} }} ")
_DEVICE_WINDOW = (f"MATCH (n:V2Entity:ScanEvent) WHERE n.device_ref = $ref AND n.occurred_at >= $from_at AND n.occurred_at <= $to_at "
                  f"AND {in_scope('n')} AND {visible('n')} ")

QUERIES = {
    # ------------------------------------------------------------------ shared records by id
    "shared_record": Query(f"MATCH (n:V2Entity {{entity_id:$ref}}) WHERE {in_scope('n')} AND n.split = 'shared' AND {visible('n')} "
                           "AND any(k IN labels(n) WHERE k IN $kinds) "
                           "RETURN properties(n) AS props, [k IN labels(n) WHERE k IN $kinds][0] AS kind LIMIT $limit", ids=("ref",), limit=1),
    "facility_devices": Query(f"MATCH (n:V2Entity:Device) WHERE n.facility_id = $ref AND {in_scope('n')} AND {visible('n')} "
                              "RETURN properties(n) AS props ORDER BY n.entity_id LIMIT $limit", ids=("ref",), limit=12),
    "package_by_barcode": Query(f"MATCH (n:V2Entity:Package) WHERE n.manifest_barcode = $text AND {in_scope('n')} AND {visible('n')} "
                                "RETURN n.entity_id AS package_id, n.shipment_id AS shipment_id, n.recorded_at AS recorded_at "
                                "ORDER BY n.entity_id LIMIT $limit", texts=("text",), limit=3),
    # ------------------------------------------------------------------ one device
    "device_heartbeats": Query(f"MATCH (n:V2Entity:DeviceHeartbeat) WHERE n.device_id = $ref AND n.occurred_at >= $from_at "
                               f"AND n.occurred_at <= $to_at AND {in_scope('n')} AND {visible('n')} "
                               "RETURN n.entity_id AS entity_id, n.occurred_at AS occurred_at, n.recorded_at AS recorded_at, "
                               "n.pending_uploads AS pending_uploads, n.last_upload_at AS last_upload_at, n.connectivity AS connectivity "
                               "ORDER BY n.occurred_at DESC, n.entity_id DESC LIMIT $limit",
                               ids=("ref",), times=("from_at", "to_at"), limit=240),
    "device_scan_counts": Query(_DEVICE_WINDOW +
                                "RETURN count(n) AS records, count(DISTINCT n.shipment_id) AS shipments, "
                                f"count(CASE WHEN {_LATE} THEN 1 END) AS late_records, "
                                f"count(DISTINCT CASE WHEN {_LATE} THEN n.shipment_id END) AS late_shipments, "
                                "min(n.occurred_at) AS first_occurred_at, max(n.occurred_at) AS last_occurred_at, "
                                "max(n.recorded_at) AS latest_recorded_at LIMIT $limit",
                                ids=("ref",), times=("from_at", "to_at"), numbers=("late_seconds",), limit=1),
    "device_scans": Query(_DEVICE_WINDOW + "RETURN properties(n) AS props ORDER BY n.occurred_at DESC, n.entity_id DESC LIMIT $limit",
                          ids=("ref",), times=("from_at", "to_at"), limit=40),
    "device_late_scans": Query(_DEVICE_WINDOW + f"AND {_LATE} RETURN properties(n) AS props ORDER BY n.occurred_at, n.entity_id LIMIT $limit",
                               ids=("ref",), times=("from_at", "to_at"), numbers=("late_seconds",), limit=40),
    # Reads and weighings made through one device, each with the declaration it is compared against.
    "device_measurements": Query(_DEVICE_WINDOW + "AND (n.observed_barcode IS NOT NULL OR n.measured_weight_kg IS NOT NULL) "
                                 f"MATCH (p:V2Entity:Package {{entity_id:n.package_id}}) WHERE {in_scope('p')} AND p.recorded_at <= $as_of "
                                 "RETURN n.entity_id AS scan_id, n.shipment_id AS shipment_id, n.package_id AS package_id, "
                                 "n.occurred_at AS occurred_at, n.recorded_at AS recorded_at, n.observation_type AS observation_type, "
                                 "n.readable AS readable, n.confidence AS confidence, n.calibrated AS calibrated, "
                                 "n.observed_barcode AS observed_barcode, p.manifest_barcode AS manifest_barcode, "
                                 "n.measured_weight_kg AS measured_weight_kg, p.weight_kg AS declared_weight_kg "
                                 "ORDER BY n.occurred_at, n.entity_id LIMIT $limit",
                                 ids=("ref",), times=("from_at", "to_at"), limit=MAX_LIMIT),
    "device_route_runs": Query(f"MATCH (n:V2Entity:RouteRun) WHERE n.device_ref = $ref AND n.start_at <= $to_at AND n.end_at >= $from_at "
                               f"AND {in_scope('n')} AND {visible('n')} "
                               "RETURN properties(n) AS props ORDER BY n.start_at DESC, n.entity_id LIMIT $limit",
                               ids=("ref",), times=("from_at", "to_at"), limit=6),
    # ------------------------------------------------------------------ one facility
    "overdue_at_facility": Query(_OVERDUE + "RETURN m.entity_id AS milestone_id, m.shipment_id AS shipment_id, m.package_id AS package_id, "
                                 "m.predicate AS predicate, m.latest_at AS latest_at, m.recorded_at AS recorded_at "
                                 "ORDER BY m.latest_at DESC, m.entity_id LIMIT $limit",
                                 ids=("ref", "shipment_id"), times=("from_at",), numbers=("allowance",), limit=20),
    "overdue_at_facility_counts": Query(_OVERDUE + "RETURN m.predicate AS predicate, count(m) AS milestones, count(DISTINCT m.shipment_id) AS shipments "
                                        "ORDER BY predicate LIMIT $limit",
                                        ids=("ref", "shipment_id"), times=("from_at",), numbers=("allowance",), limit=8),
    "facility_throughput": _in_window("FacilityThroughput", "facility_id", "start_at", limit=72),
    "facility_custody_counts": Query(f"MATCH (n:V2Entity:CustodyEvent) WHERE n.facility_id = $ref AND n.occurred_at >= $from_at AND n.occurred_at <= $to_at "
                                     f"AND {in_scope('n')} AND {visible('n')} "
                                     "RETURN n.event_type AS event_type, count(DISTINCT n.package_id) AS parcels, count(DISTINCT n.shipment_id) AS shipments, "
                                     "max(n.recorded_at) AS latest_recorded_at ORDER BY event_type LIMIT $limit",
                                     ids=("ref",), times=("from_at", "to_at"), limit=8),
    # ------------------------------------------------------------------ one route run
    "route_run_assignments": _by_reference("VehicleAssignment", "route_run_id", order="n.shipment_id, n.entity_id", limit=80),
    "route_run_custody": _by_reference("CustodyEvent", "route_run_id", limit=300),
    "route_run_attempts": _by_reference("DeliveryAttempt", "route_run_id", limit=200),
    "route_run_scans": _by_reference("ScanEvent", "route_run_id", limit=300),
    "route_run_reconciliations": _by_reference("DepotReconciliation", "route_run_id", limit=200),
    "route_run_manifests": _by_reference("Manifest", "route_manifest_ref", order="n.version, n.entity_id", limit=200),
    # ------------------------------------------------------------------ one container, one trip
    "container_scans": _by_reference("ScanEvent", "container_id", limit=300),
    "trip_events": _by_reference("TripEvent", "trip_id", limit=40),
    "trip_positions": _by_reference("GPSObservation", "trip_id", limit=160),
    "trip_custody": _by_reference("CustodyEvent", "trip_id", limit=MAX_LIMIT),
    "trip_containers": Query(f"MATCH (n:V2Entity:ScanEvent) WHERE n.trip_id = $ref AND n.container_id IS NOT NULL AND {in_scope('n')} AND {visible('n')} "
                             "RETURN n.container_id AS container_id, count(DISTINCT n.package_id) AS parcels, count(DISTINCT n.shipment_id) AS shipments, "
                             "min(n.occurred_at) AS first_scan_at, max(n.occurred_at) AS last_scan_at, max(n.recorded_at) AS latest_recorded_at "
                             "ORDER BY container_id LIMIT $limit", ids=("ref",), limit=40),
    # Where each parcel of some shipments was last recorded (its latest visible custody record).
    "last_custody": Query(f"MATCH (n:V2Entity:CustodyEvent) WHERE n.holdout_group IN $shipment_ids AND {in_scope('n')} AND {visible('n')} "
                          "WITH n ORDER BY n.occurred_at DESC, n.entity_id DESC "
                          "WITH n.package_id AS package_id, head(collect(n)) AS latest "
                          "RETURN properties(latest) AS props ORDER BY package_id LIMIT $limit", id_lists=("shipment_ids",), limit=120),
    # ------------------------------------------------------------------ messaging route, road conditions
    "sms_route_counts": Query(f"MATCH (n:V2Entity:CommunicationEvent) WHERE n.carrier_route = $text AND n.occurred_at >= $from_at AND n.occurred_at <= $to_at "
                              f"AND {in_scope('n')} AND {visible('n')} "
                              "RETURN n.purpose AS purpose, n.delivery_status AS delivery_status, count(n) AS messages, "
                              "count(DISTINCT n.shipment_id) AS shipments, max(n.recorded_at) AS latest_recorded_at "
                              "ORDER BY purpose, delivery_status LIMIT $limit", texts=("text",), times=("from_at", "to_at"), limit=24),
    "sms_route_failures": Query(f"MATCH (n:V2Entity:CommunicationEvent) WHERE n.carrier_route = $text AND n.occurred_at >= $from_at AND n.occurred_at <= $to_at "
                                f"AND n.delivery_status = 'FAILED' AND {in_scope('n')} AND {visible('n')} "
                                "RETURN properties(n) AS props ORDER BY n.occurred_at, n.entity_id LIMIT $limit",
                                texts=("text",), times=("from_at", "to_at"), limit=12),
    "traffic_events": Query(f"MATCH (n:V2Entity:TrafficEvent) WHERE n.city_id = $ref AND n.start_at <= $as_of AND n.end_at >= $from_at "
                            f"AND {in_scope('n')} AND {visible('n')} "
                            "RETURN properties(n) AS props ORDER BY n.start_at DESC, n.entity_id LIMIT $limit",
                            ids=("ref",), times=("from_at",), limit=30),
}


def _identity(value, name):
    if not isinstance(value, str) or not value.startswith("DEMO-") or len(value) > 160:
        raise ValueError(f"Invalid identity for {name}")
    return value


def clean_params(name, params, clock):
    """Validated parameters for one fixed query. `clock`: the logical clock; a snapshot may not be ahead of it."""
    spec = QUERIES.get(name)
    if spec is None:
        raise ValueError("Unknown evidence query")
    allowed = {"as_of", "limit", *spec.ids, *spec.times, *spec.numbers, *spec.texts, *spec.id_lists}
    if set(params) - allowed or not allowed - {"limit"} <= set(params):
        raise ValueError("Evidence query parameters differ from its fixed signature")
    as_of = instant(params["as_of"])
    if as_of > instant(clock):
        raise ValueError("Evidence snapshot is ahead of the logical clock")
    cleaned = {"as_of": params["as_of"]}
    for key in spec.ids:
        cleaned[key] = _identity(params[key], key)
    for key in spec.times:
        if instant(params[key]) > as_of:
            raise ValueError("Evidence window is ahead of the snapshot")
        cleaned[key] = params[key]
    for key in spec.numbers:
        if type(params[key]) is not int or not 0 <= params[key] <= 7 * 86400:
            raise ValueError(f"Invalid number for {key}")
        cleaned[key] = params[key]
    for key in spec.texts:
        if not isinstance(params[key], str) or not 1 <= len(params[key]) <= 80:
            raise ValueError(f"Invalid text for {key}")
        cleaned[key] = params[key]
    for key in spec.id_lists:
        values = params[key]
        if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 60:
            raise ValueError(f"Invalid list for {key}")
        cleaned[key] = [_identity(v, key) for v in values]
    limit = params.get("limit", spec.limit)
    if type(limit) is not int or limit < 1:
        raise ValueError("Invalid row limit")
    cleaned["limit"] = min(limit, spec.limit, MAX_LIMIT)
    if name == "shared_record":
        cleaned["kinds"] = list(SHARED_KINDS)
    return cleaned
