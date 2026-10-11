"""Writes the committed harness fixture: two tiny synthetic "worlds" (FIXTURE-E1, FIXTURE-E2) in the shapes the
harness reads. It is NOT a world-1 export and was not produced by the generator; it is hand-specified, labelled
FIXTURE, and exists only so the harness can be tested and dry-run with no database, no model and no real truth.

Per world:
  truth/truth.jsonl                  world-truth-3 rows (only the fields the harness reads), canary in every row
  truth/monitor_replay_rows.jsonl    the monitor replica's opening per live shipment
  runtime/cases.json                 what the runtime shows: case id, snapshot, symptoms, rule codes, opening evidence
  runtime/records.json               evidence id -> recorded_at (the fake database's ingestion log and resolver)

Deterministic: python -m stage3_eval.fixtures.make_fixture rewrites identical files.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
START = datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc)

# (mechanism type, cause code, acceptable causes, opening symptoms, opening rule codes, cause codes sharing the opening)
TEMPLATES = {
    "outage": ("DEVICE_OUTAGE", "DELAYED_SYNC", ["DELAYED_SYNC"], ["CUSTODY_TRANSFER_UNCONFIRMED"], ["CUSTODY_GAP"], ["CUSTODY_GAP"]),
    "skip": ("SCAN_SKIPPED_AT_RECEIPT", "CUSTODY_GAP", ["CUSTODY_GAP", "MISSED_MILESTONE"], ["CUSTODY_TRANSFER_UNCONFIRMED"], ["CUSTODY_GAP"], ["DELAYED_SYNC"]),
    "backlog": ("FACILITY_BACKLOG", "HUB_DELAY", ["HUB_DELAY", "JOURNEY_DELAY", "MISSED_MILESTONE"], ["MILESTONE_OVERDUE"], ["MISSED_MILESTONE"], ["ADDRESS_CONFLICT", "ROUTE_DELAY"]),
    "linehaul": ("LATE_LINEHAUL", "ROUTE_DELAY", ["ROUTE_DELAY", "JOURNEY_DELAY", "MISSED_MILESTONE"], ["MILESTONE_OVERDUE"], ["MISSED_MILESTONE"], ["ADDRESS_CONFLICT", "HUB_DELAY"]),
    "address": ("WRONG_ADDRESS", "ADDRESS_CONFLICT", ["ADDRESS_CONFLICT"], ["MILESTONE_OVERDUE"], ["MISSED_MILESTONE"], ["HUB_DELAY", "ROUTE_DELAY"]),
    "gate": ("WRONG_GATE", "WRONG_GATE", ["WRONG_GATE"], ["DELIVERY_ATTEMPT_FAILED"], ["WRONG_GATE", "RECIPIENT_UNAVAILABLE"], ["RECIPIENT_UNAVAILABLE"]),
    "routine": ("ROUTINE_FAILED_ATTEMPT", "RECIPIENT_UNAVAILABLE", ["RECIPIENT_UNAVAILABLE", "MISSED_MILESTONE"], ["DELIVERY_ATTEMPT_FAILED"], ["RECIPIENT_UNAVAILABLE"], ["WRONG_GATE"]),
    "scale": ("SCALE_DRIFT", "WEIGHT_MISMATCH", ["WEIGHT_MISMATCH"], ["WEIGHT_READ_DIFFERS"], ["WEIGHT_MISMATCH"], []),
    "declared": ("DECLARED_WEIGHT_WRONG", "WEIGHT_MISMATCH", ["WEIGHT_MISMATCH"], ["WEIGHT_READ_DIFFERS"], ["WEIGHT_MISMATCH"], []),
    "label": ("LABEL_MISREAD", "BARCODE_MISMATCH", ["BARCODE_MISMATCH"], ["BARCODE_READ_DIFFERS"], ["BARCODE_MISMATCH"], []),
}
# World plan: (template, identifiable at opening?) repeated; plus healthy shipments (two opened by ordinary variation).
PLANS = {
    "E1": [("outage", True)] * 6 + [("skip", True)] * 6 + [("backlog", True)] * 5 + [("linehaul", True)] * 4 + [("address", True)] * 3
          + [("gate", True)] * 5 + [("routine", True)] * 5 + [("scale", True)] * 4 + [("declared", True)] * 2 + [("label", True)] * 5
          + [("outage", False)] * 2 + [("backlog", False)] * 2 + [("gate", False)] * 1,
    "E2": [("outage", True)] * 3 + [("skip", True)] * 3 + [("backlog", True)] * 2 + [("address", True)] * 2 + [("gate", True)] * 2
          + [("routine", True)] * 2 + [("scale", True)] * 2 + [("label", True)] * 2 + [("skip", False)] * 2,
}
HEALTHY = {"E1": 4, "E2": 2}


def iso(t):
    return t.isoformat()


def canary(world):
    return "CNRY" + hashlib.sha256(f"stage3-fixture|{world}".encode()).hexdigest()[:24].upper()


def build(world):
    truth, replay, cases, records = [], [], [], {}
    mech_n = {"E1": 90000, "E2": 95000}[world]
    plan = PLANS[world]
    for i, (name, identifiable) in enumerate(plan, start=1):
        sid = f"FXT-SHP-{world}-{i:04d}"
        mtype, cause, acceptable, symptoms, codes, shares = TEMPLATES[name]
        opened = START + timedelta(hours=3 * i)
        disc, link, opening_ev = f"FXT-EV-{world}-{i:04d}-D", f"FXT-EV-{world}-{i:04d}-L", f"FXT-EV-{world}-{i:04d}-O"
        knowable = opened - timedelta(minutes=30) if identifiable else opened + timedelta(hours=8)
        records[opening_ev] = iso(opened - timedelta(hours=1))
        records[link] = iso(opened - timedelta(hours=2))
        records[disc] = iso(knowable)
        mech_n += 1
        mechanism = {"mechanism_id": f"W1M-{mech_n:05d}", "type": mtype, "subtype": None, "origin": "scheduled", "cause_code": cause,
                     "acceptable_causes": acceptable, "resolution": "AUTO", "action": None, "fault": True, "explains_opening": True,
                     "discrimination": {"opening_symptoms": symptoms, "shares_opening_with": shares, "alternative_mechanisms": [],
                                        "any_of": [{"all_of": [{"record": disc}, {"record": link}]}]},
                     "knowable_at_estimate": iso(knowable), "evidence_ids": [disc], "shared_evidence_ids": []}
        truth.append({"truth_schema": "world-truth-3", "dataset_id": f"FIXTURE-{world}", "canary": canary(world), "shipment_id": sid,
                      "split": "development", "healthy": False, "mechanisms": [mechanism], "exposures": [],
                      "first_opening": {"at": iso(opened), "codes": codes, "symptoms": symptoms}})
        replay.append({"shipment_id": sid, "healthy": False, "opened_at": iso(opened), "opening_symptoms": symptoms, "opening_codes": codes})
        cases.append({"shipment_id": sid, "case_id": f"FXT-CASE-{world}-{i:04d}", "as_of": iso(opened + timedelta(minutes=5)),
                      "symptoms": symptoms, "rule_codes": codes, "opening_evidence_ids": [opening_ev]})
    for j in range(HEALTHY[world]):
        sid = f"FXT-SHP-{world}-H{j:03d}"
        opened = START + timedelta(hours=5 * j + 1) if j < 2 else None
        truth.append({"truth_schema": "world-truth-3", "dataset_id": f"FIXTURE-{world}", "canary": canary(world), "shipment_id": sid,
                      "split": "development", "healthy": True, "mechanisms": [], "exposures": [], "first_opening": None})
        replay.append({"shipment_id": sid, "healthy": True, "opened_at": iso(opened) if opened else None,
                       "opening_symptoms": ["MILESTONE_OVERDUE"] if opened else [], "opening_codes": ["MISSED_MILESTONE"] if opened else []})
    return truth, replay, cases, records


def write(root=HERE):
    for world in PLANS:
        truth, replay, cases, records = build(world)
        base = Path(root) / f"world_{world.lower()}"
        (base / "truth").mkdir(parents=True, exist_ok=True)
        (base / "runtime").mkdir(parents=True, exist_ok=True)
        (base / "truth" / "truth.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in truth), encoding="utf-8", newline="\n")
        (base / "truth" / "monitor_replay_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in replay), encoding="utf-8", newline="\n")
        (base / "runtime" / "cases.json").write_text(json.dumps(cases, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        (base / "runtime" / "records.json").write_text(json.dumps(records, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write()
