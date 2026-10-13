"""Structural checks of the sealed 240-shipment V3 profile; no historical answer files."""
from collections import defaultdict
import unittest

from dataset_v2.context import CONTEXT, OBSERVATIONS
from dataset_v2.contracts import instant
from operations.route_evidence import build_route_evidence
from tests.world_fixture import MemoryPort, small_world
from operations.reasoning import public_evidence
from world.v3_scenarios import (CASES, DATASET_ID, ROUTE_SCHEMA, SEED, _gateway_world, _route, assert_label_free,
                                config, delivery_providers)


class V3ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = small_world()
        cls.world = cls.fixture.world

    def owned(self, sid, kind):
        return [n for n in self.world.nodes.values() if n.kind == kind and n.properties.get("holdout_group") == sid]

    def test_fixed_profile_and_no_runtime_answer_keys(self):
        self.assertEqual((config().total, config().seed, config().dataset_id), (240, SEED, DATASET_ID))
        self.assertEqual(len(CASES), 8)
        self.assertEqual(len(set(CASES)), 8)
        self.assertTrue(all(self.world.nodes[sid].properties["split"] == "development" for sid in CASES))
        text = str(ROUTE_SCHEMA).lower()
        for forbidden in ("scenario_family", "expected_cause", "root_cause", "gold", "desired_outcome"):
            self.assertNotIn(forbidden, text)
        assert_label_free({"source_nodes": [{"id": "DEMO-SOURCE", "properties": {"source_ref": "telematics"}}]})
        with self.assertRaises(ValueError):
            assert_label_free({"source_nodes": [{"properties": {"expected_cause": "injected canary"}}]})

    def test_one_offline_device_has_three_distinct_shipments_and_late_receipts(self):
        build = self.fixture.build
        groups = defaultdict(set)
        for mid, sids in build.caused.items():
            mechanism = build.plan.items.get(mid)
            if mechanism and mechanism.type == "DEVICE_OUTAGE":
                groups[mechanism.params.get("device")].update(set(sids) & set(CASES))
        self.assertTrue(any({"DEMO-SHP-000133", "DEMO-SHP-000134", "DEMO-SHP-000194"} <= sids
                            for sids in groups.values()))
        for sid in ("DEMO-SHP-000133", "DEMO-SHP-000134", "DEMO-SHP-000194"):
            self.assertTrue(any(instant(n.properties["recorded_at"]) > instant(n.properties["occurred_at"])
                                for n in self.owned(sid, "ScanEvent")))

    def test_dispute_proof_and_photo_with_failed_authentication_are_separate_evidence(self):
        dispute = "DEMO-SHP-000182"
        self.assertTrue(self.owned(dispute, "RecipientReport"))
        self.assertTrue(self.owned(dispute, "DeliveryProof"))
        self.assertTrue(any(n.properties.get("result") == "PASS" for n in self.owned(dispute, "AuthenticationEvidence")))
        photo = "DEMO-SHP-000222"
        self.assertTrue(self.owned(photo, "PhotoEvidence"))
        self.assertTrue(any(n.properties.get("result") == "FAIL" for n in self.owned(photo, "AuthenticationEvidence")))
        self.assertTrue(self.owned(photo, "RecipientReport"))

    def test_delivering_provider_reaches_packet_like_the_live_envelope(self):
        """The gateway stamps each record with its delivering provider; offline packets must hydrate the same shared record."""
        imported, items = self.fixture.imported, self.fixture.items
        gateway = _gateway_world(imported, items)
        delivered_by = delivery_providers(items)
        fed = [key for key in gateway.nodes if key in delivered_by and key not in imported.nodes]
        self.assertTrue(fed)
        changed = 0
        for key in fed:
            domain = self.world.nodes[key].properties.get("provider_id")   # decoded payload only
            actual = gateway.nodes[key].properties.get("provider_id")
            if domain is None:
                self.assertEqual(actual, delivered_by[key], key)
                changed += 1
            else:
                self.assertEqual(actual, domain, key)    # the record's own provider is never replaced
        self.assertGreater(changed, 0)
        # Packet scope: re-attaching the envelope may add a delivering provider record to a visible record's
        # context, and nothing else. Compare against the same world decoded without envelopes.
        added = set()
        for sid in ("DEMO-SHP-000129", "DEMO-SHP-000226"):
            cutoff = gateway.config.as_of
            before, _, _ = _route(self.world, sid, cutoff)
            after, _, _ = _route(gateway, sid, cutoff)
            kinds = {n["id"]: n["kind"] for n in after["nodes"]}
            new = {n["id"] for n in after["nodes"]} - {n["id"] for n in before["nodes"]}
            self.assertFalse({n["id"] for n in before["nodes"]} - {n["id"] for n in after["nodes"]}, sid)
            self.assertTrue(all(kinds[key] == "Provider" for key in new), sid)
            visible = {delivered_by[n.id] for n in gateway.nodes.values()
                       if n.properties.get("holdout_group") == sid and n.id in delivered_by
                       and n.kind in CONTEXT | OBSERVATIONS and instant(n.properties["recorded_at"]) <= instant(cutoff)}
            self.assertLessEqual(new, visible, sid)    # only providers that delivered a visible record
            added |= new
        self.assertIn("DEMO-PROV-SPL", added)

    def test_vehicle_context_and_ordinary_single_stationary_sample(self):
        sid = "DEMO-SHP-000051"
        caused = set().union(*self.fixture.build.caused.values())
        self.assertNotIn(sid, caused)
        context = public_evidence(self.world, sid, self.world.config.as_of)
        port = MemoryPort(self.world)
        route = build_route_evidence(context, lambda name, **kw: port.fetch(name, as_of=context["as_of"], **kw))
        self.assertTrue(route["contexts"])
        self.assertTrue(any(p["speed_kmh"] is not None and p["speed_kmh"] < 3 for p in route["observations"]))
        self.assertEqual(route["summary"]["stationary_intervals"], [])
        self.assertTrue(all(p["position_scope"] == "VEHICLE_ONLY" for p in route["observations"]))


if __name__ == "__main__":
    unittest.main()
