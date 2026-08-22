"""Day-one audit logging for the Cortxt MCP server.

Appends one event per *accepted* tool call (tier check passed) to the
existing session_state ledger (`runtime.session_state`) -- no new storage
mechanism, same file-backed hash-chained ledger `dispatch`, `orchestrator
chat`, and `addons submit` already use. Every event is tagged
`caller="mcp"`. Args are summarized (long strings truncated, known-sensitive
keys redacted by length only) so the ledger never becomes a second place a
secret or a full prompt leaks -- locked decision, issue #184 step 3 / #187
plan item 5.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {
    "prompt", "value", "token", "secret", "password", "credential",
    "api_key", "apikey", "authorization",
    # Defense in depth: protocol.py already pops "mandate"/"mandate_context"
    # out of `arguments` before it ever reaches audit.record, so these keys
    # should never actually be present here -- but if a future call site
    # forgets to pop them, they must never leak the envelope/signature into
    # the ledger (ADR-032).
    "mandate", "mandate_context",
}
_MAX_STR_LEN = 120


def summarize_args(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Args-summary only, never verbatim: redact known-sensitive keys down
    to just a length marker, truncate long strings, pass small/plain values
    through unchanged, and stringify anything else down to its type name."""
    if not arguments:
        return {}
    summary: dict[str, Any] = {}
    for key, value in arguments.items():
        if key.lower() in _SENSITIVE_KEYS:
            length = len(value) if isinstance(value, str) else None
            summary[key] = f"<redacted len={length}>" if length is not None else "<redacted>"
        elif isinstance(value, str) and len(value) > _MAX_STR_LEN:
            summary[key] = value[:_MAX_STR_LEN] + f"...<truncated, len={len(value)}>"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, (list, tuple)):
            summary[key] = list(value)[:20]
        else:
            summary[key] = f"<{type(value).__name__}>"
    return summary


class AuditLog:
    """One session_state session per server process, created lazily on the
    first accepted call and reused for the life of the connection -- one
    stdio connection is one session, same shape `orchestrator chat` already
    uses for its own conversational ledger."""

    def __init__(self, store: Path, task_id: str = "mcp-server") -> None:
        self._store = store
        self._task_id = task_id
        self._session_id: str | None = None
        self._sequence = 0

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def record(
        self,
        tool: str,
        arguments: dict[str, Any] | None,
        *,
        status: str = "accepted",
        mandate_id: str | None = None,
        mandate_decision: str | None = None,
    ) -> None:
        """Append one `mcp.tool_call` ledger event. `mandate_id` and
        `mandate_decision` are always written (as `null` when there's no
        mandate to report -- e.g. a Tier-0 call) rather than omitted, so
        every event has the same shape (ADR-032 / issue #206 AC 5). Never
        pass the mandate envelope itself here -- only its `mandate_id` and
        a short decision string; `summarize_args` also redacts a stray
        `mandate`/`mandate_context` key as defense in depth."""
        from runtime import session_state as state

        if self._session_id is None:
            session = state.create(self._store, task_id=self._task_id, worker_role="mcp", runtime="mcp")
            self._session_id = session["session_id"]
        state.append(
            self._store, self._session_id, self._sequence, "mcp.tool_call",
            {
                "tool": tool,
                "args_summary": summarize_args(arguments),
                "caller": "mcp",
                "status": status,
                "mandate_id": mandate_id,
                "mandate_decision": mandate_decision,
            },
        )
        self._sequence += 1
