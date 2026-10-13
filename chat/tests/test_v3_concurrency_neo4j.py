"""V3: claims raced by separate Neo4j clients against the real database. Opt-in, and one database only.

tests.test_v3_concurrency shows the claim rules on an in-memory ledger that lets one writer in at a time. That is an
assumption about the database, not evidence. These tests replace the assumption: each client is its own Neo4j driver
(its own connections and transactions) with its own store, and they race for the same records in a real database.

Target: ONLY `shipments-v2-world-v3-ci-20261013`, provisioned by the integrator with a COMPLETE synthetic V2 import.
The tests never create, replace or drop a database, never touch V2 evidence, and write only this database's operations
ledger (which they reset, with the development reset, as the other integration tests do).

To run (after provisioning, with the server's settings in the environment or the worktree's .env):

    SUHAIL_V3_RACE_TESTS=1  SUHAIL_V3_CI_DATABASE=shipments-v2-world-v3-ci-20261013

Without SUHAIL_V3_RACE_TESTS=1 the race tests are SKIPPED, and a skip is an outstanding gate, not a pass. With it, the
tests FAIL (they do not skip, and do not fall back to any other database) unless the named database is exactly the
target, is not one of the configured protected databases, exists on the server, and holds a COMPLETE synthetic import.
GuardTests checks those refusals and needs no database.

No model: investigations here run on rules only, or with the scripted investigator of the unit tests.
"""
import json
import os
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

TARGET = "shipments-v2-world-v3-ci-20261013"
OPT_IN_ENV = "SUHAIL_V3_RACE_TESTS"
DATABASE_ENV = "SUHAIL_V3_CI_DATABASE"
WORKERS = ("investigation-1", "investigation-2")
ROUNDS = 8


def refusal(named, protected, on_server=None, marker=None):
    """Why the race tests must not run against `named`, or None. named: SUHAIL_V3_CI_DATABASE. protected: the
    databases configured for anything else. on_server: {name: status} from the server, when it was asked.
    marker: the target's import marker row, when it was read."""
    if not named:
        return f"{DATABASE_ENV} is not set; these tests name their database explicitly and have no default"
    if named != TARGET:
        return f"{DATABASE_ENV} names {named!r}; only {TARGET!r} may be used, and no other database is ever a fallback"
    if TARGET.lower() in {str(name).lower() for name in protected if name}:
        return f"{TARGET!r} is configured as a database of the application; refusing to use it for race tests"
    if on_server is not None:
        if TARGET not in on_server:
            return f"{TARGET!r} does not exist on the server: it has not been provisioned (the tests never create it)"
        if str(on_server[TARGET]).lower() != "online":
            return f"{TARGET!r} is {on_server[TARGET]!r}, not online"
    if marker is not None:
        if marker.get("state") != "COMPLETE":
            return f"{TARGET!r} does not hold a COMPLETE import"
        try:
            manifest = json.loads(marker.get("manifest") or "{}")
        except ValueError:
            return f"{TARGET!r} has an unreadable import manifest"
        if manifest.get("synthetic") is not True or not str(manifest.get("dataset_id", "")).startswith("DEMO-"):
            return f"{TARGET!r} does not hold a synthetic DEMO dataset"
    return None


class GuardTests(unittest.TestCase):
    """The refusals, checked without any database."""

    def test_only_the_named_target_is_accepted_and_nothing_else_is_a_fallback(self):
        self.assertIsNone(refusal(TARGET, ("neo4j", "shipments", "neo4j")))
        self.assertIn("not set", refusal("", ()))
        self.assertIn("not set", refusal(None, ()))
        for other in ("shipments-v2-demo-ci-test", "shipments-v2-demo-test", "shipments-v2-demo", "shipments-v2-world-v3-20261013",
                      "shipments-v2-world-v3-ci-20261013-2", TARGET.upper(), "neo4j", "shipments"):
            self.assertIn("only", refusal(other, ()), other)
        self.assertIn("configured", refusal(TARGET, ("neo4j", TARGET)))
        self.assertIn("configured", refusal(TARGET, (TARGET.upper(),)))

    def test_a_missing_offline_or_incomplete_target_is_refused(self):
        ok = {"state": "COMPLETE", "manifest": json.dumps({"synthetic": True, "dataset_id": "DEMO-SUHAIL-WORLD-V3-20261013"})}
        self.assertIsNone(refusal(TARGET, (), {TARGET: "online", "neo4j": "online"}, ok))
        self.assertIn("not been provisioned", refusal(TARGET, (), {"neo4j": "online", "shipments-v2-demo-ci-test": "online"}))
        self.assertIn("not online", refusal(TARGET, (), {TARGET: "offline"}))
        self.assertIn("COMPLETE", refusal(TARGET, (), {TARGET: "online"}, {"state": "LOADING", "manifest": ok["manifest"]}))
        self.assertIn("synthetic", refusal(TARGET, (), {TARGET: "online"}, {"state": "COMPLETE", "manifest": json.dumps({"synthetic": False, "dataset_id": "DEMO-X"})}))
        self.assertIn("synthetic", refusal(TARGET, (), {TARGET: "online"}, {"state": "COMPLETE", "manifest": json.dumps({"synthetic": True, "dataset_id": "REAL-X"})}))
        self.assertIn("unreadable", refusal(TARGET, (), {TARGET: "online"}, {"state": "COMPLETE", "manifest": "{"}))

    def test_the_target_is_a_world_database_the_operations_layer_already_allows(self):
        from operations.datasets import OPERATIONS_DATABASES, SCRATCH_DATABASES, is_world_database, operations_database_allowed
        self.assertTrue(is_world_database(TARGET) and operations_database_allowed(TARGET))
        self.assertNotIn(TARGET, (*OPERATIONS_DATABASES, *SCRATCH_DATABASES))     # not one of the V2 databases


class WallClock:
    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class Client:
    """One Neo4j client: its own driver, reader and store. Nothing in process is shared between two of them."""

    def __init__(self, manifest, capacity=2, wall=None):
        import config
        from neo4j import GraphDatabase
        from operations.datasets import dataset_config
        from operations.read_model import OperationsReader
        from operations.store import OperationsStore
        self.driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD))
        cfg = dataset_config(manifest["config"])
        self.reader = OperationsReader(self.driver, TARGET, cfg.dataset_id, cfg, lambda: self.store.status()["as_of"])
        self.store = OperationsStore(self.driver, TARGET, cfg.dataset_id, cfg, reader=self.reader, uri=config.NEO4J_URI,
                                     protected=(config.NEO4J_DATABASE, config.SHIPMENT_DATABASE, config.CHAT_DATABASE))
        self.reader.store = self.store
        self.store.capacity, self.store.claim_heartbeats = capacity, False
        if wall is not None:
            self.store.wall = wall

    def hold_first_read(self, entered, release, barrier=None):
        """Make this client's next investigation stop where a model call would be, until released."""
        evidence, state = self.reader.evidence, {"held": False}

        def held(shipment_id, as_of=None):
            if not state["held"]:
                state["held"] = True
                if barrier is not None:
                    barrier.wait(30)
                entered.set()
                release.wait(60)
            return evidence(shipment_id, as_of)
        self.reader.evidence = held

    def close(self):
        self.driver.close()


@unittest.skipUnless(os.environ.get(OPT_IN_ENV) == "1",
                     f"OUTSTANDING GATE, not a pass: set {OPT_IN_ENV}=1 and {DATABASE_ENV}={TARGET} once the integrator has provisioned it")
class RaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config
        from neo4j import GraphDatabase
        protected = (config.NEO4J_DATABASE, config.SHIPMENT_DATABASE, config.CHAT_DATABASE)
        named = os.environ.get(DATABASE_ENV)
        reason = refusal(named, protected)
        if reason:
            raise AssertionError("V3 race tests refused: " + reason)
        probe = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD))
        try:
            with probe.session(database="system", default_access_mode="READ") as session:
                on_server = {row["name"]: row["currentStatus"] for row in session.run("SHOW DATABASES YIELD name, currentStatus")}
            reason = refusal(named, protected, on_server)
            if reason:
                raise AssertionError("V3 race tests refused: " + reason)
            with probe.session(database=TARGET, default_access_mode="READ") as session:
                rows = list(session.run("MATCH (m:_V2Import) RETURN m.state AS state, m.manifest_json AS manifest"))
            marker = dict(rows[0]) if len(rows) == 1 else {"state": None}
            reason = refusal(named, protected, on_server, marker)
            if reason:
                raise AssertionError("V3 race tests refused: " + reason)
        finally:
            probe.close()
        cls.manifest = json.loads(marker["manifest"])
        cls.clients = []

    @classmethod
    def tearDownClass(cls):
        for client in getattr(cls, "clients", []):
            client.close()

    def client(self, **options):
        client = Client(self.manifest, **options)
        type(self).clients.append(client)
        return client

    def fresh(self, cases, **options):
        """A reset operations ledger, the clock moved until enough shipments are visible, `cases` cases opened the way
        the monitor opens them, and two (or more) separate clients on it."""
        from tests.test_operations_store import development_reset
        first = self.client(**options)
        first.store.initialize()
        development_reset(first.store)
        visible = []
        for _ in range(60):
            first.store.tick(seconds=86400, manual=True, speed=1)
            clock = first.store.status()["as_of"]
            with first.driver.session(database=TARGET, default_access_mode="READ") as session:
                shipments = [row["id"] for row in session.run(
                    "MATCH (s:V2Entity:Shipment {dataset_id:$dataset,split:'development',synthetic:true}) RETURN s.entity_id AS id ORDER BY id LIMIT 400",
                    dataset=first.store.dataset_id)]
            visible = []
            for shipment_id in shipments:
                try:
                    first.reader.evidence(shipment_id, clock)
                except LookupError:
                    continue
                visible.append(shipment_id)
                if len(visible) >= cases:
                    break
            if len(visible) >= cases:
                break
        self.assertGreaterEqual(len(visible), cases, "the provisioned dataset shows too few development shipments to race over")

        def open_cases(tx):
            control = first.store._control(tx, lock=True)
            return [first.store._open_monitored_case(tx, shipment_id, ["MILESTONE_OVERDUE"], control["as_of"], control.get("session_id"), 900 + index)
                    for index, shipment_id in enumerate(visible)]
        opened = first.store._execute(open_cases, write=True)
        return first, opened, options

    def rows(self, client, kind, **where):
        from operations.schema import public_value
        with client.driver.session(database=TARGET, default_access_mode="READ") as session:
            found = [public_value(dict(row["p"])) for row in session.run(f"MATCH (n:OpsEntity:{kind}) RETURN properties(n) AS p")]
        return [row for row in found if all(row.get(key) == value for key, value in where.items())]

    def race(self, calls):
        """Start every call at the same moment, each on its own thread; returns {name: result or exception}."""
        start, results = threading.Barrier(len(calls)), {}

        def work(name, call):
            try:
                start.wait(30)
                results[name] = call()
            except Exception as error:
                results[name] = error
        threads = [threading.Thread(target=work, args=item, name=item[0]) for item in calls.items()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(180)
        self.assertFalse([t.name for t in threads if t.is_alive()], "a client never returned")
        return results

    def test_two_clients_racing_for_one_case_grant_it_exactly_once(self):
        first, opened, options = self.fresh(ROUNDS)
        second = self.client(**options)
        for case_id in opened:
            results = self.race({WORKERS[0]: lambda: first.store.process_one(case_id=case_id, worker_id=WORKERS[0]),
                                 WORKERS[1]: lambda: second.store.process_one(case_id=case_id, worker_id=WORKERS[1])})
            self.assertTrue(all(isinstance(r, dict) for r in results.values()), results)
            won = [name for name, r in results.items() if r.get("processed") or r.get("reason") == "snapshot_changed"]
            self.assertEqual(len(won), 1, results)                                  # one owner, never two and never none
            self.assertEqual(len(self.rows(first, "OpsAudit", case_id=case_id, event_type="CASE_CLAIMED")), 1)
            [run] = self.rows(first, "OpsRun", case_id=case_id)
            self.assertEqual((run["worker_id"], run["claim_epoch"]), (won[0], 1))
        self.assertEqual(first.store.status()["worker"]["active_count"], 0)

    def test_two_clients_claim_two_different_cases_and_investigate_them_together(self):
        first, opened, options = self.fresh(2)
        second = self.client(**options)
        first.store.control("worker", "start")
        both, release, entered = threading.Barrier(2), threading.Event(), [threading.Event(), threading.Event()]
        first.hold_first_read(entered[0], release, both)
        second.hold_first_read(entered[1], release, both)
        results = {}
        threads = [threading.Thread(target=lambda c=c, name=name: results.update({name: c.store.process_one(worker_id=name)}))
                   for c, name in ((first, WORKERS[0]), (second, WORKERS[1]))]
        for thread in threads:
            thread.start()
        self.assertTrue(entered[0].wait(60) and entered[1].wait(60), "the two investigations were never in progress together")
        observer = self.client(**options)
        worker = observer.store.status()["worker"]                                  # a third client sees both claims
        release.set()
        for thread in threads:
            thread.join(180)
        self.assertEqual((worker["active_count"], worker["active_case_id"]), (2, None))
        self.assertEqual({a["worker_id"] for a in worker["active_cases"]}, set(WORKERS))
        self.assertEqual({a["case_id"] for a in worker["active_cases"]}, set(opened))
        self.assertEqual({r.get("case_id") for r in results.values()}, set(opened), results)
        runs = self.rows(first, "OpsRun")
        self.assertEqual({r["worker_id"] for r in runs}, set(WORKERS))
        self.assertEqual(len({r["case_id"] for r in runs}), 2)
        self.assertEqual(observer.store.status()["worker"]["active_count"], 0)

    def test_with_capacity_one_two_racing_clients_never_both_hold_a_case(self):
        first, opened, options = self.fresh(ROUNDS, capacity=1)
        second = self.client(**options)
        inside, peak, lock = [0], [0], threading.Lock()

        def counted(client):
            evidence = client.reader.evidence

            def read(shipment_id, as_of=None):
                with lock:
                    inside[0] += 1
                    peak[0] = max(peak[0], inside[0])
                time.sleep(0.2)                                 # a wide window for a second owner to appear in, if one could
                try:
                    return evidence(shipment_id, as_of)
                finally:
                    with lock:
                        inside[0] -= 1
            client.reader.evidence = read
        counted(first)
        counted(second)
        refused = 0
        for _ in range(ROUNDS // 2):
            results = self.race({WORKERS[0]: lambda: first.store.process_one(manual=True, worker_id=WORKERS[0]),
                                 WORKERS[1]: lambda: second.store.process_one(manual=True, worker_id=WORKERS[1])})
            self.assertTrue(all(isinstance(r, dict) for r in results.values()), results)
            refused += sum(r.get("reason") == "capacity" for r in results.values())
        self.assertEqual(peak[0], 1)                            # never two investigations at once
        self.assertGreater(refused, 0)                          # and the races were real: someone was turned away for capacity
        cases = {r["case_id"] for r in self.rows(first, "OpsRun")}
        self.assertEqual(len(cases), len(self.rows(first, "OpsRun")))       # no case was run by two owners

    def test_an_expired_claim_is_recovered_once_and_taken_once_and_its_old_owner_is_refused(self):
        from operations import claims
        clock = WallClock()
        first, opened, options = self.fresh(1, wall=clock)
        second, third = self.client(**options), self.client(**options)
        [case_id] = opened
        entered, release, held = threading.Event(), threading.Event(), {}
        first.hold_first_read(entered, release)
        hold = first.store._hold
        first.store._hold = lambda claimed: (held.update(claimed=claimed), hold(claimed))[1]
        stalled = {}
        thread = threading.Thread(target=lambda: stalled.update(result=first.store.process_one(case_id=case_id, worker_id=WORKERS[0])))
        thread.start()
        self.assertTrue(entered.wait(60))
        clock.advance(181)                                      # the lease runs out while its owner is stalled
        with self.assertRaises(claims.ClaimLost):
            first.store.renew_claim(held["claimed"])
        results = self.race({"second": lambda: second.store.process_one(case_id=case_id, worker_id="investigation-2"),
                             "third": lambda: third.store.process_one(case_id=case_id, worker_id="investigation-3")})
        self.assertTrue(all(isinstance(r, dict) for r in results.values()), results)
        self.assertEqual(sum(bool(r.get("processed") or r.get("reason") == "snapshot_changed") for r in results.values()), 1, results)
        self.assertEqual(len(self.rows(first, "OpsAudit", case_id=case_id, event_type="CLAIM_EXPIRED")), 1)       # recovered once
        self.assertEqual(len(self.rows(first, "OpsAudit", case_id=case_id, event_type="CASE_CLAIMED")), 2)
        release.set()
        thread.join(180)
        self.assertEqual((stalled["result"]["processed"], stalled["result"]["reason"]), (False, "claim_lost"))
        runs = {r["entity_id"]: r for r in self.rows(first, "OpsRun", case_id=case_id)}
        old = runs.pop(held["claimed"]["last_run_id"])
        [new] = runs.values()
        self.assertEqual((old["status"], old["end_reason"], old["claim_epoch"]), ("ABORTED", claims.END_EXPIRED, 1))
        self.assertEqual((new["end_reason"], new["claim_epoch"]), (claims.END_FINISHED, 3))
        for kind in ("OpsReview", "OpsRecommendation", "OpsExecution"):
            self.assertEqual(self.rows(first, kind, run_id=old["entity_id"]), [], kind)      # nothing from the stale run
        self.assertEqual(set(json.loads(old["result_json"])), {"pipeline_events"})


if __name__ == "__main__":
    unittest.main()
