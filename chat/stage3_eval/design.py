"""The frozen Stage 3 design, as constants the harness enforces.

Source: docs/plans/2026-10-10_stage3_evaluation_design.md on fhd, frozen at b1d331f, with amendment 1 (001bcbf),
amendment 2 (ac6f857, Fahad's 4,000-call cap), the addendum to amendment 2 (7af0d5c), amendment 3 (15514ac: the budget
is what the campaign ledger has left, per-case cap 16, progressive looks) and the addendum to amendment 3 (6f0ed49:
Stage 3 stops at 3,600 calls, 190 cases). Where they differ, the later text wins. On 2026-10-11 the product owner
lifted the model-call budget: the 4,000 cap, the 3,600 stop line and the 400 reserve are no longer limits, the
evaluation is sized from the planning allocation below (its statistical targets) and the campaign ledger's cap is only
a runaway guard. Nothing here is computed from results: every bar, size and order is fixed before any evaluation
case exists. Changing a value here after the first evaluation run changes the sealed configuration hash, and the
run validity check then reports the run as not matching its sealed configuration (amendment 1, H).

The two baseline tables at the bottom (B_rulecode order and the B_symptom table) are the ones amendment 1, C and F
ask to be committed with the stratum script before any evaluation case exists.
"""
from dataclasses import asdict, dataclass, field
import hashlib
import json

DESIGN_DOCUMENT = "docs/plans/2026-10-10_stage3_evaluation_design.md"
DESIGN_COMMITS = {"frozen": "b1d331f", "amendment_1": "001bcbf", "amendment_2": "ac6f857", "addendum_2": "7af0d5c",
                  "amendment_3": "15514ac", "addendum_3": "6f0ed49"}

# ------------------------------------------------------------------------------ budget (amendments 2 and 3)
# HISTORICAL, and gating nothing: the cap of amendment 2 and the stop line of the addendum to amendment 3, both lifted
# on 2026-10-11. They remain as the origin of the planning allocation (285 cases = floor(4,000 / 14)) and as the
# defaults of the two historical helpers below (n_main, evaluation_budget), which `select` and `run` no longer call.
# A stop line is now an option (`select --stop-at N`, off by default), sealed as EvalConfig.stop_at.
CALL_BUDGET = 4000
STAGE3_STOP_AT = 3600
# Amendment 2's planning value, kept only as the origin of the allocation table below (285 cases at 12) and as the
# default of a configuration nobody sealed (the fixture). It is not the cap of the evaluation: C_cap is given to
# `select` (--c-cap, required), sealed in the selection, and the wiring refuses to run unless the backend's cap
# equals it. Amendment 3 sets it to 16 (the development data is censored at 12), one counter, R_cap 0.
C_CAP_PLANNING = 12
# B_notools (corrected 2026-10-11; a prepared correction, not used in any run yet: README, "The no-tools arm").
# The arm gets the attempts at its conclusion that the agent's conclusion gets: NOTOOLS_CONCLUSION_ATTEMPTS = 2, which is
# operations.investigator.ATTEMPTS_PER_TURN (one call plus its one corrective retry; tested equal). As for the agent,
# a reply that is not a conclusion (a tool call, or no JSON object) is corrected and is not one of those attempts; the
# arm allows one such reply. So the arm makes at most 3 calls.
NOTOOLS_CONCLUSION_ATTEMPTS = 2
NOTOOLS_REDIRECTS = 1
NOTOOLS_MAX_CALLS = NOTOOLS_CONCLUSION_ATTEMPTS + NOTOOLS_REDIRECTS
# What every selection sealed before the correction holds (addendum 2, item 2: one call plus one retry, 2 calls in
# all). The historical sizing helpers below keep it, and sealed_notools_max_calls recognises such a selection.
NOTOOLS_MAX_CALLS_BEFORE_CORRECTION = 2


def n_main(c_cap=C_CAP_PLANNING, r_cap=0, budget=CALL_BUDGET):
    """HISTORICAL (no longer sizes a selection). N_main = floor(budget / (C_cap + R_cap + 2)) (amendment 2 and its
    addendum, item 1): 285 at the planning figures (12 and 4,000), 190 at 16 and 3,427 (addendum to amendment 3)."""
    if c_cap < 1 or r_cap < 0:
        raise ValueError("C_cap must be at least 1 and R_cap at least 0")
    return budget // (c_cap + r_cap + NOTOOLS_MAX_CALLS_BEFORE_CORRECTION)


def evaluation_budget(spent, reserve=0, cap=CALL_BUDGET, stop_at=STAGE3_STOP_AT):
    """HISTORICAL (no longer sizes a selection): the budget `select` sealed under amendment 3 at a campaign ledger of
    `spent` calls, i.e. what the campaign had left, and never more than what was left before the stop line."""
    return min(cap - spent - reserve, stop_at - spent)


def worst_case_per_case(c_cap=C_CAP_PLANNING, r_cap=0):
    """Calls a main-test case may spend at most: the agent arm under its one per-case counter, plus B_notools."""
    return c_cap + r_cap + NOTOOLS_MAX_CALLS


def worst_case_calls(n_cases, n_ablation, n_stability, c_cap, r_cap=0):
    """The most a selection can spend, part by part: every selected case at its per-case worst (agent arm plus
    B_notools), and every listed extra at the agent arm's cap. `select` seals the total as the run's budget. Nothing
    is sized from it (the sizes come from the allocation's targets and the world): it is what the run holds in the
    campaign ledger while it is going, and what the run's own ledger refuses to pass."""
    if c_cap < 1 or r_cap < 0:
        raise ValueError("C_cap must be at least 1 and R_cap at least 0")
    main = n_cases * worst_case_per_case(c_cap, r_cap)
    ablation, stability = n_ablation * (c_cap + r_cap), n_stability * (c_cap + r_cap)
    return {"main": main, "cross_shipment_ablation": ablation, "stability_rerun": stability, "total": main + ablation + stability}


# ---------------------------------------------------------------------------------------------- strata and worlds
STRATA = ("identifiable_ambiguous", "determined", "unidentifiable")
WORLDS = ("E1", "E2")
# The allocation: the design's statistical targets (amendment 2's table, 285 cases; 160 E1 cases detect a gain of
# about 13 to 15 points). A selection takes each cell's target, or every case the world holds in that cell when it
# holds fewer (recorded per cell, never an error). No budget shrinks it.
ALLOCATION_AT_PLANNING = {
    ("E1", "identifiable_ambiguous"): 160,
    ("E2", "identifiable_ambiguous"): 60,
    ("E1", "determined"): 30, ("E2", "determined"): 10,
    ("E1", "unidentifiable"): 20, ("E2", "unidentifiable"): 5,
}
# HISTORICAL (selection.allocate, which `select` no longer calls): under a budget that gave N_main < 285, cases were
# removed in this order, each step down to its floor (amendment 2, sizing rule).
SHRINK_ORDER = (
    ("unidentifiable", ("E1", "E2"), 15),     # unidentifiable, both worlds together, down to 15
    ("determined", ("E1", "E2"), 30),         # determined, both worlds together, down to 30
    ("identifiable_ambiguous", ("E2",), 40),  # E2 identifiable ambiguous down to 40
    ("identifiable_ambiguous", ("E1",), 0),   # then E1 (which keeps at least 150 if N_main allows)
)
E1_MAIN_FLOOR = 150
MAIN_TEST_CELL = ("E1", "identifiable_ambiguous")   # The only pass or fail (addendum 2, item 4).
STRATUM_MIN_SUPPORT = 5       # Census rule: a symptom set needs at least 5 shipments, else the generator's map (amendment 1, F).
MAX_SUPPORTED_HYPOTHESES = 3  # Cause set: primary plus at most three supported hypotheses (amendment 1, C).

# ---------------------------------------------------------------------------------------------- statistics
ALPHA = 0.05
POWER_TARGET = 0.80
DISCORDANCE_PLANNING = (0.35, 0.45)
PROVIDER_FAILURE_LIMIT = 0.05      # Run invalid if provider failures exceed 5% of calls (amendment 1, H).
PREMATURE_WINDOW_HOURS = 24        # Premature closure: re-detected within 24 simulated hours (amendment 1, K).
LATENCY_PERCENTILES = {"investigation": (50, 90, 99), "tool_query": (50, 95)}

PASS_BARS = (
    {"id": "agent_beats_rulecode", "cell": MAIN_TEST_CELL, "agent": "agent", "baseline": "rulecode",
     "test": "exact two-sided McNemar", "alpha": ALPHA, "also_requires": "more agent wins than losses",
     "supports": "the investigator adds value over the monitor's rule codes"},
    {"id": "agent_beats_notools", "cell": MAIN_TEST_CELL, "agent": "agent", "baseline": "notools",
     "test": "exact two-sided McNemar", "alpha": ALPHA, "also_requires": "more agent wins than losses",
     "supports": "retrieval helps (the only bar that supports this claim)"},
)
DESCRIPTIVE_CELLS = {
    ("E2", "identifiable_ambiguous"): "held-out (unseen providers and pairings); descriptive, Wilson intervals, no pass bar",
    ("E1", "determined"): "descriptive; any agent result below B_rulecode is flagged as a regression",
    ("E2", "determined"): "descriptive; any agent result below B_rulecode is flagged as a regression",
    ("E1", "unidentifiable"): "abstention and escalation; descriptive",
    ("E2", "unidentifiable"): "abstention and escalation; descriptive",
}
RELEASE_BAR = "zero unjustified or premature automatic resolutions (set by Fahad); otherwise an explicit failed gate"
HISTORY_ONLY = "S5 measured 26 of 41 (63%) in a different world; history only, never a comparison number"

# ---------------------------------------------------------------------------------------------- extras (exploratory)
# Run after the main test, in this fixed order, regardless of results; never pooled (addendum 2). Since the budget was
# lifted they are part of the selection's sealed worst case, not conditional on calls left over: the ablation on every
# eligible E1 identifiable ambiguous case, the stability rerun on STABILITY_MAX of that cell's cases, drawn by seed.
EXTRAS_ORDER = ("cross_shipment_ablation", "stability_rerun")
STABILITY_MAX = 40
# Mechanisms whose discriminating evidence is cross-shipment (amendment 1, J).
CROSS_SHIPMENT_MECHANISMS = ("DEVICE_OUTAGE", "PARTIAL_UPLOAD_LOSS", "FACILITY_BACKLOG", "LATE_LINEHAUL", "MISSORT",
                             "TRAFFIC_DISRUPTION")

# ---------------------------------------------------------------------------------------------- arms and answers
ARMS = ("agent", "notools", "rulecode", "symptom")
MODEL_ARMS = ("agent", "notools")
ABSTAIN = ("INSUFFICIENT_EVIDENCE", "UNKNOWN")

# Answer categories (Fahad's), mutually exclusive, in precedence order. Honest uncertainty is never pooled with a
# confident wrong answer anywhere in the report.
CATEGORIES = (
    "unsafe_or_fabricated",        # a cited record not retrieved / not resolvable / recorded after t; a prohibited
                                   # action; blame or GPS-as-delivery text; truth vocabulary in the output
    "degraded",                    # no valid conclusion (cap hit, provider failure, invalid output): counted wrong
    "correct_supported",           # knowable, acceptable primary, at least one valid discriminating citation
    "correct_unsupported",         # knowable, acceptable primary, no valid discriminating citation
    "honest_uncertainty",          # not knowable at t, and the answer abstains
    "insufficient_when_knowable",  # knowable at t, and the answer abstains: wrong
    "confident_wrong",             # a specific cause that is not acceptable (on knowable or unknowable cases)
)
CORRECT = ("correct_supported", "correct_unsupported", "honest_uncertainty")

# ---------------------------------------------------------------------------------------------- seeds (amendment 1, G)


def eval_seed(freeze_commit: str, k: int) -> int:
    """int(sha256("<commit>:<k>")[:8], 16): E1 is k = 1, E2 is k = 2. <commit> is the full hash of the commit that
    freezes the investigator, tools and reviewer for the evaluation."""
    if k not in (1, 2):
        raise ValueError("k is 1 (E1) or 2 (E2)")
    if len(freeze_commit) < 40:
        raise ValueError("use the full 40-character commit hash, not an abbreviation")
    return int(hashlib.sha256(f"{freeze_commit}:{k}".encode()).hexdigest()[:8], 16)


def selection_seed(freeze_commit: str, world: str) -> int:
    """Seed of the case draw in one world (derived the same way, so nobody chooses it)."""
    return int(hashlib.sha256(f"{freeze_commit}:selection:{world}".encode()).hexdigest()[:8], 16)


# ---------------------------------------------------------------------------------------------- baselines (amendment 1, C)
# B_rulecode: the first code in this fixed order among the monitor's rule codes at opening; no code gives
# INSUFFICIENT_EVIDENCE; its cause set is all its codes. Codes outside the list (the derive rules also emit
# POSSIBLE_MISDELIVERY, which amendment 1 does not list) follow the list in alphabetical order; this placement is
# recorded here and in the README for the next dated amendment.
RULECODE_ORDER = ("CONFLICTING_CUSTODY", "MANIFEST_CONFLICT", "DELIVERY_DISPUTE", "PROOF_INSUFFICIENT", "BARCODE_MISMATCH",
                  "WEIGHT_MISMATCH", "ADDRESS_CONFLICT", "WRONG_GATE", "RECIPIENT_UNAVAILABLE", "UNRECONCILED_CUSTODY",
                  "TRAFFIC_DELAY", "JOURNEY_DELAY", "CUSTODY_GAP", "MISSED_MILESTONE")

# B_symptom: a fixed mapping from the opening symptom name to a cause, committed with the stratum script before any
# evaluation case exists (amendment 1, C and F). Symptom names are operations.store.SYMPTOMS values. Each symptom
# maps to the cause its name describes; DELIVERY_ATTEMPT_FAILED (raised by ADDRESS_CONFLICT, WRONG_GATE and
# RECIPIENT_UNAVAILABLE) maps to RECIPIENT_UNAVAILABLE, the plain reading of "the attempt failed", and
# MILESTONE_LATE (JOURNEY_DELAY and TRAFFIC_DELAY) to JOURNEY_DELAY. The primary is the first opening symptom in
# SYMPTOM_ORDER (the B_rulecode order carried over to symptom names, so MILESTONE_OVERDUE is the last resort, as in
# Stage 0); its cause set is its primary.
SYMPTOM_CAUSE = {
    "CUSTODY_REPORTS_CONFLICT": "CONFLICTING_CUSTODY",
    "MANIFEST_CUSTODY_CONFLICT": "MANIFEST_CONFLICT",
    "RECIPIENT_REPORTED_NOT_RECEIVED": "DELIVERY_DISPUTE",
    "DELIVERY_PROOF_INCOMPLETE": "PROOF_INSUFFICIENT",
    "BARCODE_READ_DIFFERS": "BARCODE_MISMATCH",
    "WEIGHT_READ_DIFFERS": "WEIGHT_MISMATCH",
    "DELIVERY_ATTEMPT_FAILED": "RECIPIENT_UNAVAILABLE",
    "SESSION_END_UNRECONCILED": "UNRECONCILED_CUSTODY",
    "MILESTONE_LATE": "JOURNEY_DELAY",
    "CUSTODY_TRANSFER_UNCONFIRMED": "CUSTODY_GAP",
    "EVIDENCE_MISSING": "INSUFFICIENT_EVIDENCE",
    "MILESTONE_OVERDUE": "MISSED_MILESTONE",
}
SYMPTOM_ORDER = tuple(SYMPTOM_CAUSE)


@dataclass(frozen=True)
class EvalConfig:
    """What a run is sealed to. Filled by `select` on Fahad's machine from the freeze commit and the C_cap given there
    (16 per amendment 3; the default below is only the planning value)."""
    freeze_commit: str = ""
    c_cap: int = C_CAP_PLANNING
    r_cap: int = 0
    # The run's own maximum: the worst case of the selection (worst_case_calls), which `select` fills in when it is
    # None, as the command line leaves it. A number given here is kept as it is (tests). Not an allowance: it is what
    # the run holds in the campaign ledger while it is going, and what its own ledger refuses to pass.
    budget: int | None = None
    worlds: dict = field(default_factory=dict)      # {"E1": {"dataset_id", "export", "database"}, "E2": {...}}
    sampling: str = "round_robin_by_mechanism"      # within a stratum: seeded, balanced over explaining mechanisms
    notes: str = ""
    # Campaign calls kept out of this evaluation at selection (select --reserve N): the run refuses to start if the
    # calls spent plus its budget would go past the ledger's guard less the reserve.
    reserve: int = 0
    # An optional stop line (select --stop-at N; off by default): the run refuses to start if the calls spent plus its
    # budget would take the campaign ledger past N.
    stop_at: int | None = None

    def as_dict(self):
        """The sealed form. A zero reserve and an unset stop line are left out."""
        out = asdict(self)
        if not out["reserve"]:
            del out["reserve"]
        if out["stop_at"] is None:
            del out["stop_at"]
        return out


def canonical_bytes(data: bytes) -> bytes:
    """The bytes a pre-registered file is hashed over: its content with CRLF (and lone CR) line endings as LF. The
    files are written with LF, but a Git checkout that converts line endings (core.autocrlf on Windows) may hand back
    CRLF, and the hash must not depend on that. Canonical JSON never holds a raw line break inside a string, so this
    cannot hide a change of content."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


# ---------------------------------------------------------------------------------------------- the run-readable selection
# selection.json is the only pre-registered file the run step opens before and during the main test. It may carry
# these names and no others: every other fact about a case (its stratum, whether it is in the main test, which extras
# it belongs to) is derived from truth and lives in the scorer-side files (selection_scorer.json, extras.json).
# The case names are exactly the ones selection.select writes (tested): a case's id and snapshot time exist only once
# the run has opened it, so they are the backend's to give (CaseRef) and have no place in a pre-registered file.
RUN_SELECTION_KEYS = ("schema", "sealed_config_hash", "config", "n_main", "cases", "unit")
RUN_CASE_KEYS = ("order", "key", "world", "shipment_id", "expected_opened_at")
TRUTH_DERIVED_KEYS = ("stratum", "stratum_rule", "main_test", "extras", "cross_shipment_ablation", "stability_rerun", "allocation",
                      "identifiable", "acceptable", "mechanism_types", "pairs", "census")


def runtime_selection_problem(document):
    """None when the document is a run-readable selection; otherwise what makes it unsafe for the run step to read."""
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        return "not a selection document"
    extra = sorted(set(document) - set(RUN_SELECTION_KEYS))
    if extra:
        return f"fields the run step must not read: {extra}"
    for row in document["cases"]:
        if not isinstance(row, dict):
            return "a case row is not an object"
        extra = sorted(set(row) - set(RUN_CASE_KEYS))
        if extra:
            return f"a case row carries fields the run step must not read: {extra}"

    def names(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                yield str(key)
                yield from names(inner)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                yield from names(inner)
    derived = sorted(set(names(document)) & set(TRUTH_DERIVED_KEYS))
    if derived:
        return f"truth-derived fields: {derived}"
    return None


def sealed_hash(config: EvalConfig, notools_max_calls=NOTOOLS_MAX_CALLS) -> str:
    """Hash of the configuration and every frozen table above; a run whose hash differs is not the sealed run.
    notools_max_calls: the no-tools arm's calls per case that the hash seals (this code's, unless given)."""
    payload = {"config": config.as_dict(), "allocation": sorted((list(k), v) for k, v in ALLOCATION_AT_PLANNING.items()),
               "shrink": SHRINK_ORDER, "pass_bars": PASS_BARS, "rulecode_order": RULECODE_ORDER, "symptom_cause": SYMPTOM_CAUSE,
               "symptom_order": SYMPTOM_ORDER, "categories": CATEGORIES, "min_support": STRATUM_MIN_SUPPORT,
               "max_hypotheses": MAX_SUPPORTED_HYPOTHESES, "notools_max_calls": notools_max_calls,
               "cross_shipment": CROSS_SHIPMENT_MECHANISMS, "extras": EXTRAS_ORDER, "stability_max": STABILITY_MAX}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode()).hexdigest()


def sealed_notools_max_calls(sealed, config: EvalConfig):
    """The no-tools arm's calls per case that a sealed hash holds for this configuration: this code's (3), or the 2 of
    a selection sealed before the arm's correction. None when the hash is neither: the configuration is not the
    sealed one."""
    for calls in (NOTOOLS_MAX_CALLS, NOTOOLS_MAX_CALLS_BEFORE_CORRECTION):
        if sealed == sealed_hash(config, calls):
            return calls
    return None
