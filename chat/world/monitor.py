"""Offline replica of the live monitor (operations.store.monitor_step), as in the Stage 0 replica.

Every record becomes visible at the first hourly tick at or after its gateway delivery time (the scenario
runner ingests hourly). At each tick the shipment is assessed with the monitor's 900 s detection
allowance; the opening symptoms are what the monitor would open a case with. Assessments only change
when a record becomes visible or a deadline passes, so only those ticks are evaluated.
"""
from datetime import timedelta
import math

from dataset_v2.contracts import Node, World, iso
from dataset_v2.derive import EvidenceIndex, assess_shipment
from dataset_v2.network import stable_fraction
from operations.store import DETECTION_ALLOWANCE_SECONDS, monitor_finding

POD_KINDS = ("ContactAttempt", "DeliveryProof", "AuthenticationEvidence", "SignatureEvidence", "PhotoEvidence", "HandoffEvidence")
# The monitor's rule (exception) codes, most specific first: a code that names one condition precedes the
# generic custody and lateness codes it usually co-occurs with.
SPECIFICITY = ("WRONG_GATE", "RECIPIENT_UNAVAILABLE", "ADDRESS_CONFLICT", "BARCODE_MISMATCH", "WEIGHT_MISMATCH", "MANIFEST_CONFLICT",
               "POSSIBLE_MISDELIVERY", "DELIVERY_DISPUTE", "PROOF_INSUFFICIENT", "TRAFFIC_DELAY", "CONFLICTING_CUSTODY",
               "UNRECONCILED_CUSTODY", "CUSTODY_GAP", "JOURNEY_DELAY", "MISSED_MILESTONE")


def by_specificity(codes):
    """Rule codes ordered most specific first (unknown codes last, alphabetically)."""
    rank = {code: i for i, code in enumerate(SPECIFICITY)}
    return sorted(set(codes), key=lambda c: (rank.get(c, len(SPECIFICITY)), c))


def gateway_lag_seconds(node):
    """The provider-feed delivery lag dataset_v2.feed.feed_item adds (same bundle rule, sequence 0)."""
    p = node.properties
    bundle = p.get("source_event_id") if node.kind == "CustodyEvent" else p.get("attempt_id") if node.kind in POD_KINDS else node.id
    return 5 + int(85 * stable_fraction(bundle or node.id, 0))


def deliver_at(node):
    from dataset_v2.contracts import instant
    return instant(node.properties["recorded_at"]) + timedelta(seconds=gateway_lag_seconds(node))


class Replica:
    def __init__(self, world: World, start, *, evidence_ids=None, gateway_lag=True):
        """start: the tick grid origin. evidence_ids: records whose visibility is tick-rounded (all observations).
        gateway_lag: add the provider-feed lag to recorded_at (False when recorded_at already is the gateway time)."""
        from dataset_v2.contracts import instant
        self.start = start
        self.world = World(world.config)
        self.visible = {}
        for key, node in world.nodes.items():
            props = node.properties
            if evidence_ids is None or key in evidence_ids:
                if props.get("occurred_at") and props.get("recorded_at"):
                    tick = self.tick_ceil(deliver_at(node) if gateway_lag else instant(props["recorded_at"]))
                    props = dict(props)
                    props["recorded_at"] = iso(tick)
                    self.visible[key] = tick
            self.world.nodes[key] = Node(node.id, node.kind, props)
        self.world.edges = world.edges
        self.index = EvidenceIndex(self.world)

    def tick_ceil(self, when):
        k = math.ceil((when - self.start).total_seconds() / 3600)
        return self.start + timedelta(hours=max(k, 0))

    def candidate_ticks(self, sid, horizon_end):
        from dataset_v2.contracts import instant
        owned = self.index.groups[sid]
        ticks = set()
        allowance = timedelta(seconds=DETECTION_ALLOWANCE_SECONDS)
        for nodes in owned.values():
            for node in nodes:
                tick = self.visible.get(node.id)
                if tick is not None:
                    ticks.add(tick)
                    ticks.add(self.tick_ceil(tick + allowance))
        for m in owned.get("ExpectedMilestone", []):
            ticks.add(self.tick_ceil(instant(m.properties["latest_at"]) + timedelta(seconds=m.properties.get("grace_seconds") or 0) + allowance + timedelta(seconds=1)))
        for s in owned.get("DeliverySession", []):
            ticks.add(self.tick_ceil(instant(s.properties["end_at"]) + timedelta(seconds=(s.properties.get("grace_seconds") or 0) + 60) + allowance + timedelta(seconds=1)))
        return sorted(t for t in ticks if t <= horizon_end)

    def timeline(self, sid, horizon_end, *, first_only=False):
        """[(tick, codes, symptoms)] whenever the assessment changes; the first non-empty entry is the opening."""
        rows, previous = [], None
        for tick in self.candidate_ticks(sid, horizon_end):
            assessment = assess_shipment(self.world, sid, iso(tick), _index=self.index,
                                         detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)
            codes = tuple(sorted(e["code"] for e in assessment["exceptions"]))
            if codes != previous:
                rows.append((tick, list(codes), monitor_finding(assessment)["symptoms"]))
                previous = codes
                if first_only and codes:
                    break
        return rows

    def opening(self, sid, horizon_end):
        for tick, codes, symptoms in self.timeline(sid, horizon_end, first_only=True):
            if codes:
                return tick, codes, symptoms
        return None
