"""Wraps routing.dsh_invoker.invoke_dsh as an EngineAdapter (ADR-026
point 3: "befintlig invocation-kod paketeras om, skrivs inte om" -- existing
invocation code is repackaged, not rewritten. This class adds no logic
beyond the delegation itself; invoke_dsh's tested behavior, including
DshInvocationError, passes through unchanged.

The default path resolves routing.dsh_invoker.invoke_dsh by live
module-attribute lookup at call time, not by binding the function object as
a constructor default -- a default-argument expression is evaluated once,
at class-definition time, and freezing it here would make
unittest.mock.patch("routing.dsh_invoker.invoke_dsh", ...) unable to
intercept calls made through DshAdapter's bare default (the same regression
hermes_adapter.py's docstring documents). Explicit injection
(DshAdapter(invoke_dsh=fake_fn)) is unaffected by this and still takes
priority -- it is only the "no argument given" path that now does a live
lookup instead of a frozen one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable
import routing.dsh_invoker as _dsh_invoker_module


class DshAdapter:
    def __init__(self, invoke_dsh: Callable | None = None) -> None:
        self._invoke_dsh = invoke_dsh

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
        # profile is accepted for EngineAdapter-protocol symmetry but is
        # meaningless for the DSH SDK (provider/model carry routing, not a
        # named Cortxt worker profile); invoke_dsh has no profile parameter.
        invoke_fn = self._invoke_dsh if self._invoke_dsh is not None else _dsh_invoker_module.invoke_dsh
        return invoke_fn(
            prompt, timeout_seconds=timeout_seconds, model=model,
            provider=provider, cwd=cwd, session_id=session_id,
        )
