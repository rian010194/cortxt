import pytest
from runtime.selfhosted_lifecycle import (
    SelfhostedLifecycleError, _VastAiControlAdapter, ensure_running, should_stop_for_idle,
)
from runtime.selfhosted_liveness import LivenessSample

def test_should_stop_when_idle_past_threshold():
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0 + 16*60,
                                 idle_threshold_minutes=15) is True

def test_should_not_stop_when_within_threshold():
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0 + 5*60,
                                 idle_threshold_minutes=15) is False

def test_should_not_stop_when_no_activity_recorded_yet():
    # Fail-closed the other direction: never seen activity means "just started",
    # not "idle forever" -- caller passes provisioning time as last_activity_ts.
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0,
                                 idle_threshold_minutes=15) is False


def test_ensure_running_starts_stopped_instance_then_waits_healthy(monkeypatch):
    calls = []
    class FakeControl:
        def status(self): return "stopped"
        def start(self): calls.append("start")
    class FakeProbe:
        def __init__(self):
            self._n = 0
        def check(self):
            self._n += 1
            return LivenessSample(alive=(self._n >= 2), vram_pct=None,
                                   queue_depth=None, tokens_per_sec=None, checked_at=0.0)
    ensure_running(control=FakeControl(), probe=FakeProbe(), poll_interval_s=0)
    assert calls == ["start"]

def test_ensure_running_noop_when_already_running(monkeypatch):
    calls = []
    class FakeControl:
        def status(self): return "running"
        def start(self): calls.append("start")
    class FakeProbe:
        def check(self):
            return LivenessSample(alive=True, vram_pct=None, queue_depth=None,
                                   tokens_per_sec=None, checked_at=0.0)
    ensure_running(control=FakeControl(), probe=FakeProbe(), poll_interval_s=0)
    assert calls == []

def test_ensure_running_raises_after_max_wait(monkeypatch):
    class FakeControl:
        def status(self): return "stopped"
        def start(self): pass
    class FakeProbe:
        def check(self):
            return LivenessSample(alive=False, vram_pct=None, queue_depth=None,
                                   tokens_per_sec=None, checked_at=0.0)
    with pytest.raises(SelfhostedLifecycleError):
        ensure_running(control=FakeControl(), probe=FakeProbe(), poll_interval_s=0,
                        max_wait_s=0)
