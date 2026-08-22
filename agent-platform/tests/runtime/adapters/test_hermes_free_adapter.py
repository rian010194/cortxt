from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from routing.hermes_invoker import HermesInvocationError
from runtime.adapters.hermes_free_adapter import HermesFreeAdapter
from runtime.engine_adapter import EngineAdapter


def test_hermes_free_adapter_is_an_engine_adapter():
    assert isinstance(HermesFreeAdapter(), EngineAdapter)


def test_invoke_fails_without_configuration_and_does_not_invoke(monkeypatch):
    monkeypatch.delenv("CORTXT_FREE_MODEL", raising=False)
    monkeypatch.delenv("CORTXT_FREE_PROVIDER", raising=False)
    invoke_hermes = Mock()

    result = HermesFreeAdapter(invoke_hermes=invoke_hermes).invoke(
        "researcher", "do research", timeout_seconds=300
    )

    assert result == {
        "status": "failed",
        "profile": "researcher",
        "stdout": "",
        "stderr": "free route not configured: set CORTXT_FREE_MODEL and CORTXT_FREE_PROVIDER",
        "elapsed_seconds": 0.0,
        "session_id": None,
    }
    invoke_hermes.assert_not_called()


def test_invoke_passes_environment_overrides_and_result_through(monkeypatch):
    monkeypatch.setenv("CORTXT_FREE_MODEL", "free-model")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "free-provider")
    expected = {"status": "succeeded", "profile": "researcher", "stdout": "done"}
    invoke_hermes = Mock(return_value=expected)

    result = HermesFreeAdapter(invoke_hermes=invoke_hermes).invoke(
        "researcher", "do research", timeout_seconds=300, session_id="session-1"
    )

    assert result is expected
    invoke_hermes.assert_called_once_with(
        "researcher",
        "do research",
        timeout_seconds=300,
        model="free-model",
        provider="free-provider",
        cwd=None,
        session_id="session-1",
    )


def test_default_constructor_uses_live_lookup(monkeypatch):
    monkeypatch.setenv("CORTXT_FREE_MODEL", "free-model")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "free-provider")
    expected = {"status": "succeeded", "profile": "researcher"}

    with patch("routing.hermes_invoker.invoke_hermes", return_value=expected) as invoke_hermes:
        result = HermesFreeAdapter().invoke(
            "researcher", "do research", timeout_seconds=300
        )

    assert result is expected
    invoke_hermes.assert_called_once_with(
        "researcher",
        "do research",
        timeout_seconds=300,
        model="free-model",
        provider="free-provider",
        cwd=None,
        session_id=None,
    )


def test_invoke_propagates_hermes_invocation_error(monkeypatch):
    monkeypatch.setenv("CORTXT_FREE_MODEL", "free-model")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "free-provider")
    invoke_hermes = Mock(side_effect=HermesInvocationError("could not start hermes"))

    with pytest.raises(HermesInvocationError, match="could not start hermes"):
        HermesFreeAdapter(invoke_hermes=invoke_hermes).invoke(
            "researcher", "do research", timeout_seconds=300
        )


def test_explicit_injection_takes_priority_over_live_lookup(monkeypatch):
    monkeypatch.setenv("CORTXT_FREE_MODEL", "free-model")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "free-provider")
    explicit = Mock(return_value={"status": "succeeded"})

    with patch("routing.hermes_invoker.invoke_hermes") as live_lookup:
        result = HermesFreeAdapter(invoke_hermes=explicit).invoke(
            "researcher", "do research", timeout_seconds=300
        )

    assert result == {"status": "succeeded"}
    explicit.assert_called_once()
    live_lookup.assert_not_called()
