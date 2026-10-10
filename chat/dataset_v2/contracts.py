"""Frozen V2 export contract. Pure Python: no DB, provider, environment or clock reads.

All generated approval, proof and outcome records are synthetic fixtures. Provenance
describes an evidence role; it never changes a synthetic fixture into a real fact.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import re

SCHEMA_VERSION = "suhail-v2.1"
GENERATOR_VERSION = "foundation-1"
POLICY_VERSION = "demo-policy-1"
DERIVATION_VERSION = "evidence-rules-1"
UTC = timezone.utc
RIYADH = timezone(timedelta(hours=3), "Asia/Riyadh")
SPLITS = ("history", "development", "held_out")


class Provenance(StrEnum):
    PUBLICLY_VERIFIED = "PUBLICLY_VERIFIED"
    REFERENCE_DATA = "REFERENCE_DATA"
    SYNTHETIC_DEMO_ASSUMPTION = "SYNTHETIC_DEMO_ASSUMPTION"
    DERIVED = "DERIVED"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    OPERATOR_DECISION = "OPERATOR_DECISION"
    VERIFIED_OUTCOME = "VERIFIED_OUTCOME"


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def digest_records(records) -> str:
    """Same canonical JSON-array digest with bounded serialization memory."""
    state=hashlib.sha256(b"[")
    first=True
    for row in records:
        if not first:state.update(b",")
        state.update(canonical(row).encode("utf-8"))
        first=False
    state.update(b"]")
    return state.hexdigest()


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Expected offset-aware UTC timestamp")
    return parsed


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Naive timestamps are not evidence")
    return value.astimezone(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Config:
    total: int = 2000
    history: int | None = None
    development: int | None = None
    held_out: int | None = None
    seed: int = 42
    normal_fraction: float = .70
    start_at: str = "2026-09-01T00:00:00+00:00"
    session_start: str = "06:00"
    session_end: str = "16:00"
    reconciliation_grace_minutes: int = 60
    simulation_days: int = 40
    dataset_id: str = "DEMO-SUHAIL-V2-FOUNDATION"

    def __post_init__(self):
        if type(self.total) is not int or not 30 <= self.total <= 100_000:
            raise ValueError("total must be an integer between 30 and 100000")
        given = (self.history, self.development, self.held_out)
        if all(value is None for value in given):
            object.__setattr__(self, "history", self.total * 3 // 5)
            object.__setattr__(self, "development", self.total // 5)
            object.__setattr__(self, "held_out", self.total - self.history - self.development)
        elif (any(type(value) is not int or value <= 0 for value in given)
              or sum(given) != self.total):
            raise ValueError("All three positive split counts must sum to total")
        if not .55 <= self.normal_fraction <= .85:
            raise ValueError("Require a majority normal and a meaningful abnormal minority")
        if type(self.seed) is not int or type(self.simulation_days) is not int or self.simulation_days < 2:
            raise ValueError("Invalid deterministic seed or simulation span")
        instant(self.start_at)
        if not re.fullmatch(r"DEMO-[A-Z0-9-]+", self.dataset_id):
            raise ValueError("Dataset identity must explicitly be DEMO")
        for value in (self.session_start, self.session_end):
            if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
                raise ValueError("Session bounds must be HH:MM")
        if (self.session_start >= self.session_end or type(self.reconciliation_grace_minutes) is not int
                or self.reconciliation_grace_minutes < 0):
            raise ValueError("Local delivery session must end after start; grace cannot be negative")
        def minutes(value):
            hour, minute = map(int,value.split(":"))
            return hour*60+minute
        if minutes(self.session_end)-minutes(self.session_start) < 180:
            raise ValueError("Synthetic delivery sessions require at least three hours")

    @property
    def split_counts(self) -> dict[str, int]:
        return dict(zip(SPLITS, (self.history, self.development, self.held_out)))

    @property
    def as_of(self) -> str:
        return iso(instant(self.start_at) + timedelta(days=self.simulation_days + 10))


# These labels are the only labels an importer may interpolate into fixed Cypher.
# ExpectedJourney/ExpectedRoute are storage aliases of JourneyPlan/Route, not duplicate nodes.
ALIASES = {
    "JourneyPlan": ("ExpectedJourney",), "Route": ("ExpectedRoute",),
    **{kind: ("Facility",) for kind in ("OrganizationWarehouse", "FulfillmentWarehouse",
                                       "Branch", "Hub", "SortingCenter", "DeliveryDepot")},
}
KINDS = frozenset((
    "City", "Customer", "Organization", "OrganizationWarehouse", "FulfillmentWarehouse",
    "Branch", "Hub", "SortingCenter", "DeliveryDepot", "Shipment", "Package", "ShipmentType",
    "ServiceLevel", "HandlingRequirement", "InventoryRecord", "Address", "AddressVersion",
    "LocationPin", "DeliveryInstruction", "Route", "RouteSegment", "RouteMilestone", "JourneyPlan",
    "ExpectedMilestone", "DeliverySession", "Vehicle", "VehicleType", "Driver", "VehicleAssignment",
    "ScanEvent", "CustodyEvent", "DeliveryAttempt", "ContactAttempt", "GPSObservation",
    "TrafficObservation", "DeliveryProof", "AuthenticationEvidence", "SignatureEvidence",
    "PhotoEvidence", "HandoffEvidence", "RecipientReport", "DepotReconciliation", "StatusEvent",
    "Policy", "Exception", "Case", "EvidenceSnapshot", "AnalysisRun", "Recommendation", "Review",
    "OperatorDecision", "ActionExecution", "Resolution", "Outcome", "Notification", "AuditEvent",
    # Live network (DEMO-SUHAIL-LIVE): carriers, devices, dispatch manifests and device telemetry.
    "Provider", "Device", "Manifest", "DeviceHeartbeat",
    # Mechanism world (DEMO-SUHAIL-WORLD-*, chat/world): shared transport catalog (containers, trips,
    # route runs, lanes), shared observations (facility throughput, trip status, traffic incidents)
    # and per-shipment customer communications.
    "Container", "Trip", "RouteRun", "Lane", "FacilityThroughput", "TripEvent", "TrafficEvent",
    "CommunicationEvent",
))
RELATIONSHIPS = frozenset((
    "IN_CITY", "OWNS", "OPERATES", "STORED_AT", "ALLOCATES", "SENDS", "RECEIVES", "HAS_PACKAGE",
    "HAS_TYPE", "USES_SERVICE", "REQUIRES", "GOVERNED_BY", "HAS_ADDRESS_VERSION", "VERSION_OF",
    "SUPERSEDES", "HAS_PIN", "HAS_INSTRUCTION", "EXPECTED_ROUTE", "HAS_PLAN", "CONTAINS",
    "FROM", "TO", "EXPECTS", "BASED_ON", "AT_FACILITY", "IN_SESSION", "HAS_ASSIGNMENT",
    "ASSIGNED_DRIVER", "USES_VEHICLE", "ON_SEGMENT", "CARRIES", "HAS_SCAN", "HAS_CUSTODY_EVENT",
    "FROM_CUSTODIAN", "TO_CUSTODIAN", "LOADED_ON", "HAS_ATTEMPT", "USED_ADDRESS", "HAS_CONTACT",
    "HAS_PROOF", "HAS_AUTHENTICATION", "HAS_SIGNATURE", "HAS_PHOTO", "HAS_HANDOFF", "HAS_REPORT",
    "HAS_STATUS", "HAS_RECONCILIATION", "HAS_TELEMETRY", "HAS_DELAY_EVIDENCE", "ABOUT",
    "HAS_EXCEPTION", "SUPPORTED_BY", "USES_SNAPSHOT", "HAS_RUN", "PROPOSES", "REVIEWED_BY",
    "HAS_DECISION", "INITIATES", "RESOLVED_BY", "HAS_OUTCOME", "VERIFIED_BY", "CITES",
    "HAS_NOTIFICATION", "HAS_AUDIT", "OBSERVED_BY", "NEXT_SESSION", "FOR_PACKAGE",
    "WORKS_FOR", "OPERATED_BY", "USES_DEVICE", "HAS_MANIFEST", "LISTS",
    # Mechanism world: shared-reference links (a parcel's record to the container, trip or route run
    # it shared with other parcels) and shared observation feeds.
    "IN_CONTAINER", "ON_TRIP", "ON_ROUTE_RUN", "ON_LANE", "HAS_COMMUNICATION", "HAS_THROUGHPUT",
    "HAS_TRIP_EVENT",
))
UTC_FIELDS = frozenset((
    "occurred_at", "recorded_at", "effective_at", "valid_from", "valid_to", "earliest_at",
    "latest_at", "promise_at", "as_of", "opened_at", "resolved_at", "verified_at", "expires_at",
    "start_at", "end_at", "acknowledged_at", "invalidated_at",
    # Mechanism world: trip cutoffs and carrier ETA revisions.
    "cutoff_at", "estimated_arrival_at",
))
CASE_STATES = frozenset(("OPEN", "INVESTIGATING", "RECOMMENDATION_READY", "AWAITING_APPROVAL",
                         "ACTION_INITIATED", "AWAITING_OUTCOME", "RESOLVED", "NEEDS_MORE_EVIDENCE",
                         "HUMAN_REVIEW", "ESCALATED", "REJECTED", "REOPENED"))


@dataclass
class Node:
    id: str
    kind: str
    properties: dict

    @property
    def labels(self) -> tuple[str, ...]:
        return ("V2Entity", self.kind, *ALIASES.get(self.kind, ()))

    def record(self) -> dict:
        return {"id": self.id, "kind": self.kind, "properties": self.properties}


@dataclass
class Edge:
    id: str
    kind: str
    start: str
    end: str
    properties: dict

    def record(self) -> dict:
        return {"id": self.id, "kind": self.kind, "start": self.start,
                "end": self.end, "properties": self.properties}


@dataclass
class World:
    config: Config
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    gold: dict[str, dict] = field(default_factory=dict)  # scoring only, never imported into Neo4j

    def node(self, kind: str, identifier: str, *, shipment_id: str | None = None,
             split: str = "shared", provenance=Provenance.SYNTHETIC_DEMO_ASSUMPTION, **props) -> str:
        if kind not in KINDS or not identifier.startswith("DEMO-"):
            raise ValueError("Unknown kind or non-DEMO identity")
        fields = {"entity_id": identifier, "dataset_id": self.config.dataset_id,
                  "schema_version": SCHEMA_VERSION, "synthetic": True, "provenance": str(provenance),
                  "source_ref": f"{GENERATOR_VERSION}:fixture", "recorded_at": self.config.start_at,
                  "split": split, "holdout_group": shipment_id, **props}
        if shipment_id:
            fields["shipment_id"] = shipment_id
        candidate = Node(identifier, kind, fields)
        if identifier in self.nodes and self.nodes[identifier] != candidate:
            raise ValueError("Conflicting node identity")
        self.nodes[identifier] = candidate
        return identifier

    def edge(self, start: str, kind: str, end: str, **props) -> str:
        if kind not in RELATIONSHIPS or start not in self.nodes or end not in self.nodes:
            raise ValueError("Unknown relationship or missing endpoint")
        owners = {n.properties.get("holdout_group") for n in (self.nodes[start], self.nodes[end])}
        owners.discard(None)
        if len(owners) > 1:
            raise ValueError("Shipment groups cannot cross-link")
        owner = next(iter(owners), None)
        split = self.nodes[owner].properties["split"] if owner else "shared"
        identity = "DEMO-EDGE-" + digest([start, kind, end, props])[:24]
        self.edges[identity] = Edge(identity, kind, start, end, {
            "edge_id": identity, "dataset_id": self.config.dataset_id,
            "schema_version": SCHEMA_VERSION, "synthetic": True,
            "provenance": str(Provenance.SYNTHETIC_DEMO_ASSUMPTION),
            "source_ref": f"{GENERATOR_VERSION}:fixture", "split": split,
            "holdout_group": owner, **props})
        return identity

    def of_kind(self, kind: str) -> list[Node]:
        return [node for node in self.nodes.values() if node.kind == kind]

    def owned(self, shipment_id: str, kind: str | None = None) -> list[Node]:
        return [node for node in self.nodes.values()
                if node.properties.get("holdout_group") == shipment_id
                and (kind is None or node.kind == kind)]

    def hashes(self) -> dict[str, str]:
        return {"nodes": digest_records(self.nodes[k].record() for k in sorted(self.nodes)),
                "edges": digest_records(self.edges[k].record() for k in sorted(self.edges)),
                "gold": digest_records(self.gold[k] for k in sorted(self.gold))}

    def manifest(self) -> dict:
        return {"dataset_id": self.config.dataset_id, "schema_version": SCHEMA_VERSION,
                "generator_version": GENERATOR_VERSION, "policy_version": POLICY_VERSION,
                "derivation_version": DERIVATION_VERSION, "config": asdict(self.config),
                "as_of": self.config.as_of, "timezone": "Asia/Riyadh", "units": "kg,m,seconds",
                "synthetic": True, "notifications": "dry_run", "network_calls": 0,
                "counts": {"nodes": len(self.nodes), "edges": len(self.edges), "shipments": len(self.gold)},
                "hashes": self.hashes()}
