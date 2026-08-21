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
  requirement). Concurrency safety for that thread's `Dispatcher.complete()`
  call lives in dispatcher.py's `Dispatcher._lock` (RLock).

Not yet decided (flagged, not solved here): whether the adapter interface
should instead return a future the dispatcher awaits, and which adapter is
implemented second. First concrete adapter: Hermes Researcher.
"""
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from dispatcher import Dispatcher, Run

# Local-only run logs (raw worker stdout/stderr never leaves this machine).
# .hermes/ is gitignored repo-wide; this reuses that existing convention
# rather than inventing a new one.
RUN_LOG_DIR = Path(".hermes") / "dispatch" / "runs"


class WorkerAdapter(Protocol):
    def invoke(self, run: Run, task_prompt: str, timeout_seconds: int) -> dict:
        """Run the worker (the caller backgrounds this call) and return a
        result_envelope dict plus an internal `_status` key the caller pops
        off and passes to Dispatcher.complete(). Must never raise for an
        ordinary worker failure — a failed/timed_out envelope is a normal
        return, not an exception. `dispatch_async` treats a raise from this
        method as a backstop case, not the expected path."""
        ...


@dataclass
class HermesAdapter:
    """Invokes a Hermes profile as a one-shot, non-interactive subprocess.

    Matches the pattern already verified end-to-end in
    the (unpublished) local manual-dispatch script: `hermes -p <profile> -z <prompt>`.

    Cost and usage are reported as `unknown` unless actually measured. This
    is deliberate, not a placeholder to fill in later: #58/#71 recorded that
    a guessed cost (e.g. defaulting to USD 0.00) was a false claim about a
    specific provider/cost regardless of the model actually used. An honest
    `unknown` satisfies dispatch-contract.md ("never silently assume zero");
    a guessed number would not.

    No field in the returned envelope carries the worker's raw stdout/stderr
    -- not `evidence`, and not `error.recovery` either (an earlier version of
    this adapter fixed the former and left the latter leaking up to 500 raw
    stderr characters into the same GitHub-posted envelope; both are now
    covered). AGENTS.md and dispatch-contract.md both forbid putting "raw
    reasoning" or "unrestricted logs" in GitHub, and the worker's stdout/
    stderr here is literally a Hermes model's response transcript. Raw
    output is written to a local, gitignored run log (RUN_LOG_DIR) instead;
    every envelope field is a short, bounded, structured summary, and
    `artifacts` carries the local log path (a content-free reference)
    rather than the content itself.
    """

    profile: str
    run_subprocess: Callable[..., "subprocess.CompletedProcess[str]"] = field(
        default=subprocess.run
    )
    log_dir: Path = field(default=RUN_LOG_DIR)

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
            log_path = self._write_run_log(run, stdout=exc.stdout, stderr=exc.stderr)
            return {
                "_status": "timed_out",
                "runtime": "hermes",
                "worker_role": self.profile,
                "model": "unknown (not captured by this adapter)",
                "usage": "unknown (subprocess timed out before completion)",
                "cost": "unknown (not measured)",
                "artifacts": [log_path] if log_path else [],
                "evidence": f"worker timed out after {timeout_seconds}s; no completion",
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
                "evidence": "worker never started: hermes CLI not found on PATH",
                "error": {
                    "category": "runtime_unavailable",
                    "recovery": f"hermes CLI not found on PATH: {exc}",
                },
                "_elapsed_seconds": time.time() - started,
            }
        except (OSError, UnicodeDecodeError) as exc:
            # Covers PermissionError (hermes resolves but isn't executable),
            # other OSError subtypes (fork failure, resource limits in a
            # sandboxed/containerized runner), and UnicodeDecodeError (worker
            # stdout/stderr bytes invalid in the locale's default encoding —
            # real risk with text=True and no explicit errors= policy).
            return {
                "_status": "failed",
                "runtime": "hermes",
                "worker_role": self.profile,
                "model": "unknown",
                "usage": "unknown (worker invocation raised before returning)",
                "cost": "unknown (not measured)",
                "artifacts": [],
                "evidence": f"worker invocation raised {type(exc).__name__} before returning",
                "error": {
                    "category": "worker_invocation_error",
                    "recovery": f"{type(exc).__name__}: {exc}",
                },
                "_elapsed_seconds": time.time() - started,
            }

        status = "succeeded" if proc.returncode == 0 else "failed"
        log_path = self._write_run_log(run, stdout=proc.stdout, stderr=proc.stderr)
        log_note = f"see local run log {log_path}" if log_path else "local run log could not be written"
        error = None
        if status != "succeeded":
            error = {
                "category": "worker_nonzero_exit",
                # Never the raw stderr tail here: it's the same "model
                # reasoning in GitHub" problem `evidence` was fixed for,
                # just moved to a different envelope field. The recovery
                # hint points at the local log instead.
                "recovery": f"hermes exited {proc.returncode}; {log_note}",
            }
        return {
            "_status": status,
            "runtime": "hermes",
            "worker_role": self.profile,
            "model": "unknown (not captured by this adapter)",
            "usage": "unknown (not captured by this adapter)",
            "cost": "unknown (not measured)",
            "artifacts": [log_path] if log_path else [],
            "evidence": f"worker exited {proc.returncode}; {len(proc.stdout or '')} chars of stdout captured, {log_note}",
            "error": error,
            "_elapsed_seconds": time.time() - started,
        }

    def _write_run_log(self, run: Run, stdout: "str | None", stderr: "str | None") -> "str | None":
        """Write raw stdout/stderr to a local, gitignored file. Returns the
        path as a string, or None if writing failed (never raises — a
        logging failure must not turn a real result into a worker error)."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / f"{run.run_id}.log"
            log_path.write_text(
                f"=== stdout ===\n{stdout or ''}\n=== stderr ===\n{stderr or ''}\n",
                encoding="utf-8",
                errors="replace",
            )
            return str(log_path)
        except OSError:
            return None


@dataclass
class DshWorkerAdapter:
    """Invokes the DeepSeek Harness Python SDK as a one-shot worker turn.

    The DSH-integration experiment's engine adapter (agent-platform's
    routing.dsh_invoker.invoke_dsh, wrapped by runtime/adapters/dsh_adapter.py)
    is the worker-invocation piece #122's dispatcher was missing. This adapter
    wires the same WorkerAdapter protocol (dispatcher.py's claim/run-identity
    layer) to that invocation, so a claimed run with runtime="dsh" dispatches
    through DSH exactly like hermes-researcher dispatches through the hermes CLI.

    Envelope discipline matches HermesAdapter: raw stdout/stderr never enters
    the envelope (AGENTS.md: no model reasoning in GitHub) -- it goes to a
    local, gitignored run log under RUN_LOG_DIR, and `artifacts` carries the
    path as a content-free reference. Cost and usage are reported as
    `unknown (not measured)` unless the SDK result actually reports them --
    the same honest-unknown stance as HermesAdapter (#58/#71).

    The DSH Python SDK is not yet installed in every environment; a missing
    SDK or a runtime that cannot start surfaces as a failed envelope (via
    DshInvocationError), not an exception -- matching the adapter contract
    ("must never raise for an ordinary worker failure").
    """

    invoke_dsh: Callable = field(default=None)  # type: ignore[assignment]
    log_dir: Path = field(default=RUN_LOG_DIR)

    def _call(self, run: Run, task_prompt: str, timeout_seconds: int) -> dict:
        # Default resolved at call time (not as a class-attribute default) so
        # tests can inject a fake and the import stays lazy: the DSH SDK may
        # be absent entirely.
        if self.invoke_dsh is None:
            from routing.dsh_invoker import invoke_dsh as _default

            return _default(task_prompt, timeout_seconds=timeout_seconds, cwd=Path.cwd())
        return self.invoke_dsh(task_prompt, timeout_seconds=timeout_seconds, cwd=Path.cwd())

    def invoke(self, run: Run, task_prompt: str, timeout_seconds: int) -> dict:
        started = time.time()
        try:
            result = self._call(run, task_prompt, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - DshInvocationError and friends
            return {
                "_status": "failed",
                "runtime": "dsh",
                "worker_role": run.worker_role,
                "model": "unknown",
                "usage": "unknown (worker never started)",
                "cost": "unknown (not measured)",
                "artifacts": [],
                "evidence": f"worker never started: {type(exc).__name__}: {exc}",
                "error": {
                    "category": "runtime_unavailable",
                    "recovery": f"{type(exc).__name__}: {exc}",
                },
                "_elapsed_seconds": time.time() - started,
            }

        status = result.get("status", "failed")
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        log_path = self._write_run_log(run, stdout=stdout, stderr=stderr)
        log_note = f"see local run log {log_path}" if log_path else "local run log could not be written"
        error = None
        if status != "succeeded":
            error = {
                "category": "worker_nonzero_exit" if status == "failed" else status,
                # Never the raw stderr tail here -- same "model reasoning in
                # GitHub" problem evidence was fixed for; point at the local log.
                "recovery": f"dsh reported status={status}; {log_note}",
            }
        return {
            "_status": status,
            "runtime": "dsh",
            "worker_role": run.worker_role,
            "model": "unknown (not captured by this adapter)",
            "usage": "unknown (not captured by this adapter)",
            "cost": "unknown (not measured)",
            "artifacts": [log_path] if log_path else [],
            "evidence": (
                f"dsh reported status={status}; "
                f"finish_reason={result.get('finish_reason')}; {log_note}"
            ),
            "error": error,
            "_elapsed_seconds": time.time() - started,
        }

    def _write_run_log(self, run: Run, stdout: "str | None", stderr: "str | None") -> "str | None":
        """Write raw stdout/stderr to a local, gitignored file. Returns the
        path as a string, or None if writing failed (never raises -- a
        logging failure must not turn a real result into a worker error)."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / f"{run.run_id}.log"
            log_path.write_text(
                f"=== stdout ===\n{stdout or ''}\n=== stderr ===\n{stderr or ''}\n",
                encoding="utf-8",
                errors="replace",
            )
            return str(log_path)
        except OSError:
            return None


class UnknownRuntimeError(RuntimeError):
    pass


ADAPTER_REGISTRY: dict[str, WorkerAdapter] = {
    "hermes-researcher": HermesAdapter(profile="researcher"),
    "hermes-coordinator": HermesAdapter(profile="coordinator"),
    # DSH-integration experiment: the DSH Python-SDK worker (route() picks
    # engine_id "dsh" for research/background-task; dispatcher.py's run.runtime
    # carries that engine_id, so the adapter key matches it directly).
    "dsh": DshWorkerAdapter(),
}


def register_adapter(runtime: str, adapter: WorkerAdapter) -> None:
    """Add or replace an adapter. Keeps the registry open for extension
    (Pi Builder, hermes-coordinator, ...) without editing call sites."""
    ADAPTER_REGISTRY[runtime] = adapter


def dispatch_async(dispatcher: Dispatcher, run: Run, task_prompt: str) -> threading.Thread:
    """Invoke `run`'s adapter in a background thread, then call
    dispatcher.complete() with the resulting envelope.

    Returns the (already-started) thread so tests can join() it; production
    callers may let it run detached. dispatcher.complete()/heartbeat()/
    sweep_expired() are safe to call concurrently from the main thread while
    this is in flight (Dispatcher._lock, an RLock, serializes them).

    A backstop, not the expected path: if the adapter raises despite its
    contract, or dispatcher.complete() itself raises, this must not leave
    the run silently stuck `in_progress` in a swallowed daemon-thread
    exception. We attempt one best-effort complete() with a synthesized
    failure envelope; if that also fails, we print to stderr as a last
    resort so the failure is at least visible in process output.
    """
    adapter = ADAPTER_REGISTRY.get(run.runtime)
    if adapter is None:
        raise UnknownRuntimeError(
            f"no adapter registered for runtime={run.runtime!r} (known: {sorted(ADAPTER_REGISTRY)})"
        )

    def _run() -> None:
        try:
            envelope = adapter.invoke(run, task_prompt, timeout_seconds=run.lease_seconds)
            status = envelope.pop("_status")
            envelope.pop("_elapsed_seconds", None)
        except Exception as exc:  # noqa: BLE001 - deliberate backstop, adapters must not raise
            status = "failed"
            envelope = {
                "runtime": run.runtime,
                "worker_role": run.worker_role,
                "model": "unknown",
                "usage": "unknown (adapter raised before returning a result)",
                "cost": "unknown (not measured)",
                "artifacts": [],
                "evidence": f"adapter raised {type(exc).__name__} instead of returning a result envelope",
                "error": {
                    "category": "adapter_contract_violation",
                    "recovery": f"{type(exc).__name__}: {exc}",
                },
            }
        try:
            dispatcher.complete(run.run_id, status, envelope)
        except Exception as exc:  # noqa: BLE001 - last resort, run must not vanish silently
            print(
                f"[worker_adapters] complete() failed for run {run.run_id}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    thread = threading.Thread(target=_run, name=f"worker-{run.run_id}", daemon=True)
    thread.start()
    return thread
