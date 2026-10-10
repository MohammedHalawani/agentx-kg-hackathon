"""Shared fixtures: the committed fixture worlds, a selection made from them, and test-only fake arms.

The fake agent below reads the fixture's truth to behave like a known investigator (some answers right with
discriminating citations, some wrong, some abstaining). That is allowed ONLY in tests: it stands in for the real
pipeline, which never sees truth. Nothing under stage3_eval outside tests/ does this."""
import json
from pathlib import Path

import pytest

from stage3_eval.arms import AgentArm, NoToolsArm, RuleCodeArm, SymptomArm
from stage3_eval.design import STAGE3_STOP_AT, EvalConfig
from stage3_eval.fixtures.fakes import world_dir
from stage3_eval.records import ArmResult
from stage3_eval.truth_io import load_replay_rows, load_truth

COMMIT = "a" * 40


def fixture_worlds():
    return {w: (load_truth(world_dir(w) / "truth" / "truth.jsonl"), load_replay_rows(world_dir(w) / "truth" / "monitor_replay_rows.jsonl"))
            for w in ("E1", "E2")}


def make_config(**over):
    """The fixture configuration: sealed at the whole Stage 3 line (3,600), the most a run may hold from an empty ledger."""
    base = dict(freeze_commit=COMMIT, budget=STAGE3_STOP_AT, worlds={w: {"dataset_id": f"FIXTURE-{w}"} for w in ("E1", "E2")})
    base.update(over)
    return EvalConfig(**base)


@pytest.fixture
def worlds():
    return fixture_worlds()


@pytest.fixture
def selected(tmp_path, worlds):
    from stage3_eval.selection import select
    config = make_config()
    summary = select(worlds, config, tmp_path / "sel")
    return config, tmp_path / "sel", summary


class FakeAgent:
    """Test-only stand-in for the real pipeline. Behaviour by shipment number (deterministic):
    n % 5 == 0 -> wrong specific cause (HUB_DELAY or CUSTODY_GAP); n % 7 == 0 -> abstains (INSUFFICIENT_EVIDENCE);
    otherwise -> the first acceptable cause, citing the discriminating record it retrieved. Unidentifiable cases are
    answered INSUFFICIENT_EVIDENCE unless n % 5 == 0."""

    def __init__(self, truth_by_world, calls=9, cap_hit_every=0):
        self.truth, self.calls, self.cap_hit_every, self.seen = truth_by_world, calls, cap_hit_every, []

    def __call__(self, case):
        self.seen.append(case.key)
        row = self.truth[case.world][case.shipment_id]
        n = int(case.shipment_id.rsplit("-", 1)[1])
        m = row["mechanisms"][0]
        disc = m["discrimination"]["any_of"][0]["all_of"][0]["record"]
        retrieved = [disc, *case.opening_evidence_ids]
        identifiable = m["knowable_at_estimate"] <= case.as_of
        if n % 5 == 0:
            primary = "HUB_DELAY" if "HUB_DELAY" not in m["acceptable_causes"] else "CUSTODY_GAP"
            cites = list(case.opening_evidence_ids)
        elif n % 7 == 0 or not identifiable:
            primary, cites = "INSUFFICIENT_EVIDENCE", []
        else:
            primary, cites = m["acceptable_causes"][0], [disc]
        status = "uncertain" if primary == "INSUFFICIENT_EVIDENCE" else "supported"
        return ArmResult(case_key=case.key, arm="agent", shipment_id=case.shipment_id, case_id=case.case_id, as_of=case.as_of,
                         primary_cause=primary, confidence="medium",
                         hypotheses=[{"cause": primary, "status": status, "supporting_evidence_ids": cites, "contradicting_evidence_ids": []}],
                         recommended_action="REQUEST_HUB_CHECK", retrieved_ids=retrieved,
                         steps=[{"tool": "scans", "args": {}, "evidence_ids": retrieved}], texts=["The record shows a delay."],
                         review_verdict="ACCEPT", calls_used=self.calls, tokens=4600 * self.calls, wall_seconds=12.5, tool_seconds=[0.05, 0.08])


def notools_turn_factory(answer="MISSED_MILESTONE"):
    calls = []

    def turn(messages):
        calls.append(messages)
        return {"action": "conclude", "hypotheses": [{"cause": answer, "status": "supported", "supporting_evidence_ids": [],
                                                      "contradicting_evidence_ids": [], "assessment": "From the symptoms only."}],
                "primary_cause": answer, "confidence": "low", "missing_evidence": ["no records were available"],
                "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": "Symptoms only."}
    return turn, calls


def build_arms(config, agent, turn):
    return {"agent": AgentArm(agent, config.c_cap, config.r_cap), "notools": NoToolsArm(turn=turn), "rulecode": RuleCodeArm(), "symptom": SymptomArm()}


def read_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def write_campaign_ledger(path, spent=173, cap=4000):
    """A campaign ledger file of the test's own (the committed one is never written by a test)."""
    entries = [{"run": "earlier runs", "started_at": "2026-10-10T00:00:00+00:00", "finished_at": "2026-10-10T01:00:00+00:00",
                "commit": "c" * 40, "calls": spent, "tokens": 0, "note": "test", "reserved": None}] if spent else []
    Path(path).write_text(json.dumps({"schema": "model-call-ledger-1", "campaign": "test", "cap": cap, "entries": entries}), encoding="utf-8")
    return Path(path)


@pytest.fixture(autouse=True)
def campaign_ledger_file(tmp_path_factory, monkeypatch):
    """Every harness test that reaches the campaign ledger gets a temporary one with 173 calls already spent."""
    path = write_campaign_ledger(tmp_path_factory.mktemp("campaign") / "model_call_ledger.json")
    monkeypatch.setenv("SUHAIL_CALL_LEDGER", str(path))
    return path
