"""Stage 4: the world operational simulator, verification from evidence produced after execution, closure only when the
exception is really gone, approval before an approval-required action, and what a person may record.

Everything runs in memory (tests.world_live): the development export of the small test world, the provider feed, the
real OperationsStore on the in-memory ledger, the real outcome verifier and authority policy. No database, no model.
The simulator is given the export's private PHYSICAL state only. Tests read truth rows nowhere; scenarios are chosen
from the physical state and from what the monitor's own rules see.
"""
import ast
import json
import pathlib
import tempfile
import unittest
from datetime import timedelta

from dataset_v2.contracts import canonical, instant, iso
from operations.lifecycle import HARNESS_ACTOR, OperationsConflict
from operations.outcome_engine import NOT_FOUND
from operations.world_simulation import (LABEL_FILES, RECEIPTS, PhysicalState, StateUnavailable, WorldOperationalSimulator, distance_m,
                                         state_directory_for)
from tests.world_live import LiveWorld, advance, ledger_store, physical, seed_case, symptoms_at

ROOT = pathlib.Path(__file__).resolve().parents[2]
OPERATOR = "DEMO-OPERATOR-LOCAL"
OUTAGE_DEVICE = "DEMO-DEV-APP-DRV-FM-KHB-005"       # Offline from 13:56 on 15 September until 04:08 the next morning.
OUTAGE_SHIPMENT = "DEMO-SHP-000133"                 # Two parcels collected by that driver while the phone was off.
HEALTHY_DEVICE = "DEMO-DEV-HH-DEPOT-RUH-N"          # Online that evening (its own window is three days later).
WRONG_LABEL = "DEMO-SHP-000049"                     # Carries another order's label: every read returns that barcode.
FAILED_ATTEMPT = "DEMO-SHP-000111"                  # A failed delivery attempt on the morning of 17 September.
UNSCANNED_AT_DEPOT = "DEMO-SHP-000232"              # On the Madinah depot shelf from 18 September with no receipt record.


def at(text):
    return f"2026-09-{text}:00+00:00"


class Scenario:
    def __init__(self, when):
        self.live = LiveWorld(when)
        self.state = PhysicalState(physical())
        self.sim = WorldOperationalSimulator(self.live.gateway, self.live, self.state, self.live.world.config)
        self.store, self.driver = ledger_store(self.live, self.sim)

    def execution(self, sid, action, **extra):
        return {"entity_id": f"DEMO-OPS-EXECUTION-TEST-{action}-{sid[-6:]}", "shipment_id": sid, "action_type": action, **extra}

    def answers(self, origin="SIMULATOR"):
        """Messages the simulator put on the feed, decoded: [(kind, id, occurred_at, properties, deliver_at)]."""
        rows = []
        for item in self.live.gateway.items.values():
            if item["origin"] == origin:
                kind, key, sid, occurred, props = self.live.gateway._decoded(item)
                rows.append((kind, key, occurred, props, item["deliver_at"]))
        return sorted(rows, key=lambda r: (r[2], r[1]))

    def run(self, hours, step=1):
        """Advance the clock; the execution adapter and the verifier run after every step, as the worker threads do."""
        for _ in range(0, hours, step):
            self.store.execute_step()
            advance(self.store, self.live, step)
            self.store.outcome_step(limit=10)

    def case(self, case_id):
        return self.store.case_detail(case_id)

    def kind(self, name):
        return [v for k, v in self.driver.ledger.values() if k == name]

    def audits(self, case_id):
        return [a["event_type"] for a in self.kind("OpsAudit") if a.get("case_id") == case_id]

    def package_at_depot(self):
        """(package id, depot, instant) for a development parcel on a depot shelf that no vehicle takes in the depot's next session."""
        for pid, row in sorted(self.state.parcels.items()):
            for (t, kind, ref), following in zip(row["timeline"], row["timeline"][1:] + [[None, None, None]]):
                if kind != "FACILITY" or ref not in self.state.depots or following[0] is None:
                    continue
                gap = instant(following[0]) - instant(t)
                if gap > timedelta(hours=40):
                    return pid, ref, instant(t) + timedelta(hours=1)
        raise AssertionError("no parcel waits on a depot shelf past a session in this world")


class StateTests(unittest.TestCase):
    def test_state_is_loaded_from_a_directory_and_a_label_directory_is_refused(self):
        tables = physical()
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp) / "DEMO-SUHAIL-WORLD-TEST" / "development"
            folder.mkdir(parents=True)
            for name, rows in tables.items():
                (folder / f"{name}.jsonl").write_text("\n".join(canonical(r) for r in rows) + "\n", encoding="utf-8")
            found = state_directory_for(tmp, "DEMO-SUHAIL-WORLD-TEST")
            self.assertEqual(found, folder)
            state = PhysicalState.load(found)
            self.assertEqual(len(state.parcels), len(tables["parcels"]))
            self.assertTrue(state.depots)
            with self.assertRaises(StateUnavailable):
                state_directory_for(tmp, "DEMO-SUHAIL-WORLD-OTHER", "held_out")
            for name in LABEL_FILES:     # A directory that holds evaluation labels is never opened as state.
                (folder / name).write_text("{}", encoding="utf-8")
                with self.assertRaises(StateUnavailable):
                    PhysicalState.load(folder)
                (folder / name).unlink()

    def test_the_adapter_attaches_only_with_a_state_root_for_this_dataset(self):
        import os
        from types import SimpleNamespace
        from unittest import mock
        from operations import world_simulation
        live = LiveWorld()
        dataset = live.world.config.dataset_id
        manifest = {"dataset_id": dataset}
        clean = {k: v for k, v in os.environ.items() if k != world_simulation.STATE_ENVIRONMENT}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, clean, clear=True):
            folder = pathlib.Path(tmp) / dataset / "development"
            folder.mkdir(parents=True)
            for name, rows in physical().items():
                (folder / f"{name}.jsonl").write_text("\n".join(canonical(r) for r in rows) + "\n", encoding="utf-8")
            store = SimpleNamespace(live=True, gateway=live.gateway, config=live.world.config, adapter=None)
            self.assertIsNone(world_simulation.attach(store, live, manifest))            # No state root: no adapter.
            self.assertIsNone(store.adapter)
            self.assertIsNone(world_simulation.attach(store, live, {"dataset_id": "DEMO-SUHAIL-LIVE-1"}, state_root=tmp))
            with mock.patch.dict(os.environ, {world_simulation.STATE_ENVIRONMENT: tmp}):
                adapter = world_simulation.attach(store, live, manifest)
            self.assertIs(store.adapter, adapter)
            self.assertEqual(adapter.name, "world_operational_simulator")
            # State that describes shipments this database does not hold is refused.
            row = json.loads((folder / "recipients.jsonl").read_text(encoding="utf-8").splitlines()[0])
            (folder / "recipients.jsonl").write_text(canonical({**row, "shipment_id": "DEMO-SHP-999999"}) + "\n", encoding="utf-8")
            with self.assertRaises(StateUnavailable):
                world_simulation.attach(SimpleNamespace(live=True, gateway=live.gateway, config=live.world.config, adapter=None), live, manifest, state_root=tmp)

    def test_the_state_names_no_cause_and_the_simulator_reads_no_label(self):
        text = json.dumps(physical())
        for word in ("cause_code", "root_cause", "mechanism", "W1M-", "DELAYED_SYNC", "WRONG_LABEL_APPLIED", "acceptable_causes"):
            self.assertNotIn(word, text)
        source = (ROOT / "chat/operations/world_simulation.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
                   {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse([m for m in imported if m and (m == "world" or m.startswith("world.") or "truth" in m or m == "operations.simulation")])
        for word in ("read_truth", "SUHAIL_EVAL_TRUTH", "suhail-eval-truth", "cause_code", "acceptable_causes", "root_cause"):
            self.assertNotIn(word, source)

    def test_no_runtime_module_reads_truth_labels(self):
        """Operations and backend: no truth-label path, reader or file anywhere; the physical-state root is named by the
        world simulator alone, and only the API's attach_simulator reaches that module."""
        import re
        labels = re.compile(r"suhail-eval-truth|SUHAIL_EVAL_TRUTH|DEFAULT_TRUTH_ROOT|truth_directory|read_truth_labels|write_truth|"
                            r"^\s*(?:from|import)\s+world(?:\.|\s|$)|world\.truth", re.M)
        state = re.compile(r"suhail-sim-state|SUHAIL_SIM_STATE|DEFAULT_STATE_ROOT|state_directory\(|write_state|private_physical")
        files = [*(ROOT / "chat" / "operations").rglob("*.py"), *(ROOT / "backend").rglob("*.py")]
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(labels.search(text), str(path))
            if path.name != "world_simulation.py":
                self.assertIsNone(state.search(text), str(path))
                if path.name != "operations_api.py":
                    self.assertNotIn("world_simulation", text, str(path))
            # The retired S5 simulator and its loader read the live-network scenario file; the world simulator names the
            # label files only to refuse a directory that holds them.
            if path.name not in ("simulation.py", "operations_api.py", "world_simulation.py"):
                self.assertNotIn("truth.jsonl", text, str(path))
        api = ast.parse((ROOT / "backend/operations_api.py").read_text(encoding="utf-8"))
        users = [f.name for f in ast.walk(api) if isinstance(f, ast.FunctionDef) and "world_simulation" in ast.unparse(f)]
        self.assertEqual(users, ["attach_simulator"])

    def test_receipts_depend_on_the_action_alone(self):
        s = Scenario(at("15T18:00"))
        told = set()
        for target in (OUTAGE_DEVICE, HEALTHY_DEVICE):   # One device holds twelve records, the other none.
            receipt = s.sim.respond(s.execution(OUTAGE_SHIPMENT, "REQUEST_DEVICE_SYNC", target_device=target, entity_id="E-" + target), s.live.clock)
            told.add(canonical(receipt))
        self.assertEqual(told, {canonical({"acknowledged": True, "behaviour": RECEIPTS["REQUEST_DEVICE_SYNC"]})})
        for text in RECEIPTS.values():
            for word in ("found", "uploaded", "buffer", "offline", "wrong", "correct", "absent", "nothing"):
                self.assertNotIn(word, text.lower())
        for target in (None, "DEMO-DEV-NO-SUCH-DEVICE"):   # Nothing to deliver the request to: not acknowledged.
            self.assertFalse(s.sim.respond(s.execution(OUTAGE_SHIPMENT, "REQUEST_DEVICE_SYNC", target_device=target, entity_id=f"E-{target}"),
                                           s.live.clock)["acknowledged"])
        self.assertFalse(s.sim.respond(s.execution(OUTAGE_SHIPMENT, "COMPENSATION"), s.live.clock)["acknowledged"])


class HandlerTests(unittest.TestCase):
    def test_device_sync_uploads_only_what_the_targeted_device_holds_then(self):
        s = Scenario(at("15T18:00"))
        device = s.state.devices[OUTAGE_DEVICE]
        held = {r["record"] for w in device["offline"] for r in w["buffered_records"]}
        before = {i["source_event_id"]: i["deliver_at"] for i in s.live.gateway.pending() if i["source_event_id"] in held}
        self.assertTrue(before)
        self.assertTrue(all(instant(t) > instant(at("16T04:00")) for t in before.values()))   # Held until the phone reconnects.
        # A healthy device: nothing is uploaded, and its heartbeat reports an empty queue.
        s.sim.respond(s.execution(OUTAGE_SHIPMENT, "REQUEST_DEVICE_SYNC", target_device=HEALTHY_DEVICE, entity_id="E-healthy"), s.live.clock)
        self.assertEqual({i["source_event_id"]: i["deliver_at"] for i in s.live.gateway.pending() if i["source_event_id"] in held}, before)
        [(kind, _, _, beat, _)] = s.answers()
        self.assertEqual((kind, beat["device_id"], beat["pending_uploads"]), ("DeviceHeartbeat", HEALTHY_DEVICE, 0))
        # The device that holds them: exactly the records made before the request reached it are uploaded now.
        s.sim.respond(s.execution(OUTAGE_SHIPMENT, "REQUEST_DEVICE_SYNC", target_device=OUTAGE_DEVICE, entity_id="E-outage"), s.live.clock)
        reached = instant(s.live.clock) + timedelta(minutes=10)
        after = {i["source_event_id"]: i for i in s.live.gateway.pending() if i["source_event_id"] in held}
        moved = {k for k, i in after.items() if instant(i["deliver_at"]) < instant(before[k])}
        self.assertTrue(moved)
        for key, item in after.items():
            occurred = instant(s.live.gateway._decoded(item)[3])
            self.assertEqual(key in moved, occurred <= reached, key)       # Nothing that does not exist yet is "uploaded".
            self.assertGreaterEqual(instant(item["deliver_at"]), occurred)
        beat = next(p for k, _, _, p, _ in s.answers() if k == "DeviceHeartbeat" and p["device_id"] == OUTAGE_DEVICE)
        self.assertEqual(beat["pending_uploads"], len(moved))

    def test_rescan_reads_the_label_the_parcel_carries_where_it_is(self):
        s = Scenario(at("17T03:30"))   # On the Jubail depot shelf from 03:18 until the morning load.
        package = WRONG_LABEL + "-PKG-01"
        row = s.state.parcels[package]
        self.assertNotEqual(row["label_barcode"], row["manifest_barcode"])
        self.assertTrue(s.sim.respond(s.execution(WRONG_LABEL, "REQUEST_RESCAN"), s.live.clock)["acknowledged"])
        [(kind, _, occurred, scan, deliver)] = s.answers()
        self.assertEqual((kind, scan["observed_barcode"], scan["facility_id"]), ("ScanEvent", row["label_barcode"], "DEMO-DEPOT-JUB-01"))
        self.assertGreater(instant(occurred), instant(s.live.clock))
        self.assertGreater(instant(deliver), instant(occurred))
        # A parcel sealed in a container (or on a vehicle) is not on a shelf: acknowledged, and nothing follows.
        moving = next(pid for pid, r in sorted(s.state.parcels.items()) if (s.sim.where(pid, instant(s.live.clock)) or ("",))[0] == "VEHICLE"
                      and r["shipment_id"] in s.live.gateway.splits and s.live.gateway.splits[r["shipment_id"]] == "development")
        sid = s.state.parcels[moving]["shipment_id"]
        self.assertEqual(len([p for p in s.state.parcels.values() if p["shipment_id"] == sid]), 1)
        self.assertTrue(s.sim.respond(s.execution(sid, "REQUEST_RESCAN"), s.live.clock)["acknowledged"])
        self.assertEqual(len(s.answers()), 1)

    def test_a_one_off_misread_reads_right_on_the_rescan(self):
        s = Scenario(at("17T03:30"))
        sid = "DEMO-SHP-000064"   # Misread once by a sorter reader on 14 September; on the Jeddah depot shelf from 03:11.
        self.assertEqual(symptoms_at(s.live, sid, s.live.clock), ["BARCODE_READ_DIFFERS"])
        s.sim.respond(s.execution(sid, "REQUEST_RESCAN"), s.live.clock)
        scans = [p for k, _, _, p, _ in s.answers() if k == "ScanEvent"]
        self.assertEqual(len(scans), 2)
        for scan in scans:
            self.assertEqual(scan["observed_barcode"], s.state.parcels[scan["package_id"]]["manifest_barcode"])

    def test_reweigh_shows_the_real_weight_and_needs_a_scale(self):
        s = Scenario(at("19T12:00"))
        tried = {}
        for sid, wrong_declaration in (("DEMO-SHP-000012", True), ("DEMO-SHP-000094", False)):
            package = sid + "-PKG-01"
            row = s.state.parcels[package]
            shelf = next((t, ref) for t, kind, ref in row["timeline"] if kind == "FACILITY" and s.sim.scales(ref) and "DEPOT" in ref)
            now = iso(instant(shelf[0]) + timedelta(minutes=5))
            live = LiveWorld(now)
            sim = WorldOperationalSimulator(live.gateway, live, s.state, live.world.config)
            sim.respond(s.execution(sid, "REQUEST_REWEIGH"), now)
            [item] = [i for i in live.gateway.items.values() if i["origin"] == "SIMULATOR"]
            scan = live.gateway._decoded(item)[4]
            self.assertTrue(scan["calibrated"])
            self.assertEqual(scan["measured_weight_kg"], round(row["true_kg"], 3))
            declared = row["declared_kg"]
            tried[sid] = abs(scan["measured_weight_kg"] - declared) > max(.5, .1 * declared)
            self.assertEqual(tried[sid], wrong_declaration)   # A wrong declaration stays wrong; a drifting scale's error is gone.
        # At a facility with no scale (a branch counter, a hub dock) nothing can be reweighed: nothing follows.
        package, start = next((pid, t) for pid, r in sorted(s.state.parcels.items()) for (t, kind, ref), nxt in zip(r["timeline"], r["timeline"][1:])
                              if kind == "FACILITY" and not s.sim.scales(ref) and instant(nxt[0]) - instant(t) > timedelta(hours=3)
                              and s.live.gateway.splits.get(r["shipment_id"]) == "development" and instant(t) > instant(at("14T00:00")))
        now = iso(instant(start) + timedelta(minutes=5))
        s2 = Scenario(now)
        self.assertIsNotNone(s2.sim.facility_of(package, instant(now) + timedelta(hours=1), loose=True))
        self.assertTrue(s2.sim.respond(s2.execution(s.state.parcels[package]["shipment_id"], "REQUEST_REWEIGH"), now)["acknowledged"])
        self.assertEqual(s2.answers(), [])

    def test_a_facility_finds_the_parcel_only_if_it_is_there(self):
        s = Scenario(at("19T04:00"))
        package = UNSCANNED_AT_DEPOT + "-PKG-01"
        self.assertEqual(s.sim.facility_of(package, instant(s.live.clock)), "DEMO-DEPOT-MED-01")
        asked = [{"package_id": package, "predicate": "RECEIVED", "location_id": "DEMO-DEPOT-MED-01"},
                 {"package_id": package, "predicate": "RECEIVED", "location_id": "DEMO-HUB-JED-01"}]
        s.sim.respond(s.execution(UNSCANNED_AT_DEPOT, "INITIATE_CUSTODY_RECONCILIATION", expected_evidence=asked), s.live.clock)
        rows = s.answers()
        found = [p for k, _, _, p, _ in rows if k == "ScanEvent" and p.get("observation_type") == "FACILITY_CHECK_SCAN"]
        absent = [p for k, _, _, p, _ in rows if k == "ScanEvent" and p.get("observation_type") == NOT_FOUND]
        custody = [p for k, _, _, p, _ in rows if k == "CustodyEvent"]
        self.assertEqual([p["facility_id"] for p in found], ["DEMO-DEPOT-MED-01"])
        self.assertIn("DEMO-HUB-JED-01", [p["checked_facility_id"] for p in absent])
        self.assertTrue(all(p.get("facility_id") is None and p["readable"] is False for p in absent))   # Never a place of presence.
        self.assertEqual([(p["to_id"], p["event_type"]) for p in custody], [("DEMO-DEPOT-MED-01", "RECEIVED")])
        # A hub check asks the same way and records no custody.
        s.sim.respond(s.execution(UNSCANNED_AT_DEPOT, "REQUEST_HUB_CHECK", expected_evidence=asked[1:], entity_id="E-hub"), s.live.clock)
        self.assertEqual(len([1 for k, _, _, _, _ in s.answers() if k == "CustodyEvent"]), 1)

    def test_the_recipient_confirms_or_corrects_the_address_and_nothing_is_delivered(self):
        s = Scenario(at("17T07:00"))
        moved = "DEMO-SHP-000131"   # Lives several kilometres from the booked address.
        for sid in (FAILED_ATTEMPT, moved):
            s.sim.respond(s.execution(sid, "REQUEST_ADDRESS_CONFIRMATION"), s.live.clock)
        answers = {p["confirmed_by"]: p for k, _, _, p, _ in s.answers()}
        self.assertEqual({k for k, _, _, _, _ in s.answers()}, {"AddressVersion"})   # No attempt, proof or custody record.
        for sid in (FAILED_ATTEMPT, moved):
            recipient = s.state.recipients[sid]
            answer = answers[recipient["recipient_id"]]
            self.assertEqual(answer["verification_status"], "VERIFIED")
            self.assertLess(distance_m((answer["lat"], answer["lng"]), recipient["home_point"]), 150)
            corrected = distance_m(recipient["home_point"], recipient["registered_point"]) > 150
            self.assertEqual(distance_m((answer["lat"], answer["lng"]), recipient["registered_point"]) > 150, corrected)
        self.assertGreater(distance_m(s.state.recipients[moved]["home_point"], s.state.recipients[moved]["registered_point"]), 1000)

    def test_prioritising_attempts_only_a_parcel_on_the_depot_shelf_and_the_result_follows_the_recipient(self):
        base = Scenario(at("14T12:00"))
        package, depot, when = base.package_at_depot()
        sid = base.state.parcels[package]["shipment_id"]
        s = Scenario(iso(when))
        recipient = s.state.recipients[sid]
        s.sim.respond(s.execution(sid, "PRIORITIZE_NEXT_SESSION"), s.live.clock)
        rows = s.answers()
        attempts = [(o, p) for k, _, o, p, _ in rows if k == "DeliveryAttempt"]
        self.assertTrue(attempts, "a parcel on the shelf is attempted in the depot's next session")
        occurred, attempt = attempts[0]
        self.assertGreater(instant(occurred), when)
        home = s.sim._at_home(recipient, instant(occurred), s.state.parcels[package]["attempts"])
        lives_there = distance_m(recipient["home_point"], recipient["registered_point"]) <= 150
        self.assertEqual(attempt["disposition"] == "DELIVERED", home and lives_there)
        kinds = {k for k, _, _, _, _ in rows}
        self.assertEqual("DeliveryProof" in kinds, attempt["disposition"] == "DELIVERED")
        if attempt["disposition"] == "FAILED":
            self.assertEqual(s.sim.facility_of(package, instant(occurred) + timedelta(hours=12)), depot)   # Back on the shelf.
        else:
            self.assertEqual(s.sim.where(package, instant(occurred) + timedelta(hours=1))[0], "PERSON")
            self.assertFalse([i for i in s.live.gateway.pending("PROVIDER") if i["source_event_id"].startswith(sid + "-")
                              and instant(s.live.gateway._decoded(i)[3]) > instant(occurred)])
        # A parcel that is not on a depot shelf (here: one on a vehicle) gets a receipt and nothing else.
        moving = next(pid for pid, r in sorted(s.state.parcels.items()) if (s.sim.where(pid, when) or ("",))[0] == "VEHICLE"
                      and s.live.gateway.splits.get(r["shipment_id"]) == "development" and r["shipment_id"] != sid)
        before = len(s.answers())
        receipt = s.sim.respond(s.execution(s.state.parcels[moving]["shipment_id"], "PRIORITIZE_NEXT_SESSION"), s.live.clock)
        self.assertTrue(receipt["acknowledged"])
        self.assertEqual(len(s.answers()), before)

    def test_reroute_and_return_move_a_parcel_only_from_where_it_is(self):
        base = Scenario(at("14T12:00"))
        package, depot, when = base.package_at_depot()
        sid = base.state.parcels[package]["shipment_id"]
        s = Scenario(iso(when))
        # No address the recipient confirmed: a reroute moves nothing.
        s.sim.respond(s.execution(sid, "REROUTE_TO_CONFIRMED_DESTINATION"), s.live.clock)
        self.assertEqual(s.answers(), [])
        s.sim.respond(s.execution(sid, "RETURN_TO_SENDER"), s.live.clock)
        rows = s.answers()
        origin = next(ref for _, kind, ref in s.state.parcels[package]["timeline"] if kind == "FACILITY")
        scans = [(o, p) for k, _, o, p, _ in rows if k == "ScanEvent"]
        self.assertEqual([p["facility_id"] for _, p in scans], [depot, origin])
        self.assertGreater(instant(scans[1][0]) - instant(scans[0][0]), timedelta(hours=1))   # It takes time to get there.
        self.assertEqual(s.sim.where(package, instant(scans[0][0]) + timedelta(minutes=30))[0], "VEHICLE")
        self.assertEqual(s.sim.facility_of(package, instant(scans[1][0]) + timedelta(minutes=1)), origin)
        # Once it has left, a rescan at the depot finds nothing to read.
        s.sim.respond(s.execution(sid, "REQUEST_RESCAN", entity_id="E-late"), iso(instant(scans[0][0]) + timedelta(hours=1)))
        self.assertEqual(len(s.answers()), len(rows))


class LifecycleTests(unittest.TestCase):
    def test_an_automatic_sync_that_uploads_the_buffered_records_resolves_the_case(self):
        s = Scenario(at("15T18:00"))
        symptoms = symptoms_at(s.live, OUTAGE_SHIPMENT, s.live.clock)
        self.assertEqual(symptoms, ["CUSTODY_TRANSFER_UNCONFIRMED"])
        case_id = seed_case(s.store, s.driver, OUTAGE_SHIPMENT, "REQUEST_DEVICE_SYNC", ["DELAYED_SYNC"], symptoms=symptoms,
                            target={"device_id": OUTAGE_DEVICE, "expected_evidence": []})
        self.assertEqual(s.store.status()["execution"]["adapter"], "world_operational_simulator")
        [executed] = s.store.execute_step()
        execution = s.driver.ledger[executed][1]
        self.assertEqual((execution["status"], execution["mode"]), ("ACKNOWLEDGED", "world_operational_simulator"))
        self.assertEqual(s.case(case_id)["workflow_state"], "AWAITING_OUTCOME")   # A receipt is not an outcome.
        self.assertEqual(s.store.outcome_step(), [])
        s.run(2)
        detail = s.case(case_id)
        self.assertEqual(detail["workflow_state"], "RESOLVED")
        outcome = detail["outcome"]
        self.assertEqual((outcome["verification_status"], outcome["outcome_type"], outcome["exception_cleared"], outcome["verifier_id"]),
                         ("VERIFIED", "delayed_upload_received", True, "SUHAIL-OUTCOME-VERIFIER"))
        executed_at = instant(str(execution["executed_at"]))
        for key in outcome["evidence_ids"]:      # Every record that verified it reached Suhail after the action.
            self.assertGreater(instant(s.live.world.nodes[key].properties["recorded_at"]), executed_at)
        self.assertLess(instant(s.live.clock), instant(at("16T04:00")))   # Hours before the phone reconnects by itself.
        self.assertIn("CASE_RESOLVED", s.audits(case_id))
        self.assertEqual(symptoms_at(s.live, OUTAGE_SHIPMENT, s.live.clock), [])

    def test_a_sync_on_a_healthy_device_is_acknowledged_and_resolves_nothing(self):
        self.healthy_sync()

    def healthy_sync(self):
        s = Scenario(at("15T18:00"))
        symptoms = symptoms_at(s.live, OUTAGE_SHIPMENT, s.live.clock)
        case_id = seed_case(s.store, s.driver, OUTAGE_SHIPMENT, "REQUEST_DEVICE_SYNC", ["DELAYED_SYNC"], symptoms=symptoms,
                            target={"device_id": HEALTHY_DEVICE, "expected_evidence": []})
        [executed] = s.store.execute_step()
        self.assertEqual(s.driver.ledger[executed][1]["status"], "ACKNOWLEDGED")
        s.run(12)   # Past 04:08: the other phone reconnects by itself and its records arrive.
        self.assertEqual(symptoms_at(s.live, OUTAGE_SHIPMENT, s.live.clock), [])
        self.assertEqual(s.case(case_id)["workflow_state"], "AWAITING_OUTCOME")   # Not this action's effect: not credited.
        s.run(66, step=6)   # Until the action's deadline.
        detail = s.case(case_id)
        self.assertEqual(detail["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual((detail["outcome"]["success"], detail["outcome"]["outcome_type"]), (False, "no_confirming_evidence"))
        self.assertIn("OUTCOME_FAILED", s.audits(case_id))
        self.assertNotIn("CASE_RESOLVED", s.audits(case_id))
        return s, case_id

    def test_a_rescan_that_confirms_a_wrong_label_leaves_the_case_with_a_person(self):
        self.wrong_label_rescan()

    def wrong_label_rescan(self):
        s = Scenario(at("17T03:30"))
        symptoms = symptoms_at(s.live, WRONG_LABEL, s.live.clock)
        self.assertEqual(symptoms, ["BARCODE_READ_DIFFERS"])
        case_id = seed_case(s.store, s.driver, WRONG_LABEL, "REQUEST_RESCAN", ["BARCODE_MISMATCH"], symptoms=symptoms)
        s.run(2)
        detail = s.case(case_id)
        self.assertEqual(detail["executions"][0]["status"], "ACKNOWLEDGED")       # The action worked technically.
        self.assertTrue([k for k in detail["outcome"]["evidence_ids"] if "-SIM-RESCAN" in k])   # Judged from the requested rescan.
        self.assertEqual(detail["workflow_state"], "HUMAN_REVIEW")                # The parcel's real problem is still there.
        self.assertEqual((detail["outcome"]["success"], detail["outcome"]["outcome_type"], detail["outcome"]["exception_cleared"]),
                         (False, "barcode_still_differs", False))
        return s, case_id

    def test_a_rescan_of_a_one_off_misread_resolves(self):
        s = Scenario(at("17T03:30"))
        sid = "DEMO-SHP-000064"
        case_id = seed_case(s.store, s.driver, sid, "REQUEST_RESCAN", ["BARCODE_MISMATCH"], symptoms=symptoms_at(s.live, sid, s.live.clock))
        s.run(2)
        detail = s.case(case_id)
        self.assertEqual((detail["workflow_state"], detail["outcome"]["outcome_type"]), ("RESOLVED", "barcode_corrected"))

    def test_an_address_confirmation_never_closes_a_failed_delivery(self):
        s = Scenario(at("17T07:00"))
        symptoms = symptoms_at(s.live, FAILED_ATTEMPT, s.live.clock)
        self.assertEqual(symptoms, ["DELIVERY_ATTEMPT_FAILED"])
        case_id = seed_case(s.store, s.driver, FAILED_ATTEMPT, "REQUEST_ADDRESS_CONFIRMATION", ["ADDRESS_CONFLICT"], symptoms=symptoms)
        s.run(6)
        detail = s.case(case_id)
        outcome = detail["outcome"]
        self.assertEqual((outcome["success"], outcome["outcome_type"], outcome["exception_cleared"]), (True, "address_confirmed", False))
        self.assertIn("DELIVERY_NOT_VERIFIED", outcome["remaining_symptoms"])
        self.assertIn("DELIVERY_ATTEMPT_FAILED", outcome["remaining_symptoms"])
        self.assertEqual(detail["workflow_state"], "HUMAN_REVIEW")
        self.assertIn("OUTCOME_VERIFIED_EXCEPTION_REMAINS", s.audits(case_id))

    def test_a_reconciliation_that_finds_the_parcel_is_verified_and_a_wrong_facility_answers_not_found(self):
        package = UNSCANNED_AT_DEPOT + "-PKG-01"
        outcomes = {}
        for facility in ("DEMO-DEPOT-MED-01", "DEMO-HUB-JED-01"):
            s = Scenario(at("19T04:00"))
            symptoms = symptoms_at(s.live, UNSCANNED_AT_DEPOT, s.live.clock)
            self.assertEqual(symptoms, ["MILESTONE_OVERDUE"])
            target = {"device_id": None, "expected_evidence": [{"package_id": package, "predicate": "RECEIVED", "location_id": facility}]}
            case_id = seed_case(s.store, s.driver, UNSCANNED_AT_DEPOT, "REQUEST_HUB_CHECK", ["MISSED_MILESTONE"], symptoms=symptoms, target=target)
            s.run(3)
            detail = s.case(case_id)
            outcomes[facility] = (detail["workflow_state"], detail["outcome"]["success"], detail["outcome"]["outcome_type"],
                                  detail["outcome"]["exception_cleared"])
        # Found where it is: verified, yet the receipt the plan expects is still missing, so a person takes it.
        self.assertEqual(outcomes["DEMO-DEPOT-MED-01"][1:3], (True, "parcel_located"))
        self.assertEqual(outcomes["DEMO-DEPOT-MED-01"][0] == "RESOLVED", outcomes["DEMO-DEPOT-MED-01"][3])
        self.assertEqual(outcomes["DEMO-HUB-JED-01"], ("HUMAN_REVIEW", False, "parcel_not_found", False))

    def test_with_no_adapter_nothing_is_acknowledged_and_the_case_goes_to_a_person(self):
        s = Scenario(at("17T03:30"))
        s.store.adapter = None
        case_id = seed_case(s.store, s.driver, WRONG_LABEL, "REQUEST_RESCAN", ["BARCODE_MISMATCH"], symptoms=["BARCODE_READ_DIFFERS"])
        s.run(1)
        self.assertEqual(s.case(case_id)["workflow_state"], "HUMAN_REVIEW")
        self.assertIn("ACTION_NOT_ACKNOWLEDGED", s.audits(case_id))


class ApprovalTests(unittest.TestCase):
    def setup(self):
        s = Scenario(at("17T07:00"))
        case_id = seed_case(s.store, s.driver, FAILED_ATTEMPT, "RETURN_TO_SENDER", ["RECIPIENT_UNAVAILABLE"], auto=False,
                            symptoms=symptoms_at(s.live, FAILED_ATTEMPT, s.live.clock))
        return s, case_id

    def test_an_approval_required_action_runs_only_after_a_person_approves(self):
        s, case_id = self.setup()
        self.assertEqual(s.case(case_id)["workflow_state"], "AWAITING_APPROVAL")
        self.assertEqual(s.store.execute_step(), [])                 # Nothing is authorized: nothing is dispatched.
        self.assertEqual(s.kind("OpsExecution"), [])
        self.assertEqual(s.answers(), [])
        with self.assertRaises(OperationsConflict):                  # The automatic path may never authorize it.
            s.store._execute(lambda tx: s.store._authorize_execution(
                tx, s.store._case(tx, case_id), "DEMO-OPS-EXECUTION-X", case_id, {"action_code": "RECIPIENT_UNAVAILABLE"}, "RETURN_TO_SENDER",
                "AUTO_POLICY", s.live.clock, decision_id=None, decided_risk="APPROVAL_REQUIRED", recommendation_id="R", run_id="RUN"), write=True)
        detail = s.case(case_id)
        self.assertTrue(detail["recommendation"]["approvable"])
        result = s.store.decide(case_id, "approve", OPERATOR, detail["state_version"], "approve-1")
        self.assertEqual(result["workflow_state"], "AWAITING_OUTCOME")
        self.assertIn("APPROVAL_CONTEXT_CHECKED", s.audits(case_id))
        [executed] = s.store.execute_step()
        execution = s.driver.ledger[executed][1]
        self.assertEqual((execution["authority"], execution["status"]), ("OPERATOR_APPROVAL", "ACKNOWLEDGED"))
        self.assertIn("EXECUTION_CONTEXT_CHECKED", s.audits(case_id))   # Rechecked again immediately before dispatch.
        self.assertEqual(s.case(case_id)["workflow_state"], "AWAITING_OUTCOME")   # Approval and receipt are not an outcome.

    def test_routine_records_since_the_recommendation_do_not_refuse_an_approval_and_a_material_one_does(self):
        import json
        from unittest import mock
        from operations import materiality
        s, case_id = self.setup()
        advance(s.store, s.live, 30)     # The parcel's next day: new records of this shipment arrive, none of them material.
        detail = s.case(case_id)
        self.assertTrue(detail["recommendation"]["approvable"])
        self.assertFalse(detail["recommendation"]["approval_context_stale"])
        # The same records with one of them material (as operations.materiality reports a late upload): refused, AUTH-20.
        late = [{"reason": "late_upload", "entity_id": "DEMO-LATE-SCAN", "kind": "ScanEvent"}]
        with mock.patch.object(materiality, "material_evidence", return_value=late):
            self.assertFalse(s.case(case_id)["recommendation"]["approvable"])
            with self.assertRaises(OperationsConflict) as refused:
                s.store.decide(case_id, "approve", OPERATOR, detail["state_version"], "approve-late")
        self.assertIn("AUTH-20", str(refused.exception))
        self.assertIn("late_upload (DEMO-LATE-SCAN)", str(refused.exception))
        self.assertEqual(s.kind("OpsExecution"), [])
        self.assertEqual(s.answers(), [])

    def test_an_approval_after_routine_records_is_rechecked_and_authorized(self):
        import json
        s, case_id = self.setup()
        advance(s.store, s.live, 30)
        detail = s.case(case_id)
        result = s.store.decide(case_id, "approve", OPERATOR, detail["state_version"], "approve-after-routine")
        self.assertEqual(result["workflow_state"], "AWAITING_OUTCOME")
        checked = [a for a in s.kind("OpsAudit") if a["event_type"] == "APPROVAL_CONTEXT_CHECKED"]
        self.assertEqual(len(checked), 1)
        self.assertGreater(json.loads(checked[0]["result"])["routine_new_records"], 0)     # the recheck ran over the new records


class HumanOutcomeTests(unittest.TestCase):
    def test_a_person_cannot_close_a_failed_verification_with_evidence_that_was_already_there(self):
        s, case_id = LifecycleTests("test_a_rescan_that_confirms_a_wrong_label_leaves_the_case_with_a_person").wrong_label_rescan()
        detail = s.case(case_id)
        visible = s.live.evidence(WRONG_LABEL, s.live.clock)["nodes"]
        old = [n["id"] for n in visible if n["kind"] in ("Package", "ScanEvent", "CustodyEvent") and "-SIM-" not in n["id"]]
        rescan = [n["id"] for n in visible if "-SIM-RESCAN" in n["id"]]
        self.assertTrue(old and rescan)
        finding = "The parcel was found on the counter shelf during the branch check."
        for cited, kind in ((old, "parcel_located"), (rescan, "parcel_located"), (old + rescan, "data_corrected")):
            # Older evidence proves nothing new, and the rescan read another order's barcode: it locates nothing.
            with self.assertRaises(OperationsConflict):
                s.store.record_human_outcome(case_id, OPERATOR, kind, finding, cited, detail["state_version"], f"h-{kind}-{len(cited)}")
        self.assertEqual(s.case(case_id)["workflow_state"], "HUMAN_REVIEW")
        self.assertEqual(len(s.kind("OpsOutcome")), 1)

    def test_a_finding_with_later_relevant_evidence_closes_only_when_nothing_remains(self):
        s, case_id = LifecycleTests("test_a_sync_on_a_healthy_device_is_acknowledged_and_resolves_nothing").healthy_sync()
        from dataset_v2.derive import custody_corroborated
        from operations.reasoning import evidence_world
        world = evidence_world(s.live.evidence(OUTAGE_SHIPMENT, s.live.clock), s.live.world.config)
        execution = next(e for e in s.kind("OpsExecution") if e["case_id"] == case_id)
        after = instant(str(execution["executed_at"]))
        later = [n.id for n in world.nodes.values() if n.kind == "CustodyEvent" and instant(n.properties["recorded_at"]) > after
                 and world.nodes.get(n.properties.get("to_id")) is not None and world.nodes[n.properties["to_id"]].kind in ("SortingCenter", "Hub", "DeliveryDepot")
                 and custody_corroborated(world, n, instant(s.live.clock))]
        self.assertTrue(later)
        detail = s.case(case_id)
        finding = "Both parcels were scanned in at the sorting centre after the request."
        # The harness may record it, but a harness finding is never a trusted precedent.
        with self.assertRaises(OperationsConflict):
            s.store.record_human_outcome(case_id, HARNESS_ACTOR, "parcel_located", finding, later, detail["state_version"], "as-operator")
        closed = s.store.record_human_outcome(case_id, OPERATOR, "parcel_located", finding, later, detail["state_version"], "human-1")
        self.assertEqual((closed["workflow_state"], closed["verification_status"], closed["remaining_symptoms"]), ("RESOLVED", "HUMAN_VERIFIED", []))
        outcome = s.driver.ledger[closed["outcome_id"]][1]
        self.assertEqual((outcome["source"], outcome["trusted_precedent"], outcome["exception_cleared"]), ("operator", True, True))
        self.assertTrue(set(outcome["relevant_evidence_ids"]) <= set(later))
        self.assertTrue(s.store.record_human_outcome(case_id, OPERATOR, "parcel_located", finding, later, detail["state_version"], "human-1")["idempotent"])
        # Reopened: neither the verifier's outcome nor the person's stands as a precedent any more.
        s.store.decide(case_id, "reopen", OPERATOR, s.case(case_id)["state_version"], "reopen-1")
        self.assertTrue(all(o["invalidated"] and not o["trusted_precedent"] for o in s.kind("OpsOutcome") if o["verification_status"] != "HUMAN_FINDING"))

    def test_a_harness_finding_is_recorded_under_the_harness_and_never_trusted(self):
        s, case_id = LifecycleTests("test_a_sync_on_a_healthy_device_is_acknowledged_and_resolves_nothing").healthy_sync()
        from operations.reasoning import evidence_world
        world = evidence_world(s.live.evidence(OUTAGE_SHIPMENT, s.live.clock), s.live.world.config)
        execution = next(e for e in s.kind("OpsExecution") if e["case_id"] == case_id)
        later = [n.id for n in world.nodes.values() if n.kind == "CustodyEvent" and instant(n.properties["recorded_at"]) > instant(str(execution["executed_at"]))]
        closed = s.store.record_human_outcome(case_id, HARNESS_ACTOR, "parcel_located", "Parcels located by the harness check of later scans.",
                                              later, s.case(case_id)["state_version"], "harness-1", source="harness")
        outcome = s.driver.ledger[closed["outcome_id"]][1]
        self.assertEqual((outcome["source"], outcome["verifier_id"], outcome["trusted_precedent"]), ("harness", HARNESS_ACTOR, False))

    def test_a_finding_is_recorded_but_the_case_stays_open_while_the_exception_remains(self):
        s = Scenario(at("19T04:00"))
        package = UNSCANNED_AT_DEPOT + "-PKG-01"
        target = {"device_id": None, "expected_evidence": [{"package_id": package, "predicate": "RECEIVED", "location_id": "DEMO-DEPOT-MED-01"}]}
        case_id = seed_case(s.store, s.driver, UNSCANNED_AT_DEPOT, "REQUEST_HUB_CHECK", ["MISSED_MILESTONE"], target=target,
                            symptoms=symptoms_at(s.live, UNSCANNED_AT_DEPOT, s.live.clock))
        s.run(3)
        detail = s.case(case_id)
        if detail["workflow_state"] == "RESOLVED":
            self.skipTest("the check itself cleared the exception in this world")
        self.assertIn("MILESTONE_OVERDUE", detail["outcome"]["remaining_symptoms"])
        scan = [n["id"] for n in s.live.evidence(UNSCANNED_AT_DEPOT, s.live.clock)["nodes"] if "-SIM-CHECK" in n["id"]]
        result = s.store.record_human_outcome(case_id, OPERATOR, "parcel_located", "The depot found the parcel on shelf C2 during the check.",
                                              scan, detail["state_version"], "human-open")
        self.assertEqual((result["workflow_state"], result["verification_status"], result["resolved"]), ("ESCALATED", "HUMAN_FINDING", False))
        self.assertIn("MILESTONE_OVERDUE", result["remaining_symptoms"])
        outcome = s.driver.ledger[result["outcome_id"]][1]
        self.assertEqual((outcome["success"], outcome["exception_cleared"], outcome["trusted_precedent"]), (False, False, False))
        negative = s.store.record_human_outcome(case_id, OPERATOR, "parcel_not_found", "Searched the returns cage and shelves; nothing found.",
                                                [package], s.case(case_id)["state_version"], "human-negative")
        self.assertEqual((negative["workflow_state"], negative["resolved"]), ("ESCALATED", False))


if __name__ == "__main__":
    unittest.main()
