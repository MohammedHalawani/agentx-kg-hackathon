"""Progress events of a running investigation are written in batches (operations.store.StageBuffer).

Every event used to be its own write transaction, on the investigation's own thread: about 0.3 s each, 5 to 8 s per
case. Now the first event of a run and a FAILED event are written at once; any other waits at most
SUHAIL_STAGE_FLUSH_SECONDS (0.75 s by default, never above 1 s) and is written with whatever else is waiting, off the
investigation's thread; everything waiting is written before the run's result is committed, after the run, and on
every failure path. No event is lost and the order is the order they were emitted in.

In-memory ledger, scripted investigator and reviewer: no database, no model.
"""
import copy
import json
import os
import time
import unittest
from unittest import mock

from operations import store as store_module
from operations.schema import public_value
from operations.store import STAGE_FLUSH_MAX_SECONDS, StageBuffer, stage_flush_seconds
from tests import test_material_reinvestigation as tm
from tests.test_operations_store import approval_policy


def event(sequence, status="RUNNING", stage="classify"):
    return {"sequence": sequence, "stage": stage, "status": status, "iteration": 0, "recorded_at": f"t{sequence}", "output": {}}


class ManualTimer:
    """threading.Timer's interface; fires only when the test says the interval has passed."""
    made = []

    def __init__(self, interval, function):
        self.interval, self.function, self.started, self.cancelled, self.daemon, self.fired = interval, function, False, False, False, False
        ManualTimer.made.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if self.started and not self.cancelled and not self.fired:
            self.fired = True
            self.function()

    @classmethod
    def live(cls):
        return [t for t in cls.made if t.started and not t.cancelled and not t.fired]


class Writes:
    """Stands in for the store's batch write: records every batch with the events list it was given."""

    def __init__(self):
        self.batches, self.fail = [], None

    def __call__(self, batch, events):
        if self.fail:
            error, self.fail = self.fail, None
            raise error
        self.batches.append(([e["sequence"] for e in batch], [e["sequence"] for e in events]))

    def sequences(self):
        return [s for batch, _events in self.batches for s in batch]


class BufferTests(unittest.TestCase):
    def setUp(self):
        ManualTimer.made = []
        self.writes = Writes()
        self.buffer = StageBuffer(self.writes, 0.75, timer=ManualTimer)
        self.emitted = []

    def add(self, sequence, status="RUNNING"):
        self.emitted.append(event(sequence, status))
        self.buffer.add(self.emitted[-1], list(self.emitted))

    def test_the_first_event_is_written_at_once_and_the_next_ones_together_when_the_interval_ends(self):
        self.add(1)
        self.assertEqual(self.writes.batches, [([1], [1])])                 # the run is on record from its first event
        self.assertEqual(ManualTimer.made, [])
        for sequence in (2, 3, 4):
            self.add(sequence)
        self.assertEqual(self.writes.batches, [([1], [1])])                 # waiting
        [timer] = ManualTimer.made                                          # one timer for the three, set at the first of them
        self.assertEqual((timer.interval, timer.started, timer.daemon), (0.75, True, True))
        timer.fire()
        self.assertEqual(self.writes.batches[1], ([2, 3, 4], [1, 2, 3, 4]))  # one write, in order, with every event so far
        self.add(5)
        self.assertEqual(len(ManualTimer.made), 2)                          # a new wait for the next one
        ManualTimer.made[1].fire()
        self.assertEqual(self.writes.sequences(), [1, 2, 3, 4, 5])          # nothing lost, nothing twice, in order

    def test_a_failed_event_is_written_at_once_with_everything_before_it(self):
        self.add(1)
        self.add(2)
        self.add(3, "FAILED")
        self.assertEqual(self.writes.batches, [([1], [1]), ([2, 3], [1, 2, 3])])
        self.assertEqual(ManualTimer.live(), [])                            # the pending timer was cancelled by the write

    def test_flush_before_the_commit_and_close_after_the_run_write_what_is_waiting(self):
        for sequence in (1, 2, 3):
            self.add(sequence)
        self.assertEqual(self.buffer.flush(), 2)                            # before the result is committed
        self.assertEqual(self.writes.sequences(), [1, 2, 3])
        self.add(4)                                                         # the last stage's own event, after the commit
        self.assertEqual(self.buffer.close(), 1)
        self.assertEqual(self.writes.sequences(), [1, 2, 3, 4])
        for timer in ManualTimer.made:                                      # a timer that fires late finds nothing to do
            timer.function()
        self.assertEqual(self.writes.sequences(), [1, 2, 3, 4])
        self.assertEqual(self.buffer.close(), 0)
        self.add(5)                                                         # after the end an event is written at once, never kept
        self.assertEqual(self.writes.sequences(), [1, 2, 3, 4, 5])

    def test_a_write_that_fails_on_the_timer_loses_nothing_and_is_raised_on_the_investigations_thread(self):
        self.add(1)
        self.add(2)
        self.add(3)
        self.writes.fail = RuntimeError("database away")
        with self.assertLogs("operations.store", level="WARNING"):
            ManualTimer.made[0].fire()                                      # the timer's thread: logged, not raised, not dropped
        self.assertEqual(self.writes.sequences(), [1])
        self.writes.fail = store_module.OperationsConflict("Investigation was superseded")
        with self.assertRaises(store_module.OperationsConflict):            # the next event: written here, and its error is raised here
            self.add(4)
        self.assertEqual(self.writes.sequences(), [1])
        self.add(5)                                                         # still retrying on this thread: now it goes through
        self.assertEqual(self.writes.batches[-1], ([2, 3, 4, 5], [1, 2, 3, 4, 5]))
        self.add(6)                                                         # and batching resumes
        self.assertEqual(self.writes.sequences(), [1, 2, 3, 4, 5])
        self.buffer.close()
        self.assertEqual(self.writes.sequences(), [1, 2, 3, 4, 5, 6])

    def test_close_on_a_failure_path_never_hides_the_first_error_and_close_after_a_run_raises(self):
        self.add(1)
        self.add(2)
        self.writes.fail = RuntimeError("database away")
        self.assertEqual(self.buffer.close(quiet=True), 0)                  # swallowed: the caller is already raising
        other = StageBuffer(Writes(), 0.75, timer=ManualTimer)
        other.add(event(1), [event(1)])
        other.add(event(2), [event(1), event(2)])
        other.write.fail = RuntimeError("database away")
        with self.assertRaises(RuntimeError):
            other.close()

    def test_an_interval_of_zero_writes_every_event_alone_as_before(self):
        buffer = StageBuffer(self.writes, 0, timer=ManualTimer)
        emitted = []
        for sequence in (1, 2, 3):
            emitted.append(event(sequence))
            buffer.add(emitted[-1], list(emitted))
        self.assertEqual(self.writes.batches, [([1], [1]), ([2], [1, 2]), ([3], [1, 2, 3])])
        self.assertEqual(ManualTimer.made, [])

    def test_the_wait_is_0_75_seconds_by_default_and_never_more_than_one_second(self):
        self.assertEqual((store_module.STAGE_FLUSH_ENV, store_module.STAGE_FLUSH_SECONDS, STAGE_FLUSH_MAX_SECONDS),
                         ("SUHAIL_STAGE_FLUSH_SECONDS", 0.75, 1.0))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(store_module.STAGE_FLUSH_ENV, None)
            self.assertEqual(stage_flush_seconds(), 0.75)
            for text, expected in (("0.25", 0.25), ("0", 0.0), ("5", 1.0), ("-1", 0.0), ("soon", 0.75), ("nan", 0.75)):
                os.environ[store_module.STAGE_FLUSH_ENV] = text
                self.assertEqual(stage_flush_seconds(), expected, text)
            self.assertEqual((stage_flush_seconds(0.5), stage_flush_seconds(30)), (0.5, 1.0))     # the store's own setting

    def test_events_added_from_another_thread_while_a_batch_is_being_written_wait_for_the_next_one(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        writes = Writes()

        def slow(batch, events):
            if len(writes.batches) == 1:
                entered.set()
                release.wait(5)
            writes(batch, events)
        buffer = StageBuffer(slow, 0.75, timer=ManualTimer)
        emitted = [event(1), event(2)]
        buffer.add(emitted[0], emitted[:1])
        buffer.add(emitted[1], emitted[:2])
        writer = threading.Thread(target=ManualTimer.made[0].fire)          # the timer's thread, writing event 2
        writer.start()
        self.assertTrue(entered.wait(5))
        emitted.append(event(3))
        buffer.add(emitted[2], list(emitted))                               # the investigation goes on meanwhile; it is not blocked
        release.set()
        writer.join(5)
        self.assertEqual(writes.sequences(), [1, 2])
        self.assertEqual(len(ManualTimer.live()), 1)                        # event 3 has its own wait
        buffer.close()
        self.assertEqual(writes.sequences(), [1, 2, 3])


class StoreTests(tm._Base):
    """The real investigation graph and store over the in-memory ledger."""

    def setUp(self):
        super().setUp()
        ManualTimer.made = []

    def prepared(self, during=None, interval=0.75, timer=ManualTimer):
        store, driver = self.make()
        store.stage_flush_seconds, store.stage_timer = interval, timer
        self.batches = []
        original = store._record_stages

        def recording(claimed, batch, events):
            original(claimed, batch, events)
            self.batches.append([e["sequence"] for e in batch])
        store._record_stages = recording
        store.agents = tm.Scripted((lambda: during(store, driver)) if during else None)
        return store, driver

    def stage_audits(self, driver):
        rows = [a for a in self.kind(driver, "OpsAudit") if a["event_type"] == "PIPELINE_STAGE"]
        return sorted(rows, key=lambda a: a["sequence"])

    def test_every_event_is_on_record_once_and_in_order_with_fewer_writes(self):
        store, driver = self.prepared()
        with approval_policy():
            result = store.process_one(manual=True)
        self.assertTrue(result["processed"])
        events = store.case_detail(result["case_id"])["run"]["result"]["pipeline_events"]
        sequences = [e["sequence"] for e in events]
        self.assertGreater(len(events), 10)
        self.assertEqual(sequences, list(range(1, len(events) + 1)))                       # complete and in order in the run record
        audits = self.stage_audits(driver)
        self.assertEqual([a["sequence"] for a in audits], sequences)                       # one audit entry per event, none twice
        self.assertEqual([(a["stage"], a["stage_status"]) for a in audits], [(e["stage"], e["status"]) for e in events])
        self.assertEqual([a["wall_recorded_at"] for a in audits], [e["recorded_at"] for e in events])
        self.assertEqual(sorted(a["wall_recorded_at"] for a in audits), [a["wall_recorded_at"] for a in audits])
        # Written in batches: the batches partition the events in order, and there are far fewer of them.
        self.assertEqual([s for batch in self.batches for s in batch], sequences)
        self.assertEqual(self.batches[0], [1])                                             # the first event at once
        self.assertLessEqual(len(self.batches), 4)                 # first event, before the commit, after the run (no interval passed here)
        self.assertEqual(store.pipeline_state(result["case_id"])["status"], "REVIEWED")    # and the run is saved as finished after them
        self.assertEqual(ManualTimer.live(), [])                                           # no timer outlives the run

    def test_with_an_interval_of_zero_each_event_is_its_own_write(self):
        store, driver = self.prepared(interval=0)
        with approval_policy():
            result = store.process_one(manual=True)
        events = store.case_detail(result["case_id"])["run"]["result"]["pipeline_events"]
        self.assertEqual(self.batches, [[e["sequence"]] for e in events])

    def test_the_live_stage_is_served_while_the_run_is_going_once_the_interval_has_passed(self):
        seen = {}

        def during(store, driver):
            case_id = self.investigating(driver)["entity_id"]
            listener = store.subscribe_pipeline(case_id)
            seen["at_once"] = store.pipeline_state(case_id)["events"]                      # what is written without any wait
            self.assertEqual(len(ManualTimer.live()), 1)                                   # the rest waits for the interval
            ManualTimer.live()[0].fire()                                                   # the interval passes (at most 1 s)
            seen["polled"] = store.pipeline_state(case_id)
            seen["detail"] = store.case_detail(case_id)
            seen["pushed"] = listener.get_nowait()
            store.unsubscribe_pipeline(case_id, listener)
        store, driver = self.prepared(during)
        with approval_policy():
            result = store.process_one(manual=True)
        self.assertEqual([(e["stage"], e["status"]) for e in seen["at_once"]], [("extract", "RUNNING")])
        live = [(e["stage"], e["status"]) for e in seen["polled"]["events"]]
        self.assertEqual(live[-1], ("classify", "RUNNING"))                                # the stage that is running now
        self.assertEqual(live[:4], [("extract", "RUNNING"), ("extract", "COMPLETED"), ("retrieve", "RUNNING"), ("retrieve", "COMPLETED")])
        self.assertEqual((seen["polled"]["status"], seen["polled"]["workflow_state"]), ("RUNNING", "INVESTIGATING"))
        self.assertEqual([e["sequence"] for e in seen["detail"]["run"]["result"]["pipeline_events"]], list(range(1, len(live) + 1)))   # GET /cases/{id}
        self.assertEqual(seen["pushed"]["events"], seen["polled"]["events"])               # the SSE stream's state
        self.assertEqual(seen["pushed"]["status"], "RUNNING")
        # And the finished run still holds every event once.
        events = store.case_detail(result["case_id"])["run"]["result"]["pipeline_events"]
        self.assertEqual([a["sequence"] for a in self.stage_audits(driver)], [e["sequence"] for e in events])

    def test_a_real_timer_writes_the_waiting_events_while_the_investigation_is_busy(self):
        import threading
        seen = {}

        def during(store, driver):
            case_id = self.investigating(driver)["entity_id"]
            started = time.monotonic()
            while time.monotonic() - started < 5:                                          # a model call in progress: nothing is emitted
                state = store.pipeline_state(case_id)
                if state["events"] and (state["events"][-1]["stage"], state["events"][-1]["status"]) == ("classify", "RUNNING"):
                    seen["after"] = time.monotonic() - started
                    break
                time.sleep(0.01)
        store, driver = self.prepared(during, interval=0.05, timer=threading.Timer)
        with approval_policy():
            result = store.process_one(manual=True)
        self.assertIn("after", seen, "the running stage never appeared while the investigation was busy")
        self.assertLess(seen["after"], STAGE_FLUSH_MAX_SECONDS)
        events = store.case_detail(result["case_id"])["run"]["result"]["pipeline_events"]
        self.assertEqual([a["sequence"] for a in self.stage_audits(driver)], [e["sequence"] for e in events])
        self.assertEqual([s for batch in self.batches for s in batch], [e["sequence"] for e in events])

    def test_a_run_that_fails_has_every_event_up_to_the_failure_on_record(self):
        def during(store, driver):
            raise RuntimeError("the investigator broke")
        store, driver = self.prepared(during)
        with self.assertRaises(RuntimeError) as raised:
            store.process_one(manual=True)
        self.assertEqual(str(raised.exception), "the investigator broke")
        audits = self.stage_audits(driver)
        self.assertEqual([a["sequence"] for a in audits], list(range(1, len(audits) + 1)))
        self.assertEqual((audits[-1]["stage"], audits[-1]["stage_status"]), ("classify", "FAILED"))     # the failure itself, written at once
        self.assertEqual((audits[-2]["stage"], audits[-2]["stage_status"]), ("classify", "RUNNING"))    # and what was waiting, before it
        [run] = self.kind(driver, "OpsRun")
        recorded = json.loads(run["result_json"])["pipeline_events"]
        self.assertEqual([e["sequence"] for e in recorded], [a["sequence"] for a in audits])
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(store.status()["worker"]["state"], "paused")
        self.assertEqual(ManualTimer.live(), [])

    def test_a_failure_while_writing_the_last_events_is_raised_and_the_first_error_is_never_hidden(self):
        store, driver = self.prepared()
        original = store._record_stages
        state = {"calls": 0}

        def failing(claimed, batch, events):
            state["calls"] += 1
            if state["calls"] >= 2:
                raise RuntimeError("database away")
            original(claimed, batch, events)
        store._record_stages = failing
        with approval_policy(), self.assertRaises(RuntimeError) as raised:
            store.process_one(manual=True)
        self.assertEqual(str(raised.exception), "database away")       # raised where it happened: before the commit
        self.assertEqual(store.status()["worker"]["state"], "paused")
        self.assertEqual(self.kind(driver, "OpsRecommendation"), [])   # nothing was committed past events that were not written

        def during(store, driver):
            raise ValueError("the investigator broke")
        store, driver = self.prepared(during)
        store._record_stages = lambda claimed, batch, events: (_ for _ in ()).throw(RuntimeError("database away"))
        with self.assertRaises(RuntimeError):                          # the very first event cannot be written: the run stops there
            store.process_one(manual=True)


if __name__ == "__main__":
    unittest.main()
