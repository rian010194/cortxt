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


def test_status_parses_real_vastai_response_shape(monkeypatch):
    # Verified live against Vast.ai's actual GET /api/v0/instances/<id>/
    # response, 2026-08-17: fields are nested under a top-level "instances"
    # key, not flat as an earlier draft assumed -- that earlier version always
    # returned "stopped" for a genuinely running instance.
    import json

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"instances": {"actual_status": "running"}}).encode()

    def fake_urlopen(request, timeout=None):
        return FakeResponse()

    monkeypatch.setattr("runtime.selfhosted_lifecycle.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("CORTXT_SELFHOSTED_API_KEY", "secret-token")
    control = _VastAiControlAdapter(instance_id="47966869",
                                     api_key_env="CORTXT_SELFHOSTED_API_KEY")
    assert control.status() == "running"


def test_status_stopped_when_actual_status_not_running(monkeypatch):
    import json

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"instances": {"actual_status": "exited"}}).encode()

    def fake_urlopen(request, timeout=None):
        return FakeResponse()

    monkeypatch.setattr("runtime.selfhosted_lifecycle.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("CORTXT_SELFHOSTED_API_KEY", "secret-token")
    control = _VastAiControlAdapter(instance_id="47966869",
                                     api_key_env="CORTXT_SELFHOSTED_API_KEY")
    assert control.status() == "stopped"


def test_stop_sends_real_vastai_request_shape(monkeypatch):
    # Verified live against Vast.ai's actual control API, 2026-08-17 (via the
    # official vastai CLI's --explain): a single PUT to the instance resource
    # with {"state": "stopped"}, not a separate /stop/ sub-route as an
    # earlier draft assumed.
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = request.data
        return FakeResponse()

    monkeypatch.setattr("runtime.selfhosted_lifecycle.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("CORTXT_SELFHOSTED_API_KEY", "secret-token")
    control = _VastAiControlAdapter(instance_id="47966869",
                                     api_key_env="CORTXT_SELFHOSTED_API_KEY")
    control.stop()
    assert captured["url"] == "https://console.vast.ai/api/v0/instances/47966869/"
    assert captured["method"] == "PUT"
    assert captured["body"] == b'{"state": "stopped"}'
