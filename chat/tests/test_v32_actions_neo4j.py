"""V3.2: the synthetic action-response protocol on a real Neo4j database, written by separate clients.

tests.test_v32_action_store exercises the same protocol on the in-memory port, which re-implements the store's Cypher by
hand. These tests run the real queries and transactions: the execution, response, expiry and verification writes, the
control lock between separate drivers, and the fences that keep a stale transaction from committing.

Same gate and same single target as tests.test_v3_concurrency_neo4j (prepare_target refuses every other database): opt in
with SUHAIL_V3_RACE_TESTS=1 and SUHAIL_V3_CI_DATABASE=shipments-v2-world-v34-race-20261016 (docs/v3.4/run-neo4j-gate.ps1).
Without the opt-in every test is SKIPPED, and a skip is an outstanding gate, not a pass.

Scripted only: no model, no external request. The case is opened and its recommendation recorded by tests.world_live.seed_case
(the store's own authorization path). Field evidence arrives as provider messages through the gateway, like any other record:
a baseline read that differs from the manifest from the shipment's own handheld, then an independent check-device rescan.
Each test starts from a development reset, which removes those test messages and everything they produced.
"""
import json
import os
import threading
import unittest
from datetime import timedelta
from unittest.mock import patch

from tests.test_v3_concurrency_neo4j import DATABASE_ENV, OPT_IN_ENV, TARGET, Client, prepare_target

ACTOR = "DEMO-OPERATOR-LOCAL"
SOURCE = "synthetic:v32-neo4j-gate"
WRONG_LABEL = "DEMO-V32-WRONG-LABEL"


@unittest.skipUnless(os.environ.get(OPT_IN_ENV) == "1",
                     f"OUTSTANDING GATE, not a pass: set {OPT_IN_ENV}=1 and {DATABASE_ENV}={TARGET}")
class ActionProtocolNeo4jTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = prepare_target()
        cls.clients = []
        cls.environment = patch.dict(os.environ, {"SUHAIL_SYNTHETIC_ACTION_RESPONSES": "1"})
        cls.environment.start()

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        for client in getattr(cls, "clients", []):
            client.close()

    # -- setup -------------------------------------------------------------------------------------------------------
    def client(self):
        from operations.action_lifecycle import SyntheticActionAdapter
        client = Client(self.manifest)
        client.store.adapter = SyntheticActionAdapter()
        type(self).clients.append(client)
        return client

    def world(self, client, sid):
        from operations.reasoning import evidence_world
        context = client.reader.evidence(sid, client.store.status()["as_of"])
        return evidence_world(context, client.store.config), context["as_of"]

    def healthy_shipment(self, client):
        """A development shipment visible now with no exception, preferably delivered (no milestone can fall due while
        the test holds it), whose packages have a scan with a device and a facility."""
        from dataset_v2.derive import assess_shipment
        from operations.closure import delivered
        from operations.store import DETECTION_ALLOWANCE_SECONDS
        fallback = None
        for _ in range(60):
            client.store.tick(seconds=86400, manual=True, speed=1)
            with client.driver.session(database=TARGET, default_access_mode="READ") as session:
                shipments = [row["id"] for row in session.run(
                    "MATCH (s:V2Entity:Shipment {dataset_id:$dataset,split:'development',synthetic:true}) "
                    "OPTIONAL MATCH (a:LiveIngested:DeliveryAttempt {shipment_id:s.entity_id}) "
                    "WITH s,count(a) AS attempts RETURN s.entity_id AS id ORDER BY attempts DESC,id LIMIT 60",
                    dataset=client.store.dataset_id)]
            for sid in shipments:
                try:
                    world, as_of = self.world(client, sid)
                except LookupError:
                    continue
                assessment = assess_shipment(world, sid, as_of, detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)
                if assessment["exceptions"]:
                    continue
                packages = sorted(n.id for n in world.nodes.values() if n.kind == "Package" and n.properties.get("shipment_id") == sid)
                scans = sorted((n for n in world.nodes.values() if n.kind == "ScanEvent" and n.properties.get("package_id") in packages
                                and n.properties.get("device_ref") and n.properties.get("facility_id")),
                               key=lambda n: n.properties["occurred_at"])
                if not packages or not scans:
                    continue
                if delivered(assessment):
                    return sid, packages, scans[-1]
                fallback = fallback or (sid, packages, scans[-1])
            if fallback:
                return fallback
        self.fail("the race fixture shows no healthy development shipment with a scanned package")

    def deliver(self, client, nodes):
        """Provider messages for `nodes`, delivered 30 s from now, then ingested by a one-minute tick."""
        from dataset_v2.contracts import instant, iso
        from operations.simulation import message
        at = iso(instant(client.store.status()["as_of"]) + timedelta(seconds=30))
        client.store.gateway.enqueue([{**message(node, "SPL_CORE", at), "origin": "V32-NEO4J-GATE"} for node in nodes])
        result = client.store.tick(seconds=60, manual=True, speed=1)
        self.assertEqual(result.get("rejected", 0) + result.get("conflicting_duplicate", 0), 0, result)

    def scans(self, client, sid, packages, facility, device, barcode=None, key="RESCAN"):
        """One readable scan per package, made now, at `facility` by `device`."""
        from dataset_v2.contracts import Node, digest, instant, iso
        with client.driver.session(database=TARGET, default_access_mode="READ") as session:
            manifest = {row["id"]: row["barcode"] for row in session.run(
                "MATCH (p:V2Entity:Package) WHERE p.entity_id IN $ids RETURN p.entity_id AS id, p.manifest_barcode AS barcode",
                ids=packages)}
        now = client.store.status()["as_of"]
        nodes = []
        for package in packages:
            node_id = f"{sid}-V32-{key}-{digest([package, now, device, barcode])[:8]}"
            nodes.append(Node(node_id, "ScanEvent", {
                "shipment_id": sid, "package_id": package, "occurred_at": iso(instant(now)), "recorded_at": iso(instant(now)),
                "source_ref": SOURCE, "readable": True, "confidence": .99, "facility_id": facility, "device_ref": device,
                "observation_type": key, "observed_barcode": barcode or manifest[package], "calibrated": False}))
        self.deliver(client, nodes)
        return [node.id for node in nodes]

    def barcode_case(self, dispatch=True):
        """A fresh ledger; a healthy shipment given a differing read from its own handheld; a case opened for it the way the
        monitor would, with an authorized automatic REQUEST_RESCAN recorded through the store's own policy path."""
        from tests.test_operations_store import development_reset
        from tests.world_live import seed_case
        first = self.client()
        first.store.initialize()
        development_reset(first.store)
        sid, packages, baseline = self.healthy_shipment(first)
        facility, device = baseline.properties["facility_id"], baseline.properties["device_ref"]
        first.store.tick(seconds=60, manual=True, speed=1)
        self.scans(first, sid, packages, facility, device, barcode=WRONG_LABEL, key="BASELINE")
        target = {"package_ids": packages, "facility_ids": [facility], "baseline_device_ids": [device]}
        case_id = seed_case(first.store, first.driver, sid, "REQUEST_RESCAN", ["BARCODE_MISMATCH"], target=target,
                            symptoms=["BARCODE_READ_DIFFERS"])
        execution_id = None
        if dispatch:
            [execution_id] = first.store.execute_step()
        self.case = {"client": first, "sid": sid, "packages": packages, "facility": facility, "device": device,
                     "case_id": case_id, "execution_id": execution_id}
        return self.case

    # -- reads and writes --------------------------------------------------------------------------------------------
    def rows(self, client, kind, **where):
        from operations.schema import public_value
        with client.driver.session(database=TARGET, default_access_mode="READ") as session:
            found = [public_value(dict(row["p"])) for row in session.run(f"MATCH (n:OpsEntity:{kind}) RETURN properties(n) AS p")]
        return [row for row in found if all(row.get(key) == value for key, value in where.items())]

    def execution(self, client=None):
        [row] = self.rows(client or self.case["client"], "OpsExecution", entity_id=self.case["execution_id"])
        return row

    def lifecycle(self, client=None):
        from operations.action_lifecycle import load
        return load(self.execution(client))

    def stored_case(self, client=None):
        [row] = self.rows(client or self.case["client"], "OpsCase", entity_id=self.case["case_id"])
        return row

    def respond(self, client, kind, response_id, evidence=None, revision=None):
        return client.store.record_action_response(
            self.case["case_id"], self.case["execution_id"], actor_id=ACTOR,
            expected_revision=self.lifecycle(client)["revision"] if revision is None else revision, response_id=response_id,
            kind=kind, occurred_at=client.store.status()["as_of"], evidence_ids=evidence or [], source_ref=SOURCE)

    def rescan(self, client):
        return self.scans(client, self.case["sid"], self.case["packages"], self.case["facility"],
                          "DEMO-DEV-CHK-" + self.case["facility"].removeprefix("DEMO-"))

    def advance_to_deadline(self, client):
        from dataset_v2.contracts import instant
        deadline = instant(self.execution(client)["deadline_at"])
        while instant(client.store.status()["as_of"]) < deadline:
            before = client.store.status()["as_of"]
            step = (deadline - instant(before)).total_seconds()
            client.store.tick(seconds=min(86400, step), manual=True, speed=1)
            self.assertNotEqual(client.store.status()["as_of"], before, "the fixture clock ended before the action deadline")
        return deadline

    def assert_credited_reads_qualify(self, client, outcome, refs):
        """The verifier credits every qualifying read after dispatch, not only the ones a response named: each credited
        read must be a readable read of this shipment's packages, matching the manifest, at the directed facility, by a
        device other than the baseline one, received after dispatch. The responder's own rescan must be among them."""
        from dataset_v2.contracts import instant
        from operations.schema import public_value
        self.assertLessEqual(set(refs), set(outcome["evidence_ids"]), outcome)
        dispatched = instant(self.execution(client)["occurred_at"])
        with client.driver.session(database=TARGET, default_access_mode="READ") as session:
            reads = [dict(row["n"]) for row in session.run(
                "MATCH (n:V2Entity:ScanEvent) WHERE n.entity_id IN $ids "
                "OPTIONAL MATCH (p:V2Entity:Package {entity_id:n.package_id}) "
                "RETURN n {.shipment_id,.package_id,.facility_id,.device_ref,.observed_barcode,.readable,.recorded_at,"
                "manifest:p.manifest_barcode} AS n", ids=outcome["evidence_ids"])]
        self.assertEqual(len(reads), len(outcome["evidence_ids"]), outcome)
        for read in reads:
            self.assertEqual((read["shipment_id"], read["facility_id"], read["readable"], read["observed_barcode"]),
                             (self.case["sid"], self.case["facility"], True, read["manifest"]), read)
            self.assertIn(read["package_id"], self.case["packages"], read)
            self.assertNotEqual(read["device_ref"], self.case["device"], read)
            self.assertGreater(instant(public_value(read["recorded_at"])), dispatched, read)

    def outcomes(self, client):
        return self.rows(client, "OpsOutcome", case_id=self.case["case_id"])

    def response_audits(self, client):
        return self.rows(client, "OpsAudit", case_id=self.case["case_id"], event_type="ACTION_RESPONSE_RECEIVED")

    def race(self, calls):
        start, results = threading.Barrier(len(calls)), {}

        def work(name, call):
            try:
                start.wait(30)
                results[name] = call()
            except Exception as error:
                results[name] = error
        threads = [threading.Thread(target=work, args=item, name=item[0]) for item in calls.items()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(180)
        self.assertFalse([t.name for t in threads if t.is_alive()], "a client never returned")
        return results

    # -- tests -------------------------------------------------------------------------------------------------------
    def test_authorized_dispatched_acknowledged_accepted_is_not_resolved_and_only_a_new_independent_rescan_resolves(self):
        case = self.barcode_case()
        first = case["client"]
        execution = self.execution()
        state = self.lifecycle()
        self.assertEqual((execution["status"], execution["mode"], execution["authority"]), ("ACKNOWLEDGED", "synthetic_response_transport", "AUTO_POLICY"))
        self.assertEqual((state["authorization"], state["dispatch"], state["state"]), ("AUTHORIZED", "SENT", "AWAITING_ACKNOWLEDGEMENT"))
        self.assertEqual(len(self.rows(first, "OpsAudit", case_id=case["case_id"], event_type="ACTION_EXECUTED")), 1)
        first.store.tick(seconds=60, manual=True, speed=1)
        for index, kind in enumerate(("ACKNOWLEDGED", "ACCEPTED", "STARTED")):
            self.assertFalse(self.respond(first, kind, f"response-{index}")["idempotent"])
            self.assertEqual(first.store.outcome_step(force=True), [], kind)
            self.assertEqual(self.stored_case()["workflow_state"], "AWAITING_OUTCOME", kind)
            self.assertEqual(self.outcomes(first), [], kind)                          # acceptance is not an outcome
        state = self.lifecycle()
        self.assertEqual((state["acknowledgement"], state["acceptance"], state["execution"], state["verification"]),
                         ("ACKNOWLEDGED", "ACCEPTED", "EXECUTING", "NOT_REQUESTED"))
        detail = first.store.case_detail(case["case_id"])
        self.assertNotEqual(detail["action_status"]["resolution"], "VERIFIED_RESOLVED")
        self.assertFalse(detail["action_status"]["human_decision_required"])     # a person doing a rescan is operational work

        # Restart: a new client (new driver, new store) sees the same committed state and replays safely.
        restarted = self.client()
        self.assertEqual(self.lifecycle(restarted), state)
        replay = self.respond(restarted, "ACKNOWLEDGED", "response-0", revision=1)
        self.assertTrue(replay["idempotent"])
        self.assertEqual(self.lifecycle(restarted)["revision"], state["revision"])

        refs = self.rescan(restarted)
        self.assertFalse(self.respond(restarted, "EVIDENCE_RECEIVED", "evidence", refs)["idempotent"])
        self.assertEqual(self.lifecycle(restarted)["verification"], "AWAITING_VERIFICATION")
        [result] = restarted.store.outcome_step(force=True)
        self.assertEqual(result["workflow_state"], "RESOLVED", (result, restarted.store.case_detail(case["case_id"]).get("outcome")))
        [outcome] = self.outcomes(restarted)
        self.assertEqual((outcome["success"], outcome["outcome_type"], outcome["verifier_id"]), (True, "barcode_corrected", "SUHAIL-OUTCOME-VERIFIER"))
        self.assert_credited_reads_qualify(restarted, outcome, refs)
        detail = restarted.store.case_detail(case["case_id"])
        self.assertEqual((detail["action_status"]["resolution"], self.lifecycle(restarted)["verification"]), ("VERIFIED_RESOLVED", "VERIFIED_SUCCESS"))
        self.assertEqual(restarted.store.outcome_step(force=True), [])             # verified once
        self.assertEqual(len(self.outcomes(restarted)), 1)

        # A late acknowledgement after resolution is audit history only.
        late = self.respond(first, "ACKNOWLEDGED", "late-ack")
        self.assertTrue(late["action_lifecycle"]["events"][-1]["late"])
        self.assertEqual(self.stored_case(restarted)["workflow_state"], "RESOLVED")

        # Provenance: every recorded response is audited once, synthetic, with its source and evidence.
        audits = [json.loads(a["result"]) for a in self.response_audits(restarted)]
        self.assertEqual(sorted(a["kind"] for a in audits), ["ACCEPTED", "ACKNOWLEDGED", "ACKNOWLEDGED", "EVIDENCE_RECEIVED", "STARTED"])
        self.assertTrue(all(a["synthetic"] is True and a["source_ref"] == SOURCE and a["execution_id"] == case["execution_id"] for a in audits))
        self.assertEqual(next(a for a in audits if a["kind"] == "EVIDENCE_RECEIVED")["evidence_ids"], refs)
        self.assertEqual(len(self.rows(restarted, "OpsExecution", case_id=case["case_id"])), 1)

    def test_two_clients_racing_the_same_and_conflicting_responses_write_once(self):
        case = self.barcode_case()
        first, second = case["client"], self.client()
        first.store.tick(seconds=60, manual=True, speed=1)
        revision = self.lifecycle()["revision"]
        same = self.race({"first": lambda: self.respond(first, "ACKNOWLEDGED", "ack", revision=revision),
                          "second": lambda: self.respond(second, "ACKNOWLEDGED", "ack", revision=revision)})
        self.assertTrue(all(isinstance(r, dict) for r in same.values()), same)
        self.assertEqual(sorted(r["idempotent"] for r in same.values()), [False, True])     # written once, replayed once
        self.assertEqual(self.lifecycle()["revision"], revision + 1)
        revision += 1
        conflicting = self.race({"accept": lambda: self.respond(first, "ACCEPTED", "accept", revision=revision),
                                 "reject": lambda: self.respond(second, "REJECTED", "reject", revision=revision)})
        from operations.lifecycle import OperationsConflict
        won = [name for name, r in conflicting.items() if isinstance(r, dict)]
        lost = [r for r in conflicting.values() if isinstance(r, OperationsConflict)]
        self.assertEqual((len(won), len(lost)), (1, 1), conflicting)                         # one wins; the stale one is refused
        state = self.lifecycle()
        self.assertEqual(state["revision"], revision + 1)
        self.assertEqual(state["state"], "ACCEPTED" if won == ["accept"] else "REJECTED")
        self.assertEqual(len(self.response_audits(first)), 2)
        self.assertEqual(self.outcomes(first), [])
        # Same response id with different content, and a new response on a stale revision, are refused.
        with self.assertRaises(OperationsConflict):
            self.respond(second, "REJECTED", "ack")
        with self.assertRaises(OperationsConflict):
            self.respond(second, "STARTED", "started", revision=revision)
        self.assertNotEqual(self.stored_case()["workflow_state"], "RESOLVED")

    def test_four_clients_racing_the_same_and_conflicting_responses_write_once(self):
        # V3.4: the same protocol with four separate clients answering at once.
        from operations.lifecycle import OperationsConflict
        case = self.barcode_case()
        clients = [case["client"], self.client(), self.client(), self.client()]
        clients[0].store.tick(seconds=60, manual=True, speed=1)
        revision = self.lifecycle()["revision"]
        same = self.race({f"client-{n}": (lambda c=c: self.respond(c, "ACKNOWLEDGED", "ack4", revision=revision))
                          for n, c in enumerate(clients)})
        self.assertTrue(all(isinstance(r, dict) for r in same.values()), same)
        self.assertEqual(sorted(r["idempotent"] for r in same.values()), [False, True, True, True])   # written once, replayed 3x
        self.assertEqual(self.lifecycle()["revision"], revision + 1)
        revision += 1
        kinds = ("ACCEPTED", "REJECTED", "ACCEPTED", "REJECTED")
        conflicting = self.race({f"{kind}-{n}": (lambda c=c, kind=kind, n=n: self.respond(c, kind, f"answer-{n}", revision=revision))
                                 for n, (c, kind) in enumerate(zip(clients, kinds))})
        won = [name for name, r in conflicting.items() if isinstance(r, dict)]
        lost = [r for r in conflicting.values() if isinstance(r, OperationsConflict)]
        self.assertEqual((len(won), len(lost)), (1, 3), conflicting)                         # one wins; the stale ones are refused
        state = self.lifecycle()
        self.assertEqual(state["revision"], revision + 1)
        self.assertEqual(state["state"], won[0].split("-")[0])
        self.assertEqual(len(self.response_audits(clients[0])), 2)
        self.assertEqual(self.outcomes(clients[0]), [])
        self.assertNotEqual(self.stored_case()["workflow_state"], "RESOLVED")

    def test_rejection_foreign_evidence_and_expiry_stay_unresolved(self):
        from dataset_v2.contracts import instant
        from operations.lifecycle import OperationsConflict
        case = self.barcode_case()
        first = case["client"]
        first.store.tick(seconds=60, manual=True, speed=1)
        self.respond(first, "ACKNOWLEDGED", "ack")
        self.respond(first, "ACCEPTED", "accepted")
        # Evidence of another shipment is refused, not attached.
        with first.driver.session(database=TARGET, default_access_mode="READ") as session:
            foreign = session.run("MATCH (n:V2Entity:ScanEvent) WHERE n.shipment_id <> $sid AND n.source_ref IS NOT NULL "
                                  "RETURN n.entity_id AS id LIMIT 1", sid=case["sid"]).single()["id"]
        with self.assertRaises(OperationsConflict):
            self.respond(first, "EVIDENCE_RECEIVED", "foreign", [foreign])
        # The deadline passes without evidence: the request expires, unresolved, without a human-decision claim.
        self.advance_to_deadline(first)
        self.assertEqual(first.store.outcome_step(force=True), [])
        self.assertEqual((self.lifecycle()["state"], self.execution()["status"]), ("EXPIRED", "RESPONSE_EXPIRED"))
        self.assertEqual(self.stored_case()["workflow_state"], "NEEDS_EVIDENCE")
        self.assertFalse(first.store.case_detail(case["case_id"])["action_status"]["human_decision_required"])
        late = self.respond(first, "ACKNOWLEDGED", "late-ack")
        self.assertTrue(late["action_lifecycle"]["events"][-1]["late"])
        self.assertEqual(self.lifecycle()["state"], "EXPIRED")
        self.assertEqual(self.outcomes(first), [])
        self.assertEqual(len(self.rows(first, "OpsAudit", case_id=case["case_id"], event_type="ACTION_RESPONSE_EXPIRED")), 1)

        rejected = self.barcode_case()
        first = rejected["client"]
        first.store.tick(seconds=60, manual=True, speed=1)
        self.respond(first, "REJECTED", "rejected")
        self.assertEqual(first.store.outcome_step(force=True), [])
        self.assertEqual((self.lifecycle()["state"], self.stored_case()["workflow_state"]), ("REJECTED", "NEEDS_EVIDENCE"))
        self.assertTrue(self.respond(first, "ACKNOWLEDGED", "late-ack")["action_lifecycle"]["events"][-1]["late"])
        self.assertEqual(self.outcomes(first), [])

    def test_evidence_racing_an_expiry_at_the_deadline_is_never_both_and_never_a_false_resolution(self):
        from dataset_v2.contracts import instant
        case = self.barcode_case()
        first, second = case["client"], self.client()
        first.store.tick(seconds=60, manual=True, speed=1)
        self.respond(first, "ACKNOWLEDGED", "ack")
        self.respond(first, "ACCEPTED", "accepted")
        refs = self.rescan(first)                                   # made and received well before the deadline
        deadline = self.advance_to_deadline(first)
        self.assertEqual(instant(first.store.status()["as_of"]), deadline)
        results = self.race({"expiry": lambda: first.store.outcome_step(force=True),
                             "evidence": lambda: self.respond(second, "EVIDENCE_RECEIVED", "on-time", refs)})
        self.assertIsInstance(results["expiry"], list, results)
        state, workflow = self.lifecycle()["state"], self.stored_case()["workflow_state"]
        # Exactly one ordering committed: the response first (and the verifier may already have read it), or the expiry.
        self.assertIn((state, workflow), {("EVIDENCE_RECEIVED", "AWAITING_OUTCOME"), ("VERIFIED", "RESOLVED"),
                                          ("EXPIRED", "NEEDS_EVIDENCE")}, results)
        if state == "EVIDENCE_RECEIVED":
            self.assertEqual(self.outcomes(first), [])
            self.assertEqual([r["workflow_state"] for r in first.store.outcome_step(force=True)], ["RESOLVED"])
        if state in ("EVIDENCE_RECEIVED", "VERIFIED"):            # verified from the real rescan, once
            [outcome] = self.outcomes(first)
            self.assertTrue(outcome["success"], outcome)
            self.assert_credited_reads_qualify(first, outcome, refs)
        else:                                                     # the expiry won: the response is history, nothing verified
            self.assertEqual(first.store.outcome_step(force=True), [])
            self.assertEqual(self.outcomes(first), [])
            self.assertEqual(len(self.rows(first, "OpsAudit", case_id=case["case_id"], event_type="ACTION_RESPONSE_EXPIRED")), 1)

    def test_a_contradiction_ingested_by_another_client_during_verification_fences_the_stale_success(self):
        case = self.barcode_case()
        first, second = case["client"], self.client()
        first.store.tick(seconds=60, manual=True, speed=1)
        self.respond(first, "ACKNOWLEDGED", "ack")
        self.respond(first, "ACCEPTED", "accepted")
        refs = self.rescan(first)
        self.respond(first, "EVIDENCE_RECEIVED", "evidence", refs)
        reader, injected = first.store._reader(), []

        def racing_evidence(sid, as_of=None):
            context = reader.evidence(sid, as_of)                 # the verifier's snapshot is taken here
            if not injected:
                injected.append(True)                             # then another client ingests a contradicting read
                self.scans(second, case["sid"], case["packages"], case["facility"], "DEMO-DEV-V32-CONTRADICTION",
                           barcode="DEMO-V32-OTHER-IDENTITY", key="CONTRADICTION")
            return context
        version = self.stored_case()["state_version"]
        with patch.object(first.store, "_reader", return_value=type("R", (), {"evidence": staticmethod(racing_evidence)})()):
            self.assertEqual(first.store.outcome_step(force=True), [])
        self.assertGreater(self.stored_case()["state_version"], version)
        self.assertEqual(self.outcomes(first), [])                 # the stale success never committed
        [result] = first.store.outcome_step(force=True)            # verified again on the current evidence
        self.assertNotEqual(result["workflow_state"], "RESOLVED")
        [outcome] = self.outcomes(first)
        self.assertFalse(outcome["success"])

    def test_after_reanalysis_a_late_response_or_expiry_of_the_old_cycle_cannot_touch_the_new_one(self):
        case = self.barcode_case()
        first, second = case["client"], self.client()
        first.store.tick(seconds=60, manual=True, speed=1)
        self.respond(first, "REJECTED", "rejected")
        current = self.stored_case()
        requested = second.store.request_reanalysis(case["case_id"], ACTOR, current["state_version"], "v32-neo4j-reanalysis")
        self.assertEqual(requested["workflow_state"], "OPEN")
        version = self.stored_case()["state_version"]
        late = self.respond(first, "ACKNOWLEDGED", "late-old-ack")            # from the other client, after the new cycle began
        self.assertTrue(late["action_lifecycle"]["events"][-1]["late"])
        stored = self.stored_case()
        self.assertEqual((stored["workflow_state"], stored["state_version"]), ("OPEN", version))
        self.advance_to_deadline(first)
        self.assertEqual(first.store.outcome_step(force=True), [])
        self.assertEqual(self.outcomes(first), [])                 # the old dispatch neither expires nor certifies the new cycle
        self.assertEqual(self.stored_case()["workflow_state"], "OPEN")


if __name__ == "__main__":
    unittest.main()
