"""Today's one known-good engine wiring (ADR-026/027 v1: exactly one
provider per engine_id, HermesAdapter is the only adapter that exists).
Kept separate from engine_registry.py so that module never has to import a
specific adapter -- adding a second adapter later means editing this file
plus adding the adapter file, not touching the registry mechanics."""
from __future__ import annotations

from runtime.adapters.hermes_adapter import HermesAdapter
from runtime.engine_registry import EngineContext


def build_default_engine_context() -> EngineContext:
    context = EngineContext()
    context.register("hermes", HermesAdapter())
    return context
