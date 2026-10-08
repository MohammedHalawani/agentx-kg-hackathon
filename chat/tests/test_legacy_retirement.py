"""Retired API routes must never invoke the unrelated domain tools."""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main


class RetiredSurfaceTests(unittest.TestCase):
    def test_legacy_chat_returns_gone_without_starting_agent(self):
        with patch.object(main, "stream_agent") as agent, TestClient(main.app) as client:
            response = client.post("/chat", json={"message": "shipment context"})
        self.assertEqual(response.status_code, 410)
        agent.assert_not_called()

    def test_legacy_registry_returns_gone_without_database_lookup(self):
        with patch("core.registry.registry_options") as lookup, TestClient(main.app) as client:
            response = client.get("/registry/Committee")
        self.assertEqual(response.status_code, 410)
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
