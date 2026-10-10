"""The redesigned interface is served under /app/ without touching the API or the old frontend."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main


class FrontendNextMountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = Path(self.tmp.name) / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("<!doctype html><title>Suhail</title>", encoding="utf-8")
        (self.dist / "assets" / "app.js").write_text("console.log('suhail')", encoding="utf-8")
        (self.dist / "suhail.svg").write_text("<svg/>", encoding="utf-8")
        (Path(self.tmp.name) / "secret.txt").write_text("outside the build", encoding="utf-8")
        patcher = patch.object(main, "_NEXT", self.dist)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)

    def test_shell_and_assets_are_served_under_app(self):
        root = self.client.get("/app/")
        self.assertEqual(root.status_code, 200)
        self.assertIn("Suhail", root.text)
        self.assertEqual(root.headers["cache-control"], "no-cache")
        self.assertEqual(self.client.get("/app", follow_redirects=False).headers["location"], "/app/")
        asset = self.client.get("/app/assets/app.js")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("javascript", asset.headers["content-type"])
        self.assertEqual(self.client.get("/app/suhail.svg").status_code, 200)

    def test_page_routes_fall_back_to_the_shell_but_missing_files_do_not(self):
        for page in ("/app/operations", "/app/audit", "/app/explore", "/app/decisions", "/app/cases/SYN-CASE-0001"):
            response = self.client.get(page)
            self.assertEqual(response.status_code, 200, page)
            self.assertIn("Suhail", response.text)
        self.assertEqual(self.client.get("/app/assets/missing.js").status_code, 404)
        self.assertEqual(self.client.get("/app/missing.png").status_code, 404)

    def test_nothing_outside_the_build_is_served(self):
        for path in ("/app/../secret.txt", "/app/%2e%2e/secret.txt", "/app/..%2fsecret.txt", "/app/assets/../../secret.txt"):
            response = self.client.get(path)
            self.assertNotIn("outside the build", response.text, path)

    def test_an_unbuilt_interface_is_a_404_not_a_substitute(self):
        with patch.object(main, "_NEXT", Path(self.tmp.name) / "absent"):
            self.assertEqual(self.client.get("/app/").status_code, 404)
            self.assertEqual(self.client.get("/app/operations").status_code, 404)

    def test_api_routes_of_the_same_names_still_answer_with_data(self):
        """/audit, /explore, /decisions and /cases/... stay API routes; only /app/... is the interface."""
        from types import SimpleNamespace
        from unittest.mock import Mock
        from backend import operations_api as api
        page = {"items": [], "filtered_total": 0, "next_cursor": None, "previous_cursor": None, "metadata": {"synthetic": True}}
        reader = Mock()
        for name in ("queue", "audit", "explore"):
            getattr(reader, name).return_value = page
        reader.decisions.return_value = {"synthetic": True, "development": {"case_counts": {}}}
        runtime = SimpleNamespace(reader=reader, store=Mock(), database="shipments-v2-demo", workers=SimpleNamespace(status=lambda: {}))
        with patch.object(api, "get_runtime", return_value=runtime):
            for route in ("/audit", "/explore", "/cases/queue"):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200, route)
                self.assertEqual(response.json()["items"], [], route)
            self.assertTrue(self.client.get("/decisions").json()["synthetic"])
        session = self.client.get("/operations/session", headers={"host": "127.0.0.1"})
        self.assertIn(session.status_code, (200, 403))
        self.assertNotIn("<!doctype", session.text.lower())


if __name__ == "__main__":
    unittest.main()
