from __future__ import annotations

from runtime.default_engine_context import build_default_engine_context


def test_hermes_has_a_provider():
    context = build_default_engine_context()
    assert context.get("hermes").has_provider is True


def test_claude_direct_has_no_provider():
    context = build_default_engine_context()
    assert context.get("claude-direct").has_provider is False


def test_each_call_returns_an_independent_context():
    first = build_default_engine_context()
    second = build_default_engine_context()
    assert first is not second
    assert first.get("hermes") is not second.get("hermes")
