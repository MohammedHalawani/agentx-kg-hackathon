"""Speed changes must not change reasoning: the optimized investigation against the current one, with a scripted model.

The scripted model is reactive: it reads its transcript and asks for the next tool of a recorded pilot sequence (the
tool order GPT-OSS chose in the twelve world-1 pilot investigations, docs/evals/2026-10-10_world1_pilot/README.md),
taking every argument from what the tools showed it, then concludes citing the ids of the latest result. The same
script drives each mode on the same mechanism-world shipments, through the real graph, tools, checks, reviewer
function and authority policy.

  memo      the per-case query memo (operations.tools, memo=True, the default) against reading every query from the
            source each time: the model must receive byte-identical transcripts, and the tool calls, review packets,
            conclusions and authority decisions must be identical, with no more database reads.
  prefetch  shipment_overview fetched before the first model turn (SUHAIL_PREFETCH_OVERVIEW=1): the same tool calls
            with the same results, the same conclusions, review verdicts and authority decisions, one model call fewer.
"""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

from operations import investigator, tools as tools_module
from operations.graph import investigate as run_graph
from tests.test_stage2_investigation import ScriptedAgents, REFERENCES
from tests.world_fixture import small_world

# The pilot's tool sequences, in order; ";" separates the revision round's calls (README of the pilot).
PILOT_SEQUENCES = [
    "shipment_overview scans same_device_activity ;",
    "shipment_overview scans scans scans same_device_activity same_device_activity",
    "shipment_overview custody_chain same_device_activity same_device_activity",
    "shipment_overview custody_chain scans same_device_activity container_and_trip",
    "shipment_overview journey custody_chain delivery_attempts device_status same_device_activity address_and_instructions same_route_run",
    "shipment_overview journey delivery_attempts address_and_instructions custody_chain same_route_run",
    "shipment_overview scans same_device_activity custody_chain ; scans device_status",
    "shipment_overview scans same_device_activity custody_chain custody_chain custody_chain device_status ;",
    "shipment_overview delivery_attempts journey journey custody_chain same_route_run same_route_run ; address_and_instructions",
    "shipment_overview scans scans scans same_device_activity vehicle_and_manifest ;",
    "shipment_overview journey custody_chain same_route_run vehicle_and_manifest delivery_attempts address_and_instructions device_status",
    "shipment_overview custody_chain scans vehicle_and_manifest same_route_run device_status",
]
MEASUREMENT = ("seconds", "queries", "query_seconds", "cached_queries", "model_seconds", "tool_seconds", "elapsed_seconds", "recorded_at")


def rounds_of(sequence):
    first, _, revision = sequence.partition(";")
    return first.split(), (revision.split() if ";" in sequence else None)


def _overview(messages):
    text = next(m["content"] for m in messages if m["content"].startswith("TOOL RESULT shipment_overview"))
    return json.loads(text[len("TOOL RESULT shipment_overview: "):].rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[0])


def arguments(tool, messages, nth):
    """Arguments for the nth call of `tool`, from the ids the overview showed (as the model would take them)."""
    if tool == "shipment_overview":
        return {}
    seen = _overview(messages)
    refs = seen["references_in_this_shipments_records"]
    pick = lambda values: values[nth % len(values)] if values else "DEMO-NONE"
    return {"custody_chain": lambda: {"package_id": pick([p["package_id"] for p in seen["packages"]])},
            "scans": lambda: {"package_id": pick([p["package_id"] for p in seen["packages"]])} if nth else {},
            "journey": lambda: {},
            "same_device_activity": lambda: {"device_id": pick(refs["device_ids"]), "hours": 24},
            "device_status": lambda: {"device_id": pick(refs["device_ids"])},
            "same_route_run": lambda: {"route_run_id": pick(refs["route_run_ids"])},
            "container_and_trip": lambda: {"container_id": pick(refs["container_ids"])} if refs["container_ids"] else {"trip_id": pick(refs["trip_ids"])},
            }.get(tool, lambda: {})()


def scripted_model(sequence, batch=1):
    """A model that follows `sequence` by reading its transcript: the next tool is the one after the results it has
    (with batch > 1, the next `batch` tools in one reply)."""
    first, revision = rounds_of(sequence)

    def turn(messages):
        reviews = [i for i, m in enumerate(messages) if m["role"] == "user" and m["content"].startswith("REVIEW OF YOUR CONCLUSION")]
        plan, start = (revision, reviews[-1]) if reviews else (first, 0)
        done = [m for m in messages[start:] if m["role"] == "user" and m["content"].startswith("TOOL RESULT")]
        if len(done) < len(plan):
            calls = []
            for tool in plan[len(done):len(done) + batch]:
                nth = sum(1 for m in messages if m["content"].startswith(f"TOOL RESULT {tool}:")) + sum(c["tool"] == tool for c in calls)
                calls.append({"tool": tool, "args": arguments(tool, messages, nth), "purpose": "Next step of the recorded sequence."})
            return {"action": "call", **calls[0]} if batch == 1 else {"action": "call", "calls": calls}
        result = next(m["content"] for m in reversed(messages) if m["content"].startswith("TOOL RESULT"))
        ids = json.loads(result.rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[1])[:3]
        other = json.loads(next(m["content"] for m in messages if m["content"].startswith("TOOL RESULT")).rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[1])[:1]
        return {"action": "conclude", "primary_cause": "CUSTODY_GAP", "confidence": "medium", "missing_evidence": [], "next_evidence_step": "",
                "recommended_action": "INITIATE_CUSTODY_RECONCILIATION", "requires_physical_check": False,
                "summary": "As the cited records show.",
                "hypotheses": [{"cause": "CUSTODY_GAP", "status": "supported", "supporting_evidence_ids": ids, "contradicting_evidence_ids": [],
                                "assessment": "As the cited records show."},
                               {"cause": "DELAYED_SYNC", "status": "refuted", "supporting_evidence_ids": [], "contradicting_evidence_ids": other,
                                "assessment": "The cited record does not show it."}]}
    turn.seen = []

    def recorded(messages):
        turn.seen.append([dict(m) for m in messages])
        return turn(messages)
    recorded.seen = turn.seen
    return recorded


def review_script(sequence):
    _, revision = rounds_of(sequence)
    accept = {"verdict": "ACCEPT", "feedback": "Supported.", "unsupported_claims": [], "unaddressed_contradictions": [], "alternatives_tested": "yes"}
    revise = {**accept, "verdict": "REVISE", "feedback": "Test one more alternative.", "alternatives_tested": "no"}
    return [revise, accept] if revision is not None else [accept]


def strip(value):
    """The run record without its timing fields."""
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in MEASUREMENT and k != "latency"}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


class Equivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = small_world()
        world, reader = cls.fixture.world, cls.fixture.reader
        cls.end = world.config.as_of
        chosen = []
        for shipment in sorted((n for n in world.of_kind("Shipment") if n.properties.get("split") == "development"), key=lambda n: n.id):
            fields = {f for node in reader.owned[shipment.id] for f in REFERENCES if isinstance(node.properties.get(f), str)}
            if {"device_ref", "route_run_id"} <= fields:
                chosen.append(shipment.id)
        cls.shipments = chosen[:len(PILOT_SEQUENCES)]
        assert len(cls.shipments) == len(PILOT_SEQUENCES), "the fixture world has too few shipments with shared references"

    def run_case(self, sid, sequence, *, memo=True, prefetch=False, batch=1):
        reader = self.fixture.reader
        reads = {"n": 0}

        def counted(name, **params):
            reads["n"] += 1
            return reader.fetch(name, **params)
        model = scripted_model(sequence, batch)
        agents = ScriptedAgents([model] * 40, review_script(sequence))
        original = tools_module.InvestigationTools.__init__

        def init(self_, *args, **kwargs):
            original(self_, *args, **{**kwargs, "memo": memo})
        env = {investigator.PREFETCH_ENV: "1" if prefetch else "0", investigator.BATCH_ENV: str(batch)}
        with mock.patch.object(tools_module.InvestigationTools, "__init__", init), mock.patch.dict("os.environ", env):
            context = reader.evidence(sid, self.end)
            analysis, _ = run_graph(sid, context["as_of"], self.fixture.world.config, lambda *_: context, lambda *_: [],
                                    agents=agents, live_session=True, symptoms=["MILESTONE_OVERDUE"],
                                    heartbeats=reader.heartbeats, port=counted, call_cap=20)
        return analysis, model.seen, agents.review_packets, reads["n"]

    def test_query_memo_changes_nothing_the_model_or_the_reviewer_sees(self):
        saved = 0
        for sid, sequence in zip(self.shipments, PILOT_SEQUENCES):
            with self.subTest(shipment=sid, sequence=sequence):
                a, seen_a, reviews_a, reads_a = self.run_case(sid, sequence, memo=False)
                b, seen_b, reviews_b, reads_b = self.run_case(sid, sequence, memo=True)
                self.assertEqual(seen_a, seen_b)                       # byte-identical transcripts, every model call
                self.assertEqual(reviews_a, reviews_b)                 # the reviewer's packets
                self.assertEqual(strip(a), strip(b))                   # conclusions, checks, review, authority, the log
                self.assertLessEqual(reads_b, reads_a)
                self.assertEqual(b["latency"]["tools"]["queries"] + b["latency"]["tools"]["cached_queries"],
                                 a["latency"]["tools"]["queries"])
                saved += reads_a - reads_b
        self.assertGreater(saved, 0)                                   # the sequences repeat some reads

    def test_overview_prefetch_keeps_the_calls_results_and_decisions_and_saves_one_model_call(self):
        for sid, sequence in zip(self.shipments, PILOT_SEQUENCES):
            with self.subTest(shipment=sid, sequence=sequence):
                a, seen_a, _, _ = self.run_case(sid, sequence)
                c, seen_c, _, _ = self.run_case(sid, sequence, prefetch=True)
                calls = lambda run: [(r["round"], *(x[k] for k in ("tool", "args", "evidence_ids", "computed_ids", "omitted_rows", "failure")))
                                     for r in run["investigation_log"]["rounds"] for x in r["tool_calls"]]
                self.assertEqual(calls(a), calls(c))
                results = lambda seen: [m["content"] for m in seen[-1] if m["content"].startswith("TOOL RESULT")]
                self.assertEqual(results(seen_a), results(seen_c))     # the model read the same evidence, in the same order
                for key in ("primary_cause", "hypotheses", "recommended_action", "confidence"):
                    self.assertEqual(a["investigation"][key], c["investigation"][key])
                self.assertEqual([t["review"]["verdict"] for t in a["trace"]], [t["review"]["verdict"] for t in c["trace"]])
                self.assertEqual(strip(a["authority"]), strip(c["authority"]))
                self.assertEqual(strip(a["result"]), strip(c["result"]))
                self.assertEqual(c["latency"]["model"]["calls"], a["latency"]["model"]["calls"] - 1)
                first = c["investigation"]["steps"][0]
                self.assertEqual((first["tool"], first["chosen_by"]), ("shipment_overview", "prefetch"))

    def test_several_tools_per_reply_read_the_same_evidence_reach_the_same_decisions_in_fewer_calls(self):
        for sid, sequence in zip(self.shipments, PILOT_SEQUENCES):
            with self.subTest(shipment=sid, sequence=sequence):
                a, seen_a, _, _ = self.run_case(sid, sequence)
                c, seen_c, _, _ = self.run_case(sid, sequence, prefetch=True, batch=3)
                calls = lambda run: [(r["round"], *(x[k] for k in ("tool", "args", "evidence_ids", "computed_ids", "omitted_rows", "failure")))
                                     for r in run["investigation_log"]["rounds"] for x in r["tool_calls"]]
                self.assertEqual(calls(a), calls(c))
                results = lambda seen: [m["content"] for m in seen[-1] if m["content"].startswith("TOOL RESULT")]
                self.assertEqual(results(seen_a), results(seen_c))
                for key in ("primary_cause", "hypotheses", "recommended_action", "confidence"):
                    self.assertEqual(a["investigation"][key], c["investigation"][key])
                self.assertEqual([t["review"]["verdict"] for t in a["trace"]], [t["review"]["verdict"] for t in c["trace"]])
                self.assertEqual(strip(a["authority"]), strip(c["authority"]))
                self.assertLess(c["latency"]["model"]["calls"], a["latency"]["model"]["calls"])
                system = seen_c[0][0]["content"]
                self.assertIn("ask for every tool (up to 3)", system)
                # The list is the only call shape offered, and the prefetched call is written in it, so the model's own
                # first reply has no single-call example to copy (on eight demo cases it kept to one tool per reply).
                self.assertIn('{"action":"call","calls":[', system)
                self.assertNotIn('{"action":"call","tool":', system)
                self.assertEqual(json.loads(seen_c[0][2]["content"])["calls"][0]["tool"], "shipment_overview")

    def test_with_the_options_off_the_instructions_and_packet_are_the_evaluated_ones(self):
        self.assertEqual(investigator.system_prompt(1), investigator.SYSTEM)
        _, seen, _, _ = self.run_case(self.shipments[0], PILOT_SEQUENCES[0])
        self.assertEqual(seen[0][0]["content"], investigator.SYSTEM)
        self.assertNotIn("max_tool_calls_per_reply", seen[0][1]["content"])
        self.assertFalse(any(m["content"].startswith("TOOL RESULT") for m in seen[0]))   # nothing fetched before the first turn

    def test_an_unusable_reply_records_why_without_its_text(self):
        from tests.test_investigator import scripted
        from operations.tools import InvestigationTools
        sid = self.shipments[0]
        context = self.fixture.reader.evidence(sid, self.end)
        tools = InvestigationTools(context, self.fixture.world.config, symptoms=["MILESTONE_OVERDUE"], port=self.fixture.reader.fetch)
        session = investigator.Session(6)
        investigator.investigate(tools, session=session, turn=scripted(None, {"action": "calls"}, {"hypotheses": []},
                                                                       {"action": "call", "tool": "journey", "args": {}}, None, None))
        kinds = [t.get("invalid_kind") for t in session.turns if t["outcome"] == "invalid"]
        self.assertEqual(kinds[:3], ["not_an_object", "action:calls", "no_action"])
        from operations import latency
        for text, kind in (("", "empty"), ("I will check the scans.", "no_json_object"), ('{"action": "conclude", "hypotheses": [}', "json_error")):
            latency.note_reply(text, None)
            self.assertEqual(latency.take_reply(), kind)


class LatencyRecord(unittest.TestCase):
    def test_every_run_records_where_its_time_went(self):
        fixture = small_world()
        case = Equivalence()
        case.fixture, case.end = fixture, fixture.world.config.as_of
        sid = next(n.id for n in sorted(fixture.world.of_kind("Shipment"), key=lambda n: n.id)
                   if n.properties.get("split") == "development" and fixture.reader.owned[n.id])
        analysis, seen, _, _ = case.run_case(sid, PILOT_SEQUENCES[6])
        latency = analysis["latency"]
        self.assertEqual(latency["schema"], "latency-1")
        self.assertEqual(latency["model"]["calls"], len(seen) + 2)    # every investigator turn plus the two reviews
        self.assertEqual(latency["model"]["by_role"]["reviewer"]["calls"], 2)
        self.assertEqual(latency["tools"]["calls"], 6)
        self.assertLessEqual(latency["first_conclusion_seconds"], latency["first_review_seconds"])
        self.assertLessEqual(latency["first_review_seconds"], latency["final_seconds"])
        self.assertTrue(all("elapsed_seconds" in e for e in analysis["pipeline_events"]))
        self.assertEqual(latency["model"]["calls"], analysis["investigation_log"]["model_calls_used"])


class AnalysisScript(unittest.TestCase):
    """scripts/investigation_latency.py on the committed pilot records and on a run's own events (the ledger path)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        import investigation_latency
        cls.script = investigation_latency

    def test_pilot_records_give_the_committed_wall_times_and_estimate_only_the_first_conclusion(self):
        path = Path(__file__).resolve().parents[2] / "docs/evals/2026-10-10_world1_pilot/pilot.json"
        runs = [self.script.from_record(r) for r in self.script.load_records(path)]
        self.assertEqual(len(runs), 12)
        summary = self.script.summarize(runs)
        self.assertEqual(summary["all"]["wall_seconds"]["worst"], 62.7)
        self.assertEqual(summary["all"]["first_conclusion_is"], "estimated")
        self.assertEqual({r["kind"] for r in runs}, {"ordinary", "complex"})

    def test_a_stage3_result_line_is_read_as_well(self):
        from stage3_eval.records import ArmResult
        line = ArmResult(case_key="k", arm="agent", shipment_id="DEMO-SHP-1", wall_seconds=30.0, calls_used=8, review_rounds=1,
                         steps=[{"tool": "scans"}]).to_dict()
        run = self.script.from_record(line)
        self.assertEqual((run["wall_seconds"], run["calls"], run["kind"], run["tool_calls"]), (30.0, 8, "ordinary", 1))
        self.assertEqual(run["first_conclusion"], "estimated")

    def test_the_ledger_path_measures_from_the_run_events(self):
        fixture = small_world()
        case = Equivalence()
        case.fixture, case.end = fixture, fixture.world.config.as_of
        Equivalence.setUpClass()
        analysis, _, _, _ = case.run_case(Equivalence.shipments[0], PILOT_SEQUENCES[0])
        run = self.script.from_run("C", "S", analysis, [])
        self.assertEqual(run["kind"], "complex")
        self.assertEqual(run["tool_calls"], 3)
        self.assertIsNotNone(run["first_conclusion_seconds"])
        self.assertLessEqual(run["first_conclusion_seconds"], run["final_seconds"])
        self.assertIsNone(run["queue_seconds"])          # no audits given


if __name__ == "__main__":
    unittest.main()
