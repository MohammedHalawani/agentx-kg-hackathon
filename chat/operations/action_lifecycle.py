"""Additive operational response lifecycle. A response never declares an outcome.

The legacy case state/review/authority are retained. These independent axes describe
routine operational work; only the existing source verifier can certify an outcome.
"""
import copy
import json

from dataset_v2.contracts import instant, digest
from operations.lifecycle import OperationsConflict

VERSION = "suhail-action-1"
EVENTS = frozenset(("ACKNOWLEDGED", "ACCEPTED", "STARTED", "EVIDENCE_RECEIVED", "REJECTED", "FAILED"))
TERMINAL = frozenset(("REFUSED", "REJECTED", "FAILED", "EXPIRED", "VERIFIED", "UNRESOLVED"))


class SyntheticActionAdapter:
    """Explicit opt-in synthetic transport only. No network sends or source generation."""
    name = "synthetic_response_transport"
    requires_response_events = True

    def respond(self, execution, now):
        return {"acknowledged": True, "synthetic": True, "external_calls": 0,
                "behaviour": "Synthetic request queued; waiting for a simulated employee/device acknowledgement."}


def initial(when):
    return {"version": VERSION, "revision": 0, "authorization": "AUTHORIZED", "dispatch": "PENDING",
            "acknowledgement": "PENDING", "acceptance": "PENDING", "execution": "PENDING",
            "verification": "NOT_REQUESTED", "state": "AUTHORIZED", "events": [], "created_at": when,
            "requires_response_events": False}


def load(execution):
    return json.loads(execution["action_lifecycle_json"]) if execution.get("action_lifecycle_json") else None


def dispatched(state, when, *, requires_responses=False, acknowledged=True):
    state = copy.deepcopy(state)
    state.update(dispatch="SENT" if acknowledged else "UNAVAILABLE", state="AWAITING_ACKNOWLEDGEMENT" if acknowledged else "FAILED",
                 dispatched_at=when, requires_response_events=requires_responses, revision=state["revision"] + 1)
    state["events"].append({"id": "dispatch", "kind": "DISPATCHED" if acknowledged else "DISPATCH_FAILED",
                            "occurred_at": when, "recorded_at": when, "synthetic": True, "evidence_ids": []})
    return state


def respond(state, event, *, now, deadline, revision, superseded=False):
    """Idempotent append under the store transaction; late events are audited only."""
    required = {"response_id", "kind", "occurred_at", "evidence_ids", "source_ref"}
    if set(event) != required or event["kind"] not in EVENTS:
        raise OperationsConflict("Invalid synthetic action response")
    if (not isinstance(event["response_id"], str) or not 1 <= len(event["response_id"]) <= 128 or
        not isinstance(event["source_ref"], str) or not event["source_ref"].startswith("synthetic:") or len(event["source_ref"])>200 or
        not isinstance(event["evidence_ids"], list) or len(event["evidence_ids"]) > 100 or
        any(not isinstance(k, str) for k in event["evidence_ids"]) or len(set(event["evidence_ids"])) != len(event["evidence_ids"])):
        raise OperationsConflict("Responses require bounded identifiers and explicit synthetic provenance")
    fingerprint = digest(event)
    prior = next((r for r in state["events"] if r["id"] == event["response_id"]), None)
    if prior:
        if prior.get("request_hash") != fingerprint:
            raise OperationsConflict("Response identifier reused with different content")
        return copy.deepcopy(state), True
    if type(revision) is not int or revision != state["revision"]:
        raise OperationsConflict("Action changed; reload its lifecycle revision")
    occurred, clock = instant(event["occurred_at"]), instant(now)
    if occurred > clock or occurred < instant(state["dispatched_at"]):
        raise OperationsConflict("Response time is outside its dispatch/receipt interval")
    if len(state["events"]) >= 100:
        raise OperationsConflict("Action response history limit reached")
    updated = copy.deepcopy(state)
    late = superseded or clock > instant(deadline) or state["state"] in TERMINAL
    row = {"id": event["response_id"], **{k: v for k, v in event.items() if k != "response_id"},
           "recorded_at": now, "synthetic": True, "request_hash": fingerprint, "late": late}
    if not late:
        allowed = {
            "ACKNOWLEDGED": {"AWAITING_ACKNOWLEDGEMENT"},
            "ACCEPTED": {"ACKNOWLEDGED"},
            "STARTED": {"ACCEPTED"},
            "EVIDENCE_RECEIVED": {"ACCEPTED", "EXECUTING", "EVIDENCE_RECEIVED"},
            "REJECTED": {"AWAITING_ACKNOWLEDGEMENT", "ACKNOWLEDGED"},
            "FAILED": {"ACCEPTED", "EXECUTING", "EVIDENCE_RECEIVED"},
        }
        if state["state"] not in allowed[event["kind"]]:
            raise OperationsConflict("Response is incompatible with the action state")
        if occurred < instant(state["events"][-1]["occurred_at"]):
            raise OperationsConflict("Out-of-order operational response")
        kind = event["kind"]
        if kind == "EVIDENCE_RECEIVED" and not event["evidence_ids"]:
            raise OperationsConflict("Evidence receipt requires actual source identifiers")
        updated["state"] = "EXECUTING" if kind == "STARTED" else kind
        axis = {"ACKNOWLEDGED": "acknowledgement", "ACCEPTED": "acceptance", "REJECTED": "acceptance",
                "STARTED": "execution", "FAILED": "execution", "EVIDENCE_RECEIVED": "verification"}[kind]
        updated[axis] = "AWAITING_VERIFICATION" if kind == "EVIDENCE_RECEIVED" else updated["state"]
    updated["events"].append(row)
    updated["revision"] += 1
    return updated, False


def refused(state,when,rule):
    updated=copy.deepcopy(state)
    updated.update(authorization="REFUSED",dispatch="REFUSED",state="REFUSED",revision=state["revision"]+1)
    updated["events"].append({"id":f"refusal-{updated['revision']}","kind":"AUTHORIZATION_REFUSED",
                              "occurred_at":when,"recorded_at":when,"synthetic":True,"evidence_ids":[],"rule_id":rule})
    return updated


def verification(state, verdict, now, *, resolved=False):
    updated = copy.deepcopy(state)
    if verdict["status"] == "pending":
        if instant(now) >= instant(verdict["deadline_at"]):
            updated.update(state="EXPIRED", execution="EXPIRED")
        else:
            return updated
    else:
        updated.update(state="VERIFIED" if verdict["status"] == "success" else "UNRESOLVED",
                       verification="VERIFIED_SUCCESS" if verdict["status"] == "success" else "VERIFIED_FAILURE",
                       resolved=bool(resolved))
    updated["revision"] += 1
    updated["events"].append({"id": f"verification-{updated['revision']}", "kind": updated["state"],
                               "occurred_at": now, "recorded_at": now, "synthetic": True,
                               "evidence_ids": verdict.get("evidence_ids") or [], "rule_id": verdict.get("rule_id")})
    return updated


def view(execution):
    state = load(execution)
    if state is None:
        return None
    waiting = {"REQUEST_RESCAN": "AWAITING_RESCAN", "REQUEST_DEVICE_SYNC": "AWAITING_SYNCHRONIZATION",
               "INITIATE_CUSTODY_RECONCILIATION": "AWAITING_CUSTODY_RECONCILIATION"}
    return {**state, "execution_id": execution["entity_id"], "action_type": execution.get("action_type"),
            "operational_label": waiting.get(execution.get("action_type"), "AWAITING_OPERATIONAL_RESPONSE")
            if state["state"] in ("ACCEPTED", "EXECUTING") else state["state"],
            "synthetic": True}


def case_status(case,actions,*,risk=None,human_closure=False,reviewer_human=False):
    """Presentation of current authority facts, separate from historical task reports."""
    from operations.authority import HUMAN_FLOOR_SYMPTOMS
    resolved=case.get("workflow_state")=="RESOLVED" and bool(case.get("verified_outcome_id"))
    human=not resolved and bool(set(case.get("symptom_codes") or [])&HUMAN_FLOOR_SYMPTOMS or
                               case.get("workflow_state")=="ESCALATED" or risk in ("HUMAN_REVIEW","PROHIBITED") or
                               human_closure or reviewer_human)
    unresolved=case.get("workflow_state")=="REJECTED" or any(a["state"] in ("REFUSED","FAILED","REJECTED","EXPIRED","UNRESOLVED") or
                                                            (a["state"]=="VERIFIED" and not a.get("resolved")) for a in actions)
    resolution=("VERIFIED_RESOLVED" if resolved else "HUMAN_DECISION_REQUIRED" if human else
                "UNRESOLVED" if unresolved else "OPERATIONAL_WORK_PENDING" if actions else "INVESTIGATION_PENDING")
    return {"version":VERSION,"resolution":resolution,"human_decision_required":human,"actions":actions,"synthetic":True}
