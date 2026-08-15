#!/usr/bin/env python3
"""Worker-invocation adapters for the minimal dispatcher (#122).

Wires scripts/dispatcher.py's claim/run-identity layer to an actual runtime
call. This is the piece PR #128 explicitly left as follow-on scope: claim()
and complete() exist, but nothing yet takes a claimed Run and calls a real
worker.

Design locked in the #122 grilling session (2026-08-15, live with operator):

- Adapter selection is dynamic per `Run.runtime` — a small registry, not a
  hardcoded runtime. `Dispatcher.claim()` already takes `runtime` as a
  caller-supplied string; this module is the only place that maps that
  string to an actual invocation. Matches the repo's vendor/model-
  independent architecture direction.
- Invocation runs in a background thread so `heartbeat`/`sweep_expired` stay
  functional during a long-running call (relevant for #101 T1's resume
  requirement).

Not yet decided (flagged, not solved here): whether the adapter interface
should instead return a future the dispatcher awaits, and which adapter is
implemented second. First concrete adapter: Hermes Researcher.
"""
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from dispatcher import Dispatcher, Run


class WorkerAdapter(Protocol):
    def invoke(self, run: Run, task_prompt: str, timeout_seconds: int) -> dict:
        """Run the worker (the caller backgrounds this call) and return a
        result_envelope dict plus an internal `_status` key the caller pops
        off and passes to Dispatcher.complete(). Must never raise for an
        ordinary worker failure — a failed/timed_out envelope is a normal
        return, not an exception."""
        ...


@dataclass
class HermesAdapter:
    """Invokes a Hermes profile as a one-shot, non-interactive subprocess.

    Matches the pattern already verified end-to-end in
    harness/scripts/dispatch-manual.sh: `hermes -p <profile> -z <prompt>`.

    Cost and usage are reported as `unknown` unless actually measured. This
    is deliberate, not a placeholder to fill in later: #58/#71 recorded that
    a guessed cost (e.g. defaulting to USD 0.00) was a false claim about a
    specific provider/cost regardless of the model actually used. An honest
    `unknown` satisfies dispatch-contract.md ("never silently assume zero");
    a guessed number would not.
    """

    profile: str
    run_subprocess: Callable[..., "subprocess.CompletedProcess[str]"] = field(
        default=subprocess.run
    )

    def invoke(self, run: Run, task_prompt: str, timeout_seconds: int) -> dict:
        started = time.time()
        try:
            proc = self.run_subprocess(
                ["hermes", "-p", self.profile, "-z", task_prompt],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "_status": "timed_out",
                "runtime": "hermes",
                "worker_role": self.profile,
                "model": "unknown (not captured by this adapter)",
                "usage": "unknown (subprocess timed out before completion)",
                "cost": "unknown (not measured)",
                "artifacts": [],
                "evidence": _tail(exc.stdout, 2000),
                "error": {
                    "category": "timeout",
                    "recovery": "retry with a fresh run_id, or raise lease_seconds if the task is legitimately long",
                },
                "_elapsed_seconds": time.time() - started,
            }
        except FileNotFoundError as exc:
            return {
                "_status": "failed",
                "runtime": "hermes",
                "worker_role": self.profile,
                "model": "unknown",
                "usage": "unknown (worker never started)",
                "cost": "unknown (not measured)",
                "artifacts": [],
                "evidence": "",
                "error": {
                    "category": "runtime_unavailable",
                    "recovery": f"hermes CLI not found on PATH: {exc}",
                },
                "_elapsed_seconds": time.time() - started,
            }

        status = "succeeded" if proc.returncode == 0 else "failed"
        error = None
        if status != "succeeded":
            error = {
                "category": "worker_nonzero_exit",
                "recovery": _tail(proc.stderr, 500) or f"hermes exited {proc.returncode}; check hermes logs",
            }
        return {
            "_status": status,
            "runtime": "hermes",
            "worker_role": self.profile,
            "model": "unknown (not captured by this adapter)",
            "usage": "unknown (not captured by this adapter)",
            "cost": "unknown (not measured)",
            "artifacts": [],
            "evidence": _tail(proc.stdout, 4000),
            "error": error,
            "_elapsed_seconds": time.time() - started,
        }


def _tail(text: "str | None", max_chars: int) -> str:
    return (text or "")[-max_chars:]


class UnknownRuntimeError(RuntimeError):
    pass


ADAPTER_REGISTRY: dict[str, WorkerAdapter] = {
    "hermes-researcher": HermesAdapter(profile="researcher"),
}


def register_adapter(runtime: str, adapter: WorkerAdapter) -> None:
    """Add or replace an adapter. Keeps the registry open for extension
    (Pi Builder, hermes-coordinator, ...) without editing call sites."""
    ADAPTER_REGISTRY[runtime] = adapter


def dispatch_async(dispatcher: Dispatcher, run: Run, task_prompt: str) -> threading.Thread:
    """Invoke `run`'s adapter in a background thread, then call
    dispatcher.complete() with the resulting envelope.

    Returns the (already-started) thread so tests can join() it; production
    callers may let it run detached — heartbeat/sweep_expired do not depend
    on this thread.
    """
    adapter = ADAPTER_REGISTRY.get(run.runtime)
    if adapter is None:
        raise UnknownRuntimeError(
            f"no adapter registered for runtime={run.runtime!r} (known: {sorted(ADAPTER_REGISTRY)})"
        )

    def _run() -> None:
        envelope = adapter.invoke(run, task_prompt, timeout_seconds=run.lease_seconds)
        status = envelope.pop("_status")
        envelope.pop("_elapsed_seconds", None)
        dispatcher.complete(run.run_id, status, envelope)

    thread = threading.Thread(target=_run, name=f"worker-{run.run_id}", daemon=True)
    thread.start()
    return thread
