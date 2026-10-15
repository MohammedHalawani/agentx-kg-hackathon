"""V3.2: a barcode-mismatch rescan is checked at the facility where this shipment's own package was misread.

Before this, a rescan target took its facilities only from missed milestones and the last corroborated custody
transfer, so a mismatch read at a facility named by neither had no facility and its strict rescan could never verify.

Shown here on the real store, claims, authority, dispatch, action lifecycle, verifier and closure (in-memory port,
scripted investigator and reviewer from tests.test_v3_concurrency; no database, no model):

  - such a case, whose earlier target was empty, resolves after a qualifying, manifest-matching new rescan;
  - acknowledgement and acceptance alone leave it waiting;
  - foreign, stale, low-confidence, wrong-device and wrong-facility rescans leave it waiting;
  - a rescan that still reads a different label does not resolve it;
  - the workers release their claims while the cases wait, and a worker takes a third case meanwhile.
"""
import copy
import json
import os
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from dataset_v2.contracts import Config, instant, iso
from dataset_v2.generate import generate
from operations.action_lifecycle import SyntheticActionAdapter, load
from operations.graph import action_target
from operations.lifecycle import OperationsConflict
from operations.outcome_engine import FACILITIES
from operations.store import CONTROL_ID, OperationsStore
from tests.test_operations_store import Driver, Reader, WallClock, development_reset
from tests.test_v3_concurrency import Base, Hooked, WORKERS

# A world large enough to hold a barcode mismatch read at a facility outside the missed milestones and last custody.
TOTAL = 600
WORLD = None


def world():
    global WORLD
    if WORLD is None:
        WORLD = generate(Config(total=TOTAL))
    return WORLD


class RescanTargetResolution(Base):
    def setUp(self):
        self.world = copy.deepcopy(world())
        env = patch.dict(os.environ, {"SUHAIL_SYNTHETIC_ACTION_RESPONSES": "1"})
        env.start()
        self.addCleanup(env.stop)

    def mismatched(self, scan):
        p = scan.properties
        return (p.get("package_id") in self.world.nodes and p.get("observed_barcode") is not None and
                p["observed_barcode"] != self.world.nodes[p["package_id"]].properties.get("manifest_barcode"))

    def make(self, cases=3, capacity=2):
        """A store whose monitor has opened a case for every development shipment with a barcode mismatch, and at
        least `cases` cases in all."""
        self.mism = {n.properties["shipment_id"] for n in self.world.of_kind("ScanEvent")
                     if n.properties.get("split") == "development" and self.mismatched(n)}
        self.assertGreaterEqual(len(self.mism), 2, "the world must hold two barcode-mismatch shipments")
        driver = Driver(self.world)
        store = OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world))
        store.initialize()
        development_reset(store)
        self.clock = store.wall = WallClock()
        store.claim_heartbeats, store.capacity, store.stage_flush_seconds = False, capacity, 0
        for _ in range(60):
            store.tick(seconds=86400, manual=True, speed=60)
            while store.status()["session"]["monitor_pending"]:
                store.monitor_step()
            opened = {c["shipment_id"] for c in self.kind(driver, "OpsCase")}
            if self.mism <= opened and len(opened) >= cases:
                break
        self.assertTrue(self.mism <= opened and len(opened) >= cases)
        store.adapter = SyntheticActionAdapter()
        return store, driver

    def control(self, driver):
        return driver.ledger[CONTROL_ID][1]

    def now(self, driver):
        v = self.control(driver)["as_of"]
        return v if isinstance(v, datetime) else instant(str(v))

    def move(self, driver, minutes, *cases):
        clock = self.now(driver) + timedelta(minutes=minutes)
        self.control(driver)["as_of"] = clock
        for case_id in cases:
            driver.ledger[case_id][1]["as_of"] = clock

    def execution_of(self, driver, case_id):
        [e] = [e for e in self.kind(driver, "OpsExecution") if e["case_id"] == case_id]
        return e

    def respond(self, store, driver, case_id, kind, key, evidence=()):
        e = self.execution_of(driver, case_id)
        return store.record_action_response(case_id, e["entity_id"], actor_id="DEMO-OPERATOR-LOCAL",
                                            expected_revision=load(e)["revision"], response_id=key, kind=kind,
                                            occurred_at=iso(self.now(driver)), evidence_ids=list(evidence),
                                            source_ref="synthetic:test-field-response")

    def rescan(self, driver, case_id, tag, **override):
        """One new rescan per target package, by an independent device at the target facility, reading the manifest
        label; `override` changes one property to make it non-qualifying."""
        e = self.execution_of(driver, case_id)
        target = json.loads(e["action_target_json"])
        clock = iso(self.now(driver))
        refs = []
        for i, package in enumerate(target["package_ids"]):
            props = dict(shipment_id=e["shipment_id"], split="development", package_id=package, occurred_at=clock,
                         recorded_at=clock, facility_id=target["facility_ids"][0], readable=True, confidence=.99,
                         device_ref="DEMO-DEVICE-TEST-INDEPENDENT",
                         observed_barcode=self.world.nodes[package].properties["manifest_barcode"],
                         source_ref="synthetic:test-independent-rescan")
            props.update(override)
            refs.append(self.world.node("ScanEvent", f"DEMO-TEST-RESCAN-{tag}-{case_id[-6:]}-{i}", **props))
        return refs

    def outcomes(self, driver, case_id):
        return [o for o in self.kind(driver, "OpsOutcome") if o["case_id"] == case_id]

    def assertWaiting(self, store, driver, case_id):
        self.assertEqual(self.case(driver, case_id)["workflow_state"], "AWAITING_OUTCOME")
        self.assertEqual(self.outcomes(driver, case_id), [])
        self.assertNotEqual(store.case_detail(case_id)["action_status"]["resolution"], "VERIFIED_RESOLVED")

    def investigate_mismatch_cases(self, store, driver):
        """Both workers investigate the two barcode-mismatch cases at once; each authorizes an automatic rescan and
        releases its claim, and the rescans are dispatched. Returns (case with a formerly empty target, the other)."""
        self.control(driver)["worker_state"] = "running"
        barrier = threading.Barrier(2)
        store.agents = Hooked(lambda t: barrier.wait(15), lambda t: barrier.wait(15))
        self.assertEqual(len(self.mism), 2, "two barcode-mismatch shipments, one per worker")
        a_id, b_id = sorted(c["entity_id"] for c in self.kind(driver, "OpsCase") if c["shipment_id"] in self.mism)
        results = self.together(store, {n: (lambda n=n, c=c: store.process_one(c, worker_id=n)) for n, c in zip(WORKERS, (a_id, b_id))})
        self.assertTrue(all(isinstance(r, dict) and r["processed"] for r in results.values()), results)
        self.assertEqual({r["case_id"] for r in results.values()}, {a_id, b_id})
        self.assertEqual(store.status()["worker"]["active_count"], 0)
        self.assertTrue(all(self.case(driver, c).get("claim_id") is None for c in (a_id, b_id)))
        self.assertEqual(len(store.execute_step()), 2)
        tools = {s["shipment"]: s["tools"] for s in store.agents.seen}
        fixed = []
        for c in (a_id, b_id):
            e = self.execution_of(driver, c)
            self.assertEqual(e["action_type"], "REQUEST_RESCAN")
            self.assertEqual(load(e)["state"], "AWAITING_ACKNOWLEDGEMENT")
            self.assertWaiting(store, driver, c)
            t = tools[e["shipment_id"]]
            misread = {n.properties["facility_id"] for n in t.nodes.values() if n.kind == "ScanEvent" and
                       n.properties.get("package_id") in t.nodes and n.properties.get("observed_barcode") is not None and
                       n.properties["observed_barcode"] != t.nodes[n.properties["package_id"]].properties.get("manifest_barcode")}
            stored = json.loads(e["action_target_json"])["facility_ids"]
            self.assertTrue(misread <= set(stored), (misread, stored))   # the misread facility is a rescan target
            if not action_target(t, [])["facility_ids"]:                 # the target as computed before the fix
                fixed.append(c)
        self.assertTrue(fixed, "the world must hold a barcode case whose earlier rescan target had no facility")
        case_id = fixed[0]
        return case_id, (b_id if case_id == a_id else a_id)

    def test_formerly_empty_target_resolves_only_on_a_qualifying_rescan(self):
        store, driver = self.make()
        case_id, other = self.investigate_mismatch_cases(store, driver)
        e = self.execution_of(driver, case_id)
        target = json.loads(e["action_target_json"])
        self.assertTrue(target["facility_ids"] and target["baseline_device_ids"], target)

        # Worker release while both wait: a worker takes the oldest other eligible case.
        third = store.process_one(worker_id=WORKERS[0])
        self.assertTrue(third["processed"], third)
        self.assertNotIn(third["case_id"], (case_id, other))
        self.assertEqual(store.status()["worker"]["active_count"], 0)
        store.execute_step()

        # Acknowledgement and acceptance alone leave the case waiting.
        self.move(driver, 10, case_id, other)
        self.respond(store, driver, case_id, "ACKNOWLEDGED", "ack")
        self.respond(store, driver, case_id, "ACCEPTED", "accept")
        self.assertEqual([r for r in store.outcome_step(force=True) if r["case_id"] == case_id], [])
        self.assertWaiting(store, driver, case_id)
        self.assertEqual(load(self.execution_of(driver, case_id))["state"], "ACCEPTED")

        # Non-qualifying rescans that read the manifest label: none of them resolves the case.
        sid = e["shipment_id"]
        policy = self.world.nodes[self.world.nodes[sid].properties["policy_id"]].properties
        minimum = float(policy.get("barcode_min_confidence") or 0)
        self.assertGreater(minimum, 0)
        elsewhere = next(n.id for n in self.world.nodes.values() if n.kind in FACILITIES and n.id not in target["facility_ids"])
        foreign = next(n.id for n in self.world.of_kind("Shipment") if n.id != sid)
        self.move(driver, 10, case_id, other)
        dispatched = instant(e["occurred_at"])
        variants = {
            "stale": {"occurred_at": iso(dispatched - timedelta(minutes=5))},           # made before the request
            "lowconf": {"confidence": minimum / 2},
            "baseline": {"device_ref": target["baseline_device_ids"][0]},                # the device that misread it
            "elsewhere": {"facility_id": elsewhere},
        }
        for n, (tag, override) in enumerate(variants.items()):
            refs = self.rescan(driver, case_id, tag, **override)
            self.respond(store, driver, case_id, "EVIDENCE_RECEIVED", f"evidence-{tag}", refs)
            self.assertEqual([r for r in store.outcome_step(force=True) if r["case_id"] == case_id], [], tag)
            self.assertWaiting(store, driver, case_id)
            self.move(driver, 5, case_id, other)
        # Another shipment's record is refused as a response and never credited by the verifier.
        refs = self.rescan(driver, case_id, "foreign", shipment_id=foreign)
        with self.assertRaises(OperationsConflict):
            self.respond(store, driver, case_id, "EVIDENCE_RECEIVED", "evidence-foreign", refs)
        self.assertEqual([r for r in store.outcome_step(force=True) if r["case_id"] == case_id], [])
        self.assertWaiting(store, driver, case_id)

        # A genuinely qualifying new rescan at the formerly missing facility, then its evidence response: resolved.
        self.move(driver, 5, case_id, other)
        refs = self.rescan(driver, case_id, "good")
        self.respond(store, driver, case_id, "EVIDENCE_RECEIVED", "evidence-good", refs)
        store.outcome_step(force=True)
        [outcome] = self.outcomes(driver, case_id)
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["outcome_type"], "barcode_corrected")
        self.assertTrue(set(refs) <= set(outcome["evidence_ids"]))
        self.assertEqual(self.case(driver, case_id)["workflow_state"], "RESOLVED")
        self.assertEqual(store.case_detail(case_id)["action_status"]["resolution"], "VERIFIED_RESOLVED")
        self.assertNotEqual(self.case(driver, other)["workflow_state"], "RESOLVED")

        # The resolved case is never claimed again.
        nxt = store.process_one(worker_id=WORKERS[1])
        self.assertNotIn(nxt.get("case_id"), (case_id,))
        self.assertEqual(len([r for r in self.kind(driver, "OpsRun") if r["case_id"] == case_id]), 1)

    def test_a_rescan_that_still_misreads_does_not_resolve(self):
        store, driver = self.make()
        case_id, _ = self.investigate_mismatch_cases(store, driver)
        self.move(driver, 10, case_id)
        self.respond(store, driver, case_id, "ACKNOWLEDGED", "ack")
        self.respond(store, driver, case_id, "ACCEPTED", "accept")
        self.move(driver, 10, case_id)
        refs = self.rescan(driver, case_id, "misread", observed_barcode="DEMO-OTHER-LABEL")
        self.respond(store, driver, case_id, "EVIDENCE_RECEIVED", "evidence-misread", refs)
        store.outcome_step(force=True)
        self.assertNotEqual(self.case(driver, case_id)["workflow_state"], "RESOLVED")
        self.assertFalse(any(o["success"] for o in self.outcomes(driver, case_id)))
        self.assertTrue(any(o["outcome_type"] == "barcode_still_differs" for o in self.outcomes(driver, case_id)))
        self.assertNotEqual(store.case_detail(case_id)["action_status"]["resolution"], "VERIFIED_RESOLVED")


if __name__ == "__main__":
    unittest.main()
