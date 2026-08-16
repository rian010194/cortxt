"""TextInferencePort: real-inference gate + provider-policy check, no schema
validation here (that is verify_against_schema's job, called by agent_loop).
"""
from __future__ import annotations

from pathlib import Path
import pytest
from adapters.inference.budget_gate import BudgetExhausted, BudgetGate
from runtime.text_inference_port import TextInferenceError, TextInferencePort


def _gate(tmp_path, max_calls):
    return BudgetGate(max_calls=max_calls, db_path=tmp_path / "spend.db")


def test_invoke_denied_by_provider_policy(tmp_path):
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": False, "provider_id": "untrusted"},
        data_class="L2",
    )
    with pytest.raises(TextInferenceError) as exc:
        port.invoke("classify this", output_schema={"type": "object"})
    assert "policy" in str(exc.value).lower()


def test_invoke_blocked_by_budget_before_any_backend_call(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        "runtime.text_inference_port.TextInferencePort._call_backend",
        lambda self, prompt, schema: called.append(1) or {"ok": True},
    )
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=0),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    with pytest.raises(BudgetExhausted):
        port.invoke("classify this", output_schema={"type": "object"})
    assert called == []  # backend never reached


def test_invoke_success_returns_parsed_backend_response(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "runtime.text_inference_port.TextInferencePort._call_backend",
        lambda self, prompt, schema: {"classification": "high_risk"},
    )
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    result = port.invoke("classify this", output_schema={"type": "object"})
    assert result == {"classification": "high_risk"}


def test_invoke_raises_when_backend_package_unavailable(tmp_path, monkeypatch):
    # Force the "package not installed" branch explicitly rather than relying on
    # cortxt_resilient_inference happening to be absent from this environment --
    # it may be installed locally for real_inference testing even though CI never
    # installs it, so the test must not depend on ambient environment state.
    monkeypatch.setattr("runtime.text_inference_port._RI_AVAILABLE", False)
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    with pytest.raises(TextInferenceError) as exc:
        port.invoke("classify this", output_schema={"type": "object"})
    assert "unavailable" in str(exc.value).lower()


def test_invoke_raises_when_backend_env_not_configured(tmp_path, monkeypatch):
    # Package present, but CORTXT_INFERENCE_URL/API_KEY unset -- must fail closed
    # with a clear "not configured" error, not attempt a network call.
    monkeypatch.setattr("runtime.text_inference_port._RI_AVAILABLE", True)
    monkeypatch.delenv("CORTXT_INFERENCE_URL", raising=False)
    monkeypatch.delenv("CORTXT_INFERENCE_API_KEY", raising=False)
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    with pytest.raises(TextInferenceError) as exc:
        port.invoke("classify this", output_schema={"type": "object"})
    assert "not configured" in str(exc.value).lower()


def test_call_backend_builds_correct_request_and_parses_json_response(tmp_path, monkeypatch):
    # Exercises the real _call_backend request/response wiring (the bug this test
    # would have caught: _HttpAdapter() was called with no messages, and execute()
    # was called with the wrong keyword arguments entirely).
    monkeypatch.setattr("runtime.text_inference_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_INFERENCE_URL", "https://inference.example/v1")
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "test-key")

    captured = {}

    class FakeAdapter:
        def __init__(self, messages):
            captured["messages"] = messages

    def fake_execute(request, adapters):
        captured["request"] = request
        captured["adapters"] = adapters
        return {
            "status": "succeeded",
            "response": {"role": "assistant", "content": '{"classification": "high_risk"}'},
        }

    monkeypatch.setattr("runtime.text_inference_port._HttpAdapter", FakeAdapter)
    monkeypatch.setattr("runtime.text_inference_port._resilient_execute", fake_execute)

    port = TextInferencePort(
        model="deepseek-v4-flash-0731",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    result = port.invoke("classify this system", output_schema={"type": "object"})

    assert result == {"classification": "high_risk"}
    route = captured["request"]["routes"][0]
    assert route["base_url"] == "https://inference.example/v1"
    assert route["model"] == "deepseek-v4-flash-0731"
    assert route["api_key_env"] == "CORTXT_INFERENCE_API_KEY"
    assert "l0-default" in captured["adapters"]
    user_messages = [m for m in captured["messages"] if m["role"] == "user"]
    assert user_messages[0]["content"] == "classify this system"


def test_call_backend_strips_markdown_code_fence_before_parsing_json(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.text_inference_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_INFERENCE_URL", "https://inference.example/v1")
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "test-key")
    monkeypatch.setattr("runtime.text_inference_port._HttpAdapter", lambda messages: object())
    monkeypatch.setattr(
        "runtime.text_inference_port._resilient_execute",
        lambda request, adapters: {
            "status": "succeeded",
            "response": {"role": "assistant", "content": '```json\n{"a": 1}\n```'},
        },
    )
    port = TextInferencePort(
        model="m", budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"}, data_class="L0",
    )
    assert port.invoke("p", output_schema={"type": "object"}) == {"a": 1}


def test_call_backend_raises_when_execute_does_not_succeed(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.text_inference_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_INFERENCE_URL", "https://inference.example/v1")
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "test-key")
    monkeypatch.setattr("runtime.text_inference_port._HttpAdapter", lambda messages: object())
    monkeypatch.setattr(
        "runtime.text_inference_port._resilient_execute",
        lambda request, adapters: {"status": "blocked", "terminal_reason": "provider_unavailable"},
    )
    port = TextInferencePort(
        model="m", budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"}, data_class="L0",
    )
    with pytest.raises(TextInferenceError) as exc:
        port.invoke("p", output_schema={"type": "object"})
    assert "did not succeed" in str(exc.value).lower()
