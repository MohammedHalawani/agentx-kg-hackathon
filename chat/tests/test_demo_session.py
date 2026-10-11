"""The curated demo session (SUHAIL_DEMO_SHIPMENTS) and the expected answer time of an execution. In memory; no model.

  - With the option set the monitor opens cases only for the listed shipments. Everything is still ingested and every
    shipment's evidence stays readable; the worker status says the option is on and how many shipments it lists.
  - Unset, nothing changes.
  - An acknowledged execution carries expected_response_at, from the simulator's schedule for the request type alone:
    the same whether or not the field will answer.
"""
import os
import unittest
from unittest import mock

from dataset_v2.contracts import Config, instant
from dataset_v2.generate import generate
from operations.store import DEMO_SHIPMENTS_ENV, OperationsStore, demo_shipments
from operations.world_simulation import DELAY, RECEIPTS, RESPONSE_ALLOWANCE
from tests.test_operations_store import Driver, Reader, development_reset
from tests.test_world_simulation import HEALTHY_DEVICE, OUTAGE_DEVICE, OUTAGE_SHIPMENT, Scenario, at
from tests.world_live import seed_case, symptoms_at


def when(value):
    """A ledger time (stored as a datetime, served as text) as a datetime."""
    return instant(value) if isinstance(value, str) else value


class OptionTests(unittest.TestCase):
    def test_ids_are_accepted_in_public_or_internal_form(self):
        self.assertEqual(demo_shipments(" SYN-SHP-000064, DEMO-SHP-000049 ,,SYN-SHP-000064"), frozenset({"DEMO-SHP-000064", "DEMO-SHP-000049"}))
        for unset in ("", " ", ",", " , "):
            self.assertIsNone(demo_shipments(unset))
        with mock.patch.dict(os.environ):
            os.environ.pop(DEMO_SHIPMENTS_ENV, None)
            self.assertIsNone(demo_shipments())
            os.environ[DEMO_SHIPMENTS_ENV] = "SYN-SHP-000001"
            self.assertEqual(demo_shipments(), frozenset({"DEMO-SHP-000001"}))


class CuratedSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = generate(Config(total=90))

    def session(self, listed=None, rounds=None):
        """A session replayed day by day with the monitor draining its queue. Returns (store, driver, rounds run)."""
        with mock.patch.dict(os.environ):
            os.environ.pop(DEMO_SHIPMENTS_ENV, None)
            if listed is not None:
                os.environ[DEMO_SHIPMENTS_ENV] = listed
            driver = Driver(self.world)
            store = OperationsStore(driver, "shipments-v2-demo", self.world.config.dataset_id, self.world.config, Reader(self.world))
        store.initialize(); development_reset(store)
        ran = 0
        while ran < (rounds or 12):
            store.tick(seconds=86400, manual=True, speed=60)
            ran += 1
            while store.status()["session"]["monitor_pending"]:
                store.monitor_step()
            if rounds is None and len(self.cases(driver)) >= 3:
                break
        return store, driver, ran

    @staticmethod
    def cases(driver):
        return sorted(props["shipment_id"] for kind, props in driver.ledger.values() if kind == "OpsCase")

    def test_only_the_listed_shipments_become_cases(self):
        open_store, open_driver, rounds = self.session()
        everything = self.cases(open_driver)
        self.assertGreaterEqual(len(everything), 3)
        self.assertEqual(open_store.status()["session"]["demo_shipments"], {"enabled": False, "count": 0})
        chosen, left_out = everything[:2], everything[2:]
        never = "DEMO-SHP-999999"       # Listed but not in the data: counted, never a case.
        store, driver, _ = self.session(",".join([chosen[0].replace("DEMO-", "SYN-"), chosen[1], never]), rounds)
        self.assertEqual(self.cases(driver), chosen)
        session = store.status()["session"]
        self.assertEqual(session["demo_shipments"], {"enabled": True, "count": 3})
        self.assertEqual((session["monitor_pending"], session["monitor_opened"], session["monitor_checked"] >= 2), (0, 2, True))
        # The same world was ingested: same clock and event count, and the other shipments' evidence is still readable.
        self.assertEqual(store.status()["as_of"], open_store.status()["as_of"])
        self.assertEqual(store.status()["simulator"]["event_count"], open_store.status()["simulator"]["event_count"])
        context = store._reader().evidence(left_out[0], store.status()["as_of"])
        self.assertTrue(any(n["kind"] == "Shipment" and n["id"] == left_out[0] for n in context["nodes"]))
        # The automatic worker has nothing but the curated cases to claim.
        claimed = set()
        for _ in range(len(everything) + 1):
            result = store.process_one(manual=True)
            if not result.get("processed"):
                break
            claimed.add(driver.ledger[result["case_id"]][1]["shipment_id"])
        self.assertEqual(claimed, set(chosen))

    def test_unset_opens_what_it_opened_before_and_a_shipment_listed_later_is_picked_up(self):
        first, first_driver, rounds = self.session()
        second, second_driver, _ = self.session(None, rounds)
        self.assertEqual(self.cases(second_driver), self.cases(first_driver))
        self.assertIsNone(second.demo_shipments)
        # The list is the store's own setting: with an empty list nothing opens.
        store, driver, _ = self.session("DEMO-SHP-999999", rounds)
        self.assertEqual(self.cases(driver), [])
        self.assertEqual(store.status()["session"]["monitor_opened"], 0)


class ExpectedResponseTests(unittest.TestCase):
    def test_the_time_comes_from_the_request_type_alone(self):
        s = Scenario(at("15T18:00"))
        now = s.live.clock
        for action in RECEIPTS:
            times = {s.sim.expected_response_at(s.execution(sid, action), now) for sid in (OUTAGE_SHIPMENT, "DEMO-SHP-000064", "DEMO-SHP-999999")}
            self.assertEqual(len(times), 1, action)                # no shipment, parcel or device state is read
            [expected] = times
            if action in RESPONSE_ALLOWANCE:
                self.assertEqual((instant(expected) - instant(now)).total_seconds(), 60 * (DELAY[action] + RESPONSE_ALLOWANCE[action]), action)
            else:                                                  # answered in a depot session or by a return journey
                self.assertIsNone(expected, action)
        self.assertEqual(sorted(set(RECEIPTS) - set(RESPONSE_ALLOWANCE)),
                         ["PRIORITIZE_NEXT_SESSION", "REROUTE_TO_CONFIRMED_DESTINATION", "RETURN_TO_SENDER"])
        self.assertIsNone(s.sim.expected_response_at({"action_type": "NOT_AN_ACTION"}, now))

    def executed(self, device):
        s = Scenario(at("15T18:00"))
        symptoms = symptoms_at(s.live, OUTAGE_SHIPMENT, s.live.clock)
        case_id = seed_case(s.store, s.driver, OUTAGE_SHIPMENT, "REQUEST_DEVICE_SYNC", ["DELAYED_SYNC"], symptoms=symptoms,
                            target={"device_id": device, "expected_evidence": []})
        [executed] = s.store.execute_step()
        [served] = s.store.case_detail(case_id)["executions"]
        return s, s.driver.ledger[executed][1], served

    def test_an_acknowledged_execution_carries_it_whatever_the_field_will_answer(self):
        s, answered, served = self.executed(OUTAGE_DEVICE)      # the device holds records: they will upload
        _, silent, _ = self.executed(HEALTHY_DEVICE)            # a healthy device: nothing will come of it
        self.assertEqual((answered["status"], silent["status"]), ("ACKNOWLEDGED", "ACKNOWLEDGED"))
        expected = when(answered["expected_response_at"])
        self.assertEqual(expected, when(silent["expected_response_at"]))
        self.assertEqual((expected - when(answered["executed_at"])).total_seconds(), 60 * (DELAY["REQUEST_DEVICE_SYNC"] + 1))
        self.assertLess(expected, when(answered["deadline_at"]))
        self.assertEqual(when(served["expected_response_at"]), expected)       # as GET /cases/{id} serves executions[]
        self.assertNotIn("expected", answered["adapter_result_json"])             # the receipt itself is unchanged
        # The answer that does come has reached Suhail by then.
        delivered = [instant(row[4]) for row in s.answers()]
        self.assertTrue(delivered and max(delivered) <= expected)

    def test_an_execution_nothing_acknowledged_has_none(self):
        s = Scenario(at("15T18:00"))
        symptoms = symptoms_at(s.live, OUTAGE_SHIPMENT, s.live.clock)
        seed_case(s.store, s.driver, OUTAGE_SHIPMENT, "REQUEST_DEVICE_SYNC", ["DELAYED_SYNC"], symptoms=symptoms,
                  target={"device_id": "DEMO-DEV-NO-SUCH-DEVICE", "expected_evidence": []})
        [executed] = s.store.execute_step()
        execution = s.driver.ledger[executed][1]
        self.assertEqual(execution["status"], "NOT_ACKNOWLEDGED")
        self.assertIsNone(execution.get("expected_response_at")); self.assertIsNone(execution.get("deadline_at"))


if __name__ == "__main__":
    unittest.main()
