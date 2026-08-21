"""MCP server entry point: `cortxt mcp serve`.

Tries the official `mcp` Python SDK's stdio server first; falls back to the
JSON-RPC 2.0 shim in `cortxt_mcp.protocol` when the SDK isn't usable in-process.
See `_try_import_sdk`'s docstring for the SDK-vs-shim selection, and the top
of this module's package docstring (`cortxt_mcp/__init__.py`) for the
tiering/audit decisions this wires together.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _try_import_sdk():
    """Best-effort import of the official `mcp` Python SDK's low-level
    server, stdio transport, and types modules.

    This repo's own package used to be *also* named `mcp`
    (`agent-platform/mcp/`, per the approved #187 plan / issue #184 step 3
    decisions), which collided with the pip-installed `mcp` SDK package the
    moment this module ran: it was itself loaded as `mcp.server`, so
    `sys.modules["mcp"]` was already bound to *this* package by the time this
    function executed, and `import mcp.server.lowlevel` resolved against this
    package's own flat-file `server` module (no `lowlevel` submodule) instead
    of the SDK's. That collision was resolved by renaming the package to
    `cortxt_mcp` (PR #203 / issue #202), so the imports below now resolve
    against the real SDK when it is installed.

    A failure here -- the SDK genuinely not being installed -- is treated as
    expected and handled: `serve()` falls back to `cortxt_mcp.protocol`'s
    stdio shim, which implements the same MCP stdio wire protocol without
    depending on the SDK package at all. This is the "thin stdio JSON-RPC 2.0
    shim as a documented fallback" the step-3 brief anticipates.
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
        # Reserved for a real SDK integration: the rename (PR #203 / issue
        # #202) resolved the import collision, so this branch is now
        # reachable when the SDK is installed, but wiring the SDK's stdio
        # server in is a separate follow-up -- deliberately not implemented
        # against code paths this environment could not execute to verify.
        logger.warning("official mcp SDK detected but not wired up in this build; using the stdio shim instead")

    from .protocol import serve_stdio

    serve_stdio(allow_dispatch=allow_dispatch, allow_credentials=allow_credentials, audit=audit)
