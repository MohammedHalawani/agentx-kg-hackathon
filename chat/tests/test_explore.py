"""Explore contract checks with fixture data; no writes or model requests."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "test")
os.environ.setdefault("NEO4J_PASSWORD", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import explore


def fixture(**extra):
    return {"shipment_id": "SHP-test", "status": "FAILED", "root_causes": [],
            "destinations": [], "attempts": 0, **extra}


class FakeDriver:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute_query(self, query, **kwargs):
        self.calls.append(kwargs)
        return self.rows, None, None


class ShipmentExploreTests(unittest.TestCase):
    def test_pending_recommendation_stays_attention_not_delivered(self):
        ship = explore.shipment_summary(fixture(pending_recommendation=True))
        self.assertTrue(ship["needs_attention"])
        self.assertFalse(ship["delivered"])
        self.assertEqual(ship["status"], "FAILED")

    def test_hub_delay_and_operational_priority_are_evidence_based(self):
        ship = explore.shipment_summary(fixture(
            unresolved=True, root_causes=["hub_delay"], attempts=2,
            policy={"sla_days": 2, "retry_limit": 2}, first_timestamp="2026-01-01T00:00:00",
            last_event={"event_type": "FAILED", "timestamp": "2026-01-04T00:00:00"},
        ))
        self.assertTrue(ship["stalled"])
        self.assertTrue(ship["critical"])
        self.assertTrue(ship["sla_breached"])
        self.assertTrue(ship["retry_budget_exhausted"])
        self.assertEqual(ship["priority_source"], "operational_rules")
        self.assertFalse(explore.shipment_summary(fixture(status="FAILED"))["needs_attention"])

    def test_invalid_points_dropped_and_origin_is_explicitly_approximate(self):
        ship = explore.shipment_summary(fixture(
            destinations=[{"lat": float("nan"), "lng": 46}, {"lat": True, "lng": 46},
                          {"lat": 91, "lng": 46}, {"lat": 24, "lng": 46, "city": "Riyadh"}],
            warehouse={"origin_warehouse_id": "WH-RUH", "origin_warehouse": "Riyadh"},
        ))
        self.assertEqual(len(ship["destinations"]), 1)
        self.assertTrue(ship["origin"]["approximate"])
        self.assertEqual(ship["origin"]["coordinate_source"], "city_centroid")

    def test_filter_and_graph_use_identical_shipment_membership(self):
        rows = [fixture(shipment_id="open", unresolved=True), fixture(shipment_id="done", status="DELIVERED")]
        driver = FakeDriver(rows)
        with patch.object(explore, "get_driver", return_value=driver), \
             patch.object(explore, "shipment_graph", return_value={"nodes": [], "relationships": []}) as graph:
            data = explore.overview("needs_attention", 1)
        self.assertEqual(data["counts"]["all"], 2)
        self.assertEqual(data["counts"]["delivered"], 1)
        self.assertEqual(data["shipments"][0]["shipment_id"], "open")
        graph.assert_called_once_with(["open"])
        self.assertEqual(driver.calls[0]["database_"], explore.config.SHIPMENT_DATABASE)

    def test_empty_filter_and_scan_boundary_are_explicit(self):
        with patch.object(explore, "get_driver", return_value=FakeDriver([fixture()])), \
             patch.object(explore, "shipment_graph", return_value={"nodes": [], "relationships": []}) as graph:
            self.assertEqual(explore.overview("delivered")["returned"], 0)
            graph.assert_called_once_with([])
        with patch.object(explore, "get_driver", return_value=FakeDriver([fixture()] * 1001)), \
             patch.object(explore, "shipment_graph", return_value={"nodes": [], "relationships": []}):
            data = explore.overview("all", 1)
        self.assertTrue(data["dataset_truncated"])
        self.assertEqual(data["counts_scope"], "first_1000_shipments")
        self.assertEqual(data["total"], 1000)
        self.assertTrue(data["truncated"])

    def test_api_validation_and_shapes(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from backend.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        self.assertEqual(client.get("/v1/explore?filter=lost").status_code, 422)
        self.assertEqual(client.get("/v1/explore?limit=51").status_code, 422)
        self.assertEqual(client.get("/v1/explore?limit=0").status_code, 422)
        self.assertEqual(client.get("/v1/graph?shipment_id=").status_code, 422)
        with patch.object(explore, "overview", return_value={"shipments": [], "counts": {"all": 0}, "graph": {"nodes": [], "relationships": []}}):
            self.assertEqual(client.get("/v1/explore").json()["shipments"], [])
        with patch.object(explore, "shipment_graph", return_value={"nodes": [], "relationships": []}) as graph:
            self.assertEqual(client.get("/v1/graph?shipment_id=unknown").status_code, 200)
            graph.assert_called_once_with(["unknown"])


if __name__ == "__main__":
    unittest.main()
