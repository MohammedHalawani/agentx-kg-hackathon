"""The arms, run step side. Nothing here reads truth: an arm sees only what the runtime shows a case (its shipment,
snapshot time, symptoms and rule codes), and this module imports nothing from the scorer (tested).

- agent:    the real pipeline (tools, investigator, reviewer, authority) on one opened case, through a callable the
            backend track supplies (WIRING.md). Worst case C_cap + R_cap calls, from the run record's own counter.
- notools:  the agent's model and system prompt on the agent's own opening packet, built by the agent's function
            (operations.investigator.case_packet: the case, the cause catalogue with its definitions and guidance,
            the action names with authority and summary, the limits, and no map from actions to causes), with one
            difference: the tool list is empty. INSUFFICIENT_EVIDENCE (or UNKNOWN) allowed under the agent's own
            abstention rules; at most 2 calls (one retry on invalid output, as the agent gets). Invalid after the
            retry counts as degraded, exactly like the agent.
- rulecode: the monitor's rule codes at opening, first in the frozen order (no model call).
- symptom:  the opening symptom names through the frozen table (no model call).

The no-tools arm cannot use operations.investigator.investigate as it stands: that validator requires a supported
primary cause to cite retrieved evidence, so with no tools every specific answer is rejected and only UNKNOWN passes.
This arm keeps the agent's prompt and catalogue and runs the agent's own validator (validate_conclusion), changing
exactly one rule: no evidence can be cited (there is none), so a primary cause may be "supported" without ids. An
answer the agent's validator accepts apart from citations is accepted here, and one it rejects is rejected here
(tested against that validator). WIRING.md records this.
"""
from dataclasses import dataclass, field
import json
import time

from stage3_eval.design import NOTOOLS_MAX_CALLS, RULECODE_ORDER, SYMPTOM_CAUSE, SYMPTOM_ORDER
from stage3_eval.records import ArmResult, from_investigation


@dataclass(frozen=True)
class CaseRef:
    """What an arm may know about a case: runtime facts only (no stratum, no truth)."""
    key: str
    world: str
    shipment_id: str
    case_id: str | None = None
    as_of: str | None = None
    symptoms: tuple = ()
    rule_codes: tuple = ()
    opening_evidence_ids: tuple = field(default=(), compare=False)


class Arm:
    name = "arm"
    uses_model = False

    def worst_case(self):
        return 0

    def run(self, case: CaseRef) -> ArmResult:
        raise NotImplementedError


class RuleCodeArm(Arm):
    name = "rulecode"

    def run(self, case):
        rank = {c: i for i, c in enumerate(RULECODE_ORDER)}
        codes = sorted(set(case.rule_codes), key=lambda c: (rank.get(c, len(RULECODE_ORDER)), c))
        primary = codes[0] if codes else "INSUFFICIENT_EVIDENCE"
        return ArmResult(case_key=case.key, arm=self.name, shipment_id=case.shipment_id, case_id=case.case_id, as_of=case.as_of,
                         primary_cause=primary, rule_codes=list(case.rule_codes), cause_set_override=codes, calls_used=0)


class SymptomArm(Arm):
    name = "symptom"

    def run(self, case):
        present = [s for s in SYMPTOM_ORDER if s in set(case.symptoms)]
        primary = SYMPTOM_CAUSE[present[0]] if present else "INSUFFICIENT_EVIDENCE"
        return ArmResult(case_key=case.key, arm=self.name, shipment_id=case.shipment_id, case_id=case.case_id, as_of=case.as_of,
                         primary_cause=primary, rule_codes=list(case.symptoms), cause_set_override=[primary], calls_used=0)


class AgentArm(Arm):
    """run_case(case) -> ArmResult, supplied by the backend track: it opens nothing and creates no database; it drives
    OperationsStore.process_one on the case's id and reads the result back with records.from_ops_run."""
    uses_model = True

    def __init__(self, run_case, c_cap, r_cap=0, name="agent"):
        self.run_case, self.c_cap, self.r_cap, self.name = run_case, int(c_cap), int(r_cap), name

    def worst_case(self):
        return self.c_cap + self.r_cap

    def run(self, case):
        started = time.perf_counter()
        result = self.run_case(case)
        result.arm, result.case_key = self.name, case.key
        if result.wall_seconds is None:
            result.wall_seconds = round(time.perf_counter() - started, 3)
        return result


class CountingTurn:
    """Wraps a model-call function and counts every call it makes (the no-tools arm's own counter)."""

    def __init__(self, turn):
        self.turn, self.calls = turn, 0

    def __call__(self, messages):
        self.calls += 1
        return self.turn(messages)


NO_EVIDENCE = "<no evidence was retrieved>"    # Stands in for a citation inside the agent's validator; never stored or shown.


def _notools_problem(out):
    """The agent's own validator (operations.investigator.validate_conclusion) with exactly one rule changed: no
    evidence id may be cited, so a supported primary cause needs no citation. Every other rule is the agent's code
    path, not a copy: the abstention rules (missing evidence named, an evidence-gathering or human next step, no
    supported cause beside the abstention), the schema, the prohibited actions and the blame and GPS wording scan
    (next_evidence_step included)."""
    from operations.investigator import validate_conclusion
    if not isinstance(out, dict) or out.get("action") not in ("call", "conclude"):
        return "reply must be one JSON object with action call or conclude"
    if out["action"] == "call":
        return "no tools are available for this case; conclude now with what you have"
    hypotheses = out.get("hypotheses")
    probe = out
    if isinstance(hypotheses, list):
        for h in hypotheses:
            if isinstance(h, dict) and ((h.get("supporting_evidence_ids") or []) or (h.get("contradicting_evidence_ids") or [])):
                return "no evidence was retrieved, so no evidence id can be cited"
        # The agent's validator asks a supported primary cause for a citation; here it gets a stand-in, on a copy.
        probe = {**out, "hypotheses": [{**h, "supporting_evidence_ids": [NO_EVIDENCE]}
                                       if isinstance(h, dict) and h.get("cause") == out.get("primary_cause") and h.get("status") == "supported"
                                       else h for h in hypotheses]}
    problem = validate_conclusion(probe, {NO_EVIDENCE})
    if problem and problem.startswith("the primary cause must be a supported hypothesis"):
        return "the primary cause must be a supported hypothesis"
    return problem


class _NoTools:
    """The agent's tool belt as operations.investigator.case_packet reads it (shipment, snapshot, symptoms, tool
    descriptions), with no tool on it."""

    def __init__(self, case: CaseRef):
        self.sid, self.as_of, self.symptoms = case.shipment_id, case.as_of, list(case.symptoms)

    def describe(self):
        return []


def notools_packet(case: CaseRef, c_cap=None):
    """The agent's opening packet from the agent's own function (operations.investigator.case_packet), for a tool belt
    with no tools: every entry but "tools" is what the agent is sent on this case at the same per-case cap (tested).
    c_cap: the agent's per-case model-call cap (the sealed C_cap), which the packet's limits state; None is the
    investigator's own default, as for an agent session built without a cap."""
    from operations.investigator import Session, case_packet
    return case_packet(_NoTools(case), Session(c_cap))


def notools_messages(case: CaseRef, c_cap=None):
    """The agent's opening messages (operations.investigator.investigate's) with an empty tool list."""
    from operations.investigator import SYSTEM
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(notools_packet(case, c_cap), ensure_ascii=False)}]


class NoToolsArm(Arm):
    name = "notools"
    uses_model = True

    def __init__(self, turn=None, c_cap=None):
        self.turn, self.c_cap = turn, c_cap

    def bind_config(self, config):
        """The run step hands every arm the sealed configuration before the first case: the packet states the agent's
        sealed per-case cap unless one was given when the arm was built."""
        if self.c_cap is None:
            self.c_cap = config.c_cap

    def worst_case(self):
        return NOTOOLS_MAX_CALLS

    def run(self, case):
        from operations.investigator import model_turn
        counter = CountingTurn(self.turn or model_turn)
        messages = notools_messages(case, self.c_cap)
        started = time.perf_counter()
        out, problem, provider_failures = None, None, 0
        for _attempt in range(NOTOOLS_MAX_CALLS):
            extra = [{"role": "user", "content": f"Your previous reply was rejected: {problem}. Reply with one corrected JSON object."}] if problem else []
            try:
                out = counter(messages + extra)
            except Exception as exc:   # provider failure: type only, as the investigator records it
                problem, out, provider_failures = f"model call failed ({type(exc).__name__})", None, provider_failures + 1
                continue
            problem = _notools_problem(out)
            if problem is None:
                break
            out = None
        wall = round(time.perf_counter() - started, 3)
        if out is None:
            inv = {"degraded": True, "mode": "model_unavailable" if str(problem).startswith("model call failed") else "invalid_model_output",
                   "validation_error": problem, "hypotheses": [], "primary_cause": None}
        else:
            inv = {**out, "degraded": False, "retrieved_evidence_ids": [], "steps": []}
        result = from_investigation(case.key, self.name, case.shipment_id, inv, case_id=case.case_id, as_of=case.as_of,
                                    calls_used=counter.calls, wall_seconds=wall, provider_failures=provider_failures)
        result.rule_codes = list(case.symptoms)
        return result
