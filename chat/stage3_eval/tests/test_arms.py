"""The arms: free baselines, the no-tools model arm (2 attempts at a conclusion, 3 calls at most) and the agent adapter."""
import json

from stage3_eval.arms import (NOTOOLS_NOTE, NOTOOLS_SEPARATOR, REPLY_TEXT_LIMIT, AgentArm, CaseRef, NoToolsArm, RuleCodeArm, SymptomArm,
                              notools_messages, retry_message)
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


def _agent_packet(case, c_cap):
    """The packet investigate() sends for this case: case_packet over the agent's real tool belt class (its catalogue
    and describe(), with no database behind it) and a session at the given cap."""
    from operations.investigator import Session, case_packet
    from operations.tools import InvestigationTools
    belt = InvestigationTools.__new__(InvestigationTools)
    belt.sid, belt.as_of, belt.symptoms, belt.disabled = case.shipment_id, case.as_of, list(case.symptoms), frozenset()
    return case_packet(belt, Session(c_cap))


def test_notools_packet_is_the_agents_packet_apart_from_the_tools():
    from operations.investigator import CATALOGUE_GUIDANCE, SYSTEM, cause_catalogue
    for c_cap in (16, 12):
        agent = json.loads(json.dumps(_agent_packet(CASE, c_cap), ensure_ascii=False))   # as it goes on the wire
        messages = notools_messages(CASE, c_cap)
        text, note = messages[1]["content"].split(NOTOOLS_SEPARATOR, 1)     # the packet is one line of JSON, then the note
        packet = json.loads(text)
        assert messages[0]["content"] == SYSTEM and len(messages) == 2 and note == NOTOOLS_NOTE
        assert agent["tools"] and packet["tools"] == []                    # the one difference
        assert list(packet) == list(agent)                                 # the same entries, in the same order
        assert {k: v for k, v in packet.items() if k != "tools"} == {k: v for k, v in agent.items() if k != "tools"}
        assert packet["limits"]["model_turns_available"] == c_cap - 1      # the agent's cap, less the call kept for review
    # What the agent is sent: the catalogue with definitions and its guidance, and no map from actions to causes.
    assert packet["cause_catalogue"] == cause_catalogue() and packet["cause_catalogue_guidance"] == CATALOGUE_GUIDANCE
    assert "definition" in packet["cause_catalogue"]["abstention"]["INSUFFICIENT_EVIDENCE"]
    assert "cause_codes" not in packet and all(set(entry) == {"authority", "summary"} for entry in packet["action_types"].values())
    assert "addresses" not in messages[1]["content"] and packet["case"]["symptoms"] == list(CASE.symptoms)


def test_the_opening_message_says_no_tools_and_a_conclusion_now_and_names_no_cause():
    """(a) The arm's opening user message states that no tools are available on this case and that a conclusion, or
    INSUFFICIENT_EVIDENCE with what is missing and a next step, is required now. It names no cause."""
    from operations.investigator import CAUSE_CATALOGUE
    turn, calls = notools_turn_factory("HUB_DELAY")
    NoToolsArm(turn=turn, c_cap=16).run(CASE)
    opening = calls[0]
    assert [m["role"] for m in opening] == ["system", "user"]                   # one opening user message, nothing after it
    note = opening[1]["content"].split(NOTOOLS_SEPARATOR, 1)[1]
    assert note == NOTOOLS_NOTE and note.startswith("No tools are available on this case")
    assert "Reply with action conclude now" in note and "INSUFFICIENT_EVIDENCE" in note
    assert "what is missing" in note and "the next step" in note
    specific = [code for group in ("observations", "mechanisms") for code in CAUSE_CATALOGUE[group]]
    assert len(specific) == 19 and not [code for code in specific if code in note]
    assert "UNKNOWN" not in note


def test_notools_arm_sends_that_packet_at_the_sealed_cap(monkeypatch):
    from .conftest import make_config
    monkeypatch.setenv("SUHAIL_MODEL_CALL_CAP", "7")                       # the environment's cap is not the sealed one
    turn, calls = notools_turn_factory("HUB_DELAY")
    arm = NoToolsArm(turn=turn)
    arm.bind_config(make_config(c_cap=16))                                 # what the run step does before the first case
    arm.run(CASE)
    assert calls[0] == notools_messages(CASE, 16)
    assert json.loads(calls[0][1]["content"].split(NOTOOLS_SEPARATOR, 1)[0])["limits"] == _agent_packet(CASE, 16)["limits"]
    given = NoToolsArm(turn=turn, c_cap=14)                                # a cap given at construction is kept
    given.bind_config(make_config(c_cap=16))
    assert given.c_cap == 14


def test_notools_valid_first_answer_costs_one_call():
    turn, calls = notools_turn_factory("HUB_DELAY")
    r = NoToolsArm(turn=turn).run(CASE)
    assert r.primary_cause == "HUB_DELAY" and r.calls_used == 1 and len(calls) == 1 and not r.degraded and r.cited_ids == []


def invalid_conclusion(**over):
    """A conclusion the validator rejects: its primary cause is not a cause code (the commonest failure of the first run)."""
    good, _ = notools_turn_factory("HUB_DELAY")
    return {**good([]), "primary_cause": "a hub delay", **over}


def scripted(*replies):
    """A model that gives these replies in order (an exception is raised), recording every conversation it is sent."""
    seen, left = [], list(replies)

    def turn(messages):
        seen.append([dict(m) for m in messages])
        reply = left.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return turn, seen


def test_the_retry_conversation_holds_the_rejected_reply_then_the_rejection():
    """(b) The retry is the conversation continued: the opening messages, the model's rejected reply as the assistant's
    message, then the rejection in the agent's own retry words."""
    import inspect
    from operations import investigator
    good, _ = notools_turn_factory("HUB_DELAY")
    rejected = '{"action": "conclude", "primary_cause": "a hub delay", "hypotheses": []}'       # the model's text, as replied
    turn, seen = scripted(rejected, good([]))
    r = NoToolsArm(turn=turn, c_cap=16).run(CASE)
    assert not r.degraded and r.primary_cause == "HUB_DELAY" and r.calls_used == 2
    opening = notools_messages(CASE, 16)
    assert seen[0] == opening
    assert seen[1][:2] == opening and [m["role"] for m in seen[1]] == ["system", "user", "assistant", "user"]
    assert seen[1][2] == {"role": "assistant", "content": rejected}                       # the reply itself, not a summary of it
    problem = r.attempts[0]["validation_error"]
    assert problem == "hypotheses must be a non-empty list" and seen[1][3] == {"role": "user", "content": retry_message(problem)}
    # The agent's own corrective line, word for word.
    assert 'f"Your previous reply was rejected: {problem}. Reply with one corrected JSON object."' in inspect.getsource(investigator.investigate)
    assert retry_message("X") == "Your previous reply was rejected: X. Reply with one corrected JSON object."


def test_the_arm_gets_two_attempts_at_its_conclusion_as_the_agents_conclusion_does():
    """(c) Two attempts at a conclusion (operations.investigator.ATTEMPTS_PER_TURN), then degraded; a reply that is not
    a conclusion is corrected once without using one of them; never more than 3 calls."""
    from operations.investigator import ATTEMPTS_PER_TURN
    from stage3_eval.design import NOTOOLS_CONCLUSION_ATTEMPTS, NOTOOLS_MAX_CALLS
    good, _ = notools_turn_factory("HUB_DELAY")
    call = {"action": "call", "tool": "scans", "args": {}}
    assert NOTOOLS_CONCLUSION_ATTEMPTS == ATTEMPTS_PER_TURN == 2 and NOTOOLS_MAX_CALLS == 3 == NoToolsArm().worst_case()
    # Two invalid conclusions: degraded after 2 calls; a third is never made.
    turn, seen = scripted(invalid_conclusion(), invalid_conclusion(), good([]))
    r = NoToolsArm(turn=turn).run(CASE)
    assert r.degraded and r.failure_mode == "invalid_model_output" and r.calls_used == 2 == len(seen)
    assert r.validation_error == "primary_cause must be one of the cause codes"
    # A tool call first: both attempts at the conclusion are still there, and the second one is accepted (3 calls).
    turn, seen = scripted(call, invalid_conclusion(), good([]))
    r = NoToolsArm(turn=turn).run(CASE)
    assert not r.degraded and r.primary_cause == "HUB_DELAY" and r.calls_used == 3 == len(seen)
    assert [a["kind"] for a in r.attempts] == ["not_a_conclusion", "conclusion", "conclusion"]
    # Never a fourth call, whatever the replies: three tool calls end degraded at the arm's maximum.
    turn, seen = scripted(call, call, call, good([]))
    r = NoToolsArm(turn=turn).run(CASE)
    assert r.degraded and r.calls_used == 3 == len(seen) and r.failure_mode == "invalid_model_output"
    assert "rejected" in seen[1][-1]["content"] and "no tools are available" in seen[1][-1]["content"]


def test_a_first_reply_that_calls_a_tool_is_followed_by_a_valid_conclusion_and_accepted():
    good, _ = notools_turn_factory("HUB_DELAY")
    call = {"action": "call", "tool": "shipment_overview", "args": {}, "purpose": "Start with the case's records."}
    turn, seen = scripted(call, good([]))
    r = NoToolsArm(turn=turn, c_cap=16).run(CASE)
    assert not r.degraded and r.failure_mode is None and r.primary_cause == "HUB_DELAY" and r.calls_used == 2 == len(seen)
    assert seen[1][2] == {"role": "assistant", "content": json.dumps(call, ensure_ascii=False)}
    assert seen[1][3]["content"] == retry_message("no tools are available for this case; conclude now with what you have")
    assert [(a["kind"], a["validation_error"]) for a in r.attempts] == [
        ("not_a_conclusion", "no tools are available for this case; conclude now with what you have"), ("conclusion", None)]


def test_every_attempts_reply_text_and_validation_error_is_recorded_bounded_and_screened(tmp_path):
    """(d) The reply text of every attempt (bounded) and its validation error are on the arm result, in what the run
    writes to results/ and captured/arm_outputs/, and under the run's marker screen."""
    from stage3_eval.canary import marker_hits
    from stage3_eval.records import ArmResult
    from stage3_eval.runner import RunWriter
    good, _ = notools_turn_factory("HUB_DELAY")
    prose = "I would first look at the scans. " * 400                                     # no JSON object at all, and long
    assert len(prose) > REPLY_TEXT_LIMIT
    turn, seen = scripted(prose, json.dumps(invalid_conclusion()), good([]))
    r = NoToolsArm(turn=turn).run(CASE)
    assert not r.degraded and r.calls_used == 3
    assert [a["attempt"] for a in r.attempts] == [1, 2, 3]
    assert r.attempts[0] == {"attempt": 1, "kind": "not_a_conclusion", "reply": prose[:REPLY_TEXT_LIMIT], "reply_chars": len(prose),
                             "validation_error": "reply must be one JSON object with action call or conclude"}
    assert r.attempts[1]["reply"] == json.dumps(invalid_conclusion()) and r.attempts[1]["validation_error"] == "primary_cause must be one of the cause codes"
    assert json.loads(r.attempts[2]["reply"])["primary_cause"] == "HUB_DELAY" and r.attempts[2]["validation_error"] is None
    assert seen[1][2]["content"] == prose[:REPLY_TEXT_LIMIT]                              # the retry is bounded too
    # A rejected reply is recorded, not scored: `texts` holds the accepted conclusion's wording only.
    assert not [t for t in r.texts if "look at the scans" in t]
    # A degraded result carries its replies as well (the first run recorded none: texts was [""]).
    turn, _seen = scripted(invalid_conclusion(), TimeoutError("provider"), invalid_conclusion(summary="Second try."))
    lost = NoToolsArm(turn=turn).run(CASE)
    assert lost.degraded and lost.calls_used == 3 and lost.provider_failures == 1
    assert [(a["kind"], bool(a["reply"])) for a in lost.attempts] == [("conclusion", True), ("provider_failure", False), ("conclusion", True)]
    assert lost.attempts[1]["validation_error"] == "model call failed (TimeoutError)" and "Second try." in lost.attempts[2]["reply"]
    # Written with the result, read back whole, and an older record without the field still loads.
    writer = RunWriter(tmp_path / "run")
    writer.result(r)
    for relative in ("results/main/notools.jsonl", "captured/arm_outputs/main_notools.jsonl"):
        line = json.loads((tmp_path / "run" / relative).read_text(encoding="utf-8"))
        assert line["attempts"] == r.attempts and ArmResult.from_dict(line).attempts == r.attempts
    assert ArmResult.from_dict({k: v for k, v in r.to_dict().items() if k != "attempts"}).attempts == []
    # The marker screen reads the result's whole dictionary: a marker-shaped token in a REJECTED reply is a hit.
    assert marker_hits(r.to_dict()) == 0
    turn, _seen = scripted("see CNRY" + "0123456789abcdef01234567" + " and W1M-00042", good([]))
    assert marker_hits(NoToolsArm(turn=turn).run(CASE).to_dict()) == 2


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
