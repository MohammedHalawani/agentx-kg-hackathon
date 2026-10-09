"""S5 safeguards: truth isolation, exactly-once execution across restarts, human-verified closure."""
import ast
import json
import pathlib
import unittest

from dataset_v2.contracts import Config
from dataset_v2.generate import generate
from operations.lifecycle import OperationsConflict
from operations.store import OperationsStore
from tests import test_operations_store as _store
from tests.test_operations_store import Reader

ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENT_REACHABLE = ["chat/operations/tools.py", "chat/operations/investigator.py", "chat/operations/checks.py",
                   "chat/operations/graph.py", "chat/operations/read_model.py", "chat/operations/reasoning.py",
                   "chat/operations/agents.py", "chat/operations/worker.py", "backend/operations_api.py", "backend/main.py"]


def imported_names(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names |= {f"{node.module}.{a.name}" for a in node.names} | {node.module or ""}
    return names


class TruthIsolationTests(unittest.TestCase):
    def test_no_agent_or_operator_module_can_reach_truth_or_simulator_state(self):
        for path in AGENT_REACHABLE:
            names = imported_names(path)
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertFalse(any("simulation" in n for n in names if path != "backend/operations_api.py"), path)
            self.assertNotIn("truth.jsonl", source, path)
            self.assertFalse(any(n.endswith("read_truth") for n in names if path != "backend/operations_api.py"), path)

    def test_api_reads_truth_only_to_construct_the_simulator(self):
        source = (ROOT / "backend/operations_api.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        users = [f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and "read_truth" in ast.unparse(f)]
        self.assertEqual(users, ["attach_simulator"])
        routes = [ast.unparse(d) for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) for d in f.decorator_list]
        self.assertFalse([r for r in routes if "truth" in r.lower()])

    def test_static_frontend_mount_does_not_expose_artifacts(self):
        main = (ROOT / "backend/main.py").read_text(encoding="utf-8")
        self.assertNotIn("artifacts", main)

    def test_investigator_prompt_and_tool_results_name_no_truth(self):
        from operations import investigator
        for marker in ("truth", "recipe", "root_cause", "expected_resolution", "buffered_upload", "wrong_label", "offline_device"):
            self.assertNotIn(marker, investigator.SYSTEM.lower())



class ReceiptLeakTests(unittest.TestCase):
    def test_receipts_depend_on_the_action_alone_and_carry_no_answer_key_wording(self):
        from dataset_v2.contracts import canonical
        from dataset_v2.live_bundle import truth_vocabulary
        from operations.reasoning import public_evidence
        from operations.simulation import RECEIPTS, OperationalSimulator
        from dataset_v2.feed import reconstitute, split_feed
        from dataset_v2.network import generate_live, live_config
        world, truth = generate_live(live_config(total=600))  # The full live recipe mix (120 live shipments).
        imported, items = split_feed(world, truth)
        world = reconstitute(imported, items)

        class Gateway:
            def enqueue(self, items): pass
            def pending_feed_ids(self, ids): return list(ids)
            def reschedule(self, ids, at): return len(ids)

        class Reader:
            def evidence(self, sid, at): return public_evidence(world, sid, at)

        simulator = OperationalSimulator(Gateway(), Reader(), truth, world.config)
        receipts = {}
        abnormal = [sid for sid, row in truth.items() if row["split"] == "development" and not row["healthy"]]
        self.assertGreater(len({truth[sid]["recipe"] for sid in abnormal}), 25)
        for sid in abnormal:
            for action in RECEIPTS:
                receipt = simulator.respond({"shipment_id": sid, "action_type": action, "target_device": None,
                                             "expected_evidence": [], "entity_id": "X"}, world.config.as_of)
                receipts.setdefault(action, set()).add(canonical(receipt))
        # Whatever the field state (wrong label, unresponsive contractor, offline device...), one receipt per action.
        self.assertEqual({action: len(texts) for action, texts in receipts.items()}, {action: 1 for action in RECEIPTS})
        text = " ".join(t for texts in receipts.values() for t in texts).lower()
        vocabulary = truth_vocabulary(truth)
        self.assertIn("label wrongly applied", vocabulary)
        self.assertIn("retained by contractor", vocabulary)
        for term in vocabulary:
            self.assertNotIn(term.lower(), text)


class SimulatorTargetingTests(unittest.TestCase):
    """The simulated field answers only the device or facility a request reaches."""
    @classmethod
    def setUpClass(cls):
        from tests import test_outcome_verification as tov
        cls.world, cls.truth = tov.Fixture.get()

    def simulator(self):
        from operations.reasoning import public_evidence
        from operations.simulation import OperationalSimulator
        world, sent = self.world, {"enqueued": [], "rescheduled": []}

        class Gateway:
            def enqueue(self, items): sent["enqueued"].extend(items)
            def pending_feed_ids(self, ids): return list(ids)
            def reschedule(self, ids, at): sent["rescheduled"].extend(ids); return len(ids)

        class Reader:
            def evidence(self, sid, at): return public_evidence(world, sid, at)
        return OperationalSimulator(Gateway(), Reader(), self.truth, world.config), sent

    def offline(self):
        from dataset_v2.contracts import instant, iso
        from datetime import timedelta
        sid, row = next((s, r) for s, r in self.truth.items() if r["split"] == "development" and r["recipe"] == "offline_device_sync")
        at = iso(instant(row["physical"]["offline_from"]) + timedelta(hours=3))
        return sid, row, at

    def test_only_the_targeted_device_answers_a_sync(self):
        sid, row, at = self.offline()
        device = row["physical"]["device_id"]
        for target, uploads in ((device, True), ("DEMO-DEV-APP-SOMEONE-ELSE", False), (None, False)):
            simulator, sent = self.simulator()
            simulator.respond({"shipment_id": sid, "action_type": "REQUEST_DEVICE_SYNC", "target_device": target,
                               "expected_evidence": [], "entity_id": "X"}, at)
            self.assertEqual(bool(sent["rescheduled"]), uploads, target)
            beats = [m["source_event_id"] for m in sent["enqueued"] if m["channel"] == "MDM"]
            self.assertTrue(all(target and b.startswith(target) for b in beats), (target, beats))
            self.assertFalse([b for b in beats if b.startswith(device)] if target != device else [])

    def test_a_check_finds_the_parcel_only_at_a_facility_the_request_reached(self):
        sid, row, at = self.offline()
        depot = row["physical"]["depot_id"]
        simulator, sent = self.simulator()
        simulator.respond({"shipment_id": sid, "action_type": "REQUEST_HUB_CHECK", "expected_evidence": [], "entity_id": "X"}, at)
        self.assertFalse([m for m in sent["enqueued"] if depot.removeprefix("DEMO-") in m["payload_json"]])  # Only its upstream holder was asked.
        simulator, sent = self.simulator()
        simulator.respond({"shipment_id": sid, "action_type": "REQUEST_HUB_CHECK", "entity_id": "X",
                           "expected_evidence": [{"package_id": "P", "predicate": "RECEIVED", "location_id": depot}]}, at)
        scans = [m for m in sent["enqueued"] if m["channel"] == "SPL_CORE"]
        self.assertTrue(scans)
        self.assertTrue(all("DEMO-DEV-CHK-" in m["payload_json"] and row["physical"]["device_id"] not in m["payload_json"] for m in scans))


class _Store(unittest.TestCase):
    """Reuses the store test fixtures without re-running their tests."""
    setUpClass = classmethod(lambda cls: setattr(cls, "world", generate(Config(total=90))))
    make = _store.StoreTests.make
    processed = _store.StoreTests.processed


class ExecutionRecoveryTests(_Store):
    def test_claimed_but_unacknowledged_execution_is_redispatched_exactly_once(self):
        store, driver, result = self.processed()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-crash")
        calls = []
        class Adapter:
            def respond(self, execution, now):
                calls.append(execution["entity_id"]); return {"acknowledged": True, "behaviour": "test"}
        # Simulate a crash after the claim and before the receipt.
        def crash(tx):
            for kind, e in tx.ledger.values():
                if kind == "OpsExecution": e["status"] = "EXECUTING"
        driver.execute_write(crash)
        self.assertEqual(store.execute_step(), [])  # A claimed execution is not picked again by a live worker.
        restarted = OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world))
        restarted.adapter = Adapter()
        restarted.initialize()
        self.assertEqual(len(restarted.execute_step()), 1)
        self.assertEqual(restarted.execute_step(), [])
        self.assertEqual(len(calls), 1)
        audit = [v["event_type"] for k, v in driver.ledger.values() if k == "OpsAudit"]
        self.assertIn("EXECUTION_RECOVERED", audit)

    def test_simulator_messages_have_deterministic_ids(self):
        from dataset_v2.contracts import Node
        from operations.simulation import message
        node = Node("DEMO-X-SIM-1", "ScanEvent", {"shipment_id": "S", "occurred_at": "2026-09-01T00:00:00+00:00", "source_ref": "x"})
        self.assertEqual(message(node, "SPL_CORE", "2026-09-01T00:01:00+00:00")["feed_id"],
                         message(node, "SPL_CORE", "2026-09-01T00:05:00+00:00")["feed_id"])


class HumanClosureTests(_Store):
    def test_person_closes_with_evidence_as_human_verified_not_evidence_verified(self):
        store, driver, result = self.processed()
        def to_human(tx):
            tx.ledger[result["case_id"]][1]["workflow_state"] = "HUMAN_REVIEW"
        driver.execute_write(to_human)
        case = store.case_detail(result["case_id"])
        evidence = [n["id"] for n in store.reader.evidence(case["shipment_id"], store.status()["as_of"])["nodes"] if n["kind"] == "Package"]
        with self.assertRaises(OperationsConflict):
            store.record_human_outcome(case["case_id"], "DEMO-OPERATOR-LOCAL", "parcel_located", "found", evidence, case["state_version"], "short-1")
        with self.assertRaises(OperationsConflict):
            store.record_human_outcome(case["case_id"], "DEMO-OPERATOR-LOCAL", "parcel_located", "Parcel found on shelf B4 during the depot check.",
                                       ["DEMO-NOT-VISIBLE"], case["state_version"], "foreign-1")
        closed = store.record_human_outcome(case["case_id"], "DEMO-OPERATOR-LOCAL", "parcel_located",
                                            "Parcel found on shelf B4 during the depot check.", evidence, case["state_version"], "human-01")
        self.assertEqual((closed["workflow_state"], closed["verification_status"]), ("RESOLVED", "HUMAN_VERIFIED"))
        outcome = next(v for k, v in driver.ledger.values() if k == "OpsOutcome")
        self.assertEqual((outcome["verification_status"], outcome["verifier_id"]), ("HUMAN_VERIFIED", "DEMO-OPERATOR-LOCAL"))
        self.assertTrue(store.record_human_outcome(case["case_id"], "DEMO-OPERATOR-LOCAL", "parcel_located",
                                                   "Parcel found on shelf B4 during the depot check.", evidence, case["state_version"], "human-01")["idempotent"])


class ReviewerOutageRecordTests(_Store):
    def test_reviewer_outage_is_stored_and_served_as_unavailable_and_nothing_executes(self):
        from tests import test_investigator as ti
        store, driver = self.make()
        fake = ti.FakeInvestigator(lambda tools: [("shipment_overview", {})], ["UNAVAILABLE"])
        fake.cause, fake.action = "BARCODE_MISMATCH", "REQUEST_RESCAN"
        store.agents = fake
        result = store.process_one(manual=True)
        self.assertTrue(result["processed"])
        reviews = [v for k, v in driver.ledger.values() if k == "OpsReview"]
        self.assertTrue(reviews)
        self.assertTrue(all(r["verdict"] == "review_unavailable" and r["model_verdict"] == "UNAVAILABLE" and r["degraded"] for r in reviews))
        self.assertNotIn("اجتازت", "".join(r["summary_ar"] for r in reviews))
        detail = store.case_detail(result["case_id"])
        self.assertEqual(detail["review"]["verdict"], "review_unavailable")
        self.assertEqual(detail["workflow_state"], "HUMAN_REVIEW")
        audit = [v["event_type"] for k, v in driver.ledger.values() if k == "OpsAudit"]
        self.assertIn("MODEL_DEGRADED", audit)
        self.assertNotIn("RECOMMENDATION_READY", audit)
        self.assertFalse([v for k, v in driver.ledger.values() if k == "OpsExecution"])


class AuthorityPolicyTests(unittest.TestCase):
    def test_prohibited_is_never_relabelled_whatever_the_other_inputs(self):
        from operations.authority import authorize
        for action in ("COMPENSATION", "LIABILITY_DETERMINATION"):
            for degraded in (False, True):
                for verdict in ("ACCEPT", "UNAVAILABLE", "HUMAN_REVIEW", "ESCALATE", None):
                    for contractor in (False, True):
                        for conflict in (False, True):
                            for codes in ((), ("DELIVERY_DISPUTE",)):
                                risk, _ = authorize(action, codes, review_verdict=verdict, evidence_conflict=conflict, synthetic=True,
                                                    live_session=True, degraded=degraded, contractor_custody=contractor)
                                self.assertEqual(risk, "PROHIBITED")

    def test_execution_permission_for_every_action_path_and_decision(self):
        from operations.authority import ACTIONS, execution_permission
        for action, (base, *_rest) in ACTIONS.items():
            for decided in ("AUTO", "APPROVAL_REQUIRED", "HUMAN_REVIEW", "PROHIBITED", None):
                auto, _, _ = execution_permission(action, "AUTO_POLICY", decided)
                approved, _, _ = execution_permission(action, "OPERATOR_APPROVAL", decided)
                self.assertEqual(auto, base == "AUTO" and decided == "AUTO", (action, decided))
                self.assertEqual(approved, base in ("AUTO", "APPROVAL_REQUIRED") and decided != "PROHIBITED", (action, decided))
        self.assertFalse(execution_permission("NOT_AN_ACTION", "OPERATOR_APPROVAL", "AUTO")[0])
        self.assertFalse(execution_permission("REQUEST_RESCAN", "SOMETHING_ELSE", "AUTO")[0])


class AuthorityAtExecutionTests(_Store):
    """The policy is re-checked on every path: operator approval, the automatic switch and dispatch."""
    def case_with(self, action, risk, state):
        store, driver, result = self.processed()
        case_id = result["case_id"]
        def tamper(tx):
            case = tx.ledger[case_id][1]
            case["workflow_state"] = state
            recommendation = tx.ledger[case["recommendation_id"]][1]
            recommendation.update(action_type=action, risk_class=risk)
        driver.execute_write(tamper)
        return store, driver, store.case_detail(case_id)

    def executions(self, driver):
        return [v for k, v in driver.ledger.values() if k == "OpsExecution"]

    def audit(self, driver):
        return [v["event_type"] for k, v in driver.ledger.values() if k == "OpsAudit"]

    def test_operator_may_authorize_auto_and_approval_class_actions(self):
        for action, risk, state in (("REQUEST_RESCAN", "HUMAN_REVIEW", "HUMAN_REVIEW"),
                                    ("RETURN_TO_SENDER", "APPROVAL_REQUIRED", "AWAITING_APPROVAL")):
            store, driver, case = self.case_with(action, risk, state)
            approved = store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-" + action[:12])
            self.assertEqual(approved["workflow_state"], "AWAITING_OUTCOME")
            [execution] = self.executions(driver)
            self.assertEqual((execution["action_type"], execution["authority"], execution["decided_risk"], execution["permission_rule"]),
                             (action, "OPERATOR_APPROVAL", risk, "AUTH-19-operator-approved"))

    def test_no_click_executes_a_person_only_or_prohibited_action(self):
        for action, risk, rule in (("PHYSICAL_CUSTODY_CHECK", "HUMAN_REVIEW", "AUTH-12-human-review-action"),
                                   ("COMPENSATION", "AUTO", "AUTH-13-prohibited"),
                                   ("LIABILITY_DETERMINATION", "PROHIBITED", "AUTH-13-prohibited"),
                                   ("REQUEST_RESCAN", "PROHIBITED", "AUTH-13-prohibited")):
            store, driver, case = self.case_with(action, risk, "HUMAN_REVIEW")
            with self.assertRaises(OperationsConflict) as refused:
                store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-" + action[:12])
            self.assertIn(rule, str(refused.exception))
            self.assertEqual(self.executions(driver), [])
            self.assertIn("APPROVAL_REFUSED", self.audit(driver))
            self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "HUMAN_REVIEW")
            store.execute_step()
            self.assertEqual(self.executions(driver), [])

    def test_dispatch_refuses_an_execution_the_policy_does_not_allow_whatever_wrote_it(self):
        calls = []
        class Adapter:
            def respond(self, execution, now):
                calls.append(execution["action_type"]); return {"acknowledged": True, "behaviour": "test"}
        for action, path, decided in (("COMPENSATION", "AUTO_POLICY", "AUTO"), ("REQUEST_RESCAN", "AUTO_POLICY", "APPROVAL_REQUIRED"),
                                      ("PHYSICAL_CUSTODY_CHECK", "OPERATOR_APPROVAL", "HUMAN_REVIEW"), ("REQUEST_RESCAN", "AUTO_POLICY", None)):
            store, driver, result = self.processed()
            store.adapter = Adapter()
            case_id = result["case_id"]
            def plant(tx):
                tx.ledger["DEMO-OPS-EXECUTION-PLANTED"] = ("OpsExecution", {
                    "entity_id": "DEMO-OPS-EXECUTION-PLANTED", "case_id": case_id, "shipment_id": result.get("shipment_id") or tx.ledger[case_id][1]["shipment_id"],
                    "action_type": action, "authority": path, "decided_risk": decided, "status": "AUTHORIZED", "dataset_id": self.world.config.dataset_id,
                    "split": "development", "synthetic": True, "recorded_at": tx.ledger[case_id][1]["recorded_at"], "expected_evidence_json": "[]"})
            driver.execute_write(plant)
            store.execute_step()
            self.assertEqual(calls, [], (action, path, decided))
            planted = driver.ledger["DEMO-OPS-EXECUTION-PLANTED"][1]
            self.assertEqual(planted["status"], "REFUSED")
            self.assertIn("EXECUTION_REFUSED", self.audit(driver))

    def switch_run(self, action, decided):
        """The automatic switch on, with the policy's decision forced, so the AUTO path itself is exercised."""
        from unittest import mock
        from tests import test_investigator as ti
        store, driver = self.make()
        fake = ti.FakeInvestigator(lambda tools: [("shipment_overview", {})], ["ACCEPT"])
        fake.cause, fake.action = "BARCODE_MISMATCH", action
        store.agents = fake
        store.control("worker", "start")
        with mock.patch("operations.authority.authorize", return_value=(decided, "Low-risk, reversible, evidence-bound action within the synthetic automation allowlist.")), \
             mock.patch("operations.authority.symptom_floor", side_effect=lambda risk, reason, action_type, symptoms: (risk, reason, "AUTO")):
            result = store.process_one()
        self.assertTrue(result["processed"])
        return store, driver, result

    def test_automatic_switch_executes_an_auto_class_action_decided_auto(self):
        store, driver, result = self.switch_run("REQUEST_RESCAN", "AUTO")
        [execution] = self.executions(driver)
        self.assertEqual((execution["authority"], execution["decided_risk"], execution["permission_rule"]), ("AUTO_POLICY", "AUTO", "AUTH-10-auto-allowlist"))

    def test_automatic_switch_never_runs_a_person_only_action_even_if_decided_auto(self):
        store, driver, result = self.switch_run("PHYSICAL_CUSTODY_CHECK", "AUTO")
        self.assertEqual(self.executions(driver), [])
        self.assertEqual(store.case_detail(result["case_id"])["workflow_state"], "HUMAN_REVIEW")
        self.assertIn("EXECUTION_REFUSED", self.audit(driver))

    def test_a_retried_refusal_is_refused_and_audited_again(self):
        store, driver, case = self.case_with("PHYSICAL_CUSTODY_CHECK", "HUMAN_REVIEW", "HUMAN_REVIEW")
        for key in ("refuse-a", "refuse-b", "refuse-a"):
            with self.assertRaises(OperationsConflict) as refused:
                store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], key)
            self.assertIn("AUTH-12-human-review-action", str(refused.exception))
        self.assertEqual(self.audit(driver).count("APPROVAL_REFUSED"), 2)  # One per distinct command.

    def test_a_recommendation_without_an_action_type_is_never_approved_as_a_stand_in(self):
        store, driver, case = self.case_with(None, None, "HUMAN_REVIEW")
        self.assertFalse(store.case_detail(case["case_id"])["recommendation"]["approvable"])
        with self.assertRaises(OperationsConflict) as refused:
            store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-none")
        self.assertIn("AUTH-01-unknown-action", str(refused.exception))
        self.assertEqual(self.executions(driver), [])

    def test_rules_only_recommendations_carry_their_catalog_action_and_authority(self):
        store, driver, result = self.processed()  # Rules only (no model): the fixture's default.
        recommendation = store.case_detail(result["case_id"])["recommendation"]
        if recommendation:
            from operations.authority import ACTIONS
            self.assertIn(recommendation["action_type"], ACTIONS)
            self.assertIsNotNone(recommendation["risk_class"])
            self.assertNotEqual(recommendation["risk_class"], "AUTO")  # No independent model review: never automatic.

    def test_a_superseded_snapshot_never_makes_a_rejected_proposal_approvable(self):
        from tests import test_investigator as ti
        from operations.store import MAX_SNAPSHOT_REFRESHES
        store, driver = self.make()
        case_id = next(k for k, (kind, v) in driver.ledger.items() if kind == "OpsCase")

        class Moving(ti.FakeInvestigator):
            def investigate(self, tools, on_step=None, feedback=None):
                def bump(tx):  # Evidence arrives during every attempt.
                    tx.ledger[case_id][1]["state_version"] += 1
                driver.execute_write(bump)
                return super().investigate(tools, on_step=on_step, feedback=feedback)
        fake = Moving(lambda tools: [("shipment_overview", {})], ["REVISE", "REVISE"])
        fake.cause, fake.action = "BARCODE_MISMATCH", "REQUEST_RESCAN"
        store.agents = fake
        def exhausted(tx):
            tx.ledger[case_id][1]["snapshot_refreshes"] = MAX_SNAPSHOT_REFRESHES
        driver.execute_write(exhausted)
        store.process_one(case_id=case_id, manual=True)
        detail = store.case_detail(case_id)
        self.assertEqual(detail["workflow_state"], "ESCALATED")
        authority = detail["run"]["result"]["authority"]
        self.assertEqual(authority["rule_id"], "AUTH-15-superseded-snapshot")


class CurrentRunTests(_Store):
    def test_case_view_serves_the_current_runs_review_never_an_earlier_pass(self):
        from tests import test_investigator as ti
        store, driver = self.make()
        fake = ti.FakeInvestigator(lambda tools: [("shipment_overview", {})], ["REVISE", "ACCEPT", "UNAVAILABLE"])
        fake.cause, fake.action = "BARCODE_MISMATCH", "REQUEST_RESCAN"
        store.agents = fake
        first = store.process_one(manual=True)
        detail = store.case_detail(first["case_id"])
        self.assertEqual(detail["review"]["verdict"], "accept")
        store.request_reanalysis(first["case_id"], "DEMO-OPERATOR-LOCAL", detail["state_version"], "reanalyze-1")
        second = store.process_one(case_id=first["case_id"], manual=True)
        self.assertTrue(second["processed"])
        detail = store.case_detail(first["case_id"])
        self.assertEqual(detail["run"]["entity_id"], detail["last_run_id"])
        self.assertEqual(detail["review"]["verdict"], "review_unavailable")
        self.assertEqual([t["review"]["verdict"] for t in detail["run"]["result"]["trace"]], ["review_unavailable"])

    def test_a_receipt_nobody_acknowledged_is_not_awaiting_an_outcome(self):
        store, driver, result = self.processed()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-unack")
        class Silent:
            def respond(self, execution, now): return {"acknowledged": False, "behaviour": "No field system accepts this request type."}
        store.adapter = Silent()
        store.execute_step()
        execution = next(v for k, v in driver.ledger.values() if k == "OpsExecution")
        self.assertEqual(execution["status"], "NOT_ACKNOWLEDGED")
        self.assertEqual(store.case_detail(case["case_id"])["workflow_state"], "HUMAN_REVIEW")
        self.assertIn("ACTION_NOT_ACKNOWLEDGED", [v["event_type"] for k, v in driver.ledger.values() if k == "OpsAudit"])


class ExceptionClearanceTests(_Store):
    """A verified action resolves the case only when the exception itself is gone."""
    def verify_with(self, exceptions):
        from unittest import mock
        store, driver, result = self.processed()
        case = store.case_detail(result["case_id"])
        store.decide(case["case_id"], "approve", "DEMO-OPERATOR-LOCAL", case["state_version"], "approve-clear")
        def no_human_closure(tx):
            for kind, e in tx.ledger.values():
                if kind == "OpsExecution": e["closure"] = "AUTO"
                if kind == "OpsCase": e["symptom_codes"] = ["MILESTONE_OVERDUE"]
        driver.execute_write(no_human_closure)
        store.adapter = _store.Acknowledging()
        store.execute_step()
        current = store.case_detail(case["case_id"])
        verdict = {"status": "success", "outcome_type": "delayed_upload_received", "evidence_ids": [], "reason": "Late upload arrived.",
                   "rule_id": "VERIFY-REQUEST_DEVICE_SYNC-success", "expected_effect": "late upload"}
        assessment = {"exceptions": exceptions}
        with mock.patch("operations.outcome_engine.evaluate", return_value=verdict),              mock.patch("dataset_v2.derive.assess_shipment", return_value=assessment):
            store.request_verification(case["case_id"], "DEMO-OPERATOR-LOCAL", current["state_version"], "verify-clear")
        outcome = next(v for k, v in driver.ledger.values() if k == "OpsOutcome")
        audit = [v["event_type"] for k, v in driver.ledger.values() if k == "OpsAudit"]
        return store.case_detail(case["case_id"]), outcome, audit

    def test_action_verified_but_standing_symptom_remains_is_not_resolved(self):
        case, outcome, audit = self.verify_with([{"code": "MANIFEST_CONFLICT"}])
        self.assertEqual(case["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual((outcome["success"], outcome["exception_cleared"], outcome["remaining_symptoms"]),
                         (True, False, ["MANIFEST_CUSTODY_CONFLICT"]))
        self.assertIn("OUTCOME_VERIFIED_EXCEPTION_REMAINS", audit)
        self.assertNotIn("CASE_RESOLVED", audit)

    def test_past_event_symptom_does_not_block_resolution_when_the_condition_is_gone(self):
        case, outcome, audit = self.verify_with([{"code": "JOURNEY_DELAY"}])
        self.assertEqual(case["workflow_state"], "RESOLVED")
        self.assertTrue(outcome["exception_cleared"])
        self.assertIn("CASE_RESOLVED", audit)


if __name__ == "__main__":
    unittest.main()
