"""Scorer side only: reading truth rows and deciding what was knowable at an instant.

Only the pre-run selection step and the post-run scorer import this module. The run step (runner.py, arms.py)
never does, and a test checks that statically. Truth rows are the `world-truth-3` rows that `world.export`
writes outside the repository (default C:\\Projects\\suhail-eval-truth\\...); this module refuses a truth path
inside the repository unless it is the committed harness fixture (dataset ids starting with FIXTURE-).

What is knowable at t (amendment 1, A) follows world.truth: a mechanism is identifiable at t when every item of at
least one group of its discrimination spec is satisfied, given `ingested`, the evidence ids recorded at or before t.
The scorer uses the run's own ingestion log (read from the database after the run); the pre-run selection, before
any run exists, uses the generator-side estimate (`knowable_at_estimate`), as the stratum script must be computed
before the agent runs. The two can differ; the report counts the cases whose knowability moved.

Acceptable causes at t are the acceptable codes of the identifiable mechanisms that explain the case's opening
(all actionable mechanisms when none explains it), exactly as the world's tell test scores a prediction.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

from world.mechanisms import CATALOGUE, MECHANISM_TYPES, RULE_CODES
from world.truth import discriminated

FIXTURE_PREFIX = "FIXTURE-"
CANARY_PATTERN = re.compile(r"CNRY[0-9A-F]{24}")
MECHANISM_ID_PATTERN = re.compile(r"W1M-\d{5}")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_truth(path, *, dataset_id=None):
    """{shipment_id: truth row} from a truth.jsonl. Refuses repository paths except the committed fixture."""
    path = Path(path)
    rows = read_jsonl(path)
    if _inside_repo(path) and not all(str(r.get("dataset_id", dataset_id or "")).startswith(FIXTURE_PREFIX) for r in rows):
        raise ValueError(f"{path} is inside the repository; real truth rows live outside it (only FIXTURE- data may be here)")
    canaries = {r.get("canary") for r in rows}
    if len(canaries) != 1 or not all(isinstance(c, str) and CANARY_PATTERN.fullmatch(c) for c in canaries):
        raise ValueError("every truth row must carry the same world canary token (CNRY + 24 hex characters)")
    return {r["shipment_id"]: r for r in rows}


def load_replay_rows(path):
    """{shipment_id: monitor replay row} (monitor_replay_rows.jsonl beside truth.jsonl)."""
    return {r["shipment_id"]: r for r in read_jsonl(path)}


def canary_of(truth) -> str:
    return next(iter(truth.values()))["canary"]


def truth_vocabulary(truth):
    """What must never appear in anything the runtime can see: the canary, every mechanism id in the truth rows, and
    every mechanism name that is not also a catalogue cause code or rule code (WRONG_GATE and RECIPIENT_UNAVAILABLE
    are legitimate operational codes and stay allowed, as in world.export check)."""
    allowed = {c for entry in CATALOGUE.values() for c in (entry[0], *entry[1]) if c} | {c for codes in RULE_CODES.values() for c in codes}
    names = sorted(set(MECHANISM_TYPES) - allowed)
    ids = sorted({m["mechanism_id"] for r in truth.values() for m in r.get("mechanisms", [])}
                 | {e["mechanism_id"] for r in truth.values() for e in r.get("exposures", [])})
    return {"canary": canary_of(truth), "mechanism_ids": ids, "mechanism_names": names}


# ------------------------------------------------------------------------------------------- knowability at t
@dataclass
class TruthAt:
    """What the truth says about one case at one instant (scorer side only)."""
    healthy: bool
    identifiable: bool
    acceptable: frozenset = frozenset()          # acceptable cause codes of the identifiable explaining mechanisms
    knowable_causes: frozenset = frozenset()     # their primary cause codes (for cause-set recall)
    discriminating: dict = field(default_factory=dict)   # cause code -> record ids that discriminate a mechanism accepting it
    bearing: dict = field(default_factory=dict)          # cause code -> record ids shaped by or cited for a mechanism accepting it
    mechanism_types: tuple = ()                  # explaining mechanism types (for per-mechanism reporting and pairs)


def explaining_mechanisms(row, opening_codes=None):
    """Actionable mechanisms that explain the opening (all actionable ones when none explains it)."""
    actionable = [m for m in row.get("mechanisms", []) if m.get("resolution") != "NONE" and m.get("cause_code")]
    if opening_codes is None:
        explaining = [m for m in actionable if m.get("explains_opening")]
    else:
        explaining = [m for m in actionable if set(RULE_CODES.get(m["type"], ())) & set(opening_codes)]
    return explaining or actionable


def _spec_records(m):
    return {i["record"] for g in m.get("discrimination", {}).get("any_of", []) for i in g.get("all_of", []) if "record" in i}


def truth_at(row, t, ingested=None, *, opening_codes=None) -> TruthAt:
    """Knowability at instant t. `ingested`: evidence ids recorded at or before t from the run's ingestion log; None
    uses the generator-side estimate (pre-run selection only)."""
    from dataset_v2.contracts import instant
    when = instant(t) if isinstance(t, str) else t
    if row.get("healthy"):
        return TruthAt(healthy=True, identifiable=False)
    explaining = explaining_mechanisms(row, opening_codes)
    if ingested is None:
        known = [m for m in explaining if m.get("knowable_at_estimate") and instant(m["knowable_at_estimate"]) <= when]
    else:
        known = [m for m in explaining if discriminated(m["discrimination"], when, ingested)]
    discriminating, bearing = {}, {}
    for m in explaining:
        for cause in m.get("acceptable_causes") or []:
            discriminating.setdefault(cause, set()).update(_spec_records(m))
            bearing.setdefault(cause, set()).update(_spec_records(m) | set(m.get("evidence_ids") or []) | set(m.get("shared_evidence_ids") or []))
    return TruthAt(healthy=False, identifiable=bool(known),
                   acceptable=frozenset(c for m in known for c in m.get("acceptable_causes") or []),
                   knowable_causes=frozenset(m["cause_code"] for m in known),
                   discriminating={k: frozenset(v) for k, v in discriminating.items()},
                   bearing={k: frozenset(v) for k, v in bearing.items()},
                   mechanism_types=tuple(sorted({m["type"] for m in explaining})))


def eventual_acceptable(row):
    """Secondary truth (the full story), never the headline: the explaining mechanisms' acceptable causes."""
    return frozenset(c for m in explaining_mechanisms(row) for c in m.get("acceptable_causes") or [])
