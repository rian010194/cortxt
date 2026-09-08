#!/usr/bin/env python3
"""One documented way to start Cortxt OS, with the refusals that make it safe.

`agent-platform/widget/action_host.py` is the loopback host that serves Cortxt
OS and mounts the single operator-gated mutation route (ADR-038). It can be
started three different ways, and two of them mislead:

- `python agent-platform/widget/action_host.py` always mounts the mutation
  route; its parser accepts `--port`, `--spec`, `--require-commit` and
  `--require-clean` and there is no flag that disables actions.
- `cortxt widget --enable-actions` calls `action_host.main()` with neither
  port nor spec, so it always binds 8765 and always serves
  `widget_contract/specs/candidates-0.1.yaml`. A `--port` typed on that
  command line is an argparse error (exit 2) because the subparser declares
  no such flag.

This script is the third way and the documented one. It does not reimplement
the server and it changes nothing about how `action_host` handles requests --
it refuses the four start conditions that are silent and expensive when wrong,
reports what the host will actually use, and then hands off to
`action_host.main`. See `docs/agents/running-cortxt-os.md`.
"""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PREFIX = "[start-cortxt-os]"
DEFAULT_PORT = 8765
LOOPBACK = "127.0.0.1"
# Named in the order the success line prints them.
FREE_ROUTE_VARS = ("CORTXT_FREE_PROVIDER", "CORTXT_FREE_MODEL")
# What the 2026-09-04 dogfood used. Quoted as an example in the refusal
# message and never applied: choosing a model is an operator act, and a script
# that picks one turns an unverified route into an invisible default.
FREE_ROUTE_EXAMPLE = {"CORTXT_FREE_PROVIDER": "nous",
                      "CORTXT_FREE_MODEL": "upstage/solar-pro4:free"}
REPO_ROOT_MARKER = ("agent-platform", "widget", "action_host.py")


def _say(message: str) -> None:
    print(f"{PREFIX} {message}")


def _refuse(message: str) -> int:
    """One line, exit 2. A refusal names the fix, not only the fault."""
    print(f"{PREFIX} refusing to start: {message}")
    return 2


def _port_is_listening(port: int, *, connect=None) -> bool:
    """True when something already answers on 127.0.0.1:<port>.

    Deliberately a *pre-bind* probe rather than a caught bind failure.
    `action_host` serves through `_ReusableThreadingHTTPServer`, which sets
    `allow_reuse_address` (SO_REUSEADDR); on win32 that lets a second process
    bind an address a first process is already listening on, with no error at
    all. A bind-failure check would therefore pass exactly where two listeners
    are about to disagree about the same registry.
    """
    connect = connect or socket.create_connection
    try:
        conn = connect((LOOPBACK, port), 0.5)
    except OSError:
        return False
    try:
        conn.close()
    except OSError:
        pass
    return True


def _git(*args: str, cwd: Path, run=None) -> str:
    """Git metadata, or the literal string "unknown" -- never a guess.

    Mirrors `action_host.source_signature`: an operator comparing this against
    the worktree they expect must be able to see a real mismatch instead of a
    false match.
    """
    run = run or subprocess.run
    try:
        proc = run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    return proc.stdout.strip() or "unknown"


def _load_action_host(repo_root: Path):
    """Import the host module out of *this* checkout.

    `agent-platform` goes on `sys.path` ahead of anything else so an editable
    install of a different worktree cannot answer instead -- the S7b dogfood
    defect `source_signature` exists to expose.
    """
    package_root = str((repo_root / "agent-platform").resolve())
    if sys.path[:1] != [package_root]:
        while package_root in sys.path:
            sys.path.remove(package_root)
        sys.path.insert(0, package_root)
    return importlib.import_module("widget.action_host")


def _registry_path(host) -> Path:
    """The registry expression the host itself uses.

    NOT `cwd / "agent-platform" / ".dispatch" / "runs.json"`. `ActionHost`
    resolves the registry from `AGENT_PLATFORM_DIR`, which is derived from
    `Path(action_host.__file__).parent.parent` -- cwd only selects which
    module gets imported, never where that module then reads. Printing a
    cwd-relative path here would name a file the host does not open.
    """
    return Path(host.AGENT_PLATFORM_DIR) / ".dispatch" / "runs.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="start_cortxt_os.py",
        description="Start the Cortxt OS action host from the repository root.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to serve on (default: {DEFAULT_PORT}). Unlike "
                             f"`cortxt widget --enable-actions`, this one is real.")
    parser.add_argument("--spec", type=Path, default=None,
                        help="Widget spec to serve actions for (default: the host's own "
                             "candidates-0.1.yaml)")
    parser.add_argument("--require-commit", default=None,
                        help="Passed through to action_host: fail closed unless the running "
                             "git commit matches exactly. Opt-in proof tooling, not a default.")
    parser.add_argument("--require-clean", action="store_true",
                        help="Passed through to action_host: fail closed unless the worktree "
                             "is clean. Opt-in proof tooling, not a default.")
    parser.add_argument("--no-free-route", action="store_true",
                        help="Skip the free-route environment and `hermes` checks. For "
                             "read-only OS use where no dispatch is intended.")
    return parser


def main(argv: list[str] | None = None, *, host=None, connect=None, run=None, which=None) -> int:
    args = build_parser().parse_args(argv)
    cwd = Path.cwd()

    # 1. Exactly one listener. This is the refusal every previous handoff
    #    meant by "exactly one listener" and none of them enforced.
    if _port_is_listening(args.port, connect=connect):
        return _refuse(
            f"a host is already listening on {LOOPBACK}:{args.port}. Cortxt OS requires "
            f"exactly one listener -- two hosts on one registry disagree about the same "
            f"Runs. Stop the running host (Ctrl+C in its terminal), or start this one on "
            f"another port with --port.")

    # 2. Repository root. Getting this wrong is silent and expensive, so it is
    #    checked rather than documented.
    if not (cwd.joinpath(*REPO_ROOT_MARKER)).is_file():
        return _refuse(
            f"the working directory {cwd} is not the repository root -- expected to find "
            f"{'/'.join(REPO_ROOT_MARKER)} beneath it. cd to the repository root and run "
            f"`python scripts/start_cortxt_os.py` from there. Running from elsewhere "
            f"selects a different module to import; see the registry-resolution paragraph "
            f"in docs/agents/work-launcher.md.")

    if not args.no_free_route:
        # 3. Free-route environment. Presence only -- never the value.
        missing = [name for name in FREE_ROUTE_VARS if not os.environ.get(name)]
        if missing:
            example = ", ".join(f"{name}={FREE_ROUTE_EXAMPLE[name]}" for name in FREE_ROUTE_VARS)
            return _refuse(
                f"the free route is incomplete: {' and '.join(missing)} "
                f"{'is' if len(missing) == 1 else 'are'} unset or empty. Both "
                f"{FREE_ROUTE_VARS[0]} and {FREE_ROUTE_VARS[1]} must be set before starting. "
                f"The 2026-09-04 dogfood used {example} -- an example, not a default; this "
                f"script never sets them, because choosing a model is an operator act. Pass "
                f"--no-free-route for read-only use where no dispatch is intended.")

        # 4. The dispatcher binary the free route shells out to.
        if (which or shutil.which)("hermes") is None:
            return _refuse(
                "`hermes` is not on PATH, so the free route cannot dispatch. Install it and "
                "reopen the shell, or pass --no-free-route for read-only use where no "
                "dispatch is intended.")

    host = host if host is not None else _load_action_host(cwd)
    registry = _registry_path(host)

    _say(f"repo root: {cwd}")
    _say(f"commit: {_git('rev-parse', 'HEAD', cwd=cwd, run=run)}  "
         f"branch: {_git('rev-parse', '--abbrev-ref', 'HEAD', cwd=cwd, run=run)}")
    _say(f"registry: {registry} (exists: {'yes' if registry.is_file() else 'no'})")
    if args.no_free_route:
        _say("free route: disabled (--no-free-route)")
    else:
        # Routing configuration, not credentials -- `worker_adapters` already
        # reports both on the envelope for exactly this reason.
        _say(f"free route: provider={os.environ[FREE_ROUTE_VARS[0]]} "
             f"model={os.environ[FREE_ROUTE_VARS[1]]}")
    _say(f"url: http://{LOOPBACK}:{args.port}/index.html")

    return host.main(port=args.port, spec_path=args.spec,
                     require_commit=args.require_commit, require_clean=args.require_clean)


if __name__ == "__main__":
    raise SystemExit(main())
