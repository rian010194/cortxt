"""Wraps routing.hermes_invoker.invoke_hermes for the configured free route.

The default path resolves routing.hermes_invoker.invoke_hermes by live
module-attribute lookup at call time, not by binding the function object as
a constructor default. This lets
unittest.mock.patch("routing.hermes_invoker.invoke_hermes", ...) intercept
calls made through HermesFreeAdapter's bare default. Explicit injection
(HermesFreeAdapter(invoke_hermes=fake_fn)) still takes priority.

`model`/`provider` are accepted as keyword arguments for EngineAdapter
protocol compatibility (the dispatch path always passes them), but they are
deliberately ignored: the free route is configured exclusively through
`CORTXT_FREE_MODEL` / `CORTXT_FREE_PROVIDER` env vars, so an explicit CLI
override can never silently switch the free route to a different model or
provider than the operator configured.

Live arm: from ``agent-platform/``, set ``CORTXT_FREE_MODEL``,
``CORTXT_FREE_PROVIDER``, and the Hermes CLI provider key in the environment,
then run ``pytest -m real_inference tests/runtime/adapters/test_hermes_free_live.py``.
Provider keys are environment-only and must never be stored in this repository.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import routing.hermes_invoker as _hermes_invoker_module


class HermesFreeAdapter:
    def __init__(self, invoke_hermes: Callable | None = None) -> None:
        self._invoke_hermes = invoke_hermes

    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,  # noqa: ARG002 - protocol compat, env is authoritative
        provider: str | None = None,  # noqa: ARG002 - protocol compat, env is authoritative
        cwd: Path | None = None,
        session_id: str | None = None,
    ) -> dict:
        model = os.environ.get("CORTXT_FREE_MODEL")
        provider = os.environ.get("CORTXT_FREE_PROVIDER")
        if not model or not provider:
            return {
                "status": "failed",
                "profile": profile,
                "stdout": "",
                "stderr": "free route not configured: set CORTXT_FREE_MODEL and CORTXT_FREE_PROVIDER",
                "elapsed_seconds": 0.0,
                "session_id": None,
            }

        invoke_fn = (
            self._invoke_hermes
            if self._invoke_hermes is not None
            else _hermes_invoker_module.invoke_hermes
        )
        return invoke_fn(
            profile,
            prompt,
            timeout_seconds=timeout_seconds,
            model=model,
            provider=provider,
            cwd=cwd,
            session_id=session_id,
        )
