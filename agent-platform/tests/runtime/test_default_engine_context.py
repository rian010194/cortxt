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


def test_codex_has_a_provider():
    context = build_default_engine_context()
    assert context.get("codex").has_provider is True


def test_claude_has_a_provider():
    context = build_default_engine_context()
    assert context.get("claude").has_provider is True


def test_dsh_has_a_provider():
    # DSH-integration experiment (lab/dsh-integration): the DSH SDK adapter
    # is registered in the default engine context like hermes/codex/claude,
    # so `cortxt orchestrator --engine dsh` can invoke it without touching
    # route()'s selection (ADR-026: registration and selection are separate
    # layers). route() now picks dsh for research/background-task via its
    # DEFAULT_MANIFESTS entry (operator decision 2026-08-21).
    context = build_default_engine_context()
    assert context.get("dsh").has_provider is True
