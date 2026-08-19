from __future__ import annotations

import pytest

from runtime.adapters.hermes_adapter import HermesAdapter
from runtime.engine_adapter import EngineAdapter
from routing.hermes_invoker import HermesInvocationError


def test_hermes_adapter_is_an_engine_adapter():
    assert isinstance(HermesAdapter(), EngineAdapter)


def test_invoke_delegates_to_injected_invoke_hermes_unchanged():
    calls = []

    def fake_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None):
        calls.append((profile, prompt, timeout_seconds, model, provider))
        return {"status": "succeeded", "profile": profile}

    adapter = HermesAdapter(invoke_hermes=fake_invoke_hermes)
    result = adapter.invoke("researcher", "do research", timeout_seconds=300, model="m", provider="p")

    assert result == {"status": "succeeded", "profile": "researcher"}
    assert calls == [("researcher", "do research", 300, "m", "p")]


def test_invoke_propagates_hermes_invocation_error_unwrapped():
    def raising_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None):
        raise HermesInvocationError("could not start hermes")

    adapter = HermesAdapter(invoke_hermes=raising_invoke_hermes)
    with pytest.raises(HermesInvocationError):
        adapter.invoke("builder", "do it", timeout_seconds=60)


def test_default_constructor_uses_real_invoke_hermes():
    import runtime.adapters.hermes_adapter as module
    from routing.hermes_invoker import invoke_hermes as real_invoke_hermes

    adapter = module.HermesAdapter()
    assert adapter._invoke_hermes is real_invoke_hermes
