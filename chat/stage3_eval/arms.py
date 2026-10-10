"""The arms, run step side. Nothing here reads truth: an arm sees only what the runtime shows a case (its shipment,
snapshot time, symptoms and rule codes), and this module imports nothing from the scorer (tested).

- agent:    the real pipeline (tools, investigator, reviewer, authority) on one opened case, through a callable the
            backend track supplies (WIRING.md). Worst case C_cap + R_cap calls, from the run record's own counter.
- notools:  the agent's model, system prompt, cause catalogue, action catalogue and output format on the same opening
            packet, with no tools; INSUFFICIENT_EVIDENCE (or UNKNOWN) allowed; at most 2 calls (one retry on
            invalid output, as the agent gets). Invalid after the retry counts as degraded, exactly like the agent.
- rulecode: the monitor's rule codes at opening, first in the frozen order (no model call).
- symptom:  the opening symptom names through the frozen table (no model call).

The no-tools arm cannot use operations.investigator.investigate as it stands: that validator requires a supported
primary cause to cite retrieved evidence, so with no tools every specific answer is rejected and only UNKNOWN passes.
This arm keeps the agent's prompt, catalogue, schema and safety rules and changes exactly one rule: no evidence can
be cited (there is none), so a primary cause may be "supported" without ids. WIRING.md records this.
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


def _notools_problem(out):
    from operations.agents import BLAME, GPS_DELIVERY
    from operations.authority import ACTIONS
    from operations.investigator import CAUSE_CHOICES
    if not isinstance(out, dict) or out.get("action") not in ("call", "conclude"):
        return "reply must be one JSON object with action call or conclude"
    if out["action"] == "call":
        return "no tools are available for this case; conclude now with what you have"
    hypotheses = out.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        return "hypotheses must be a non-empty list"
    if out.get("primary_cause") not in CAUSE_CHOICES:
        return "primary_cause must be one of the cause codes"
    if out.get("confidence") not in ("low", "medium", "high"):
        return "confidence must be low|medium|high"
    action = out.get("recommended_action")
    if action not in ACTIONS:
        return "recommended_action must be one of the action types"
    if ACTIONS[action][0] == "PROHIBITED":
        return "Prohibited actions (money, liability, blame) cannot be recommended"
    primary = None
    for h in hypotheses:
        if not isinstance(h, dict) or h.get("cause") not in CAUSE_CHOICES or h.get("status") not in ("supported", "refuted", "uncertain"):
            return "each hypothesis needs a cause code and status supported|refuted|uncertain"
        if (h.get("supporting_evidence_ids") or []) or (h.get("contradicting_evidence_ids") or []):
            return "no evidence was retrieved, so no evidence id can be cited"
        if h["cause"] == out["primary_cause"]:
            primary = h
    if out["primary_cause"] != "UNKNOWN" and (primary is None or primary["status"] != "supported"):
        return "the primary cause must be a supported hypothesis"
    for text in [out.get("summary", ""), *[h.get("assessment", "") for h in hypotheses], *map(str, out.get("missing_evidence") or [])]:
        if BLAME.search(text or ""):
            return "output attributes blame or wrongdoing to a person"
        if GPS_DELIVERY.search(text or ""):
            return "output treats vehicle GPS as parcel delivery or location evidence"
    return None


def notools_messages(case: CaseRef):
    """The agent's opening messages with an empty tool catalogue (operations.investigator.investigate's packet)."""
    from operations.authority import ACTIONS
    from operations.investigator import CAUSE_CHOICES, SYSTEM
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({
                "case": {"shipment_id": case.shipment_id, "as_of": case.as_of, "symptoms": list(case.symptoms)},
                "tools": [], "cause_codes": list(CAUSE_CHOICES),
                "action_types": {k: {"authority": v[0], "addresses": sorted(v[1]), "summary": v[3]} for k, v in ACTIONS.items()},
                "limits": {"max_tool_calls": 0}}, ensure_ascii=False)}]


class NoToolsArm(Arm):
    name = "notools"
    uses_model = True

    def __init__(self, turn=None):
        self.turn = turn

    def worst_case(self):
        return NOTOOLS_MAX_CALLS

    def run(self, case):
        from operations.investigator import model_turn
        counter = CountingTurn(self.turn or model_turn)
        messages = notools_messages(case)
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
