"""The hard call-budget guard and its crash-safe ledger."""
import random

import pytest

from stage3_eval.budget import BudgetExceeded, BudgetLedger, CapViolation, read_ledger


def test_reserve_settle_and_refuse(tmp_path):
    led = BudgetLedger(tmp_path / "l.jsonl", 30)
    r = led.reserve("E1:a", "agent", 12)
    assert led.committed == 12
    led.settle(r, 9, tokens=100)
    assert led.committed == 9 and led.settled == 9 and led.tokens == 100
    led.settle(led.reserve("E1:a", "notools", 2), 1)
    led.reserve("E1:b", "agent", 12)
    with pytest.raises(BudgetExceeded):
        led.reserve("E1:c", "agent", 12)       # 10 + 12 held + 12 > 30: refused before anything is called
    events = [e["event"] for e in read_ledger(tmp_path / "l.jsonl")]
    assert events == ["open", "reserve", "settle", "reserve", "settle", "reserve", "refused"]


def test_settle_above_reservation_is_a_recorded_violation(tmp_path):
    led = BudgetLedger(tmp_path / "l.jsonl", 100)
    r = led.reserve("E1:a", "agent", 12)
    with pytest.raises(CapViolation):
        led.settle(r, 13)
    assert led.violations and "violation" in [e["event"] for e in read_ledger(tmp_path / "l.jsonl")]


def test_missing_call_count_is_settled_at_worst_case(tmp_path):
    led = BudgetLedger(tmp_path / "l.jsonl", 100)
    led.settle(led.reserve("E1:a", "agent", 12), None)
    assert led.settled == 12
    assert read_ledger(tmp_path / "l.jsonl")[-1]["source"].startswith("reserved_worst_case")


def test_crash_recovery_counts_open_reservations_at_worst_case(tmp_path):
    path = tmp_path / "l.jsonl"
    led = BudgetLedger(path, 50)
    led.settle(led.reserve("E1:a", "agent", 12), 7)
    led.reserve("E1:b", "agent", 12)           # the process dies here
    with pytest.raises(FileExistsError):
        BudgetLedger(path, 50)
    again = BudgetLedger(path, 50, resume=True)
    assert again.settled == 19 and again.recovered == 1 and ("E1:b", "agent") in again.done
    assert read_ledger(path)[-1]["event"] == "crash_recovery"
    with pytest.raises(ValueError):
        BudgetLedger(path, 60, resume=True)    # a resume cannot change the budget


def test_dry_run_plans_and_spends_nothing(tmp_path):
    led = BudgetLedger(tmp_path / "l.jsonl", 20, dry_run=True)
    assert led.reserve("E1:a", "agent", 12) is None
    led.settle(None, 99)                        # ignored in a dry run
    assert led.settled == 0 and led.planned == 12
    with pytest.raises(BudgetExceeded):
        led.reserve("E1:b", "agent", 12)


def test_random_sequences_never_exceed_the_budget(tmp_path):
    rng = random.Random(7)
    for trial in range(20):
        led = BudgetLedger(tmp_path / f"l{trial}.jsonl", 200)
        for i in range(60):
            try:
                rid = led.reserve(f"E1:{i}", "agent", rng.randint(1, 14))
            except BudgetExceeded:
                continue
            reserved = led.open[rid][2]
            led.settle(rid, rng.randint(0, reserved))
            assert led.committed <= 200
        assert led.settled <= 200
