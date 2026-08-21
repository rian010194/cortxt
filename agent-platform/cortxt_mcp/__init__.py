"""Cortxt MCP server package (`cortxt mcp serve`).

Package name `cortxt_mcp` (renamed from `mcp` in PR #203, issue #202): the
top-level `mcp` name collided with the official PyPI `mcp` Python SDK at
import time, which the `[mcp]` optional-dependency group targets
(`mcp>=1.2`). Renaming makes the SDK importable in-process and leaves the
stdio shim in `protocol.py` as a genuine fallback for environments without
the SDK.

Exposes a first, read-only tool slice (`route_engine`, `list_engine_manifests`,
`cortxt_status`, `cortxt_sessions`, `cortxt_runtimes`, `cortxt_orchestrator`,
`cortxt_pipeline`) over MCP's stdio transport, plus tier-gated write/dispatch
tools behind `--allow-dispatch` (`cortxt_dispatch`, `cortxt_addons_submit`,
`cortxt_daemon_status`) and a reserved, currently-empty `--allow-credentials`
tier. Every accepted call is audit-logged to the existing session_state
ledger (`caller="mcp"`). See:

  - `tools.py`   -- tool registry, tier gating, thin-wrapper handlers.
  - `audit.py`   -- args-summary audit logging to the session_state ledger.
  - `protocol.py`-- fallback stdio JSON-RPC 2.0 transport shim.
  - `server.py`  -- `serve()` entry point (SDK-vs-shim selection).

Design and tiering decisions are locked by GitHub issue #184 step 3's
approval, following the plan in issue #187.
"""
from __future__ import annotations

from .server import serve

__all__ = ["serve"]
