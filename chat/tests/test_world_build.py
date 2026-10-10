"""World-1: physics, observation, truth isolation, tells, splits, feed round trip and the bundle reader. No database.

One small world (240 shipments over 6 booking days) is built once for the module, with scaled-down over-sampling
rates (about 1-2 affected shipments per mechanism and split) so every mechanism still occurs in every split. The
pre-run tell test builds a second small world (seed + 1).
"""
from collections import defaultdict
from datetime import timedelta
import json
from pathlib import Path
import re
import tempfile
import unittest

from dataset_v2.contracts import canonical, instant
from dataset_v2.feed import ENVELOPE, Reference, decode
from world.config import MECHANISM_RATES, WorldConfig, uniform_rates
from world.mechanisms import MECHANISM_TYPES
from world.monitor import deliver_at
from world.pipeline import build_and_validate
from world.schedule import SCHEDULED
from world.truth import canary_token, labels_at, labels_at_estimate
from world import validate as V

CONFIG = WorldConfig(total=240, days=6, seed=11, dataset_id="DEMO-SUHAIL-WORLD-TEST", rates=uniform_rates(.004, .016))
REPO = Path(__file__).resolve().parents[2]


class WorldBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build, cls.report, cls.replays = build_and_validate(CONFIG, with_heldout=True, replay_splits=("development",))
        cls.dev = cls.build.exports["development"]
        cls.held = cls.build.exports["held_out"]
        world = cls.build.world
        cls.delivered = {nid: deliver_at(world.nodes[nid]) for nid in cls.build.observer.records
                         if nid in world.nodes and world.nodes[nid].properties.get("recorded_at")}

    def ingested(self, t):
        return {nid for nid, when in self.delivered.items() if when <= t}

    # ------------------------------------------------------------------ validation sections
    def test_physics_holds(self):
        physics = self.report["physics"]
        self.assertTrue(physics["pass"], physics["failed_counts"])
        for code in ("ONE_PLACE_AT_A_TIME", "PARCEL_CONSERVATION", "CUSTODY_CONTINUITY", "CUSTODY_MATCHES_LOCATION", "CONTAINER_CONTENTS",
                     "VEHICLE_CAPACITY", "DRIVER_ONE_VEHICLE", "TRAVEL_TIME_VS_DISTANCE", "THROUGHPUT_WITHIN_CAPACITY", "SCAN_WHERE_PARCEL_IS"):
            self.assertGreater(physics["checked"][code], 0, code)

    def test_observation_holds(self):
        observation = self.report["observation"]
        self.assertTrue(observation["pass"], observation["failed_counts"])
        self.assertGreater(observation["out_of_order_pairs"], 0)
        self.assertGreater(observation["retransmitted_messages"], 0)
        self.assertGreater(observation["checked"]["NO_HEARTBEAT_DURING_OUTAGE"], 0)

    def test_foundation_validation_fails_only_on_documented_rules_with_replacements(self):
        for split, export in self.report["exports"].items():
            foundation = export["foundation"]
            self.assertTrue(foundation["pass"], (split, foundation["documented_exceptions"]))
            self.assertTrue(set(foundation["error_codes"]) <= set(V.ALLOWED_FOUNDATION), foundation["error_codes"])

    def test_truth_never_reaches_nodes_edges_or_feed(self):
        for split, export in self.report["exports"].items():
            self.assertTrue(export["isolation"]["pass"], (split, export["isolation"]["hits"]))
            self.assertTrue(export["isolation"]["canary_checked"])
            self.assertEqual(export["isolation"]["canary_hits"], 0)

    def test_no_single_field_value_tells_the_mechanism(self):
        tells = self.report["tells"]
        self.assertTrue(tells["pass"], (tells["development"]["tells"], tells["world"]["tells"]))

    def test_every_scheduled_mechanism_reaches_its_target_in_every_split(self):
        affected = self.report["coverage"]["affected_shipments"]
        sizes = defaultdict(int)
        for row in self.build.truth.values():
            sizes[row["split"]] += 1
        for mtype in SCHEDULED:
            for split in ("history", "development", "held_out"):
                self.assertGreaterEqual(affected.get(mtype, {}).get(split, 0), CONFIG.target(mtype, split, sizes[split]), (mtype, split))

    # ------------------------------------------------------------------ addendum B4: committed rates
    def test_over_sampling_rates_are_committed_and_recorded_in_the_manifest(self):
        from world.build import world_manifest
        self.assertEqual(set(MECHANISM_RATES), set(SCHEDULED))
        self.assertEqual(WorldConfig().rates, tuple((m, h, l) for m, (h, l) in sorted(MECHANISM_RATES.items())))
        imported, items, truth, live_start = self.dev
        weighting = world_manifest(self.build, "development", imported, items, truth)["scenario_weighting"]
        self.assertEqual(set(weighting["rates"]), set(SCHEDULED))
        self.assertEqual(weighting["targets"]["development"]["WRONG_GATE"],
                         CONFIG.target("WRONG_GATE", "development", weighting["achieved"]["development"]["shipments"]))

    # ------------------------------------------------------------------ detectors catch what they should
    def test_isolation_scan_catches_an_injected_mechanism_word_and_the_canary(self):
        imported, items, truth, start = self.dev
        sid = next(s for s, r in truth.items() if r["split"] == "history")
        node = imported.nodes[sid]
        original = dict(node.properties)
        for note in ("suspected device_outage at depot", "ref " + canary_token(CONFIG), "see W1M-00012"):
            try:
                node.properties["note"] = note
                self.assertFalse(V.isolation(self.build, imported, [])["pass"], note)
            finally:
                node.properties.clear()
                node.properties.update(original)

    def test_tell_detector_catches_an_injected_tell(self):
        world = self.build.world
        per_type = defaultdict(set)
        for sid, r in self.build.truth.items():
            for m in r["mechanisms"]:
                if m["type"] not in V.TELL_EXCLUDED:
                    per_type[m["type"]].add(sid)
        # A mechanism common enough for the support floor (5) and rare enough to count as rare (<= 20%).
        mtype = max((t for t, s in per_type.items() if 5 <= len(s) <= .2 * len(self.build.truth)), key=lambda t: (len(per_type[t]), t))
        sids = sorted(per_type[mtype])
        injected = []
        for sid in sids:
            node = world.nodes[sid]
            node.properties["gate_flag"] = "MISMATCH"
            injected.append(node)
        try:
            tells = V.tells(self.build)
            self.assertFalse(tells["pass"])
            self.assertIn(["Shipment", "gate_flag", "MISMATCH"], [row["feature"] for row in tells["world"]["tells"]])
        finally:
            for node in injected:
                node.properties.pop("gate_flag")

    # ------------------------------------------------------------------ addendum B3: pre-run tell test
    def test_lookup_classifier_does_not_beat_the_rule_code_baseline_on_another_seed(self):
        result = self.report["tell_test"]
        self.assertTrue(result["pass"], result["ambiguous"])
        self.assertNotEqual(result["train"]["seed"], result["test"]["seed"])
        self.assertGreater(result["ambiguous"]["cases"], 0)

    def test_tell_test_catches_a_value_that_names_the_cause(self):
        def cases(seed, tell):
            out = {}
            for i in range(40):
                cause = ("CUSTODY_GAP", "DELAYED_SYNC")[(i * 7 + seed) % 5 < 2]
                features = {"ScanEvent.observation_type=HANDHELD_RECEIPT", f"Device.batch={(i + seed) % 3}"}
                if tell:
                    features.add(f"ScanEvent.lane_hint={'A' if cause == 'DELAYED_SYNC' else 'B'}")
                out[f"{seed}-{i}"] = {"symptoms": "CUSTODY_TRANSFER_UNCONFIRMED", "codes": ["CUSTODY_GAP"], "features": features,
                                      "causes": [cause], "ambiguous": True}
            return out
        clean = V.tell_test_cases(cases(1, False), cases(2, False))
        self.assertTrue(clean["pass"], clean["ambiguous"])
        told = V.tell_test_cases(cases(1, True), cases(2, True))
        self.assertFalse(told["pass"], told["ambiguous"])
        self.assertEqual(told["ambiguous"]["lookup_accuracy"], 1.0)

    # ------------------------------------------------------------------ truth format (addendum A1, B2)
    def test_truth_rows_carry_mechanisms_discrimination_specs_and_the_canary(self):
        canary = canary_token(CONFIG)
        for sid, row in self.build.truth.items():
            for key in ("split", "healthy", "root_cause", "acceptable_causes", "expected_resolution", "physical", "mechanisms",
                        "knowable_at_estimate"):
                self.assertIn(key, row)
            self.assertEqual(row["canary"], canary)
            self.assertNotIn("knowable_at", row)
            for m in row["mechanisms"]:
                for key in ("mechanism_id", "type", "cause_code", "started_at", "knowable_at_estimate", "discrimination", "evidence_ids",
                            "resolution", "action"):
                    self.assertIn(key, m)
                self.assertIn(m["type"], MECHANISM_TYPES)
                spec = m["discrimination"]
                self.assertTrue({"opening_symptoms", "shares_opening_with", "alternative_mechanisms", "any_of"} <= set(spec))
                for group in spec["any_of"]:
                    for item in group["all_of"]:
                        self.assertEqual(len(item), 1)
                        self.assertIn(next(iter(item)), ("record", "absence"))
            self.assertEqual(row["healthy"], not any(m["resolution"] != "NONE" for m in row["mechanisms"]))

    def test_discrimination_specs_are_machine_checkable(self):
        result = self.report["discrimination"]
        self.assertTrue(result["pass"], result["failed_counts"])
        for code in ("RECORD_ITEM_IS_AN_OBSERVATION", "ABSENCE_MATCHES_RECOMPUTED", "ABSENCE_IS_REAL", "ESTIMATE_RECOMPUTES"):
            self.assertGreater(result["checked"].get(code, 0), 0, code)

    def test_labels_at_decides_from_the_ingestion_log(self):
        rows = [r for r in self.build.truth.values() if not r["healthy"] and r["knowable_at_estimate"]]
        self.assertTrue(rows)
        for row in rows:
            first = instant(row["knowable_at_estimate"])   # The primary mechanism is the earliest identifiable one.
            before = first - timedelta(seconds=1)
            self.assertEqual(labels_at(row, before, self.ingested(before)), ["INSUFFICIENT_EVIDENCE"], row["shipment_id"])
            self.assertIn(row["root_cause"], labels_at(row, first, self.ingested(first)))
            self.assertEqual(labels_at_estimate(row, first), labels_at(row, first, self.ingested(first)))
        # The same instant with nothing ingested: only absence items can be satisfied, so record-only specs say nothing.
        record_only = [r for r in rows if all("record" in i for m in r["mechanisms"] for g in m["discrimination"]["any_of"] for i in g["all_of"])]
        self.assertTrue(record_only)
        for row in record_only:
            self.assertEqual(labels_at(row, self.build.config.end_at, set()), ["INSUFFICIENT_EVIDENCE"])
        healthy = next(r for r in self.build.truth.values() if r["healthy"])
        self.assertEqual(labels_at(healthy, healthy["promise_at"], set()), [])

    def test_ambiguous_cases_are_counted_and_mostly_identifiable(self):
        ambiguity = self.replays["development"]["ambiguity"]
        self.assertGreater(ambiguity["ambiguous"], 0)
        self.assertEqual(ambiguity["identifiable_ambiguous"] + ambiguity["unidentifiable_ambiguous"], ambiguity["ambiguous"])
        self.assertGreater(ambiguity["identifiable_ambiguous"], ambiguity["ambiguous"] // 2)

    # ------------------------------------------------------------------ splits and feed
    def test_development_export_leaves_held_out_days_out_and_feeds_live_records(self):
        imported, items, truth, live_start = self.dev
        held = {sid for sid, r in self.build.truth.items() if r["split"] == "held_out"}
        self.assertFalse(held & set(imported.nodes))
        self.assertFalse(any(n.properties.get("holdout_group") in held for n in imported.nodes.values()))
        fed_owners = {self.build.world.nodes[i["source_event_id"]].properties.get("holdout_group") for i in items}
        self.assertFalse(held & fed_owners)
        history = {sid for sid, r in self.build.truth.items() if r["split"] == "history"}
        self.assertFalse(history & fed_owners)
        live = {sid for sid, r in self.build.truth.items() if r["split"] == "development"}
        for node in imported.nodes.values():
            owner = node.properties.get("holdout_group")
            if owner in live:
                self.assertEqual(node.properties["recorded_at"], imported.nodes[owner].properties["recorded_at"], node.id)
        self.assertEqual(imported.config.split_counts, {"history": len(history), "development": len(live)})

    def test_held_out_export_imports_history_and_development_in_full(self):
        imported, items, truth, live_start = self.held
        held = {sid for sid, r in self.build.truth.items() if r["split"] == "held_out"}
        self.assertEqual({n.id for n in imported.nodes.values() if n.kind == "Shipment" and n.properties["split"] == "development"}, held)
        self.assertGreater(sum(1 for n in imported.nodes.values() if n.kind == "Outcome"), 0)

    def test_every_feed_message_decodes_to_its_record_exactly(self):
        imported, items, truth, live_start = self.dev
        ref = Reference.from_world(imported)
        world = self.build.world
        for item in items:
            kind, entity, sid, occurred, props = decode(item["channel"], item["message_type"], json.loads(item["payload_json"]), ref)
            node = world.nodes[entity]
            self.assertEqual(kind, node.kind)
            self.assertEqual(occurred, node.properties["occurred_at"])
            self.assertEqual(canonical(props), canonical({k: v for k, v in node.properties.items() if k not in ENVELOPE}), entity)
            self.assertGreaterEqual(instant(item["deliver_at"]), instant(node.properties["recorded_at"]))

    # ------------------------------------------------------------------ history precedents (addendum A2, B5)
    def test_history_outcomes_give_the_precedents_query_real_rows(self):
        imported = self.dev[0]
        outcomes = [n for n in imported.nodes.values() if n.kind == "Outcome"]
        self.assertTrue(outcomes)
        self.assertTrue(all(n.properties["split"] == "history" and n.properties["verification_status"] == "VERIFIED" for n in outcomes))
        self.assertEqual({type(n.properties["success"]) for n in outcomes}, {bool})

    def test_no_precedent_leaks_across_the_cutoff(self):
        from world.build import CUTOFF_EXEMPT, mechanism_active_until
        result = self.report["precedent_cutoff"]
        self.assertTrue(result["pass"], result["failed_counts"])
        for split, (imported, items, truth, live_start) in self.build.exports.items():
            outcomes = [n for n in imported.nodes.values() if n.kind == "Outcome"]
            for outcome in outcomes:
                self.assertLess(instant(outcome.properties["verified_at"]), live_start, outcome.id)
                sid = outcome.properties["holdout_group"]
                for m in self.build.truth[sid]["mechanisms"]:
                    if m["type"] not in CUTOFF_EXEMPT:
                        until = mechanism_active_until(self.build, m, sid)
                        self.assertIsNotNone(until, (sid, m["mechanism_id"]))
                        self.assertLess(until, live_start, (sid, m["mechanism_id"]))
            excluded = self.build.history_reports[split]["not_imported"]
            self.assertFalse(set(excluded) & {n.properties["holdout_group"] for n in outcomes})

    def test_history_authoring_reads_no_truth_labels(self):
        from operations.authority import default_action
        from world.monitor import by_specificity
        source = (Path(__file__).resolve().parents[1] / "world" / "history.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        body = code.split('"""', 2)[2]   # Skip the module docstring.
        for word in ("truth", "mechanism", "cause_code", "root_cause", "MECHANISM", "CATALOGUE", "world.truth", "world.mechanisms"):
            self.assertNotIn(word, body.replace("not_imported", ""), word)
        imported = self.dev[0]
        for rec in (n for n in imported.nodes.values() if n.kind == "Recommendation"):
            case = next(n for n in imported.nodes.values() if n.kind == "Case" and n.properties["holdout_group"] == rec.properties["holdout_group"])
            allowed = {default_action(c) for c in by_specificity(case.properties["codes"])}
            self.assertIn(rec.properties["action_type"], allowed)

    # ------------------------------------------------------------------ monitor replay
    def test_monitor_replay_measures_false_positives_and_shared_opening_symptoms(self):
        replay = self.replays["development"]
        self.assertGreater(replay["healthy"]["shipments"], 0)
        self.assertGreater(replay["abnormal"]["opened"], 0)
        self.assertTrue(any(row["distinct_mechanisms"] >= 2 for row in replay["per_opening_symptom_set"].values()))

    # ------------------------------------------------------------------ bundle files, truth directory, guards (addendum B1)
    def test_bundle_round_trip_through_the_world_reader_without_truth(self):
        from world.export import read_world_bundle, write_bundle
        canary = canary_token(CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"
            write_bundle(self.build, "development", target, self.report, self.replays["development"])
            bundle, items = read_world_bundle(target)
            imported = self.dev[0]
            self.assertEqual(bundle.manifest, imported.manifest())
            self.assertEqual(len(items), len(self.dev[1]))
            names = {p.name for p in target.iterdir()}
            self.assertTrue({"nodes.jsonl", "edges.jsonl", "gold.jsonl", "feed.jsonl", "manifest.json", "validation.json",
                             "statistics.json", "feed_manifest.json", "world_manifest.json", "world_validation.json", "private"} <= names)
            self.assertNotIn("truth.jsonl", names)
            private = {p.name for p in (target / "private").iterdir()}
            self.assertTrue({"parcels.jsonl", "containers.jsonl", "devices.jsonl", "recipients.jsonl", "routes.jsonl", "trips.jsonl"} <= private)
            self.assertFalse({"mechanisms.jsonl", "record_index.jsonl", "acts.jsonl", "truth.jsonl"} & private)
            mechanism_words = re.compile("|".join(sorted(MECHANISM_TYPES)))
            for path in [*target.glob("*.jsonl"), *(target / "private").glob("*.jsonl")]:
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("W1M-", text, path.name)
                self.assertNotIn(canary, text, path.name)
                if path.parent.name == "private":
                    self.assertIsNone(mechanism_words.search(text), path.name)
            with self.assertRaises(ValueError):
                write_bundle(self.build, "development", target, self.report, self.replays["development"])

    def test_truth_labels_are_written_outside_the_repository(self):
        from world.export import read_truth_labels, truth_directory, write_truth
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn(REPO, Path(tmp).resolve().parents)
            target = Path(write_truth(self.build, tmp, self.replays, self.build.history_reports))
            self.assertEqual(target, Path(tmp).resolve() / CONFIG.dataset_id)
            rows = [json.loads(line) for line in (target / "truth.jsonl").open(encoding="utf-8")]
            self.assertEqual(len(rows), len(self.build.truth))
            self.assertEqual({r["canary"] for r in rows}, {canary_token(CONFIG)})
            labels = read_truth_labels(tmp, CONFIG.dataset_id)
            self.assertEqual(len(labels["mechanism_ids"]), len(self.build.plan.items))
            with self.assertRaises(ValueError):
                write_truth(self.build, tmp, self.replays, self.build.history_reports)
        for inside in (REPO, REPO / "artifacts" / "truth", Path(tempfile.gettempdir()) / "artifacts"):
            with self.assertRaises(ValueError):
                truth_directory(inside, CONFIG.dataset_id)

    def test_backend_and_operations_never_read_the_truth_label_path(self):
        banned = re.compile(r"suhail-eval-truth|SUHAIL_EVAL_TRUTH|DEFAULT_TRUTH_ROOT|truth_directory|read_truth_labels|write_truth|"
                            r"^\s*(?:from|import)\s+world(?:\.|\s|$)", re.M)
        files = [*(REPO / "chat" / "operations").rglob("*.py"), *(REPO / "backend").rglob("*.py")]
        self.assertTrue(files)
        for path in files:
            self.assertIsNone(banned.search(path.read_text(encoding="utf-8")), str(path))

    def test_private_physical_state_carries_no_labels(self):
        result = self.report["private_state_isolation"]
        self.assertTrue(result["pass"], result["hits"])
        self.assertGreater(sum(result["records_scanned"].values()), 0)

    def test_world_database_guard(self):
        from dataset_v2.load import ImportRefused
        from world.export import world_guard
        for name in ("shipments-v2-demo-live", "shipments-v2-demo", "shipments-v2-demo-test", "shipments-v2-demo-test2", "neo4j", "shipments"):
            with self.assertRaises(ImportRefused):
                world_guard(name)
        self.assertEqual(world_guard("shipments-v2-world-1-small"), "shipments-v2-world-1-small")


class DeterminismTests(unittest.TestCase):
    def test_same_seed_and_config_give_identical_hashes(self):
        from world.build import build_world, export_bundle
        from world.pipeline import world_digests
        config = WorldConfig(total=90, days=4, seed=5, dataset_id="DEMO-SUHAIL-WORLD-DET", rates=uniform_rates(.004, .016))
        digests = []
        for _ in range(2):
            build = build_world(config)
            build.exports = {"development": export_bundle(build, "development")}
            digests.append(world_digests(build, build.exports))
        self.assertEqual(digests[0], digests[1])
