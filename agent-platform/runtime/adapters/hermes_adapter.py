"""Wraps routing.hermes_invoker.invoke_hermes as an EngineAdapter (ADR-026
point 3: "befintlig invocation-kod paketeras om, skrivs inte om" -- existing
invocation code is repackaged, not rewritten. This class adds no logic
beyond the delegation itself; invoke_hermes's tested subprocess behavior,
including HermesInvocationError, passes through unchanged."""
from __future__ import annotations

from typing import Callable
from routing.hermes_invoker import invoke_hermes as _default_invoke_hermes


class HermesAdapter:
    def __init__(self, invoke_hermes: Callable = _default_invoke_hermes) -> None:
        self._invoke_hermes = invoke_hermes

    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict:
        return self._invoke_hermes(
            profile, prompt, timeout_seconds=timeout_seconds, model=model, provider=provider
        )
