"""Session status: reads real Cortxt session state, not Hermes's Kanban DB.

ADR-016 requires Hermes stay a swappable adapter, not a core dependency of
Cortxt's own status views, so this reads runtime/session_state.py's
event-sourced session log directly.

`write_snapshot()` is the CLI/widget wiring point: the CLI writes the same
`load_sessions()` output the table is rendered from, and the widget (served
statically by agent-platform/widget/serve.py) polls that file — one data
source, not two independently-fetched views that can drift.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

_AGENT_PLATFORM_ROOT = Path(__file__).resolve().parent.parent
if str(_AGENT_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_PLATFORM_ROOT))

from runtime import session_state as state  # noqa: E402

logger = logging.getLogger(__name__)

# A session with no terminal event yet is still running. Failed is a
# distinct, more alarming signal than blocked/warn -- they aren't the
# same severity of problem.
DEFAULT_STATUS = "running"
STATUS_SEVERITY = {
    "running": "info",
    "succeeded": "ok",
    "blocked": "warn",
    "failed": "error",
    "timed_out": "error",
}


def _session_status(doc: dict[str, Any]) -> tuple[str, str]:
    """Derive (status, updated_at) from a session's event chain.

    The terminal status comes from the last `session.terminal` event if one
    exists; otherwise the session is still running and "updated_at" is its
    most recent event's timestamp.
    """
    for event in reversed(doc["events"]):
        if event["event_type"] == "session.terminal":
            return event["payload"].get("status", DEFAULT_STATUS), event["timestamp"]
    return DEFAULT_STATUS, doc["events"][-1]["timestamp"]


def load_sessions(store: Path) -> list[dict[str, Any]]:
    """Load every session under `store`.

    A session directory that fails to load (missing/corrupt session.json,
    broken hash chain) is skipped, not silently dropped -- it's logged with
    its id and the reason so the gap is visible instead of just missing.
    """
    sessions: list[dict[str, Any]] = []
    if not store.is_dir():
        return sessions

    for session_dir in sorted(store.iterdir()):
        if not session_dir.is_dir():
            continue
        session_id = session_dir.name
        try:
            doc = state.load(store, session_id)
        except state.SessionError as error:
            logger.warning(
                "skipping session %s: %s (%s)", session_id, error.message, error.category
            )
            continue
        if not doc["events"]:
            # Valid JSON, valid hash chain (there's nothing to break), but
            # no session.created event to read an identity from -- same
            # "can't use this" bucket as a SessionError, so skip+log it too.
            logger.warning("skipping session %s: no events", session_id)
            continue

        task_id = doc["events"][0]["payload"].get("task_id", session_id)
        status, updated_at = _session_status(doc)
        sessions.append(
            {
                "session_id": session_id,
                "task_id": task_id,
                "status": status,
                "severity": STATUS_SEVERITY.get(status, "info"),
                "updated_at": updated_at,
            }
        )
    return sessions


def render_table(sessions: list[dict[str, Any]]) -> str:
    """Human-readable CLI table for `cortxt sessions`."""
    if not sessions:
        return "No sessions found."
    header = f"{'TASK':<30} {'STATUS':<12} {'UPDATED':<28} SESSION"
    lines = [header, "-" * len(header)]
    for s in sessions:
        lines.append(f"{s['task_id']:<30} {s['status']:<12} {s['updated_at']:<28} {s['session_id']}")
    return "\n".join(lines)


def write_snapshot(sessions: list[dict[str, Any]], snapshot_path: Path) -> None:
    """Atomically write the JSON snapshot the widget polls.

    Same write pattern as session_state._atomic_write: tempfile in the
    target directory + os.replace, so a reader never sees a half-written
    file.
    """
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"generated_at": state.utc_now(), "sessions": sessions}
    descriptor, tmp = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=snapshot_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, snapshot_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
