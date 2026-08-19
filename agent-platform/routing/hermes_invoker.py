"""Minimal, tested subprocess wrapper around the Hermes CLI's one-shot mode.

Part of Orchestrator Dispatch v0.1 (`.hermes/plans/2026-08-19-orchestrator-dispatch-v01.md`):
`routing/engine_manifest.route()` picks "hermes" as an engine_id, but picking
isn't invoking. This is the invocation, self-contained in `agent-platform/`
rather than reaching into `scripts/worker_adapters.py`'s HermesAdapter (a
different package, not importable cleanly from here, and shaped around
`scripts/dispatcher.py`'s Run/claim lifecycle this module doesn't need).

Deliberately narrow: one call, one result, no retry/backoff logic (that's
the caller's decision, informed by the ADR-022 manifest's reliability_class),
no run tracking (the caller wires this into session_state itself, same
pattern as everything else `cortxt` does).
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable


class HermesInvocationError(RuntimeError):
    """Raised when the hermes CLI itself could not be started (not found,
    not executable, or another OSError before it ever ran) -- distinct from
    a normal failed/timed-out response, which is a regular return value."""


def invoke_hermes(
    profile: str,
    prompt: str,
    *,
    timeout_seconds: int,
    run_subprocess: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    model: str | None = None,
    provider: str | None = None,
    cwd: Path | None = None,
) -> dict:
    """Run `hermes -p <profile> -z <prompt>` (with optional -m/--provider
    overrides) and return a structured result.

    Returns a dict with:
        status: "succeeded" | "failed" | "timed_out"
        profile: the profile passed in
        stdout / stderr: captured text
        elapsed_seconds: wall-clock time for the call

    Raises HermesInvocationError if the hermes executable itself could not
    be started (missing from PATH, not executable, etc.) -- that's an
    environment problem, not a normal dispatch outcome.
    """
    if not prompt.strip():
        raise ValueError("prompt must be a non-empty string")

    argv = ["hermes", "-p", profile, "-z", prompt]
    if model:
        argv += ["-m", model]
    if provider:
        argv += ["--provider", provider]

    started = time.time()
    try:
        proc = run_subprocess(
            argv, capture_output=True, text=True, timeout=timeout_seconds,
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timed_out",
            "profile": profile,
            "stdout": "",
            "stderr": f"hermes did not complete within {timeout_seconds}s",
            "elapsed_seconds": time.time() - started,
        }
    except OSError as error:
        raise HermesInvocationError(f"could not start hermes: {error}") from error

    return {
        "status": "succeeded" if proc.returncode == 0 else "failed",
        "profile": profile,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "elapsed_seconds": time.time() - started,
    }
