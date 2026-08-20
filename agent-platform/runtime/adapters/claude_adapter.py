"""Wraps the Claude Code CLI (`claude -p`) as an EngineAdapter (ADR-026).

Verified live against the installed `claude` CLI (v2.1.236), 2026-08-20:
`claude -p <prompt> --output-format json` prints one JSON object on stdout
whose `result` key is the final assistant text, `session_id` is the
engine-native session id, and `is_error` is a bool independent of the
process exit code (confirmed live: a refused/erroring turn can still exit
0 with `is_error:true`, so both signals feed `status`). `claude -p
--resume <session_id> <prompt> --output-format json` continues that same
session -- confirmed live, a resumed call correctly recalled a fact from
the prior turn. Unlike Codex, there is no separate "get me just the final
message" flag; the whole JSON object is stdout and gets parsed directly,
no temp file needed.

`stdin=subprocess.DEVNULL` mirrors CodexAdapter's reasoning: `-p` mode
should not block or silently read extra input from an inherited stdin
under a subprocess whose stdin is not explicitly closed.

`profile` (the EngineAdapter protocol's generic first argument) has no
direct Claude CLI equivalent -- there is no Claude-native notion of a
named inference profile the way Codex has `-p <profile>`. The closest
analog is `--agent <agent>` ("Agent for the current session"), so a
non-empty `profile` is forwarded as `--agent`. In practice
`_run_orchestrator_chat` (cli/unified_cli.py) only forwards a profile
name when the active engine is Hermes, so `profile` is empty/None for
every real `--engine claude` call today; the mapping exists for
completeness and any future engine-aware profile plumbing, not because
it is exercised yet.

`provider` has no CLI equivalent either (model/account routing is not a
per-call override on this CLI) -- raises NotImplementedError, matching
CodexAdapter's own stance on the same gap.

Windows npm-shim check (2026-08-20): `where claude` on this machine finds
only `claude.exe`, a real PE binary (confirmed via a hex dump: `MZ`/`PE`
header, not a `.cmd` shim), because Claude Code is installed as a native
build here, not via `npm install -g @anthropic-ai/claude-code`. No
`claude.cmd`/`claude.js` shim exists in this environment, so the Codex
`.cmd`-routes-through-cmd.exe injection risk this docstring's sibling
(codex_adapter.py) describes does not reproduce today. It is still
handled defensively below, since an npm-installed Claude Code elsewhere
would have the identical shim shape -- `_default_claude_launch_prefix`
resolves a `claude.cmd` shim's actual `node.exe` + `<script>.js` target by
parsing the shim's own text (rather than hardcoding a package path the
way CodexAdapter does for `@openai/codex`, since this environment has no
real shim to confirm an exact npm package/bin layout against) and
launches that pair directly, bypassing cmd.exe the same way. Falls back
to `claude.exe` (found via `shutil.which`, a real PE binary with no
shell-routing risk) if the shim isn't found or isn't parseable, and
never falls back to a `.bat` target for the same reason CodexAdapter
doesn't: identical implicit-cmd.exe-routing risk this function exists to
close.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from subprocess_windows import no_window_kwargs


class ClaudeInvocationError(RuntimeError):
    """Raised when the claude executable itself could not be started."""


# Matches the relative script path an npm-generated .cmd shim invokes via
# node.exe, e.g. "%~dp0\node_modules\@anthropic-ai\claude-code\cli.js".
# Deliberately generic (not hardcoded to a specific package name) since no
# real npm-installed shim exists in this environment to confirm one against.
_SHIM_SCRIPT_RE = re.compile(r'"%~dp0\\(node_modules[\\/][^"]+?\.js)"')


def _resolve_shim_target_script(shim_path: Path) -> Path | None:
    try:
        text = shim_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _SHIM_SCRIPT_RE.search(text)
    if not match:
        return None
    relative = match.group(1).replace("\\", "/")
    return shim_path.parent / relative


def _default_claude_launch_prefix() -> list[str]:
    """Resolve how to launch `claude` on Windows, bypassing any `.cmd` shim.

    See module docstring for the full reasoning. Falls back, in order: a
    parsed npm `.cmd` shim's node.exe + script pair -> a directly resolved
    `claude.exe` -> the bare `claude` name (POSIX, or nothing better found).
    Never falls back to a `.bat` target.
    """
    if sys.platform == "win32":
        cmd_shim = shutil.which("claude.cmd")
        if cmd_shim:
            shim_path = Path(cmd_shim)
            shim_dir = shim_path.parent
            node_exe = shim_dir / "node.exe"
            if not node_exe.is_file():
                found_node = shutil.which("node.exe") or shutil.which("node")
                node_exe = Path(found_node) if found_node else None
            script = _resolve_shim_target_script(shim_path)
            if node_exe is not None and node_exe.is_file() and script is not None and script.is_file():
                return [str(node_exe), str(script)]
        resolved_exe = shutil.which("claude.exe")
        if resolved_exe:
            return [resolved_exe]
    return ["claude"]


class ClaudeAdapter:
    def __init__(
        self, run_subprocess: Callable[..., "subprocess.CompletedProcess[str]"] | None = None
    ) -> None:
        # Real subprocess.run only when no fake was injected -- resolving
        # "claude" to a platform-specific executable path (below) is a
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
                "ClaudeAdapter has no provider-override flag on the claude CLI"
            )

        argv = ["claude", "-p"]
        if session_id:
            argv += ["--resume", session_id]
        argv += ["--output-format", "json"]
        if profile:
            argv += ["--agent", profile]
        if model:
            argv += ["--model", model]
        argv.append(prompt)
        call_argv = argv
        if self._using_real_subprocess:
            call_argv = _default_claude_launch_prefix() + argv[1:]

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
                "stderr": f"claude did not complete within {timeout_seconds}s",
                "elapsed_seconds": time.time() - started,
                "session_id": session_id,
            }
        except OSError as error:
            raise ClaudeInvocationError(f"could not start claude: {error}") from error

        raw_stdout = proc.stdout or ""
        try:
            payload = json.loads(raw_stdout)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict):
            new_session_id = payload.get("session_id") or session_id
            succeeded = proc.returncode == 0 and not payload.get("is_error", False)
            message = payload.get("result")
            stdout = message if isinstance(message, str) and message else raw_stdout
        else:
            new_session_id = session_id
            succeeded = proc.returncode == 0
            stdout = raw_stdout

        return {
            "status": "succeeded" if succeeded else "failed",
            "profile": profile,
            "stdout": stdout,
            "stderr": proc.stderr or "",
            "elapsed_seconds": time.time() - started,
            "session_id": new_session_id,
        }
