"""Offline invariants that must hold before generating a world or enabling a loader."""
import unittest
from dataclasses import asdict

from dataset_v2.contracts import Config, KINDS, Provenance, World, instant


class V2ContractTests(unittest.TestCase):
    def test_default_and_scaled_split_contract(self):
        self.assertEqual(Config().split_counts, {"history": 1200, "development": 400, "held_out": 400})
        self.assertEqual(sum(Config(total=31).split_counts.values()), 31)
        self.assertEqual(Config(total=50, history=20, development=15, held_out=15).history, 20)
        for values in ({"total": 2000, "history": 1200}, {"normal_fraction": .4},
                       {"start_at": "2026-01-01T00:00:00"}, {"session_end": "04:00"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Config(**values)

    def test_provenance_is_not_real_world_verification(self):
        world = World(Config(total=30))
        world.node("Outcome", "DEMO-OUT-1", provenance=Provenance.VERIFIED_OUTCOME)
        self.assertTrue(world.nodes["DEMO-OUT-1"].properties["synthetic"])
        self.assertEqual(len(Provenance), 7)
        self.assertTrue({"LocationPin", "DeliveryInstruction", "AuthenticationEvidence",
                         "PhotoEvidence", "DepotReconciliation", "HandoffEvidence"} <= KINDS)

    def test_conflicting_id_and_cross_split_edges_are_refused(self):
        world = World(Config(total=30))
        for key, split in (("DEMO-SHP-1", "history"), ("DEMO-SHP-2", "held_out")):
            world.node("Shipment", key, shipment_id=key, split=split)
        world.node("Package", "DEMO-PKG-1", shipment_id="DEMO-SHP-1", split="history")
        with self.assertRaises(ValueError):
            world.edge("DEMO-SHP-2", "HAS_PACKAGE", "DEMO-PKG-1")
        with self.assertRaises(ValueError):
            world.node("Package", "DEMO-PKG-1", shipment_id="DEMO-SHP-1", split="held_out")
        world.edge("DEMO-SHP-1", "HAS_PACKAGE", "DEMO-PKG-1")
        self.assertEqual(next(iter(world.edges.values())).properties["split"], "history")

    def test_serialization_and_manifest_have_no_wall_clock(self):
        a, b = World(Config(total=30)), World(Config(total=30))
        a.node("City", "DEMO-CITY-1")
        b.node("City", "DEMO-CITY-1")
        self.assertEqual(a.hashes(), b.hashes())
        self.assertEqual(a.manifest(), b.manifest())
        self.assertEqual(asdict(a.config), asdict(b.config))
        self.assertEqual(instant(a.config.as_of).utcoffset().total_seconds(), 0)


if __name__ == "__main__":
    unittest.main()
