"""Bounded deterministic replay planning; no random data, clocks or external effects."""
from dataset_v2.contracts import instant

SPEEDS = frozenset((1, 10, 60))
EVENT_KINDS = frozenset(("ScanEvent", "CustodyEvent", "DeliveryAttempt", "ContactAttempt", "GPSObservation",
                       "TrafficObservation", "DeliveryProof", "AuthenticationEvidence", "SignatureEvidence",
                       "PhotoEvidence", "HandoffEvidence", "RecipientReport", "DepotReconciliation", "StatusEvent", "Case"))


def replay_plan(events, cursor, target, limit=100):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Invalid replay bound")
    instant(target)
    eligible = [event for event in events if (event["time"], event["id"]) > (cursor["time"], cursor["id"])
                and instant(event["time"]) <= instant(target)]
    return sorted(eligible, key=lambda event: (event["time"], event["id"]))[:limit]
