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
_CLI_DIR = Path(__file__).resolve().parent
if str(_CLI_DIR) not in sys.path:
    sys.path.insert(0, str(_CLI_DIR))

from runtime import session_state as state  # noqa: E402

# Bare (not `from . import`) because this module is sometimes loaded as a
# standalone top-level module (`import status`, cli_dir on sys.path) rather
# than as the `cli` package's `status` submodule -- see the "Normal import"
# note on `_run_sessions` in unified_cli.py. A relative import breaks under
# that loading path with "attempted relative import with no known parent
# package"; a bare import with cli_dir on sys.path works either way.
import color as color_cli  # noqa: E402

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

# An operator can append this event to a session's log to correct automatic
# staleness inference (e.g. mark a closed-but-never-terminated REPL window
# abandoned immediately, instead of waiting for `stale_after_seconds` to
# elapse). Purely additive: it never rewrites or removes prior events.
ARCHIVE_EVENT_TYPE = "session.archived"

# Three-way derived lifecycle classification, computed at read time from the
# append-only event log -- never stored, never mutates history:
#   running   -- no terminal event yet, and recently active.
#   terminal  -- has a session.terminal event (succeeded/failed/blocked/...).
#   abandoned -- no terminal event, but either exceeded the staleness
#                threshold or was explicitly archived by an operator. This
#                replaces the old binary "stale" flag: it's a distinct state,
#                not just a relabeling, because it changes how segments are
#                projected (see _segments_from_events) so an abandoned
#                session's open segment stops extending to "now".
LIFECYCLE_RUNNING = "running"
LIFECYCLE_TERMINAL = "terminal"
LIFECYCLE_ABANDONED = "abandoned"


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


def _archived_event(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Most recent operator-recorded archival event, if any.

    Only meaningful for a session with no terminal event -- a session that
    already ended (succeeded/failed/blocked/timed_out) doesn't need operator
    correction, its lifecycle is already unambiguous.
    """
    for event in reversed(doc["events"]):
        if event["event_type"] == ARCHIVE_EVENT_TYPE:
            return event
    return None


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

        if status != DEFAULT_STATUS:
            lifecycle = LIFECYCLE_TERMINAL
            archived_event = None
        else:
            archived_event = _archived_event(doc)
            auto_abandoned = age_seconds > stale_after_seconds
            lifecycle = LIFECYCLE_ABANDONED if (archived_event or auto_abandoned) else LIFECYCLE_RUNNING
        is_abandoned = lifecycle == LIFECYCLE_ABANDONED
        display_status = LIFECYCLE_ABANDONED if is_abandoned else status
        # An operator-recorded archive event is authoritative about *when*
        # the session was last known to be active -- prefer its timestamp
        # over the last raw event when capping the abandoned segment.
        last_activity_at = archived_event["timestamp"] if archived_event else updated_at

        sessions.append(
            {
                "session_id": session_id,
                "task_id": task_id,
                "status": status,
                "display_status": display_status,
                "severity": "warn" if is_abandoned else STATUS_SEVERITY.get(status, "info"),
                "updated_at": updated_at,
                "age_seconds": round(age_seconds, 3),
                "lifecycle": lifecycle,
                "is_abandoned": is_abandoned,
                "workstream_id": created_payload.get("workstream_id") or created_payload.get("issue_id") or task_id,
                "run_id": created_payload.get("run_id") or session_id,
                "issue_id": created_payload.get("issue_id"),
                "branch": created_payload.get("branch"),
                "worktree": created_payload.get("worktree"),
                "worker_role": created_payload.get("worker_role") or "agent",
                "runtime": created_payload.get("runtime"),
                "plan_task_ref": created_payload.get("plan_task_ref"),
                "started_at": doc["events"][0]["timestamp"],
                "segments": _segments_from_events(doc["events"], display_status, last_activity_at),
                "activity": [
                    {"event_type": event["event_type"], "timestamp": event["timestamp"]}
                    for event in doc["events"][-12:]
                ],
            }
        )
    return sessions


def _segments_from_events(
    events: list[dict[str, Any]], display_status: str, last_activity_at: str | None = None
) -> list[dict[str, Any]]:
    """Project append-only events into small, UI-safe timeline intervals.

    `last_activity_at` is the abandoned-session's own last-known-activity
    timestamp (from `load_sessions`). A trailing "abandoned" marker segment
    is capped there instead of left open (`finished_at: None`) -- an open
    segment reads as "still running" to any consumer that fills in "now" for
    a missing end time (the widget's Gantt axis did exactly that, which is
    why a session abandoned hours ago dominated the chart on every reload).
    A genuinely still-running session's segment keeps no such marker, so it
    is free to still extend to "now" in the UI -- that's correct for it.
    """
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
    elif display_status == LIFECYCLE_ABANDONED:
        marker_at = last_activity_at or end
        segments.append({"state": LIFECYCLE_ABANDONED, "started_at": marker_at, "finished_at": marker_at})
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
                "branch": session.get("branch"),
                "started_at": session.get("started_at"),
                "status": session["display_status"],
                "severity": session["severity"],
                "segments": session["segments"],
            }
        )

    priority = {"failed": 6, "blocked": 5, "abandoned": 4, "running": 3, "timed_out": 2, "succeeded": 1}
    for workstream in grouped.values():
        lane_statuses = [lane["status"] for lane in workstream["lanes"]]
        workstream["status"] = max(lane_statuses, key=lambda value: priority.get(value, 0))
    return sorted(grouped.values(), key=lambda item: item["updated_at"], reverse=True)


def build_orchestrator_summary(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    active = [s for s in sessions if s["status"] == "running" and not s["is_abandoned"]]
    abandoned = [s for s in sessions if s["is_abandoned"]]
    blocked = [s for s in sessions if s["status"] == "blocked"]
    failed = [s for s in sessions if s["status"] in {"failed", "timed_out"}]
    attention = len(abandoned) + len(blocked) + len(failed)
    return {
        "status": "attention" if attention else ("working" if active else "idle"),
        "active_agent_sessions": len(active),
        "abandoned_agent_sessions": len(abandoned),
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


def format_lane_summary(lane: dict[str, Any]) -> str:
    """Compact, distinguishing one-line summary for a single lane.

    Every lane in a workstream can share the same `label` (worker_role) and
    `runtime` -- that was the whole bug this exists to fix: every lane
    rendered as the identical generic "orchestrator - codex" string, with no
    way to tell 10 different sessions apart. session_id already uniquely
    identifies a lane, so a short suffix of it -- plus branch and a real
    start timestamp, both of which already exist on every session -- is
    enough to distinguish lanes without inventing new data.
    """
    label = lane.get("label") or "agent"
    runtime = lane.get("runtime") or "runtime okand"
    session_id = lane.get("session_id") or lane.get("lane_id") or ""
    suffix = session_id[-8:] if session_id else "--------"
    branch = lane.get("branch") or "no branch"
    started_at = lane.get("started_at") or "unknown start"
    return f"{label} ({runtime}) #{suffix} {branch} started {started_at}"


def render_table(sessions: list[dict[str, Any]], *, color: bool | None = None) -> str:
    """Human-readable CLI table for `cortxt sessions`.

    `color=None` auto-detects (real terminal -> colored, piped/captured ->
    plain); pass True/False to force it. Status text is colored, not the
    fixed-width padding around it, so column alignment survives either way.
    """
    if not sessions:
        return "No sessions found."
    header = f"{'TASK':<30} {'STATUS':<12} {'UPDATED':<28} SESSION"
    lines = [header, "-" * len(header)]
    for s in sessions:
        status_text = s.get("display_status", s["status"])
        status_cell = color_cli.colorize(f"{status_text:<12}", status_text, enabled=color)
        lines.append(f"{s['task_id']:<30} {status_cell} {s['updated_at']:<28} {s['session_id']}")
    return "\n".join(lines)


def render_status_table(
    summary: dict[str, Any], workstreams: list[dict[str, Any]], *, color: bool | None = None
) -> str:
    """Ledger view for `cortxt status`: one row per workstream, not per session.

    A workstream groups its agent sessions into lanes (see
    `build_workstreams`); this table shows the workstream-level rollup an
    operator scans first, leaving the per-session detail to `cortxt sessions`
    and the live per-lane view to `cortxt pipeline`.

    `color=None` auto-detects; pass True/False to force it.
    """
    overall_status = summary.get("status", "idle")
    status_text = color_cli.colorize(overall_status, overall_status, enabled=color)
    lines = [f"Status: {status_text} -- {summary.get('message', '')}", ""]
    if not workstreams:
        lines.append("No workstreams found.")
        return "\n".join(lines)
    header = f"{'WORKSTREAM':<28} {'STATUS':<10} {'LANES':<6} {'BRANCH':<30} UPDATED"
    lines.append(header)
    lines.append("-" * len(header))
    for workstream in workstreams:
        branch = workstream["workspace"].get("branch") or "-"
        status_cell = color_cli.colorize(f"{workstream['status']:<10}", workstream["status"], enabled=color)
        lines.append(
            f"{workstream['workstream_id']:<28} {status_cell} "
            f"{len(workstream['lanes']):<6} {branch:<30} {workstream['updated_at']}"
        )
        for lane in workstream.get("lanes", []):
            lines.append(f"    - {format_lane_summary(lane)}")
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
    work: list[dict[str, Any]] | None = None,
) -> None:
    """Atomically write the JSON snapshot the widget polls.

    `runtimes`/`credentials`/`daemon` are optional admin-surface data (Phase 4) the
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
        or skills is None or profiles is None or work is None
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
        if work is None:
            work = existing.get("work")

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
    if work is None:
        work = [
            {"issue_id": item.get("issue_id"), "run_id": item.get("run_id"),
             "runtime": item.get("runtime"), "worker": item.get("worker_role"),
             "status": item.get("display_status"), "updated_at": item.get("updated_at"),
             "issue_url": item.get("issue_url"), "pr_url": item.get("pr_url")}
            for item in sessions if item.get("run_id") and item.get("display_status") == "running"
        ]
    doc["work"] = work
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
