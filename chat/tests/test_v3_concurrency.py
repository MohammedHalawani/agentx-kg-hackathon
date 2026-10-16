"""V3: up to two cases are investigated at once, each under its own claim (operations.claims).

What is shown here, on the real store and the real investigation graph:

  - two different cases are inside their investigations at the same moment, each with its own tools, run, reviews,
    authority decision and stage stream;
  - a case is granted to one worker only, and capacity is never exceeded, whichever entry point asks;
  - a claim is a wall-clock lease: a paused or fast simulation clock neither expires nor extends it, and a renewal
    changes nothing but the lease;
  - a worker that lost its case (an expired lease, a pause, a new owner) can write nothing: no renewal, no progress
    event, no result, no recommendation, no authorized action, and it cannot release whoever holds the case now;
  - one worker failing does not stop the other, or automatic investigation; a case lost twice goes to a person;
  - the events a worker emits after committing its result are kept, and never set a finished run back to RUNNING;
  - an authorized action has one effect in the field, however often it is dispatched, replayed or recovered.

In-memory ledger (tests.test_operations_store.Driver: one writer at a time, as the OpsControl lock makes the database),
scripted investigator and reviewer: no database, no model. That a real database serialises grants the same way is
shown separately (tests.test_v3_concurrency_neo4j); this module alone does not prove it.
"""
import copy
import json
import os
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from dataset_v2.contracts import Config, instant
from dataset_v2.generate import generate
from operations import claims
from operations.lifecycle import OperationsConflict
from operations.reasoning import public_evidence
from operations.schema import FIELDS, public_value
from operations.store import CONTROL_ID, OperationsStore
from tests import test_investigator as ti
from tests.test_operations_store import Driver, Reader, WallClock, approval_policy, development_reset, live_claim
from tests.test_stage_event_batching import ManualTimer

WORKERS = ("investigation-1", "investigation-2")
STATUS_FIELDS = {"case_id", "shipment_id", "worker_id", "claim_id", "claim_epoch", "workflow_state", "run_id", "run_status",
                 "active_stage", "started_at", "updated_at", "lease_expires_at", "as_of", "state_version", "final_result"}
WORLD = None


def world():
    global WORLD
    if WORLD is None:
        WORLD = generate(Config(total=90))
    return WORLD


class Hooked(ti.FakeInvestigator):
    """The scripted investigator and reviewer over the real tools. `hooks` run in order, one per investigation, while
    that investigation is in progress (where a model call would be); `always` runs in every one."""
    cause, action = "BARCODE_MISMATCH", "REQUEST_RESCAN"

    def __init__(self, *hooks, always=None):
        super().__init__(lambda tools: [("shipment_overview", {})], ())
        self.hooks, self.always, self.seen, self.lock = list(hooks), always, [], threading.Lock()

    def investigate(self, tools, on_step=None, feedback=None):
        with self.lock:
            self.seen.append({"shipment": tools.sid, "tools": tools, "thread": threading.current_thread().name})
            hook = self.hooks.pop(0) if self.hooks else None
        for call in (self.always, hook):
            if call:
                call(tools)
        return super().investigate(tools, on_step=on_step, feedback=feedback)


class ProcessDied(BaseException):
    """Stands for the process ending mid-call: nothing catches it, so what was not committed is not written."""


class CountingAdapter:
    """A synthetic field system that acts once per idempotency key: a request it has seen is acknowledged again and
    nothing more happens. `die_after` requests end the process right after the effect, before any receipt is recorded."""
    name = "counting_synthetic_adapter"

    def __init__(self, die_after=()):
        self.effects, self.calls, self.die_after, self.lock = {}, 0, set(die_after), threading.Lock()

    def respond(self, execution, now):
        with self.lock:
            self.calls += 1
            call, key = self.calls, execution["idempotency_key"]
            replayed = key in self.effects
            self.effects.setdefault(key, {"execution_id": execution["entity_id"], "at": now})
        if call in self.die_after:
            raise ProcessDied()
        return {"acknowledged": True, "behaviour": "Replayed request; nothing further was done." if replayed else "Request accepted."}


class Base(unittest.TestCase):
    def setUp(self):
        self.world = copy.deepcopy(world())
        ManualTimer.made = []

    def make(self, cases=2, capacity=2):
        """A store whose monitor has opened at least `cases` cases. The wall clock is the test's, claims are renewed by
        hand and every progress event is written at once, so nothing here depends on timing."""
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
            if len(self.kind(driver, "OpsCase")) >= cases:
                break
        self.assertGreaterEqual(len(self.kind(driver, "OpsCase")), cases)
        self.held = []
        hold = store._hold
        store._hold = lambda claimed: (self.held.append(claimed), hold(claimed))[1]     # every claim granted, in order
        return store, driver

    def kind(self, driver, kind):
        return [public_value(copy.deepcopy(v)) for k, v in list(driver.ledger.values()) if k == kind]

    def case(self, driver, case_id):
        return next(c for c in self.kind(driver, "OpsCase") if c["entity_id"] == case_id)

    def queue(self, driver):
        """Case ids in the order the automatic worker takes them."""
        return [c["entity_id"] for c in sorted(self.kind(driver, "OpsCase"), key=lambda c: (instant(c["opened_at"]), c["entity_id"]))]

    def audits(self, driver, event_type, case_id=None):
        return [a for a in self.kind(driver, "OpsAudit") if a["event_type"] == event_type and (case_id is None or a["case_id"] == case_id)]

    def run_of(self, driver, run_id):
        return next(r for r in self.kind(driver, "OpsRun") if r["entity_id"] == run_id)

    def written_for(self, driver, run_id):
        """Every decision record written for a run: its reviews, recommendation and authorized actions."""
        return {kind: [r["entity_id"] for r in self.kind(driver, kind) if r.get("run_id") == run_id]
                for kind in ("OpsReview", "OpsRecommendation", "OpsExecution")}

    def together(self, store, calls):
        """Run each named call on its own thread; returns {name: result or the exception it raised}."""
        results = {}

        def work(name, call):
            try:
                results[name] = call()
            except Exception as error:
                results[name] = error
        threads = [threading.Thread(target=work, args=item, name=item[0]) for item in calls.items()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertFalse([t.name for t in threads if t.is_alive()], "an investigation never returned")
        return results


class SettingsTests(unittest.TestCase):
    def test_one_worker_is_the_default_and_only_one_to_four_are_allowed(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(claims.WORKERS_ENV, None)
            self.assertEqual(claims.investigation_workers(), 1)
            for text, expected in (("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 1), ("0", 1), ("-2", 1), ("two", 1), ("", 1), ("2.5", 1), ("nan", 1)):
                os.environ[claims.WORKERS_ENV] = text
                self.assertEqual(claims.investigation_workers(), expected, text)

    def test_the_lease_is_180_seconds_and_the_heartbeat_15_and_never_more_than_a_third_of_the_lease(self):
        self.assertEqual((claims.WORKERS_ENV, claims.LEASE_ENV, claims.HEARTBEAT_ENV),
                         ("SUHAIL_INVESTIGATION_WORKERS", "SUHAIL_CLAIM_LEASE_SECONDS", "SUHAIL_CLAIM_HEARTBEAT_SECONDS"))
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in (claims.LEASE_ENV, claims.HEARTBEAT_ENV):
                os.environ.pop(name, None)
            self.assertEqual((claims.lease_seconds(), claims.heartbeat_seconds(claims.lease_seconds())), (180.0, 15.0))
            for text, expected in (("60", 60.0), ("0", 180.0), ("-5", 180.0), ("soon", 180.0), ("99999", 3600.0), ("0.2", 1.0), ("inf", 180.0)):
                os.environ[claims.LEASE_ENV] = text
                self.assertEqual(claims.lease_seconds(), expected, text)
            for text, lease, expected in (("15", 180.0, 15.0), ("100", 180.0, 60.0), ("0", 180.0, 15.0), ("x", 180.0, 15.0), ("15", 30.0, 10.0)):
                os.environ[claims.HEARTBEAT_ENV] = text
                self.assertEqual(claims.heartbeat_seconds(lease), expected, (text, lease))
        self.assertEqual((claims.lease_seconds(45), claims.heartbeat_seconds(45.0, 5)), (45.0, 5.0))      # the store's own settings

    def test_the_new_ledger_fields_are_registered(self):
        self.assertLessEqual({"worker_id", "claim_epoch", "claim_wall_at", "claim_as_of", "lease_expires_at", "lease_heartbeat_at"},
                             FIELDS["OpsCase"])
        self.assertLessEqual({"worker_id", "claim_id", "claim_epoch"}, FIELDS["OpsRun"])
        self.assertLessEqual({"claim_id", "claim_at", "last_run_id", "as_of", "state_version"}, FIELDS["OpsCase"])     # kept


class OverlapTests(Base):
    def test_two_cases_are_investigated_at_the_same_time_each_with_its_own_records(self):
        store, driver = self.make()
        barrier, during = threading.Barrier(2), []

        def inside(tools):
            barrier.wait(15)        # passes only when both investigations are in progress at once
            during.append(store.status()["worker"])
        store.agents = Hooked(always=inside)
        listeners = {case_id: store.subscribe_pipeline(case_id) for case_id in self.queue(driver)[:2]}
        results = self.together(store, {name: (lambda name=name: store.process_one(manual=True, worker_id=name)) for name in WORKERS})
        self.assertEqual([type(r) for r in results.values()], [dict, dict], results)
        self.assertTrue(all(r["processed"] for r in results.values()), results)
        first, second = results[WORKERS[0]], results[WORKERS[1]]
        self.assertNotEqual(first["case_id"], second["case_id"])
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual({first["case_id"], second["case_id"]}, set(self.queue(driver)[:2]))        # the two oldest, FIFO
        # Each investigation had its own tools, on its own thread, over its own shipment's evidence only.
        seen = store.agents.seen
        self.assertEqual(len(seen), 2)
        self.assertIsNot(seen[0]["tools"], seen[1]["tools"])
        self.assertEqual({s["thread"] for s in seen}, set(WORKERS))
        self.assertNotEqual(seen[0]["shipment"], seen[1]["shipment"])
        for item in seen:
            visible = {n["id"] for n in public_evidence(self.world, item["shipment"], item["tools"].as_of)["nodes"]}
            self.assertTrue(item["tools"].retrieved)
            self.assertLessEqual(set(item["tools"].retrieved), visible)
        # While both ran: two live claims, no single "active case", both workers named.
        for worker in during:
            self.assertEqual((worker["concurrency"], worker["active_count"]), (2, 2))
            self.assertEqual((worker["active_case_id"], worker["active_shipment_id"]), (None, None))
            self.assertEqual({a["worker_id"] for a in worker["active_cases"]}, set(WORKERS))
            self.assertEqual({a["case_id"] for a in worker["active_cases"]}, {first["case_id"], second["case_id"]})
            for active in worker["active_cases"]:
                self.assertEqual(set(active), STATUS_FIELDS)
                self.assertEqual((active["run_status"], active["workflow_state"], active["claim_epoch"], active["final_result"]),
                                 ("RUNNING", "INVESTIGATING", 1, None))
                self.assertEqual(active["active_stage"], "classify")
                self.assertTrue(all(active[k] for k in ("claim_id", "run_id", "started_at", "updated_at", "lease_expires_at", "as_of")))
            self.assertEqual([a["case_id"] for a in worker["active_cases"]],
                             [a["case_id"] for a in sorted(worker["active_cases"], key=lambda a: (instant(a["started_at"]), a["case_id"]))])
        # Separate runs, reviews, authority decisions and stage streams, and nothing of one under the other.
        for name, result in results.items():
            case, run = self.case(driver, result["case_id"]), self.run_of(driver, result["run_id"])
            self.assertEqual((run["status"], run["end_reason"], run["worker_id"], run["case_id"]),
                             ("REVIEWED", claims.END_FINISHED, name, result["case_id"]))
            self.assertEqual((case["workflow_state"], case["last_run_id"]), (result["workflow_state"], result["run_id"]))
            self.assertIsNone(case.get("claim_id"))
            written = self.written_for(driver, result["run_id"])
            self.assertTrue(written["OpsReview"])
            self.assertEqual(len(self.audits(driver, "AUTHORITY_DECISION", result["case_id"])), 1)
            stages = sorted((a for a in self.audits(driver, "PIPELINE_STAGE", result["case_id"])), key=lambda a: a["sequence"])
            self.assertEqual([a["sequence"] for a in stages], list(range(1, len(stages) + 1)))
            self.assertEqual({a["run_id"] for a in stages}, {result["run_id"]})
            events = json.loads(run["result_json"])["pipeline_events"]
            self.assertEqual([e["sequence"] for e in events], [a["sequence"] for a in stages])
            extracted = next(e for e in events if (e["stage"], e["status"]) == ("extract", "COMPLETED"))
            self.assertEqual(extracted["output"]["shipment_id"], case["shipment_id"])
            states = []
            while not listeners[result["case_id"]].empty():
                states.append(listeners[result["case_id"]].get_nowait())
            self.assertTrue(states)
            self.assertEqual({s["run_id"] for s in states}, {result["run_id"]})         # never the other case's run
        worker = store.status()["worker"]
        self.assertEqual((worker["active_count"], worker["active_cases"], worker["processed_count"]), (0, [], 2))

    def test_one_case_is_granted_once_when_two_workers_ask_for_it_together(self):
        store, driver = self.make()
        store.agents = Hooked()
        case_id, start = self.queue(driver)[0], threading.Barrier(2)

        def ask(name):
            start.wait(15)
            return store.process_one(case_id=case_id, worker_id=name)
        results = self.together(store, {name: (lambda name=name: ask(name)) for name in WORKERS})
        won = [name for name, r in results.items() if r.get("processed")]
        lost = [r for r in results.values() if not r.get("processed")]
        self.assertEqual((len(won), len(lost)), (1, 1), results)
        self.assertEqual(lost[0], {"processed": False, "outcome": None, "reason": "none_eligible"})
        self.assertEqual(len(self.audits(driver, "CASE_CLAIMED", case_id)), 1)
        [run] = [r for r in self.kind(driver, "OpsRun") if r["case_id"] == case_id]
        self.assertEqual((run["worker_id"], run["claim_epoch"], run["status"]), (won[0], 1, "REVIEWED"))

    def test_a_case_being_investigated_cannot_be_claimed_again_and_capacity_holds_for_every_entry_point(self):
        store, driver = self.make(cases=3, capacity=2)
        first, second, third = self.queue(driver)[:3]
        seen = {}

        def while_two_run(tools):
            seen["same_case"] = store.process_one(case_id=first, worker_id="investigation-9")
            seen["manual"] = store.process_one(manual=True)
            seen["named"] = store.process_one(case_id=third)
            store.control("worker", "start")
            seen["automatic"] = store.process_one(worker_id="investigation-9")
            seen["count"] = store.status()["worker"]["active_count"]
        store.agents = Hooked(lambda tools: store.process_one(manual=True, worker_id=WORKERS[1]), while_two_run)
        result = store.process_one(manual=True, worker_id=WORKERS[0])
        self.assertTrue(result["processed"])
        self.assertEqual(seen["same_case"]["reason"], "capacity")       # two are live: nothing more is granted, whoever asks
        self.assertEqual([seen[k]["reason"] for k in ("manual", "named", "automatic")], ["capacity"] * 3)
        self.assertEqual(seen["count"], 2)
        self.assertEqual(self.case(driver, third)["workflow_state"], "OPEN")
        self.assertEqual(len(self.kind(driver, "OpsRun")), 2)
        self.assertTrue(store.process_one(case_id=third)["processed"])      # a place is free again

    def test_with_one_worker_it_behaves_as_before_and_names_its_single_active_case(self):
        store, driver = self.make(capacity=1)
        seen = {}

        def inside(tools):
            seen["second"] = store.process_one(manual=True, worker_id=WORKERS[1])
            seen["worker"] = store.status()["worker"]
        store.agents = Hooked(inside)
        first = store.process_one(manual=True, worker_id=WORKERS[0])
        self.assertTrue(first["processed"])
        self.assertEqual(seen["second"], {"processed": False, "outcome": None, "reason": "capacity"})
        worker = seen["worker"]
        self.assertEqual((worker["concurrency"], worker["active_count"]), (1, 1))
        self.assertEqual((worker["active_case_id"], worker["active_shipment_id"]),
                         (first["case_id"], self.case(driver, first["case_id"])["shipment_id"]))
        self.assertEqual([a["case_id"] for a in worker["active_cases"]], [first["case_id"]])
        after = store.status()["worker"]
        self.assertEqual((after["active_case_id"], after["active_count"], after["last_case_id"]), (None, 0, first["case_id"]))
        second = store.process_one(manual=True, worker_id=WORKERS[0])       # then the next one, in order
        self.assertTrue(second["processed"])
        self.assertEqual([first["case_id"], second["case_id"]], self.queue(driver)[:2])

    def test_a_paused_worker_claims_nothing_automatically_and_says_why(self):
        store, driver = self.make()
        store.agents = Hooked()
        self.assertEqual(store.process_one(worker_id=WORKERS[0]), {"processed": False, "outcome": None, "reason": "worker_paused"})
        self.assertEqual(self.kind(driver, "OpsRun"), [])


class LeaseTests(Base):
    def test_a_renewal_changes_only_the_lease_and_the_simulation_clock_never_moves_it(self):
        store, driver = self.make()
        seen = {}

        def inside(tools):
            claimed = self.held[0]
            before = self.case(driver, claimed["entity_id"])
            self.assertEqual(instant(before["lease_expires_at"]) - instant(before["claim_wall_at"]), timedelta(seconds=180))
            # The world runs far ahead (fast replay, then weeks of simulated time at once): the lease does not move, and
            # is still live.
            clock_before = store.status()["as_of"]
            for _ in range(3):
                store.tick(seconds=86400, manual=True, speed=3600)

            def weeks_later(tx):
                control = tx.ledger[CONTROL_ID][1]
                control["as_of"] = control["as_of"] + timedelta(days=45)
            driver.execute_write(weeks_later)
            fast = self.case(driver, claimed["entity_id"])
            self.assertGreater(instant(store.status()["as_of"]) - instant(clock_before), timedelta(days=30))
            self.assertEqual([fast[k] for k in ("lease_expires_at", "lease_heartbeat_at", "claim_wall_at", "claim_as_of", "claim_epoch")],
                             [before[k] for k in ("lease_expires_at", "lease_heartbeat_at", "claim_wall_at", "claim_as_of", "claim_epoch")])
            self.assertEqual(store.status()["worker"]["active_count"], 1)
            # The world is paused; wall time passes. Just inside the lease it is live, and a renewal extends it.
            store.control("simulator", "pause")
            self.clock.advance(179)
            self.assertEqual(store.status()["worker"]["active_count"], 1)
            store.renew_claim(claimed)
            renewed = self.case(driver, claimed["entity_id"])
            self.assertEqual(instant(renewed["lease_expires_at"]), self.clock.now + timedelta(seconds=180))
            self.assertEqual(instant(renewed["lease_heartbeat_at"]), self.clock.now)
            changed = {k for k in set(fast) | set(renewed) if fast.get(k) != renewed.get(k)}
            self.assertEqual(changed, {"lease_expires_at", "lease_heartbeat_at"})        # not the version, cutoff or counters
            seen["status"] = store.status()["worker"]["active_cases"][0]
            seen["updated"] = self.run_of(driver, claimed["last_run_id"])["updated_wall_at"]
            # Nobody renews for longer than the lease while the world stays paused: it expires all the same.
            paused_at = store.status()["as_of"]
            self.clock.advance(180)
            self.assertEqual(store.status()["as_of"], paused_at)
            self.assertEqual(store.status()["worker"]["active_count"], 0)
            with self.assertRaises(claims.ClaimLost) as lost:
                store.renew_claim(claimed)
            self.assertEqual(lost.exception.reason, "lease_expired")
        store.agents = Hooked(inside)
        result = store.process_one(manual=True, worker_id=WORKERS[0])
        self.assertEqual((result["processed"], result["reason"]), (False, "claim_lost"))
        self.assertEqual(seen["status"]["lease_expires_at"], (self.clock.now).isoformat())      # as renewed, 180 s before now
        # A renewal is not progress: the run's last-progress time is the last accepted event's, not the renewal's.
        self.assertLess(instant(seen["updated"]), instant(seen["status"]["lease_expires_at"]) - timedelta(seconds=180))
        self.assertEqual(seen["status"]["updated_at"], seen["updated"])

    def test_a_live_claim_renews_itself_on_its_own_thread_without_touching_the_case(self):
        store, driver = self.make()
        store.wall, store.claim_heartbeats, store.lease_seconds, store.heartbeat_seconds = claims.wall_now, True, 30, 0.02
        seen = {}

        def inside(tools):
            claimed = self.held[0]
            first = self.case(driver, claimed["entity_id"])
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and self.case(driver, claimed["entity_id"])["lease_heartbeat_at"] == first["lease_heartbeat_at"]:
                time.sleep(0.01)
            later = self.case(driver, claimed["entity_id"])
            seen["beat"] = instant(later["lease_heartbeat_at"]) > instant(first["lease_heartbeat_at"])
            seen["same"] = [(first[k], later[k]) for k in ("state_version", "as_of", "claim_epoch", "claim_id")]
            seen["thread"] = store._claims[claimed["entity_id"]].thread
        store.agents = Hooked(inside)
        result = store.process_one(manual=True, worker_id=WORKERS[0])
        self.assertTrue(result["processed"])
        self.assertTrue(seen["beat"])
        self.assertTrue(all(a == b for a, b in seen["same"]), seen["same"])
        self.assertFalse(seen["thread"].is_alive())          # the renewal thread ends with the run
        self.assertEqual(store._claims, {})

    def test_restart_recovers_only_expired_claims_and_never_takes_a_live_one(self):
        store, driver = self.make()
        seen = {}

        def inside(tools):
            claimed = self.held[0]
            restarted = OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world))
            restarted.wall = self.clock
            restarted.initialize()                              # another start of the service while this claim is live
            seen["live"] = self.case(driver, claimed["entity_id"])
            self.assertEqual(restarted.recover_claims(), [])
            self.clock.advance(181)
            restarted.initialize()                              # and one after the lease ran out
            seen["expired"] = self.case(driver, claimed["entity_id"])
        store.agents = Hooked(inside)
        result = store.process_one(manual=True, worker_id=WORKERS[0])
        self.assertEqual(result["reason"], "claim_lost")
        claimed = self.held[0]
        self.assertEqual([seen["live"][k] for k in claims.IDENTITY] + [seen["live"]["workflow_state"]],
                         [claimed[k] for k in claims.IDENTITY] + ["INVESTIGATING"])
        self.assertEqual((seen["expired"]["workflow_state"], seen["expired"]["claim_epoch"], seen["expired"].get("claim_id"),
                          seen["expired"]["claim_recoveries"]), ("OPEN", 2, None, 1))
        run = self.run_of(driver, claimed["last_run_id"])
        self.assertEqual((run["status"], run["end_reason"]), ("ABORTED", claims.END_EXPIRED))
        [audit] = self.audits(driver, "CLAIM_EXPIRED")
        self.assertIn(WORKERS[0], audit["result"])
        self.assertEqual(self.written_for(driver, claimed["last_run_id"]), {"OpsReview": [], "OpsRecommendation": [], "OpsExecution": []})


class FencingTests(Base):
    def test_after_expiry_a_new_owner_succeeds_and_the_old_one_can_write_nothing(self):
        store, driver = self.make()
        refused, seen = [], {}
        record = store._record_stages

        def recording(claimed, batch, events):
            # The old owner's event writes are refused; it carries on regardless, up to its result, which must be too.
            try:
                record(claimed, batch, events)
            except claims.ClaimLost as error:
                refused.append((claimed["worker_id"], error.reason, [e["sequence"] for e in batch]))
        store._record_stages = recording
        listener = {}

        def while_the_new_owner_runs(tools):
            old = self.held[0]
            before = copy.deepcopy(driver.ledger)
            for name, write in (("renew", lambda: store.renew_claim(old)),
                                ("events", lambda: record(old, [{"sequence": 99, "stage": "classify", "status": "RUNNING", "iteration": 0,
                                                                  "recorded_at": self.clock.now.isoformat(), "output": {}}], [])),
                                ("trace", lambda: store._save_run_trace(old, {"writeback": {"processed": True}, "result": {"workflow_state": "RESOLVED"}}))):
                with self.assertRaises(claims.ClaimLost, msg=name) as lost:
                    write()
                seen[name] = lost.exception.reason
            store._fail_claim(old, RuntimeError("late"))                    # cannot release the case its replacement holds
            self.assertEqual(store.release_claims({WORKERS[0]}), [])
            self.assertEqual(driver.ledger, before)                         # none of it wrote anything at all
            seen["owner"] = store.status()["worker"]["active_cases"]

        def while_the_old_owner_is_stalled(tools):
            old = self.held[0]
            listener["queue"] = store.subscribe_pipeline(old["entity_id"])
            self.clock.advance(181)                                         # a provider call that outlives the lease
            with self.assertRaises(claims.ClaimLost) as lost:
                store.renew_claim(old)                                      # expired is final, even with nobody else there yet
            seen["alone"] = lost.exception.reason
            self.assertEqual(store.status()["worker"]["active_count"], 0)
            seen["new"] = store.process_one(case_id=old["entity_id"], worker_id=WORKERS[1])
        store.agents = Hooked(while_the_old_owner_is_stalled, while_the_new_owner_runs)
        result = store.process_one(manual=True, worker_id=WORKERS[0])
        old, new = self.held
        self.assertEqual(result, {"processed": False, "case_id": old["entity_id"], "reason": "claim_lost", "outcome": None})
        self.assertTrue(seen["new"]["processed"])
        self.assertEqual((seen["alone"], seen["renew"], seen["events"], seen["trace"]), ("lease_expired", "superseded", "superseded", "run_closed"))
        self.assertEqual([(a["worker_id"], a["claim_epoch"], a["run_id"]) for a in seen["owner"]], [(WORKERS[1], 3, new["last_run_id"])])
        self.assertEqual((old["claim_epoch"], new["claim_epoch"]), (1, 3))          # granted, revoked, granted again
        self.assertNotEqual(old["claim_id"], new["claim_id"])
        # Every event the old owner emitted after it lost the case was refused, and so was its result.
        self.assertTrue(refused)
        self.assertEqual({(worker, reason) for worker, reason, _ in refused}, {(WORKERS[0], "released")})
        old_run, new_run = self.run_of(driver, old["last_run_id"]), self.run_of(driver, new["last_run_id"])
        self.assertEqual((old_run["status"], old_run["end_reason"]), ("ABORTED", claims.END_EXPIRED))
        self.assertEqual((new_run["status"], new_run["end_reason"], new_run["worker_id"]), ("REVIEWED", claims.END_FINISHED, WORKERS[1]))
        self.assertEqual(self.written_for(driver, old["last_run_id"]), {"OpsReview": [], "OpsRecommendation": [], "OpsExecution": []})
        stale = json.loads(old_run["result_json"])
        self.assertEqual(set(stale), {"pipeline_events"})                   # no result, proposal, review or authority of its own
        self.assertNotIn(99, [e["sequence"] for e in stale["pipeline_events"]])
        # The case is what its new owner made it; nothing was authorized from the stale run.
        case = self.case(driver, old["entity_id"])
        self.assertEqual((case["workflow_state"], case["last_run_id"], case["claim_recoveries"]),
                         (seen["new"]["workflow_state"], new["last_run_id"], 0))
        self.assertTrue(self.written_for(driver, new["last_run_id"])["OpsReview"])
        self.assertEqual({e["run_id"] for e in self.kind(driver, "OpsExecution")} - {new["last_run_id"]}, set())
        self.assertEqual({r["run_id"] for r in self.kind(driver, "OpsRecommendation")} - {new["last_run_id"]}, set())
        # Subscribers of the case were sent the new run's states and none of the old owner's late ones.
        states = []
        while not listener["queue"].empty():
            states.append(listener["queue"].get_nowait())
        self.assertTrue(states)
        self.assertEqual({s["run_id"] for s in states}, {new["last_run_id"]})
        self.assertEqual(len(self.audits(driver, "CLAIM_EXPIRED", old["entity_id"])), 1)

    def test_a_stale_result_that_would_have_acted_automatically_authorizes_nothing(self):
        """The same investigation twice: the one that keeps its claim authorizes its action; the one whose lease ran out
        before its result was written leaves no recommendation and no execution behind."""
        def investigate(expire):
            store, driver = self.make()
            store.agents = Hooked((lambda tools: self.clock.advance(181)) if expire else None)
            auto = ("AUTO", "Evidence request: reversible and policy-authorized.")
            with approval_policy(auto):
                result = store.process_one(manual=True, worker_id=WORKERS[0])
            return store, driver, result
        store, driver, kept = investigate(expire=False)
        self.assertTrue(kept["processed"])
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["authority"], execution["status"], execution["run_id"]), ("AUTO_POLICY", "AUTHORIZED", kept["run_id"]))
        store, driver, lost = investigate(expire=True)
        self.assertEqual(lost["reason"], "claim_lost")
        self.assertEqual((self.kind(driver, "OpsExecution"), self.kind(driver, "OpsRecommendation"), self.kind(driver, "OpsReview")), ([], [], []))
        self.assertEqual(self.audits(driver, "ACTION_AUTHORIZED"), [])
        case = self.case(driver, lost["case_id"])
        self.assertEqual((case["workflow_state"], case.get("recommendation_id")), ("INVESTIGATING", None))    # until it is recovered
        store.agents = Hooked()
        with approval_policy(("AUTO", "Evidence request: reversible and policy-authorized.")):
            again = store.process_one(case_id=lost["case_id"], worker_id=WORKERS[1])       # recovered, then investigated afresh
        self.assertTrue(again["processed"])
        self.assertEqual([e["run_id"] for e in self.kind(driver, "OpsExecution")], [again["run_id"]])

    def test_a_pause_revokes_every_live_claim_and_their_late_results_are_refused(self):
        store, driver = self.make()
        store.control("worker", "start")
        barrier, paused = threading.Barrier(3), threading.Event()

        def inside(tools):
            barrier.wait(15)
            paused.wait(15)
        store.agents = Hooked(always=inside)
        results = {}
        threads = [threading.Thread(target=lambda name=name: results.update({name: store.process_one(worker_id=name)}), name=name)
                   for name in WORKERS]
        for thread in threads:
            thread.start()
        barrier.wait(15)                                    # both investigations are in progress
        handles = dict(store._claims)
        self.assertEqual(store.status()["worker"]["active_count"], 2)
        status = store.control("worker", "pause", actor_id="DEMO-OPERATOR-LOCAL")
        self.assertEqual((status["worker"]["state"], status["worker"]["active_count"]), ("paused", 0))
        self.assertTrue(all(handle.cancelled.is_set() for handle in handles.values()))
        paused.set()
        for thread in threads:
            thread.join(60)
        self.assertEqual(sorted(r["reason"] for r in results.values()), ["claim_lost", "claim_lost"])
        for claimed in self.held:
            case, run = self.case(driver, claimed["entity_id"]), self.run_of(driver, claimed["last_run_id"])
            self.assertEqual((case["workflow_state"], case["claim_epoch"], case.get("claim_id"), case.get("claim_recoveries") or 0),
                             ("OPEN", 2, None, 0))                  # stopped on purpose: not counted as a lost investigation
            self.assertEqual((run["status"], run["end_reason"]), ("ABORTED", claims.END_PAUSED))
            [released] = self.audits(driver, "CLAIM_RELEASED", claimed["entity_id"])
            self.assertEqual(released["actor_id"], "DEMO-OPERATOR-LOCAL")
            self.assertEqual(self.written_for(driver, claimed["last_run_id"]), {"OpsReview": [], "OpsRecommendation": [], "OpsExecution": []})
        self.assertEqual(store.status()["worker"]["processed_count"], 0)
        self.assertEqual(store._claims, {})

    def test_reset_and_skip_see_every_live_claim_and_not_the_old_single_flag(self):
        store, driver = self.make()
        seen = {}

        def refused(call):
            with self.assertRaises(OperationsConflict) as error:
                call()
            return str(error.exception)

        def while_two_run(tools):
            seen["reset"] = refused(lambda: development_reset(store))
            seen["skip"] = refused(lambda: store.skip_to_next_event())
            seen["audit"] = json.loads(public_value(copy.deepcopy(driver.ledger[CONTROL_ID][1]))["reset_audit_json"])[-1]
            seen["cases"] = len(self.kind(driver, "OpsCase"))
        store.agents = Hooked(lambda tools: store.process_one(manual=True, worker_id=WORKERS[1]), while_two_run)
        cases = len(self.kind(driver, "OpsCase"))
        self.assertTrue(store.process_one(manual=True, worker_id=WORKERS[0])["processed"])
        self.assertIn("Pause auto-triage", seen["reset"])
        self.assertIn("investigation is running", seen["skip"])
        self.assertEqual((seen["audit"]["result"], seen["audit"]["reason"]), ("REFUSED", "investigation worker active"))
        self.assertEqual(sorted(seen["audit"]["active_case_ids"]), sorted(c["entity_id"] for c in self.held))
        self.assertEqual(seen["cases"], cases)
        # The flag of the earlier ledger format excludes nothing by itself: with no live claim, a reset goes ahead.
        driver.ledger[CONTROL_ID][1]["worker_claim"] = "DEMO-OPS-CASE-LEFTOVER"
        development_reset(store)
        self.assertEqual(self.kind(driver, "OpsCase"), [])
        self.assertIsNone(public_value(copy.deepcopy(driver.ledger[CONTROL_ID][1])).get("worker_claim"))

    def test_a_reset_after_a_claim_expired_goes_ahead_and_its_worker_then_writes_nothing(self):
        store, driver = self.make()

        def inside(tools):
            self.clock.advance(181)
            development_reset(store)
        store.agents = Hooked(inside)
        result = store.process_one(manual=True, worker_id=WORKERS[0])
        self.assertEqual(result["reason"], "claim_lost")
        self.assertEqual({kind for kind, _ in driver.ledger.values()}, {"OpsControl"})      # the new session is empty


class FailureTests(Base):
    def test_one_worker_failing_leaves_the_other_running_and_automatic_investigation_on(self):
        store, driver = self.make()
        store.control("worker", "start")
        barrier, failing = threading.Barrier(2), self.case(driver, self.queue(driver)[0])["shipment_id"]

        def inside(tools):
            barrier.wait(15)
            if tools.sid == failing:
                raise RuntimeError("secret detail that must not be recorded")
        store.agents = Hooked(always=inside)
        results = self.together(store, {name: (lambda name=name: store.process_one(worker_id=name)) for name in WORKERS})
        failed = [name for name, r in results.items() if isinstance(r, RuntimeError)]
        done = [r for r in results.values() if isinstance(r, dict)]
        self.assertEqual((len(failed), len(done)), (1, 1), results)
        self.assertTrue(done[0]["processed"])                                       # the peer finished its own case
        self.assertEqual(self.run_of(driver, done[0]["run_id"])["status"], "REVIEWED")
        status = store.status()["worker"]
        self.assertEqual((status["state"], status["active_count"], status["processed_count"]), ("running", 0, 1))     # not paused
        lost = next(c for c in self.held if c["worker_id"] == failed[0])
        case, run = self.case(driver, lost["entity_id"]), self.run_of(driver, lost["last_run_id"])
        self.assertEqual((case["workflow_state"], case["claim_recoveries"], case["claim_epoch"], case.get("claim_id")), ("OPEN", 1, 2, None))
        self.assertEqual((run["status"], run["end_reason"]), ("FAILED", claims.END_FAILED))
        [audit] = self.audits(driver, "CLAIM_FAILED")
        self.assertIn("RuntimeError", audit["result"])
        self.assertNotIn("secret detail", json.dumps(self.kind(driver, "OpsAudit"), default=str))    # the type only
        self.assertEqual(self.written_for(driver, lost["last_run_id"]), {"OpsReview": [], "OpsRecommendation": [], "OpsExecution": []})
        self.assertEqual(store._claims, {})

    def test_a_case_lost_twice_goes_to_a_person_with_nothing_invented_for_it(self):
        store, driver = self.make()
        case_id = self.queue(driver)[0]

        def broken(tools):
            raise RuntimeError("the investigator broke")
        store.agents = Hooked(broken, broken)
        for attempt in (1, 2):
            with self.assertRaises(RuntimeError):
                store.process_one(case_id=case_id, worker_id=WORKERS[0])
            case = self.case(driver, case_id)
            self.assertEqual((case["workflow_state"], case["claim_recoveries"]), ("OPEN" if attempt == 1 else "HUMAN_REVIEW", attempt))
        case = self.case(driver, case_id)
        self.assertEqual((case["diagnosis_available"], case["cause_codes"], case.get("recommendation_id"), case.get("claim_id")),
                         (False, [], None, None))
        self.assertEqual(len(self.audits(driver, "CLAIM_RECOVERY_LIMIT", case_id)), 1)
        self.assertEqual([self.kind(driver, kind) for kind in ("OpsReview", "OpsRecommendation", "OpsExecution", "OpsOutcome")], [[], [], [], []])
        self.assertEqual([r["status"] for r in self.kind(driver, "OpsRun")], ["FAILED", "FAILED"])
        self.assertFalse(store.process_one(case_id=case_id)["processed"])           # not queued again automatically
        detail = store.case_detail(case_id)
        self.assertEqual((detail["workflow_state"], detail["diagnosis"]["available"], detail["review"], detail["outcome"]),
                         ("HUMAN_REVIEW", False, None, None))
        # A person can still ask for it to be investigated again; a finished investigation clears the count.
        store.request_reanalysis(case_id, "DEMO-OPERATOR-LOCAL", detail["state_version"], "after-two-losses")
        store.agents = Hooked()
        self.assertTrue(store.process_one(case_id=case_id)["processed"])
        self.assertEqual(self.case(driver, case_id)["claim_recoveries"], 0)

    def test_an_expired_claim_counts_as_a_loss_and_the_second_one_goes_to_a_person(self):
        store, driver = self.make()
        case_id = self.queue(driver)[0]
        store.agents = Hooked(lambda tools: self.clock.advance(181), lambda tools: self.clock.advance(181))
        for expected in ("OPEN", "HUMAN_REVIEW"):
            self.assertEqual(store.process_one(case_id=case_id, worker_id=WORKERS[0])["reason"], "claim_lost")
            self.assertEqual(store.recover_claims(), [case_id])
            self.assertEqual(self.case(driver, case_id)["workflow_state"], expected)
        self.assertEqual(store.recover_claims(), [])
        self.assertEqual([r["end_reason"] for r in self.kind(driver, "OpsRun")], [claims.END_EXPIRED] * 2)
        self.assertEqual(len(self.audits(driver, "CLAIM_RECOVERY_LIMIT", case_id)), 1)


class TerminalEventTests(Base):
    def buffered(self):
        store, driver = self.make()
        store.stage_flush_seconds, store.stage_timer = 0.75, ManualTimer
        return store, driver

    def closing(self, events):
        return [(e["stage"], e["status"]) for e in events if e["stage"] in ("writeback", "escalate")]

    def test_the_last_stage_s_events_are_kept_and_a_finished_run_never_goes_back_to_running(self):
        store, driver = self.buffered()
        store.agents = Hooked()
        case_id = self.queue(driver)[0]
        listener = store.subscribe_pipeline(case_id)
        with approval_policy():
            result = store.process_one(case_id=case_id, worker_id=WORKERS[0])
        self.assertEqual(result["workflow_state"], "AWAITING_APPROVAL")
        run = self.run_of(driver, result["run_id"])
        stored = json.loads(run["result_json"])
        events = stored["pipeline_events"]
        self.assertEqual(self.closing(events), [("writeback", "RUNNING"), ("writeback", "COMPLETED")])     # emitted after the commit, and kept
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual((run["status"], run["end_reason"], run["mode"]), ("REVIEWED", claims.END_FINISHED, "gpt_oss_agents"))
        self.assertIsNone(run.get("active_stage"))
        [decided] = self.audits(driver, "AUTHORITY_DECISION", case_id)       # the committed authority decision is the stored one
        self.assertIn('"rule_id":"' + stored["authority"]["rule_id"] + '"', decided["result"])
        self.assertIn('"risk_class":"' + stored["authority"]["risk_class"] + '"', decided["result"])
        self.assertEqual(stored["result"]["workflow_state"], "AWAITING_APPROVAL")
        self.assertEqual(stored["writeback"]["run_id"], result["run_id"])                   # the completed trace was saved
        self.assertEqual(self.case(driver, case_id)["workflow_state"], "AWAITING_APPROVAL")
        states = []
        while not listener.empty():
            states.append(listener.get_nowait())
        statuses = [s["status"] for s in states]
        self.assertIn("REVIEWED", statuses)
        self.assertEqual(statuses, sorted(statuses, key=lambda s: s == "REVIEWED"))          # once REVIEWED, never RUNNING again
        self.assertEqual(statuses[-1], "REVIEWED")
        self.assertEqual(states[-1]["workflow_state"], "AWAITING_APPROVAL")
        for timer in ManualTimer.made:                                                      # a timer that fires late writes nothing
            timer.function()
        self.assertEqual(self.run_of(driver, result["run_id"]), run)

    def test_a_failure_between_the_commit_the_last_flush_and_the_trace_save_leaves_the_committed_run_final(self):
        for point in ("flush", "trace"):
            with self.subTest(failing=point):
                store, driver = self.buffered()
                store.agents = Hooked()
                store.control("worker", "start")
                record, save = store._record_stages, store._save_run_trace

                def failing_flush(claimed, batch, events):
                    if self.run_of(driver, claimed["last_run_id"]).get("end_reason"):
                        raise ConnectionError("database away")      # after the commit only
                    record(claimed, batch, events)

                def failing_save(case, analysis):
                    raise ConnectionError("database away")
                if point == "flush":
                    store._record_stages = failing_flush
                else:
                    store._save_run_trace = failing_save
                with approval_policy():
                    result = store.process_one(worker_id=WORKERS[0])        # does not raise: the investigation is committed
                self.assertEqual((result["processed"], result["workflow_state"]), (True, "AWAITING_APPROVAL"))
                run = self.run_of(driver, result["run_id"])
                stored = json.loads(run["result_json"])
                self.assertEqual((run["status"], run["end_reason"]), ("REVIEWED", claims.END_FINISHED))
                self.assertEqual(stored["result"]["workflow_state"], "AWAITING_APPROVAL")
                self.assertTrue(stored["authority"]["rule_id"])
                self.assertEqual(self.closing(stored["pipeline_events"]),
                                 [("writeback", "RUNNING")] if point == "flush" else [("writeback", "RUNNING"), ("writeback", "COMPLETED")])
                case = self.case(driver, result["case_id"])
                self.assertEqual((case["workflow_state"], case.get("claim_id"), case["recommendation_id"] is not None), ("AWAITING_APPROVAL", None, True))
                self.assertEqual(len(self.written_for(driver, result["run_id"])["OpsRecommendation"]), 1)
                status = store.status()["worker"]
                self.assertEqual((status["state"], status["active_count"], status["processed_count"]), ("running", 0, 1))
                self.assertEqual(self.audits(driver, "CLAIM_FAILED"), [])
                self.assertEqual(store.case_detail(result["case_id"])["investigation_status"]["run_status"], "REVIEWED")

    def test_a_failure_before_the_commit_still_fails_the_run_and_commits_nothing(self):
        store, driver = self.buffered()
        store.agents = Hooked()
        store.control("worker", "start")
        record, calls = store._record_stages, []

        def failing(claimed, batch, events):
            calls.append(len(batch))
            if len(calls) >= 2:
                raise ConnectionError("database away")
            record(claimed, batch, events)
        store._record_stages = failing
        with approval_policy(), self.assertRaises(ConnectionError):
            store.process_one(worker_id=WORKERS[0])
        [claimed] = self.held
        self.assertEqual(self.written_for(driver, claimed["last_run_id"]), {"OpsReview": [], "OpsRecommendation": [], "OpsExecution": []})
        case = self.case(driver, claimed["entity_id"])
        self.assertEqual((case["workflow_state"], case["claim_recoveries"]), ("OPEN", 1))
        self.assertEqual(self.run_of(driver, claimed["last_run_id"])["end_reason"], claims.END_FAILED)
        self.assertEqual(store.status()["worker"]["state"], "running")

    def test_a_finished_worker_s_late_events_are_refused_once_the_case_has_a_new_run(self):
        store, driver = self.make()
        store.agents = Hooked()
        case_id = self.queue(driver)[0]
        with approval_policy():
            first = store.process_one(case_id=case_id, worker_id=WORKERS[0])
        old, before = self.held[0], self.run_of(driver, first["run_id"])
        events = json.loads(before["result_json"])["pipeline_events"]
        late = {"sequence": len(events) + 1, "stage": "writeback", "status": "COMPLETED", "iteration": 0,
                "recorded_at": self.clock.now.isoformat(), "output": {}}
        store._record_stages(old, [late], [*events, late])           # still its own, current, closed run: appended
        appended = self.run_of(driver, first["run_id"])
        self.assertEqual((appended["status"], len(json.loads(appended["result_json"])["pipeline_events"])), ("REVIEWED", len(events) + 1))
        detail = store.case_detail(case_id)
        store.request_reanalysis(case_id, "DEMO-OPERATOR-LOCAL", detail["state_version"], "again")
        seen = {}

        def while_the_new_run_is_going(tools):
            for name, write in (("events", lambda: store._record_stages(old, [late], [*events, late, late])),
                                ("trace", lambda: store._save_run_trace(old, {"writeback": {"processed": True}}))):
                with self.assertRaises(claims.ClaimLost) as lost:
                    write()
                seen[name] = lost.exception.reason
        store.agents = Hooked(while_the_new_run_is_going)
        with approval_policy():
            second = store.process_one(case_id=case_id, worker_id=WORKERS[1])
        self.assertTrue(second["processed"])
        self.assertEqual(seen, {"events": "superseded", "trace": "run_closed"})
        self.assertEqual(self.run_of(driver, first["run_id"]), appended)     # the earlier run is exactly as it was left
        self.assertEqual(self.run_of(driver, second["run_id"])["status"], "REVIEWED")


class StatusTests(Base):
    def test_case_detail_serves_the_queued_running_and_final_status_of_the_investigation(self):
        store, driver = self.make()
        case_id = self.queue(driver)[0]
        queued = store.case_detail(case_id)["investigation_status"]
        self.assertEqual(set(queued), STATUS_FIELDS)
        self.assertEqual([queued[k] for k in ("run_status", "worker_id", "claim_id", "run_id", "started_at", "lease_expires_at", "final_result", "claim_epoch")],
                         ["QUEUED", None, None, None, None, None, None, 0])
        seen = {}
        store.agents = Hooked(lambda tools: seen.update(running=store.case_detail(case_id)["investigation_status"],
                                                        worker=store.status()["worker"]["active_cases"]))
        with approval_policy():
            result = store.process_one(case_id=case_id, worker_id=WORKERS[0])
        running = seen["running"]
        self.assertEqual(seen["worker"], [running])                              # the same projection in both places
        self.assertEqual((running["run_status"], running["worker_id"], running["claim_epoch"], running["active_stage"]),
                         ("RUNNING", WORKERS[0], 1, "classify"))
        self.assertEqual(instant(running["lease_expires_at"]) - instant(running["started_at"]), timedelta(seconds=180))
        final = store.case_detail(case_id)["investigation_status"]
        self.assertEqual(set(final), STATUS_FIELDS)
        self.assertEqual((final["run_status"], final["workflow_state"], final["active_stage"], final["lease_expires_at"]),
                         ("REVIEWED", "AWAITING_APPROVAL", None, None))
        # The finished projection keeps who ran it, and its cutoff is the run's own, not the case's later one.
        self.assertEqual((final["worker_id"], final["claim_id"], final["claim_epoch"], final["run_id"], final["as_of"], final["started_at"]),
                         (WORKERS[0], running["claim_id"], 1, result["run_id"], running["as_of"], running["started_at"]))
        self.assertEqual(final["final_result"], {"workflow_state": "AWAITING_APPROVAL", "review_verdict": "accept", "model_verdict": "ACCEPT",
                                                 "outcome_verification_status": None})       # reviewed is not verified
        self.assertGreaterEqual(instant(final["updated_at"]), instant(running["updated_at"]))
        text = json.dumps([running, final, store.status()["worker"]], default=str)
        for forbidden in ("result_json", "pipeline_events", "feedback", "summary", "api_key", "password"):
            self.assertNotIn(forbidden, text)
        requeued = store.request_reanalysis(case_id, "DEMO-OPERATOR-LOCAL", store.case_detail(case_id)["state_version"], "again")
        again = store.case_detail(case_id)["investigation_status"]
        self.assertEqual((requeued["workflow_state"], again["run_status"], again["run_id"], again["worker_id"], again["claim_epoch"]),
                         ("OPEN", "QUEUED", None, None, 1))


class WorkerPoolTests(Base):
    def pool(self, store, pace="0"):
        from operations.workers import WorkerPool
        with mock.patch.dict(os.environ, {"SUHAIL_WORKER_PACE_SECONDS": pace}):
            return WorkerPool(store)

    def test_the_pool_has_one_investigation_loop_per_place_and_the_other_workers_as_before(self):
        store, driver = self.make(capacity=2)
        two = self.pool(store)
        self.assertEqual(two.investigators, list(WORKERS))
        self.assertEqual(set(two.workers), {"ingestion", "monitor", "execution", "verification", "investigation", *WORKERS})
        self.assertIs(two.workers["investigation"], two.workers[WORKERS[0]])        # the earlier name still answers
        self.assertIsNot(two.workers[WORKERS[0]], two.workers[WORKERS[1]])
        self.assertEqual(len(two._threads()), 6)
        self.assertEqual({w.name for w in two._threads()},
                         {"suhail-" + name for name in ("ingestion", "monitor", "execution", "verification", *WORKERS)})
        self.assertEqual(set(two.status()), set(two.workers))
        store.capacity = 1
        one = self.pool(store)
        self.assertEqual((one.investigators, len(one._threads())), ([WORKERS[0]], 5))
        self.assertIs(one.workers["investigation"], one.workers[WORKERS[0]])

    def test_each_loop_paces_itself_and_one_loop_s_failure_delays_only_that_loop(self):
        store, driver = self.make(cases=3)
        store.control("worker", "start")
        store.agents = Hooked()
        pool = self.pool(store, pace="600")
        first = pool.investigate(WORKERS[0])
        self.assertTrue(first["processed"])
        self.assertEqual(pool.investigate(WORKERS[0]), {"processed": False})        # its own pause between cases
        self.assertEqual(len(self.held), 1)
        second = pool.investigate(WORKERS[1])                                       # the other loop is not held by it
        self.assertTrue(second["processed"])
        self.assertEqual([c["worker_id"] for c in self.held], list(WORKERS))
        self.assertEqual(pool.investigate(), {"processed": False})                  # no name: the first loop
        # A failing step: only that loop waits before claiming again, longer each time it fails in a row.
        pool = self.pool(store, pace="0")
        store.agents = Hooked(lambda tools: (_ for _ in ()).throw(RuntimeError("broke")))
        with self.assertRaises(RuntimeError):
            pool.investigate(WORKERS[0])
        self.assertEqual(pool._failures, {WORKERS[0]: 1, WORKERS[1]: 0})
        wait = pool._retry_at[WORKERS[0]] - time.monotonic()
        self.assertTrue(0 < wait <= pool.FAILURE_BACKOFF_SECONDS, wait)
        claims_before = len(self.held)
        self.assertEqual(pool.investigate(WORKERS[0]), {"processed": False})        # waiting: it does not even claim
        self.assertEqual(len(self.held), claims_before)
        self.assertEqual(pool._retry_at[WORKERS[1]], 0.0)
        self.assertTrue(pool.investigate(WORKERS[1])["processed"])                  # the other takes the requeued case
        self.assertEqual(store.status()["worker"]["state"], "running")

    def test_the_shared_reader_and_model_client_are_built_before_the_loops_start(self):
        from llm.pipeline import _llm
        store, driver = self.make()
        store.agents, store.reader = Hooked(), None
        pool, order = self.pool(store), []
        with mock.patch.object(_llm, "model", side_effect=lambda: order.append("model")), \
             mock.patch("operations.workers.Worker.start", autospec=True, side_effect=lambda worker: order.append(worker.key)):
            pool.start()
        self.assertEqual(order[0], "model")                                         # before any worker thread starts
        self.assertEqual(sorted(order[1:]), sorted(["ingestion", "monitor", "execution", "verification", *WORKERS]))
        self.assertIsNotNone(store.reader)
        store.agents = None                                                         # rules only: no model client is built
        with mock.patch.object(_llm, "model") as built, mock.patch("operations.workers.Worker.start", autospec=True):
            self.pool(store).start()
        built.assert_not_called()

    def test_stopping_the_pool_claims_nothing_more_and_gives_up_only_its_own_claims(self):
        store, driver = self.make()
        store.control("worker", "start")
        pool, seen = self.pool(store), {}

        def while_both_run(tools):
            seen["released"] = pool.stop()
            seen["after"] = pool.investigate(WORKERS[1])
            seen["live"] = [(a["worker_id"], a["case_id"]) for a in store.status()["worker"]["active_cases"]]
        store.agents = Hooked(lambda tools: seen.update(other=store.process_one(manual=True, worker_id="another-owner")), while_both_run)
        result = pool.investigate(WORKERS[0])
        mine, other = self.held
        self.assertEqual((mine["worker_id"], other["worker_id"]), (WORKERS[0], "another-owner"))
        self.assertEqual(seen["released"], [mine["entity_id"]])
        self.assertEqual(seen["after"], {"processed": False})                       # stopped: no new claim
        self.assertEqual(seen["live"], [("another-owner", other["entity_id"])])     # the other owner's claim was not touched
        self.assertTrue(seen["other"]["processed"])
        self.assertEqual((result["processed"], result["reason"]), (False, "claim_lost"))
        case, run = self.case(driver, mine["entity_id"]), self.run_of(driver, mine["last_run_id"])
        self.assertEqual((case["workflow_state"], case.get("claim_recoveries") or 0, run["status"], run["end_reason"]),
                         ("OPEN", 0, "ABORTED", claims.END_STOPPED))
        self.assertEqual(store._claims, {})
        self.assertTrue(all(worker.stop_event.is_set() for worker in pool._threads()))

    def test_two_loops_of_a_running_pool_investigate_two_cases_at_the_same_time(self):
        store, driver = self.make()
        barrier = threading.Barrier(2)
        together = lambda tools: barrier.wait(20)                                   # passes only if both loops are inside at once
        store.agents = Hooked(together, together)                                   # the first two investigations; any later one runs alone
        store.control("worker", "start")
        pool = self.pool(store).start()
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and store.status()["worker"]["processed_count"] < 2:
                time.sleep(0.05)
            workers = pool.status()
        finally:
            pool.stop()
            for worker in pool._threads():
                worker.join(10)
        self.assertGreaterEqual(store.status()["worker"]["processed_count"], 2)
        self.assertFalse(barrier.broken)
        first_two = store.agents.seen[:2]
        self.assertEqual({s["thread"] for s in first_two}, {"suhail-" + name for name in WORKERS})
        self.assertEqual(len({s["shipment"] for s in first_two}), 2)
        reviewed = [r for r in self.kind(driver, "OpsRun") if r["status"] == "REVIEWED"]
        self.assertLessEqual(set(WORKERS), {r["worker_id"] for r in reviewed})
        self.assertEqual(len({r["case_id"] for r in reviewed}), len(reviewed))
        self.assertTrue(all(workers[name]["last_error"] is None for name in WORKERS))
        self.assertEqual(workers["investigation"], workers[WORKERS[0]])

    def test_an_investigation_s_model_calls_carry_its_claim_and_stop_waiting_when_it_is_revoked(self):
        from operations import provider_gate
        store, driver = self.make()
        seen = {}

        def inside(tools):
            seen["labels"], cancel = provider_gate.current()
            seen["before"] = cancel.is_set()
            store.control("worker", "pause")
            seen["after"] = cancel.is_set()
        store.agents = Hooked(inside)
        result = store.process_one(manual=True, worker_id=WORKERS[0])
        [claimed] = self.held
        self.assertEqual(seen["labels"], {"case_id": claimed["entity_id"], "run_id": claimed["last_run_id"], "worker_id": WORKERS[0]})
        self.assertEqual((seen["before"], seen["after"], result["reason"]), (False, True, "claim_lost"))
        self.assertEqual(provider_gate.current(), ({}, None))


def run_mock_batch(test, workers, cases=4, latency=0.5):
    """The same fixed batch through the real store with `workers` investigation loops. The investigator is the scripted
    double; it takes `latency` seconds where its model calls would be. Returns what was measured: cases completed, errors,
    the most investigations in progress at once, and wall time. Mock only: it shows that the loops overlap and that the
    capacity holds, not how long a model takes or how well it diagnoses."""
    store, driver = test.make(cases=cases, capacity=workers)
    store.control("worker", "start")
    inside, peak, lock, errors = [0], [0], threading.Lock(), []

    def model_time(tools):
        with lock:
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
        time.sleep(latency)
        with lock:
            inside[0] -= 1
    store.agents = Hooked(always=model_time)
    queued = len(test.kind(driver, "OpsCase"))

    def loop(name):
        while True:
            try:
                result = store.process_one(worker_id=name)
            except Exception as error:
                errors.append(type(error).__name__)
                return
            if not result.get("processed") and result.get("reason") == "none_eligible":
                return
    threads = [threading.Thread(target=loop, args=(name,), name=name) for name in WORKERS[:workers]]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    return {"workers": workers, "queued": queued, "completed": store.status()["worker"]["processed_count"], "errors": errors,
            "peak_investigations": peak[0], "wall_seconds": round(time.monotonic() - started, 3), "latency_seconds": latency,
            "runs_by_worker": {name: sum(r["worker_id"] == name for r in test.kind(driver, "OpsRun")) for name in WORKERS[:workers]},
            "mock_only": True}


class BatchHarnessTests(Base):
    def test_a_fixed_mock_batch_overlaps_with_two_workers_and_never_with_one(self):
        one, two = run_mock_batch(self, 1), run_mock_batch(self, 2)
        print("\nMOCK BATCH (not a model measurement)", json.dumps([one, two]))
        self.assertEqual((one["errors"], two["errors"]), ([], []))
        self.assertGreaterEqual(one["queued"], 4)
        self.assertEqual((one["completed"], two["completed"]), (one["queued"], one["queued"]))     # the same batch, all of it
        self.assertEqual((one["peak_investigations"], two["peak_investigations"]), (1, 2))
        self.assertTrue(all(count > 0 for count in two["runs_by_worker"].values()), two)            # both loops took cases
        self.assertLess(two["wall_seconds"], one["wall_seconds"])


class ExecutionTests(Base):
    def approved(self, adapter):
        store, driver = self.make()
        store.agents, store.adapter = Hooked(), adapter
        with approval_policy():
            result = store.process_one(manual=True, worker_id=WORKERS[0])
        self.assertEqual(result["workflow_state"], "AWAITING_APPROVAL")
        version = store.case_detail(result["case_id"])["state_version"]
        approval = store.decide(result["case_id"], "approve", "DEMO-OPERATOR-LOCAL", version, "approve-once")
        return store, driver, result, version, approval

    def test_repeated_approval_dispatch_and_a_restart_cause_one_effect(self):
        adapter = CountingAdapter(die_after={1})
        store, driver, result, version, approval = self.approved(adapter)
        replay = store.decide(result["case_id"], "approve", "DEMO-OPERATOR-LOCAL", version, "approve-once")
        self.assertEqual((replay["idempotent"], replay["execution_id"]), (True, approval["execution_id"]))
        with self.assertRaises(OperationsConflict):                                         # a second approval is not a second action
            store.decide(result["case_id"], "approve", "DEMO-OPERATOR-LOCAL", store.case_detail(result["case_id"])["state_version"], "approve-twice")
        self.assertEqual(len(self.kind(driver, "OpsExecution")), 1)
        with self.assertRaises(ProcessDied):                # the field acted, then the process ended before the receipt
            store.execute_step()
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["status"], len(adapter.effects)), ("EXECUTING", 1))
        restarted = OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world))
        restarted.wall, restarted.adapter = self.clock, adapter
        restarted.initialize()                              # the restart: the unacknowledged execution is dispatched again
        self.assertEqual(self.kind(driver, "OpsExecution")[0]["status"], "AUTHORIZED")
        self.assertEqual(restarted.execute_step(), [approval["execution_id"]])
        self.assertEqual((restarted.execute_step(), store.execute_step()), ([], []))
        [execution] = self.kind(driver, "OpsExecution")
        self.assertEqual((execution["status"], execution["entity_id"], execution["idempotency_key"], execution["run_id"], execution["recommendation_id"]),
                         ("ACKNOWLEDGED", approval["execution_id"], approval["execution_id"], result["run_id"],
                          self.written_for(driver, result["run_id"])["OpsRecommendation"][0]))
        self.assertEqual((adapter.calls, list(adapter.effects)), (2, [approval["execution_id"]]))       # asked twice, acted once
        self.assertEqual(len(self.audits(driver, "EXECUTION_RECOVERED")), 1)
        self.assertEqual(len(self.audits(driver, "ACTION_EXECUTED")), 1)
        # A receipt is not an outcome: the case waits for independent verification, and nothing was declared.
        self.assertEqual(self.case(driver, result["case_id"])["workflow_state"], "AWAITING_OUTCOME")
        restarted.outcome_step(limit=10)
        self.assertNotEqual(self.case(driver, result["case_id"])["workflow_state"], "RESOLVED")
        self.assertFalse(any(o.get("verification_status") == "VERIFIED" and o.get("success") for o in self.kind(driver, "OpsOutcome")))

    def test_two_dispatchers_at_once_send_an_authorized_action_once(self):
        adapter = CountingAdapter()
        store, driver, result, version, approval = self.approved(adapter)
        start = threading.Barrier(2)

        def dispatch():
            start.wait(15)
            return store.execute_step()
        results = self.together(store, {"dispatch-1": dispatch, "dispatch-2": dispatch})
        self.assertEqual(sorted(results.values(), key=len), [[], [approval["execution_id"]]])
        self.assertEqual((adapter.calls, len(adapter.effects)), (1, 1))
        self.assertEqual([e["status"] for e in self.kind(driver, "OpsExecution")], ["ACKNOWLEDGED"])


if __name__ == "__main__":
    unittest.main()
