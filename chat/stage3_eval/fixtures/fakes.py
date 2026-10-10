"""In-memory stand-ins for the backend seams (interfaces.py), backed by the committed fixture's runtime files.
They read runtime/ only (never truth/), so the dry run exercises the run step exactly as the real one is wired."""
import json
from pathlib import Path

from stage3_eval.arms import CaseRef

FIXTURE_ROOT = Path(__file__).resolve().parent


def world_dir(world):
    return FIXTURE_ROOT / f"world_{world.lower()}"


class FixtureCaseSource:
    def __init__(self, worlds=("E1", "E2")):
        self.cases = {}
        for world in worlds:
            for c in json.loads((world_dir(world) / "runtime" / "cases.json").read_text(encoding="utf-8")):
                self.cases[(world, c["shipment_id"])] = c

    def case_ref(self, world, shipment_id):
        c = self.cases.get((world, shipment_id))
        if c is None:
            return None
        return CaseRef(key=f"{world}:{shipment_id}", world=world, shipment_id=shipment_id, case_id=c["case_id"], as_of=c["as_of"],
                       symptoms=tuple(c["symptoms"]), rule_codes=tuple(c["rule_codes"]), opening_evidence_ids=tuple(c["opening_evidence_ids"]))


class FixtureDatabase:
    """The ingestion log and the citation resolver of the fixture's fake database."""

    def __init__(self, worlds=("E1", "E2")):
        self.records = {w: json.loads((world_dir(w) / "runtime" / "records.json").read_text(encoding="utf-8")) for w in worlds}

    def ingested(self, world, t):
        from dataset_v2.contracts import instant
        when = instant(t)
        return {i for i, at in self.records[world].items() if instant(at) <= when}

    def recorded_at(self, world, ids):
        return {i: self.records[world][i] for i in ids if i in self.records[world]}


class FixtureCapture:
    """Captures a clean text for every required surface (the fixture's runtime holds no truth)."""

    def capture_case(self, case, results):
        return {"tools": [{"case": case.case_id, "steps": results["agent"].steps if results.get("agent") else []}],
                "api": [{"case_id": case.case_id, "symptoms": list(case.symptoms)}],
                "receipts": [{"case_id": case.case_id, "executions": results["agent"].executions if results.get("agent") else []}]}

    def capture_run(self):
        return {"graph": [{"note": "fixture database property dump", "cases": len(FixtureCaseSource().cases)}], "logs": ["fixture run log"]}


def refuse(*_args, **_kwargs):
    raise AssertionError("a dry run must not call the model or the backend case runner")
