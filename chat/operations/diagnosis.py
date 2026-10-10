"""The case diagnosis served to operators: the current run's agent investigation, or explicitly absent.

Only a completed agent investigation (GPT-OSS tool loop, independently reviewed) is a diagnosis. Rule
checks are served separately as rule signals; they never fill this field. While a newer investigation
is queued or running, the earlier one is not shown as current.
"""

ABSENT_REASONS = ("not_a_case", "no_operations_ledger", "not_investigated", "investigation_in_progress",
                  "reinvestigation_pending", "investigation_incomplete", "no_agent_investigation", "investigation_unavailable")
HYPOTHESIS_FIELDS = ("cause", "status", "assessment", "supporting_evidence_ids", "contradicting_evidence_ids")


def absent_diagnosis(reason, *, run_id=None, superseded_run_id=None):
    if reason not in ABSENT_REASONS:
        raise ValueError("Unknown absent-diagnosis reason")
    return {"available": False, "reason": reason, "source": None, "run_id": run_id, "superseded_run_id": superseded_run_id,
            "as_of": None, "investigated_at": None, "primary_cause": None, "confidence": None, "summary": None,
            "hypotheses": [], "missing_evidence": [], "requires_physical_check": None, "tool_calls": 0,
            "snapshot_superseded": False, "language": None}


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
    investigation = result.get("investigation")
    if result.get("mode") != "gpt_oss_agents" or not investigation:
        return absent_diagnosis("no_agent_investigation", run_id=run_id)
    if investigation.get("degraded") or not investigation.get("primary_cause"):
        return absent_diagnosis("investigation_unavailable", run_id=run_id)
    return {"available": True, "reason": None, "source": "agent_investigation", "run_id": run_id, "superseded_run_id": None,
            "as_of": (result.get("result") or {}).get("as_of"), "investigated_at": run.get("recorded_at"),
            "primary_cause": investigation["primary_cause"], "confidence": investigation.get("confidence"),
            "summary": investigation.get("summary"),
            "hypotheses": [{key: h.get(key) for key in HYPOTHESIS_FIELDS} for h in investigation.get("hypotheses") or []],
            "missing_evidence": list(investigation.get("missing_evidence") or []),
            "requires_physical_check": investigation.get("requires_physical_check"),
            "tool_calls": len(investigation.get("steps") or []),
            "snapshot_superseded": any(d.get("role") == "snapshot" for d in result.get("degraded") or []),
            # Model prose (summary, assessments) is the investigator's own text, untranslated.
            "language": "en"}
