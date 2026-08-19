"""The invocation contract every engine adapter implements (ADR-026).

route() (routing/engine_manifest.py) decides *which* engine_id wins for a
task -- picking isn't invoking, per hermes_invoker.py's own docstring. This
Protocol is the "invoking" half: whatever object a broker holds for a given
engine_id, it can call .invoke(...) on it without knowing which concrete
engine it's talking to.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class EngineAdapter(Protocol):
    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
        cwd: Path | None = None,
    ) -> dict:
        ...
