"""V3.4: claims raced by three and four separate Neo4j clients against the real database. Opt-in, one database only.

The same gate, target, fixture and refusals as tests.test_v3_concurrency_neo4j (prepare_target refuses every other
database; without SUHAIL_V3_RACE_TESTS=1 every test is SKIPPED, and a skip is an outstanding gate, not a pass). Each
client is its own driver and store; nothing in process is shared between them. No model: investigations run on rules.

What is shown, with up to four investigation workers:
  - four clients claim four different cases and are inside their investigations at the same moment;
  - four clients racing for one case grant it exactly once, round after round;
  - with three places, four racing clients never hold more than three cases, and someone is turned away for capacity;
  - an expired claim is recovered once and taken once by one of three competitors; its stalled owner's late result is
    refused and nothing of the stale run is written;
  - a pause cancels four running investigations at once: every one loses its claim, writes nothing more, and its case is
    queued again and then taken once;
  - cases a round has finished (waiting for evidence, with a person, or otherwise out of the queue) are never claimed
    again by the next round, which takes only the next eligible cases.
"""
import json
import os
import threading
import time
import unittest

from tests import test_v3_concurrency_neo4j as base
from tests.test_v3_concurrency_neo4j import DATABASE_ENV, OPT_IN_ENV, TARGET, WallClock

WORKERS = tuple(f"investigation-{n}" for n in range(1, 5))
ROUNDS = 6
CLAIMABLE = ("OPEN", "REOPENED")


@unittest.skipUnless(os.environ.get(OPT_IN_ENV) == "1",
                     f"OUTSTANDING GATE, not a pass: set {OPT_IN_ENV}=1 and {DATABASE_ENV}={TARGET} once the integrator has provisioned it")
class FourClientRaceTests(unittest.TestCase):
    # The two-client harness's own fixture, client, ledger and race helpers (not its tests, which run in their module).
    setUpClass = base.RaceTests.__dict__["setUpClass"]
    tearDownClass = base.RaceTests.__dict__["tearDownClass"]
    client, fresh, rows, race = base.RaceTests.client, base.RaceTests.fresh, base.RaceTests.rows, base.RaceTests.race

    def clients(self, count, **options):
        first, opened, options = self.fresh(options.pop("cases"), **options)
        return [first, *[self.client(**options) for _ in range(count - 1)]], opened, options

    def test_four_clients_claim_four_different_cases_and_investigate_them_together(self):
        clients, opened, options = self.clients(4, cases=4, capacity=4)
        clients[0].store.control("worker", "start")
        together, release = threading.Barrier(4), threading.Event()
        entered = [threading.Event() for _ in clients]
        for client, event in zip(clients, entered):
            client.hold_first_read(event, release, together)
        results = {}
        threads = [threading.Thread(target=lambda c=c, name=name: results.update({name: c.store.process_one(worker_id=name)}))
                   for c, name in zip(clients, WORKERS)]
        for thread in threads:
            thread.start()
        self.assertTrue(all(event.wait(60) for event in entered), "the four investigations were never in progress together")
        observer = self.client(**options)
        worker = observer.store.status()["worker"]                                 # a fifth client sees all four claims
        release.set()
        for thread in threads:
            thread.join(180)
        self.assertEqual((worker["concurrency"], worker["active_count"], worker["active_case_id"]), (4, 4, None))
        self.assertEqual({a["worker_id"] for a in worker["active_cases"]}, set(WORKERS))
        self.assertEqual({a["case_id"] for a in worker["active_cases"]}, set(opened))
        self.assertEqual({r.get("case_id") for r in results.values()}, set(opened), results)
        runs = self.rows(clients[0], "OpsRun")
        self.assertEqual(sorted(r["worker_id"] for r in runs), sorted(WORKERS))
        self.assertEqual(len({r["case_id"] for r in runs}), 4)
        self.assertEqual(observer.store.status()["worker"]["active_count"], 0)

    def test_four_clients_racing_for_one_case_grant_it_exactly_once(self):
        clients, opened, options = self.clients(4, cases=ROUNDS, capacity=4)
        for case_id in opened:
            results = self.race({name: (lambda c=c, name=name: c.store.process_one(case_id=case_id, worker_id=name))
                                 for c, name in zip(clients, WORKERS)})
            self.assertTrue(all(isinstance(r, dict) for r in results.values()), results)
            won = [name for name, r in results.items() if r.get("processed") or r.get("reason") == "snapshot_changed"]
            self.assertEqual(len(won), 1, results)                                 # one owner, never two and never none
            self.assertEqual(sorted(r.get("reason") for name, r in results.items() if name not in won), ["none_eligible"] * 3)
            self.assertEqual(len(self.rows(clients[0], "OpsAudit", case_id=case_id, event_type="CASE_CLAIMED")), 1)
            [run] = self.rows(clients[0], "OpsRun", case_id=case_id)
            self.assertEqual((run["worker_id"], run["claim_epoch"]), (won[0], 1))
        self.assertEqual(clients[0].store.status()["worker"]["active_count"], 0)

    def test_with_three_places_four_racing_clients_never_hold_more_than_three(self):
        clients, opened, options = self.clients(4, cases=ROUNDS * 2, capacity=3)
        inside, peak, lock = [0], [0], threading.Lock()

        def counted(client):
            evidence = client.reader.evidence

            def read(shipment_id, as_of=None):
                with lock:
                    inside[0] += 1
                    peak[0] = max(peak[0], inside[0])
                time.sleep(0.3)                                 # a wide window for a fourth owner to appear in, if one could
                try:
                    return evidence(shipment_id, as_of)
                finally:
                    with lock:
                        inside[0] -= 1
            client.reader.evidence = read
        for client in clients:
            counted(client)
        refused = 0
        for _ in range(ROUNDS // 2):
            results = self.race({name: (lambda c=c, name=name: c.store.process_one(manual=True, worker_id=name))
                                 for c, name in zip(clients, WORKERS)})
            self.assertTrue(all(isinstance(r, dict) for r in results.values()), results)
            refused += sum(r.get("reason") == "capacity" for r in results.values())
        self.assertLessEqual(peak[0], 3)                        # never four investigations at once
        self.assertGreater(refused, 0)                          # and the races were real: someone was turned away for capacity
        runs = self.rows(clients[0], "OpsRun")
        self.assertEqual(len({r["case_id"] for r in runs}), len(runs))      # no case was run by two owners

    def test_an_expired_claim_is_taken_once_by_one_of_three_competitors_and_its_stalled_owner_is_refused(self):
        from operations import claims
        clock = WallClock()
        first, opened, options = self.fresh(1, wall=clock, capacity=4)
        competitors = [self.client(**options) for _ in range(3)]
        [case_id] = opened
        entered, release, held = threading.Event(), threading.Event(), {}
        first.hold_first_read(entered, release)
        hold = first.store._hold
        first.store._hold = lambda claimed: (held.update(claimed=claimed), hold(claimed))[1]
        stalled = {}
        thread = threading.Thread(target=lambda: stalled.update(result=first.store.process_one(case_id=case_id, worker_id=WORKERS[0])))
        thread.start()
        self.assertTrue(entered.wait(60))
        clock.advance(181)                                      # the lease runs out while its owner is stalled (a late model)
        with self.assertRaises(claims.ClaimLost):
            first.store.renew_claim(held["claimed"])
        results = self.race({name: (lambda c=c, name=name: c.store.process_one(case_id=case_id, worker_id=name))
                             for c, name in zip(competitors, WORKERS[1:])})
        self.assertTrue(all(isinstance(r, dict) for r in results.values()), results)
        self.assertEqual(sum(bool(r.get("processed") or r.get("reason") == "snapshot_changed") for r in results.values()), 1, results)
        self.assertEqual(len(self.rows(first, "OpsAudit", case_id=case_id, event_type="CLAIM_EXPIRED")), 1)       # recovered once
        self.assertEqual(len(self.rows(first, "OpsAudit", case_id=case_id, event_type="CASE_CLAIMED")), 2)
        release.set()                                           # the stalled owner's late result arrives now
        thread.join(180)
        self.assertEqual((stalled["result"]["processed"], stalled["result"]["reason"]), (False, "claim_lost"))
        runs = {r["entity_id"]: r for r in self.rows(first, "OpsRun", case_id=case_id)}
        old = runs.pop(held["claimed"]["last_run_id"])
        [new] = runs.values()
        self.assertEqual((old["status"], old["end_reason"], old["claim_epoch"]), ("ABORTED", claims.END_EXPIRED, 1))
        self.assertEqual((new["end_reason"], new["claim_epoch"]), (claims.END_FINISHED, 3))
        for kind in ("OpsReview", "OpsRecommendation", "OpsExecution"):
            self.assertEqual(self.rows(first, kind, run_id=old["entity_id"]), [], kind)     # nothing from the stale run
        self.assertEqual(set(json.loads(old["result_json"])), {"pipeline_events"})

    def test_a_pause_cancels_four_running_investigations_and_each_case_is_then_taken_once(self):
        from operations import claims
        clients, opened, options = self.clients(4, cases=4, capacity=4)
        clients[0].store.control("worker", "start")
        together, release = threading.Barrier(4), threading.Event()
        entered = [threading.Event() for _ in clients]
        for client, event in zip(clients, entered):
            client.hold_first_read(event, release, together)
        results = {}
        threads = [threading.Thread(target=lambda c=c, name=name: results.update({name: c.store.process_one(worker_id=name)}))
                   for c, name in zip(clients, WORKERS)]
        for thread in threads:
            thread.start()
        self.assertTrue(all(event.wait(60) for event in entered))
        operator = self.client(**options)
        operator.store.control("worker", "pause")              # a deliberate stop from another client: every claim is revoked
        release.set()
        for thread in threads:
            thread.join(180)
        self.assertEqual([results[name]["reason"] for name in WORKERS], ["claim_lost"] * 4, results)
        aborted = self.rows(operator, "OpsRun")
        self.assertEqual(len(aborted), 4)
        self.assertEqual({(r["status"], r["end_reason"]) for r in aborted}, {("ABORTED", claims.END_PAUSED)})
        for run in aborted:
            for kind in ("OpsReview", "OpsRecommendation", "OpsExecution"):
                self.assertEqual(self.rows(operator, kind, run_id=run["entity_id"]), [], kind)
        states = {c["entity_id"]: c["workflow_state"] for c in self.rows(operator, "OpsCase") if c["entity_id"] in opened}
        self.assertTrue(all(state in CLAIMABLE for state in states.values()), states)       # queued again, not lost
        operator.store.control("worker", "start")
        again = self.race({name: (lambda c=c, name=name: c.store.process_one(worker_id=name)) for c, name in zip(clients, WORKERS)})
        self.assertEqual(sorted(r.get("case_id") for r in again.values()), sorted(opened), again)
        finished = [r for r in self.rows(operator, "OpsRun") if r["end_reason"] == claims.END_FINISHED]
        self.assertEqual((len(finished), len({r["case_id"] for r in finished})), (4, 4))
        self.assertEqual({r["claim_epoch"] for r in finished}, {3})                         # grant, revoke, grant

    def test_a_round_s_finished_cases_are_never_claimed_again_and_the_next_round_takes_the_next_cases(self):
        clients, opened, options = self.clients(4, cases=8, capacity=4)
        oldest = sorted(self.rows(clients[0], "OpsCase"), key=lambda c: (str(c["opened_at"]), c["entity_id"]))
        first_round = self.race({name: (lambda c=c, name=name: c.store.process_one(manual=True, worker_id=name))
                                 for c, name in zip(clients, WORKERS)})
        taken = {r["case_id"] for r in first_round.values() if isinstance(r, dict) and r.get("case_id")}
        self.assertEqual(len(taken), 4, first_round)
        self.assertEqual(taken, {c["entity_id"] for c in oldest[:4]})                       # FIFO across separate clients
        after = {c["entity_id"]: c["workflow_state"] for c in self.rows(clients[0], "OpsCase")}
        self.assertTrue(all(after[case] not in (*CLAIMABLE, "INVESTIGATING") for case in taken), after)
        second_round = self.race({name: (lambda c=c, name=name: c.store.process_one(manual=True, worker_id=name))
                                  for c, name in zip(clients, WORKERS)})
        next_taken = {r["case_id"] for r in second_round.values() if isinstance(r, dict) and r.get("case_id")}
        self.assertEqual(next_taken, {c["entity_id"] for c in oldest[4:8]}, second_round)
        self.assertFalse(taken & next_taken)
        runs = self.rows(clients[0], "OpsRun")
        self.assertEqual((len(runs), len({r["case_id"] for r in runs})), (8, 8))
        print("\nV3.4 ROUND STATES", json.dumps({"after_first_round": sorted(after[c] for c in taken)}))


if __name__ == "__main__":
    unittest.main()
