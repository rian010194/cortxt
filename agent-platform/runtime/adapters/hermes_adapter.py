"""Wraps routing.hermes_invoker.invoke_hermes as an EngineAdapter (ADR-026
point 3: "befintlig invocation-kod paketeras om, skrivs inte om" -- existing
invocation code is repackaged, not rewritten. This class adds no logic
beyond the delegation itself; invoke_hermes's tested subprocess behavior,
including HermesInvocationError, passes through unchanged.

The default path resolves routing.hermes_invoker.invoke_hermes by live
module-attribute lookup at call time, not by binding the function object as
a constructor default -- a default-argument expression is evaluated once,
at class-definition time, and freezing it here would make
unittest.mock.patch("routing.hermes_invoker.invoke_hermes", ...) unable to
intercept calls made through HermesAdapter's bare default (a real
regression found in agent-platform/tests/cli/test_dispatch.py, a
pre-existing suite that patches exactly that target around real
cli.unified_cli.main([...]) calls). Explicit injection
(HermesAdapter(invoke_hermes=fake_fn)) is unaffected by this and still
takes priority -- it is only the "no argument given" path that now does a
live lookup instead of a frozen one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable
import routing.hermes_invoker as _hermes_invoker_module


class HermesAdapter:
    def __init__(self, invoke_hermes: Callable | None = None) -> None:
        self._invoke_hermes = invoke_hermes

    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
        cwd: Path | None = None,
        session_id: str | None = None,
    ) -> dict:
        invoke_fn = self._invoke_hermes if self._invoke_hermes is not None else _hermes_invoker_module.invoke_hermes
        return invoke_fn(
            profile, prompt, timeout_seconds=timeout_seconds, model=model,
            provider=provider, cwd=cwd, session_id=session_id,
        )
