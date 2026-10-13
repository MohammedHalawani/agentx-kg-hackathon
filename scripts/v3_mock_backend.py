"""Test-only: the integrated V3 backend with a MOCK provider, on the disposable race database.

For checking two active cases and stale-run protection through the real HTTP surface and the real frontend build
without a model: the real store, claims, worker loops, investigation graph, investigator loop, reviewer path and
provider gate run; only the provider call itself is replaced by a scripted double that waits and answers.

  database   ONLY `shipments-v2-world-v3-ci-20261013` (the unit tests' small synthetic world). The V3 development
             world and every other database are refused. Its operations ledger is reset here, as the race tests do.
  provider   a scripted double. Every reply says it is a mock; the investigator's conclusion is
             INSUFFICIENT_EVIDENCE and the reviewer sends the case to a person, so nothing is diagnosed, authorized,
             executed or verified from a mock. The model name recorded with each run is `mock/scripted-provider`.
             The real model client is never built and no key is read.
  limits     two investigation workers, provider limit 1 (the shipped cap). Two cases are INVESTIGATING at once
             while their provider calls take turns; that is overlap of claims, not of model inference.

GET /__mock/provider reports the double's own count of calls and the most it ever had in flight.

Run from `chat`:   uv run python ../scripts/v3_mock_backend.py [--port 8024] [--delay 5] [--cases 4]
It serves until stopped and never stops another process.
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TARGET = "shipments-v2-world-v3-ci-20261013"
MODEL_LABEL = "mock/scripted-provider"
NOTE = "MOCK PROVIDER: scripted reply for an integration test. No model was called and nothing here is a finding."


class MockChat:
    """Stands where the chat model would be. Waits `delay` seconds, then answers from a fixed script by role."""

    def __init__(self, delay):
        self.delay, self.lock = delay, threading.Lock()
        self.calls, self.inside, self.peak, self.by_role = 0, 0, 0, {}

    def invoke(self, messages, **kwargs):
        system = str(getattr(messages[0], "content", ""))
        role = ("investigator" if system.startswith("You are Suhail's investigation agent")
                else "reviewer" if system.startswith("You are Suhail's independent reviewer") else "other")
        with self.lock:
            self.calls += 1
            self.inside += 1
            self.peak = max(self.peak, self.inside)
            self.by_role[role] = self.by_role.get(role, 0) + 1
        try:
            time.sleep(self.delay)
            return SimpleNamespace(content=json.dumps(self.reply(role, messages)))
        finally:
            with self.lock:
                self.inside -= 1

    @staticmethod
    def reply(role, messages):
        if role == "investigator":
            seen = sum(str(getattr(m, "content", "")).startswith("TOOL RESULT") for m in messages[1:])
            if seen < 2:
                return {"action": "call", "tool": ("shipment_overview", "route_observations")[seen], "args": {},
                        "purpose": "Mock provider: read the case's records."}
            return {"action": "conclude", "primary_cause": "INSUFFICIENT_EVIDENCE", "confidence": "low",
                    "hypotheses": [{"cause": "INSUFFICIENT_EVIDENCE", "status": "uncertain", "supporting_evidence_ids": [],
                                    "contradicting_evidence_ids": [], "assessment": NOTE}],
                    "missing_evidence": ["An investigation by a real model: this run used a mock provider."],
                    "next_evidence_step": "Investigate this case with a real model; this reply is from a mock provider.",
                    "recommended_action": "REQUEST_ADDITIONAL_EVIDENCE", "requires_physical_check": False, "summary": NOTE}
        if role == "reviewer":
            return {"verdict": "HUMAN_REVIEW", "feedback": NOTE, "unsupported_claims": [], "unaddressed_contradictions": [],
                    "alternatives_tested": "no"}
        return {}

    def report(self):
        with self.lock:
            return {"provider": MODEL_LABEL, "calls": self.calls, "in_flight": self.inside, "peak_in_flight": self.peak,
                    "by_role": dict(self.by_role), "delay_seconds": self.delay}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8024)
    parser.add_argument("--delay", type=float, default=5.0, help="seconds each mock provider call takes")
    parser.add_argument("--cases", type=int, default=4, help="open at least this many cases before serving")
    args = parser.parse_args(argv)
    if args.port in (8022, 8023) or not 1024 < args.port < 65536:
        raise SystemExit("Refusing: ports 8022 and 8023 belong to the recording backend and the V3 backend")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            raise SystemExit(f"Refusing: port {args.port} is already in use; this harness never stops a process")

    for name in ("LLM_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY"):
        os.environ[name] = ""
    for name in ("SUHAIL_DEMO_SHIPMENTS", "SUHAIL_SIM_STATE_ROOT", "SUHAIL_LIVE_BUNDLE", "SUHAIL_EVAL_TRUTH_ROOT", "SUHAIL_DISABLED_TOOLS",
                 "SUHAIL_PREFETCH_OVERVIEW", "SUHAIL_TOOL_BATCH"):
        os.environ.pop(name, None)
    os.environ.update({"LLM_MODEL": MODEL_LABEL, "LLM_API_BASE": "", "SUHAIL_INVESTIGATION_WORKERS": "2",
                       "SUHAIL_PROVIDER_MAX_INFLIGHT": "1", "SUHAIL_CLAIM_LEASE_SECONDS": "180", "SUHAIL_CLAIM_HEARTBEAT_SECONDS": "15",
                       "SUHAIL_WORKER_PACE_SECONDS": "0", "SUHAIL_DEV_RESET": "1", "SUHAIL_NARRATION": "0", "SUHAIL_CANOPUS": "0",
                       "SUHAIL_V2_AGENTS": "gpt-oss", "SUHAIL_FRONTEND_NEXT_DIST": str(ROOT / "frontend-next" / "dist")})
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "chat"), str(ROOT)]
    import config
    if os.environ.get("SUHAIL_OPERATIONS_DATABASE") != TARGET or config.NEO4J_URI != "bolt://127.0.0.1:7687" \
            or TARGET in (config.NEO4J_DATABASE, config.SHIPMENT_DATABASE, config.CHAT_DATABASE):
        raise SystemExit(f"Refusing: this harness runs only on {TARGET} on the local server "
                         f"(SUHAIL_OPERATIONS_DATABASE names {os.environ.get('SUHAIL_OPERATIONS_DATABASE')!r})")

    from llm.pipeline import _llm
    mock = MockChat(args.delay)

    def never():
        raise RuntimeError("the real model client is not available in the mock backend")
    _llm._build_model = never
    _llm.model = lambda: mock
    _llm.model.cache_clear = lambda: None

    import main as server
    from backend import operations_api
    runtime = operations_api.get_runtime()
    if runtime is None or runtime.database != TARGET:
        raise SystemExit("Refusing: the operations runtime did not start on the disposable database")
    store = runtime.store
    store.reset_session("DEMO-OPERATOR-LOCAL", confirmation=store.reset_confirmation())
    # Advance the simulated clock until the monitor has opened enough cases; automatic investigation stays off.
    # One simulated day per step (a larger step would ingest the whole feed at once).
    for _ in range(40):
        opened = store.status()["session"]["monitor_opened"]
        if opened >= args.cases:
            break
        store.tick(seconds=86400, manual=True, speed=1)
        while store.status()["session"]["monitor_pending"] and store.status()["session"]["monitor_opened"] < args.cases:
            store.monitor_step()
    status = store.status()
    print(json.dumps({"database": runtime.database, "port": args.port, "provider": MODEL_LABEL, "cases_opened": status["session"]["monitor_opened"],
                      "workers": status["worker"]["concurrency"], "provider_limit": os.environ["SUHAIL_PROVIDER_MAX_INFLIGHT"],
                      "worker_state": status["worker"]["state"], "as_of": status["as_of"]}), flush=True)
    server.app.add_api_route("/__mock/provider", mock.report, methods=["GET"])
    server.app.router.routes.insert(0, server.app.router.routes.pop())      # ahead of the frontend's catch-all mount
    import uvicorn
    uvicorn.run(server.app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
