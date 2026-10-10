"""scripts/world_pilot.py and scripts/world_pilot_score.py (no model calls anywhere).

Without a database: the pilot's refusals, its time-check comparison and the scorer's verdicts.

Opt-in, against local Neo4j (SUHAIL_NEO4J_TESTS=1, scratch database from SUHAIL_TEST_DATABASE): a small mechanism
world is imported into the scratch database, the pilot replays its feed with a scripted investigator that calls
every cross-shipment tool, and then
- every tool call's fixed Cypher ran on the server without a failure, and its citations are valid;
- the run record comes back from reader.case_detail;
- the time-correct check passes;
- every query of operations.cross_shipment returns the same rows from Neo4j as from the in-memory reference;
- the scorer, run on the pilot's results with the fixture's truth rows, gives each case a verdict.
"""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

from dataset_v2.contracts import digest, instant
from operations import investigator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import world_pilot            # noqa: E402
import world_pilot_score      # noqa: E402

TEST_DATABASE = os.environ.get("SUHAIL_TEST_DATABASE", "shipments-v2-demo-ci-test")
SCRATCH = ("shipments-v2-demo-test", "shipments-v2-demo-test2", "shipments-v2-demo-ci-test")


class PlanAgents:
    """A scripted investigator over the real loop and tools: it reads the overview, calls the tools for every shared
    reference the overview names, and concludes INSUFFICIENT_EVIDENCE citing what it retrieved. The reviewer accepts."""

    def __init__(self):
        self.calls = 0

    @staticmethod
    def _results(messages):
        return [m["content"] for m in messages if m["role"] == "user" and m["content"].startswith("TOOL RESULT ")]

    def _turn(self, messages):
        self.calls += 1
        results = self._results(messages)
        if not results:
            return {"action": "call", "tool": "shipment_overview", "args": {}, "purpose": "Start."}
        overview = json.loads(results[0].split(": ", 1)[1].rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[0])
        refs = overview["references_in_this_shipments_records"]
        plan = [("journey", {})]
        if refs["route_run_ids"]:
            plan.append(("same_route_run", {"route_run_id": refs["route_run_ids"][0]}))
        if refs["container_ids"] or refs["trip_ids"]:
            plan.append(("container_and_trip", {**({"container_id": refs["container_ids"][0]} if refs["container_ids"] else {}),
                                                **({"trip_id": refs["trip_ids"][0]} if refs["trip_ids"] else {})}))
        if refs["facility_ids"]:
            plan.append(("facility_window", {"facility_id": refs["facility_ids"][0], "hours": 24}))
        if refs["device_ids"]:
            plan.append(("same_device_activity", {"device_id": refs["device_ids"][0], "hours": 24}))
        plan += [("communications", {}), ("route_conditions", {})]
        done = len(results) - 1
        if done < len(plan):
            tool, args = plan[done]
            return {"action": "call", "tool": tool, "args": args, "purpose": "Inspect."}
        cited = []
        for text in results:
            for key in json.loads(text.rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[1])[:2]:
                if key not in cited:
                    cited.append(key)
        return {"action": "conclude", "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low",
                "missing_evidence": ["the record that would tell the remaining explanations apart"],
                "next_evidence_step": "Ask the facility for its scan log of the parcel.",
                "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False,
                "summary": "The retrieved records do not establish a cause.",
                "hypotheses": [{"cause": "INSUFFICIENT_EVIDENCE", "status": "uncertain", "supporting_evidence_ids": cited[:8],
                                "contradicting_evidence_ids": [], "assessment": "Nothing retrieved separates the explanations."},
                               {"cause": "DELAYED_SYNC", "status": "uncertain", "supporting_evidence_ids": [],
                                "contradicting_evidence_ids": cited[8:10], "assessment": "The device records do not show it."}]}

    def _ask(self, system, user, default):
        self.calls += 1
        return {"verdict": "ACCEPT", "feedback": "The cited records do not establish a cause.", "unsupported_claims": [],
                "unaddressed_contradictions": [], "alternatives_tested": "yes"}

    def investigate(self, tools, *, turn=None, on_step=None, feedback=None, session=None, review=None):
        return investigator.investigate(tools, turn=self._turn, on_step=on_step, feedback=feedback, session=session, review=review)

    def review(self, conclusion, records, checks, symptoms, *, ask=None, context=None, session=None):
        return investigator.review(conclusion, records, checks, symptoms, ask=self._ask, context=context, session=session)


class PilotGuardTests(unittest.TestCase):
    def test_the_pilot_refuses_to_run_when_a_truth_path_is_set_and_never_imports_truth(self):
        clean = {k: v for k, v in os.environ.items() if "TRUTH" not in k.upper() and k != "SUHAIL_SIM_STATE_ROOT"}
        with mock.patch.dict(os.environ, clean, clear=True):
            self.assertEqual(world_pilot.truth_environment(), [])
            world_pilot.refuse_truth_access()
        for name in ("SUHAIL_EVAL_TRUTH_ROOT", "SUHAIL_SIM_STATE_ROOT", "MY_TRUTH_DIR"):
            with mock.patch.dict(os.environ, {**clean, name: r"C:\somewhere"}, clear=True):
                self.assertEqual(world_pilot.truth_environment(), [name])
                with self.assertRaises(SystemExit):
                    world_pilot.refuse_truth_access()
                with self.assertRaises(SystemExit):   # The command refuses before it touches git, Neo4j or a model.
                    world_pilot.main(["--out", "never-written.json"])
        source = (Path(world_pilot.__file__)).read_text(encoding="utf-8")
        for forbidden in ("import world.truth", "from world.truth", "from world import truth", "suhail-eval-truth", "suhail-sim-state",
                          "read_truth", "labels_at(", "state_directory", "truth_directory"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("ask_json", source)             # No model call of its own: only store.process_one makes them.
        self.assertNotIn("model_turn", source)

    def test_only_world_data_in_a_world_or_scratch_database(self):
        class NoDriver:
            def session(self, **options):
                raise AssertionError("refused before any query")
        for database in ("shipments-v2-demo-live", "shipments-v2-demo", "neo4j", "shipments", "shipments-v2-demo-ui"):
            with self.assertRaises(SystemExit):
                world_pilot.open_store(NoDriver(), database, investigator)

    def test_the_time_check_compares_rows_and_dates(self):
        at = instant("2026-09-14T21:00:00+00:00")
        first = {"world_traversals": {"same_trip": {"rows": {"shipments": 3}, "latest_recorded_at": "2026-09-14T20:00:00+00:00"}},
                 "tool_queries": {"trip_events": {"rows": 2, "digest": "a", "latest_timestamp": "2026-09-14T20:30:00+00:00"},
                                  "trip_positions": {"rows": 0, "digest": "e", "latest_timestamp": None}}}
        same = json.loads(json.dumps(first))
        common = dict(clock_at_first="2026-09-14T21:00:00+00:00", clock_at_second="2026-09-15T03:00:00+00:00", targets={})
        result = world_pilot.compare_time_check(at, first, same, **common)
        self.assertTrue(result["pass"])
        self.assertEqual((result["queries_run"], result["queries_returning_rows"]), (3, 2))
        grown = json.loads(json.dumps(first))
        grown["tool_queries"]["trip_events"] = {"rows": 3, "digest": "b", "latest_timestamp": "2026-09-14T23:00:00+00:00"}
        result = world_pilot.compare_time_check(at, first, grown, **common)
        self.assertFalse(result["pass"])
        self.assertEqual(result["queries_whose_rows_differ"], ["tool_queries.trip_events"])
        self.assertEqual(result["queries_returning_a_record_from_after_as_of"], {"tool_queries.trip_events": "2026-09-14T23:00:00+00:00"})
        # No later ingestion to compare against is not a pass.
        self.assertFalse(world_pilot.compare_time_check(at, first, same, clock_at_first=common["clock_at_first"],
                                                        clock_at_second=common["clock_at_first"], targets={})["pass"])


class ScoreTests(unittest.TestCase):
    """Verdicts from a truth row, an investigation snapshot and the ids ingested by then."""

    def row(self, healthy=False):
        def mechanism(cause, record, acceptable=()):
            return {"cause_code": cause, "acceptable_causes": [cause, *acceptable], "resolution": "AUTO", "type": "X",
                    "discrimination": {"any_of": [{"all_of": [{"record": record}]}]}}
        return {"shipment_id": "DEMO-SHP-1", "healthy": healthy,
                "mechanisms": [] if healthy else [mechanism("HUB_DELAY", "DEMO-R1", ("JOURNEY_DELAY",)), mechanism("DELAYED_SYNC", "DEMO-R2")]}

    def case(self, primary, supported=()):
        return {"case_id": "C", "shipment_id": "DEMO-SHP-1", "snapshot_as_of": "2026-09-15T00:00:00+00:00", "primary_cause": primary,
                "hypotheses": [{"cause": c, "status": "supported"} for c in ([primary] if primary else []) + list(supported)]}

    def verdict(self, primary, ingested, healthy=False, supported=()):
        return world_pilot_score.score_case(self.case(primary, supported), self.row(healthy), set(ingested))

    def test_verdicts(self):
        self.assertEqual(world_pilot_score.spec_records(self.row()), {"DEMO-R1", "DEMO-R2"})
        scored = self.verdict("HUB_DELAY", {"DEMO-R1"})
        self.assertEqual((scored["verdict"], scored["knowable_causes"]), ("correct", ["HUB_DELAY"]))
        self.assertEqual(self.verdict("JOURNEY_DELAY", {"DEMO-R1"})["verdict"], "correct")            # Listed as acceptable for that mechanism.
        self.assertEqual(self.verdict("DELAYED_SYNC", {"DEMO-R1"})["verdict"], "incorrect")           # Not knowable yet.
        self.assertTrue(self.verdict("DELAYED_SYNC", {"DEMO-R1"})["primary_is_an_eventual_cause"])
        self.assertEqual(self.verdict("INSUFFICIENT_EVIDENCE", {"DEMO-R1"})["verdict"], "wrongly uncertain")
        nothing = self.verdict("INSUFFICIENT_EVIDENCE", set())
        self.assertEqual((nothing["verdict"], nothing["knowable_causes"]), ("appropriately uncertain", ["INSUFFICIENT_EVIDENCE"]))
        self.assertEqual(self.verdict("HUB_DELAY", set())["verdict"], "incorrect")                    # A guess before it is knowable.
        self.assertEqual(self.verdict(None, {"DEMO-R1"})["verdict"], "no valid conclusion")
        self.assertEqual(self.verdict("INSUFFICIENT_EVIDENCE", set(), healthy=True)["verdict"], "appropriately uncertain")
        self.assertEqual(self.verdict("HUB_DELAY", set(), healthy=True)["verdict"], "incorrect")
        both = self.verdict("HUB_DELAY", {"DEMO-R1", "DEMO-R2"}, supported=("DELAYED_SYNC", "WRONG_GATE"))
        self.assertEqual((both["knowable_causes_named"], both["supported_causes_not_knowable"]), (["DELAYED_SYNC", "HUB_DELAY"], ["WRONG_GATE"]))

    def test_the_scorer_is_a_separate_program_from_the_pilot(self):
        pilot = Path(world_pilot.__file__).read_text(encoding="utf-8")
        self.assertNotIn("world_pilot_score", pilot.replace("(world_pilot_score.py)", ""))
        scorer = Path(world_pilot_score.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import world_pilot\n", scorer)
        self.assertNotIn("process_one", scorer)           # It investigates nothing and calls no model.
        self.assertNotIn("litellm", scorer)


def build_world_database(database):
    """Import the fixture's mechanism world into a scratch database (recreated) with its feed pending."""
    import config
    from core.query_runner import get_driver
    from dataset_v2.live_bundle import load_feed
    from dataset_v2.load import Bundle, apply_bundle
    from tests.world_fixture import small_world
    from world.export import create_indexes
    assert database in SCRATCH
    fixture = small_world()
    driver = get_driver()
    with driver.session(database="system") as session:
        session.run(f"CREATE OR REPLACE DATABASE `{database}` WAIT 60 SECONDS").consume()
    manifest = fixture.imported.manifest()
    bundle = Bundle(fixture.imported, manifest, digest(manifest), {})
    report = apply_bundle(driver, bundle, uri=config.NEO4J_URI, database=database,
                          protected=(config.SHIPMENT_DATABASE, config.NEO4J_DATABASE, config.CHAT_DATABASE))
    assert report["status"] == "imported", report
    load_feed(driver, database, bundle, fixture.items)
    create_indexes(driver, database)
    return driver, fixture


GATEWAY_ENVELOPE = ("channel", "feed_id", "feed_origin", "ingest_lag_seconds", "ingested_at", "provider_id", "raw_payload_hash")


def comparable(rows):
    """Rows as a sorted list of canonical texts, with every time value in one spelling."""
    def norm(value):
        if isinstance(value, dict):
            # A record's content: without the loader's internal properties (_v2_record_hash) and the envelope the gateway
            # adds to a fed record. Every other property must be equal.
            return {k: norm(v) for k, v in value.items() if v is not None and not k.startswith("_") and k not in GATEWAY_ENVELOPE}
        if isinstance(value, list):
            return [norm(v) for v in value]
        if hasattr(value, "isoformat"):
            return instant(value.isoformat()).isoformat()
        if isinstance(value, str) and len(value) >= 20 and value[4:5] == "-" and "T" in value[:11]:
            try:
                return instant(value).isoformat()
            except ValueError:
                return value
        return value
    return sorted(json.dumps(norm(row), sort_keys=True, default=str) for row in rows)


@unittest.skipUnless(os.environ.get("SUHAIL_NEO4J_TESTS") == "1", "set SUHAIL_NEO4J_TESTS=1 to run against local Neo4j")
class WorldPilotNeo4jTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert TEST_DATABASE in SCRATCH
        cls.driver, cls.fixture = build_world_database(TEST_DATABASE)
        cls.agents = PlanAgents()
        cls.lines = []
        cls.result = world_pilot.run_pilot(cls.driver, TEST_DATABASE, agents=cls.agents, per_alert=2, max_cases=4, max_calls=38,
                                           check_after_hours=6, calls_used=lambda: cls.agents.calls, log=cls.lines.append)
        cls.result = json.loads(json.dumps(cls.result, default=world_pilot._iso))   # As the results file holds it.

    def test_cases_open_from_ingested_evidence_and_are_investigated_within_the_budget(self):
        result = self.result
        replay = result["replay"]
        self.assertEqual(result["settings"]["execution_adapter"], "none")
        self.assertEqual(replay["rejected"], 0)
        self.assertGreaterEqual(replay["cases_opened"], len(result["cases"]))
        self.assertTrue(result["cases"])
        # A case is not started when fewer calls than the per-case cap remain: 38 calls cover at most three ten-call cases.
        self.assertLessEqual(len(result["cases"]), 3)
        self.assertLessEqual(replay["model_calls_counted"], 38)
        self.assertEqual(replay["model_calls_by_case_counters"], replay["model_calls_counted"])   # Both counts agree.
        self.assertEqual(replay["model_calls_counted"], sum(case["model_calls_used"] for case in result["cases"]))
        self.assertIn(replay["stop_reason"], ("model_call_budget", "max_cases_reached", "feed_ended"))
        per_set = {}
        for case in result["cases"]:
            key = "+".join(case["opening_symptoms"])
            per_set[key] = per_set.get(key, 0) + 1
            self.assertTrue(case["opening_symptoms"])
            self.assertGreaterEqual(instant(case["snapshot_as_of"]), instant(case["opened_at"]))
            self.assertLessEqual(instant(case["snapshot_as_of"]), instant(replay["clock_at_end"]))
        self.assertLessEqual(max(per_set.values()), 2)

    def test_every_tool_query_ran_on_the_server_and_every_citation_is_valid(self):
        tools_called = set()
        for case in self.result["cases"]:
            self.assertIsNone(case["error"])
            self.assertTrue(case["processed"], case)
            self.assertEqual(len(case["rounds"]), 1)
            for call in case["rounds"][0]["tool_calls"]:
                tools_called.add(call["tool"])
                self.assertIsNone(call["failure"], (case["case_id"], call["tool"], call["args"]))
            self.assertTrue(case["citations"])
            self.assertTrue(all(c["exists"] and c["retrieved_in_this_run"] and c["recorded_at_or_before_snapshot"] and c["valid"]
                                for c in case["citations"]), case["citations"])
            self.assertTrue(case["citations_all_valid"])
            self.assertEqual(case["model_calls_used"], len(case["rounds"][0]["tool_calls"]) + 2)   # Turns, the conclusion, one review.
            self.assertEqual(case["model_calls_used"], case["provider_calls"])
        self.assertTrue({"shipment_overview", "journey", "communications", "route_conditions"} <= tools_called)
        self.assertTrue(tools_called & {"same_device_activity", "facility_window", "same_route_run", "container_and_trip"}, tools_called)

    def test_the_run_record_is_served_and_nothing_resolves_without_a_simulator(self):
        for case in self.result["cases"]:
            self.assertEqual(case["case_detail_returns"], {"diagnosis": True, "review": True, "run": True, "investigation_log": True, "error": None})
            self.assertEqual((case["primary_cause"], case["insufficient_evidence"]), ("INSUFFICIENT_EVIDENCE", True))
            self.assertTrue(case["missing_evidence"] and case["next_evidence_step"])
            self.assertEqual(case["review"]["model_verdict"], "ACCEPT")
            # An insufficient-evidence conclusion never closes by itself; with no adapter nothing is acknowledged.
            self.assertIn(case["authority"]["risk_class"], ("AUTO", "HUMAN_REVIEW"))
            self.assertEqual(case["authority"]["closure"], "HUMAN")
            self.assertTrue(case["authority"]["rule_id"])
            self.assertEqual(case["final_workflow_state"], "HUMAN_REVIEW")
        with self.driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
            states = {r["s"] for r in session.run("MATCH (c:OpsCase) RETURN c.workflow_state AS s")}
            executions = {r["s"] for r in session.run("MATCH (e:OpsExecution) RETURN e.status AS s")}
            outcomes = session.run("MATCH (o:OpsOutcome) RETURN count(o) AS n").single()["n"]
        self.assertNotIn("RESOLVED", states)
        self.assertLessEqual(executions, {"NOT_ACKNOWLEDGED"})
        self.assertEqual(outcomes, 0)

    def test_the_time_correct_check_passes(self):
        check = self.result["time_correct_check"]
        self.assertTrue(check["pass"], {k: check[k] for k in ("queries_whose_rows_differ", "queries_returning_a_record_from_after_as_of",
                                                              "queries_returning_rows", "clock_at_first_pass", "clock_at_second_pass")})
        self.assertGreater(instant(check["clock_at_second_pass"]), instant(check["as_of"]))
        self.assertGreater(check["queries_returning_rows"], 8)

    def test_every_catalogue_query_returns_the_same_rows_from_neo4j_as_from_the_reference(self):
        from operations.cross_shipment import QUERIES
        from operations.datasets import dataset_config
        from operations.read_model import OperationsReader
        from tests.world_fixture import MemoryPort
        check = self.result["time_correct_check"]
        clock = self.result["replay"]["clock_at_end"]
        config = dataset_config(self.fixture.imported.manifest()["config"])
        reader = OperationsReader(self.driver, TEST_DATABASE, config.dataset_id, config, clock=lambda: clock)
        port = MemoryPort(self.fixture.world, clock=lambda: clock)
        seen = set()
        for as_of in (check["as_of"], clock):
            targets = world_pilot.check_targets(self.driver, TEST_DATABASE, config.dataset_id, instant(as_of))
            calls = world_pilot.catalogue_calls(targets, instant(as_of))
            with self.driver.session(database=TEST_DATABASE, default_access_mode="READ") as session:
                barcode = session.run("MATCH (p:Package) RETURN p.manifest_barcode AS b, p.shipment_id AS s ORDER BY p.entity_id LIMIT 1").single()
                shipments = [r["s"] for r in session.run("MATCH (s:Shipment {split:'development'}) RETURN s.entity_id AS s ORDER BY s LIMIT 20")]
            calls += [("package_by_barcode", {"text": barcode["b"]}), ("last_custody", {"shipment_ids": shipments}),
                      ("shared_record", {"ref": targets["trip"]}), ("shared_record", {"ref": targets["device"]})]
            for name, params in calls:
                seen.add(name)
                ours = reader.fetch(name, as_of=as_of, **params)
                reference = port.fetch(name, as_of=as_of, **params)
                self.assertEqual(comparable(ours), comparable(reference), (name, params, as_of))
        self.assertEqual(seen, set(QUERIES))

    def test_the_scorer_gives_each_case_a_verdict_from_the_runs_own_ingestion(self):
        scored = world_pilot_score.score(self.result, self.fixture.truth, self.driver, TEST_DATABASE)
        self.assertEqual(len(scored["cases"]), len(self.result["cases"]))
        for case in scored["cases"]:
            score = case["score"]
            self.assertIn(score["verdict"], world_pilot_score.VERDICTS)
            # The scripted investigator always abstains: right when nothing is knowable yet, wrong when a cause is.
            expected = "appropriately uncertain" if score["knowable_causes"] in ([], ["INSUFFICIENT_EVIDENCE"]) else "wrongly uncertain"
            self.assertEqual(score["verdict"], expected)
            self.assertTrue(score["run_found_in_database"])
        self.assertEqual(sum(scored["summary"]["verdicts"].values()), len(scored["cases"]))


if __name__ == "__main__":
    unittest.main()
