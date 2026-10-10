"""The arms: free baselines, the no-tools model arm (2 calls at most) and the agent adapter."""
import json

from stage3_eval.arms import AgentArm, CaseRef, NoToolsArm, RuleCodeArm, SymptomArm, notools_messages
from stage3_eval.records import FIELDS, from_ops_run

from .conftest import notools_turn_factory

CASE = CaseRef(key="E1:S1", world="E1", shipment_id="S1", case_id="C1", as_of="2026-09-14T09:00:00+00:00",
               symptoms=("MILESTONE_OVERDUE", "CUSTODY_TRANSFER_UNCONFIRMED"), rule_codes=("MISSED_MILESTONE", "CUSTODY_GAP"))


def test_rulecode_baseline_uses_the_frozen_order():
    r = RuleCodeArm().run(CASE)
    assert r.primary_cause == "CUSTODY_GAP" and r.cause_set() == ["CUSTODY_GAP", "MISSED_MILESTONE"] and r.calls_used == 0
    odd = RuleCodeArm().run(CaseRef(key="k", world="E1", shipment_id="s", rule_codes=("POSSIBLE_MISDELIVERY", "MISSED_MILESTONE")))
    assert odd.primary_cause == "MISSED_MILESTONE"     # codes outside amendment C's list come after it
    assert RuleCodeArm().run(CaseRef(key="k", world="E1", shipment_id="s")).primary_cause == "INSUFFICIENT_EVIDENCE"


def test_symptom_baseline_uses_the_frozen_table():
    assert SymptomArm().run(CASE).primary_cause == "CUSTODY_GAP"
    only = SymptomArm().run(CaseRef(key="k", world="E1", shipment_id="s", symptoms=("MILESTONE_OVERDUE",)))
    assert only.primary_cause == "MISSED_MILESTONE" and only.cause_set() == ["MISSED_MILESTONE"]


def test_notools_arm_uses_the_agent_prompt_and_no_tools():
    from operations.investigator import SYSTEM
    messages = notools_messages(CASE)
    packet = json.loads(messages[1]["content"])
    assert messages[0]["content"] == SYSTEM and packet["tools"] == [] and packet["case"]["symptoms"] == list(CASE.symptoms)
    assert "INSUFFICIENT_EVIDENCE" in packet["cause_codes"] and "UNKNOWN" in packet["cause_codes"]


def test_notools_valid_first_answer_costs_one_call():
    turn, calls = notools_turn_factory("HUB_DELAY")
    r = NoToolsArm(turn=turn).run(CASE)
    assert r.primary_cause == "HUB_DELAY" and r.calls_used == 1 and len(calls) == 1 and not r.degraded and r.cited_ids == []


def test_notools_retries_once_then_degrades():
    seen = []

    def turn(messages):
        seen.append(messages)
        return {"action": "call", "tool": "scans", "args": {}}
    r = NoToolsArm(turn=turn).run(CASE)
    assert r.degraded and r.calls_used == 2 and len(seen) == 2 and r.failure_mode == "invalid_model_output"
    assert "rejected" in seen[1][-1]["content"]


def test_notools_rejects_citations_and_counts_provider_failures():
    good, _ = notools_turn_factory("HUB_DELAY")
    answers = iter([{**good([]), "hypotheses": [{"cause": "HUB_DELAY", "status": "supported", "supporting_evidence_ids": ["X"]}]}, good([])])
    assert NoToolsArm(turn=lambda m: next(answers)).run(CASE).calls_used == 2

    def broken(messages):
        raise TimeoutError("provider")
    r = NoToolsArm(turn=broken).run(CASE)
    assert r.degraded and r.failure_mode == "model_unavailable" and r.provider_failures == 2 and r.calls_used == 2


def test_notools_abstention_is_allowed():
    turn, _ = notools_turn_factory("INSUFFICIENT_EVIDENCE")
    r = NoToolsArm(turn=turn).run(CASE)
    assert r.abstained and not r.degraded


def agent_abstention(**over):
    """The abstention the shared SYSTEM prompt asks for and the agent's validator accepts: the primary is
    INSUFFICIENT_EVIDENCE, the candidate cause is an uncertain hypothesis, the missing evidence is named and the next
    step gathers evidence. (No hypothesis carries the abstention code itself.)"""
    base = {"action": "conclude", "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low",
            "hypotheses": [{"cause": "HUB_DELAY", "status": "uncertain", "supporting_evidence_ids": [], "contradicting_evidence_ids": [],
                            "assessment": "The symptoms alone do not separate a hub delay from a late upload."}],
            "missing_evidence": ["the hub's scan log for the parcel"], "next_evidence_step": "Ask the hub for its scan log.",
            "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": "Not enough to name a cause."}
    return {**base, **over}


def test_notools_accepts_the_abstention_the_agents_validator_accepts():
    from operations.investigator import validate_conclusion
    answer = agent_abstention()
    assert validate_conclusion(answer, set()) is None           # the agent arm accepts this shape
    seen = []
    r = NoToolsArm(turn=lambda m: seen.append(m) or answer).run(CASE)
    assert not r.degraded and r.abstained and r.calls_used == 1 and len(seen) == 1


def test_notools_applies_the_agents_abstention_and_wording_rules():
    from operations.investigator import validate_conclusion
    from stage3_eval.arms import _notools_problem
    rejected = [
        agent_abstention(missing_evidence=[]),                                   # the missing evidence is not named
        agent_abstention(recommended_action="REROUTE_TO_CONFIRMED_DESTINATION"),              # not a next step that gathers evidence
        agent_abstention(hypotheses=[{"cause": "HUB_DELAY", "status": "supported"}]),   # a cause supported beside the abstention
        agent_abstention(primary_cause="UNKNOWN", missing_evidence=[]),          # UNKNOWN abstains under the same rules
        agent_abstention(next_evidence_step="The driver stole the parcel; ask the depot."),
        agent_abstention(next_evidence_step="The vehicle GPS proves the parcel was delivered."),
    ]
    for answer in rejected:
        assert validate_conclusion(answer, set()) is not None, answer            # the agent's validator rejects it
        assert _notools_problem(answer) == validate_conclusion(answer, set()), answer
        r = NoToolsArm(turn=lambda m, a=answer: a).run(CASE)
        assert r.degraded and r.calls_used == 2 and r.failure_mode == "invalid_model_output"
    # The one difference: a supported specific cause needs no citation here, and a citation is refused.
    specific = agent_abstention(primary_cause="HUB_DELAY", recommended_action="REQUEST_HUB_CHECK", missing_evidence=[],
                                hypotheses=[{"cause": "HUB_DELAY", "status": "supported", "supporting_evidence_ids": []}])
    assert _notools_problem(specific) is None and validate_conclusion(specific, set()) is not None
    assert specific["hypotheses"][0]["supporting_evidence_ids"] == []            # the stand-in citation never reaches the answer
    cited = agent_abstention(hypotheses=[{"cause": "HUB_DELAY", "status": "uncertain", "contradicting_evidence_ids": ["X"]}])
    assert "no evidence id can be cited" in _notools_problem(cited)
    unsupported = {**specific, "hypotheses": [{"cause": "HUB_DELAY", "status": "uncertain"}]}
    assert _notools_problem(unsupported) == "the primary cause must be a supported hypothesis"


def test_agent_arm_reads_an_s5_shaped_run_record():
    analysis = {"investigation": {"mode": "gpt-oss", "degraded": False, "steps": [{"tool": "scans", "args": {"package_id": "P"}, "evidence_ids": ["E1", "E2"]}],
                                  "retrieved_evidence_ids": ["E1", "E2"], "primary_cause": "HUB_DELAY", "confidence": "medium",
                                  "hypotheses": [{"cause": "HUB_DELAY", "status": "supported", "supporting_evidence_ids": ["E1"], "contradicting_evidence_ids": []},
                                                 {"cause": "ROUTE_DELAY", "status": "supported", "supporting_evidence_ids": ["E2"], "contradicting_evidence_ids": []},
                                                 {"cause": "DELAYED_SYNC", "status": "refuted", "supporting_evidence_ids": [], "contradicting_evidence_ids": ["E2"]}],
                                  "recommended_action": "REQUEST_HUB_CHECK", "summary": "s", "missing_evidence": []},
                "review": {"model_verdict": "ACCEPT"}, "trace": [{}], "degraded": [], "authority": {"risk_class": "AUTOMATIC"},
                "pipeline_events": [{"evidence_as_of": "2026-09-14T09:00:00+00:00"}], "model_calls_used": 8}
    runs = [{"recorded_at": "2026-09-14T09:01:00", "result_json": json.dumps(analysis)},
            {"recorded_at": "2026-09-15T09:01:00", "result_json": json.dumps({**analysis, "investigation": {**analysis["investigation"], "primary_cause": "X"}})}]
    r = from_ops_run("E1:S1", "S1", case={"entity_id": "C1", "workflow_state": "RESOLVED"}, runs=runs,
                     executions=[{"action_type": "REQUEST_HUB_CHECK", "authority": "AUTO_POLICY", "status": "EXECUTED"}],
                     outcomes=[{"outcome_type": "VERIFIED", "success": True, "verifier_id": "V"}])
    assert r.primary_cause == "HUB_DELAY"             # the FIRST investigation is scored
    assert r.calls_used == 8 and r.as_of == "2026-09-14T09:00:00+00:00" and r.review_verdict == "ACCEPT" and r.review_rounds == 1
    assert r.cited_ids == ["E1", "E2"] and r.cause_set() == ["HUB_DELAY", "ROUTE_DELAY"] and r.executions[0]["authority"] == "AUTO_POLICY"
    assert "model_calls_used" in FIELDS["calls_used"]
    none = from_ops_run("E1:S1", "S1", case={"entity_id": "C1"}, runs=[])
    assert none.degraded and none.failure_mode == "no_run_recorded"


def test_the_backends_nested_counter_is_lifted_as_integers_never_as_the_counter_object():
    counter = {"model_call_cap": 12, "model_calls_used": 5, "model_calls_by_role": {"investigator": 5}, "cap_reached": True, "calls_refused_by_cap": 1}
    investigation = {"mode": "model_call_cap", "degraded": True, "hypotheses": [], "primary_cause": None, "model_calls": counter}

    def read(analysis, **row):
        return from_ops_run("E1:S1", "S1", case={"entity_id": "C1"}, runs=[{"recorded_at": "t", "result_json": json.dumps(analysis), **row}])
    # No investigation log (the investigator failed before a round was logged): the investigator's own budget.
    nested = read({"investigation": investigation})
    assert (nested.calls_used, nested.cap_hit) == (5, True) and type(nested.calls_used) is int and nested.cap_hit is True
    # The log, when there is one, is the one counter.
    logged = read({"investigation": investigation, "investigation_log": {**counter, "model_calls_used": 7, "cap_reached": False}})
    assert (logged.calls_used, logged.cap_hit) == (7, False)
    # A name that holds the whole counter object (or anything that is not a count) is passed over, never returned.
    for bad in (counter, "7", 7.5, True, -1):
        odd = read({"investigation": {**investigation, "model_calls": None}, "model_calls_used": bad, "cap_hit": "yes", "total_tokens": bad})
        assert odd.calls_used is None and odd.tokens is None and odd.cap_hit is False, bad
    assert read({"investigation": investigation, "model_calls_used": counter}).calls_used == 5     # the next candidate still answers
    assert read({"investigation": {**investigation, "model_calls": None}}, model_calls_used=9).calls_used == 9   # the OpsRun row


def test_cause_set_is_capped_at_primary_plus_three():
    from stage3_eval.records import ArmResult
    hyps = [{"cause": c, "status": "supported"} for c in ("A", "B", "C", "D", "E")]
    assert ArmResult(case_key="k", arm="agent", shipment_id="s", primary_cause="A", hypotheses=hyps).cause_set() == ["A", "B", "C", "D"]


def test_agent_arm_names_and_times_results():
    arm = AgentArm(lambda case: __import__("stage3_eval.records", fromlist=["ArmResult"]).ArmResult(case_key="x", arm="x", shipment_id=case.shipment_id), 12)
    r = arm.run(CASE)
    assert r.arm == "agent" and r.case_key == "E1:S1" and r.wall_seconds is not None and arm.worst_case() == 12
