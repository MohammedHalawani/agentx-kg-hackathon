"""V3 integration: what the merged backend serves, checked against the frozen contract suhail-v3-1.

The frozen examples (docs/v3/06-contract-examples.json) and their rules (docs/v3/08-interface-reference.md) are the
reference. Checked here, on the real store, read model and route projection of the merged branches:

  - GET /worker/status `worker.active_cases` and GET /cases/{id} `investigation_status` carry exactly the frozen
    fields, with the frozen nullability, for a queued, a running and a finished investigation;
  - the read model forwards the store's `investigation_status` unchanged, and the HTTP boundary turns its storage
    identifiers (DEMO-) into public ones (SYN-) without touching anything else;
  - `route_evidence` and the `vehicle_path` layer carry the frozen fields and literals;
  - the four concurrency settings default to one worker, one provider call, a 180 s lease and a 15 s renewal, and
    .env.example and the V3 launcher (scripts/v3_backend.ps1) say the same; the launcher is where V3 names its model.

In-memory ledger, scripted investigator and reviewer: no database, no model call.
"""
import json
import math
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dataset_v2.contracts import instant
from operations import claims, provider_gate
from operations.identifiers import public_value
from operations.read_model import CASE_STATES, OperationsReader
from operations.route_evidence import build_route_evidence
from tests import test_v3_concurrency as concurrency
from tests import test_v3_route_evidence as route
from tests.test_operations_read_model import make_reader
from tests.test_operations_store import approval_policy

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "docs" / "v3" / "06-contract-examples.json").read_text(encoding="utf-8"))
RUN_STATES = {"QUEUED", "RUNNING", "REVIEWED", "ABORTED", "FAILED"}
STAGES = {"extract", "retrieve", "classify", "retrieve_context", "recommend", "review", "writeback", "escalate"}
SETTINGS = {"SUHAIL_INVESTIGATION_WORKERS": "1", "SUHAIL_CLAIM_LEASE_SECONDS": "180",
            "SUHAIL_CLAIM_HEARTBEAT_SECONDS": "15", "SUHAIL_PROVIDER_MAX_INFLIGHT": "1"}


def wall(value):
    """A wall time as served: a UTC ISO 8601 string with an offset."""
    return isinstance(value, str) and instant(value).utcoffset() is not None


class FrozenContractTests(unittest.TestCase):
    def test_the_contract_in_this_checkout_is_the_approved_frozen_one(self):
        self.assertEqual((CONTRACT["contract_version"], CONTRACT["status"]), ("suhail-v3-1", "approved_frozen"))
        self.assertEqual(CONTRACT["id_boundary"], {"storage_prefix": "DEMO-", "http_prefix": "SYN-",
                                                   "conversion_module": "chat/operations/identifiers.py"})
        self.assertEqual(concurrency.STATUS_FIELDS, set(CONTRACT["finalized_case_status_http_example"]))


class InvestigationStatusTests(concurrency.Base):
    """The status projection, from the store through the read model to the HTTP boundary."""

    def check(self, status, example):
        self.assertEqual(set(status), set(example))
        for key in ("case_id", "shipment_id"):
            self.assertTrue(isinstance(status[key], str) and status[key].startswith("SYN-") and len(status[key]) <= 160, key)
        self.assertTrue(type(status["claim_epoch"]) is int and status["claim_epoch"] >= 0)
        self.assertTrue(type(status["state_version"]) is int and status["state_version"] >= 0)
        self.assertIn(status["workflow_state"], CASE_STATES)
        self.assertIn(status["run_status"], RUN_STATES)
        self.assertTrue(status["active_stage"] is None or status["active_stage"] in STAGES)
        self.assertTrue(wall(status["as_of"]))
        for key in ("started_at", "updated_at", "lease_expires_at"):
            self.assertTrue(status[key] is None or wall(status[key]), key)
        for key in ("worker_id", "claim_id", "run_id"):
            self.assertTrue(status[key] is None or isinstance(status[key], str), key)
        if status["final_result"] is not None:
            self.assertEqual(set(status["final_result"]), set(CONTRACT["finalized_case_status_http_example"]["final_result"]))
        self.assertNotIn("DEMO-", json.dumps(status))

    def test_case_detail_public_ids_resolve_in_the_real_run_evidence_maps(self):
        store, driver = self.make()
        case_id = self.queue(driver)[0]
        store.agents = concurrency.Hooked()
        with approval_policy():
            store.process_one(case_id=case_id, worker_id=concurrency.WORKERS[0])
        detail = public_value(store.case_detail(case_id))
        log = detail["run"]["result"]["investigation_log"]
        self.assertTrue(log["evidence_index"])
        for entry in log["rounds"]:
            for call in entry["tool_calls"]:
                for key in call["evidence_ids"]:
                    self.assertTrue(key.startswith("SYN-"))
                    self.assertIn(key, log["evidence_index"])
        for field in ("computed_results", "cited_external_records"):
            for key in log[field]:
                self.assertTrue(key.startswith("SYN-"))
                self.assertIn(key, log["evidence_index"])

    def served(self, store, case_id):
        """GET /cases/{id} as the server builds it: the read model over the store, then the public identifiers."""
        row = store.case_detail(case_id)
        reader, _ = make_reader(lambda query, params: [{"shipment_id": row["shipment_id"], "as_of": row["as_of"],
                                                        "workflow_state": row["workflow_state"], "state_version": row["state_version"]}])
        reader.shipment_detail = lambda sid, as_of: {"shipment_id": sid, "as_of": as_of, "evidence": {"nodes": [], "edges": []}}
        # The store's own case detail; its ledger graph and narration reads are not part of this check.
        reader.store = SimpleNamespace(case_detail=store.case_detail)
        detail = reader.case_detail(case_id)
        self.assertEqual(detail["investigation_status"], store.case_detail(case_id)["investigation_status"])      # forwarded unchanged
        return public_value(detail)["investigation_status"]

    def test_queued_running_and_finished_status_match_the_frozen_fields_through_the_read_model(self):
        store, driver = self.make()
        case_id = self.queue(driver)[0]
        example = CONTRACT["finalized_case_status_http_example"]
        queued = self.served(store, case_id)
        self.check(queued, example)
        self.assertEqual([queued[k] for k in ("run_status", "worker_id", "claim_id", "run_id", "started_at", "updated_at",
                                              "lease_expires_at", "final_result")], ["QUEUED", *[None] * 7])
        idle = public_value(store.status())["worker"]
        self.assertEqual((idle["active_count"], idle["active_cases"], idle["active_case_id"], idle["active_shipment_id"]), (0, [], None, None))
        seen = {}
        store.agents = concurrency.Hooked(lambda tools: seen.update(detail=self.served(store, case_id),
                                                                    worker=public_value(store.status())["worker"]))
        with approval_policy():
            result = store.process_one(case_id=case_id, worker_id=concurrency.WORKERS[0])
        running, worker = seen["detail"], seen["worker"]
        active = CONTRACT["worker_status_http_example"]["worker"]
        self.check(running, active["active_cases"][0])
        self.assertLessEqual(set(active), set(worker))                         # every frozen worker field is served
        self.assertEqual(worker["active_cases"], [running])                    # one projection in both places
        self.assertEqual((worker["concurrency"], worker["active_count"], worker["active_case_id"], worker["active_shipment_id"]),
                         (2, 1, running["case_id"], running["shipment_id"]))
        self.assertEqual((running["run_status"], running["worker_id"], running["final_result"]), ("RUNNING", "investigation-1", None))
        for key in ("worker_id", "claim_id", "run_id", "started_at", "updated_at", "lease_expires_at"):
            self.assertIsNotNone(running[key], key)                            # identities are required while active
        final = self.served(store, case_id)
        self.check(final, example)
        self.assertEqual((final["run_status"], final["active_stage"], final["lease_expires_at"], final["run_id"]),
                         ("REVIEWED", None, None, public_value(result["run_id"])))
        self.assertEqual((final["worker_id"], final["claim_id"], final["as_of"]), (running["worker_id"], running["claim_id"], running["as_of"]))
        self.assertIsNone(final["final_result"]["outcome_verification_status"])        # reviewed is not verified
        after = public_value(store.status())["worker"]
        self.assertEqual((after["active_count"], after["active_cases"]), (0, []))      # a finished run is not an active claim

    def test_two_active_cases_leave_the_single_ids_empty(self):
        store, driver = self.make()
        first, second = self.queue(driver)[:2]
        with concurrency.live_claim(store, case_id=first, worker_id=concurrency.WORKERS[0]), \
                concurrency.live_claim(store, case_id=second, worker_id=concurrency.WORKERS[1]):
            worker = public_value(store.status())["worker"]
        example = CONTRACT["worker_status_http_example"]["worker"]
        self.assertEqual((worker["active_count"], worker["concurrency"], worker["active_case_id"], worker["active_shipment_id"]),
                         (example["active_count"], example["concurrency"], example["active_case_id"], example["active_shipment_id"]))
        self.assertEqual(len(worker["active_cases"]), 2)
        self.assertEqual({item["worker_id"] for item in worker["active_cases"]}, set(concurrency.WORKERS))
        self.assertEqual(worker["active_cases"], sorted(worker["active_cases"], key=lambda item: (item["started_at"], item["case_id"])))
        for item in worker["active_cases"]:
            self.check(item, example["active_cases"][0])


class RouteEvidenceContractTests(unittest.TestCase):
    def setUp(self):
        rows = [route.position("DEMO-GPS-V3-1", "2026-09-19T09:00:00+00:00", "2026-09-19T09:01:00+00:00"),
                route.position("DEMO-GPS-V3-2", "2026-09-19T09:04:00+00:00", "2026-09-19T09:05:00+00:00")]
        self.context = route.context(route.T1)
        self.fetch = lambda name, **params: [dict(row, props=dict(row["props"])) for row in rows] if name == "route_run_positions" else []

    def test_route_evidence_carries_the_frozen_fields_and_literals(self):
        example = CONTRACT["route_evidence_http_example"]
        served = public_value(build_route_evidence(self.context, self.fetch))
        self.assertEqual(set(served), set(example))
        self.assertEqual((served["schema"], served["shipment_id"], served["as_of"]), ("route-evidence-v3-1", "SYN-SHP-V3-1", route.T1))
        self.assertEqual(set(served["truncated"]), set(example["truncated"]))
        self.assertTrue(all(type(flag) is bool for flag in served["truncated"].values()))
        self.assertTrue(0 < len(served["contexts"]) <= 4 and 0 < len(served["observations"]) <= 160)
        for item in served["contexts"]:
            self.assertEqual(set(item), set(example["contexts"][0]))
            self.assertTrue(item["route_run_id"] or item["trip_id"])
        optional = {"ingested_at"}
        for point in served["observations"]:
            self.assertLessEqual(set(example["observations"][0]) - optional, set(point))
            self.assertLessEqual(set(point), set(example["observations"][0]))
            self.assertEqual((point["position_scope"], point["classification"]), ("VEHICLE_ONLY", "observed_vehicle"))
            self.assertTrue(all(isinstance(point[k], str) and point[k].startswith("SYN-") for k in ("entity_id", "evidence_id", "vehicle_id")))
            self.assertTrue(math.isfinite(point["lat"]) and -90 <= point["lat"] <= 90 and math.isfinite(point["lng"]) and -180 <= point["lng"] <= 180)
            self.assertTrue(instant(point["occurred_at"]) <= instant(point["recorded_at"]) <= instant(served["as_of"]))
        summary = served["summary"]
        self.assertLessEqual(set(example["summary"]) - {"note"}, set(summary))
        self.assertLessEqual(set(summary), set(example["summary"]))
        self.assertEqual(summary["points_returned"], len(served["observations"]))
        self.assertTrue(len(summary["stationary_intervals"]) <= 4 and len(summary["timing_comparisons"]) <= 8)
        self.assertLessEqual(len(summary.get("note") or ""), 400)
        for interval in summary["stationary_intervals"]:
            self.assertEqual(set(interval), {"vehicle_id", "route_run_id", "trip_id", "first_observed_at", "last_observed_at",
                                             "threshold_kmh", "gap_limit_seconds", "input_evidence_ids"})
        shown = {point["evidence_id"] for point in served["observations"]}
        self.assertLessEqual(set(summary["input_evidence_ids"]), shown)
        for node in served["source_nodes"]:
            self.assertEqual(set(node), {"id", "kind", "properties"})
        for edge in served["source_relationships"]:
            self.assertEqual(set(edge), {"id", "kind", "start", "end", "properties"})
        text = json.dumps(served).lower()
        for forbidden in ("scenario", "cause", "diagnosis", "expected_", "truth", "holdout", "blame", "delivered"):
            self.assertNotIn(forbidden, text)

    def test_the_vehicle_path_layer_is_the_same_projection_with_the_frozen_fields(self):
        reader = OperationsReader.__new__(OperationsReader)
        reader.config = None
        reader.evidence = lambda shipment_id, as_of=None: self.context
        reader.rule_signals = lambda evidence: {}
        reader.fetch = lambda name, **params: self.fetch(name, **params)
        with mock.patch("operations.read_model.route_layers", return_value={"layers": {"vehicle_path": [], "actual_route": ["kept"]},
                                                                           "truncated": {"vehicle_path": False}}):
            detail = public_value(reader.shipment_detail(route.SID))
        example = CONTRACT["route_layers_http_extension_example"]
        path = detail["route_layers"]["layers"]["vehicle_path"]
        self.assertEqual([point["evidence_id"] for point in path], [point["evidence_id"] for point in detail["route_evidence"]["observations"]])
        for point in path:
            self.assertLessEqual(set(example["layers"]["vehicle_path"][0]), set(point))
            self.assertEqual((point["source"], point["position_scope"]), ("vehicle_telemetry_only", "VEHICLE_ONLY"))
        self.assertEqual(detail["route_layers"]["layers"]["actual_route"], ["kept"])                # the other layers are left alone
        self.assertEqual(detail["route_layers"]["truncated"]["vehicle_path"], detail["route_evidence"]["truncated"]["observations"])
        self.assertEqual(detail["route_evidence"]["as_of"], detail["as_of"])


class ShippedSettingsTests(unittest.TestCase):
    def test_the_code_defaults_are_one_worker_one_provider_call_and_the_frozen_lease(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in SETTINGS:
                os.environ.pop(name, None)
            lease = claims.lease_seconds()
            self.assertEqual((claims.investigation_workers(), provider_gate.max_inflight(), lease, claims.heartbeat_seconds(lease)),
                             (1, 1, 180.0, 15.0))
        self.assertEqual({claims.WORKERS_ENV, claims.LEASE_ENV, claims.HEARTBEAT_ENV, provider_gate.MAX_INFLIGHT_ENV}, set(SETTINGS))
        self.assertEqual((claims.WORKER_COUNTS, provider_gate.LIMITS), ((1, 2, 3, 4), (1, 2, 3, 4)))     # V3.4: up to four

    def test_env_example_documents_the_four_settings_at_their_defaults(self):
        lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        values = dict(line.split("=", 1) for line in lines if line and not line.startswith("#") and "=" in line)
        self.assertEqual({name: values.get(name) for name in SETTINGS}, SETTINGS)

    def test_the_v3_launcher_sets_the_four_settings_its_own_target_and_the_model(self):
        text = (ROOT / "scripts" / "v3_backend.ps1").read_text(encoding="utf-8")
        self.assertRegex(text, r"\[ValidateSet\(1, 2\)\]\[int\]\$Workers = 1\b")
        self.assertRegex(text, r"\[ValidateSet\(1, 2\)\]\[int\]\$ProviderMaxInflight = 1\b")
        for line in ("SUHAIL_INVESTIGATION_WORKERS   = \"$Workers\"", "SUHAIL_PROVIDER_MAX_INFLIGHT   = \"$ProviderMaxInflight\"",
                     "SUHAIL_CLAIM_LEASE_SECONDS     = '180'", "SUHAIL_CLAIM_HEARTBEAT_SECONDS = '15'",
                     "SUHAIL_DEV_RESET               = '0'", "$Port = 8023", "$Database = 'shipments-v2-world-v3-20261013'",
                     "$StateRoot = 'C:\\Projects\\suhail-v3-state\\world-v3-20261013'", "$Model = 'openai/gpt-oss:120b'"):
            self.assertIn(line, text)
        # It starts one process and never stops one; the recording backend's port and database are not its targets.
        self.assertEqual(len(re.findall(r"\bStart-Process\b", text)), 1)
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        for forbidden in ("Stop-Process", "taskkill", "--reload", "--workers", "8022", "shipments-v2-world-ux-test", "C:\\Projects\\demo"):
            self.assertNotIn(forbidden, code)
        self.assertNotRegex(code, r"(?i)(api_key|password)\s*=")


if __name__ == "__main__":
    unittest.main()
