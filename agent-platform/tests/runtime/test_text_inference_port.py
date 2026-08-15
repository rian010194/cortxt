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


def test_invoke_raises_when_backend_package_unavailable(tmp_path):
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    # No monkeypatch: real _call_backend runs, cortxt_resilient_inference is not
    # installed in the default dev/CI environment, so this must fail closed with
    # a clear TextInferenceError, never a silent fabricated response.
    with pytest.raises(TextInferenceError) as exc:
        port.invoke("classify this", output_schema={"type": "object"})
    assert "unavailable" in str(exc.value).lower()
