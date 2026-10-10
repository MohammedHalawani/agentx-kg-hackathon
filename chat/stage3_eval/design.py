"""The frozen Stage 3 design, as constants the harness enforces.

Source: docs/plans/2026-10-10_stage3_evaluation_design.md on fhd, frozen at b1d331f, with amendment 1 (001bcbf),
amendment 2 (ac6f857, Fahad's 4,000-call cap) and the addendum to amendment 2 (7af0d5c). Where they differ, the
later text wins. Nothing here is computed from results: every bar, size and order is fixed before any evaluation
case exists. Changing a value here after the first evaluation run changes the sealed configuration hash, and the
run validity check then reports the run as not matching its sealed configuration (amendment 1, H).

The two baseline tables at the bottom (B_rulecode order and the B_symptom table) are the ones amendment 1, C and F
ask to be committed with the stratum script before any evaluation case exists.
"""
from dataclasses import asdict, dataclass, field
import hashlib
import json

DESIGN_DOCUMENT = "docs/plans/2026-10-10_stage3_evaluation_design.md"
DESIGN_COMMITS = {"frozen": "b1d331f", "amendment_1": "001bcbf", "amendment_2": "ac6f857", "addendum_2": "7af0d5c"}

# ---------------------------------------------------------------------------------------------- budget (amendment 2)
CALL_BUDGET = 4000            # Fahad's hard cap for the blind evaluation on E1 and E2, every arm and retry included.
C_CAP_PLANNING = 12           # Planning value; the real C_cap is the 95th percentile of correct development runs.
NOTOOLS_MAX_CALLS = 2         # One call plus one retry on invalid output (addendum 2, item 2).


def n_main(c_cap=C_CAP_PLANNING, r_cap=0, budget=CALL_BUDGET):
    """N_main = floor(budget / (C_cap + R_cap + 2)) (amendment 2 and its addendum, item 1)."""
    if c_cap < 1 or r_cap < 0:
        raise ValueError("C_cap must be at least 1 and R_cap at least 0")
    return budget // (c_cap + r_cap + NOTOOLS_MAX_CALLS)


def worst_case_per_case(c_cap=C_CAP_PLANNING, r_cap=0):
    """Calls a main-test case may spend at most: the agent arm under its one per-case counter, plus B_notools."""
    return c_cap + r_cap + NOTOOLS_MAX_CALLS


# ---------------------------------------------------------------------------------------------- strata and worlds
STRATA = ("identifiable_ambiguous", "determined", "unidentifiable")
WORLDS = ("E1", "E2")
# Amendment 2 allocation at C_cap = 12 (N_main = 285).
ALLOCATION_AT_PLANNING = {
    ("E1", "identifiable_ambiguous"): 160,
    ("E2", "identifiable_ambiguous"): 60,
    ("E1", "determined"): 30, ("E2", "determined"): 10,
    ("E1", "unidentifiable"): 20, ("E2", "unidentifiable"): 5,
}
# If N_main < 285, cases are removed in this order, each step down to its floor (amendment 2, sizing rule).
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
# Run only if calls remain after the main test, in this fixed order, regardless of results; never pooled (addendum 2).
EXTRAS_ORDER = ("cross_shipment_ablation", "stability_rerun")
STABILITY_MAX = 20
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
    """What a run is sealed to. Filled on Fahad's machine once C_cap and the freeze commit are known."""
    freeze_commit: str = ""
    c_cap: int = C_CAP_PLANNING
    r_cap: int = 0
    budget: int = CALL_BUDGET
    worlds: dict = field(default_factory=dict)      # {"E1": {"dataset_id", "export", "database"}, "E2": {...}}
    sampling: str = "round_robin_by_mechanism"      # within a stratum: seeded, balanced over explaining mechanisms
    notes: str = ""

    def as_dict(self):
        return asdict(self)


def sealed_hash(config: EvalConfig) -> str:
    """Hash of the configuration and every frozen table above; a run whose hash differs is not the sealed run."""
    payload = {"config": config.as_dict(), "allocation": sorted((list(k), v) for k, v in ALLOCATION_AT_PLANNING.items()),
               "shrink": SHRINK_ORDER, "pass_bars": PASS_BARS, "rulecode_order": RULECODE_ORDER, "symptom_cause": SYMPTOM_CAUSE,
               "symptom_order": SYMPTOM_ORDER, "categories": CATEGORIES, "min_support": STRATUM_MIN_SUPPORT,
               "max_hypotheses": MAX_SUPPORTED_HYPOTHESES, "notools_max_calls": NOTOOLS_MAX_CALLS,
               "cross_shipment": CROSS_SHIPMENT_MECHANISMS, "extras": EXTRAS_ORDER, "stability_max": STABILITY_MAX}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode()).hexdigest()
