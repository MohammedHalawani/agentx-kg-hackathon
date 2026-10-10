"""Operator transitions are distinct from outcome verification and resolution."""
import os


class OperationsConflict(ValueError):
    pass


DECISIONS = frozenset(("approve", "reject", "request_evidence", "escalate", "reopen"))
# Operators allowed to act on the local synthetic ledger: SUHAIL_OPERATOR_IDS (comma separated), default the local
# demonstration operator. The evaluation harness acts under its own id with source "harness", never as an operator.
DEFAULT_OPERATOR = "DEMO-OPERATOR-LOCAL"
HARNESS_ACTOR = "DEMO-S5-HARNESS"
SOURCES = ("operator", "harness")


def operator_ids():
    configured = [x.strip() for x in os.environ.get("SUHAIL_OPERATOR_IDS", "").split(",") if x.strip()]
    ids = configured or [DEFAULT_OPERATOR]
    if HARNESS_ACTOR in ids or any(not x.startswith("DEMO-") for x in ids):
        raise OperationsConflict("Operator ids must be DEMO- identities distinct from the harness")
    return tuple(ids)


def decision_state(state, decision):
    if decision not in DECISIONS:
        raise OperationsConflict("Unknown operator decision")
    allowed = {
        "approve": ({"AWAITING_APPROVAL", "HUMAN_REVIEW", "RECOMMENDATION_READY"}, "AWAITING_OUTCOME"),
        "reject": ({"AWAITING_APPROVAL", "HUMAN_REVIEW", "RECOMMENDATION_READY"}, "REJECTED"),
        "request_evidence": ({"OPEN", "AWAITING_APPROVAL", "HUMAN_REVIEW", "NEEDS_EVIDENCE", "RECOMMENDATION_READY"}, "NEEDS_EVIDENCE"),
        "escalate": ({"OPEN", "AWAITING_APPROVAL", "HUMAN_REVIEW", "NEEDS_EVIDENCE", "RECOMMENDATION_READY"}, "ESCALATED"),
        "reopen": ({"RESOLVED", "REJECTED", "ESCALATED"}, "REOPENED"),
    }
    sources, destination = allowed[decision]
    if state not in sources:
        raise OperationsConflict("Decision is stale or incompatible with the case state")
    return destination


def require_version(case, expected_version):
    if type(expected_version) is not int or expected_version != case["state_version"]:
        raise OperationsConflict("Case changed; reload its authoritative version")


def require_actor(actor_id, authority=None, *, source="operator"):
    """A configured operator acting as an operator, or the harness acting under its own id. Returns the source."""
    if source not in SOURCES or authority not in (None, "LOCAL_DEMO_OPERATOR"):
        raise OperationsConflict("Local operator authority required")
    if source == "harness":
        if actor_id != HARNESS_ACTOR:
            raise OperationsConflict("The evaluation harness acts only under its own actor id")
        return source
    if actor_id not in operator_ids():
        raise OperationsConflict("Local operator authority required")
    return source
