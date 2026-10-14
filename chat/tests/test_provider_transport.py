"""Real LiteLLM/OpenAI HTTP transport, against an ephemeral loopback server only."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import litellm
from langchain_core.messages import HumanMessage
from llm.pipeline import _llm
from operations import investigator, provider_gate


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status, self.stall = 503, False
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                test.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                if test.stall:
                    time.sleep(0.5)
                payload = json.dumps({"error": {"message": "offline failure", "type": "server_error"}}).encode()
                try:
                    self.send_response(test.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.gate = provider_gate.ProviderGate(1)
        previous = provider_gate.use(self.gate)
        self.addCleanup(provider_gate.use, previous)
        _llm.model.cache_clear()
        self.addCleanup(_llm.model.cache_clear)
        for patcher in (
            patch.object(_llm.config, "LLM_API_BASE", f"http://127.0.0.1:{self.server.server_port}/v1"),
            patch.object(_llm.config, "LLM_API_KEY", "offline-placeholder"),
            patch.object(_llm.config, "LLM_TIMEOUT_SECONDS", 0.15),
            patch.object(litellm, "telemetry", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = _llm.model()
        self.assertEqual(self.client._client_params["max_retries"], 0)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def attempt(self):
        return _llm.invoke([HumanMessage("offline transport probe")], client=self.client)

    def test_503_has_exactly_one_http_request(self):
        with self.assertRaises(litellm.ServiceUnavailableError):
            self.attempt()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.gate.snapshot()["inflight"], 0)

    def test_429_has_exactly_one_http_request(self):
        self.status = 429
        with self.assertRaises(litellm.RateLimitError):
            self.attempt()
        self.assertEqual(len(self.requests), 1)

    def test_http_timeout_has_exactly_one_http_request(self):
        self.stall = True
        with self.assertRaises(litellm.Timeout):
            self.attempt()
        self.close_server()  # Drain delayed handlers before asserting no late retry.
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.gate.snapshot()["inflight"], 0)

    def test_explicit_reviewer_retry_is_counted_and_sends_two_requests(self):
        session = investigator.Session(cap=12)

        def ask(*args):
            self.attempt()

        result = investigator.review({}, {}, {}, [], ask=ask, session=session, repair=False)
        self.assertEqual(result["verdict"], "UNAVAILABLE")
        self.assertEqual(session.budget.snapshot()["model_calls_by_role"], {"reviewer": 2})
        self.assertEqual(session.budget.used, 2)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.gate.snapshot()["inflight"], 0)


if __name__ == "__main__":
    unittest.main()
