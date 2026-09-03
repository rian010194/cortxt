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
import contextlib
import os
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
#
# Anchored to the repository root, never the process cwd: a bounded worker
# invoked from an arbitrary working directory (a git worktree, an unrelated
# checkout) must still write logs under the same fixed tree, not scatter a
# second `.hermes/dispatch/runs/` next to wherever it happened to be started
# (S7b nested-dispatch dogfood defect).
RUN_LOG_DIR = Path(__file__).resolve().parents[1] / ".hermes" / "dispatch" / "runs"

# Set on every bounded-worker subprocess this module starts (HermesAdapter,
# DshWorkerAdapter, HermesFreeAdapter). Read by Dispatcher.claim() and
# WorkLauncher._launch() (via NESTED_DISPATCH_ENV) to refuse a *second*
# claim/dispatch made from inside an already-running worker. This is a
# technical guard, not a prompt instruction: a worker that shells out to
# `cortxt work resume`, imports work_launcher directly, or otherwise reaches
# the claim/dispatch code path inherits this env var from its parent
# subprocess and is rejected before any claim or run identity is created
# (S7b nested-dispatch dogfood defect -- a Hermes worker started an
# unauthorized second Run from a separate, cwd-relative registry).
NESTED_DISPATCH_ENV = "CORTXT_BOUNDED_WORKER"


def _bounded_worker_env() -> dict:
    """Environment for a worker subprocess: parent env plus the nested-
    dispatch marker. Never mutates os.environ itself."""
    env = dict(os.environ)
    env[NESTED_DISPATCH_ENV] = "1"
    return env


def _bounded_subprocess_run(*args, **kwargs) -> "subprocess.CompletedProcess[str]":
    """`subprocess.run` with the nested-dispatch marker injected, for
    invoker functions (e.g. routing.hermes_invoker.invoke_hermes) that
    accept a `run_subprocess` callable but don't inject env themselves."""
    kwargs.setdefault("env", _bounded_worker_env())
    return subprocess.run(*args, **kwargs)


_nested_dispatch_lock = threading.Lock()
_nested_dispatch_depth = 0
_nested_dispatch_previous: "str | None" = None


@contextlib.contextmanager
def bounded_worker_context():
    """Thread-safe scoped marker for an in-process bounded-worker call
    (DshWorkerAdapter's in-process SDK invocation).

    Naive `previous = os.environ.get(...); os.environ[K] = "1"; ...;
    os.environ[K] = previous` races across concurrent threads sharing the
    same process env: thread A can restore the marker to `None` while
    thread B's SDK call is still in flight, letting a nested claim through
    (or, on the other order, leave the marker stuck set after every bounded
    call has actually finished). `os.environ` is process-wide, so any
    concurrency-safe scheme here must be reference-counted, not a plain
    set/restore pair.

    A module-level lock plus a depth counter fixes this: the marker is set
    on the first concurrent entry and only cleared on the last concurrent
    exit, so it stays set for the whole time at least one bounded-worker
    call is active anywhere in this process, and is restored to its
    original value (normally unset) once the last one exits -- success or
    exception, via the `finally`.
    """
    global _nested_dispatch_depth, _nested_dispatch_previous
    with _nested_dispatch_lock:
        if _nested_dispatch_depth == 0:
            _nested_dispatch_previous = os.environ.get(NESTED_DISPATCH_ENV)
        _nested_dispatch_depth += 1
        os.environ[NESTED_DISPATCH_ENV] = "1"
    try:
        yield
    finally:
        with _nested_dispatch_lock:
            _nested_dispatch_depth -= 1
            if _nested_dispatch_depth == 0:
                if _nested_dispatch_previous is None:
                    os.environ.pop(NESTED_DISPATCH_ENV, None)
                else:
                    os.environ[NESTED_DISPATCH_ENV] = _nested_dispatch_previous
                _nested_dispatch_previous = None


def _log_references(run: Run, log_path: "str | None") -> list[str]:
    """A stable, path-free identifier list for a local run log.

    The envelope (posted to GitHub via Dispatcher._result_comment) must never
    carry a real local filesystem path -- on a developer machine that path
    routinely embeds the OS username and directory layout, which is exactly
    the kind of local/content detail the artifact policy forbids alongside
    prompts, stdout/stderr, and secrets. Operators can still find the file:
    it always lives at RUN_LOG_DIR / f"{run.run_id}.log", which this
    identifier deterministically encodes without echoing the path itself.
    Empty when the log was never written (same "don't falsely claim a log
    exists" contract as before).
    """
    if log_path is None:
        return []
    return [f"run-log:{run.run_id}"]


class WorkerAdapter(Protocol):
    def invoke(self, run: Run, task_prompt: str, timeout_seconds: int,
               worktree: Path | None = None) -> dict:
        """Run the worker (the caller backgrounds this call) and return a
        result_envelope dict plus an internal `_status` key the caller pops
        off and passes to Dispatcher.complete(). Must never raise for an
        ordinary worker failure — a failed/timed_out envelope is a normal
        return, not an exception. `dispatch_async` treats a raise from this
        method as a backstop case, not the expected path.

        `worktree`, when given, is the run's isolated git worktree: the
        worker subprocess must run with that directory as its cwd so it can
        never write outside the assigned workspace (#419)."""
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

    def invoke(self, run: Run, task_prompt: str, timeout_seconds: int,
               worktree: Path | None = None) -> dict:
        started = time.time()
        try:
            proc = self.run_subprocess(
                ["hermes", "-p", self.profile, "-z", task_prompt],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                # Bound the worker to its run's isolated worktree (#419): the
                # subprocess must never inherit the CLI's cwd, which may be an
                # unrelated directory or another checkout.
                cwd=worktree if worktree is not None else None,
                # NESTED_DISPATCH_ENV marks this subprocess as a bounded
                # worker: if it (or anything it shells out to) reaches
                # Dispatcher.claim() or WorkLauncher._launch(), the claim is
                # refused instead of silently creating a second Run.
                env=_bounded_worker_env(),
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
                "artifacts": _log_references(run, log_path),
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
        log_note = "see local run log" if log_path else "local run log could not be written"
        error = None
        if status != "succeeded":
            error = {
                "category": "worker_nonzero_exit",
                # Never the raw stderr tail here: it's the same "model
                # reasoning in GitHub" problem `evidence` was fixed for,
                # just moved to a different envelope field. The recovery
                # hint points at the local log instead -- never the log's
                # actual filesystem path (that can leak the OS username and
                # local directory layout; see `_log_references`).
                "recovery": f"hermes exited {proc.returncode}; {log_note}",
            }
        return {
            "_status": status,
            "runtime": "hermes",
            "worker_role": self.profile,
            "model": "unknown (not captured by this adapter)",
            "usage": "unknown (not captured by this adapter)",
            "cost": "unknown (not measured)",
            "artifacts": _log_references(run, log_path),
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

    Nested-dispatch guard (S7b #482 follow-on): unlike HermesAdapter/
    HermesFreeAdapter, this adapter does not shell out to an OS subprocess it
    owns -- ``routing.dsh_invoker.invoke_dsh`` calls the DSH Python SDK
    in-process, and the SDK itself owns whatever runtime subprocess it starts
    internally (there is no ``run_subprocess`` seam to inject an env var
    into; see that module's docstring). ``_bounded_subprocess_run`` /
    ``_bounded_worker_env`` therefore cannot mark that subprocess the way
    they mark HermesAdapter's ``hermes`` CLI child. Because this call runs
    inside the *same process* as ``Dispatcher.claim()`` (dispatch_async's
    background thread), that process's own ``os.environ`` is temporarily
    marked with ``NESTED_DISPATCH_ENV`` for the duration of the SDK call --
    any subprocess the SDK spawns inherits it (the normal `os.environ`
    inheritance model), so a DSH-run worker that shells out to
    ``cortxt work resume`` is rejected by ``Dispatcher.claim()`` exactly like
    a nested Hermes worker is. The marker is always restored (never left set)
    even if the SDK call raises, so it cannot leak into an unrelated
    later call on the same process/thread.
    """

    invoke_dsh: Callable = field(default=None)  # type: ignore[assignment]
    log_dir: Path = field(default=RUN_LOG_DIR)

    def _call(self, run: Run, task_prompt: str, timeout_seconds: int,
              worktree: Path | None = None) -> dict:
        # Default resolved at call time (not as a class-attribute default) so
        # tests can inject a fake and the import stays lazy: the DSH SDK may
        # be absent entirely. Provider/model routing is provider-neutral
        # (issue #204): read CORTXT_DSH_PROVIDER / CORTXT_DSH_MODEL from the
        # environment, never hardcode a vendor; the SDK's own defaults apply
        # when neither is set.
        provider = os.environ.get("CORTXT_DSH_PROVIDER")
        model = os.environ.get("CORTXT_DSH_MODEL")
        # Run inside the isolated worktree when one is assigned (#419); never
        # silently fall back to the CLI's cwd for a worktree-backed run.
        cwd = worktree if worktree is not None else Path.cwd()
        invoke = self.invoke_dsh
        if invoke is None:
            from routing.dsh_invoker import invoke_dsh as invoke
        # Nested-dispatch guard for the in-process SDK call (see class
        # docstring): no run_subprocess seam exists here, so the marker is
        # set on this process's own os.environ for the SDK call's duration --
        # any subprocess the SDK spawns internally inherits it. Uses the
        # reference-counted `bounded_worker_context()` (not a naive
        # get/set/restore triple) so concurrent in-process DSH calls on
        # different threads can't race each other's restore and clear the
        # marker while a sibling call is still in flight -- it stays set as
        # long as at least one bounded call is active anywhere in this
        # process, and is restored to its original value only once the last
        # one exits, success or exception.
        with bounded_worker_context():
            return invoke(
                task_prompt, timeout_seconds=timeout_seconds,
                provider=provider, model=model, cwd=cwd,
            )

    def invoke(self, run: Run, task_prompt: str, timeout_seconds: int,
               worktree: Path | None = None) -> dict:
        started = time.time()
        try:
            result = self._call(run, task_prompt, timeout_seconds, worktree=worktree)
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
        log_note = "see local run log" if log_path else "local run log could not be written"
        error = None
        if status != "succeeded":
            error = {
                "category": "worker_nonzero_exit" if status == "failed" else status,
                # Never the raw stderr tail here -- same "model reasoning in
                # GitHub" problem evidence was fixed for; point at the local
                # log, never its actual filesystem path.
                "recovery": f"dsh reported status={status}; {log_note}",
            }
        # The invocation actually started with these provider/model values
        # (read once here, matching what _call passed to invoke_dsh): report
        # them once the invocation began, rather than a blanket "unknown"
        # that would misrepresent a real, observed invocation (S7b #482
        # dogfood defect -- provider=nous/model=... was used but the
        # envelope claimed "unknown"). Usage/cost stay honestly "unknown"
        # because the SDK result here does not report them.
        provider = os.environ.get("CORTXT_DSH_PROVIDER") or "unknown (provider-default; CORTXT_DSH_PROVIDER unset)"
        model = os.environ.get("CORTXT_DSH_MODEL") or "unknown (provider-default; CORTXT_DSH_MODEL unset)"
        return {
            "_status": status,
            "runtime": "dsh",
            "worker_role": run.worker_role,
            "provider": provider,
            "model": model,
            "usage": "unknown (not reported by the dsh SDK result)",
            "cost": "unknown (not measured)",
            "artifacts": _log_references(run, log_path),
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


@dataclass
class HermesFreeAdapter:
    """Free-tier hermes route for the WorkLauncher dispatch registry.

    Reuses the same invoker the platform-registered HermesFreeAdapter wraps
    (``routing.hermes_invoker.invoke_hermes``, resolved lazily at call time so
    the import stays cheap and injectable), and reads provider/model strictly
    from ``CORTXT_FREE_MODEL`` / ``CORTXT_FREE_PROVIDER`` environment
    variables -- never hard-coded, so provider/credential policy is not
    duplicated here (S7b #482 dogfood defect).

    A missing configuration is an ordinary worker failure (a failed envelope
    with ``runtime_unavailable`` recovery guidance), never an exception --
    matching the WorkerAdapter contract. Raw stdout/stderr goes to the local
    gitignored run log only; envelope fields are short, bounded, structured
    summaries (no model reasoning in GitHub).
    """

    invoke_hermes: Callable = field(default=None)  # type: ignore[assignment]
    log_dir: Path = field(default=RUN_LOG_DIR)

    def _call(self, run: Run, task_prompt: str, timeout_seconds: int,
              worktree: Path | None = None) -> dict | None:
        model = os.environ.get("CORTXT_FREE_MODEL")
        provider = os.environ.get("CORTXT_FREE_PROVIDER")
        if not model or not provider:
            return None
        # Bound the worker to its run's isolated worktree when one exists
        # (#419); never silently fall back to the CLI's cwd.
        cwd = worktree if worktree is not None else Path.cwd()
        if self.invoke_hermes is None:
            from routing.hermes_invoker import invoke_hermes as _default
            # Route the hermes CLI subprocess through _bounded_worker_env()
            # (the invoker accepts an injectable run_subprocess) so the
            # nested-dispatch marker reaches the actual worker OS process,
            # not just this Python call.
            return _default(
                run.worker_role, task_prompt, timeout_seconds=timeout_seconds,
                model=model, provider=provider, cwd=cwd,
                run_subprocess=_bounded_subprocess_run,
            )
        return self.invoke_hermes(
            run.worker_role, task_prompt, timeout_seconds=timeout_seconds,
            model=model, provider=provider, cwd=cwd,
        )

    def invoke(self, run: Run, task_prompt: str, timeout_seconds: int,
               worktree: Path | None = None) -> dict:
        started = time.time()
        try:
            result = self._call(run, task_prompt, timeout_seconds, worktree=worktree)
        except Exception as exc:  # noqa: BLE001 - HermesInvocationError and friends
            return {
                "_status": "failed",
                "runtime": "hermes-free",
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
        if result is None:
            return {
                "_status": "failed",
                "runtime": "hermes-free",
                "worker_role": run.worker_role,
                "model": "unknown",
                "usage": "unknown (worker never started)",
                "cost": "unknown (not measured)",
                "artifacts": [],
                "evidence": "free route not configured; worker never started",
                "error": {
                    "category": "runtime_unavailable",
                    "recovery": "set CORTXT_FREE_MODEL and CORTXT_FREE_PROVIDER, then retry with a fresh run",
                },
                "_elapsed_seconds": time.time() - started,
            }
        status = result.get("status", "failed")
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        log_path = self._write_run_log(run, stdout=stdout, stderr=stderr)
        log_note = "see local run log" if log_path else "local run log could not be written"
        error = None
        if status != "succeeded":
            error = {
                "category": "worker_nonzero_exit" if status == "failed" else status,
                # Never the raw stderr tail: same "model reasoning in GitHub"
                # problem `evidence` was fixed for; point at the local log,
                # never its actual filesystem path.
                "recovery": f"hermes-free reported status={status}; {log_note}",
            }
        # The invocation actually started with these provider/model values
        # (the same env vars _call read to build the invoke_hermes call);
        # report what was actually used once the invocation began, instead
        # of the blanket "unknown" that misrepresented a real, observed
        # invocation (S7b #482 dogfood defect: provider=nous,
        # model=upstage/solar-pro4:free were used, envelope said "unknown").
        # Usage/cost stay honestly "unknown" -- the hermes CLI's one-shot
        # mode does not report them, so this adapter never guesses.
        model = os.environ.get("CORTXT_FREE_MODEL") or "unknown"
        provider = os.environ.get("CORTXT_FREE_PROVIDER") or "unknown"
        return {
            "_status": status,
            "runtime": "hermes-free",
            "worker_role": run.worker_role,
            "provider": provider,
            "model": model,
            "usage": "unknown (not reported by the hermes CLI's one-shot mode)",
            "cost": "unknown (not measured)",
            "artifacts": _log_references(run, log_path),
            "evidence": f"hermes-free reported status={status}; {log_note}",
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


ADAPTER_REGISTRY: dict[str, WorkerAdapter] = {
    "hermes-researcher": HermesAdapter(profile="researcher"),
    "hermes-coordinator": HermesAdapter(profile="coordinator"),
    # DSH-integration experiment: the DSH Python-SDK worker (route() picks
    # engine_id "dsh" for research/background-task; dispatcher.py's run.runtime
    # carries that engine_id, so the adapter key matches it directly).
    "dsh": DshWorkerAdapter(),
    # Free-tier hermes route (engine_id "hermes-free" from the routing
    # manifest). Wires the same invoker the platform HermesFreeAdapter wraps,
    # so the WorkLauncher can actually dispatch what eligibility approves.
    "hermes-free": HermesFreeAdapter(),
}


def register_adapter(runtime: str, adapter: WorkerAdapter) -> None:
    """Add or replace an adapter. Keeps the registry open for extension
    (Pi Builder, hermes-coordinator, ...) without editing call sites."""
    ADAPTER_REGISTRY[runtime] = adapter


# Runtimes that need more than "an adapter class is registered" to actually
# be launchable: a registry hit is necessary but not sufficient when the
# adapter itself refuses to start without configuration it reads from the
# environment (S7b #482 follow-on -- a launch that was reported dispatchable
# but immediately failed with "free route not configured").
_RUNTIME_ENV_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "hermes-free": ("CORTXT_FREE_MODEL", "CORTXT_FREE_PROVIDER"),
}


def is_runtime_dispatchable(runtime: str) -> bool:
    """Single authoritative runtime-dispatchability check (S7b #482).

    The WorkLauncher dispatches through ``ADAPTER_REGISTRY``; dispatch-request
    eligibility must consult exactly this registry so the projection and the
    real launch cannot disagree (the dogfood defect: eligibility used the
    platform engine context where ``hermes-free`` had a provider, while the
    launcher registry had no ``hermes-free`` adapter).

    Registry membership only (matches every existing eligibility caller,
    including dispatch-request projection tests that intentionally exercise
    an unconfigured environment). See `runtime_launch_config_ok` for the
    stricter "would this launch actually start" check.
    """
    return runtime in ADAPTER_REGISTRY


def runtime_launch_config_ok(runtime: str) -> bool:
    """Stricter pre-launch config check: registered AND actually configured.

    ``is_runtime_dispatchable`` alone can report a runtime as dispatchable
    when the adapter is registered but would immediately fail with
    ``runtime_unavailable`` for lack of configuration (S7b #482 follow-on --
    ``hermes-free`` needs ``CORTXT_FREE_MODEL``/``CORTXT_FREE_PROVIDER`` set,
    not just an adapter class present). Callers that are about to actually
    launch (not just project eligibility for display) should consult this
    in addition to ``is_runtime_dispatchable``. Never inspects or reports
    credential *values* -- only whether the non-secret routing env vars are
    set, matching "the check must not expose credentials."
    """
    if not is_runtime_dispatchable(runtime):
        return False
    required_env = _RUNTIME_ENV_REQUIREMENTS.get(runtime, ())
    return all(os.environ.get(name) for name in required_env)


def _worktree_git(worktree, args):
    """Run ``git`` inside ``worktree``, returning ``(returncode, stdout)``.

    The same ``(returncode, stdout)`` contract ``commit_evidence`` uses, so the
    adapter path can resolve its Run's branch tip without this module knowing
    anything about the gate.
    """
    proc = subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30,
                          cwd=str(worktree))
    return proc.returncode, proc.stdout


def _derive_run_branch_commit(run, repo_dir, git) -> "str | None":
    """Resolve the tip of ``run``'s registered branch, or None.

    The Evidence Gate re-verifies whatever commit is claimed against the Run's
    registered isolated branch, timestamp, DCO and artifact policy, so deriving
    the branch tip here is safe (`#506`): a baseline commit that predates the
    claim is refused by the gate's own ``commit_predates_run`` check, and a
    branch that cannot be resolved yields None (a later ``commit_missing``).
    """
    branch = getattr(run, "branch", None)
    if not repo_dir or not branch:
        return None
    try:
        code, out = git(["rev-parse", f"refs/heads/{branch}"])
    except Exception:  # noqa: BLE001 - a readable repo is the gate's job, never ours
        return None
    if code != 0:
        return None
    value = (out or "").strip()
    return value if value else None


def enrich_run_correlation(run, result_envelope, *, repo_dir=None, git=None) -> dict:
    """Inject the authoritative correlation fields into a result envelope (#506).

    ``run_id``, ``issue_id`` and ``request_id`` come from the durable Run
    record, never trusted from worker prose: a worker that echoes them back adds
    no assurance and must not be allowed to change them. These are overwritten
    unconditionally, because correlation is the platform's to own.

    The ``commit`` is *not* taken from worker prose on faith either: when the
    envelope omits it and a ``repo_dir`` + ``run.branch`` are available, it is
    derived from the Run's own isolated branch. Whatever commit is ultimately
    presented is still verified by the Evidence Gate itself (reachability, the
    Run's branch, a strictly-after-claim timestamp, DCO, and artifact policy) --
    this helper supplies the authoritative identity fields, it does not weaken
    the gate's checks.

    Returns a new envelope dict; the caller's original is not mutated.
    """
    envelope = dict(result_envelope or {})
    envelope["run_id"] = str(run.run_id)
    envelope["issue_id"] = str(run.issue_id)
    request_id = getattr(run, "request_id", None)
    if request_id is not None:
        envelope["request_id"] = str(request_id)
    else:
        # No authoritative request_id on the Run record. A worker-supplied one
        # must not survive here: the gate would then be comparing the worker's
        # own claim against nothing. Dropping it keeps the failure honest --
        # `request_id_not_recorded`, an unapproved Run -- instead of letting
        # worker prose stand in for approved identity.
        envelope.pop("request_id", None)
    if not envelope.get("commit"):
        derived = _derive_run_branch_commit(run, repo_dir, git) if (repo_dir and git) else None
        if derived:
            envelope["commit"] = derived
    return envelope


def dispatch_async(dispatcher: Dispatcher, run: Run, task_prompt: str,
                   worktree: Path | None = None,
                   on_terminal: "Callable[[str, str], None] | None" = None) -> threading.Thread:
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

    `worktree` (the run's isolated git worktree) is forwarded to the
    adapter so the worker subprocess runs with that cwd, never the CLI's
    (#419).

    `on_terminal(run_id, status)`, when given, runs after dispatcher.complete()
    for every terminal status this thread produces (succeeded, failed, or the
    adapter_contract_violation backstop above) -- the WorkLauncher wires its
    execution-map claim release through this hook so a claim is never left
    held past the point its Run went terminal, regardless of outcome (S7b
    nested-dispatch dogfood follow-on: the claim-release path only ran for
    launcher.submit(), never for a worker completing on its own through this
    background thread). Never allowed to crash the thread or mask the
    dispatcher.complete() outcome -- a hook failure is caught and printed,
    same discipline as the complete() backstop above.
    """
    adapter = ADAPTER_REGISTRY.get(run.runtime)
    if adapter is None:
        raise UnknownRuntimeError(
            f"no adapter registered for runtime={run.runtime!r} (known: {sorted(ADAPTER_REGISTRY)})"
        )

    def _run() -> None:
        try:
            envelope = adapter.invoke(run, task_prompt, timeout_seconds=run.lease_seconds,
                                      worktree=worktree)
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
            # #506: supply the authoritative correlation fields from the durable
            # Run record before the Evidence Gate sees the envelope, so a worker
            # that echoes nothing (or echoes wrong values) can never bypass
            # correlation.
            #
            # This is the path a real OS launch takes (WorkLauncher._dispatch ->
            # dispatch_async -> adapter -> Dispatcher.complete), so the commit
            # must be derived here too, not only in the coordinator-direct
            # `WorkLauncher.submit()`. No adapter emits a `commit` field, so
            # without derivation every mutating Run on the live path stops at
            # `commit_missing` and the accepted arm is structurally unreachable.
            # The run's own isolated worktree is a git working directory for its
            # own branch, which is all the derivation needs. Only a claimed
            # success is enriched with a commit: a failed run must not carry a
            # field that reads as evidence. The Evidence Gate still verifies
            # whatever is presented (reachability, the Run's branch, a strictly-
            # after-claim timestamp, DCO, artifact policy), so a run that landed
            # nothing derives its branch's baseline tip and is refused by
            # `commit_predates_run` rather than passing.
            derive = worktree if status == "succeeded" else None
            envelope = enrich_run_correlation(
                run, envelope, repo_dir=derive,
                git=(lambda args, _wt=derive: _worktree_git(_wt, args)) if derive else None)
            dispatcher.complete(run.run_id, status, envelope)
        except Exception as exc:  # noqa: BLE001 - last resort, run must not vanish silently
            print(
                f"[worker_adapters] complete() failed for run {run.run_id}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        if on_terminal is not None:
            try:
                on_terminal(run.run_id, status)
            except Exception as exc:  # noqa: BLE001 - never let a release hook mask the result
                print(
                    f"[worker_adapters] on_terminal() failed for run {run.run_id}: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

    thread = threading.Thread(target=_run, name=f"worker-{run.run_id}", daemon=True)
    thread.start()
    return thread
