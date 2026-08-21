"""Tests for runtime/adapters/dsh_adapter.py.

Mirrors the HermesAdapter test discipline: the adapter adds no logic beyond
the delegation itself, so tests verify (1) it implements the EngineAdapter
protocol, (2) it forwards every keyword unchanged to invoke_dsh, and
(3) the default path resolves invoke_dsh by live module-attribute lookup at
call time -- not as a frozen constructor default -- so
unittest.mock.patch("routing.dsh_invoker.invoke_dsh", ...) can intercept
calls made through the adapter's bare default (the exact regression
hermes_adapter.py's docstring documents for test_dispatch.py).
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from runtime.adapters.dsh_adapter import DshAdapter
from runtime.engine_adapter import EngineAdapter


def test_dsh_adapter_is_an_engine_adapter():
    assert isinstance(DshAdapter(), EngineAdapter)


def test_dsh_adapter_forwards_all_keywords_to_invoke_dsh():
    captured = {}

    def fake_invoke_dsh(prompt, *, timeout_seconds, model=None, provider=None,
                        cwd=None, session_id=None):
        captured.update(prompt=prompt, timeout_seconds=timeout_seconds, model=model,
                        provider=provider, cwd=cwd, session_id=session_id)
        return {"status": "succeeded", "stdout": "ok", "session_id": "sess-1"}

    adapter = DshAdapter(invoke_dsh=fake_invoke_dsh)
    result = adapter.invoke(
        "researcher", "do the thing", timeout_seconds=60,
        model="deepseek-v4-flash-0731", provider="nous",
        cwd=Path("C:/work"), session_id="sess-1",
    )

    assert captured == {
        "prompt": "do the thing",
        "timeout_seconds": 60,
        "model": "deepseek-v4-flash-0731",
        "provider": "nous",
        "cwd": Path("C:/work"),
        "session_id": "sess-1",
    }
    assert result["status"] == "succeeded"


def test_dsh_adapter_default_path_calls_live_module_attribute():
    # The no-argument path must resolve routing.dsh_invoker.invoke_dsh by
    # live lookup at call time, exactly like HermesAdapter -- a frozen
    # default would make unittest.mock.patch unable to intercept real
    # cli.unified_cli.main([...]) calls.
    with mock.patch("routing.dsh_invoker.invoke_dsh", return_value={"status": "succeeded"}) as mocked:
        result = DshAdapter().invoke("researcher", "do the thing", timeout_seconds=60)

    mocked.assert_called_once_with(
        "do the thing", timeout_seconds=60, model=None, provider=None, cwd=None, session_id=None,
    )
    assert result["status"] == "succeeded"


def test_dsh_adapter_explicit_injection_takes_priority_over_live_lookup():
    def fake_invoke_dsh(prompt, *, timeout_seconds, model=None, provider=None,
                        cwd=None, session_id=None):
        return {"status": "timed_out", "stdout": ""}

    with mock.patch("routing.dsh_invoker.invoke_dsh", return_value={"status": "succeeded"}):
        result = DshAdapter(invoke_dsh=fake_invoke_dsh).invoke("researcher", "do it", timeout_seconds=5)

    assert result["status"] == "timed_out"  # injected fake wins, live lookup untouched


def test_dsh_adapter_passes_timeout_seconds_as_keyword_only():
    # Regression guard: timeout_seconds must arrive as a keyword argument
    # (the EngineAdapter protocol's shape), never positionally.
    captured = {}

    def fake_invoke_dsh(prompt, **kwargs):
        captured.update(kwargs)
        return {"status": "succeeded", "stdout": "ok"}

    DshAdapter(invoke_dsh=fake_invoke_dsh).invoke("researcher", "do it", timeout_seconds=42)

    assert captured["timeout_seconds"] == 42
