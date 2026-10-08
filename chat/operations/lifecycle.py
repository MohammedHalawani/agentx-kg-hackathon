"""Operator transitions are distinct from outcome verification and resolution."""


class OperationsConflict(ValueError):
    pass


DECISIONS = frozenset(("approve", "reject", "request_evidence", "escalate", "reopen"))


def decision_state(state, decision):
    if decision not in DECISIONS:
        raise OperationsConflict("Unknown operator decision")
    allowed = {
        "approve": ({"AWAITING_APPROVAL", "HUMAN_REVIEW", "RECOMMENDATION_READY"}, "AWAITING_OUTCOME"),
        "reject": ({"AWAITING_APPROVAL", "HUMAN_REVIEW", "RECOMMENDATION_READY"}, "REJECTED"),
        "request_evidence": ({"OPEN", "AWAITING_APPROVAL", "HUMAN_REVIEW", "NEEDS_EVIDENCE", "RECOMMENDATION_READY"}, "NEEDS_EVIDENCE"),
        "escalate": ({"OPEN", "AWAITING_APPROVAL", "HUMAN_REVIEW", "NEEDS_EVIDENCE", "RECOMMENDATION_READY"}, "ESCALATED"),
        "reopen": ({"RESOLVED", "REJECTED", "ESCALATED", "NEEDS_EVIDENCE", "HUMAN_REVIEW"}, "REOPENED"),
    }
    sources, destination = allowed[decision]
    if state not in sources:
        raise OperationsConflict("Decision is stale or incompatible with the case state")
    return destination


def require_version(case, expected_version):
    if type(expected_version) is not int or expected_version != case["state_version"]:
        raise OperationsConflict("Case changed; reload its authoritative version")


def require_actor(actor_id, authority=None):
    if actor_id != "DEMO-OPERATOR-LOCAL" or authority not in (None, "LOCAL_DEMO_OPERATOR"):
        raise OperationsConflict("Local operator authority required")
