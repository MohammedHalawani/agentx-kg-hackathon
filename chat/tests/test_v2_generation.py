"""End-to-end offline foundation tests; no DB or provider dependency."""
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from dataset_v2.context import evidence_context
from dataset_v2.contracts import Config, canonical, instant
from dataset_v2.export import export_world
from dataset_v2.generate import CITIES, NORMAL_RECIPES, PERTURBATIONS, generate
from dataset_v2.load import read_bundle
from dataset_v2.validate import validate_world


class V2GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world=generate(Config(total=300))

    def test_complete_world_and_scenario_coverage(self):
        w=self.world
        report=validate_world(w)
        self.assertTrue(report["pass"],report["errors"][:10])
        self.assertEqual(report["statistics"]["flows"],{"C2C":90,"B2C":150,"B2B":60})
        self.assertEqual({n.properties["name"] for n in w.of_kind("City")},{c[1] for c in CITIES})
        self.assertEqual({row["recipe_id"] for row in w.gold.values()},set(NORMAL_RECIPES+PERTURBATIONS))
        groups={n.properties["holdout_group"] for n in w.of_kind("Case")}
        for sid,row in w.gold.items():
            self.assertEqual(sid not in groups,row["intended_healthy"],sid)
        self.assertEqual(report["statistics"]["healthy_no_case"],210)

    def test_deterministic_world_and_changed_seed(self):
        a=generate(Config(total=30,seed=42))
        b=generate(Config(total=30,seed=42))
        c=generate(Config(total=30,seed=43))
        self.assertEqual(a.manifest(),b.manifest())
        self.assertNotEqual(a.hashes(),c.hashes())
        self.assertEqual(len(a.of_kind("Shipment")),30)
        self.assertEqual(len(a.nodes),len(set(a.nodes)))
        self.assertEqual(len(a.edges),len(set(a.edges)))

    def test_session_configuration_and_overnight_linehaul(self):
        w=generate(Config(total=30,session_start="05:30",session_end="17:30"))
        report=validate_world(w)
        self.assertTrue(report["pass"],report["errors"][:10])
        sessions=w.of_kind("DeliverySession")
        self.assertTrue(sessions)
        self.assertTrue(all(n.properties["start_local"]=="05:30" for n in sessions))
        overnight=[n for n in w.of_kind("VehicleAssignment") if n.properties["mode"]=="linehaul"
                   and (instant(n.properties["valid_from"])+timedelta(hours=3)).date()
                   < (instant(n.properties["valid_to"])+timedelta(hours=3)).date()]
        self.assertTrue(overnight)

    def test_all_fleet_types_and_history_require_later_proof(self):
        w=self.world
        self.assertEqual({n.properties["type_id"] for n in w.of_kind("Vehicle")},
                         {"DEMO-VTYPE-"+key for key in ("LMV","LARGE","LHV","TRUCK","HEAVY")})
        cases=w.of_kind("Case")
        self.assertTrue(any(n.properties["state"]=="REOPENED" for n in cases))
        self.assertTrue(any(n.properties.get("invalidated") is True for n in w.of_kind("Outcome")))
        for outcome in w.of_kind("Outcome"):
            if outcome.properties["invalidated"]:continue
            self.assertEqual(outcome.properties["split"],"history")
            cutoff=instant(w.nodes[outcome.properties["holdout_group"]].properties["as_of"])
            proofs=[w.nodes[key] for key in outcome.properties["evidence_ids"] if w.nodes[key].kind=="DeliveryProof"]
            self.assertTrue(proofs)
            self.assertTrue(all(instant(p.properties["occurred_at"])>cutoff for p in proofs))

    def test_runtime_context_has_no_gold_future_history_or_other_groups(self):
        w=self.world
        sid=next(row["shipment_id"] for row in w.gold.values() if row["split"]=="history" and not row["intended_healthy"])
        context=evidence_context(w,sid)
        text=canonical(context)
        self.assertNotIn('"recipe_id"',text)
        self.assertNotIn('"split"',text)
        self.assertNotIn('"holdout_group"',text)
        self.assertNotIn("FOLLOWUP",text)
        withheld={"Case","Exception","Outcome","Resolution","Recommendation","Review","OperatorDecision","AnalysisRun","AuditEvent"}
        self.assertFalse(withheld & {n["kind"] for n in context["nodes"]})
        for row in context["nodes"]:
            original=w.nodes[row["id"]]
            self.assertIn(original.properties["holdout_group"],(None,sid))
            if original.properties.get("occurred_at"):
                self.assertLessEqual(instant(original.properties["occurred_at"]),instant(context["as_of"]))
        # A shared vehicle cannot reveal its other shipment-owned observations.
        selected={n["id"] for n in context["nodes"]}
        self.assertTrue(all(e["start"] in selected and e["end"] in selected for e in context["edges"]))

    def test_prior_time_context_does_not_leak_latest_tracking_status(self):
        w=self.world
        shipment=w.of_kind("Shipment")[0]
        before=instant(shipment.properties["occurred_at"])-timedelta(seconds=1)
        context=evidence_context(w,shipment.id,before.isoformat())
        # Creation itself is a timed record and is not yet observable.
        self.assertNotIn(shipment.id,{n["id"] for n in context["nodes"]})

    def test_atomic_export_is_byte_reproducible_and_importable_offline(self):
        w=generate(Config(total=30))
        with tempfile.TemporaryDirectory() as directory:
            first,second=Path(directory)/"first",Path(directory)/"second"
            export_world(w,first);export_world(generate(Config(total=30)),second)
            self.assertEqual(read_bundle(first).manifest,w.manifest())
            for path in first.iterdir():
                self.assertEqual(path.read_bytes(),(second/path.name).read_bytes())
            self.assertEqual(json.loads((first/"statistics.json").read_text())["shipments"],30)
            with self.assertRaises(ValueError):export_world(w,first)

    def test_corrupt_world_cannot_publish_a_pass_bundle(self):
        w=generate(Config(total=30))
        w.of_kind("Package")[0].properties["weight_kg"]=-1
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"bad"
            with self.assertRaises(ValueError):export_world(w,target)
            self.assertFalse(target.exists())


if __name__=="__main__":unittest.main()
