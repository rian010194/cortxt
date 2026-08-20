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


def _default_codex_launch_prefix() -> list[str]:
    """Resolve how to launch `codex` on Windows, bypassing its `.cmd` shim.

    npm installs `codex` as a `.cmd` shim on Windows (confirmed via `where
    codex`, which lists an extensionless file *and* `codex.cmd`).
    `subprocess.run(["codex", ...])` without `shell=True` can't execute the
    extensionless one directly -- Windows' CreateProcess has no way to
    associate it with an interpreter -- and fails with `WinError 2` ("the
    system cannot find the file specified"), observed live.

    Launching `codex.cmd` directly (`shell=False`) *does* start the
    process, but Windows' CreateProcess routes any `.bat`/`.cmd` target
    through `cmd.exe` internally regardless of `shell=False` -- meaning
    argv elements (including the operator's `prompt` text) pass through
    cmd.exe's own metacharacter interpretation (`&`, `|`, `%VAR%`, `^`,
    ...) before codex ever sees them, a real injection surface for
    untrusted or accidental special characters in a chat prompt. Confirmed
    by reading the shim itself (`%APPDATA%\\npm\\codex.cmd`): it is a thin
    wrapper that ultimately runs `node.exe
    node_modules\\@openai\\codex\\bin\\codex.js %*`. Resolving straight to
    that `node.exe` + `codex.js` pair and launching *that* bypasses
    `cmd.exe` entirely -- CreateProcess launches `node.exe` directly, and
    every argv element after it (prompt included) is passed through as a
    real argv array, never reinterpreted as a shell command line.

    Falls back to `codex.exe` (a real PE binary, launched directly by
    CreateProcess with no shell involved -- no equivalent risk) if the
    npm-shim layout isn't found. Deliberately does **not** fall back to
    `codex.bat`: a `.bat` target has the exact same implicit-cmd.exe-
    routing risk this function exists to avoid, so falling back to it
    would silently reopen the injection vector for a layout this function
    has no evidence actually occurs. POSIX's own `codex` has a real
    shebang and needs none of this.
    """
    if sys.platform == "win32":
        cmd_shim = shutil.which("codex.cmd")
        if cmd_shim:
            shim_dir = Path(cmd_shim).parent
            node_exe = shim_dir / "node.exe"
            if not node_exe.is_file():
                found_node = shutil.which("node.exe") or shutil.which("node")
                node_exe = Path(found_node) if found_node else None
            codex_js = shim_dir / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            if node_exe is not None and node_exe.is_file() and codex_js.is_file():
                return [str(node_exe), str(codex_js)]
        resolved_exe = shutil.which("codex.exe")
        if resolved_exe:
            return [resolved_exe]
    return ["codex"]


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
                call_argv = _default_codex_launch_prefix() + argv[1:]

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
