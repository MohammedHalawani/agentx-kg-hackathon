import unittest

from dataset_v2.contracts import Provenance
from dataset_v2.derive import derive_world
from dataset_v2.validate import validate_world
from test_v2_derivation import add_proof, fixture


class ValidationTests(unittest.TestCase):
    def errors(self, world):
        return {error["code"] for error in validate_world(world)["errors"]}

    def test_fixture_validates_without_mutation(self):
        world = fixture()
        before = world.hashes()
        report = validate_world(world)
        self.assertTrue(report["pass"], report["errors"])
        self.assertEqual(world.hashes(), before)

    def test_gold_label_leak_and_cross_group_reference_rejected(self):
        world = fixture()
        world.nodes["DEMO-SCAN-0"].properties["gold_category"] = "barcode"
        world.nodes["DEMO-CUSTODY-0"].properties["source_event_id"] = "DEMO-SCAN-1"
        self.assertIn("GOLD_RUNTIME_ISOLATION", self.errors(world))
        self.assertIn("CUSTODY_SOURCE", self.errors(world))
        world.nodes["DEMO-SCAN-0"].properties.pop("gold_category")
        world.nodes["DEMO-SCAN-0"].properties["metadata"] = {"nested": [{"recipe": "hidden_answer"}]}
        self.assertIn("GOLD_RUNTIME_ISOLATION", self.errors(world))

    def test_unit_timestamp_and_physical_route_mutations(self):
        world = fixture()
        world.nodes["DEMO-PKG-0"].properties["volume_m3"] = 10
        world.nodes["DEMO-SCAN-0"].properties["occurred_at"] = "2026-09-01T01:00:00"
        world.nodes["DEMO-SEG-0"].properties["minimum_seconds"] = -1
        codes = self.errors(world)
        self.assertTrue({"PACKAGE_VOLUME", "UTC_TIMESTAMP", "OBSERVATION_CHRONOLOGY", "ROUTE_DURATION"} <= codes)

    def test_explicit_incomplete_observation_is_not_impossible_truth(self):
        world = fixture()
        world.nodes["DEMO-CUSTODY-0"].properties.update(received_acknowledgments=1, source_quality="INCOMPLETE_ACK")
        derive_world(world)
        self.assertTrue(validate_world(world)["pass"])
        world.nodes["DEMO-CUSTODY-0"].properties.pop("source_quality")
        self.assertIn("INCOMPLETE_ACK_OBSERVATION", self.errors(world))

    def test_aggregate_capacity_and_driver_overlap_guard(self):
        world = fixture()
        world.node("Vehicle", "DEMO-SECOND-VAN", payload_kg=1.5, volume_m3=10, handling=["STANDARD"], modes=["ROAD"])
        for i in range(3):
            sid = f"DEMO-SHP-{i}"
            world.node("VehicleAssignment", f"DEMO-ALLOC-{i}", shipment_id=sid, split="history", vehicle_id="DEMO-SECOND-VAN" if i<2 else "DEMO-VAN",
                       driver_id="DEMO-DRIVER", valid_from="2026-09-01T03:00:00+00:00", valid_to="2026-09-01T04:00:00+00:00",
                       package_ids=[f"DEMO-PKG-{i}"], weight_kg=1, volume_m3=.001, mode="ROAD", segment_id=f"DEMO-SEG-{i}")
        self.assertTrue({"AGGREGATE_VEHICLE_CAPACITY", "DRIVER_INTERVAL"} <= self.errors(world))

    def test_recommendation_alone_cannot_make_resolved_case(self):
        world = fixture()
        world.nodes["DEMO-SCAN-0"].properties["observed_barcode"] = "DEMO-WRONG"
        derive_world(world)
        case = world.owned("DEMO-SHP-0", "Case")[0]
        case.properties["state"] = "RESOLVED"
        world.node("Recommendation", "DEMO-REC", shipment_id="DEMO-SHP-0", split="history", action="Correct barcode")
        self.assertIn("RESOLVED_EVIDENCE_CHAIN", self.errors(world))

    def test_pending_is_not_success_and_failed_verified_history_remains_failure(self):
        world = fixture()
        world.node("Outcome", "DEMO-PENDING", shipment_id="DEMO-SHP-0", split="history", status="pending", success=True)
        self.assertIn("PENDING_NOT_SUCCESS", self.errors(world))
        p = world.nodes["DEMO-PENDING"].properties
        p.update(status="failed", success=False, verification_status="VERIFIED", verified_at="2026-09-01T01:30:00+00:00",
                 evidence_ids=["DEMO-SCAN-0"], invalidated=False)
        self.assertNotIn("OUTCOME_STATUS_MEANING", self.errors(world))
        p["status"] = "succeeded"
        self.assertIn("OUTCOME_STATUS_MEANING", self.errors(world))

    def test_recommendation_and_review_cannot_cite_future_completion(self):
        world = fixture()
        for kind in ("Recommendation", "Review"):
            world.node(kind, f"DEMO-{kind}", shipment_id="DEMO-SHP-0", split="history", evidence_ids=["DEMO-SCAN-0"],
                       occurred_at="2026-09-01T00:30:00+00:00", recorded_at="2026-09-01T00:30:00+00:00")
        self.assertIn("RECOMMENDATION_REVIEW_EVIDENCE_TIME", self.errors(world))
        for kind in ("Recommendation", "Review"):
            world.nodes[f"DEMO-{kind}"].properties["occurred_at"] = "2026-09-01T01:30:00+00:00"
        self.assertNotIn("RECOMMENDATION_REVIEW_EVIDENCE_TIME", self.errors(world))
        world.nodes["DEMO-SCAN-0"].properties["recorded_at"] = "2026-09-01T03:00:00+00:00"
        self.assertIn("RECOMMENDATION_REVIEW_EVIDENCE_TIME", self.errors(world))

    def test_planned_vehicle_exit_is_not_physical_custody_evidence(self):
        world = fixture()
        scan = world.node("ScanEvent", "DEMO-LOAD-SCAN", shipment_id="DEMO-SHP-0", split="history", package_id="DEMO-PKG-0", confidence=.99,
                          occurred_at="2026-09-01T01:30:00+00:00", recorded_at="2026-09-01T01:30:00+00:00")
        load = world.node("CustodyEvent", "DEMO-LOAD-CUSTODY", shipment_id="DEMO-SHP-0", split="history", package_id="DEMO-PKG-0", from_id="DEMO-DEPOT", to_id="DEMO-VAN",
                          event_type="LOADED", source_event_id=scan, source_quality="CORROBORATED", required_acknowledgments=2, received_acknowledgments=2,
                          occurred_at="2026-09-01T01:30:00+00:00", recorded_at="2026-09-01T01:30:00+00:00")
        edge = world.edge("DEMO-SHP-0","LOADED_ON","DEMO-VAN",package_id="DEMO-PKG-0",custody_event_id=load,
                          valid_from="2026-09-01T01:30:00+00:00",valid_to="2026-09-01T13:00:00+00:00")
        derive_world(world)
        self.assertIn("LOADED_ON_END_EVIDENCE", self.errors(world))
        world.edges[edge].properties["valid_to"] = None
        self.assertNotIn("LOADED_ON_END_EVIDENCE", self.errors(world))

    def test_linked_resolved_chain_requires_receipt_valid_proof_and_noninvalidated_outcome(self):
        world = fixture()
        proof = add_proof(world)
        world.nodes["DEMO-SCAN-0"].properties["observed_barcode"] = "DEMO-WRONG"
        derive_world(world)
        case = world.owned("DEMO-SHP-0", "Case")[0]
        case.properties["state"] = "RESOLVED"
        def node(kind, key, **props):
            return world.node(kind, key, shipment_id="DEMO-SHP-0", split="history",
                              occurred_at="2026-09-01T13:00:00+00:00", recorded_at="2026-09-01T13:00:00+00:00", **props)
        run = node("AnalysisRun", "DEMO-RUN")
        rec = node("Recommendation", "DEMO-REC")
        review = node("Review", "DEMO-REVIEW", verdict="accept")
        decision = node("OperatorDecision", "DEMO-DECISION", provenance=Provenance.OPERATOR_DECISION, decision="approve")
        execution = node("ActionExecution", "DEMO-EXEC", receipt_ref="DEMO-EXTERNAL-RECEIPT", status="ACKNOWLEDGED_FIXTURE", action_type="delivery_reconciliation")
        resolution = node("Resolution", "DEMO-RES")
        outcome = node("Outcome", "DEMO-OUT", success=True, status="succeeded", action_type="delivery_reconciliation", verification_status="VERIFIED",
                       verified_at="2026-09-01T13:00:00+00:00", evidence_ids=[proof], invalidated=False)
        for a, rel, b in ((case.id,"HAS_RUN",run),(run,"PROPOSES",rec),(rec,"REVIEWED_BY",review),(rec,"HAS_DECISION",decision),
                          (decision,"INITIATES",execution),(case.id,"RESOLVED_BY",resolution),(resolution,"HAS_OUTCOME",outcome),(outcome,"VERIFIED_BY",decision)):
            world.edge(a,rel,b)
        self.assertTrue(validate_world(world)["pass"], validate_world(world)["errors"])
        world.nodes[execution].properties["receipt_ref"] = None
        self.assertIn("RESOLVED_EVIDENCE_CHAIN", self.errors(world))
        world.nodes[execution].properties["receipt_ref"] = "DEMO-EXTERNAL-RECEIPT"
        world.nodes[outcome].properties["invalidated"] = True
        self.assertIn("RESOLVED_EVIDENCE_CHAIN", self.errors(world))
        world.nodes[outcome].properties["invalidated"] = False
        world.nodes[outcome].properties["evidence_ids"] = ["DEMO-SCAN-0"]
        self.assertIn("DELIVERY_OUTCOME_PROOF", self.errors(world))

    def test_recovery_uses_last_corroborated_holder_not_invalid_pod_claim(self):
        world = fixture()
        proof = add_proof(world)
        world.nodes["DEMO-SHP-0-AUTH"].properties["result"] = "FAIL"
        def custody(tag, hour, source, target, kind, ack=2, quality="CORROBORATED", proof_id=None):
            stamp = f"2026-09-01T{hour:02d}:00:00+00:00"
            scan = world.node("ScanEvent", f"DEMO-{tag}-SCAN", shipment_id="DEMO-SHP-0", split="history", package_id="DEMO-PKG-0",
                              readable=True, confidence=.99, occurred_at=stamp, recorded_at=stamp)
            world.node("CustodyEvent", f"DEMO-{tag}", shipment_id="DEMO-SHP-0", split="history", package_id="DEMO-PKG-0",
                       from_id=source, to_id=target, event_type=kind, source_event_id=scan, required_acknowledgments=2,
                       received_acknowledgments=ack, source_quality=quality, proof_id=proof_id, occurred_at=stamp, recorded_at=stamp)
        custody("LOAD",9,"DEMO-DEPOT","DEMO-VAN","LOADED")
        custody("BAD-DELIVERY",10,"DEMO-VAN","DEMO-CUSTOMER","DELIVERED",1,"INCOMPLETE_ACK",proof)
        custody("RECOVERY",11,"DEMO-VAN","DEMO-DEPOT","RETURNED")
        derive_world(world)
        self.assertNotIn("PHYSICAL_CUSTODY_CHAIN", self.errors(world))
        assessment = world.gold["DEMO-SHP-0"]["assessment"]
        self.assertEqual(assessment["custody"][0]["last_corroborated_holder_id"], "DEMO-DEPOT")
        world.nodes["DEMO-RECOVERY"].properties["from_id"] = "DEMO-CUSTOMER"
        self.assertIn("PHYSICAL_CUSTODY_CHAIN", self.errors(world))


if __name__ == "__main__":
    unittest.main()
