"""Stage 2: the investigation as the evaluation harness and the pilot will drive it (scripted model; no provider,
no database).

- the cross-shipment tools over a mechanism world (through the in-memory reference port): citable ids, computed
  results, time-correct at a mid-feed snapshot, disabled tools;
- one model-call budget for the whole case investigation; a revision round keeps the conversation and records;
- what the reviewer receives; deterministic citation validity;
- INSUFFICIENT_EVIDENCE from the investigator or the reviewer never acts or closes automatically;
- the run record a store persists and case_detail serves (docs/api/investigation-run.md).
"""
import json
import unittest

from dataset_v2.contracts import Config, instant
from dataset_v2.generate import generate
from operations import investigator
from operations.checks import citation_validity, fact_checks
from operations.graph import investigate as run_graph
from operations.reasoning import public_evidence
from operations.tools import CROSS_SHIPMENT_TOOLS, InvestigationTools
from tests import test_investigator as ti
from tests import test_operations_store as _store
from tests.test_operations_store import approval_policy
from tests.world_fixture import small_world

REFERENCES = ("route_run_id", "trip_id", "container_id", "device_ref", "facility_id")


class ScriptedAgents:
    """The real investigator and reviewer functions with a scripted model underneath (what the harness drives)."""

    def __init__(self, turns, reviews):
        self.turn = ti.scripted(*turns)
        self.reviews = list(reviews)
        self.review_packets = []

    def investigate(self, tools, *, turn=None, on_step=None, feedback=None, session=None, review=None):
        return investigator.investigate(tools, turn=self.turn, on_step=on_step, feedback=feedback, session=session, review=review)

    def review(self, conclusion, records, checks, symptoms, *, ask=None, context=None, session=None):
        def scripted_ask(system, user, default):
            self.review_packets.append(json.loads(user)["facts"])
            reply = self.reviews.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        return investigator.review(conclusion, records, checks, symptoms, ask=scripted_ask, context=context, session=session)


def call(tool, **args):
    return {"action": "call", "tool": tool, "args": args, "purpose": "Inspect."}


def conclude(cause="BARCODE_MISMATCH", action="REQUEST_RESCAN", *, take=3, alternative="WEIGHT_MISMATCH", **extra):
    """A conclusion citing the first ids of the latest tool result, with one alternative tested against the same ids."""
    def reply(messages):
        result = next(m["content"] for m in reversed(messages) if m["content"].startswith("TOOL RESULT"))
        ids = json.loads(result.rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[1])[:take]
        abstain = cause == "INSUFFICIENT_EVIDENCE"
        hypotheses = [{"cause": cause, "status": "uncertain" if abstain else "supported", "supporting_evidence_ids": ids,
                       "contradicting_evidence_ids": [], "assessment": "As the cited records show."},
                      {"cause": alternative, "status": "refuted", "supporting_evidence_ids": [], "contradicting_evidence_ids": ids[:1],
                       "assessment": "The cited comparison does not show it."}]
        return {"action": "conclude", "primary_cause": cause, "confidence": "medium", "missing_evidence": [], "next_evidence_step": "",
                "recommended_action": action, "requires_physical_check": False, "summary": "Supported by the cited records.",
                "hypotheses": hypotheses, **extra}
    return reply


def verdict(value, feedback="Checked against the cited records.", **extra):
    return {"verdict": value, "feedback": feedback, "unsupported_claims": [], "unaddressed_contradictions": [], "alternatives_tested": "yes", **extra}


class WorldToolTests(unittest.TestCase):
    """The tools that look beyond one shipment, on mechanism-world records."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = small_world()
        cls.world = cls.fixture.world
        cls.reader = cls.fixture.reader
        cls.end = cls.world.config.as_of
        cls.sid, cls.refs = cls.pick()

    @classmethod
    def pick(cls):
        for shipment in sorted((n for n in cls.world.of_kind("Shipment") if n.properties.get("split") == "development"), key=lambda n: n.id):
            refs = {}
            for node in cls.reader.owned[shipment.id]:
                for field in REFERENCES:
                    if isinstance(node.properties.get(field), str):
                        refs.setdefault(field, set()).add(node.properties[field])
            if all(field in refs for field in REFERENCES):
                return shipment.id, {k: sorted(v) for k, v in refs.items()}
        raise AssertionError("no development shipment with every shared reference")

    def tools(self, as_of=None, **options):
        as_of = as_of or self.end
        return InvestigationTools(self.reader.evidence(self.sid, as_of), self.world.config, symptoms=["MILESTONE_OVERDUE"],
                                  heartbeats=self.reader.heartbeats, port=self.reader.fetch, **options)

    def arguments(self):
        return {"same_device_activity": {"device_id": self.refs["device_ref"][0], "hours": 24},
                "same_route_run": {"route_run_id": self.refs["route_run_id"][0]},
                "container_and_trip": {"container_id": self.refs["container_id"][0], "trip_id": self.refs["trip_id"][0]},
                "facility_window": {"facility_id": self.refs["facility_id"][0], "hours": 24}}

    def test_every_tool_answers_on_world_records_and_lists_citable_ids(self):
        tools = self.tools()
        package = next(n.id for n in tools.world.nodes.values() if n.kind == "Package")
        arguments = {**self.arguments(), "custody_chain": {"package_id": package}, "device_status": {"device_id": self.refs["device_ref"][0]},
                     "precedents": {"cause": "HUB_DELAY"}}
        for tool in tools.CATALOG:
            out = tools.call(tool, arguments.get(tool, {}))
            self.assertIsNone(tools.calls[-1]["failure"], (tool, out["result"][:200]))
            self.assertLessEqual(len(out["result"]), 6000 + 4000, tool)
            self.assertEqual(out["evidence_ids"], json.loads(out["result"].rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[1]), tool)
            for key in out["evidence_ids"]:
                self.assertIn(key, tools.index, (tool, key))            # Every citable id resolves for the validity check.
            self.assertTrue(set(out["computed_ids"]) <= set(tools.computed), tool)
        for tool in CROSS_SHIPMENT_TOOLS:
            listed = next(c for c in tools.calls if c["tool"] == tool)
            self.assertTrue(listed["computed_ids"], tool)               # A count or comparison the investigator can cite.
        # The overview hands the model the ids to ask the cross-shipment tools about.
        overview = json.loads(tools.calls[0] and tools.call("shipment_overview", {})["result"].rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[0])
        named = overview["references_in_this_shipments_records"]
        self.assertIn(self.refs["route_run_id"][0], named["route_run_ids"])
        self.assertIn(self.refs["trip_id"][0], named["trip_ids"])

    def test_cross_shipment_tools_return_other_shipments_records_with_their_ids(self):
        tools = self.tools()
        out = tools.call("same_route_run", self.arguments()["same_route_run"])
        body = json.loads(out["result"].rsplit(" CITABLE_EVIDENCE_IDS: ", 1)[0])
        others = [row for row in body["parcels"] if not row["this_shipment"]]
        self.assertTrue(others)
        self.assertGreater(body["summary"]["shipments"], 1)
        for row in others:
            for key in row["record_ids"]:
                self.assertIn(key, out["evidence_ids"])
                self.assertEqual(tools.index[key]["scope"], "other_shipment")
                self.assertEqual(self.world.nodes[key].properties["holdout_group"], row["shipment_id"])
        # A cited record of another shipment and a cited computed result are valid citations; an id never retrieved is not.
        cited = [others[0]["record_ids"][0], body["summary"]["computed_id"], "DEMO-SHP-999999-SCAN-001"]
        validity = citation_validity({"hypotheses": [{"supporting_evidence_ids": cited}]}, tools)
        self.assertEqual([row["valid"] for row in validity["citations"]], [True, True, False])
        self.assertEqual(validity["invalid_ids"], ["DEMO-SHP-999999-SCAN-001"])

    def test_a_mid_feed_snapshot_never_shows_a_later_record(self):
        dates = sorted(n.properties["occurred_at"] for n in self.reader.owned[self.sid] if n.kind == "ScanEvent")
        middle = dates[len(dates) // 2]
        tools = self.tools(as_of=middle)
        for tool, args in self.arguments().items():
            tools.call(tool, args)
            self.assertIsNone(tools.calls[-1]["failure"], tool)
        cutoff = instant(middle)
        self.assertGreater(len(tools.index), 5)
        for key, meta in tools.index.items():
            for field in ("recorded_at", "occurred_at"):
                if meta.get(field):
                    self.assertLessEqual(instant(meta[field]), cutoff, (key, field))
        later = self.tools()
        for tool, args in self.arguments().items():
            later.call(tool, args)
        self.assertGreater(len(later.index), len(tools.index))          # The same questions asked later see more.

    def test_disabled_tools_are_absent_and_refused(self):
        tools = self.tools(disabled=CROSS_SHIPMENT_TOOLS)
        self.assertFalse({d["tool"] for d in tools.describe()} & set(CROSS_SHIPMENT_TOOLS))
        self.assertIn("shipment_overview", {d["tool"] for d in tools.describe()})
        for tool, args in self.arguments().items():
            self.assertIn("error", tools.call(tool, args))
        self.assertEqual(tools.calls, [])
        # The investigator loop refuses them too, and carries on.
        agents = ScriptedAgents([call("same_route_run", **self.arguments()["same_route_run"]), call("policy"),
                                 conclude("INSUFFICIENT_EVIDENCE", "REQUEST_ADDITIONAL_EVIDENCE", missing_evidence=["the receiving scan"],
                                          next_evidence_step="Ask the facility for its scan log.")], [])
        out = agents.investigate(tools)
        self.assertFalse(out["degraded"])
        self.assertEqual([s["tool"] for s in out["steps"]], ["policy"])
        self.assertIn("unknown tool same_route_run", out["validation_errors"][0]["error"])


class InvestigationRunTests(ti.Base):
    """One case investigation through the graph: budget, revision, reviewer input and the per-round log."""

    def run_case(self, turns, reviews, *, recipe="different_barcode", symptoms=("BARCODE_READ_DIFFERS",), **options):
        sid = self.shipment(recipe)
        context = public_evidence(self.world, sid, self.world.config.as_of)
        agents = ScriptedAgents(turns, reviews)
        result, _ = run_graph(sid, context["as_of"], self.world.config, lambda *_: context, lambda *_: [], agents=agents,
                              live_session=True, symptoms=symptoms, heartbeats=ti.heartbeats_from(self.world), **options)
        return result, agents

    def test_a_revision_round_keeps_the_conversation_records_and_one_call_budget(self):
        result, agents = self.run_case(
            [call("scans"), conclude(), call("policy"), conclude()],
            [verdict("REVISE", "Check the policy threshold too.", unsupported_claims=["the confidence threshold"]), verdict("ACCEPT")])
        log = result["investigation_log"]
        self.assertEqual([len(r["tool_calls"]) for r in log["rounds"]], [1, 1])
        self.assertEqual([r["tool_calls"][0]["tool"] for r in log["rounds"]], ["scans", "policy"])
        # Four investigator turns and two reviews, one counter.
        self.assertEqual((log["model_calls_used"], log["model_call_cap"], log["cap_reached"]), (6, investigator.DEFAULT_MODEL_CALL_CAP, False))
        self.assertEqual(log["model_calls_by_role"], {"investigator": 4, "reviewer": 2})
        self.assertEqual([r["model_calls_used"] for r in log["rounds"]], [3, 6])
        # Round two continued round one's conversation: its first model input holds the first tool result, the first
        # conclusion and the reviewer's points; the scan ids of round one are still citable.
        second = agents.turn.seen[2]
        starts = [m["content"][:28] for m in second]
        self.assertLess(starts.index("TOOL RESULT scans: {\"summary"), starts.index("REVIEW OF YOUR CONCLUSION: {"))
        self.assertLess(starts.index("REVIEW OF YOUR CONCLUSION: {"), starts.index("TOOL RESULT policy: {\"policy"))
        points = next(m["content"] for m in second if m["content"].startswith("REVIEW OF YOUR CONCLUSION"))
        self.assertIn("the confidence threshold", points)
        self.assertIn("Check the policy threshold too.", points)
        self.assertEqual(sum(m["role"] == "system" for m in second), 1)     # One conversation, not a fresh start.
        first_ids = set(log["rounds"][0]["tool_calls"][0]["evidence_ids"])
        self.assertTrue(first_ids <= set(log["evidence_index"]))
        # The reviewer's second input carries its own earlier feedback.
        first, again = agents.review_packets
        self.assertNotIn("previous_reviews", first)
        self.assertEqual(again["previous_reviews"][0]["feedback"], "Check the policy threshold too.")
        self.assertEqual(again["previous_reviews"][0]["unsupported_claims"], ["the confidence threshold"])
        self.assertEqual(again["review_round"], 1)
        self.assertEqual([r["review"]["model_verdict"] for r in log["rounds"]], ["REVISE", "ACCEPT"])
        self.assertEqual(log["rounds"][0]["review"]["unsupported_claims"], ["the confidence threshold"])
        self.assertEqual(result["review"]["verdict"], "accept")

    def test_the_reviewer_receives_records_computed_results_uncited_ids_and_citation_validity(self):
        result, agents = self.run_case([call("scans"), call("policy"), conclude(take=4)], [verdict("ACCEPT")])
        packet = agents.review_packets[0]
        cited = {i for h in packet["investigator_conclusion"]["hypotheses"] for i in h["supporting_evidence_ids"] + h["contradicting_evidence_ids"]}
        self.assertEqual(set(packet["cited_records"]), cited)
        self.assertTrue(all("kind" in record for record in packet["cited_records"].values()))
        self.assertEqual((packet["citation_validity"]["cited"], packet["citation_validity"]["all_valid"]), (len(cited), True))
        comparisons = {v["computation"] for v in packet["computed_results_seen"].values()}
        self.assertIn("BARCODE_COMPARISON", comparisons)
        uncited = {i for group in packet["retrieved_but_uncited"].values() for i in group["ids"]}
        self.assertTrue(uncited)
        self.assertFalse(uncited & cited)
        self.assertEqual([c["tool"] for c in packet["tool_calls"]], ["scans", "policy"])
        self.assertIn("deterministic_checks", packet)
        log = result["investigation_log"]
        validity = log["rounds"][0]["citation_validity"]
        self.assertEqual([row["valid"] for row in validity["citations"]], [True] * len(cited))
        self.assertTrue(all(row["retrieved_in_this_investigation"] and row["recorded_at_or_before_snapshot"] for row in validity["citations"]))
        self.assertEqual(set(log["computed_results"]) >= set(log["rounds"][0]["tool_calls"][0]["computed_ids"]), True)
        self.assertEqual(log["disabled_tools"], [])
        self.assertEqual(log["snapshot_as_of"], self.world.config.as_of)

    def test_a_rejected_tool_call_turn_is_corrected_and_only_a_twice_invalid_conclusion_fails_closed(self):
        bad_conclusion = {"action": "conclude", "primary_cause": "BARCODE_MISMATCH", "hypotheses": []}
        result, _ = self.run_case(["not json", call("no_such_tool"), {"action": "wander"}, call("scans"), bad_conclusion, conclude()], [verdict("ACCEPT")])
        log = result["investigation_log"]
        self.assertFalse(log["rounds"][0]["investigator"]["degraded"])
        self.assertEqual(len(log["rounds"][0]["investigator"]["validation_errors"]), 4)
        self.assertEqual(log["rounds"][0]["conclusion"]["primary_cause"], "BARCODE_MISMATCH")
        self.assertEqual(log["model_calls_used"], 7)
        # The same invalid conclusion twice: no diagnosis, a person reviews.
        result, _ = self.run_case([call("scans"), bad_conclusion, bad_conclusion], [])
        self.assertEqual(result["investigation"]["mode"], "invalid_model_output")
        self.assertIsNone(result["investigation"]["primary_cause"])
        self.assertEqual(result["authority"]["risk_class"], "HUMAN_REVIEW")
        self.assertIsNone(result["investigation_log"]["rounds"][0]["conclusion"])

    def test_the_model_call_cap_is_enforced_in_code_and_a_cap_hit_is_a_degraded_run(self):
        result, agents = self.run_case([call("scans")] * 10, [], call_cap=4)
        log = result["investigation_log"]
        self.assertEqual((log["model_call_cap"], log["model_calls_used"], log["cap_reached"]), (4, 3, True))   # One call stays reserved for review.
        self.assertEqual(len(agents.turn.seen), 3)
        self.assertEqual(result["investigation"]["mode"], "model_call_cap")
        self.assertEqual((result["authority"]["risk_class"], result["result"]["workflow_state"]), ("HUMAN_REVIEW", "HUMAN_REVIEW"))
        self.assertEqual(result["degraded"][0]["kind"], "model_call_cap")
        # A revision needs an investigator turn and a review: with too few calls left the case goes to a person.
        result, agents = self.run_case([call("scans"), conclude(), conclude()], [verdict("REVISE"), verdict("ACCEPT")], call_cap=4)
        self.assertEqual(len(agents.review_packets), 1)
        self.assertEqual(result["investigation_log"]["model_calls_used"], 3)
        self.assertNotEqual(result["authority"]["risk_class"], "AUTO")
        self.assertEqual(result["result"]["workflow_state"], "ESCALATED")

    def test_insufficient_evidence_must_name_what_is_missing_and_never_closes_automatically(self):
        abstain = dict(missing_evidence=["a second read of the label"], next_evidence_step="Ask the facility to rescan the parcel.")
        incomplete = conclude("INSUFFICIENT_EVIDENCE", "REQUEST_ADDITIONAL_EVIDENCE")
        result, _ = self.run_case([call("scans"), incomplete, conclude("INSUFFICIENT_EVIDENCE", "REQUEST_ADDITIONAL_EVIDENCE", **abstain)], [verdict("ACCEPT")])
        log = result["investigation_log"]["rounds"][0]
        self.assertIn("must name the missing evidence", log["investigator"]["validation_errors"][0]["error"])
        self.assertEqual(log["conclusion"]["primary_cause"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(log["conclusion"]["next_evidence_step"], "Ask the facility to rescan the parcel.")
        # The evidence request may run; only a person can close the case.
        self.assertEqual((result["authority"]["risk_class"], result["authority"]["closure"]), ("AUTO", "HUMAN"))
        # It cannot recommend anything but evidence gathering or a person's check, and cannot also claim a cause.
        for wrong in (conclude("INSUFFICIENT_EVIDENCE", "PRIORITIZE_NEXT_SESSION", **abstain),):
            result, _ = self.run_case([call("scans"), wrong, wrong], [])
            self.assertTrue(result["investigation"]["degraded"])
            self.assertEqual(result["authority"]["risk_class"], "HUMAN_REVIEW")

    def test_a_reviewer_finding_of_insufficient_evidence_never_acts_automatically(self):
        result, agents = self.run_case([call("scans"), conclude(), conclude()],
                                       [verdict("INSUFFICIENT_EVIDENCE", "One read cannot establish this."), verdict("INSUFFICIENT_EVIDENCE", "Still one read.")])
        self.assertEqual(len(agents.review_packets), 2)                 # Sent back once for more evidence, then to a person.
        self.assertEqual(result["review"]["reason_code"], "MODEL_INSUFFICIENT_EVIDENCE")
        self.assertEqual((result["authority"]["risk_class"], result["result"]["workflow_state"]), ("HUMAN_REVIEW", "ESCALATED"))
        self.assertIn("insufficient", result["authority"]["reason"])

    def test_a_reviewer_outage_still_fails_closed(self):
        result, _ = self.run_case([call("scans"), conclude()], [TimeoutError("slow"), TimeoutError("slow")])
        self.assertEqual(result["review"]["verdict"], "review_unavailable")
        self.assertEqual((result["authority"]["risk_class"], result["authority"]["rule_id"]), ("HUMAN_REVIEW", "AUTH-02-model-degraded"))
        log = result["investigation_log"]
        self.assertTrue(log["rounds"][0]["review"]["degraded"])
        self.assertEqual(log["model_calls_by_role"], {"investigator": 2, "reviewer": 2})   # The reviewer's retry is counted.

    def test_an_invalid_citation_removes_automatic_authority_without_changing_the_diagnosis(self):
        sid = self.shipment("different_barcode")
        tools = self.tools(sid, self.world.config.as_of, symptoms=("BARCODE_READ_DIFFERS",))
        tools.call("scans", {})
        scan = next(i for i in tools.retrieved if "-SCAN-" in i)
        inv = {"primary_cause": "BARCODE_MISMATCH", "hypotheses": [{"cause": "BARCODE_MISMATCH", "status": "supported",
               "supporting_evidence_ids": [scan, "DEMO-NOT-RETRIEVED"], "contradicting_evidence_ids": []}]}
        checks = fact_checks(inv, tools)
        self.assertEqual(checks["citations"]["invalid_ids"], ["DEMO-NOT-RETRIEVED"])
        self.assertTrue(checks["unsupported"])
        self.assertEqual(inv["primary_cause"], "BARCODE_MISMATCH")

    def test_the_investigator_input_has_definitions_and_no_action_to_cause_mapping(self):
        sid = self.shipment("different_barcode")
        tools = self.tools(sid, self.world.config.as_of)
        packet = investigator.case_packet(tools, investigator.Session())
        self.assertEqual(set(packet["cause_catalogue"]), {"observations", "mechanisms", "abstention"})
        codes = {code for group in packet["cause_catalogue"].values() for code in group}
        self.assertEqual(codes, set(investigator.CAUSES))               # One catalogue: every cause code has a definition.
        for entry in packet["action_types"].values():
            self.assertEqual(set(entry), {"authority", "summary"})      # No "addresses" list.
        self.assertNotIn("addresses", json.dumps(packet))
        self.assertIn("reviewer", investigator.SYSTEM)
        self.assertIn("INSUFFICIENT_EVIDENCE", investigator.SYSTEM)


class RunRecordTests(unittest.TestCase):
    """What a store persists for an investigation and what case_detail serves back."""

    setUpClass = classmethod(lambda cls: setattr(cls, "world", generate(Config(total=90))))
    make = _store.StoreTests.make

    def test_the_run_record_is_persisted_with_its_rounds_and_served_by_case_detail(self):
        store, driver = self.make()
        store.agents = ScriptedAgents([call("shipment_overview"), conclude("INSUFFICIENT_EVIDENCE", "REQUEST_ADDITIONAL_EVIDENCE", take=2,
                                                                          missing_evidence=["the receiving scan"],
                                                                          next_evidence_step="Ask the facility for its scan log."),
                                       call("journey"), conclude("INSUFFICIENT_EVIDENCE", "REQUEST_ADDITIONAL_EVIDENCE", take=2,
                                                                 missing_evidence=["the receiving scan"],
                                                                 next_evidence_step="Ask the facility for its scan log.")],
                                      [verdict("REVISE", "Look at the journey."), verdict("ACCEPT")])
        store.disabled_tools = ("precedents",)
        store.model_call_cap = 9
        with approval_policy():
            result = store.process_one(manual=True)
        self.assertTrue(result["processed"])
        stored = next(v for k, v in driver.ledger.values() if k == "OpsRun" and v["entity_id"] == result["run_id"])
        self.assertEqual(stored["status"], "REVIEWED")
        saved = json.loads(stored["result_json"])["investigation_log"]   # Stored as JSON text with the run.
        detail = store.case_detail(result["case_id"])
        log = detail["run"]["result"]["investigation_log"]
        self.assertEqual(log, saved)
        self.assertEqual((log["model_calls_used"], log["model_call_cap"]), (6, 9))
        self.assertEqual(log["disabled_tools"], ["precedents"])
        self.assertEqual(log["snapshot_as_of"], detail["run"]["recorded_at"])
        self.assertEqual([r["round"] for r in log["rounds"]], [0, 1])
        for entry in log["rounds"]:
            for key in ("snapshot_as_of", "tool_calls", "conclusion", "investigator", "citation_validity", "fact_checks", "review",
                        "model_calls_used", "model_call_cap"):
                self.assertIn(key, entry)
            for tool_call in entry["tool_calls"]:
                self.assertEqual(set(tool_call), {"tool", "args", "evidence_ids", "computed_ids", "omitted_rows", "failure"})
            self.assertEqual(set(entry["review"]) >= {"verdict", "model_verdict", "reason_code", "feedback", "unsupported_claims"}, True)
        self.assertEqual(log["rounds"][1]["conclusion"]["missing_evidence"], ["the receiving scan"])
        # The run record next to it: the conclusion, the final review and the authority decision.
        run = detail["run"]["result"]
        self.assertEqual(run["investigation"]["primary_cause"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(run["investigation"]["model_calls"]["model_calls_used"], 5)   # As the investigator returned, before the last review.
        self.assertEqual(run["review"]["model_verdict"], "ACCEPT")
        self.assertEqual(run["authority"]["closure"], "HUMAN")
        self.assertEqual(detail["review"]["model_verdict"], "ACCEPT")
        # No chain-of-thought field anywhere in the stored run.
        text = stored["result_json"]
        for marker in ("reasoning_content", "chain_of_thought", "\"thinking\""):
            self.assertNotIn(marker, text)
        # An insufficient-evidence conclusion is not served as a diagnosis of a cause, and never closes by itself.
        self.assertNotEqual(detail["workflow_state"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
