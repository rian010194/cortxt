"""Fallback MCP stdio transport: a thin JSON-RPC 2.0 shim over stdin/stdout.

This is the documented fallback path noted in issue #184 step 3's brief:
used whenever the official `mcp` Python SDK isn't importable in-process --
see `server.py`'s `_try_import_sdk` docstring for why that is in fact the
expected path in this repo today (the local `agent-platform/mcp/` package
name collides with the pip `mcp` SDK package). Implements just the MCP
methods this server's tool surface needs -- `initialize`,
`notifications/initialized`, `tools/list`, `tools/call` -- framed as
newline-delimited JSON objects on stdin/stdout, matching MCP's stdio
transport.

`handle_request` is a pure function (dict in, dict-or-None out) so it's
testable without any real stdio I/O; `serve_stdio` is the thin blocking loop
around it used by the real `serve()` entry point.
"""
from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from . import tools
from .audit import AuditLog

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cortxt-mcp"
SERVER_VERSION = "0.1.0"


def _tool_schema(spec: tools.ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        # Tool-specific arguments aren't validated by JSON Schema here --
        # each handler in tools.py validates its own required fields (and
        # raises ValueError/KeyError, surfaced below as a -32000 error).
        # A real per-tool schema is a reasonable follow-up, not required
        # for this first read-only slice.
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
    }


def handle_request(
    request: dict[str, Any],
    *,
    allow_dispatch: bool,
    allow_credentials: bool,
    audit: AuditLog | None = None,
) -> dict[str, Any] | None:
    """Handle one decoded JSON-RPC 2.0 request or notification.

    Returns the response dict to write back, or None for a notification
    (no `id` on the request -> no reply, per JSON-RPC 2.0) or for a request
    whose `id` is present but the method is itself a notification-shaped
    one (`notifications/initialized`).
    """
    has_id = "id" in request
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    def _result(result: Any) -> dict[str, Any] | None:
        if not has_id:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(code: int, message: str) -> dict[str, Any] | None:
        if not has_id:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return _result({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        specs = tools.list_tools(allow_dispatch=allow_dispatch, allow_credentials=allow_credentials)
        return _result({"tools": [_tool_schema(spec) for spec in specs]})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            payload = tools.call_tool(
                name, arguments, allow_dispatch=allow_dispatch, allow_credentials=allow_credentials,
            )
        except tools.ToolNotFoundError:
            return _error(-32601, f"unknown tool: {name}")
        except tools.ToolTierLockedError as error:
            return _error(-32001, str(error))
        except Exception as error:  # tool handlers raise plain exceptions on bad/missing arguments
            return _error(-32000, str(error))

        if audit is not None:
            audit.record(name, arguments, status="accepted")

        return _result({"content": [{"type": "text", "text": json.dumps(payload, default=str)}]})

    return _error(-32601, f"unknown method: {method}")


def serve_stdio(
    *,
    allow_dispatch: bool,
    allow_credentials: bool,
    audit: AuditLog,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """Blocking loop over stdio: one JSON object per line in, one JSON
    object per line out. Blank lines and lines that don't parse as JSON are
    skipped rather than crashing the server on client noise."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_request(
            request, allow_dispatch=allow_dispatch, allow_credentials=allow_credentials, audit=audit,
        )
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
