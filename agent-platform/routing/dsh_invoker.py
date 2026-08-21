"""Minimal, tested wrapper around the DeepSeek Harness Python SDK.

Part of the DSH-integration experiment (lab/dsh-integration/README.md):
`routing/engine_manifest.route()` may pick "dsh" as an engine_id, but
picking isn't invoking. This is the invocation, self-contained in
`agent-platform/`, mirroring `routing/hermes_invoker.py`'s role for Hermes.

Deliberately narrow: one run, one result, no retry/backoff logic (that's
the caller's decision), no run tracking (the caller wires this into
session_state itself, same pattern as everything else `cortxt` does).

The injectable seam is a *harness factory*, not a run_subprocess: the DSH
Python SDK (`deepseek_harness.DeepSeekHarness`) is a library that owns its
own lazily-started JSON-RPC subprocess internally, so there is no argv we
build and no subprocess we own to pass a fake run_subprocess to. The
default factory lazy-imports the SDK (a missing SDK surfaces as
`DshInvocationError`, never as an ImportError at module import time) and
constructs a `DeepSeekHarness` from a `DeepSeekHarnessConfig`; tests inject
a fake factory returning a run()-capable object and never touch a real
runtime, model endpoint, or API key.

Timeout model: the SDK's `request_timeout_seconds` is threaded through to
the runtime (each JSON-RPC request is bounded); a `TimeoutError` from the
SDK maps to the `timed_out` status. A hard wall-clock kill of the whole
run is not implemented here -- the runtime subprocess is owned by the SDK,
not by this module, and the daemon's own lease/heartbeat layer is the
caller-side deadline.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

# A factory returns an object usable as a context manager with a
# run(input: str, session_id: str | None = None) -> RunResult method.
HarnessFactory = Callable[[dict], object]


class DshInvocationError(RuntimeError):
    """Raised when the DSH SDK itself could not be started (not installed,
    runtime binary missing, or another environment error before any run
    began) -- distinct from a normal failed/timed-out response, which is a
    regular return value."""


def _default_harness_factory(config: dict) -> object:
    """Lazily import and construct a DeepSeekHarness from the SDK.

    Kept as a plain function (not a class attribute default) so tests can
    inject a fake factory, and so an uninstalled SDK raises
    DshInvocationError at call time rather than breaking module import.
    """
    try:
        from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    except ImportError as error:
        raise DshInvocationError(
            "deepseek-harness-sdk is not installed; "
            "install it or inject a harness_factory"
        ) from error
    return DeepSeekHarness(DeepSeekHarnessConfig(**config))


def invoke_dsh(
    prompt: str,
    *,
    timeout_seconds: int,
    model: str | None = None,
    provider: str | None = None,
    cwd: Path | None = None,
    session_id: str | None = None,
    harness_factory: HarnessFactory | None = None,
) -> dict:
    """Run a one-shot prompt through the DSH Python SDK and return a
    structured result.

    Returns a dict with:
        status: "succeeded" | "failed" | "timed_out"
        stdout: the SDK RunResult.final_response on success, "" otherwise
        stderr: a short diagnostic on failure, "" otherwise
        elapsed_seconds: wall-clock time for the call
        session_id: the SDK's session id (fresh or resumed), or the input
            session_id echoed back when a resumed call failed
        finish_reason: the SDK RunResult.finish_reason, or None

    Raises DshInvocationError if the SDK itself could not be started
    (not installed, runtime binary missing, etc.) -- that's an environment
    problem, not a normal dispatch outcome.
    """
    if not prompt.strip():
        raise ValueError("prompt must be a non-empty string")

    factory = harness_factory if harness_factory is not None else _default_harness_factory
    config: dict = {
        "provider": provider or "deepseek-official",
        "model": model or "deepseek-v4-flash",
        "request_timeout_seconds": timeout_seconds,
    }
    if cwd is not None:
        config["cwd"] = str(cwd)

    started = time.time()
    try:
        harness = factory(config)
    except DshInvocationError:
        raise
    except (ImportError, OSError) as error:
        raise DshInvocationError(f"could not start DSH harness: {error}") from error
    except Exception as error:  # noqa: BLE001 - any factory failure is an environment problem
        raise DshInvocationError(f"could not start DSH harness: {type(error).__name__}: {error}") from error

    try:
        with harness:  # type: ignore[attr-defined]
            result = harness.run(prompt, session_id=session_id)  # type: ignore[attr-defined]
    except TimeoutError:
        return {
            "status": "timed_out",
            "stdout": "",
            "stderr": f"dsh did not complete within {timeout_seconds}s",
            "elapsed_seconds": time.time() - started,
            "session_id": session_id,
            "finish_reason": None,
        }
    except Exception as error:  # noqa: BLE001 - SDK HarnessError subclasses land here
        return {
            "status": "failed",
            "stdout": "",
            "stderr": f"{type(error).__name__}: {error}",
            "elapsed_seconds": time.time() - started,
            "session_id": session_id,
            "finish_reason": None,
        }

    return {
        "status": "succeeded",
        "stdout": getattr(result, "final_response", ""),
        "stderr": "",
        "elapsed_seconds": time.time() - started,
        "session_id": getattr(result, "session_id", session_id),
        "finish_reason": getattr(result, "finish_reason", None),
    }
