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
from datetime import datetime, timezone
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
DEFAULT_STALE_AFTER_SECONDS = 300


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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


def load_sessions(
    store: Path,
    *,
    now: datetime | None = None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
) -> list[dict[str, Any]]:
    """Load every session under `store`.

    A session directory that fails to load (missing/corrupt session.json,
    broken hash chain) is skipped, not silently dropped -- it's logged with
    its id and the reason so the gap is visible instead of just missing.
    """
    sessions: list[dict[str, Any]] = []
    observed_at = now or datetime.now(timezone.utc)
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

        created_payload = doc["events"][0]["payload"]
        task_id = created_payload.get("task_id", session_id)
        status, updated_at = _session_status(doc)
        age_seconds = max(0.0, (observed_at - _parse_timestamp(updated_at)).total_seconds())
        is_stale = status == "running" and age_seconds > stale_after_seconds
        display_status = "stale" if is_stale else status
        sessions.append(
            {
                "session_id": session_id,
                "task_id": task_id,
                "status": status,
                "display_status": display_status,
                "severity": "warn" if is_stale else STATUS_SEVERITY.get(status, "info"),
                "updated_at": updated_at,
                "age_seconds": round(age_seconds, 3),
                "is_stale": is_stale,
                "workstream_id": created_payload.get("workstream_id") or created_payload.get("issue_id") or task_id,
                "run_id": created_payload.get("run_id") or session_id,
                "issue_id": created_payload.get("issue_id"),
                "branch": created_payload.get("branch"),
                "worktree": created_payload.get("worktree"),
                "worker_role": created_payload.get("worker_role") or "agent",
                "runtime": created_payload.get("runtime"),
                "segments": _segments_from_events(doc["events"], display_status),
                "activity": [
                    {"event_type": event["event_type"], "timestamp": event["timestamp"]}
                    for event in doc["events"][-12:]
                ],
            }
        )
    return sessions


def _segments_from_events(events: list[dict[str, Any]], display_status: str) -> list[dict[str, Any]]:
    """Project append-only events into small, UI-safe timeline intervals."""
    if not events:
        return []
    start = events[0]["timestamp"]
    end = events[-1]["timestamp"]
    terminal = next((e for e in reversed(events) if e["event_type"] == "session.terminal"), None)
    running_end = terminal["timestamp"] if terminal else end
    segments = [{"state": "running", "started_at": start, "finished_at": running_end}]
    if terminal:
        terminal_state = terminal["payload"].get("status", display_status)
        segments.append(
            {
                "state": terminal_state,
                "started_at": terminal["timestamp"],
                "finished_at": terminal["timestamp"],
            }
        )
    elif display_status == "stale":
        segments.append({"state": "stale", "started_at": end, "finished_at": None})
    return segments


def build_workstreams(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group agent sessions into operator-visible workstreams."""
    grouped: dict[str, dict[str, Any]] = {}
    for session in sessions:
        workstream_id = str(session["workstream_id"])
        workstream = grouped.setdefault(
            workstream_id,
            {
                "workstream_id": workstream_id,
                "issue_id": session.get("issue_id"),
                "workspace": {
                    "branch": session.get("branch"),
                    "worktree": session.get("worktree"),
                },
                "status": "idle",
                "updated_at": session["updated_at"],
                "lanes": [],
            },
        )
        workstream["updated_at"] = max(workstream["updated_at"], session["updated_at"])
        workstream["lanes"].append(
            {
                "lane_id": session["session_id"],
                "label": session.get("worker_role") or "agent",
                "runtime": session.get("runtime"),
                "run_id": session.get("run_id"),
                "session_id": session["session_id"],
                "status": session["display_status"],
                "severity": session["severity"],
                "segments": session["segments"],
            }
        )

    priority = {"failed": 6, "blocked": 5, "stale": 4, "running": 3, "timed_out": 2, "succeeded": 1}
    for workstream in grouped.values():
        lane_statuses = [lane["status"] for lane in workstream["lanes"]]
        workstream["status"] = max(lane_statuses, key=lambda value: priority.get(value, 0))
    return sorted(grouped.values(), key=lambda item: item["updated_at"], reverse=True)


def build_orchestrator_summary(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    active = [s for s in sessions if s["status"] == "running" and not s["is_stale"]]
    stale = [s for s in sessions if s["is_stale"]]
    blocked = [s for s in sessions if s["status"] == "blocked"]
    failed = [s for s in sessions if s["status"] in {"failed", "timed_out"}]
    attention = len(stale) + len(blocked) + len(failed)
    return {
        "status": "attention" if attention else ("working" if active else "idle"),
        "active_agent_sessions": len(active),
        "stale_agent_sessions": len(stale),
        "blocked_agent_sessions": len(blocked),
        "failed_agent_sessions": len(failed),
        "attention_items": attention,
        "message": (
            f"{len(active)} active; {attention} need attention"
            if active or attention
            else "No verified agent work is active"
        ),
    }


def build_activity(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a payload-free activity feed suitable for the compact widget."""
    items: list[dict[str, Any]] = []
    for session in sessions:
        for event in session.get("activity", []):
            items.append(
                {
                    "timestamp": event["timestamp"],
                    "event_type": event["event_type"],
                    "workstream_id": session.get("workstream_id"),
                    "actor": session.get("worker_role") or session.get("runtime") or "agent",
                    "runtime": session.get("runtime"),
                }
            )
    return sorted(items, key=lambda item: item["timestamp"], reverse=True)[:80]


def render_table(sessions: list[dict[str, Any]]) -> str:
    """Human-readable CLI table for `cortxt sessions`."""
    if not sessions:
        return "No sessions found."
    header = f"{'TASK':<30} {'STATUS':<12} {'UPDATED':<28} SESSION"
    lines = [header, "-" * len(header)]
    for s in sessions:
        lines.append(f"{s['task_id']:<30} {s.get('display_status', s['status']):<12} {s['updated_at']:<28} {s['session_id']}")
    return "\n".join(lines)


def write_snapshot(
    sessions: list[dict[str, Any]] | None,
    snapshot_path: Path,
    *,
    runtimes: list[dict[str, Any]] | None = None,
    credentials: list[dict[str, Any]] | None = None,
    daemon: dict[str, Any] | None = None,
    engines: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
    profiles: list[dict[str, Any]] | None = None,
) -> None:
    """Atomically write the JSON snapshot the widget polls.

    `runtimes`/`credentials`/`daemon` are optional admin-surface data (Fas 4) the
    widget can render alongside sessions. Every call to this function
    rewrites the whole document, but not every caller knows about all
    keys (`_run_runtimes` only has `runtimes`, `_refresh_credentials_snapshot`
    only has `credentials`, and `sessions`/`dispatch`/`addons` have neither) --
    so `None` means "caller didn't supply this", not "clear it". When a key
    isn't supplied, carry forward whatever value is already in the existing
    snapshot file at `snapshot_path`, if any, so one command's write doesn't
    clobber another command's data (review finding: this is what made the
    widget's runtimes/credentials panels flicker empty depending on which
    command ran last). If the existing file doesn't exist or isn't valid
    JSON, fall back to omitting the key exactly as before -- never raise
    over a missing/corrupt previous snapshot.

    Same write pattern as session_state._atomic_write: tempfile in the
    target directory + os.replace, so a reader never sees a half-written
    file.
    """
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        existing = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    if sessions is None:
        sessions = existing.get("sessions", [])

    if (
        runtimes is None or credentials is None or daemon is None or engines is None
        or skills is None or profiles is None
    ):
        if runtimes is None:
            runtimes = existing.get("runtimes")
        if credentials is None:
            credentials = existing.get("credentials")
        if daemon is None:
            daemon = existing.get("daemon")
        if engines is None:
            engines = existing.get("engines")
        if skills is None:
            skills = existing.get("skills")
        if profiles is None:
            profiles = existing.get("profiles")

    workstreams = build_workstreams(sessions)
    known_workstreams = {item["workstream_id"] for item in workstreams}
    for daemon_workstream in (daemon or {}).get("workstreams", []):
        if daemon_workstream.get("workstream_id") not in known_workstreams:
            workstreams.append(daemon_workstream)

    doc: dict[str, Any] = {
        "schema_version": 2,
        "generated_at": state.utc_now(),
        "orchestrator": build_orchestrator_summary(sessions),
        "workstreams": workstreams,
        "sessions": sessions,
        "activity": build_activity(sessions),
    }
    if runtimes is not None:
        doc["runtimes"] = runtimes
    if credentials is not None:
        doc["credentials"] = credentials
    if daemon is not None:
        doc["daemon"] = daemon
    if engines is not None:
        doc["engines"] = engines
    if skills is not None:
        doc["skills"] = skills
    if profiles is not None:
        doc["profiles"] = profiles
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
