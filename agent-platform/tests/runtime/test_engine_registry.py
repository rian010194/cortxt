from __future__ import annotations

from pathlib import Path

import pytest

from runtime.engine_registry import EngineBroker, EngineContext, NoProviderRegisteredError


class _FakeAdapter:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
        self.calls.append((profile, prompt, timeout_seconds, model, provider, cwd, session_id))
        return self._response


def test_empty_broker_has_no_provider():
    broker = EngineBroker()
    assert broker.has_provider is False


def test_empty_broker_invoke_raises_no_provider_registered():
    broker = EngineBroker()
    with pytest.raises(NoProviderRegisteredError):
        broker.invoke("builder", "do it", timeout_seconds=60)


def test_broker_with_one_provider_passes_through():
    adapter = _FakeAdapter({"status": "succeeded"})
    broker = EngineBroker()
    broker.register(adapter)
    result = broker.invoke("builder", "do it", timeout_seconds=60, model="m", provider="p")
    assert result == {"status": "succeeded"}
    assert adapter.calls == [("builder", "do it", 60, "m", "p", None, None)]
    assert broker.has_provider is True


def test_broker_passes_cwd_through_to_adapter():
    adapter = _FakeAdapter({"status": "succeeded"})
    broker = EngineBroker()
    broker.register(adapter)
    worktree = Path("/some/worktree")
    broker.invoke("builder", "do it", timeout_seconds=60, cwd=worktree)
    assert adapter.calls == [("builder", "do it", 60, None, None, worktree, None)]


def test_broker_passes_session_id_through_to_adapter():
    adapter = _FakeAdapter({"status": "succeeded"})
    broker = EngineBroker()
    broker.register(adapter)
    broker.invoke("builder", "do it", timeout_seconds=60, session_id="sess-123")
    assert adapter.calls == [("builder", "do it", 60, None, None, None, "sess-123")]


def test_context_get_returns_broker_for_unknown_engine_id():
    context = EngineContext()
    broker = context.get("nobody-registered-this")
    assert isinstance(broker, EngineBroker)
    assert broker.has_provider is False


def test_context_get_is_stable_across_calls():
    context = EngineContext()
    first = context.get("hermes")
    second = context.get("hermes")
    assert first is second


def test_context_register_makes_broker_have_provider():
    adapter = _FakeAdapter({"status": "succeeded"})
    context = EngineContext()
    context.register("hermes", adapter)
    assert context.get("hermes").has_provider is True
