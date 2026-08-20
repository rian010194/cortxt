"""Wraps the Codex CLI (`codex exec`) as an EngineAdapter (ADR-026).

Verified live against the installed `codex` CLI, 2026-08-20: every
`codex exec` (fresh or `resume`) JSONL stream's first line is
`{"type":"thread.started","thread_id":"<uuid>"}`, and that `thread_id` is
what `codex exec resume <thread_id> ...` accepts to continue the same
conversation -- confirmed a resumed call correctly recalled the prior
turn's content. `-o/--output-last-message <file>` writes the final
assistant message as plain text, avoiding parsing conversational prose out
of the JSONL/stdout stream.

`stdin=subprocess.DEVNULL` is required, not optional: `codex exec` reads
stdin as an appended `<stdin>` block whenever stdin isn't explicitly
closed/redirected, even when a prompt argument is also given -- observed
live as a "Reading additional input from stdin..." message that would
otherwise silently corrupt the prompt under a subprocess whose stdin is
inherited from a parent process.

The returned dict's `stdout` key holds the *parsed final message* (the
`-o` file's contents), not the raw JSONL stream -- deliberately, so
`_run_orchestrator_chat`'s `result.get("stdout", "").strip()` (written
against `invoke_hermes()`, where stdout already *is* the answer) works
identically for both engines without an engine-specific branch. The raw
JSONL is not preserved separately in v1 -- a real need for it (debugging a
parse failure) is a v2 concern, not designed here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from subprocess_windows import no_window_kwargs


class CodexInvocationError(RuntimeError):
    """Raised when the codex executable itself could not be started."""


def _default_codex_executable() -> str:
    """Resolve the real `codex` executable on Windows.

    npm installs `codex` as a `.cmd` shim on Windows (confirmed via `where
    codex`, which lists an extensionless file *and* `codex.cmd`).
    `subprocess.run(["codex", ...])` without `shell=True` can't execute the
    extensionless one directly -- Windows' CreateProcess has no way to
    associate it with an interpreter -- and fails with `WinError 2` ("the
    system cannot find the file specified"), observed live. Resolve to the
    `.cmd`/`.exe` shim explicitly instead of using `shell=True` (which would
    reintroduce shell-quoting risk for the prompt argument). POSIX has no
    such split -- "codex" resolves and executes directly there.
    """
    if sys.platform == "win32":
        for candidate in ("codex.cmd", "codex.exe", "codex.bat"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return "codex"


def _parse_thread_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
    return None


class CodexAdapter:
    def __init__(
        self, run_subprocess: Callable[..., "subprocess.CompletedProcess[str]"] | None = None
    ) -> None:
        # Real subprocess.run only when no fake was injected -- resolving
        # "codex" to a platform-specific executable path (below) is a
        # concern of *actually launching a process*, not of the argv this
        # adapter builds, so it must not change what a fake run_subprocess
        # (as every test injects) receives.
        self._using_real_subprocess = run_subprocess is None
        self._run_subprocess = run_subprocess if run_subprocess is not None else subprocess.run

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
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if provider:
            raise NotImplementedError(
                "CodexAdapter has no provider-override flag on the codex CLI"
            )

        descriptor, tmp_path_str = tempfile.mkstemp(prefix=".codex-last-message-", suffix=".txt")
        os.close(descriptor)
        tmp_path = Path(tmp_path_str)
        try:
            argv = ["codex", "exec"]
            if session_id:
                argv += ["resume", session_id]
            argv += ["--json", "-o", str(tmp_path)]
            if profile:
                argv += ["-p", profile]
            if model:
                argv += ["-m", model]
            if cwd is not None:
                argv += ["-C", str(cwd)]
            argv.append(prompt)
            call_argv = argv
            if self._using_real_subprocess:
                call_argv = [_default_codex_executable()] + argv[1:]

            started = time.time()
            try:
                proc = self._run_subprocess(
                    call_argv,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    stdin=subprocess.DEVNULL,
                    cwd=str(cwd) if cwd is not None else None,
                    **no_window_kwargs(),
                )
            except subprocess.TimeoutExpired:
                return {
                    "status": "timed_out",
                    "profile": profile,
                    "stdout": "",
                    "stderr": f"codex did not complete within {timeout_seconds}s",
                    "elapsed_seconds": time.time() - started,
                    "session_id": session_id,
                }
            except OSError as error:
                raise CodexInvocationError(f"could not start codex: {error}") from error

            new_session_id = _parse_thread_id(proc.stdout or "") or session_id
            message = tmp_path.read_text(encoding="utf-8", errors="replace") if tmp_path.exists() else ""
            return {
                "status": "succeeded" if proc.returncode == 0 else "failed",
                "profile": profile,
                "stdout": message.strip() if message.strip() else (proc.stdout or ""),
                "stderr": proc.stderr or "",
                "elapsed_seconds": time.time() - started,
                "session_id": new_session_id,
            }
        finally:
            tmp_path.unlink(missing_ok=True)
