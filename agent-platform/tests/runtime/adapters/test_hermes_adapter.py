from __future__ import annotations

import pytest

from runtime.adapters.hermes_adapter import HermesAdapter
from runtime.engine_adapter import EngineAdapter
from routing.hermes_invoker import HermesInvocationError


def test_hermes_adapter_is_an_engine_adapter():
    assert isinstance(HermesAdapter(), EngineAdapter)


def test_invoke_delegates_to_injected_invoke_hermes_unchanged():
    calls = []

    def fake_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
        calls.append((profile, prompt, timeout_seconds, model, provider, cwd, session_id))
        return {"status": "succeeded", "profile": profile}

    adapter = HermesAdapter(invoke_hermes=fake_invoke_hermes)
    result = adapter.invoke("researcher", "do research", timeout_seconds=300, model="m", provider="p")

    assert result == {"status": "succeeded", "profile": "researcher"}
    assert calls == [("researcher", "do research", 300, "m", "p", None, None)]


def test_invoke_propagates_hermes_invocation_error_unwrapped():
    def raising_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
        raise HermesInvocationError("could not start hermes")

    adapter = HermesAdapter(invoke_hermes=raising_invoke_hermes)
    with pytest.raises(HermesInvocationError):
        adapter.invoke("builder", "do it", timeout_seconds=60)


def test_default_constructor_delegates_to_live_hermes_invoker_module_lookup():
    from unittest.mock import patch

    fake_result = {"status": "succeeded", "profile": "builder"}
    adapter = HermesAdapter()
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result) as fake:
        result = adapter.invoke("builder", "do it", timeout_seconds=60)
    fake.assert_called_once_with("builder", "do it", timeout_seconds=60, model=None, provider=None, cwd=None, session_id=None)
    assert result == fake_result


def test_explicit_invoke_hermes_still_takes_priority_over_live_lookup():
    from unittest.mock import patch

    calls = []

    def explicit_fn(profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
        calls.append((profile, prompt, timeout_seconds, model, provider, cwd, session_id))
        return {"status": "succeeded", "profile": profile}

    adapter = HermesAdapter(invoke_hermes=explicit_fn)
    with patch("routing.hermes_invoker.invoke_hermes") as unused_patch:
        adapter.invoke("builder", "do it", timeout_seconds=60)
    unused_patch.assert_not_called()
    assert calls == [("builder", "do it", 60, None, None, None, None)]


def test_invoke_passes_session_id_through_to_invoke_hermes():
    calls = []

    def fake_invoke_hermes(profile, prompt, *, timeout_seconds, model=None,
                            provider=None, cwd=None, session_id=None):
        calls.append(session_id)
        return {"status": "succeeded", "profile": profile, "session_id": "new-id"}

    adapter = HermesAdapter(invoke_hermes=fake_invoke_hermes)
    result = adapter.invoke("builder", "do it", timeout_seconds=60, session_id="old-id")

    assert calls == ["old-id"]
    assert result["session_id"] == "new-id"
