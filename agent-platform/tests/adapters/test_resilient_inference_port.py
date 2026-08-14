"""Unit tests for ResilientInferencePort (Delmål 1 AC).

These tests mock the provider-neutral ``execute`` backend so they are hermetic and cost 0
model calls. They verify request-shape, strict integer parsing, and fail-closed behavior.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("cortxt_resilient_inference")
pytest.importorskip("adapters.inference")

from adapters.inference import InferenceExecutionError, ResilientInferencePort  # noqa: E402


def _captured_request():
    """Container for the request dict passed to the mocked execute."""
    return {}


@pytest.fixture
def port(monkeypatch):
    monkeypatch.setenv("CORTXT_INFERENCE_URL", "https://inference.example/v1")
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("CORTXT_INFERENCE_MODEL", "test-model")
    return ResilientInferencePort()


def _install_mock_execute(monkeypatch, envelope):
    import adapters.inference.resilient_inference_port as m

    captured = {}

    def fake_execute(request, adapters):
        captured["request"] = request
        captured["adapters"] = adapters
        return envelope

    monkeypatch.setattr(m, "_resilient_execute", fake_execute)
    return captured


def test_invoke_returns_int_for_simple_content(port, monkeypatch):
    captured = _install_mock_execute(
        monkeypatch,
        {"status": "succeeded", "response": {"content": "7"}, "terminal_reason": "completed"},
    )
    assert port.invoke("7") == 7
    req = captured["request"]
    assert req["task_id"]
    assert req["idempotency"] == "read_only"
    assert req["routes"][0]["route_id"] == "l0-default"
    assert req["routes"][0]["policy_eligible"] is True


def test_invoke_fail_closed_on_non_succeeded(port, monkeypatch):
    _install_mock_execute(
        monkeypatch,
        {"status": "blocked", "terminal_reason": "attempt_budget_exhausted"},
    )
    with pytest.raises(InferenceExecutionError):
        port.invoke("7")


def test_invoke_fail_closed_on_non_numeric(port, monkeypatch):
    _install_mock_execute(
        monkeypatch,
        {"status": "succeeded", "response": {"content": "may contain letters"}},
    )
    with pytest.raises(InferenceExecutionError):
        port.invoke("7")


def test_available_false_without_env(monkeypatch):
    for var in ("CORTXT_INFERENCE_URL", "CORTXT_INFERENCE_API_KEY", "CORTXT_INFERENCE_MODEL"):
        monkeypatch.delenv(var, raising=False)
    port = ResilientInferencePort()
    assert not port.available()
    with pytest.raises(InferenceExecutionError):
        port.invoke("7")


def test_no_credentials_in_request(port, monkeypatch):
    """The request must carry api_key_env NAME, not the secret value."""
    captured = _install_mock_execute(
        monkeypatch,
        {"status": "succeeded", "response": {"content": "3"}},
    )
    port.invoke("3")
    req = captured["request"]
    assert req["routes"][0]["api_key_env"] == "CORTXT_INFERENCE_API_KEY"
    assert "test-key" not in _serialize(req)


def _serialize(obj):
    import json

    return json.dumps(obj)
