"""One normalised result shape for every arm, and the one adapter that reads the backend's run record into it.

The agent arm's raw record is the OpsRun analysis the pipeline writes (result_json: investigation, review, trace,
degraded, checks, authority, investigation_log, pipeline_events) plus the case's OpsExecution and OpsOutcome rows.
Every field name this harness reads is in FIELDS below and nowhere else; a name with dots is a path into nested
objects. The Stage 2 names are those of docs/api/investigation-run.md: the one per-case model-call counter is
investigation_log.model_calls_used, the snapshot investigation_log.snapshot_as_of and a cap hit
investigation_log.cap_reached. Adjust FIELDS, not the scorer.
"""
from dataclasses import asdict, dataclass, field
import json

from stage3_eval.design import ABSTAIN, MAX_SUPPORTED_HYPOTHESES

# Every backend field name the harness reads. Candidates are tried in order; the first present wins.
FIELDS = {
    "investigation": ("investigation",),
    "review": ("review",),
    "review_verdict": ("model_verdict", "verdict"),
    "trace": ("trace",),
    "degraded": ("degraded",),
    "authority": ("authority",),
    "risk_class": ("risk_class",),
    "pipeline_events": ("pipeline_events",),
    "evidence_as_of": ("evidence_as_of",),
    # The evidence snapshot of the run (t). Older records carry it only on their stage events (evidence_as_of).
    "snapshot": ("investigation_log.snapshot_as_of",),
    # Stage 2: one per-case counter over investigator turns, reviewer rounds, revisions and retries. A degraded run
    # with no log (the investigator failed before a round was logged) still has the investigator's own budget.
    "calls_used": ("investigation_log.model_calls_used", "investigation.model_calls.model_calls_used", "model_calls_used", "calls_used"),
    "tokens": ("model_tokens", "tokens_used", "total_tokens"),
    "cap_hit": ("investigation_log.cap_reached", "investigation.model_calls.cap_reached", "call_cap_hit", "cap_hit"),
    "wall_seconds": ("wall_seconds", "investigation_seconds"),
    "tool_seconds": ("tool_seconds", "query_seconds"),
}


def pick(record, name, default=None):
    for key in FIELDS[name]:
        value = record
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
            if value is None:
                break
        if value is not None:
            return value
    return default


@dataclass
class ArmResult:
    case_key: str
    arm: str
    shipment_id: str
    case_id: str | None = None
    as_of: str | None = None                 # the investigation's evidence snapshot (t)
    primary_cause: str | None = None
    hypotheses: list = field(default_factory=list)   # [{cause, status, supporting_evidence_ids, contradicting_evidence_ids, assessment}]
    confidence: str | None = None
    recommended_action: str | None = None
    retrieved_ids: list = field(default_factory=list)
    steps: list = field(default_factory=list)        # [{tool, args, evidence_ids, seconds?}]
    texts: list = field(default_factory=list)        # summary and assessments (scanned for blame, GPS misuse, vocabulary)
    degraded: bool = False
    failure_mode: str | None = None
    validation_error: str | None = None
    review_verdict: str | None = None
    review_rounds: int = 0
    authority: str | None = None
    executions: list = field(default_factory=list)   # [{action_type, authority, status}]
    outcomes: list = field(default_factory=list)     # [{type, success, verifier}]
    final_state: str | None = None
    calls_used: int | None = None
    tokens: int | None = None
    wall_seconds: float | None = None
    tool_seconds: list = field(default_factory=list)
    cap_hit: bool = False
    provider_failures: int = 0                       # provider (transport) failures among this arm's calls
    rule_codes: list = field(default_factory=list)   # baselines: the codes or symptoms they read
    cause_set_override: list | None = None           # B_rulecode: all its codes
    not_run: str | None = None                       # dry run, budget refusal, or an arm error

    @property
    def abstained(self):
        return self.primary_cause in ABSTAIN

    @property
    def cited_ids(self):
        return sorted({i for h in self.hypotheses for i in (h.get("supporting_evidence_ids") or []) + (h.get("contradicting_evidence_ids") or [])
                       if isinstance(i, str)})

    def cause_set(self):
        """Primary plus at most three supported hypotheses (amendment 1, C); a baseline's own set when it has one."""
        if self.cause_set_override is not None:
            return [c for c in self.cause_set_override if c not in ABSTAIN]
        out = [self.primary_cause] if self.primary_cause and self.primary_cause not in ABSTAIN else []
        for h in self.hypotheses:
            if len(out) >= 1 + MAX_SUPPORTED_HYPOTHESES:
                break
            if h.get("status") == "supported" and h.get("cause") not in out and h.get("cause") not in ABSTAIN:
                out.append(h["cause"])
        return out

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def from_investigation(case_key, arm, shipment_id, inv, **extra):
    """An ArmResult from an operations.investigator.investigate() result dict."""
    hyps = [{k: h.get(k) for k in ("cause", "status", "supporting_evidence_ids", "contradicting_evidence_ids", "assessment")}
            for h in inv.get("hypotheses") or []]
    return ArmResult(case_key=case_key, arm=arm, shipment_id=shipment_id, primary_cause=inv.get("primary_cause"), hypotheses=hyps,
                     confidence=inv.get("confidence"), recommended_action=inv.get("recommended_action"),
                     retrieved_ids=sorted(inv.get("retrieved_evidence_ids") or []),
                     steps=[{k: s.get(k) for k in ("tool", "args", "evidence_ids", "seconds") if k in s} for s in inv.get("steps") or []],
                     texts=[inv.get("summary") or "", *[h.get("assessment") or "" for h in hyps], *map(str, inv.get("missing_evidence") or [])],
                     degraded=bool(inv.get("degraded")), failure_mode=inv.get("mode") if inv.get("degraded") else None,
                     validation_error=inv.get("validation_error"), **extra)


def _load(value):
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return value or {}


def from_ops_run(case_key, shipment_id, *, case, runs, executions=(), outcomes=()):
    """The agent arm's result for one case from the backend ledger: `case` is the OpsCase properties, `runs` its OpsRun
    properties (the FIRST investigation is scored; later ones are kept for the every-case report), `executions` and
    `outcomes` the case's OpsExecution and OpsOutcome properties."""
    ordered = sorted(runs, key=lambda r: str(r.get("recorded_at")))
    if not ordered:
        return ArmResult(case_key=case_key, arm="agent", shipment_id=shipment_id, case_id=case.get("entity_id"),
                         degraded=True, failure_mode="no_run_recorded", not_run=None)
    first = ordered[0]
    analysis = _load(first.get("result_json"))
    inv = pick(analysis, "investigation", {}) or {}
    review = pick(analysis, "review", {}) or {}
    authority = pick(analysis, "authority", {}) or {}
    snapshot = pick(analysis, "snapshot") or next(
        (pick(e, "evidence_as_of") for e in pick(analysis, "pipeline_events", []) or [] if pick(e, "evidence_as_of")), None)
    degraded_roles = [d.get("role") for d in pick(analysis, "degraded", []) or [] if isinstance(d, dict)]
    result = from_investigation(case_key, "agent", shipment_id, inv, case_id=case.get("entity_id"),
                                as_of=str(snapshot) if snapshot else None,
                                review_verdict=pick(review, "review_verdict"), review_rounds=len(pick(analysis, "trace", []) or []),
                                authority=pick(authority, "risk_class"),
                                executions=[{"action_type": e.get("action_type"), "authority": e.get("authority"), "status": e.get("status")}
                                            for e in executions],
                                outcomes=[{"type": o.get("outcome_type"), "success": o.get("success"), "verifier": o.get("verifier_id")}
                                          for o in outcomes],
                                final_state=case.get("workflow_state"),
                                calls_used=pick(analysis, "calls_used", pick(first, "calls_used")),
                                tokens=pick(analysis, "tokens", pick(first, "tokens")),
                                wall_seconds=pick(analysis, "wall_seconds", pick(first, "wall_seconds")),
                                tool_seconds=list(pick(analysis, "tool_seconds", []) or []),
                                cap_hit=bool(pick(analysis, "cap_hit", False)))
    if "investigator" in degraded_roles and not result.degraded:
        result.degraded, result.failure_mode = True, "investigator_degraded"
    return result
