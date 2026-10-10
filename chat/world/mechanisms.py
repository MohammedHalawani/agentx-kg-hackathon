"""Mechanism catalogue and the plan of mechanism instances a world run applies.

A mechanism is a world-level cause (a device, facility, trip, driver, route, recipient or label condition).
It acts on every parcel it physically touches; nothing here names a shipment's outcome. The catalogue maps
each mechanism type to the cause code in the current catalogue (chat/operations/agents.py CAUSES), the
resolution it permits and the catalogue action (chat/operations/authority.py ACTIONS) that addresses it.
This module is truth-side: nothing from it is written into a node, edge or feed message.
"""
from dataclasses import dataclass, field

# type -> (cause code, acceptable causes, resolution, action, fault, physical effect, observation effect, natural recovery)
CATALOGUE = {
    "DEVICE_OUTAGE": ("DELAYED_SYNC", ("DELAYED_SYNC",), "AUTO", "REQUEST_DEVICE_SYNC", True,
                      "none: parcels move normally",
                      "the device's records buffer locally and upload at reconnect; its heartbeats stop",
                      "the device reconnects at the end of the window and uploads everything it buffered"),
    "PARTIAL_UPLOAD_LOSS": ("DELAYED_SYNC", ("DELAYED_SYNC",), "AUTO", "REQUEST_DEVICE_SYNC", True,
                            "none", "some records stay stuck in the device outbox; heartbeats report a pending queue",
                            "the nightly full sync uploads the stuck records"),
    "SCAN_SKIPPED_AT_RECEIPT": ("CUSTODY_GAP", ("CUSTODY_GAP", "MISSED_MILESTONE"), "AUTO", "INITIATE_CUSTODY_RECONCILIATION", True,
                                "parcel is received physically", "no receipt scan; later scans appear without it",
                                "the next handling scan (loading) shows the parcel moved on"),
    "FACILITY_BACKLOG": ("HUB_DELAY", ("HUB_DELAY", "JOURNEY_DELAY", "MISSED_MILESTONE"), "AUTO", "REQUEST_HUB_CHECK", True,
                         "processing capacity drops; parcels miss connections", "facility throughput falls and its queue grows",
                         "capacity returns and the queue drains onto later departures"),
    "LATE_LINEHAUL": ("ROUTE_DELAY", ("ROUTE_DELAY", "JOURNEY_DELAY", "MISSED_MILESTONE"), "AUTO", "PRIORITIZE_NEXT_SESSION", True,
                      "the trip departs late or stops mid-route; every container on it is late",
                      "carrier ETA revisions; stationary positions; late arrival scans for all its containers",
                      "the trip completes late and parcels continue on later connections"),
    "MISSORT": ("HUB_DELAY", ("HUB_DELAY", "MISSED_MILESTONE", "CUSTODY_GAP"), "AUTO", "REQUEST_HUB_CHECK", True,
                "a parcel goes into the wrong container, or a container onto the wrong trip",
                "a receipt scan at an unexpected depot or hub", "the receiving site sends it back; about a day lost"),
    "ASSIGNED_NOT_LOADED": ("CUSTODY_GAP", ("CUSTODY_GAP", "UNRECONCILED_CUSTODY", "MISSED_MILESTONE"), "HUMAN",
                            "INITIATE_CUSTODY_RECONCILIATION", True,
                            "the parcel stays on the depot shelf", "on the route manifest, no driver-app load confirmation",
                            "the evening stock check scans it at the depot; it is planned again"),
    "DELIVERY_SCAN_SKIPPED": ("UNRECONCILED_CUSTODY", ("UNRECONCILED_CUSTODY", "MISSED_MILESTONE"), "HUMAN",
                              "INITIATE_CUSTODY_RECONCILIATION", True,
                              "the parcel is handed to the recipient", "no attempt, proof or delivery scan; out for delivery overnight",
                              "sometimes the recipient confirms receipt; otherwise nothing"),
    "RETURN_SCAN_SKIPPED": ("UNRECONCILED_CUSTODY", ("UNRECONCILED_CUSTODY", "CUSTODY_GAP"), "HUMAN", "INITIATE_CUSTODY_RECONCILIATION", True,
                            "the parcel is back on the depot shelf", "no return scan; the session ends unreconciled",
                            "the evening stock check finds it and the session is reconciled late"),
    "CONTRACTOR_RETAINS": ("UNRECONCILED_CUSTODY", ("UNRECONCILED_CUSTODY",), "HUMAN", "PHYSICAL_CUSTODY_CHECK", True,
                           "an independent driver keeps undelivered parcels", "the driver app goes silent; no return, no reconciliation",
                           "sometimes the driver returns the parcels a day or two later"),
    "UNRECORDED_HANDOFF": ("CUSTODY_GAP", ("CUSTODY_GAP", "CONFLICTING_CUSTODY"), "AUTO", "INITIATE_CUSTODY_RECONCILIATION", True,
                           "parcels move from one driver's vehicle to another's", "the other driver's app delivers parcels the first driver loaded",
                           "the parcels are delivered; the custody record stays inconsistent"),
    "RECIPIENT_UNAVAILABLE": ("RECIPIENT_UNAVAILABLE", ("RECIPIENT_UNAVAILABLE",), "AUTO", "PRIORITIZE_NEXT_SESSION", True,
                              "nobody can receive the parcel for days", "failed attempts, unanswered calls",
                              "the recipient becomes reachable and a later attempt succeeds, or attempts run out"),
    "WRONG_ADDRESS": ("ADDRESS_CONFLICT", ("ADDRESS_CONFLICT",), "AUTO", "REQUEST_ADDRESS_CONFIRMATION", True,
                      "the booked address is outdated; the recipient lives elsewhere", "failed attempt at the old address",
                      "the recipient sends a dated address correction; the next attempt uses it"),
    "WRONG_GATE": ("WRONG_GATE", ("WRONG_GATE",), "AUTO", "REQUEST_ADDRESS_CONFIRMATION", True,
                   "navigation leads the driver to a different compound gate", "attempt records a gate other than the instruction",
                   "the recipient guides the driver, or a later attempt uses the right gate"),
    "OTP_NOT_RECEIVED": ("PROOF_INSUFFICIENT", ("PROOF_INSUFFICIENT", "RECIPIENT_UNAVAILABLE"), "AUTO", "REQUEST_ADDITIONAL_EVIDENCE", True,
                         "the recipient is present but the one-time code never arrives", "failed SMS delivery reports for the code",
                         "the gateway recovers; a later attempt verifies, or the driver overrides without a code"),
    "NEIGHBOUR_RECEIVES": ("DELIVERY_DISPUTE", ("DELIVERY_DISPUTE", "PROOF_INSUFFICIENT"), "HUMAN", "DELIVERY_DISPUTE_REVIEW", True,
                           "an unauthorised neighbour or other person takes the parcel", "proof names another person; recipient may report non-receipt",
                           "the neighbour passes it on, or the recipient complains"),
    "MISDELIVERY": ("POSSIBLE_MISDELIVERY", ("POSSIBLE_MISDELIVERY", "DELIVERY_DISPUTE"), "HUMAN", "DELIVERY_DISPUTE_REVIEW", True,
                    "the parcel is left at the wrong building", "proof location away from the address; non-receipt report",
                    "none without investigation"),
    "LABEL_MISREAD": ("BARCODE_MISMATCH", ("BARCODE_MISMATCH",), "AUTO", "REQUEST_RESCAN", True,
                      "none", "one read returns a wrong barcode; other reads are right", "the next read is correct"),
    "WRONG_LABEL_APPLIED": ("BARCODE_MISMATCH", ("BARCODE_MISMATCH",), "HUMAN", "REQUEST_RESCAN", True,
                            "the parcel carries another order's label", "every read returns the same wrong barcode",
                            "none: a rescan reads the same wrong label; a person must relabel"),
    "SCALE_DRIFT": ("WEIGHT_MISMATCH", ("WEIGHT_MISMATCH",), "AUTO", "REQUEST_REWEIGH", True,
                    "none", "every weighing on that scale in the window is off", "recalibration at the next shift change"),
    "DECLARED_WEIGHT_WRONG": ("WEIGHT_MISMATCH", ("WEIGHT_MISMATCH",), "HUMAN", "REQUEST_REWEIGH", True,
                              "the declared weight is wrong", "every scale agrees with each other and not with the declaration",
                              "none: a reweigh confirms the measured weight; a person corrects the declaration"),
    "MANIFEST_ERROR": ("MANIFEST_CONFLICT", ("MANIFEST_CONFLICT",), "HUMAN", "MANIFEST_RECONCILIATION_REVIEW", True,
                       "none: the parcel is on the vehicle", "a revised route manifest drops a loaded parcel",
                       "none: the manifest stays wrong until a person reconciles it"),
    "TRAFFIC_DISRUPTION": ("TRAFFIC_DELAY", ("TRAFFIC_DELAY", "ROUTE_DELAY"), "AUTO", "PRIORITIZE_NEXT_SESSION", True,
                           "routes through the zone slow down; some stops run out of time",
                           "shared traffic incident; slow vehicle positions; not-attempted stops on several routes",
                           "the next session delivers"),
    "ROUTINE_FAILED_ATTEMPT": ("RECIPIENT_UNAVAILABLE", ("RECIPIENT_UNAVAILABLE",), "AUTO", "PRIORITIZE_NEXT_SESSION", True,
                              "an ordinary failed attempt (not home, building not found, access refused, code not given, shift cut short)",
                              "a failed attempt record; the next attempt is after the promise",
                              "the next session delivers"),
    "CUSTOMER_COMPLAINT": ("DELIVERY_DISPUTE", ("DELIVERY_DISPUTE",), "NONE", None, False,
                           "none", "an inbound recipient message (a question, or a non-receipt claim on a delivered parcel)",
                           "a question needs no action; a claim on a delivered parcel needs a person"),
    "DUPLICATE_EVENTS": (None, (), "NONE", None, False, "none", "a provider retransmits a message with the same identity",
                         "the gateway de-duplicates; never a case"),
}
MECHANISM_TYPES = tuple(CATALOGUE)
# A non-receipt claim on a delivered parcel needs a person even though nothing physical went wrong.
CLAIM_SUBTYPE = "NON_RECEIPT_CLAIM"


ROUTINE_CAUSE = {"NOT_HOME": "RECIPIENT_UNAVAILABLE", "RESCHEDULED_BY_RECIPIENT": "RECIPIENT_UNAVAILABLE",
                 "CODE_NOT_PROVIDED": "RECIPIENT_UNAVAILABLE", "BUILDING_NOT_FOUND": "ADDRESS_CONFLICT",
                 "ACCESS_REFUSED": "RECIPIENT_UNAVAILABLE", "ROUTE_NOT_COMPLETED": "ROUTE_DELAY"}


def resolution_of(mtype, subtype=None):
    if mtype == "CUSTOMER_COMPLAINT":
        return ("HUMAN", "DELIVERY_DISPUTE_REVIEW") if subtype == CLAIM_SUBTYPE else ("NONE", None)
    entry = CATALOGUE[mtype]
    return entry[2], entry[3]


def cause_of(mtype, subtype=None):
    if mtype == "ROUTINE_FAILED_ATTEMPT":
        cause = ROUTINE_CAUSE.get(subtype, "RECIPIENT_UNAVAILABLE")
        return cause, [cause, "MISSED_MILESTONE"]
    if mtype == "CUSTOMER_COMPLAINT":
        return ("DELIVERY_DISPUTE", ["DELIVERY_DISPUTE"]) if subtype == CLAIM_SUBTYPE else (None, [])
    entry = CATALOGUE[mtype]
    return entry[0], list(entry[1])


@dataclass
class Mechanism:
    mid: str
    type: str
    subtype: str
    started_at: object
    ended_at: object
    params: dict = field(default_factory=dict)
    origin: str = "scheduled"     # scheduled (scenario weighting) or base (real-frequency draw)


class MechanismPlan:
    """Instances and the lookups the physical simulation and the observation layer consult."""

    def __init__(self):
        self.items = {}
        self.device_down = {}        # device -> [(start, end, mid)]
        self.device_loss = {}        # device -> [(start, end, fraction, mid)]
        self.backlog = {}            # facility -> [(start, end, factor, mid)]
        self.trip_delay = {}         # trip id -> (kind, seconds, fraction, mid)
        self.misload = {}            # trip id -> (wrong trip id, mid)
        self.parcel = {}             # pid -> {type: (mid, params)}
        self.shipment = {}           # sid -> {type: (mid, params)}
        self.scale_drift = {}        # device -> [(start, end, factor, mid)]
        self.sms_outage = {}         # carrier route -> [(start, end, mid)]
        self.route = {}              # (depot, date, slot) -> {type: (mid, params)}
        self.depot_day = {}          # (depot, date) -> {type: (mid, params)}
        self.traffic = []            # (city, district, start, end, factor, mid)
        self._n = 0

    def add(self, mtype, subtype, started_at, ended_at, origin="scheduled", **params):
        self._n += 1
        mid = f"W1M-{self._n:05d}"
        self.items[mid] = Mechanism(mid, mtype, subtype, started_at, ended_at, params, origin)
        return mid

    def on_parcel(self, pid, mtype, mid, **params):
        self.parcel.setdefault(pid, {})[mtype] = (mid, params)

    def on_shipment(self, sid, mtype, mid, **params):
        self.shipment.setdefault(sid, {})[mtype] = (mid, params)

    def parcel_flag(self, pid, mtype):
        return self.parcel.get(pid, {}).get(mtype)

    def shipment_flag(self, sid, mtype):
        return self.shipment.get(sid, {}).get(mtype)

    @staticmethod
    def _window(rows, t):
        for row in rows:
            if row[0] <= t < row[1]:
                return row
        return None

    def down(self, device, t):
        row = self._window(self.device_down.get(device, ()), t)
        return row[-1] if row else None

    def backlog_at(self, facility, t):
        row = self._window(self.backlog.get(facility, ()), t)
        return (row[2], row[3]) if row else (1.0, None)

    def drift_at(self, device, t):
        row = self._window(self.scale_drift.get(device, ()), t)
        return (row[2], row[3]) if row else (0.0, None)

    def sms_down(self, route, t):
        row = self._window(self.sms_outage.get(route, ()), t)
        return row[-1] if row else None

    def traffic_at(self, city, district, t):
        for c, d, start, end, factor, mid in self.traffic:
            if c == city and d == district and start <= t < end:
                return factor, mid
        return 1.0, None
