import pytest

from widget_contract.llm_client import LLMCallError, generate_text


def test_generate_text_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("CORTXT_WIDGET_GEN_MODEL", raising=False)
    monkeypatch.delenv("CORTXT_INFERENCE_URL", raising=False)
    monkeypatch.delenv("CORTXT_INFERENCE_API_KEY", raising=False)
    with pytest.raises(LLMCallError, match="not configured"):
        generate_text("hello")


def test_generate_text_returns_assistant_content(monkeypatch):
    monkeypatch.setenv("CORTXT_WIDGET_GEN_MODEL", "test-model")
    monkeypatch.setenv("CORTXT_INFERENCE_URL", "https://example.invalid")
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "test-key")

    def fake_execute(request, adapters):
        assert request["routes"][0]["model"] == "test-model"
        assert request["idempotency"] == "read_only"
        return {
            "task_id": request["task_id"], "status": "succeeded",
            "selected_route_id": "l0-default", "terminal_reason": "completed",
            "attempts": [], "response": {"role": "assistant", "content": "  hi there  "},
        }

    import widget_contract.llm_client as mod
    monkeypatch.setattr(mod, "_execute", fake_execute)
    assert generate_text("hello") == "hi there"


def test_generate_text_raises_on_blocked_outcome(monkeypatch):
    monkeypatch.setenv("CORTXT_WIDGET_GEN_MODEL", "test-model")
    monkeypatch.setenv("CORTXT_INFERENCE_URL", "https://example.invalid")
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "test-key")

    def fake_execute(request, adapters):
        return {"task_id": request["task_id"], "status": "blocked",
                "selected_route_id": None, "terminal_reason": "attempt_budget_exhausted",
                "attempts": []}

    import widget_contract.llm_client as mod
    monkeypatch.setattr(mod, "_execute", fake_execute)
    with pytest.raises(LLMCallError, match="attempt_budget_exhausted"):
        generate_text("hello")
