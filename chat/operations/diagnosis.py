"""The case diagnosis served to operators: the current run's accepted agent investigation, or explicitly absent.

Only a completed agent investigation (GPT-OSS tool loop) that the independent model reviewer accepted is a
diagnosis. An investigation the reviewer did not accept (it asked for a revision, for a person, or could not
review) is served apart as `unaccepted_investigation`, labelled, never as what happened. Rule checks are served
separately as rule signals; they never fill this field. While a newer investigation is queued or running, the
earlier one is not shown as current.
"""
from operations.worker import review_reason

ABSENT_REASONS = ("not_a_case", "no_operations_ledger", "not_investigated", "investigation_in_progress",
                  "reinvestigation_pending", "investigation_incomplete", "no_agent_investigation", "investigation_unavailable",
                  "review_not_accepted")
HYPOTHESIS_FIELDS = ("cause", "status", "assessment", "supporting_evidence_ids", "contradicting_evidence_ids")


def absent_diagnosis(reason, *, run_id=None, superseded_run_id=None, review=None, unaccepted=None):
    if reason not in ABSENT_REASONS:
        raise ValueError("Unknown absent-diagnosis reason")
    return {"available": False, "reason": reason, "source": None, "run_id": run_id, "superseded_run_id": superseded_run_id,
            "as_of": None, "investigated_at": None, "primary_cause": None, "confidence": None, "summary": None,
            "hypotheses": [], "missing_evidence": [], "requires_physical_check": None, "tool_calls": 0,
            "snapshot_superseded": False, "language": None, "review": review, "unaccepted_investigation": unaccepted}


def final_review(result):
    """The run's final review (the last round's verdict), or None."""
    result = result or {}
    review = result.get("review")
    if not review:
        trace = result.get("trace") or []
        review = (trace[-1] or {}).get("review") if trace else None
    return review or None


def review_status(review):
    """What the independent reviewer decided about this investigation, as served with the diagnosis."""
    if not review:
        return None
    accepted = review.get("verdict") == "accept" and review.get("model_verdict") == "ACCEPT"
    return {"verdict": review.get("verdict"), "model_verdict": review.get("model_verdict"), "reason_code": review_reason(review),
            "accepted": accepted}


def investigation_status(result):
    """(available, reason) for a recorded analysis: only an agent investigation the independent reviewer accepted.
    Used for the served diagnosis and for what the case records as its summary and cause codes."""
    result = result or {}
    investigation = result.get("investigation")
    if result.get("mode") != "gpt_oss_agents" or not investigation:
        return False, "no_agent_investigation"
    if investigation.get("degraded") or not investigation.get("primary_cause"):
        return False, "investigation_unavailable"
    if not (review_status(final_review(result)) or {}).get("accepted"):
        return False, "review_not_accepted"
    return True, None


def _findings(run, result, investigation):
    return {"run_id": run.get("entity_id"), "as_of": (result.get("result") or {}).get("as_of"), "investigated_at": run.get("recorded_at"),
            "primary_cause": investigation["primary_cause"], "confidence": investigation.get("confidence"),
            "summary": investigation.get("summary"),
            "hypotheses": [{key: h.get(key) for key in HYPOTHESIS_FIELDS} for h in investigation.get("hypotheses") or []],
            "missing_evidence": list(investigation.get("missing_evidence") or []),
            "requires_physical_check": investigation.get("requires_physical_check"),
            "tool_calls": len(investigation.get("steps") or []),
            "snapshot_superseded": any(d.get("role") == "snapshot" for d in result.get("degraded") or []),
            # Model prose (summary, assessments) is the investigator's own text, untranslated.
            "language": "en"}


def case_diagnosis(case, run):
    """case: the stored case; run: its current run (case.last_run_id) with `result` parsed, or None."""
    state = case.get("workflow_state")
    last = case.get("last_run_id")
    if state == "INVESTIGATING":
        return absent_diagnosis("investigation_in_progress", run_id=last)
    if run is None:
        return absent_diagnosis("not_investigated")
    run_id = run.get("entity_id")
    if state in ("OPEN", "REOPENED"):
        # Queued for a new investigation: the earlier one is superseded, not current.
        return absent_diagnosis("reinvestigation_pending", superseded_run_id=run_id)
    if run.get("status") != "REVIEWED":
        return absent_diagnosis("investigation_incomplete", run_id=run_id)
    result = run.get("result") or {}
    available, reason = investigation_status(result)
    review = review_status(final_review(result))
    if reason == "review_not_accepted":
        # The investigator's findings, labelled as not accepted by the independent reviewer: never "what happened".
        return absent_diagnosis(reason, run_id=run_id, review=review,
                                unaccepted={**_findings(run, result, result["investigation"]), "accepted": False, "review": review})
    if not available:
        return absent_diagnosis(reason, run_id=run_id, review=review)
    return {"available": True, "reason": None, "source": "agent_investigation", "superseded_run_id": None,
            **_findings(run, result, result["investigation"]), "review": review, "unaccepted_investigation": None}
