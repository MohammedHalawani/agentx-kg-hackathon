"""Observation mutation tests: recipes cannot supply the answer."""
import unittest

from dataset_v2.contracts import Config, World
from dataset_v2.derive import assess_shipment, derive_world


def fixture(total=30):
    world = World(Config(total=total))
    for kind, key, props in (
        ("Policy", "DEMO-POL", dict(barcode_min_confidence=.9, weight_absolute_kg=.5, weight_relative_fraction=.1)),
        ("OrganizationWarehouse", "DEMO-ORIGIN", {}), ("DeliveryDepot", "DEMO-DEPOT", {}),
        ("Vehicle", "DEMO-VAN", dict(payload_kg=100, volume_m3=10, handling=["STANDARD"], modes=["ROAD"])),
        ("Driver", "DEMO-DRIVER", {}), ("Customer", "DEMO-CUSTOMER", {}),
        ("ServiceLevel", "DEMO-SERVICE", {}), ("ShipmentType", "DEMO-TYPE", {})):
        world.node(kind, key, **props)
    splits = [split for split, count in world.config.split_counts.items() for _ in range(count)]
    for i, split in enumerate(splits):
        sid, pkg = f"DEMO-SHP-{i}", f"DEMO-PKG-{i}"
        route, segment, journey = f"DEMO-ROUTE-{i}", f"DEMO-SEG-{i}", f"DEMO-JOURNEY-{i}"
        addr, av = f"DEMO-ADDRESS-{i}", f"DEMO-AV-{i}"
        world.node("Shipment", sid, shipment_id=sid, split=split, package_ids=[pkg], as_of="2026-09-01T02:00:00+00:00",
                   journey_id=journey, policy_id="DEMO-POL", recipient_id="DEMO-CUSTOMER", current_address_version_id=av, status="IN_TRANSIT")
        def node(kind, key, **props):
            return world.node(kind, key, shipment_id=sid, split=split, **props)
        node("Package", pkg, package_id=pkg, manifest_barcode=f"DEMO-BAR-{i}", weight_kg=1,
             length_m=.1, width_m=.1, height_m=.1, volume_m3=.001, handling="STANDARD")
        node("Address", addr)
        node("AddressVersion", av, address_id=addr, version=1, valid_from=world.config.start_at,
             valid_to=None, lat=24, lng=46, accuracy_m=10)
        node("Route", route, segment_ids=[segment])
        node("RouteSegment", segment, sequence=1, from_id="DEMO-ORIGIN", to_id="DEMO-DEPOT",
             mode="ROAD", minimum_seconds=60, maximum_seconds=3600)
        node("JourneyPlan", journey, route_id=route, service_id="DEMO-SERVICE", type_id="DEMO-TYPE", policy_id="DEMO-POL",
             promise_at="2026-09-02T12:00:00+00:00", as_of="2026-09-01T02:00:00+00:00")
        scan = node("ScanEvent", f"DEMO-SCAN-{i}", package_id=pkg, observed_barcode=f"DEMO-BAR-{i}", readable=True, confidence=.99,
                    measured_weight_kg=1, calibrated=True, facility_id="DEMO-DEPOT", occurred_at="2026-09-01T01:00:00+00:00", recorded_at="2026-09-01T01:00:00+00:00")
        node("CustodyEvent", f"DEMO-CUSTODY-{i}", package_id=pkg, from_id="DEMO-ORIGIN", to_id="DEMO-DEPOT", event_type="RECEIVED",
             source_event_id=scan, source_quality="CORROBORATED", required_acknowledgments=2, received_acknowledgments=2, facility_id="DEMO-DEPOT",
             occurred_at="2026-09-01T01:00:00+00:00", recorded_at="2026-09-01T01:00:00+00:00")
        node("ExpectedMilestone", f"DEMO-MILE-{i}", package_id=pkg, sequence=1, predicate="RECEIVED", location_id="DEMO-DEPOT",
             earliest_at="2026-09-01T00:30:00+00:00", latest_at="2026-09-01T01:30:00+00:00", grace_seconds=60)
        world.edge(sid, "HAS_PACKAGE", pkg)
        world.gold[sid] = {"shipment_id": sid, "recipe": "HEALTHY"}
    derive_world(world)
    return world


def add_proof(world, sid="DEMO-SHP-0"):
    pkg, av = world.nodes[sid].properties["package_ids"][0], world.nodes[sid].properties["current_address_version_id"]
    split = world.nodes[sid].properties["split"]
    world.nodes[sid].properties["as_of"] = "2026-09-01T12:00:00+00:00"
    def node(kind, tag, **props):
        return world.node(kind, f"{sid}-{tag}", shipment_id=sid, split=split,
                          occurred_at="2026-09-01T10:00:00+00:00", recorded_at="2026-09-01T10:00:00+00:00", **props)
    session = world.node("DeliverySession", f"{sid}-SESSION", shipment_id=sid, split=split, depot_id="DEMO-DEPOT",
                         start_at="2026-09-01T03:00:00+00:00", end_at="2026-09-01T13:00:00+00:00", timezone="Asia/Riyadh", grace_seconds=3600)
    attempt = node("DeliveryAttempt", "ATTEMPT", package_id=pkg, used_address_version_id=av, disposition="DELIVERED", observed_gate="Gate 1", session_id=session)
    auth = node("AuthenticationEvidence", "AUTH", package_id=pkg, attempt_id=attempt, method="SYNTHETIC_OTP", result="PASS",
                expires_at="2026-09-01T10:05:00+00:00", authorized_recipient_id="DEMO-CUSTOMER")
    handoff = node("HandoffEvidence", "HANDOFF", package_id=pkg, attempt_id=attempt, recipient_id="DEMO-CUSTOMER", recipient_type="EXPECTED_RECIPIENT", authorization_ref=None)
    proof = node("DeliveryProof", "PROOF", package_id=pkg, attempt_id=attempt, address_version_id=av, authentication_id=auth,
                 handoff_id=handoff, verification_policy="synthetic_bound_delivery_v1", lat=24, lng=46, accuracy_m=10)
    world.edge(attempt, "HAS_PROOF", proof)
    return proof


class DerivationTests(unittest.TestCase):
    def test_normal_has_no_case_and_gold_cannot_choose_cause(self):
        world = fixture()
        self.assertEqual(world.of_kind("Case"), [])
        original = assess_shipment(world, "DEMO-SHP-0")
        world.gold["DEMO-SHP-0"].update(recipe="WRONG_GATE", expected_cause="LOST")
        self.assertEqual(assess_shipment(world, "DEMO-SHP-0"), original)
        hashes = world.hashes()
        derive_world(world)
        self.assertEqual(world.hashes(), hashes)

    def test_barcode_weight_and_contextual_tolerance(self):
        world = fixture()
        scan = world.nodes["DEMO-SCAN-0"].properties
        scan.update(observed_barcode="DEMO-DIFFERENT", measured_weight_kg=1.6)
        self.assertEqual(assess_shipment(world, "DEMO-SHP-0")["supported_codes"], ["BARCODE_MISMATCH", "WEIGHT_MISMATCH"])
        scan.update(readable=False, calibrated=False)
        self.assertEqual(assess_shipment(world, "DEMO-SHP-0")["supported_codes"], [])
        scan.update(readable=True, confidence=.2, calibrated=True, measured_weight_kg=1.5)
        self.assertEqual(assess_shipment(world, "DEMO-SHP-0")["supported_codes"], [])

    def test_missing_ack_does_not_establish_holder_and_conflict_requires_review(self):
        world = fixture()
        p = world.nodes["DEMO-CUSTODY-0"].properties
        p.update(received_acknowledgments=1, source_quality="INCOMPLETE_ACK")
        assessment = assess_shipment(world, "DEMO-SHP-0")
        self.assertIn("CUSTODY_GAP", assessment["supported_codes"])
        self.assertIsNone(assessment["custody"][0]["last_corroborated_holder_id"])
        p.update(received_acknowledgments=2, source_quality="ATTRIBUTED_REPORT")
        assessment = assess_shipment(world, "DEMO-SHP-0")
        self.assertTrue(assessment["requires_human_review"])
        self.assertNotIn("CONFLICTING_CUSTODY", assessment["supported_codes"])
        self.assertFalse(assessment["lost"])

    def test_raw_independent_reports_derive_conflict_without_diagnostic_label(self):
        world = fixture()
        for i, to in enumerate(("DEMO-DEPOT", "DEMO-VAN")):
            scan = world.node("ScanEvent",f"DEMO-REPORT-SOURCE-{i}",shipment_id="DEMO-SHP-0",split="history",package_id="DEMO-PKG-0",
                              confidence=.99,occurred_at="2026-09-01T01:30:00+00:00",recorded_at="2026-09-01T01:30:00+00:00")
            world.node("CustodyEvent",f"DEMO-REPORT-CUSTODY-{i}",shipment_id="DEMO-SHP-0",split="history",package_id="DEMO-PKG-0",from_id="DEMO-DEPOT",to_id=to,
                       source_quality="ATTRIBUTED_REPORT",source_ref=f"synthetic_reporting_source_{i}",source_event_id=scan,
                       required_acknowledgments=2,received_acknowledgments=2,event_type="LOADED",occurred_at="2026-09-01T01:30:00+00:00",recorded_at="2026-09-01T01:30:00+00:00")
        result = assess_shipment(world,"DEMO-SHP-0")
        self.assertIn("CONFLICTING_CUSTODY",result["supported_codes"])
        self.assertTrue(result["requires_human_review"])
        self.assertEqual(result["custody"][0]["last_corroborated_holder_id"],"DEMO-DEPOT")

    def test_future_followup_and_vehicle_gps_cannot_answer_current_case(self):
        world = fixture()
        before = assess_shipment(world, "DEMO-SHP-0")
        world.node("ScanEvent", "DEMO-FUTURE-SCAN", shipment_id="DEMO-SHP-0", split="history", package_id="DEMO-PKG-0",
                   observed_barcode="DEMO-WRONG", readable=True, confidence=1, measured_weight_kg=9, calibrated=True,
                   occurred_at="2026-09-02T01:00:00+00:00", recorded_at="2026-09-02T01:00:00+00:00")
        world.node("GPSObservation", "DEMO-GPS", shipment_id="DEMO-SHP-0", split="history", vehicle_id="DEMO-VAN", lat=25, lng=47,
                   accuracy_m=500, occurred_at="2026-09-01T01:10:00+00:00", recorded_at="2026-09-01T01:10:00+00:00")
        self.assertEqual(assess_shipment(world, "DEMO-SHP-0"), before)

    def test_late_recorded_scan_is_not_known_at_initial_snapshot(self):
        world = fixture()
        before = assess_shipment(world, "DEMO-SHP-0")
        world.node("ScanEvent", "DEMO-LATE-SCAN", shipment_id="DEMO-SHP-0", split="history", package_id="DEMO-PKG-0",
                   observed_barcode="DEMO-WRONG", readable=True, confidence=1, measured_weight_kg=9, calibrated=True,
                   occurred_at="2026-09-01T01:00:00+00:00", recorded_at="2026-09-01T03:00:00+00:00")
        self.assertEqual(assess_shipment(world, "DEMO-SHP-0"), before)
        self.assertIn("BARCODE_MISMATCH", assess_shipment(world, "DEMO-SHP-0", as_of="2026-09-01T04:00:00+00:00")["supported_codes"])

    def test_session_absence_derives_unreconciled_never_lost(self):
        world = fixture()
        world.nodes["DEMO-SHP-0"].properties["as_of"] = "2026-09-01T15:00:00+00:00"
        world.node("DeliverySession", "DEMO-SESSION", shipment_id="DEMO-SHP-0", split="history", depot_id="DEMO-DEPOT",
                   start_at="2026-09-01T03:00:00+00:00", end_at="2026-09-01T13:00:00+00:00", timezone="Asia/Riyadh", grace_seconds=3600)
        world.node("VehicleAssignment", "DEMO-ASSIGN", shipment_id="DEMO-SHP-0", split="history", vehicle_id="DEMO-VAN", driver_id="DEMO-DRIVER",
                   valid_from="2026-09-01T03:00:00+00:00", valid_to="2026-09-01T13:00:00+00:00", package_ids=["DEMO-PKG-0"], weight_kg=1, volume_m3=.001, mode="ROAD", session_id="DEMO-SESSION")
        result = assess_shipment(world, "DEMO-SHP-0")
        self.assertEqual(result["supported_codes"], ["UNRECONCILED_CUSTODY"])
        self.assertFalse(result["lost"])

    def test_bound_proof_does_not_dismiss_recipient_report_and_point_conflict_is_neutral(self):
        world = fixture()
        proof = add_proof(world)
        result = assess_shipment(world, "DEMO-SHP-0")
        self.assertEqual(result["delivery_assessment"][0]["assessment"], "CORROBORATED_DELIVERY")
        world.node("RecipientReport", "DEMO-REPORT", shipment_id="DEMO-SHP-0", split="history", package_id="DEMO-PKG-0",
                   report_code="NOT_RECEIVED", occurred_at="2026-09-01T11:00:00+00:00", recorded_at="2026-09-01T11:00:00+00:00")
        result = assess_shipment(world, "DEMO-SHP-0")
        self.assertEqual(result["delivery_assessment"][0]["assessment"], "CONFLICTING_EVIDENCE")
        self.assertTrue(result["requires_human_review"])
        world.nodes[proof].properties["lat"] += .1
        result = assess_shipment(world, "DEMO-SHP-0")
        self.assertEqual(result["delivery_assessment"][0]["assessment"], "POSSIBLE_MISDELIVERY")
        self.assertFalse(result["lost"])

    def test_authentication_binding_and_expiry_are_not_proof_by_method_name(self):
        world = fixture()
        add_proof(world)
        auth = world.nodes["DEMO-SHP-0-AUTH"].properties
        for mutation in ({"result": "FAIL"}, {"authorized_recipient_id": "DEMO-OTHER"}, {"expires_at": "2026-09-01T09:00:00+00:00"}):
            original = dict(auth)
            auth.update(mutation)
            self.assertIn("PROOF_INSUFFICIENT", assess_shipment(world, "DEMO-SHP-0")["supported_codes"])
            auth.clear(); auth.update(original)

    def test_gate_and_address_use_effective_evidence_not_recipe(self):
        world = fixture()
        add_proof(world)
        world.node("DeliveryInstruction", "DEMO-INSTRUCTION", shipment_id="DEMO-SHP-0", split="history", address_version_id="DEMO-AV-0", gate="Gate 2",
                   valid_from="2026-09-01T00:00:00+00:00", valid_to=None)
        self.assertIn("WRONG_GATE", assess_shipment(world, "DEMO-SHP-0")["supported_codes"])
        world.nodes["DEMO-INSTRUCTION"].properties["valid_from"] = "2026-09-02T00:00:00+00:00"
        self.assertNotIn("WRONG_GATE", assess_shipment(world, "DEMO-SHP-0")["supported_codes"])
        world.nodes["DEMO-AV-0"].properties["valid_to"] = "2026-09-01T09:00:00+00:00"
        self.assertIn("ADDRESS_CONFLICT", assess_shipment(world, "DEMO-SHP-0")["supported_codes"])


if __name__ == "__main__":
    unittest.main()
