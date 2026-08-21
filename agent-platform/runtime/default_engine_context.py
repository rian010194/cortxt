"""Today's known-good engine wiring (ADR-026/027 v1: exactly one provider
per engine_id). Kept separate from engine_registry.py so that module never
has to import a specific adapter -- adding a new adapter means editing
this file plus adding the adapter file, not touching the registry
mechanics."""
from __future__ import annotations

from runtime.adapters.claude_adapter import ClaudeAdapter
from runtime.adapters.codex_adapter import CodexAdapter
from runtime.adapters.dsh_adapter import DshAdapter
from runtime.adapters.hermes_adapter import HermesAdapter
from runtime.engine_registry import EngineContext


def build_default_engine_context() -> EngineContext:
    context = EngineContext()
    context.register("hermes", HermesAdapter())
    context.register("codex", CodexAdapter())
    context.register("claude", ClaudeAdapter())
    context.register("dsh", DshAdapter())
    return context
