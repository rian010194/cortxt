"""MCP server entry point: `cortxt mcp serve`.

Tries the official `mcp` Python SDK's stdio server first; falls back to the
JSON-RPC 2.0 shim in `mcp.protocol` when the SDK isn't usable in-process.
See `_try_import_sdk`'s docstring for why the fallback is the expected path
in this repo today, and the top of this module's package docstring
(`mcp/__init__.py`) for the tiering/audit decisions this wires together.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _try_import_sdk():
    """Best-effort import of the official `mcp` Python SDK's low-level
    server, stdio transport, and types modules.

    This repo's own package is *also* named `mcp` (`agent-platform/mcp/`,
    per the approved #187 plan / issue #184 step 3 decisions) -- which
    collides with the pip-installed `mcp` SDK package the moment this very
    module runs: it is itself loaded as `mcp.server`, so `sys.modules["mcp"]`
    is already bound to *this* package by the time this function executes,
    and `import mcp.server.lowlevel` resolves against this package's own
    flat-file `server` module (no `lowlevel` submodule) instead of the SDK's.
    That's the same class of problem `cortxt_entrypoint.py` documents for the
    `cli` package name and works around with file-path loading under a
    private `sys.modules` key; we do not replicate that workaround here,
    because it cannot be exercised against a live interpreter in every
    environment this ships to (this build environment could not run Python
    to verify it), and a subtly-wrong version of that trick is worse than a
    deterministic, fully-tested fallback.

    Any failure here -- the collision above, or the SDK genuinely not being
    installed -- is treated as expected and handled: `serve()` falls back to
    `mcp.protocol`'s stdio shim, which implements the same MCP stdio wire
    protocol without depending on the SDK package at all. This is the
    "thin stdio JSON-RPC 2.0 shim as a documented fallback" the step-3 brief
    anticipates, and given the collision above, it is the path this build
    actually exercises today.
    """
    try:
        import importlib

        lowlevel = importlib.import_module("mcp.server.lowlevel")
        stdio = importlib.import_module("mcp.server.stdio")
        types_mod = importlib.import_module("mcp.types")
        return lowlevel, stdio, types_mod
    except Exception as error:
        logger.info("official mcp SDK not usable in-process (%s); using the stdio shim", error)
        return None


def serve(
    *,
    allow_dispatch: bool = False,
    allow_credentials: bool = False,
    store: Path | None = None,
) -> None:
    """Entry point for `cortxt mcp serve`. Blocks on stdio until the client
    disconnects (EOF on stdin), same foreground-blocking shape as
    `cortxt widget`.

    Tier 0 (read-only) tools are always on. `allow_dispatch` unlocks Tier 1
    (`cortxt_dispatch`, `cortxt_addons_submit`, `cortxt_daemon_status`).
    `allow_credentials` unlocks Tier 2 -- scaffolding only today, no
    credential tools are registered yet. `store` is the session_state ledger
    used for audit logging (default: `agent-platform/.sessions`, same
    default every other CLI subcommand uses).
    """
    from .audit import AuditLog

    agent_platform_dir = Path(__file__).resolve().parent.parent
    store = store or (agent_platform_dir / ".sessions")
    audit = AuditLog(store)

    sdk = _try_import_sdk()
    if sdk is not None:
        # Reserved for a real SDK integration once the name collision
        # documented in _try_import_sdk is resolved -- not reachable in this
        # build (see that docstring), so deliberately not implemented against
        # code paths this environment could not execute to verify.
        logger.warning("official mcp SDK detected but not wired up in this build; using the stdio shim instead")

    from .protocol import serve_stdio

    serve_stdio(allow_dispatch=allow_dispatch, allow_credentials=allow_credentials, audit=audit)
