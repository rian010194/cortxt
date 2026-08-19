import time

from daemon.budget import SessionBudget


def test_starts_not_exhausted():
    b = SessionBudget(max_cost_usd=10.0, max_wall_clock_seconds=3600.0)
    assert not b.exhausted()


def test_cost_ceiling_exhausts():
    b = SessionBudget(max_cost_usd=1.0, max_wall_clock_seconds=3600.0)
    b.record_cost(0.5)
    assert not b.exhausted()
    b.record_cost(0.6)
    assert b.exhausted()
    assert b.spent_usd == 1.1


def test_wall_clock_ceiling_exhausts(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])
    b = SessionBudget(max_cost_usd=1000.0, max_wall_clock_seconds=60.0)
    assert not b.exhausted()
    fake_time[0] += 61.0
    assert b.exhausted()


def test_negative_cost_rejected():
    b = SessionBudget(max_cost_usd=10.0, max_wall_clock_seconds=3600.0)
    try:
        b.record_cost(-1.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
