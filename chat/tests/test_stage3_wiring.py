"""chat/scripts/stage3_wiring.py: the Stage 3 harness wired to the store, the investigator and the world databases.

No model call anywhere. Without a database: a fake store behind the wiring's seams (the case source, run_case, the
capture, the scorer seams), the real investigation graph over the in-memory world with a scripted model (the Stage 2
run record read through records.FIELDS, the as-of extras), and the whole harness (select, dry run, run, score, report)
over the committed harness fixture with a fake world.

Opt-in, against local Neo4j (SUHAIL_NEO4J_TESTS=1, scratch database from SUHAIL_TEST_DATABASE): the fixture mechanism
world is imported into the scratch database and the same sequence runs through the real store, monitor, tools and
read model with a scripted model: select -> dry run -> run -> score -> report.
"""
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from dataset_v2.contracts import instant
from scripts import stage3_wiring as wiring
from stage3_eval.arms import CaseRef
from stage3_eval.design import EvalConfig
from stage3_eval.records import from_ops_run
from stage3_eval.runner import run
from tests.test_stage2_pilot import PlanAgents, SCRATCH, TEST_DATABASE, build_world_database

START = "2026-09-14T06:00:00+00:00"
NEO4J_TEST_HOURS = int(os.environ.get("SUHAIL_STAGE3_TEST_HOURS", "48"))


def stage2_analysis(snapshot, *, primary="INSUFFICIENT_EVIDENCE", calls=7, cited=(), retrieved=(), cap_reached=False, degraded=False):
    """A run record in the shape docs/api/investigation-run.md describes (the fields the harness reads)."""
    hypotheses = [] if degraded else [{"cause": primary, "status": "uncertain" if primary == "INSUFFICIENT_EVIDENCE" else "supported",
                                       "supporting_evidence_ids": list(cited), "contradicting_evidence_ids": [], "assessment": "As recorded."}]
    budget = {"model_call_cap": 12, "model_calls_used": calls, "model_calls_by_role": {"investigator": calls - 1, "reviewer": 1},
              "cap_reached": cap_reached, "calls_refused_by_cap": int(cap_reached)}
    investigation = {"mode": "model_call_cap" if degraded else "gpt-oss", "degraded": degraded, "primary_cause": None if degraded else primary,
                     "confidence": "low", "hypotheses": hypotheses, "missing_evidence": ["the deciding record"], "recommended_action":
                     "REQUEST_ADDITIONAL_EVIDENCE", "summary": "Nothing decides it.", "retrieved_evidence_ids": sorted(retrieved),
                     "steps": [{"round": 0, "tool": "shipment_overview", "args": {}, "evidence_ids": sorted(retrieved), "computed_ids": []}],
                     "validation_error": "model-call cap reached" if degraded else None, "model_calls": budget}
    return {"mode": "gpt_oss_agents", "investigation": investigation,
            "review": {"verdict": "human_review", "model_verdict": "ACCEPT", "reason_code": "X", "feedback": ""},
            "trace": [{"iteration": 0, "review": {"verdict": "human_review"}}], "proposal": None, "checks": {},
            "authority": {"risk_class": "HUMAN_REVIEW", "rule_id": "AUTH-26", "reason": "insufficient evidence"},
            "degraded": [{"role": "investigator", "error": "cap", "kind": "model_call_cap"}] if degraded else [],
            "investigation_log": {"snapshot_as_of": snapshot, **budget, "disabled_tools": [], "rounds": [{"round": 0}]},
            "pipeline_events": [{"stage": "retrieve", "evidence_as_of": snapshot}]}


class FakeStore:
    """The store calls the wiring makes, over an in-memory ledger. Cases open at fixed hours; nothing else is real."""

    def __init__(self, openings, *, start=START, end_hours=400, session_id="DEMO-SESSION-1", calls=7):
        self.openings = dict(openings)       # shipment id -> {"at": iso, "symptoms": [...], "codes": [...], "evidence": [...]}
        self.now, self.end = instant(start), instant(start) + timedelta(hours=end_hours)
        self.session_id, self.calls = session_id, calls
        self.ledger = {kind: [] for kind in wiring.LEDGER_KINDS}
        self.pending, self.processed, self.ticks, self.executed, self.outcome_steps = [], [], 0, 0, 0
        self.worker_state, self.model_call_cap, self.disabled_tools = "paused", None, ("left", "over")
        self.dataset_id, self.config, self.agents, self.resets = "DEMO-SUHAIL-WORLD-FAKE", None, None, 0
        self.event_count, self.monitor_checked = 0, 0
        self.unprocessable = set()

    def status(self):
        return {"as_of": self.now.isoformat(), "worker": {"state": self.worker_state},
                "session": {"session_id": self.session_id, "monitor_pending": len(self.pending), "monitor_checked": self.monitor_checked},
                "simulator": {"event_count": self.event_count, "end_at": self.end.isoformat()}, "execution": {"adapter": "none"}}

    def control(self, component, action):
        self.worker_state = "paused" if action == "pause" else "running"

    def tick(self, seconds=1, *, manual=False, speed=None):
        assert manual and seconds == 3600
        self.ticks += 1
        self.now = min(self.now + timedelta(seconds=seconds), self.end)
        self.event_count += 1
        self.pending = [sid for sid, o in self.openings.items() if instant(o["at"]) <= self.now
                        and not any(c["shipment_id"] == sid for c in self.ledger["OpsCase"])]
        return {"events_replayed": 3, "as_of": self.now.isoformat(), "rejected": 0}

    def monitor_step(self, limit=5):
        batch, self.pending = self.pending[:limit], self.pending[limit:]
        opened = []
        for sid in batch:
            case_id = f"DEMO-OPS-CASE-{sid[-6:]}"
            when = self.now.isoformat()
            self.ledger["OpsCase"].append({"entity_id": case_id, "shipment_id": sid, "session_id": self.session_id, "opened_at": when,
                                           "recorded_at": when, "workflow_state": "OPEN", "symptom_codes": list(self.openings[sid]["symptoms"])})
            self.ledger["OpsAudit"].append({"entity_id": "A-" + case_id, "case_id": case_id, "event_type": "CASE_OPENED", "recorded_at": when,
                                            "result": "Monitor symptoms: " + ", ".join(self.openings[sid]["symptoms"])})
            opened.append(case_id)
        self.monitor_checked += len(batch)
        return {"checked": len(batch), "opened": opened}

    def outcome_step(self, limit=3):
        self.outcome_steps += 1
        return []

    def process_one(self, case_id=None, *, manual=False):
        assert case_id is not None and manual, "the harness investigates a named case only"
        self.processed.append(case_id)
        case = next(c for c in self.ledger["OpsCase"] if c["entity_id"] == case_id)
        if case["shipment_id"] in self.unprocessable:
            return {"processed": False, "reason": "snapshot_changed"}
        when = self.now.isoformat()
        opening = self.openings[case["shipment_id"]]
        analysis = stage2_analysis(when, calls=self.calls, cited=opening["evidence"][:1], retrieved=opening["evidence"])
        self.ledger["OpsRun"].append({"entity_id": "RUN-" + case_id, "case_id": case_id, "recorded_at": when, "result_json": json.dumps(analysis)})
        self.ledger["OpsExecution"].append({"entity_id": "EXE-" + case_id, "case_id": case_id, "recorded_at": when, "action_type":
                                            "REQUEST_ADDITIONAL_EVIDENCE", "authority": "AUTO_POLICY", "status": "AUTHORIZED",
                                            "adapter_result_json": None})
        case["workflow_state"] = "HUMAN_REVIEW"
        return {"processed": True, "case_id": case_id, "run_id": "RUN-" + case_id}

    def execute_step(self, limit=5):
        self.executed += 1
        for execution in self.ledger["OpsExecution"]:
            if execution["status"] == "AUTHORIZED":
                execution.update(status="NOT_ACKNOWLEDGED", adapter_result_json=json.dumps({"acknowledged": False, "adapter": "none"}))
        return []

    def reset_session(self, actor, confirmation=None):
        self.resets += 1
        self.now, self.event_count, self.monitor_checked, self.session_id = instant(START), 0, 0, f"DEMO-SESSION-{self.resets + 1}"
        self.ledger = {kind: [] for kind in wiring.LEDGER_KINDS}

    def reset_confirmation(self):
        return "RESET"


class FakeSession:
    """A WorldSession over a FakeStore."""

    def __init__(self, world, store):
        self.world, self.store, self.database, self.dataset_id, self.manifest_hash = world, store, f"shipments-v2-world-{world.lower()}", store.dataset_id, "0" * 64
        self.reader = SimpleNamespace()
        self.assessed = []

    def clock(self):
        return self.store.status()["as_of"]

    def rows(self, kind, **where):
        assert kind in wiring.LEDGER_KINDS and not set(where) - set(wiring.LEDGER_FILTERS)
        rows = [dict(r) for r in self.store.ledger[kind] if all(r.get(k) == v for k, v in where.items())]
        return sorted(rows, key=lambda r: (str(r.get("recorded_at")), r["entity_id"]))

    def opening_facts(self, shipment_id, at):
        self.assessed.append((shipment_id, at))
        opening = self.store.openings[shipment_id]
        return tuple(sorted(opening["codes"])), tuple(sorted(opening["evidence"]))

    def api_responses(self, case):
        return [{"endpoint": "case_detail", "response": {"case_id": case.case_id, "run": {"result": {"mode": "gpt_oss_agents"}}}},
                {"endpoint": "queue", "response": {"items": [{"case_id": case.case_id}]}}]

    def graph_dump(self):
        yield {"world": self.world, "nodes": [{"labels": ["OpsCase"], "properties": c} for c in self.store.ledger["OpsCase"]]}


def openings(*rows):
    return {sid: {"at": at, "symptoms": symptoms, "codes": codes, "evidence": [f"DEMO-EV-{sid[-3:]}-1", f"DEMO-EV-{sid[-3:]}-2"]}
            for sid, at, symptoms, codes in rows}


THREE = openings(("DEMO-SHP-000001", "2026-09-14T09:00:00+00:00", ["MILESTONE_OVERDUE"], ["MISSED_MILESTONE"]),
                 ("DEMO-SHP-000002", "2026-09-14T09:00:00+00:00", ["WEIGHT_READ_DIFFERS", "BARCODE_READ_DIFFERS"], ["WEIGHT_MISMATCH", "BARCODE_MISMATCH"]),
                 ("DEMO-SHP-000003", "2026-09-14T15:00:00+00:00", ["DELIVERY_ATTEMPT_FAILED"], ["WRONG_GATE", "RECIPIENT_UNAVAILABLE"]))
EXPECTED = {("E1", sid): opening["at"] for sid, opening in THREE.items()}   # what the selection carries (expected_opened_at)


class CaseSourceTests(unittest.TestCase):
    def source(self, expected=None, **options):
        self.store = FakeStore(THREE)
        self.session = FakeSession("E1", self.store)
        return wiring.WorldCaseSource({"E1": self.session}, expected, **options)

    def test_the_clock_advances_only_until_the_selected_case_opens(self):
        source = self.source({("E1", "DEMO-SHP-000001"): "2026-09-14T09:00:00+00:00", ("E1", "DEMO-SHP-000003"): "2026-09-14T15:00:00+00:00"})
        ref = source.case_ref("E1", "DEMO-SHP-000001")
        self.assertEqual(self.store.ticks, 3)                                   # 06:00 -> 09:00 and no further
        self.assertEqual((ref.key, ref.world, ref.shipment_id, ref.case_id), ("E1:DEMO-SHP-000001", "E1", "DEMO-SHP-000001", "DEMO-OPS-CASE-000001"))
        self.assertEqual(ref.as_of, "2026-09-14T09:00:00+00:00")                # the store's clock: the snapshot the run will use
        self.assertEqual((ref.symptoms, ref.rule_codes), (("MILESTONE_OVERDUE",), ("MISSED_MILESTONE",)))
        self.assertEqual(ref.opening_evidence_ids, ("DEMO-EV-001-1", "DEMO-EV-001-2"))
        self.assertEqual(self.session.assessed[0], ("DEMO-SHP-000001", "2026-09-14T09:00:00+00:00"))   # assessed at the opening
        self.assertEqual(self.store.outcome_steps, 3)                           # earlier cases' verifications keep running
        self.assertEqual(self.store.processed, [])                              # the source investigates nothing
        # A case that opened in the same tick is returned without moving the clock.
        other = source.case_ref("E1", "DEMO-SHP-000002")
        self.assertEqual((self.store.ticks, other.as_of), (3, "2026-09-14T09:00:00+00:00"))
        self.assertEqual(other.symptoms, ("BARCODE_READ_DIFFERS", "WEIGHT_READ_DIFFERS"))               # from the CASE_OPENED audit
        self.assertEqual(other.rule_codes, ("BARCODE_MISMATCH", "WEIGHT_MISMATCH"))
        later = source.case_ref("E1", "DEMO-SHP-000003")
        self.assertEqual((self.store.ticks, later.as_of), (9, "2026-09-14T15:00:00+00:00"))
        self.assertEqual(source.counts["E1"], {"hours": 9, "ingested": 27, "rejected": 0, "monitor_checked": 3, "cases_opened": 3})

    def test_a_case_that_does_not_open_is_given_up_at_the_horizon(self):
        source = self.source({("E1", "DEMO-SHP-000009"): "2026-09-14T08:00:00+00:00"})
        self.assertIsNone(source.case_ref("E1", "DEMO-SHP-000009"))
        self.assertEqual(self.store.status()["as_of"], "2026-09-14T10:00:00+00:00")   # expected 08:00 + 2 h, not the end of the feed
        # Cases that opened on the way are known, and are still returned at the clock as it stands.
        self.assertEqual(source.case_ref("E1", "DEMO-SHP-000001").as_of, "2026-09-14T10:00:00+00:00")
        # Without an expected opening the wait is the horizon from where the clock stands.
        self.assertIsNone(source.case_ref("E1", "DEMO-SHP-000008"))
        self.assertEqual(self.store.status()["as_of"], "2026-09-14T12:00:00+00:00")

    def test_the_replay_end_stops_the_wait(self):
        self.store = FakeStore(THREE, end_hours=1)
        source = wiring.WorldCaseSource({"E1": FakeSession("E1", self.store)}, {("E1", "DEMO-SHP-000003"): "2026-09-14T15:00:00+00:00"})
        self.assertIsNone(source.case_ref("E1", "DEMO-SHP-000003"))
        self.assertLessEqual(self.store.ticks, 2)

    def test_a_resumed_session_knows_the_cases_it_already_opened(self):
        first = self.source({("E1", "DEMO-SHP-000001"): "2026-09-14T09:00:00+00:00"})
        first.case_ref("E1", "DEMO-SHP-000001")
        ticks = self.store.ticks
        again = wiring.WorldCaseSource({"E1": self.session})
        ref = again.case_ref("E1", "DEMO-SHP-000002")
        self.assertEqual((self.store.ticks, ref.case_id, ref.rule_codes), (ticks, "DEMO-OPS-CASE-000002", ("BARCODE_MISMATCH", "WEIGHT_MISMATCH")))

    def test_only_the_first_case_of_a_shipment_counts(self):
        source = self.source({("E1", "DEMO-SHP-000001"): "2026-09-14T09:00:00+00:00"})
        self.assertIsNotNone(source.case_ref("E1", "DEMO-SHP-000001"))
        self.store.ledger["OpsCase"].append({"entity_id": "DEMO-OPS-CASE-SECOND", "shipment_id": "DEMO-SHP-000001", "session_id": self.store.session_id,
                                             "opened_at": "2026-09-14T20:00:00+00:00", "recorded_at": "2026-09-14T20:00:00+00:00", "symptom_codes": ["X"]})
        source._note("E1", self.store.ledger["OpsCase"][-1])
        self.assertEqual(source.case_ref("E1", "DEMO-SHP-000001").case_id, "DEMO-OPS-CASE-000001")


class RunCaseTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore(THREE, calls=9)
        self.session = FakeSession("E1", self.store)
        self.source = wiring.WorldCaseSource({"E1": self.session}, EXPECTED)
        self.case = self.source.case_ref("E1", "DEMO-SHP-000001")

    def test_the_named_case_is_processed_once_and_read_back_from_the_ledger(self):
        result = wiring.run_case(self.session, self.case)
        self.assertEqual((self.store.processed, self.store.executed), ([self.case.case_id], 1))
        self.assertEqual((result.arm, result.case_key, result.case_id), ("agent", "E1:DEMO-SHP-000001", self.case.case_id))
        self.assertEqual((result.calls_used, result.as_of, result.cap_hit), (9, "2026-09-14T09:00:00+00:00", False))   # the store's own counter
        self.assertEqual((result.primary_cause, result.review_verdict, result.authority, result.final_state),
                         ("INSUFFICIENT_EVIDENCE", "ACCEPT", "HUMAN_REVIEW", "HUMAN_REVIEW"))
        self.assertEqual(result.retrieved_ids, ["DEMO-EV-001-1", "DEMO-EV-001-2"])
        self.assertEqual(result.cited_ids, ["DEMO-EV-001-1"])
        self.assertEqual(result.executions, [{"action_type": "REQUEST_ADDITIONAL_EVIDENCE", "authority": "AUTO_POLICY", "status": "NOT_ACKNOWLEDGED"}])
        self.assertFalse(result.degraded)

    def test_a_case_that_was_not_processed_is_degraded_and_settled_at_its_worst_case(self):
        self.store.unprocessable.add("DEMO-SHP-000001")
        result = wiring.run_case(self.session, self.case)
        self.assertEqual((result.degraded, result.failure_mode, result.calls_used), (True, "not_processed:snapshot_changed", None))
        self.assertEqual(self.store.processed, [self.case.case_id])          # not retried: a retry could pass the reservation
        self.assertEqual(self.store.executed, 0)

    def test_tokens_and_tool_seconds_come_from_the_run_not_from_a_second_call_count(self):
        tap = wiring.ToolTap(None)
        tokens = iter([1000, 5600])
        original = self.store.process_one

        def process_one(case_id=None, *, manual=False):
            tap.calls.extend([{"seconds": 0.02}, {"seconds": 0.05}])
            return original(case_id, manual=manual)
        self.store.process_one = process_one
        result = wiring.run_case(self.session, self.case, tap=tap, tokens=lambda: next(tokens))
        self.assertEqual((result.tokens, result.tool_seconds, result.calls_used), (4600, [0.02, 0.05], 9))

    def test_a_backend_cap_that_is_not_the_sealed_one_stops_the_run_before_anything_is_called(self):
        """Gate fix 3: the store's per-case cap must equal the sealed C_cap, at build and again before each case."""
        from stage3_eval.arms import AgentArm
        from stage3_eval.budget import BudgetLedger, RunStopped
        from stage3_eval.runner import _run_arm
        self.store.model_call_cap = 12
        self.assertEqual(wiring.require_sealed_cap(self.session, 12), 12)
        for wrong in (None, 11, 20):          # None: the environment's default, whatever it is, is not the sealed setting
            self.store.model_call_cap = wrong
            with self.assertRaisesRegex(RunStopped, "sealed C_cap is 12"):
                wiring.require_sealed_cap(self.session, 12)
            with self.assertRaises(RunStopped):
                wiring.run_case(self.session, self.case, c_cap=12)
            with self.assertRaises(RunStopped):
                wiring.investigate_as_of(self.session, self.case, c_cap=12)
        self.assertEqual(self.store.processed, [])
        # The runner does not turn it into an arm error: the run stops, the reservation stays counted at its worst case.
        with tempfile.TemporaryDirectory() as directory:
            ledger, counts = BudgetLedger(Path(directory) / "ledger.jsonl", 100), {"arm_errors": 0}
            arm = AgentArm(lambda case: wiring.run_case(self.session, case, c_cap=12), 12)
            with self.assertRaises(RunStopped):
                _run_arm(arm, self.case, ledger, False, counts)
            self.assertEqual((counts["arm_errors"], ledger.committed, self.store.processed), (0, 12, []))


class RecordFieldTests(unittest.TestCase):
    """records.FIELDS reads the Stage 2 run record (docs/api/investigation-run.md)."""

    def test_the_counter_snapshot_and_cap_hit_are_read_from_the_investigation_log(self):
        analysis = stage2_analysis("2026-09-15T10:00:00+00:00", calls=11, cap_reached=True, degraded=True)
        result = from_ops_run("E1:S", "S", case={"entity_id": "C", "workflow_state": "ESCALATED"},
                              runs=[{"recorded_at": "2026-09-15T10:00:00+00:00", "result_json": json.dumps(analysis)}])
        self.assertEqual((result.calls_used, result.as_of, result.cap_hit), (11, "2026-09-15T10:00:00+00:00", True))
        self.assertEqual((result.degraded, result.failure_mode, result.primary_cause), (True, "model_call_cap", None))
        self.assertEqual((result.review_verdict, result.review_rounds, result.authority), ("ACCEPT", 1, "HUMAN_REVIEW"))

    def test_the_first_run_is_scored_and_a_run_without_a_log_falls_back_to_the_investigators_budget(self):
        first = stage2_analysis("2026-09-15T10:00:00+00:00", calls=6)
        first["investigation_log"] = None
        second = stage2_analysis("2026-09-16T10:00:00+00:00", calls=12, primary="HUB_DELAY")
        result = from_ops_run("E1:S", "S", case={"entity_id": "C"},
                              runs=[{"recorded_at": "2026-09-16T10:00:00+00:00", "result_json": json.dumps(second)},
                                    {"recorded_at": "2026-09-15T10:00:00+00:00", "result_json": json.dumps(first)}])
        self.assertEqual((result.calls_used, result.as_of, result.primary_cause), (6, "2026-09-15T10:00:00+00:00", "INSUFFICIENT_EVIDENCE"))
        nothing = from_ops_run("E1:S", "S", case={"entity_id": "C"}, runs=[{"recorded_at": "x", "result_json": json.dumps({"investigation": None})}])
        self.assertIsNone(nothing.calls_used)                                  # settled at the worst case by the budget ledger


class RealGraphTests(unittest.TestCase):
    """The real investigation graph and tools over the in-memory world with a scripted model: the run record the
    harness reads, the as-of extras and the tool tap."""

    @classmethod
    def setUpClass(cls):
        from tests.world_fixture import small_world
        cls.fixture = small_world()
        cls.config = cls.fixture.world.config
        cls.sid = sorted(n.id for n in cls.fixture.world.of_kind("Shipment") if n.properties.get("split") == "development")[0]
        cls.as_of = cls.config.as_of
        cls.agents = PlanAgents()
        cls.tap = wiring.ToolTap(cls.agents)
        store = SimpleNamespace(config=cls.config, agents=cls.tap, model_call_cap=12)     # no process_one, no execute_step: nothing can be recorded
        cls.session = SimpleNamespace(world="E1", reader=cls.fixture.reader, store=store)
        cls.case = CaseRef(key=f"E1:{cls.sid}", world="E1", shipment_id=cls.sid, case_id="DEMO-OPS-CASE-X", as_of=cls.as_of,
                           symptoms=("MILESTONE_OVERDUE",))

    def test_an_extra_investigates_as_of_the_snapshot_with_the_tools_withheld_and_records_nothing(self):
        from operations.tools import CROSS_SHIPMENT_TOOLS
        before = self.agents.calls
        full = wiring.investigate_as_of(self.session, self.case, disabled=(), tap=self.tap, arm="stability_rerun")
        full_calls, full_index = self.tap.drain()
        used = self.agents.calls - before
        self.assertEqual((full.arm, full.as_of, full.case_key), ("stability_rerun", self.as_of, self.case.key))
        self.assertEqual(full.calls_used, used)                                # the investigation's own counter, nothing else
        self.assertEqual((full.primary_cause, full.degraded, full.review_verdict), ("INSUFFICIENT_EVIDENCE", False, "ACCEPT"))
        self.assertLessEqual(used, 12)
        self.assertTrue(set(full.cited_ids) <= set(full.retrieved_ids))
        self.assertEqual(full.executions, [])
        self.assertEqual(len(full.tool_seconds), len(full_calls))
        self.assertEqual([c["tool"] for c in full_calls], [s["tool"] for s in full.steps])
        for call in full_calls:                                                # the text the model received, with its citable ids
            self.assertIn(" CITABLE_EVIDENCE_IDS: ", call["output"]["result"])
            self.assertEqual((call["shipment_id"], call["as_of"]), (self.sid, self.as_of))
        self.assertTrue(set(full.retrieved_ids) <= set(full_index))
        for key in full.retrieved_ids:
            self.assertTrue(full_index[key]["recorded_at"], key)
            self.assertLessEqual(instant(full_index[key]["recorded_at"]), instant(self.as_of))
        ablated = wiring.investigate_as_of(self.session, self.case, disabled=CROSS_SHIPMENT_TOOLS, tap=self.tap, arm="cross_shipment_ablation")
        ablated_calls, _ = self.tap.drain()
        self.assertFalse({s["tool"] for s in ablated.steps} & set(CROSS_SHIPMENT_TOOLS))
        for call in ablated_calls:
            if call["tool"] in CROSS_SHIPMENT_TOOLS:                           # asked for, refused, and never counted as a step
                self.assertIn("error", call["output"])
        self.assertTrue({s["tool"] for s in full.steps} & set(CROSS_SHIPMENT_TOOLS), "the fixture shipment has no shared reference")

    def test_the_tap_changes_nothing_the_model_sees(self):
        from operations.graph import investigate
        plain = PlanAgents()
        reader = self.fixture.reader
        arguments = dict(commit=None, live_session=True, symptoms=["MILESTONE_OVERDUE"], heartbeats=reader.heartbeats, port=reader.fetch, call_cap=12)
        direct, _ = investigate(self.sid, self.as_of, self.config, reader.evidence, lambda sid, codes: [], agents=plain, **arguments)
        tapped, _ = investigate(self.sid, self.as_of, self.config, reader.evidence, lambda sid, codes: [], agents=wiring.ToolTap(PlanAgents()), **arguments)
        from tests.test_latency_equivalence import strip       # timing fields differ from run to run; nothing else may
        for field in ("investigation", "review", "authority", "investigation_log", "context_hash"):
            self.assertEqual(json.dumps(strip(direct[field]), sort_keys=True, default=str), json.dumps(strip(tapped[field]), sort_keys=True, default=str), field)


class CaptureAndScorerTests(unittest.TestCase):
    def test_the_five_surfaces_are_captured(self):
        store = FakeStore(THREE)
        session = FakeSession("E1", store)
        source = wiring.WorldCaseSource({"E1": session}, EXPECTED)
        case = source.case_ref("E1", "DEMO-SHP-000001")
        tap = wiring.ToolTap(None)
        logs = wiring.LogCapture()
        capture = wiring.WorldCapture({"E1": session}, tap, logs)
        belt = SimpleNamespace(sid=case.shipment_id, as_of=case.as_of, call=lambda tool, args: {"result": 'TEXT CITABLE_EVIDENCE_IDS: ["DEMO-EV-001-1"]'},
                               index={"DEMO-EV-001-1": {"kind": "ScanEvent", "scope": "shipment", "recorded_at": "2026-09-14T08:00:00+00:00"},
                                      "DEMO-CMP-1": {"kind": "ComputedResult", "scope": "computed", "recorded_at": None}},
                               computed={"DEMO-CMP-1": {"computed_as_of": case.as_of}})
        tap._tap(belt)
        belt.call("scans", {})
        result = wiring.run_case(session, case)
        captured = capture.capture_case(case, {"agent": result})
        self.assertEqual(captured["tools"][0]["calls"][0]["output"]["result"], 'TEXT CITABLE_EVIDENCE_IDS: ["DEMO-EV-001-1"]')
        self.assertEqual(captured["tool_index"][0]["index"]["DEMO-CMP-1"]["recorded_at"], case.as_of)
        self.assertEqual([r["endpoint"] for r in captured["api"]], ["case_detail", "queue"])
        self.assertEqual(captured["receipts"][0]["record"]["adapter_result_json"], json.dumps({"acknowledged": False, "adapter": "none"}))
        self.assertEqual(tap.drain(), ([], {}))                                # drained per case
        extra_belt = SimpleNamespace(sid=case.shipment_id, as_of=case.as_of, call=lambda tool, args: {"result": "X"}, index={}, computed={})
        tap._tap(extra_belt)
        extra_belt.call("journey", {})
        capture.stash_extra(case, "stability_rerun")
        logs.emit(__import__("logging").LogRecord("stage3_wiring", 20, __file__, 1, "E1: session", (), None))
        whole = capture.capture_run()
        self.assertEqual(sorted(whole), ["graph", "logs", "tool_index", "tools"])
        self.assertEqual(list(whole["graph"])[0]["nodes"][0]["labels"], ["OpsCase"])
        self.assertEqual(whole["logs"][0]["records"], 1)
        self.assertIn("E1: session", whole["logs"][1])
        self.assertEqual((whole["tools"][0]["arm"], whole["tools"][0]["calls"][0]["tool"]), ("stability_rerun", "journey"))
        # A case with no execution still writes a receipts line.
        other = source.case_ref("E1", "DEMO-SHP-000002")
        self.assertEqual(capture.capture_case(other, {})["receipts"][0]["kind"], "none")

    def test_the_ingestion_log_counts_an_imported_record_from_its_time_and_a_fed_record_from_its_ingestion(self):
        rows = [("DEMO-IMPORTED", "2026-09-14T08:00:00+00:00", None),
                ("DEMO-FED", "2026-09-14T08:10:00+00:00", "2026-09-14T09:00:00+00:00"),
                ("DEMO-LATER", "2026-09-14T09:30:00+00:00", "2026-09-14T10:00:00+00:00")]
        reads = []
        log = wiring.WorldIngestionLog(lambda world: reads.append(world) or rows)
        self.assertEqual(log.ingested("E1", "2026-09-14T08:30:00+00:00"), {"DEMO-IMPORTED"})      # delivered, not yet ingested
        self.assertEqual(log.ingested("E1", "2026-09-14T09:00:00Z"), {"DEMO-IMPORTED", "DEMO-FED"})
        self.assertEqual(log.ingested("E1", "2026-09-14T10:00:00+00:00"), {"DEMO-IMPORTED", "DEMO-FED", "DEMO-LATER"})
        self.assertEqual(reads, ["E1"])                                         # one read of the database per world

    def test_the_resolver_answers_from_the_database_then_from_the_tools_own_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captured" / "tool_index"
            root.mkdir(parents=True)
            (root / "E1_S.jsonl").write_text(json.dumps({"world": "E1", "case": "E1:S", "index": {
                "DEMO-CMP-1": {"kind": "ComputedResult", "scope": "computed", "recorded_at": "2026-09-14T09:00:00+00:00", "shown_as_of": "2026-09-14T09:00:00+00:00"},
                "DEMO-REC-1": {"kind": "ScanEvent", "scope": "shipment", "recorded_at": "2030-01-01T00:00:00+00:00"},
                "DEMO-DEVICE": {"kind": "Device", "scope": "shared", "recorded_at": None, "shown_as_of": "2026-09-14T09:00:00+00:00"}}}) + "\n"
                + json.dumps({"world": "E1", "case": "extras", "index": {"DEMO-CMP-1": {"recorded_at": "2026-09-15T09:00:00+00:00"}}}) + "\n", encoding="utf-8")
            index = wiring.read_tool_index(directory)
        self.assertEqual(index["E1"]["DEMO-CMP-1"]["recorded_at"], "2026-09-14T09:00:00+00:00")   # the earliest showing
        resolver = wiring.WorldResolver(lambda world, ids: {"DEMO-REC-1": "2026-09-14T08:00:00+00:00"} if world == "E1" else {}, index)
        found = resolver.recorded_at("E1", ["DEMO-REC-1", "DEMO-CMP-1", "DEMO-DEVICE", "DEMO-INVENTED", None])
        self.assertEqual(found, {"DEMO-REC-1": "2026-09-14T08:00:00+00:00",      # the database wins over the index
                                 "DEMO-CMP-1": "2026-09-14T09:00:00+00:00", "DEMO-DEVICE": "2026-09-14T09:00:00+00:00"})
        self.assertEqual(resolver.recorded_at("E2", ["DEMO-CMP-1"]), {})         # another world's index does not resolve it


class SessionTests(unittest.TestCase):
    def test_a_fresh_session_is_used_as_it_is_with_the_cap_set_and_the_worker_paused(self):
        store = FakeStore(THREE)
        store.worker_state = "running"
        done = wiring.prepare_session(FakeSession("E1", store), resume=False, c_cap=14, allow_reset=False)
        self.assertEqual((store.model_call_cap, store.disabled_tools, store.worker_state, store.resets), (14, (), "paused", 0))
        self.assertEqual((done["session_reset"], done["resumed"], done["clock_at_start"], done["per_case_model_call_cap"], done["worker_paused_by_wiring"]),
                         (False, False, START, 14, True))

    def test_an_advanced_session_is_refused_unless_resumed_or_the_reset_is_asked_for(self):
        store = FakeStore(THREE)
        session = FakeSession("E1", store)
        wiring.WorldCaseSource({"E1": session}, {("E1", "DEMO-SHP-000001"): "2026-09-14T09:00:00+00:00"}).case_ref("E1", "DEMO-SHP-000001")
        with self.assertRaisesRegex(SystemExit, "already advanced"):
            wiring.prepare_session(session, resume=False, c_cap=12, allow_reset=False)
        with mock.patch.dict(os.environ, {wiring.RESET_ENV: "0"}):
            with self.assertRaisesRegex(SystemExit, wiring.RESET_ENV):
                wiring.prepare_session(session, resume=False, c_cap=12)
        self.assertEqual(store.resets, 0)
        kept = wiring.prepare_session(session, resume=True, c_cap=12, allow_reset=False)
        self.assertEqual((kept["resumed"], kept["session_reset"], kept["clock_at_start"]), (True, False, "2026-09-14T09:00:00+00:00"))
        with mock.patch.dict(os.environ, {wiring.RESET_ENV: "1"}), mock.patch.object(wiring._pilot(), "reset_ledger", lambda s: s.reset_session("x")):
            reset = wiring.prepare_session(session, resume=False, c_cap=12)
        self.assertEqual((store.resets, reset["session_reset"], reset["clock_at_start"], reset["session_id"]), (1, True, START, "DEMO-SESSION-2"))

    def test_a_cap_the_investigator_would_clamp_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "C_cap 2 is outside"):
            wiring.prepare_session(FakeSession("E1", FakeStore(THREE)), resume=False, c_cap=2, allow_reset=False)

    def test_a_selection_naming_an_excluded_shipment_is_refused_for_that_dataset_only(self):
        """The exclusion list (shipments whose truth labels were exposed) is honoured by the run side too."""
        from stage3_eval.budget import RunStopped
        session = FakeSession("E1", FakeStore(THREE))
        selection = {"cases": [{"world": "E1", "shipment_id": sid} for sid in THREE]}
        lists = ({session.dataset_id: frozenset({"DEMO-SHP-000002"})}, [{"file": "test"}])
        with self.assertRaisesRegex(SystemExit, "exclusion list of dataset DEMO-SUHAIL-WORLD-FAKE.*DEMO-SHP-000002"):
            wiring.refuse_excluded({"E1": session}, selection, lists)
        self.assertEqual(wiring.refuse_excluded({"E1": session}, selection, ({"ANOTHER-DATASET": frozenset(THREE)}, [{"file": "test"}])),
                         [{"file": "test"}])
        # The committed list is the default: it names world 1's dataset, and a database holding that dataset is refused.
        self.assertEqual(wiring.refuse_excluded({"E1": session}, selection)[0]["dataset_id"], "DEMO-SUHAIL-WORLD-1")
        session.dataset_id = "DEMO-SUHAIL-WORLD-1"
        with self.assertRaisesRegex(SystemExit, "DEMO-SHP-000019"):
            wiring.refuse_excluded({"E1": session}, {"cases": [{"world": "E1", "shipment_id": "DEMO-SHP-000019"}]})
        # The case source itself never hands such a shipment to an arm, and does not move the clock for it.
        store = FakeStore(THREE)
        source = wiring.WorldCaseSource({"E1": FakeSession("E1", store)}, EXPECTED, exclusions={store.dataset_id: frozenset({"DEMO-SHP-000001"})})
        with self.assertRaisesRegex(RunStopped, "exclusion list"):
            source.case_ref("E1", "DEMO-SHP-000001")
        self.assertEqual(store.ticks, 0)
        self.assertEqual(source.case_ref("E1", "DEMO-SHP-000002").shipment_id, "DEMO-SHP-000002")

    def test_the_no_tools_arm_is_built_at_the_sealed_cap(self):
        """Its packet states the agent's per-case cap; the wiring gives it the sealed C_cap, not the runner's binding."""
        clean = {k: v for k, v in os.environ.items() if "TRUTH" not in k.upper() and k != "SUHAIL_SIM_STATE_ROOT"}
        with mock.patch.dict(os.environ, clean, clear=True):
            wired = wiring.build(EvalConfig(freeze_commit="a" * 40, c_cap=16, budget=100, worlds={}), dry_run=True, agents=object(), driver=object())
        self.addCleanup(wired["close"])
        self.assertEqual((wired["arms"]["notools"].c_cap, wired["arms"]["notools"].worst_case()), (16, 3))
        self.assertEqual((wired["arms"]["agent"].worst_case(), wired["extras_arms"]["stability_rerun"].worst_case()), (16, 16))

    def test_the_run_side_refuses_a_truth_path_and_reads_no_truth(self):
        with mock.patch.dict(os.environ, {"SUHAIL_EVAL_TRUTH_ROOT": r"C:\somewhere"}):
            with self.assertRaises(SystemExit):
                wiring.build(EvalConfig(freeze_commit="a" * 40, worlds={"E1": {"database": "shipments-v2-world-x"}}), driver=object())
        source = Path(wiring.__file__).read_text(encoding="utf-8")
        for forbidden in ("import world.truth", "from world.truth", "from world import", "world.mechanisms", "suhail-eval-truth", "truth_io",
                          "stage3_eval.scoring", "stage3_eval.selection", "stage3_eval.strata", "labels_at(", "CREATE OR REPLACE DATABASE",
                          "DROP DATABASE", "CREATE DATABASE"):
            self.assertNotIn(forbidden, source)
        with self.assertRaisesRegex(SystemExit, "names no database"):
            wiring.open_world(object(), "E1", {}, None)


class HarnessOverAFakeWorldTests(unittest.TestCase):
    """select -> dry run -> run -> score -> report over the committed harness fixture, with the wiring's own case
    source, agent arm, extras and capture on a fake store."""

    def setUp(self):
        from stage3_eval.fixtures.fakes import FixtureDatabase, world_dir
        from stage3_eval.selection import scorer_view, select
        from stage3_eval.truth_io import load_replay_rows, load_truth
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.worlds = {w: (load_truth(world_dir(w) / "truth" / "truth.jsonl"), load_replay_rows(world_dir(w) / "truth" / "monitor_replay_rows.jsonl"))
                       for w in ("E1", "E2")}
        self.config = EvalConfig(freeze_commit="b" * 40, budget=1500, worlds={w: {"database": f"shipments-v2-world-{w.lower()}"} for w in ("E1", "E2")})
        select(self.worlds, self.config, self.root / "pre")
        self.selection = json.loads((self.root / "pre" / "selection.json").read_text(encoding="utf-8"))   # what the run reads
        self.scored_selection = scorer_view(self.root / "pre" / "selection.json")                          # scorer side only
        self.runtime = {w: json.loads((world_dir(w) / "runtime" / "cases.json").read_text(encoding="utf-8")) for w in ("E1", "E2")}
        self.database = FixtureDatabase()
        clean = {k: v for k, v in os.environ.items() if "TRUTH" not in k.upper()}
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def wired(self, *, dry_run=False):
        sessions = {}
        for world, cases in self.runtime.items():
            rows = {c["shipment_id"]: {"at": c["as_of"][:14] + "00:00+00:00", "symptoms": c["symptoms"], "codes": c["rule_codes"],
                                       "evidence": c["opening_evidence_ids"]} for c in cases}
            sessions[world] = FakeSession(world, FakeStore(rows, calls=8, end_hours=24 * 30))
        expected = {(row["world"], row["shipment_id"]): row["expected_opened_at"] for row in self.selection["cases"]}
        tap = wiring.ToolTap(None)
        capture = wiring.WorldCapture(sessions, tap, wiring.LogCapture())
        from stage3_eval.arms import AgentArm, NoToolsArm, RuleCodeArm, SymptomArm

        def notools(messages):
            return {"action": "conclude", "primary_cause": "MISSED_MILESTONE", "confidence": "low", "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE",
                    "hypotheses": [{"cause": "MISSED_MILESTONE", "status": "supported", "supporting_evidence_ids": [], "contradicting_evidence_ids": [],
                                    "assessment": "From the symptoms only."}], "missing_evidence": ["records"], "requires_physical_check": False,
                    "summary": "Symptoms only."}

        def stability(case):
            session = sessions[case.world]
            analysis = stage2_analysis(case.as_of, calls=5)
            try:
                return from_ops_run(case.key, case.shipment_id, case={"entity_id": case.case_id}, runs=[{"recorded_at": case.as_of, "result_json": analysis}])
            finally:
                capture.stash_extra(case, "stability_rerun")
                self.assertTrue(session.store.processed)
        return sessions, {"arms": {"agent": AgentArm(lambda case: wiring.run_case(sessions[case.world], case, tap=tap), self.config.c_cap),
                                   "notools": NoToolsArm(turn=notools), "rulecode": RuleCodeArm(), "symptom": SymptomArm()},
                          "case_source": wiring.WorldCaseSource(sessions, expected), "capture": capture,
                          "extras_arms": {"stability_rerun": AgentArm(stability, self.config.c_cap, name="stability_rerun")}}

    def test_select_dry_run_run_score_report(self):
        from stage3_eval.canary import TruthScanner
        from stage3_eval.report import build_report, render_markdown
        from stage3_eval.scoring import score_run
        from stage3_eval.truth_io import truth_vocabulary
        selected = len(self.selection["cases"])
        # Dry run: the replay is driven, cases are read, nothing is investigated and no call is reserved.
        sessions, wired = self.wired(dry_run=True)
        manifest = run(self.root / "pre" / "selection.json", self.root / "dry", config=self.config, dry_run=True, **wired)
        self.assertEqual([s.store.processed for s in sessions.values()], [[], []])
        self.assertTrue(all(s.store.ticks for s in sessions.values()))
        self.assertEqual((manifest["ledger"]["settled_calls"], manifest["counts"]["not_opened"]), (0, 0))
        self.assertEqual(manifest["ledger"]["planned_calls"], selected * (self.config.c_cap + 3))
        # The run.
        sessions, wired = self.wired()
        manifest = run(self.root / "pre" / "selection.json", self.root / "run", config=self.config,
                       extras_path=self.root / "pre" / "extras.json", provenance=lambda: {"dirty_tree": False, "tree_changed_during_run": False,
                                           "model_calls": {"succeeded": {"scripted": selected * 9}, "failed": {}}}, **wired)
        self.assertEqual((manifest["status"], manifest["counts"]["not_opened"], manifest["counts"]["arm_errors"]), ("completed", 0, 0))
        investigated = [case_id for s in sessions.values() for case_id in s.store.processed]
        self.assertEqual(len(investigated), selected)
        self.assertEqual(len(set(investigated)), selected)                        # each selected case once, and no other
        opened = sum(len(s.store.ledger["OpsCase"]) for s in sessions.values())
        self.assertGreaterEqual(opened, selected)
        self.assertEqual(manifest["ledger"]["calls_by_arm"]["agent"], selected * 8)   # the store's counter, as recorded
        agent_rows = [json.loads(l) for l in (self.root / "run" / "results" / "main" / "agent.jsonl").read_text(encoding="utf-8").splitlines()]
        cases = {json.loads(l)["key"]: json.loads(l) for l in (self.root / "run" / "cases.jsonl").read_text(encoding="utf-8").splitlines()}
        for row in agent_rows:
            # Investigated at the tick the case opened: the snapshot is the monitor's expected opening hour.
            self.assertEqual(row["as_of"], cases[row["case_key"]]["as_of"])
        expected = {row["key"]: row["expected_opened_at"] for row in self.selection["cases"]}
        late = [k for k, c in cases.items() if instant(c["as_of"]) > instant(expected[k])]
        self.assertEqual(late, [])
        for surface in ("tools", "api", "receipts", "graph", "logs", "tool_index"):
            self.assertTrue(any((self.root / "run" / "captured" / surface).iterdir()), surface)
        # Score and report (the scorer side reads truth; the fixture's database answers the two seams).
        truth = {w: self.worlds[w][0] for w in self.worlds}
        self.assertEqual(manifest["extras"]["stability_rerun"]["completed"], 34)   # the whole main-test cell (34 <= design.STABILITY_MAX)
        scores = score_run(self.root / "run", self.scored_selection, truth, ingestion=self.database, resolver=self.database)
        self.assertEqual(len([s for s in scores if s["phase"] == "main"]), selected * 4)
        canary = TruthScanner(truth_vocabulary(truth["E1"])).scan_run(self.root / "run")
        self.assertEqual((canary["verdict"], canary["missing_surfaces"]), ("clean", []))
        report = build_report(self.scored_selection, scores=scores, run_manifest=manifest, canary=canary,
                              pairs=json.loads((self.root / "pre" / "pairs.json").read_text(encoding="utf-8")))
        self.assertEqual(report["validity"]["verdict"], "valid")
        self.assertIn("Arms side by side", render_markdown(report))


@unittest.skipUnless(os.environ.get("SUHAIL_NEO4J_TESTS") == "1", "set SUHAIL_NEO4J_TESTS=1 to run against local Neo4j")
class Stage3WiringNeo4jTests(unittest.TestCase):
    """The fixture mechanism world in the scratch database, driven by the real store through the wiring with a scripted
    model: select -> dry run -> run -> score -> report."""

    @classmethod
    def setUpClass(cls):
        from stage3_eval.selection import scorer_view, select
        from world.validate import monitor_replay
        assert TEST_DATABASE in SCRATCH
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.driver, cls.fixture = build_world_database(TEST_DATABASE)
        fixture = cls.fixture
        # The scorer side of the test: the fixture's truth rows and the monitor replica's openings (never given to build()).
        replay = monitor_replay(fixture.build, fixture.imported, fixture.items, fixture.truth, fixture.live_start)["shipments"]
        # Only the shipments the replica opens in the first hours are offered to the selection, so the test replays a
        # short stretch of the feed (an hour of feed takes the store some ten seconds here), twice.
        horizon = instant(str(fixture.live_start)) + timedelta(hours=NEO4J_TEST_HOURS)
        replay = {sid: row for sid, row in replay.items() if row.get("opened_at") and instant(row["opened_at"]) <= horizon}
        cls.truth = {"E1": dict(fixture.truth)}
        cls.config = EvalConfig(freeze_commit="c" * 40, c_cap=12, budget=1400, worlds={"E1": {"database": TEST_DATABASE}})
        cls.summary = select({"E1": (cls.truth["E1"], replay)}, cls.config, cls.root / "pre")
        cls.selection = json.loads((cls.root / "pre" / "selection.json").read_text(encoding="utf-8"))   # what the run reads
        cls.scored_selection = scorer_view(cls.root / "pre" / "selection.json")                          # scorer side only
        cls.replay = replay
        clean = {k: v for k, v in os.environ.items() if "TRUTH" not in k.upper()}
        cls.patcher = mock.patch.dict(os.environ, clean, clear=True)
        cls.patcher.start()
        cls.agents = PlanAgents()

        def notools(messages):
            cls.notools_calls += 1
            return {"action": "conclude", "primary_cause": "UNKNOWN", "confidence": "low", "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE",
                    "hypotheses": [{"cause": "UNKNOWN", "status": "uncertain", "supporting_evidence_ids": [], "contradicting_evidence_ids": [],
                                    "assessment": "Symptoms alone do not decide it."}], "missing_evidence": ["every record"],
                    "requires_physical_check": False, "summary": "Symptoms only."}
        cls.notools_calls = 0
        # 1. Dry run on the real store: the replay is driven and the cases are read; nothing is investigated.
        wired = wiring.build(cls.config, dry_run=True, selection=cls.selection, agents=cls.agents, notools_turn=notools, driver=cls.driver,
                             allow_reset=True)
        cls.dry = run(cls.root / "pre" / "selection.json", cls.root / "dry", config=cls.config, dry_run=True,
                      **{k: wired[k] for k in ("arms", "case_source", "capture", "extras_arms", "provenance")})
        cls.calls_after_dry = (cls.agents.calls, cls.notools_calls)
        cls.dry_runs = wired["sessions"]["E1"].rows("OpsRun")
        cls.dry_cases = len(wired["sessions"]["E1"].rows("OpsCase"))
        wired["close"]()
        # 2. The run: the session has advanced, so it must be reset explicitly (allow_reset stands for SUHAIL_STAGE3_RESET_SESSION=1).
        try:
            wiring.build(cls.config, selection=cls.selection, agents=cls.agents, notools_turn=notools, driver=cls.driver, allow_reset=False)
            cls.refused_without_reset = False
        except SystemExit:
            cls.refused_without_reset = True
        cls.wired = wiring.build(cls.config, selection=cls.selection, agents=cls.agents, notools_turn=notools, driver=cls.driver, allow_reset=True)
        cls.manifest = run(cls.root / "pre" / "selection.json", cls.root / "run", config=cls.config, extras_path=cls.root / "pre" / "extras.json",
                           **{k: cls.wired[k] for k in ("arms", "case_source", "capture", "extras_arms", "provenance")})
        cls.session = cls.wired["sessions"]["E1"]

    @classmethod
    def tearDownClass(cls):
        cls.wired["close"]()
        cls.patcher.stop()
        cls.directory.cleanup()

    def rows(self, relative):
        path = self.root / "run" / relative
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []

    def test_the_dry_run_drives_the_replay_and_investigates_nothing(self):
        self.assertEqual(self.calls_after_dry, (0, 0))
        self.assertEqual(self.dry_runs, [])
        self.assertGreater(self.dry_cases, 0)
        self.assertEqual((self.dry["ledger"]["settled_calls"], self.dry["dry_run"]), (0, True))
        self.assertEqual(self.dry["provenance"]["model"], "scripted (test)")
        self.assertTrue(self.dry["provenance"]["worlds"]["E1"]["session_reset"])
        self.assertTrue(self.refused_without_reset)

    def test_selected_cases_open_in_the_run_and_only_they_are_investigated(self):
        manifest, selected = self.manifest, self.selection["cases"]
        self.assertTrue(selected)
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["counts"]["arm_errors"], 0)
        cases = {c["key"]: c for c in self.rows("cases.jsonl")}
        opened = [row for row in selected if row["key"] in cases]
        # The replica that made the selection and the store's monitor agree on which shipments open.
        self.assertEqual(manifest["counts"]["not_opened"], len(selected) - len(opened))
        self.assertGreaterEqual(len(opened), 0.9 * len(selected), (len(opened), len(selected)))
        runs = self.session.rows("OpsRun")
        investigated = {r["case_id"] for r in runs}
        self.assertEqual(investigated, {cases[row["key"]]["case_id"] for row in opened})
        self.assertGreater(len(self.session.rows("OpsCase")), len(investigated) - 1)
        for row in opened:
            case = cases[row["key"]]
            replica = self.replay[row["shipment_id"]]
            self.assertEqual(sorted(case["symptoms"]), sorted(replica["opening_symptoms"]), row["key"])
            self.assertEqual(sorted(case["rule_codes"]), sorted(replica["opening_codes"]), row["key"])
            self.assertTrue(case["opening_evidence_ids"], row["key"])
            # Opened within the horizon of the replica's expected opening.
            self.assertLessEqual(instant(case["as_of"]), instant(row["expected_opened_at"]) + timedelta(hours=wiring.OPEN_HORIZON_HOURS))

    def test_the_agent_arm_reads_the_run_record_back_and_the_ledger_holds_the_stores_own_count(self):
        agent = [r for r in self.rows("results/main/agent.jsonl") if r["not_run"] is None]
        self.assertTrue(agent)
        runs = {r["case_id"]: json.loads(r["result_json"]) for r in self.session.rows("OpsRun")}
        for row in agent:
            log = runs[row["case_id"]]["investigation_log"]
            self.assertEqual((row["calls_used"], row["as_of"]), (log["model_calls_used"], log["snapshot_as_of"]))
            self.assertLessEqual(row["calls_used"], 12)
            self.assertEqual(row["primary_cause"], "INSUFFICIENT_EVIDENCE")
            self.assertTrue(row["steps"] and row["retrieved_ids"])
            self.assertEqual(len(row["tool_seconds"]), len(row["steps"]))
        extras = [r for name in ("cross_shipment_ablation", "stability_rerun") for r in self.rows(f"results/extras/{name}.jsonl")]
        ledger = self.manifest["ledger"]
        self.assertEqual(ledger["calls_by_arm"].get("agent", 0), sum(r["calls_used"] for r in agent))
        self.assertEqual(ledger["settled_calls"], self.agents.calls + self.notools_calls)   # every scripted model call, and no other
        self.assertLessEqual(ledger["committed_calls"], self.config.budget)
        # The no-tools arm answered at the agent's snapshot.
        by_key = {r["case_key"]: r for r in agent}
        for row in self.rows("results/main/notools.jsonl"):
            if row["case_key"] in by_key and row["not_run"] is None:
                self.assertEqual(row["as_of"], by_key[row["case_key"]]["as_of"])
        # Extras: as of the main snapshot, nothing recorded for them (one OpsRun per investigated case).
        self.assertEqual(len(self.session.rows("OpsRun")), len(agent))
        from operations.tools import CROSS_SHIPMENT_TOOLS
        for row in extras:
            self.assertEqual(row["as_of"], by_key[row["case_key"]]["as_of"])
            if row["arm"] == "cross_shipment_ablation":
                self.assertFalse({s["tool"] for s in row["steps"]} & set(CROSS_SHIPMENT_TOOLS))

    def test_the_five_surfaces_are_captured_and_the_provenance_names_the_run(self):
        captured = self.root / "run" / "captured"
        for surface in ("tools", "api", "receipts", "graph", "logs", "tool_index"):
            self.assertTrue(any(captured.joinpath(surface).iterdir()), surface)
        graph = self.rows("captured/graph/run.jsonl")
        nodes = sum(len(item.get("nodes") or []) for item in graph)
        with self.driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
            self.assertEqual(nodes, session.run("MATCH (n) RETURN count(n) AS n").single()["n"])
            self.assertEqual(sum(len(item.get("relationships") or []) for item in graph),
                             session.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"])
        provenance = self.manifest["provenance"]
        world = provenance["worlds"]["E1"]
        self.assertEqual((world["database"], world["execution_adapter"], world["per_case_model_call_cap"]), (TEST_DATABASE, "none", 12))
        self.assertEqual(world["session_id"], self.session.store.status()["session"]["session_id"])
        self.assertEqual((provenance["truth_environment_set"], provenance["wiring"]), ([], "chat/scripts/stage3_wiring.py"))
        self.assertGreater(world["replay"]["ingested"], 0)

    def test_score_and_report(self):
        from stage3_eval.canary import TruthScanner
        from stage3_eval.report import build_report, render_markdown
        from stage3_eval.scoring import score_run
        from stage3_eval.truth_io import truth_vocabulary
        scorer = wiring.build_scorer(self.config, run_dir=self.root / "run", driver=self.driver)
        agent = [r for r in self.rows("results/main/agent.jsonl") if r["not_run"] is None]
        # The ingestion log is the run's: what a tool showed at t was ingested by t, and nothing later was.
        for row in agent[:5]:
            held = scorer["ingestion"].ingested("E1", row["as_of"])
            own = [i for i in row["retrieved_ids"] if i in self.fixture.world.nodes]
            self.assertTrue(own)
            self.assertTrue(set(own) <= held, row["case_key"])
            resolved = scorer["resolver"].recorded_at("E1", row["retrieved_ids"])
            self.assertEqual(sorted(resolved), sorted(row["retrieved_ids"]), row["case_key"])    # every id a tool listed resolves
            self.assertTrue(all(instant(at) <= instant(row["as_of"]) for at in resolved.values()), row["case_key"])
        self.assertEqual(scorer["resolver"].recorded_at("E1", ["DEMO-INVENTED-ID"]), {})
        self.assertLess(len(scorer["ingestion"].ingested("E1", agent[0]["as_of"])), len(scorer["ingestion"].ingested("E1", "2100-01-01T00:00:00+00:00")))
        scores = score_run(self.root / "run", self.scored_selection, self.truth, ingestion=scorer["ingestion"], resolver=scorer["resolver"])
        main = [s for s in scores if s["phase"] == "main"]
        self.assertEqual(len(main), 4 * len(self.selection["cases"]))
        scored_agent = [s for s in main if s["arm"] == "agent" and s["category"] != "degraded"]
        self.assertTrue(scored_agent)
        # The scripted model always abstains with valid citations: never unsafe, and either honest or wrongly uncertain.
        self.assertEqual({s["category"] for s in scored_agent} - {"honest_uncertainty", "insufficient_when_knowable"}, set())
        canary = TruthScanner(truth_vocabulary(self.truth["E1"])).scan_run(self.root / "run")
        self.assertEqual((canary["verdict"], canary["missing_surfaces"]), ("clean", []), canary.get("hit_locations"))
        report = build_report(self.scored_selection, scores=scores, run_manifest=self.manifest, canary=canary,
                              pairs=json.loads((self.root / "pre" / "pairs.json").read_text(encoding="utf-8")))
        self.assertNotIn("canary", " ".join(report["validity"].get("reasons") or []))
        self.assertIn("Arms side by side", render_markdown(report))
        # A scorer built after the session is reset again refuses: the ingestion times would not be this run's.
        manifest_path = self.root / "run" / "run_manifest.json"
        changed = json.loads(manifest_path.read_text(encoding="utf-8"))
        changed["provenance"]["worlds"]["E1"]["session_id"] = "DEMO-OTHER-SESSION"
        other = self.root / "other"
        other.mkdir(exist_ok=True)
        (other / "run_manifest.json").write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "reset after the run"):
            wiring.build_scorer(self.config, run_dir=other, driver=self.driver)


if __name__ == "__main__":
    unittest.main()
