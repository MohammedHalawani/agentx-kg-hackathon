"""Receipt-cutoff and source-binding checks for the additive vehicle evidence contract."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from dataset_v2.contracts import instant
from operations.route_evidence import build_route_evidence
from operations.tools import InvestigationTools, MAX_RESULT_CHARS
from tests.world_fixture import MemoryPort, small_world
from operations.reasoning import public_evidence
from operations.read_model import OperationsReader


T0 = "2026-09-19T10:00:00+00:00"
T1 = "2026-09-19T12:00:00+00:00"
SID = "DEMO-SHP-V3-1"
RUN = "DEMO-RR-V3-1"
VEH = "DEMO-VEH-V3-1"
DATASET = "DEMO-SUHAIL-WORLD-V3-20261013"


def node(key, kind, **props):
    return {"id": key, "kind": kind, "properties": {"entity_id": key, "dataset_id": DATASET,
            "split": "development" if kind != "RouteRun" else "shared",
            "recorded_at": "2026-09-19T07:00:00+00:00", **props}}


def context(cutoff):
    return {"shipment_id": SID, "as_of": cutoff, "nodes": [
        node(SID, "Shipment", shipment_id=SID),
        node(RUN, "RouteRun", vehicle_id=VEH, device_ref="DEMO-DEV-V3-1"),
        node("DEMO-ASSIGN-V3-1", "VehicleAssignment", shipment_id=SID, route_run_id=RUN,
             vehicle_id=VEH, valid_from="2026-09-19T08:00:00+00:00", valid_to="2026-09-19T18:00:00+00:00")],
        "edges": []}


def position(key, occurred, recorded, **changes):
    return {"props": {"entity_id": key, "dataset_id": DATASET, "split": "shared",
            "vehicle_id": VEH, "route_run_id": RUN, "trip_id": None,
            "lat": 24.7, "lng": 46.6, "accuracy_m": 12.0, "speed_kmh": 0.0,
            "occurred_at": occurred, "recorded_at": recorded, "source_ref": "telematics",
            "position_scope": "VEHICLE_ONLY", **changes}}


class RouteEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.early = position("DEMO-GPS-V3-1", "2026-09-19T09:00:00+00:00", "2026-09-19T09:01:00+00:00")
        self.late = position("DEMO-GPS-V3-2", "2026-09-19T09:04:00+00:00", "2026-09-19T11:30:00+00:00")

    def fetch(self, cutoff, rows):
        def read(name, **params):
            self.assertEqual(name, "route_run_positions")
            self.assertEqual(params["ref"], RUN)
            return [copy.deepcopy(r) for r in rows if r["props"]["recorded_at"] <= cutoff]
        return read

    def test_later_ingest_does_not_change_earlier_snapshot(self):
        rows = [self.early, self.late]
        before = build_route_evidence(context(T0), self.fetch(T0, rows))
        after = build_route_evidence(context(T1), self.fetch(T1, rows))
        again = build_route_evidence(context(T0), self.fetch(T0, rows))
        self.assertEqual([p["evidence_id"] for p in before["observations"]], ["DEMO-GPS-V3-1"])
        self.assertEqual(before, again)
        self.assertEqual([p["evidence_id"] for p in after["observations"]], ["DEMO-GPS-V3-1", "DEMO-GPS-V3-2"])
        self.assertEqual(after["summary"]["stationary_intervals"][0]["input_evidence_ids"],
                         ["DEMO-GPS-V3-1", "DEMO-GPS-V3-2"])

    def test_foreign_run_interval_and_invalid_geometry_are_rejected(self):
        wrong = position("DEMO-GPS-FOREIGN", "2026-09-19T09:01:00+00:00", "2026-09-19T09:02:00+00:00",
                         route_run_id="DEMO-RR-OTHER")
        outside = position("DEMO-GPS-OUTSIDE", "2026-09-19T19:00:00+00:00", "2026-09-19T19:01:00+00:00")
        missing = position("DEMO-GPS-NO-GEOMETRY", "2026-09-19T09:02:00+00:00", "2026-09-19T09:03:00+00:00", lat=None)
        held = position("DEMO-GPS-HELD", "2026-09-19T09:03:00+00:00", "2026-09-19T09:04:00+00:00", split="held_out")
        result = build_route_evidence(context(T1), self.fetch(T1, [self.early, wrong, outside, missing, held]))
        self.assertEqual([p["evidence_id"] for p in result["observations"]], ["DEMO-GPS-V3-1"])
        self.assertEqual(result["summary"]["timing_comparisons"], [])
        self.assertEqual(result["source_relationships"], [])
        self.assertTrue(all(p["position_scope"] == "VEHICLE_ONLY" for p in result["observations"]))

    def test_summary_spans_chronological_extremes_across_vehicle_contexts(self):
        """List order is vehicle-grouped; the summary interval must still be first <= last in time."""
        trip, trip_vehicle = "DEMO-TRIP-V3-1", "DEMO-VEH-V3-0"   # sorts before VEH-V3-1 but runs later
        c = context(T1)
        c["nodes"] = [n for n in c["nodes"] if n["kind"] != "VehicleAssignment"] + [
            node(trip, "Trip", vehicle_id=trip_vehicle),
            node("DEMO-ASSIGN-V3-RUN", "VehicleAssignment", shipment_id=SID, route_run_id=RUN, vehicle_id=VEH,
                 valid_from="2026-09-19T08:00:00+00:00", valid_to="2026-09-19T10:00:00+00:00"),
            node("DEMO-ASSIGN-V3-TRIP", "VehicleAssignment", shipment_id=SID, trip_id=trip, vehicle_id=trip_vehicle,
                 valid_from="2026-09-19T10:00:00+00:00", valid_to="2026-09-19T18:00:00+00:00")]
        rows = {"route_run_positions": [self.early,
                                        position("DEMO-GPS-V3-RUN-2", "2026-09-19T09:30:00+00:00", "2026-09-19T09:31:00+00:00")],
                "trip_evidence_positions": [
                    position("DEMO-GPS-V3-TRIP-1", "2026-09-19T10:30:00+00:00", "2026-09-19T10:31:00+00:00",
                             vehicle_id=trip_vehicle, route_run_id=None, trip_id=trip),
                    position("DEMO-GPS-V3-TRIP-2", "2026-09-19T11:45:00+00:00", "2026-09-19T11:46:00+00:00",
                             vehicle_id=trip_vehicle, route_run_id=None, trip_id=trip)]}
        calls = []
        def fetch(name, **params):
            calls.append(name)
            return [copy.deepcopy(r) for r in rows[name] if r["props"]["vehicle_id"] == params["vehicle_id"]]
        result = build_route_evidence(c, fetch)
        listed = [p["evidence_id"] for p in result["observations"]]
        # Deterministic vehicle-grouped listing and source IDs are unchanged ...
        self.assertEqual(listed, ["DEMO-GPS-V3-TRIP-1", "DEMO-GPS-V3-TRIP-2", "DEMO-GPS-V3-1", "DEMO-GPS-V3-RUN-2"])
        self.assertEqual(result["summary"]["input_evidence_ids"], listed)
        self.assertEqual(sorted(calls), ["route_run_positions", "trip_evidence_positions"])
        # ... but the interval spans the actual earliest and latest returned observations.
        self.assertEqual(result["summary"]["first_observed_at"], "2026-09-19T09:00:00+00:00")
        self.assertEqual(result["summary"]["last_observed_at"], "2026-09-19T11:45:00+00:00")
        self.assertLessEqual(instant(result["summary"]["first_observed_at"]), instant(result["summary"]["last_observed_at"]))
        stamps = [instant(p["occurred_at"]) for p in result["observations"]]
        self.assertEqual(instant(result["summary"]["first_observed_at"]), min(stamps))
        self.assertEqual(instant(result["summary"]["last_observed_at"]), max(stamps))

    def test_unbound_run_is_not_queried(self):
        c = context(T1)
        c["nodes"] = [n for n in c["nodes"] if n["kind"] != "VehicleAssignment"]
        result = build_route_evidence(c, lambda *a, **k: self.fail("foreign query"))
        self.assertFalse(result["contexts"])
        self.assertFalse(result["observations"])

    def test_sentinel_preserves_real_endpoint_and_discloses_sampling(self):
        origin = datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)
        rows = [position(f"DEMO-GPS-BULK-{i:03d}", (origin + timedelta(minutes=i)).isoformat(),
                         (origin + timedelta(minutes=i, seconds=10)).isoformat()) for i in range(162)]
        def fetch(name, **params):
            if name == "route_run_positions_tail":
                return rows[-1:]
            self.assertEqual(name, "route_run_positions")
            self.assertEqual(params["limit"], 161)
            return rows[:params["limit"]]
        result = build_route_evidence(context(T1), fetch)
        self.assertEqual(len(result["observations"]), 160)
        self.assertEqual(result["observations"][0]["evidence_id"], "DEMO-GPS-BULK-000")
        self.assertEqual(result["observations"][-1]["evidence_id"], "DEMO-GPS-BULK-161")
        self.assertTrue(result["truncated"]["observations"])

    def test_real_world_and_tool_render_only_displayed_ids(self):
        fixture = small_world()
        assignment = next(n for n in fixture.world.of_kind("VehicleAssignment")
                          if n.properties.get("split") == "development" and n.properties.get("route_run_id"))
        sid = assignment.properties["shipment_id"]
        ctx = public_evidence(fixture.world, sid, fixture.world.config.as_of)
        port = MemoryPort(fixture.world)
        result = build_route_evidence(ctx, lambda name, **kw: port.fetch(name, as_of=ctx["as_of"], **kw))
        self.assertTrue(result["contexts"])
        self.assertTrue(result["observations"])
        self.assertTrue(all(n["id"] in {p["evidence_id"] for p in result["observations"]}
                            or n["id"] in {c["assignment_id"] for c in result["contexts"]}
                            or any(n["id"] in c["plan_source_ids"] + c["custody_source_ids"] for c in result["contexts"])
                            for n in result["source_nodes"]))
        belt = InvestigationTools(ctx, fixture.world.config, port=port.fetch)
        response = belt.call("route_observations", {})
        rendered = json.loads(response["result"].split(" CITABLE_EVIDENCE_IDS: ")[0])
        displayed = {r["evidence_id"] for r in rendered["vehicle_observations"]}
        self.assertLessEqual(len(displayed), 12)
        self.assertLessEqual(len(response["result"].split(" CITABLE_EVIDENCE_IDS: ")[0]), MAX_RESULT_CHARS)
        self.assertEqual({i for i in response["evidence_ids"] if i.startswith("DEMO-GPS-")}, displayed)
        self.assertTrue(all(r["position_scope"] == "VEHICLE_ONLY" for r in rendered["vehicle_observations"]))
        reader = OperationsReader.__new__(OperationsReader)
        reader.config = fixture.world.config
        reader.evidence = lambda shipment_id, as_of=None: ctx
        reader.rule_signals = lambda evidence: {}
        reader.fetch = lambda name, **kw: port.fetch(name, **kw)
        detail = reader.shipment_detail(sid)
        self.assertEqual([p["evidence_id"] for p in detail["route_layers"]["layers"]["vehicle_path"]],
                         [p["evidence_id"] for p in detail["route_evidence"]["observations"]])
        self.assertEqual(detail["route_evidence"]["as_of"], detail["as_of"])


if __name__ == "__main__":
    unittest.main()
