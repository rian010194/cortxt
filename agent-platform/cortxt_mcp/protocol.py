"""Fallback MCP stdio transport: a thin JSON-RPC 2.0 shim over stdin/stdout.

This is the documented fallback path noted in issue #184 step 3's brief:
used whenever the official `mcp` Python SDK isn't importable in-process --
see `server.py`'s `_try_import_sdk` docstring for the SDK-vs-shim selection.
(The original reason for the fallback being the *only* path -- this repo's
package was itself named `mcp`, colliding with the pip `mcp` SDK package --
was resolved by renaming the package to `cortxt_mcp` in PR #203 / issue
#202, so the SDK now imports cleanly and the shim is a genuine fallback.)
Implements just the MCP
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

from . import mandate as mandate_module
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
    mandate_verifier: Any = None,
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

    def _error(code: int, message: str, *, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not has_id:
            return None
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

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
        # `arguments` is copied (not mutated in place) before the reserved
        # `mandate`/`mandate_context` keys are popped out of it -- the
        # remainder is what actually reaches the tool handler and the
        # ledger's args_summary. A real MCP client can send both keys
        # today with zero wire-protocol changes: the shim's inputSchema
        # already declares additionalProperties: True.
        arguments = dict(params.get("arguments") or {})
        raw_mandate = arguments.pop("mandate", None)
        raw_call_context = arguments.pop("mandate_context", None)
        if not isinstance(raw_call_context, dict):
            raw_call_context = {}
        mandate_id = raw_mandate.get("mandate_id") if isinstance(raw_mandate, dict) else None
        spec = tools.TOOL_REGISTRY.get(name)
        tier_requires_mandate = spec is not None and spec.tier >= tools.TIER_DISPATCH

        try:
            try:
                estimated_cost_usd = float(raw_call_context.get("estimated_cost_usd", 0.0) or 0.0)
            except (TypeError, ValueError):
                # Malformed cost estimate: fail closed to a value that
                # cannot pass a budget check, rather than silently
                # defaulting to 0.0 (which would under-report spend).
                estimated_cost_usd = float("inf")
            raw_estimated_runtime = raw_call_context.get("estimated_runtime_seconds")
            try:
                estimated_runtime_seconds = (
                    None if raw_estimated_runtime is None
                    else float(raw_estimated_runtime)
                )
            except (TypeError, ValueError):
                # Malformed runtime estimate: fail closed to a value that
                # cannot pass a runtime check, rather than silently
                # treating the runtime as undeclared.
                estimated_runtime_seconds = float("inf")
            call_context = mandate_module.CallContext(
                issue_ref=raw_call_context.get("issue_ref", ""),
                data_class=raw_call_context.get("data_class", "L0"),
                estimated_cost_usd=estimated_cost_usd,
                estimated_runtime_seconds=estimated_runtime_seconds,
                scope_text=raw_call_context.get("scope_text"),
                expected_scope_fingerprint=raw_call_context.get("expected_scope_fingerprint"),
            )
            payload = tools.call_tool(
                name, arguments, allow_dispatch=allow_dispatch, allow_credentials=allow_credentials,
                mandate=raw_mandate, mandate_verifier=mandate_verifier, call_context=call_context,
            )
        except tools.ToolNotFoundError:
            return _error(-32601, f"unknown tool: {name}")
        except tools.ToolTierLockedError as error:
            if audit is not None:
                audit.record(
                    name, arguments, status="rejected",
                    mandate_id=mandate_id if tier_requires_mandate else None,
                    mandate_decision="tier_locked" if tier_requires_mandate else None,
                )
            return _error(-32001, str(error))
        except tools.MandateRejectedError as error:
            if audit is not None:
                audit.record(
                    name, arguments, status="rejected",
                    mandate_id=mandate_id, mandate_decision=f"rejected:{error.reason}",
                )
            return _error(-32002, str(error), data={"reason": error.reason})
        except Exception as error:  # tool handlers raise plain exceptions on bad/missing arguments
            return _error(-32000, str(error))

        if audit is not None:
            audit.record(
                name, arguments, status="accepted",
                mandate_id=mandate_id if tier_requires_mandate else None,
                mandate_decision="accepted" if tier_requires_mandate else None,
            )

        return _result({"content": [{"type": "text", "text": json.dumps(payload, default=str)}]})

    return _error(-32601, f"unknown method: {method}")


def serve_stdio(
    *,
    allow_dispatch: bool,
    allow_credentials: bool,
    audit: AuditLog,
    mandate_verifier: Any = None,
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
            mandate_verifier=mandate_verifier,
        )
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
