"""S3: the agent tool loop, its tools, fact checks and the investigation graph (scripted model; no provider)."""
import json
import types
import unittest
from datetime import timedelta

from dataset_v2.contracts import canonical, instant, iso
from dataset_v2.feed import reconstitute, split_feed
from dataset_v2.network import generate_live, live_config
from operations import investigator
from operations.checks import fact_checks
from operations.graph import investigate as run_graph
from operations.reasoning import public_evidence
from operations.tools import InvestigationTools


class World:
    """Live world as Suhail would have ingested it (recorded_at = delivery time)."""
    _cache = None

    @classmethod
    def get(cls):
        if cls._cache is None:
            world, truth = generate_live(live_config(total=150))
            imported, items = split_feed(world, truth)
            cls._cache = (reconstitute(imported, items), truth)
        return cls._cache


def heartbeats_from(world):
    def fetch(device_id, since, until):
        return [{"entity_id": n.id, **n.properties} for n in world.of_kind("DeviceHeartbeat")
                if n.properties["device_id"] == device_id and instant(since) <= instant(n.properties["occurred_at"]) <= instant(until)
                and instant(n.properties["recorded_at"]) <= instant(until)]
    return fetch


def scripted(*replies):
    queue = list(replies)
    seen = []
    def turn(messages):
        seen.append(messages)
        reply = queue.pop(0)
        return reply(messages) if callable(reply) else reply
    turn.seen = seen
    return turn


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world, cls.truth = World.get()

    def shipment(self, recipe):
        return next(sid for sid, row in self.truth.items() if row["recipe"] == recipe and row["split"] == "development")

    def tools(self, sid, as_of, symptoms=("MILESTONE_OVERDUE",)):
        context = public_evidence(self.world, sid, as_of)
        return InvestigationTools(context, self.world.config, symptoms=symptoms, heartbeats=heartbeats_from(self.world),
                                  precedents=lambda cause: [])


class ToolTests(Base):
    def test_tools_are_time_correct_and_carry_no_truth(self):
        sid = self.shipment("offline_device_sync")
        row = self.truth[sid]
        late = row["physical"]["buffered_event_ids"]
        occurred = min(instant(self.world.nodes[k].properties["occurred_at"]) for k in late)
        tools = self.tools(sid, iso(occurred + timedelta(hours=3)))
        texts = []
        for package in [n.id for n in tools.world.nodes.values() if n.kind == "Package"]:
            texts.append(tools.call("custody_chain", {"package_id": package})["result"])
            texts.append(tools.call("journey", {"package_id": package})["result"])
        texts.append(tools.call("device_status", {"device_id": row["physical"]["device_id"], "hours": 24})["result"])
        blob = " ".join(texts)
        for key in late:
            self.assertNotIn(key, blob)  # Uploaded ~20h later: invisible at this snapshot.
            self.assertNotIn(key, tools.retrieved)
        for marker in ("offline_device_sync", "buffered_upload", "root_cause", "DELAYED_SYNC", "recipe"):
            self.assertNotIn(marker, blob)
        self.assertIn("missing_after_deadline", blob)
        report = tools.device_reports[row["physical"]["device_id"]]
        self.assertGreaterEqual(report["hours_since_last_seen"], 2)

    def test_every_tool_returns_a_result_including_precedents(self):
        sid = self.shipment("different_barcode")
        tools = InvestigationTools(public_evidence(self.world, sid, self.world.config.as_of), self.world.config,
                                   heartbeats=heartbeats_from(self.world),
                                   precedents=lambda cause: [{"case_id": "C1", "action_type": "REQUEST_RESCAN", "success": True, "verified_at": "2026-09-01T00:00:00+00:00"}])
        package = next(n.id for n in tools.world.nodes.values() if n.kind == "Package")
        args = {"custody_chain": {"package_id": package}, "device_status": {"device_id": "DEMO-DEV-HH-DEPOT-RUH-01"}, "precedents": {"cause": "BARCODE_MISMATCH"}}
        for tool in tools.CATALOG:
            out = tools.call(tool, args.get(tool, {}))
            self.assertIn("result", out, tool)
            self.assertNotIn("invalid arguments", out["result"], tool)
        self.assertIn("REQUEST_RESCAN", tools.call("precedents", {"cause": "BARCODE_MISMATCH"})["result"])

    def test_unknown_tool_and_foreign_package_are_refused(self):
        sid = self.shipment("on_time")
        tools = self.tools(sid, self.world.config.as_of)
        self.assertIn("error", tools.call("cypher", {"query": "MATCH (n) RETURN n"}))
        self.assertIn("invalid arguments", tools.call("custody_chain", {"package_id": "DEMO-SHP-999999-PKG-01"})["result"])


class LoopTests(Base):
    def setUp(self):
        self.sid = self.shipment("different_barcode")
        self.tool_belt = self.tools(self.sid, self.world.config.as_of, symptoms=("BARCODE_READ_DIFFERS",))
        self.package = next(n.id for n in self.tool_belt.world.nodes.values() if n.kind == "Package")

    def conclude(self, ids, cause="BARCODE_MISMATCH", action="REQUEST_RESCAN"):
        return {"action": "conclude", "primary_cause": cause, "confidence": "medium", "missing_evidence": [],
                "recommended_action": action, "requires_physical_check": False, "summary": "A readable scan differs from the manifest barcode.",
                "hypotheses": [{"cause": cause, "status": "supported", "supporting_evidence_ids": ids, "contradicting_evidence_ids": [],
                                "assessment": "The scan reading differs from the manifest."},
                               {"cause": "WEIGHT_MISMATCH", "status": "refuted", "supporting_evidence_ids": [], "contradicting_evidence_ids": [],
                                "assessment": "Weights are within tolerance."}]}

    def test_agent_iterates_and_may_only_cite_what_its_tools_returned(self):
        def cite_scan(messages):
            result = next(m["content"] for m in reversed(messages) if m["content"].startswith("TOOL RESULT"))
            scan = json.loads(result.split(": ", 1)[1].split(" CITABLE_EVIDENCE_IDS")[0])["scans"][0]["scan_id"]
            return self.conclude([scan])
        turn = scripted({"action": "call", "tool": "scans", "args": {"package_id": self.package}, "purpose": "Compare barcode reads."},
                        self.conclude(["DEMO-SHP-000001-SCAN-01"]),  # Not retrieved: rejected, model must correct.
                        cite_scan)
        steps = []
        out = investigator.investigate(self.tool_belt, turn=turn, on_step=steps.append)
        self.assertEqual(out["mode"], "gpt-oss"); self.assertFalse(out["degraded"])
        self.assertEqual([s["tool"] for s in steps], ["scans"])
        self.assertIn("were not returned by your tools", turn.seen[2][-1]["content"])
        self.assertTrue(set(out["hypotheses"][0]["supporting_evidence_ids"]) <= self.tool_belt.retrieved)

    def test_budget_and_failures_fail_closed_without_a_substituted_diagnosis(self):
        call = {"action": "call", "tool": "policy", "args": {}, "purpose": "Read thresholds."}
        out = investigator.investigate(self.tool_belt, turn=scripted(*[call] * investigator.MAX_TOOL_CALLS, call, call))
        self.assertTrue(out["degraded"]); self.assertIsNone(out["primary_cause"])
        self.assertEqual(len(out["steps"]), investigator.MAX_TOOL_CALLS)
        def boom(messages): raise TimeoutError("slow")
        out = investigator.investigate(self.tool_belt, turn=scripted(boom, boom))
        self.assertTrue(out["degraded"]); self.assertIn("TimeoutError", out["validation_error"])

    def test_blame_and_gps_claims_are_rejected(self):
        bad = self.conclude([])
        bad["summary"] = "The driver lost the parcel."
        turn = scripted({"action": "call", "tool": "scans", "args": {"package_id": self.package}, "purpose": "x"}, bad, bad)
        self.assertTrue(investigator.investigate(self.tool_belt, turn=turn)["degraded"])

    def test_reviewer_failure_is_unavailable_never_accept(self):
        def broken(system, user, default): raise ConnectionError("down")
        def slow(system, user, default): raise TimeoutError("slow")
        def garbage(system, user, default): return {"verdict": "LOOKS_FINE", "feedback": 7}
        def empty(system, user, default): return None
        def not_text(system, user, default): return {"verdict": "ACCEPT", "feedback": 7}
        def not_object(system, user, default): return ["ACCEPT"]
        for ask in (broken, slow, garbage, empty, not_text, not_object):
            review = investigator.review({"hypotheses": []}, {}, [], [], ask=ask)
            self.assertEqual(review["verdict"], "UNAVAILABLE", ask.__name__); self.assertTrue(review["degraded"], ask.__name__)


class FactCheckTests(Base):
    def test_delayed_sync_requires_late_upload_or_device_silence(self):
        sid = self.shipment("offline_device_sync")
        row = self.truth[sid]
        occurred = min(instant(self.world.nodes[k].properties["occurred_at"]) for k in row["physical"]["buffered_event_ids"])
        tools = self.tools(sid, iso(occurred + timedelta(hours=3)))
        package = next(n.id for n in tools.world.nodes.values() if n.kind == "Package")
        tools.call("journey", {"package_id": package})
        milestone_ids = sorted(tools.retrieved)
        inv = {"primary_cause": "DELAYED_SYNC", "hypotheses": [{"cause": "DELAYED_SYNC", "status": "supported",
               "supporting_evidence_ids": milestone_ids[:2], "contradicting_evidence_ids": []}]}
        self.assertTrue(fact_checks(inv, tools)["unsupported"])  # No silence or lag evidence retrieved yet.
        tools.call("device_status", {"device_id": row["physical"]["device_id"]})
        self.assertFalse(fact_checks(inv, tools)["unsupported"])

    def test_contractor_held_parcel_is_flagged(self):
        sid = self.shipment("contractor_unreturned")
        tools = self.tools(sid, self.world.config.as_of)
        inv = {"primary_cause": "UNRECONCILED_CUSTODY", "hypotheses": []}
        self.assertTrue(fact_checks(inv, tools)["contractor_custody"])


class FakeInvestigator:
    """Scripted investigator/reviewer with the real tools underneath."""
    def __init__(self, plan, verdicts):
        self.plan, self.verdicts, self.feedback = plan, list(verdicts), []

    def investigate(self, tools, on_step=None, feedback=None):
        self.feedback.append(feedback)
        replies = [{"action": "call", "tool": t, "args": a, "purpose": "Inspect."} for t, a in self.plan(tools)]
        def conclude(messages):
            ids = sorted(tools.retrieved)[:3]
            return {"action": "conclude", "primary_cause": self.cause, "confidence": "medium", "missing_evidence": [],
                    "recommended_action": self.action, "requires_physical_check": False, "summary": "Supported by retrieved evidence.",
                    "hypotheses": [{"cause": self.cause, "status": "supported", "supporting_evidence_ids": ids,
                                    "contradicting_evidence_ids": [], "assessment": "Consistent with the records."}]}
        return investigator.investigate(tools, turn=scripted(*replies, conclude), on_step=on_step)

    def review(self, conclusion, records, checks, symptoms):
        verdict = self.verdicts.pop(0) if self.verdicts else "ACCEPT"
        if verdict == "UNAVAILABLE":  # Same shape as investigator.review on failure, timeout or invalid output.
            return {"verdict": "UNAVAILABLE", "feedback": "Independent model review could not be completed.", "unsupported_claims": [],
                    "mode": "model_unavailable", "degraded": True, "validation_error": "TimeoutError"}
        return {"verdict": verdict, "feedback": "Re-check the scan device." if verdict == "REVISE" else "Supported.",
                "unsupported_claims": [], "mode": "gpt-oss", "degraded": False, "validation_error": None}


class GraphTests(Base):
    def run_case(self, recipe, cause, action, verdicts=("ACCEPT",), as_of=None, symptoms=("BARCODE_READ_DIFFERS",)):
        sid = self.shipment(recipe)
        context = public_evidence(self.world, sid, as_of or self.world.config.as_of)
        fake = FakeInvestigator(lambda tools: [("scans", {}), ("custody_chain", {"package_id": next(n.id for n in tools.world.nodes.values() if n.kind == "Package")})], verdicts)
        fake.cause, fake.action = cause, action
        events = []
        result, _ = run_graph(sid, context["as_of"], self.world.config, lambda *_: context, lambda *_: [],
                              on_event=lambda e, _: events.append(e), agents=fake, live_session=True, symptoms=symptoms,
                              heartbeats=heartbeats_from(self.world))
        return result, events, fake

    def test_tool_calls_are_recorded_stage_events_and_accept_can_be_auto(self):
        result, events, _ = self.run_case("different_barcode", "BARCODE_MISMATCH", "REQUEST_RESCAN")
        calls = [e for e in events if e["stage"] == "classify" and e["output"].get("kind") == "tool_call"]
        self.assertEqual([c["output"]["tool"] for c in calls], ["scans", "custody_chain"])
        self.assertTrue(all(c["status"] == "RUNNING" and c["output"]["evidence_ids"] for c in calls))
        self.assertEqual(result["authority"]["risk_class"], "AUTO")
        self.assertEqual(result["result"]["workflow_state"], "AWAITING_OUTCOME")

    def test_reviewer_revise_reinvestigates_with_feedback(self):
        result, events, fake = self.run_case("different_barcode", "BARCODE_MISMATCH", "REQUEST_RESCAN", verdicts=("REVISE", "ACCEPT"))
        self.assertEqual(fake.feedback, [None, "Re-check the scan device."])
        self.assertIn(("classify", "RETRYING"), [(e["stage"], e["status"]) for e in events])
        self.assertEqual(len(result["trace"]), 2)

    def test_cause_inconsistent_with_evidence_rules_never_gets_auto(self):
        result, _, _ = self.run_case("on_time", "BARCODE_MISMATCH", "REQUEST_RESCAN", symptoms=("MILESTONE_OVERDUE",))
        self.assertNotEqual(result["authority"]["risk_class"], "AUTO")
        self.assertTrue(result["checks"]["unsupported"])

    def test_contractor_custody_routes_to_a_person(self):
        result, _, _ = self.run_case("contractor_unreturned", "UNRECONCILED_CUSTODY", "INITIATE_CUSTODY_RECONCILIATION",
                                     symptoms=("SESSION_END_UNRECONCILED",))
        self.assertEqual(result["authority"]["risk_class"], "HUMAN_REVIEW")
        self.assertIn("contractor", result["authority"]["reason"])

    def test_observed_symptom_floor_beats_a_wrong_diagnosis(self):
        # Reconciliation is not evidence-gathering: the floor turns AUTO into human investigation.
        result, _, _ = self.run_case("different_barcode", "BARCODE_MISMATCH", "INITIATE_CUSTODY_RECONCILIATION",
                                     symptoms=("BARCODE_READ_DIFFERS", "SESSION_END_UNRECONCILED"))
        self.assertEqual(result["authority"]["risk_class"], "HUMAN_REVIEW")
        # An evidence request may still run automatically, but only a person can close the case.
        result, _, _ = self.run_case("different_barcode", "BARCODE_MISMATCH", "REQUEST_RESCAN",
                                     symptoms=("BARCODE_READ_DIFFERS", "SESSION_END_UNRECONCILED"))
        self.assertEqual((result["authority"]["risk_class"], result["authority"]["closure"]), ("AUTO", "HUMAN"))
        self.assertTrue(result["authority"]["rule_id"].startswith("AUTH-"))
        self.assertIn("symptoms", result["authority"]["inputs"])

    def test_reviewer_outage_is_recorded_as_unavailable_never_as_a_pass(self):
        result, events, _ = self.run_case("different_barcode", "BARCODE_MISMATCH", "REQUEST_RESCAN", verdicts=("UNAVAILABLE",))
        self.assertEqual(result["review"]["verdict"], "review_unavailable")
        self.assertNotIn("accept", [item["review"]["verdict"] for item in result["trace"]])
        self.assertEqual((result["authority"]["risk_class"], result["authority"]["rule_id"]), ("HUMAN_REVIEW", "AUTH-02-model-degraded"))
        self.assertEqual(result["result"]["workflow_state"], "HUMAN_REVIEW")
        review_stage = [e for e in events if e["stage"] == "review" and e["status"] not in ("RUNNING", "RETRYING")]
        self.assertEqual(review_stage[-1]["status"], "DEGRADED")
        self.assertEqual(review_stage[-1]["output"]["verdict"], "review_unavailable")

    def test_reviewer_request_for_human_judgment_is_not_recorded_as_a_pass(self):
        for model_verdict in ("HUMAN_REVIEW", "ESCALATE"):
            result, events, _ = self.run_case("different_barcode", "BARCODE_MISMATCH", "REQUEST_RESCAN", verdicts=(model_verdict,))
            self.assertEqual(result["review"]["verdict"], "human_review")
            review_stage = [e for e in events if e["stage"] == "review" and e["status"] not in ("RUNNING", "RETRYING")]
            self.assertEqual(review_stage[-1]["status"], "HUMAN_REVIEW")  # Not drawn as a completed (passed) review.
            self.assertEqual((result["authority"]["risk_class"], result["authority"]["rule_id"]), ("HUMAN_REVIEW", "AUTH-03-reviewer-human"))

    def test_no_rule_codes_are_given_to_the_investigator(self):
        sid = self.shipment("different_barcode")
        tools = self.tools(sid, self.world.config.as_of)
        seen = []
        investigator.investigate(tools, turn=scripted(lambda m: seen.append(m) or {"action": "call", "tool": "nope"},
                                                      lambda m: {"action": "call", "tool": "nope"}))
        opening = seen[0][1]["content"]
        for code in ("BARCODE_MISMATCH\", \"evidence", "deterministic_signals", "supported_codes"):
            self.assertNotIn(code, opening)
        self.assertNotIn("diagnoses", opening)


if __name__ == "__main__":
    unittest.main()
