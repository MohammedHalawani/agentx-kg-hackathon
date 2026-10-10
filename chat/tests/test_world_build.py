"""World-1: physics, observation, causes, truth isolation, tells, splits by time, feed round trip and the bundle reader.
No database.

One small world (240 shipments over 8 booking days) is built once for the module, with scaled-down over-sampling
rates (about 1-2 caused shipments per mechanism and split) so every mechanism still occurs in every split. The
pre-run tell test builds a second small world (seed + 1).
"""
from collections import defaultdict
from datetime import timedelta
import inspect
import json
from pathlib import Path
import re
import tempfile
import unittest

from dataset_v2.contracts import canonical, instant
from dataset_v2.feed import ENVELOPE, Reference, decode
from world.build import ATTEMPT_CAUSES, BOOKING_CONTEXT
from world.config import HISTORY_RATE, LIVE_RATE, MECHANISM_RATES, WorldConfig, uniform_rates
from world.mechanisms import MECHANISM_TYPES, RULE_CODES
from world.monitor import deliver_at
from world.pipeline import build_and_validate
from world.schedule import SCHEDULED
from world.truth import canary_token, labels_at, labels_at_estimate, own_item
from world import validate as V

CONFIG = WorldConfig(total=240, seed=11, dataset_id="DEMO-SUHAIL-WORLD-TEST", rates=uniform_rates(.012, .012))
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

    def test_no_single_record_observable_tells_the_mechanism(self):
        tells = self.report["tells"]
        self.assertTrue(tells["pass"], (tells["development"]["tells"], tells["world"]["tells"]))

    # ------------------------------------------------------------------ causes, not touches (review finding A1)
    def test_every_scheduled_mechanism_causes_its_target_in_every_split(self):
        caused = self.report["coverage"]["caused_shipments"]
        sizes = defaultdict(int)
        for row in self.build.truth.values():
            sizes[row["split"]] += 1
        for mtype in SCHEDULED:
            for split in ("history", "development", "held_out"):
                self.assertGreaterEqual(caused.get(mtype, {}).get(split, 0), CONFIG.target(mtype, split, sizes[split]), (mtype, split))
        self.assertTrue(self.report["coverage"]["pass"], self.report["coverage"]["below_minimum"])

    def test_a_mechanism_is_listed_as_a_cause_or_as_an_exposure_never_both(self):
        exposed_somewhere = 0
        for sid, row in self.build.truth.items():
            causes = {m["mechanism_id"] for m in row["mechanisms"]}
            exposures = {m["mechanism_id"] for m in row["exposures"]}
            self.assertFalse(causes & exposures, sid)
            exposed_somewhere += bool(exposures)
            self.assertEqual(causes, {mid for mid, sids in self.build.caused.items() if sid in sids}, sid)
        self.assertGreater(exposed_somewhere, 0)
        # Shared faults touch more shipments than they cause anything on: the difference is recorded, not scored.
        for mtype in ("FACILITY_BACKLOG", "DEVICE_OUTAGE"):
            exposed = sum(len(sids) for mid, sids in self.build.exposed.items() if self.build.plan.items[mid].type == mtype)
            self.assertGreater(exposed, 0, mtype)

    def test_every_failed_attempt_has_a_cause(self):
        plan = self.build.plan
        failed = [a for a in self.build.sim.acts if a["type"] == "attempt" and a["disposition"] == "FAILED"]
        self.assertTrue(failed)
        for a in failed:
            causes = [m for m in a["mech"] if plan.items[m].type in ATTEMPT_CAUSES | {"ROUTINE_FAILED_ATTEMPT"}]
            self.assertTrue(causes, a["act"])
            self.assertTrue(any(a["sid"] in self.build.caused.get(m, ()) for m in causes), a["act"])

    def test_acceptable_causes_come_from_the_mechanisms_that_explain_the_opening(self):
        opened = [r for r in self.build.truth.values() if r["first_opening"] and not r["healthy"]]
        self.assertTrue(opened)
        explained = 0
        for row in opened:
            actionable = [m for m in row["mechanisms"] if m["resolution"] != "NONE"]
            explaining = [m for m in actionable if set(RULE_CODES[m["type"]]) & set(row["first_opening"]["codes"])]
            self.assertEqual([m["mechanism_id"] for m in actionable if m["explains_opening"]], [m["mechanism_id"] for m in explaining])
            explained += bool(explaining)
            self.assertEqual(row["acceptable_causes"], sorted({c for m in (explaining or actionable) for c in m["acceptable_causes"]}))
            if explaining:
                self.assertIn(row["root_cause"], {m["cause_code"] for m in explaining})
        self.assertGreater(explained, len(opened) * .9)

    def test_clean_case_floor_is_reported_with_the_size_it_needs(self):
        floor = self.report["coverage"]["clean_case_floor"]
        self.assertEqual(floor["floor"], 10)
        self.assertEqual(set(floor["clean_cases_per_mechanism"]), set(SCHEDULED))
        self.assertIn("per_family", floor)
        self.assertFalse(floor["gates_export"])

    # ------------------------------------------------------------------ addendum B4: committed rates
    def test_over_sampling_rates_are_committed_and_recorded_in_the_manifest(self):
        from world.build import truth_manifest, world_manifest
        self.assertEqual(set(MECHANISM_RATES), set(SCHEDULED))
        self.assertEqual(HISTORY_RATE, LIVE_RATE)   # History is a fair prior for the live days.
        self.assertEqual(WorldConfig().rates, tuple((m, h, l) for m, (h, l) in sorted(MECHANISM_RATES.items())))
        imported, items, truth, live_start = self.dev
        manifest = world_manifest(self.build, "development", imported, items, truth)
        weighting = manifest["scenario_weighting"]
        self.assertEqual(set(weighting["rates"]), set(SCHEDULED))
        self.assertEqual(set(weighting["targets"]), {"history", "development"})   # No count of a later split in this export.
        self.assertNotIn("achieved", weighting)
        self.assertEqual(weighting["targets"]["development"]["WRONG_GATE"],
                         CONFIG.target("WRONG_GATE", "development", manifest["counts"]["shipments"]["development"]))
        self.assertEqual(set(truth_manifest(self.build, "development", truth)["achieved"]), {"history", "development"})

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

    def _mechanism_with_support(self):
        per_type = defaultdict(set)
        for sid, r in self.build.truth.items():
            for m in r["mechanisms"]:
                if m["type"] not in V.TELL_EXCLUDED:
                    per_type[m["type"]].add(sid)
        # A mechanism common enough for the support floor (5) and rare enough to count as rare (<= 20%).
        mtype = max((t for t, s in per_type.items() if 5 <= len(s) <= .2 * len(self.build.truth)), key=lambda t: (len(per_type[t]), t))
        return mtype, sorted(per_type[mtype])

    def test_tell_detector_catches_an_injected_value(self):
        world = self.build.world
        mtype, sids = self._mechanism_with_support()
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

    def test_tell_detector_catches_absent_values_list_lengths_numbers_and_lags(self):
        world = self.build.world
        mtype, sids = self._mechanism_with_support()
        cases = (("hint_ref", None, ["Shipment", "hint_ref", V.NONE]), ("hint_list", [], ["Shipment", "hint_list#", "0"]),
                 ("hint_count", 54321, ["Shipment", "hint_count~", "~1e4.5"]))
        for field, value, feature in cases:
            for sid in sids:
                world.nodes[sid].properties[field] = value
            try:
                found = [row["feature"] for row in V.tells(self.build)["world"]["tells"]]
                self.assertIn(feature, found, field)
            finally:
                for sid in sids:
                    world.nodes[sid].properties.pop(field)
        # A record that always arrives ten hours late for one mechanism only.
        stamped = []
        for sid in sids:
            node = world.nodes[sid]
            stamped.append((node, node.properties["recorded_at"]))
            node.properties["recorded_at"] = (instant(node.properties["occurred_at"]) + timedelta(hours=11)).isoformat()
        try:
            found = [row["feature"] for row in V.tells(self.build)["world"]["tells"]]
            self.assertIn(["Shipment", "<lag>", ">=10h"], found)
        finally:
            for node, recorded in stamped:
                node.properties["recorded_at"] = recorded

    def test_a_documented_discriminator_is_reported_apart_from_tells(self):
        self.assertEqual(V._accepted("MANIFEST_ERROR", ("Manifest", "package_ids#", 0))[:20], "the revised manifest")
        self.assertIsNone(V._accepted("MISSORT", ("Manifest", "package_ids#", 0)))
        self.assertIsNone(V._accepted("MANIFEST_ERROR", ("ScanEvent", "confidence~", "~1e-0.5")))

    # ------------------------------------------------------------------ addendum B3: pre-run tell test (gating)
    def test_lookup_classifier_does_not_beat_the_rule_code_baseline_on_another_seed(self):
        result = self.report["tell_test"]
        self.assertTrue(result["gates_export"])
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
            for key in ("split", "healthy", "root_cause", "acceptable_causes", "expected_resolution", "physical", "mechanisms", "exposures",
                        "knowable_at_estimate"):
                self.assertIn(key, row)
            self.assertEqual(row["canary"], canary)
            self.assertNotIn("knowable_at", row)
            for m in row["mechanisms"]:
                for key in ("mechanism_id", "type", "cause_code", "started_at", "knowable_at_estimate", "discrimination", "evidence_ids",
                            "resolution", "action", "explains_opening"):
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
        for result in (self.report["discrimination"], *(e["discrimination"] for e in self.report["exports"].values())):
            self.assertTrue(result["pass"], result["failed_counts"])
            for code in ("RECORD_ITEM_IS_AN_OBSERVATION", "ABSENCE_MATCHES_RECOMPUTED", "ABSENCE_IS_REAL", "ESTIMATE_RECOMPUTES",
                         "EVERY_GROUP_HAS_AN_ITEM_OF_THE_SHIPMENT", "ESTIMATE_NOT_BEFORE_BOOKING", "NOTHING_IDENTIFIABLE_BEFORE_BOOKING",
                         "ESTIMATE_NOT_BEFORE_THE_SHIPMENT_WAS_AFFECTED"):
                self.assertGreater(result["checked"].get(code, 0), 0, code)

    def test_no_cause_is_knowable_from_shared_records_alone(self):
        """Review finding B1: every group of every spec holds a record of the shipment itself or an absence about its
        own parcel, so a heartbeat, a throughput report or another parcel's weighing alone never makes a cause knowable."""
        records = self.build.observer.records
        shared_only = set(records) - {n for n, meta in records.items() if meta["sid"]}
        checked = 0
        for sid, row in self.build.truth.items():
            packages = {p.pid for p in self.build.shipments[sid].parcels}
            others = shared_only | {n for n, meta in records.items() if meta["sid"] and meta["sid"] != sid}
            for m in row["mechanisms"]:
                for group in m["discrimination"]["any_of"]:
                    self.assertTrue(any(own_item(i, sid, packages, lambda n: records[n]["sid"]) for i in group["all_of"]), (sid, m["type"]))
                    checked += 1
            # With every record of every OTHER shipment and every shared record ingested, at the end of the horizon,
            # nothing is identifiable unless an absence about the shipment's own parcel says so.
            names = labels_at(row, self.build.config.end_at, others)
            if names not in ([], ["INSUFFICIENT_EVIDENCE"]):
                own_absence = any("absence" in i and i["absence"]["match"].get("package_id") in packages
                                  for m in row["mechanisms"] for g in m["discrimination"]["any_of"] for i in g["all_of"])
                self.assertTrue(own_absence, sid)
        self.assertGreater(checked, 0)

    def test_labels_at_decides_from_the_ingestion_log(self):
        rows = [r for r in self.build.truth.values() if not r["healthy"] and r["knowable_at_estimate"]]
        self.assertTrue(rows)
        for row in rows:
            first = min(instant(m["knowable_at_estimate"]) for m in row["mechanisms"] if m["resolution"] != "NONE" and m["knowable_at_estimate"])
            before = first - timedelta(seconds=1)
            self.assertEqual(labels_at(row, before, self.ingested(before)), ["INSUFFICIENT_EVIDENCE"], row["shipment_id"])
            self.assertNotEqual(labels_at(row, first, self.ingested(first)), ["INSUFFICIENT_EVIDENCE"], row["shipment_id"])
            self.assertEqual(labels_at_estimate(row, first), labels_at(row, first, self.ingested(first)))
        # The same instant with nothing ingested: only absence items can be satisfied, so record-only specs say nothing.
        record_only = [r for r in rows if all("record" in i for m in r["mechanisms"] for g in m["discrimination"]["any_of"] for i in g["all_of"])]
        self.assertTrue(record_only)
        for row in record_only:
            self.assertEqual(labels_at(row, self.build.config.end_at, set()), ["INSUFFICIENT_EVIDENCE"])
        healthy = next(r for r in self.build.truth.values() if r["healthy"])
        self.assertEqual(labels_at(healthy, healthy["promise_at"], set()), [])

    def test_nothing_is_identifiable_before_a_shipment_is_booked(self):
        """Review finding B2: the scorer's ingestion log is time-aware (an imported record counts from its own
        recorded_at), so no cause is named for a development shipment before its booking, with every imported id."""
        imported, items, truth, live_start = self.dev
        replay = self.replays["development"]
        self.assertTrue(replay["pass"])
        self.assertEqual(replay["shipments_with_a_cause_identifiable_before_booking"], 0)
        stamped = [(instant(n.properties["recorded_at"]), nid) for nid, n in imported.nodes.items()]
        abnormal = [r for r in truth.values() if r["split"] == "development" and not r["healthy"]]
        self.assertTrue(abnormal)
        for row in abnormal:
            for t in (live_start, instant(row["booked_at"]) - timedelta(seconds=1)):
                self.assertEqual(labels_at(row, t, {nid for at, nid in stamped if at <= t}), ["INSUFFICIENT_EVIDENCE"], row["shipment_id"])
        self.assertEqual({r["labels_before_booking"][0] if r["labels_before_booking"] else "" for r in replay["shipments"].values()}
                         - {"", "INSUFFICIENT_EVIDENCE"}, set())

    def test_an_export_truth_cites_only_records_that_export_contains(self):
        """Review finding B8: a development spec never needs a held-out shipment's record."""
        imported, items, truth, live_start = self.dev
        present = set(truth)
        records = self.build.observer.records
        for row in truth.values():
            self.assertNotEqual(row["split"], "held_out")
            for m in row["mechanisms"]:
                cited = [i["record"] for g in m["discrimination"]["any_of"] for i in g["all_of"] if "record" in i]
                cited += [n for g in m["discrimination"]["any_of"] for i in g["all_of"] if "absence" in i for n in i["absence"]["cancelled_by"]]
                for nid in [*cited, *m["evidence_ids"], *m["shared_evidence_ids"]]:
                    owner = records[nid]["sid"]
                    self.assertTrue(owner is None or owner in present, (row["shipment_id"], nid))

    def test_ambiguous_cases_are_counted_and_mostly_identifiable(self):
        ambiguity = self.replays["development"]["ambiguity"]
        self.assertGreater(ambiguity["ambiguous"], 0)
        self.assertEqual(ambiguity["identifiable_ambiguous"] + ambiguity["unidentifiable_ambiguous"], ambiguity["ambiguous"])
        self.assertGreater(ambiguity["identifiable_ambiguous"], ambiguity["ambiguous"] // 2)

    # ------------------------------------------------------------------ splits by time, and the feed
    def test_nothing_recorded_after_the_live_start_is_imported(self):
        """Review findings A7 and B3: the import holds what was recorded by the live start; everything later (of any
        shipment or shared resource) is a feed message. Only a live shipment's booking-time context is imported with
        a later stamp, exactly at its booking (the foundation contract; every reader filters by recorded_at)."""
        result = self.report["import_cut"]
        self.assertTrue(result["pass"], result["failed_counts"])
        for split, (imported, items, truth, live_start) in self.build.exports.items():
            fed = {i["source_event_id"] for i in items}
            exceptions = 0
            for node in imported.nodes.values():
                p = node.properties
                late = instant(p["recorded_at"]) > live_start or (p.get("occurred_at") and instant(p["occurred_at"]) > live_start)
                if not late:
                    continue
                exceptions += 1
                self.assertEqual(p["split"], "development", node.id)
                self.assertIn(node.kind, BOOKING_CONTEXT, node.id)
                self.assertEqual(p["recorded_at"], imported.nodes[p["holdout_group"]].properties["recorded_at"], node.id)
            self.assertEqual(exceptions, result["per_export"][split]["live_booking_context_records"])
            self.assertFalse(fed & set(imported.nodes))
            world = self.build.world
            history = {sid for sid, r in truth.items() if imported.nodes[sid].properties["split"] == "history"}
            later_history = [n for n in fed if world.nodes[n].properties.get("holdout_group") in history]
            self.assertTrue(later_history)   # Earlier booking days keep moving after the live start: that evidence is fed.
            for nid in later_history:
                self.assertGreater(instant(world.nodes[nid].properties["recorded_at"]), live_start, nid)
            shared = [n for n in fed if world.nodes[n].kind in ("Trip", "Container", "RouteRun")]
            self.assertTrue(shared)
            for item in items:
                self.assertGreater(instant(item["deliver_at"]), live_start)
            # No case, exception or interval of an imported shipment comes from after the live start.
            for node in imported.nodes.values():
                if node.kind in ("Case", "Exception"):
                    self.assertLessEqual(instant(node.properties["recorded_at"]), live_start, node.id)

    def test_development_export_leaves_held_out_days_out(self):
        imported, items, truth, live_start = self.dev
        held = {sid for sid, r in self.build.truth.items() if r["split"] == "held_out"}
        self.assertTrue(held)
        self.assertFalse(held & set(imported.nodes))
        self.assertFalse(any(n.properties.get("holdout_group") in held for n in imported.nodes.values()))
        fed_owners = {self.build.world.nodes[i["source_event_id"]].properties.get("holdout_group") for i in items}
        self.assertFalse(held & fed_owners)
        self.assertFalse(held & set(truth))
        self.assertFalse(held & set(imported.gold))
        live = {sid for sid, r in self.build.truth.items() if r["split"] == "development"}
        for node in imported.nodes.values():
            owner = node.properties.get("holdout_group")
            if owner in live:
                self.assertEqual(node.properties["recorded_at"], imported.nodes[owner].properties["recorded_at"], node.id)
        history = {sid for sid, r in self.build.truth.items() if r["split"] == "history"}
        self.assertEqual(imported.config.split_counts, {"history": len(history), "development": len(live)})

    def test_scoring_rows_of_live_shipments_carry_no_hindsight(self):
        """Review finding B9: no end-of-horizon assessment and no opening time of a live shipment in the bundle."""
        imported, items, truth, live_start = self.dev
        live = [row for row in imported.gold.values() if row["split"] == "development"]
        self.assertTrue(live)
        self.assertEqual({row["initial_snapshot_at"] for row in live}, {imported.config.as_of})
        for row in live:
            self.assertNotIn("assessment", row)

    def test_held_out_export_imports_what_was_recorded_before_its_start(self):
        imported, items, truth, live_start = self.held
        held = {sid for sid, r in self.build.truth.items() if r["split"] == "held_out"}
        self.assertEqual({n.id for n in imported.nodes.values() if n.kind == "Shipment" and n.properties["split"] == "development"}, held)
        self.assertGreater(sum(1 for n in imported.nodes.values() if n.kind == "Outcome"), 0)

    def test_every_feed_message_decodes_to_its_record_exactly(self):
        imported, items, truth, live_start = self.dev
        ref = Reference.from_world(imported)
        world = self.build.world
        kinds = set()
        for item in items:
            kind, entity, sid, occurred, props = decode(item["channel"], item["message_type"], json.loads(item["payload_json"]), ref)
            node = world.nodes[entity]
            kinds.add(kind)
            self.assertEqual(kind, node.kind)
            self.assertEqual(occurred, node.properties["occurred_at"])
            self.assertEqual(canonical(props), canonical({k: v for k, v in node.properties.items() if k not in ENVELOPE}), entity)
            self.assertGreaterEqual(instant(item["deliver_at"]), instant(node.properties["recorded_at"]))
        self.assertTrue({"Trip", "Container", "RouteRun", "FacilityThroughput", "TripEvent"} <= kinds)

    # ------------------------------------------------------------------ forecasts and facility reports (A5, A6)
    def test_a_carrier_estimate_is_never_the_simulated_arrival(self):
        result = self.report["forecasts"]
        self.assertTrue(result["pass"], result["failed_counts"])
        self.assertGreater(result["estimates_compared"], 0)
        self.assertEqual(result["estimates_equal_to_arrival"], 0)
        self.assertGreater(result["delay_notices"], 0)
        nodes = self.build.world.nodes
        self.assertFalse([n.id for n in nodes.values() if n.kind == "TripEvent" and n.properties["event_type"] == "ARRIVED"
                          and n.properties.get("estimated_arrival_at")])

    def test_a_backlog_shows_in_the_facility_throughput_reports(self):
        result = self.report["throughput_separation"]
        self.assertTrue(result["pass"], result["failed_counts"])
        self.assertTrue(result["backlogs"])
        sample = next(n for n in self.build.world.nodes.values() if n.kind == "FacilityThroughput")
        for field in ("processed_count", "queue_depth", "nominal_capacity_per_hour", "staffed_capacity_per_hour", "oldest_waiting_minutes"):
            self.assertIn(field, sample.properties)

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
        self.assertIn("without_scheduled_fault", replay)
        for row in replay["per_mechanism"].values():
            self.assertGreaterEqual(row["caused_shipments"], row["opened"])
            self.assertGreaterEqual(row["opened_and_explaining"], row["clean_cases"])

    # ------------------------------------------------------------------ bundle files, truth and state directories, guards (B1)
    def test_bundle_holds_only_importable_data(self):
        from world.export import read_world_bundle, write_bundle
        canary = canary_token(CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"
            write_bundle(self.build, "development", target, self.report)
            bundle, items = read_world_bundle(target)
            imported = self.dev[0]
            self.assertEqual(bundle.manifest, imported.manifest())
            self.assertEqual(len(items), len(self.dev[1]))
            names = {p.name for p in target.iterdir()}
            self.assertEqual(names, {"nodes.jsonl", "edges.jsonl", "gold.jsonl", "feed.jsonl", "manifest.json", "validation.json",
                                     "statistics.json", "feed_manifest.json", "world_manifest.json", "world_validation.json"})
            held = sorted(sid for sid, r in self.build.truth.items() if r["split"] == "held_out")
            from operations.agents import CAUSES
            # Mechanism names that are not also rule codes of the monitor (those appear in derived history cases).
            mechanism_words = re.compile("(?<![A-Z_])(" + "|".join(sorted((m for m in MECHANISM_TYPES if m not in CAUSES), key=len, reverse=True))
                                         + ")(?![A-Z_])")
            for path in target.iterdir():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("W1M-", text, path.name)
                self.assertNotIn(canary, text, path.name)
                self.assertNotIn("truth_hash", text, path.name)
                self.assertFalse([sid for sid in held if sid in text], path.name)
                if path.name != "world_manifest.json":
                    self.assertIsNone(mechanism_words.search(text), path.name)
            # The manifest names mechanism types only as the committed rates and targets (already in the repository).
            manifest = json.loads((target / "world_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["scenario_weighting"]), {"note", "rates", "targets"})
            self.assertNotIn("precedents", manifest)
            with self.assertRaises(ValueError):
                write_bundle(self.build, "development", target, self.report)

    def test_truth_labels_are_written_outside_the_repository_per_export(self):
        from world.export import read_truth_labels, truth_directory, write_truth
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn(REPO, Path(tmp).resolve().parents)
            target = Path(write_truth(self.build, tmp, self.replays, self.build.history_reports, report=self.report))
            self.assertEqual(target, Path(tmp).resolve() / CONFIG.dataset_id)
            held = {sid for sid, r in self.build.truth.items() if r["split"] == "held_out"}
            for split, (imported, items, truth, live_start) in self.build.exports.items():
                rows = [json.loads(line) for line in (target / split / "truth.jsonl").open(encoding="utf-8")]
                self.assertEqual({r["shipment_id"] for r in rows}, set(truth))
                self.assertEqual({r["canary"] for r in rows}, {canary_token(CONFIG)})
                self.assertTrue((target / split / "truth_manifest.json").exists())
            self.assertFalse(held & {json.loads(line)["shipment_id"] for line in (target / "development" / "truth.jsonl").open(encoding="utf-8")})
            self.assertTrue((target / "development" / "monitor_replay_rows.jsonl").exists())
            labels = read_truth_labels(tmp, CONFIG.dataset_id)
            self.assertEqual(labels["canary"], [canary_token(CONFIG)])
            self.assertEqual(len(labels["mechanism_ids"]), len(self.build.plan.items))
            with self.assertRaises(ValueError):
                write_truth(self.build, tmp, self.replays, self.build.history_reports)
        for inside in (REPO, REPO / "artifacts" / "truth", Path(tempfile.gettempdir()) / "artifacts"):
            with self.assertRaises(ValueError):
                truth_directory(inside, CONFIG.dataset_id)
        self.assertEqual(truth_directory(None, "DEMO-X", "world-1-small-r2").parent.name, "world-1-small-r2")

    def test_physical_state_is_written_outside_the_repository_and_cut_to_the_export(self):
        """Review findings A11 and B6: the simulator's state lives in its own root outside the repository, holds only
        the export's shipments, and lists every device."""
        from world.export import private_physical, state_directory, write_state
        held = {sid for sid, r in self.build.truth.items() if r["split"] == "held_out"}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(write_state(self.build, tmp))
            self.assertEqual(target, Path(tmp).resolve() / CONFIG.dataset_id)
            self.assertEqual({p.name for p in target.iterdir()}, {"development", "held_out", "README.txt"})
            names = {p.name for p in (target / "development").iterdir()}
            self.assertTrue({"parcels.jsonl", "containers.jsonl", "devices.jsonl", "recipients.jsonl", "routes.jsonl", "trips.jsonl",
                             "events.jsonl"} <= names)
            for path in (target / "development").iterdir():
                text = path.read_text(encoding="utf-8")
                self.assertFalse([sid for sid in sorted(held) if sid in text], path.name)
                self.assertNotIn("W1M-", text, path.name)
            self.assertTrue([sid for sid in sorted(held) if sid in (target / "held_out" / "parcels.jsonl").read_text(encoding="utf-8")])
            with self.assertRaises(ValueError):
                write_state(self.build, tmp)
        state = private_physical(self.build, "development")
        devices = {row["device_id"]: row for row in state["devices"]}
        self.assertTrue(set(self.build.network.devices) <= set(devices))
        self.assertGreater(sum(1 for row in devices.values() if not row["offline"] and not row["upload_stuck"] and not row["scale_offset"]),
                           len(devices) // 3)
        self.assertEqual({row["shipment_id"] for row in state["parcels"]}, set(self.dev[2]))
        for inside in (REPO, REPO / "artifacts" / "world" / "x" / "private", Path(tempfile.gettempdir()) / "artifacts"):
            with self.assertRaises(ValueError):
                state_directory(inside, CONFIG.dataset_id)

    def test_backend_and_operations_never_read_the_truth_or_state_paths(self):
        banned = re.compile(r"suhail-eval-truth|SUHAIL_EVAL_TRUTH|DEFAULT_TRUTH_ROOT|truth_directory|read_truth_labels|write_truth|"
                            r"suhail-sim-state|SUHAIL_SIM_STATE|DEFAULT_STATE_ROOT|state_directory|write_state|private_physical|"
                            r"^\s*(?:from|import)\s+world(?:\.|\s|$)", re.M)
        files = [*(REPO / "chat" / "operations").rglob("*.py"), *(REPO / "backend").rglob("*.py")]
        self.assertTrue(files)
        for path in files:
            self.assertIsNone(banned.search(path.read_text(encoding="utf-8")), str(path))

    def test_physical_state_scan_is_hygiene_and_says_so(self):
        for split, export in self.report["exports"].items():
            result = export["physical_state_vocabulary"]
            self.assertTrue(result["pass"], result["hits"])
            self.assertGreater(sum(result["records_scanned"].values()), 0)
            self.assertTrue(result["labels_derivable_from_this_state"])

    def test_every_cross_shipment_traversal_uses_the_time_correct_predicate(self):
        """Review finding A7: one predicate (recorded_at <= as_of and occurred_at <= as_of) filters every record a
        cross-shipment lookup returns. (The database test of it runs in `world.export check --ingest`.)"""
        from world import export
        predicate = export.visible("n")
        self.assertIn("n.recorded_at <= $as_of", predicate)
        self.assertIn("n.occurred_at <= $as_of", predicate)
        source = inspect.getsource(export.traversals)
        matches = re.findall(r"MATCH \((\w+):(\w+)", source) + re.findall(r"-\((\w+):(\w+)\)", source) + re.findall(r"->\((\w+):(\w+)\)", source)
        self.assertGreater(len(matches), 10)
        for alias, label in matches:
            self.assertIn(f"visible('{alias}')", source, (alias, label))
        self.assertNotIn("LiveIngested", source)

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
        config = WorldConfig(total=90, days=4, seed=5, dataset_id="DEMO-SUHAIL-WORLD-DET", rates=uniform_rates(.012, .012))
        digests = []
        for _ in range(2):
            build = build_world(config)
            build.exports = {"development": export_bundle(build, "development")}
            digests.append(world_digests(build, build.exports))
        self.assertEqual(digests[0], digests[1])
