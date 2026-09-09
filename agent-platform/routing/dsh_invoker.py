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

import sys
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


def _close_runtime_quietly(harness, exc_info=None) -> BaseException | None:
    """Release a runtime, and return what releasing it raised.

    Closing is not allowed to decide, mask, or replace an outcome. Three
    callers need that, for three different reasons:

    * a launch that failed after spawning the subprocess -- the
      `DshInvocationError` about the launch is the useful diagnosis, and a
      second error from cleaning up after it is not;
    * an exception this module does not classify -- masking a KeyboardInterrupt
      with an `OSError` from `proc.wait()` loses the thing the operator did;
    * a completed run -- whose status is already established, and which must
      never be re-reported as a runtime that was never there.

    `exc_info=None` means "closing after nothing was entered": `close()` is
    called directly, since `__exit__` on a context manager that never entered
    is not the SDK's contract. Otherwise `__exit__` receives the given triple,
    exactly as `with` would have delivered it. Its return value is deliberately
    ignored: a harness that suppressed an exception would otherwise leave this
    function with no outcome to return.
    """
    try:
        if exc_info is None:
            close = getattr(harness, "close", None)
            if close is not None:
                close()
        else:
            harness.__exit__(*exc_info)
    except BaseException as error:  # noqa: BLE001 - reported, never raised from here
        return error
    return None


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
        stderr: a short diagnostic on failure, "" otherwise -- plus a note on
            any outcome whose runtime would not close cleanly, which is a fact
            about the host and never changes the status
        elapsed_seconds: wall-clock time for the call
        session_id: the SDK's session id (fresh or resumed), or the input
            session_id echoed back when a resumed call failed
        finish_reason: the SDK RunResult.finish_reason, or None

    Raises DshInvocationError if the SDK itself could not be started
    (not installed, runtime binary missing, etc.) -- that's an environment
    problem, not a normal dispatch outcome. "Started" covers both building the
    harness and entering it: the runtime subprocess is spawned by `__enter__`,
    so a machine with no carrier fails there, after a perfectly successful
    construction. A worker that started and then failed or timed out is a
    result, and is returned as one.
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

    # Starting the runtime and running the worker are two different events with
    # two different meanings, so they are separated here (#531).
    #
    # `DeepSeekHarness(...)` only builds a config object -- the JSON-RPC runtime
    # subprocess is spawned by `__enter__`. An environment with no runtime to
    # spawn therefore constructs the harness successfully and fails on entry,
    # and a single `try` around `with harness:` caught that and returned it as
    # an ordinary `status: "failed"`, which `DshWorkerAdapter` maps to
    # `worker_nonzero_exit`. That is not a cosmetic mislabel:
    # `worker_nonzero_exit` asserts the mandate was attempted, so an operator
    # reading it goes looking for the worker's output instead of at the host.
    #
    # Entering by hand rather than with `with`, because the two guarantees the
    # statement gives are not the ones this function needs. See `_close_runtime`
    # for the closing rules and why an outcome is never reclassified by them.
    try:
        harness.__enter__()  # type: ignore[attr-defined]
    except Exception as error:  # noqa: BLE001 - launch failure is an environment problem
        # `start()` is `Popen` followed by a JSON-RPC handshake, so a handshake
        # that fails leaves a live subprocess behind. `close()` is idempotent
        # (it returns immediately when nothing was spawned) and is the SDK's
        # documented way to reap it, so it is safe on both halves of that split.
        # `__exit__` is not called: a context manager whose `__enter__` raised
        # was never entered.
        _close_runtime_quietly(harness)
        raise DshInvocationError(
            f"could not start DSH runtime: {type(error).__name__}: {error}"
        ) from error

    # Past this point a worker did start, so everything below is a *result* and
    # is reported as a status, never raised.
    outcome: dict
    worker_error: BaseException | None = None
    try:
        result = harness.run(prompt, session_id=session_id)  # type: ignore[attr-defined]
    except TimeoutError as error:
        worker_error = error
        outcome = {
            "status": "timed_out",
            "stdout": "",
            "stderr": f"dsh did not complete within {timeout_seconds}s",
            "elapsed_seconds": time.time() - started,
            "session_id": session_id,
            "finish_reason": None,
        }
    except Exception as error:  # noqa: BLE001 - SDK HarnessError subclasses land here
        worker_error = error
        outcome = {
            "status": "failed",
            "stdout": "",
            "stderr": f"{type(error).__name__}: {error}",
            "elapsed_seconds": time.time() - started,
            "session_id": session_id,
            "finish_reason": None,
        }
    except BaseException:
        # Not ours to classify -- a KeyboardInterrupt is the realistic case.
        # The runtime is still told exactly what is propagating, as `with`
        # would have told it, and the original exception continues.
        _close_runtime_quietly(harness, sys.exc_info())
        raise
    else:
        outcome = {
            "status": "succeeded",
            "stdout": getattr(result, "final_response", ""),
            "stderr": "",
            "elapsed_seconds": time.time() - started,
            "session_id": getattr(result, "session_id", session_id),
            "finish_reason": getattr(result, "finish_reason", None),
        }

    exc_info = (
        (type(worker_error), worker_error, worker_error.__traceback__)
        if worker_error is not None
        else (None, None, None)
    )
    close_error = _close_runtime_quietly(harness, exc_info)
    if close_error is not None:
        # The worker's outcome is already established and a host-side cleanup
        # fault does not change it. Letting this propagate would reach
        # `DshWorkerAdapter`'s exception arm and report `runtime_unavailable`
        # for a worker that ran -- the exact inversion this change exists to
        # remove. It is recorded rather than swallowed, because a runtime that
        # will not close is a real fact about the host.
        note = f"runtime did not close cleanly: {type(close_error).__name__}: {close_error}"
        joined = outcome["stderr"] + "\n" + note
        outcome["stderr"] = joined if outcome["stderr"] else note

    return outcome
