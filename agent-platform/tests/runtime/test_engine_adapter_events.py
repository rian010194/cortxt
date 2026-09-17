"""Event capability helpers on the engine adapter seam (ADR-047 D3).

The capability is declared by an adapter attribute and read through module
helpers -- it is deliberately not an EngineAdapter Protocol member, because a
data member on a runtime_checkable Protocol would make every existing adapter
fail isinstance().
"""
from __future__ import annotations

import pytest

from runtime.adapters.claude_adapter import ClaudeAdapter
from runtime.adapters.codex_adapter import CodexAdapter
from runtime.adapters.dsh_adapter import DshAdapter
from runtime.adapters.hermes_adapter import HermesAdapter
from runtime.adapters.hermes_free_adapter import HermesFreeAdapter
from runtime.engine_adapter import (
    EngineAdapter,
    EventsNotSupported,
    require_event_support,
    supports_events,
)

_EXISTING_ADAPTERS = [ClaudeAdapter, CodexAdapter, DshAdapter, HermesAdapter, HermesFreeAdapter]


@pytest.mark.parametrize("adapter_cls", _EXISTING_ADAPTERS, ids=lambda c: c.__name__)
def test_existing_adapters_do_not_support_events(adapter_cls):
    assert supports_events(adapter_cls()) is False


@pytest.mark.parametrize("adapter_cls", _EXISTING_ADAPTERS, ids=lambda c: c.__name__)
def test_require_event_support_raises_for_existing_adapters_naming_the_type(adapter_cls):
    with pytest.raises(EventsNotSupported, match=adapter_cls.__name__):
        require_event_support(adapter_cls())


class _Declares:
    def __init__(self, value):
        self.supports_events = value

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
        return {"status": "succeeded", "session_id": session_id}


@pytest.mark.parametrize("value", ["yes", 1, [True], object()])
def test_truthy_non_true_declarations_do_not_count(value):
    adapter = _Declares(value)
    assert supports_events(adapter) is False
    with pytest.raises(EventsNotSupported):
        require_event_support(adapter)


def test_declared_true_supports_events_and_require_passes():
    adapter = _Declares(True)
    assert supports_events(adapter) is True
    assert require_event_support(adapter) is None


def test_object_with_only_invoke_is_still_an_engine_adapter():
    class _OnlyInvoke:
        def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
            return {}

    assert isinstance(_OnlyInvoke(), EngineAdapter)
    assert supports_events(_OnlyInvoke()) is False


def test_capability_is_not_a_protocol_member():
    # A Protocol member would be listed here and enforced by isinstance().
    assert "supports_events" not in getattr(EngineAdapter, "__protocol_attrs__", {"invoke"})
    assert not hasattr(EngineAdapter, "supports_events")
