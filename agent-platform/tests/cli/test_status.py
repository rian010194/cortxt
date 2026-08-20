from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime import session_state as state

from cli import status


def test_load_sessions_empty_store_returns_empty_list(tmp_path):
    assert status.load_sessions(tmp_path / "sessions") == []


def test_load_sessions_missing_store_dir_returns_empty_list(tmp_path):
    assert status.load_sessions(tmp_path / "does-not-exist") == []


def test_load_sessions_loads_a_real_running_session(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="wire-widget-to-cli")
    session_id = session["session_id"]

    sessions = status.load_sessions(store)

    assert len(sessions) == 1
    entry = sessions[0]
    assert entry["session_id"] == session_id
    assert entry["task_id"] == "wire-widget-to-cli"
    assert entry["status"] == "running"
    assert entry["severity"] == "info"
    assert entry["updated_at"] == session["events"][0]["timestamp"]


def test_load_sessions_reflects_terminal_status_and_severity(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="fas2-follow-up")
    session_id = session["session_id"]
    state.append(store, session_id, 0, "session.terminal", {"status": "failed"})

    sessions = status.load_sessions(store)

    assert sessions[0]["status"] == "failed"
    # failed must not share a severity with blocked -- it's a worse signal.
    assert sessions[0]["severity"] == "error"
    assert sessions[0]["severity"] != status.STATUS_SEVERITY["blocked"]


def test_load_sessions_maps_timed_out_status_to_error_severity(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="orchestrator-dispatch-timeout")
    state.append(store, session["session_id"], 0, "session.terminal", {"status": "timed_out"})
    sessions = status.load_sessions(store)
    assert sessions[0]["status"] == "timed_out"
    assert sessions[0]["severity"] == "error"


def test_load_sessions_classifies_old_unfinished_work_as_abandoned(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="abandoned-run")
    created = session["events"][0]["timestamp"]
    now = datetime.fromisoformat(created.replace("Z", "+00:00")) + timedelta(minutes=6)

    entry = status.load_sessions(store, now=now, stale_after_seconds=300)[0]

    assert entry["status"] == "running"
    assert entry["display_status"] == "abandoned"
    assert entry["is_abandoned"] is True
    assert entry["lifecycle"] == "abandoned"
    assert entry["segments"][-1]["state"] == "abandoned"


def test_load_sessions_lifecycle_is_running_for_fresh_running_session(tmp_path):
    store = tmp_path / "sessions"
    state.create(store, task_id="fresh-run")

    entry = status.load_sessions(store)[0]

    assert entry["lifecycle"] == "running"
    assert entry["is_abandoned"] is False
    assert entry["display_status"] == "running"


def test_load_sessions_lifecycle_is_terminal_for_any_terminal_status(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="finished-run")
    state.append(store, session["session_id"], 0, "session.terminal", {"status": "blocked"})

    entry = status.load_sessions(store)[0]

    assert entry["lifecycle"] == "terminal"
    assert entry["is_abandoned"] is False
    assert entry["status"] == "blocked"


def test_load_sessions_abandoned_segment_is_capped_at_last_activity_not_open_ended(tmp_path):
    """Regression test for the widget's Gantt axis bug: an abandoned
    session's trailing segment must carry a concrete `finished_at` (its own
    last-known-activity timestamp), not `None`. The widget's JS falls back
    to `new Date()` for a null `finished_at`, which made every abandoned
    session's bar -- and the whole axis -- stretch to "now" on every page
    load, no matter how long ago the session was actually abandoned.
    """
    store = tmp_path / "sessions"
    session = state.create(store, task_id="abandoned-run")
    created = session["events"][0]["timestamp"]
    now = datetime.fromisoformat(created.replace("Z", "+00:00")) + timedelta(hours=7)

    entry = status.load_sessions(store, now=now, stale_after_seconds=300)[0]

    abandoned_segment = entry["segments"][-1]
    assert abandoned_segment["state"] == "abandoned"
    assert abandoned_segment["finished_at"] is not None
    assert abandoned_segment["finished_at"] == entry["updated_at"]


def test_load_sessions_operator_archived_event_forces_abandoned_before_threshold(tmp_path):
    """An operator can record an explicit `session.archived` event to correct
    automatic staleness inference -- e.g. to mark a session abandoned
    immediately, without waiting for `stale_after_seconds` to elapse."""
    store = tmp_path / "sessions"
    session = state.create(store, task_id="operator-archived")
    state.append(
        store, session["session_id"], 0, "session.archived", {"reason": "operator closed REPL"}
    )

    entry = status.load_sessions(store, stale_after_seconds=300)[0]

    assert entry["lifecycle"] == "abandoned"
    assert entry["is_abandoned"] is True
    assert entry["display_status"] == "abandoned"
    assert entry["segments"][-1]["finished_at"] is not None


def test_workstream_groups_agent_sessions_and_keeps_workspace_metadata(tmp_path):
    store = tmp_path / "sessions"
    state.create(
        store,
        task_id="builder-step",
        workstream_id="issue-180",
        run_id="run-2",
        issue_id="owner/repo#180",
        branch="daemon/issue-180",
        worker_role="builder",
        runtime="hermes",
    )
    sessions = status.load_sessions(store, now=datetime.now(timezone.utc))

    workstream = status.build_workstreams(sessions)[0]

    assert workstream["workstream_id"] == "issue-180"
    assert workstream["workspace"]["branch"] == "daemon/issue-180"
    assert workstream["lanes"][0]["label"] == "builder"
    assert workstream["lanes"][0]["runtime"] == "hermes"


def test_load_sessions_includes_started_at(tmp_path):
    """`started_at` is the session's first (creation) event timestamp -- it
    already exists inside `segments[0]["started_at"]`, but callers that just
    want "when did this session begin" for a distinguishing label shouldn't
    have to reach into the segments projection to get it."""
    store = tmp_path / "sessions"
    session = state.create(store, task_id="wire-widget-to-cli")

    entry = status.load_sessions(store)[0]

    assert entry["started_at"] == session["events"][0]["timestamp"]


def test_build_workstreams_lanes_carry_distinguishing_metadata(tmp_path):
    """Two lanes in the same workstream with the same worker_role/runtime
    must still be distinguishable: each lane needs its own branch and a real
    start timestamp alongside the session_id it already carries (Codex
    review finding: session_id, branch, runtime, and start time already
    exist per-session and should be surfaced onto the lane, not invented)."""
    store = tmp_path / "sessions"
    state.create(
        store,
        task_id="task-a",
        workstream_id="issue-180",
        branch="daemon/issue-180-a",
        worker_role="orchestrator",
        runtime="codex",
    )
    state.create(
        store,
        task_id="task-b",
        workstream_id="issue-180",
        branch="daemon/issue-180-b",
        worker_role="orchestrator",
        runtime="codex",
    )
    sessions = status.load_sessions(store, now=datetime.now(timezone.utc))

    workstream = status.build_workstreams(sessions)[0]
    lanes = workstream["lanes"]

    assert len(lanes) == 2
    branches = {lane["branch"] for lane in lanes}
    assert branches == {"daemon/issue-180-a", "daemon/issue-180-b"}
    for lane in lanes:
        assert lane["started_at"]
        assert lane["session_id"]


def test_lane_summary_distinguishes_two_same_role_same_runtime_lanes():
    """The whole point of this feature: two lanes that would otherwise
    render as the identical generic string ("orchestrator - codex") must
    produce different summary strings once session_id/branch/timestamp are
    folded in."""
    lane_a = {
        "session_id": "session_" + "a" * 32,
        "label": "orchestrator",
        "runtime": "codex",
        "branch": "daemon/issue-180-a",
        "started_at": "2026-08-20T10:00:00.000000Z",
        "status": "running",
    }
    lane_b = {
        "session_id": "session_" + "b" * 32,
        "label": "orchestrator",
        "runtime": "codex",
        "branch": "daemon/issue-180-b",
        "started_at": "2026-08-20T10:05:00.000000Z",
        "status": "running",
    }

    summary_a = status.format_lane_summary(lane_a)
    summary_b = status.format_lane_summary(lane_b)

    assert summary_a != summary_b
    # session_id suffix, not the full 40-char id, keeps it compact.
    assert "aaaaaaaa" in summary_a
    assert "session_" not in summary_a
    assert "daemon/issue-180-a" in summary_a
    assert "2026-08-20T10:00:00.000000Z" in summary_a


def test_lane_summary_shows_no_branch_when_branch_missing():
    lane = {
        "session_id": "session_" + "c" * 32,
        "label": "agent",
        "runtime": None,
        "branch": None,
        "started_at": "2026-08-20T10:00:00.000000Z",
        "status": "running",
    }

    summary = status.format_lane_summary(lane)

    assert "no branch" in summary


def test_render_status_table_includes_per_lane_summary_lines():
    """`cortxt status` shows a workstream summary row today, but the lanes
    beneath it are indistinguishable (just a count). Each lane needs its own
    line with session_id-suffix + branch + timestamp."""
    summary = {"status": "working", "message": "1 active; 0 need attention"}
    workstreams = [
        {
            "workstream_id": "issue-180",
            "status": "running",
            "updated_at": "2026-08-20T00:00:00.000000Z",
            "workspace": {"branch": "daemon/issue-180", "worktree": None},
            "lanes": [
                {
                    "lane_id": "session-1",
                    "session_id": "session_" + "1" * 32,
                    "label": "orchestrator",
                    "runtime": "codex",
                    "branch": "daemon/issue-180-a",
                    "started_at": "2026-08-20T00:00:00.000000Z",
                    "status": "running",
                },
                {
                    "lane_id": "session-2",
                    "session_id": "session_" + "2" * 32,
                    "label": "orchestrator",
                    "runtime": "codex",
                    "branch": "daemon/issue-180-b",
                    "started_at": "2026-08-20T00:05:00.000000Z",
                    "status": "running",
                },
            ],
        }
    ]

    table = status.render_status_table(summary, workstreams)

    assert "daemon/issue-180-a" in table
    assert "daemon/issue-180-b" in table
    assert "11111111" in table
    assert "22222222" in table


def test_load_sessions_skips_and_logs_malformed_session(tmp_path, caplog):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="good-session")
    good_id = session["session_id"]

    bad_id = "session_" + "0" * 32
    bad_dir = store / bad_id
    bad_dir.mkdir(parents=True)
    (bad_dir / "session.json").write_text("not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        sessions = status.load_sessions(store)

    assert [s["session_id"] for s in sessions] == [good_id]
    assert any(bad_id in record.message for record in caplog.records)


def test_load_sessions_skips_and_logs_a_session_with_no_events(tmp_path, caplog):
    """A session.json with events: [] has a trivially valid (empty) hash
    chain -- state.load() doesn't reject it -- but there's no
    session.created event to read an identity from. Must be skipped like
    any other unusable session, not crash the whole listing.
    """
    store = tmp_path / "sessions"
    session = state.create(store, task_id="good-session")
    good_id = session["session_id"]

    empty_id = "session_" + "1" * 32
    empty_dir = store / empty_id
    empty_dir.mkdir(parents=True)
    doc = {"schema_version": 1, "session_id": empty_id, "events": []}
    (empty_dir / "session.json").write_text(json.dumps(doc), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        sessions = status.load_sessions(store)

    assert [s["session_id"] for s in sessions] == [good_id]
    assert any(empty_id in record.message for record in caplog.records)


def test_render_table_reports_no_sessions_when_empty():
    assert status.render_table([]) == "No sessions found."


def test_render_table_includes_task_and_status():
    sessions = [
        {
            "session_id": "session_" + "1" * 32,
            "task_id": "example-task",
            "status": "succeeded",
            "severity": "ok",
            "updated_at": "2026-08-18T00:00:00.000000Z",
        }
    ]
    table = status.render_table(sessions)
    assert "example-task" in table
    assert "succeeded" in table


def test_write_snapshot_is_the_same_data_the_table_is_rendered_from(tmp_path):
    store = tmp_path / "sessions"
    state.create(store, task_id="snapshot-source-of-truth")
    sessions = status.load_sessions(store)

    snapshot_path = tmp_path / "widget" / "snapshot.json"
    status.write_snapshot(sessions, snapshot_path)

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["sessions"] == sessions
    assert "generated_at" in doc


def test_write_snapshot_omits_runtimes_and_credentials_by_default(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    status.write_snapshot([], snapshot_path)

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "runtimes" not in doc
    assert "credentials" not in doc


def test_write_snapshot_includes_runtimes_and_credentials_when_given(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    runtimes = [{"runtime_id": "hermes", "installed": True, "path": "/usr/bin/hermes"}]
    credentials = [{"credential_id": "openai-key", "last_action": "store", "last_result": "ok", "last_timestamp": "2026-08-19T10:00:00Z"}]

    status.write_snapshot([], snapshot_path, runtimes=runtimes, credentials=credentials)

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["runtimes"] == runtimes
    assert doc["credentials"] == credentials


def test_write_snapshot_preserves_runtimes_across_a_later_credentials_only_call(tmp_path):
    """Review finding: _run_runtimes and _refresh_credentials_snapshot each
    only pass the one key they know about. Without carry-forward, a
    `credentials` call made after a `runtimes` call silently wipes the
    `runtimes` key (and vice versa) because write_snapshot rebuilds the
    whole document from scratch every time."""
    snapshot_path = tmp_path / "snapshot.json"
    runtimes = [{"runtime_id": "hermes", "installed": True, "path": "/usr/bin/hermes"}]
    credentials = [{"credential_id": "openai-key", "last_action": "store", "last_result": "ok", "last_timestamp": "2026-08-19T10:00:00Z"}]

    status.write_snapshot([], snapshot_path, runtimes=runtimes)
    status.write_snapshot([], snapshot_path, credentials=credentials)

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["runtimes"] == runtimes
    assert doc["credentials"] == credentials


def test_write_snapshot_includes_daemon_section(tmp_path):
    from cli import status

    snapshot_path = tmp_path / "snapshot.json"
    status.write_snapshot([], snapshot_path, daemon={"status": "idle", "claimed": []})

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["daemon"] == {"status": "idle", "claimed": []}


def test_write_snapshot_preserves_daemon_when_omitted(tmp_path):
    from cli import status

    snapshot_path = tmp_path / "snapshot.json"
    status.write_snapshot([], snapshot_path, daemon={"status": "running", "claimed": ["owner/repo#1"]})
    status.write_snapshot([], snapshot_path, runtimes=[{"name": "hermes"}])  # daemon omitted this call

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["daemon"] == {"status": "running", "claimed": ["owner/repo#1"]}
    assert doc["runtimes"] == [{"name": "hermes"}]


def test_write_snapshot_replaces_the_file_atomically(tmp_path, monkeypatch):
    """A live watch loop (`cortxt pipeline --watch`) rewrites this file on
    every redraw while the widget polls it concurrently. If the write were
    truncate-then-fill instead of write-temp-then-rename, a poll landing
    mid-write would read a partial/invalid JSON document. Assert the
    mechanism directly: the real write must go through a temp file in the
    same directory followed by `os.replace`, never a direct open-and-write
    of `snapshot_path` itself."""
    snapshot_path = tmp_path / "widget" / "snapshot.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text('{"generated_at": "old"}', encoding="utf-8")

    replace_calls = []
    real_replace = os.replace

    def spy_replace(src, dst):
        # At the moment of replace, the temp file must already hold the
        # full new document, and the destination must still be the old one.
        assert Path(src).read_text(encoding="utf-8") != snapshot_path.read_text(encoding="utf-8")
        replace_calls.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    status.write_snapshot([], snapshot_path)

    assert len(replace_calls) == 1
    src, dst = replace_calls[0]
    assert Path(src).parent == snapshot_path.parent
    assert Path(dst) == snapshot_path
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["generated_at"] != "old"


def test_render_status_table_reports_no_workstreams_when_empty():
    summary = {"status": "idle", "message": "No verified agent work is active"}
    table = status.render_status_table(summary, [])
    assert "No workstreams found." in table
    assert "idle" in table


def test_render_status_table_includes_workstream_row():
    summary = {"status": "working", "message": "1 active; 0 need attention"}
    workstreams = [
        {
            "workstream_id": "issue-180",
            "status": "running",
            "updated_at": "2026-08-20T00:00:00.000000Z",
            "workspace": {"branch": "daemon/issue-180", "worktree": None},
            "lanes": [{"lane_id": "session-1", "label": "builder", "status": "running"}],
        }
    ]

    table = status.render_status_table(summary, workstreams)

    assert "issue-180" in table
    assert "running" in table
    assert "daemon/issue-180" in table
    assert "2026-08-20T00:00:00.000000Z" in table


def test_render_table_has_no_ansi_codes_by_default_under_pytest_capture():
    """pytest captures stdout as a non-tty stream -- the default (color not
    passed) must auto-detect that and stay plain, so this and every other
    render_table test above (which assert exact substrings) keep passing."""
    sessions = [
        {
            "session_id": "session_" + "1" * 32,
            "task_id": "example-task",
            "status": "succeeded",
            "display_status": "succeeded",
            "severity": "ok",
            "updated_at": "2026-08-18T00:00:00.000000Z",
        }
    ]
    table = status.render_table(sessions)
    assert "\033[" not in table


def test_render_table_colors_status_when_explicitly_enabled():
    sessions = [
        {
            "session_id": "session_" + "1" * 32,
            "task_id": "example-task",
            "status": "succeeded",
            "display_status": "succeeded",
            "severity": "ok",
            "updated_at": "2026-08-18T00:00:00.000000Z",
        }
    ]
    table = status.render_table(sessions, color=True)
    assert "\033[" in table
    assert "example-task" in table
    assert "succeeded" in table


def test_render_status_table_colors_status_when_explicitly_enabled():
    summary = {"status": "working", "message": "1 active; 0 need attention"}
    workstreams = [
        {
            "workstream_id": "issue-180",
            "status": "running",
            "updated_at": "2026-08-20T00:00:00.000000Z",
            "workspace": {"branch": "daemon/issue-180", "worktree": None},
            "lanes": [{"lane_id": "session-1", "label": "builder", "status": "running"}],
        }
    ]

    plain = status.render_status_table(summary, workstreams, color=False)
    colored = status.render_status_table(summary, workstreams, color=True)

    assert "\033[" not in plain
    assert "\033[" in colored
    assert "issue-180" in colored
    assert "running" in colored


def test_render_status_table_shows_dash_for_missing_branch():
    summary = {"status": "working", "message": "m"}
    workstreams = [
        {
            "workstream_id": "no-branch-stream",
            "status": "running",
            "updated_at": "2026-08-20T00:00:00.000000Z",
            "workspace": {"branch": None, "worktree": None},
            "lanes": [],
        }
    ]

    table = status.render_status_table(summary, workstreams)

    assert "no-branch-stream" in table
    lines = [line for line in table.splitlines() if "no-branch-stream" in line]
    assert lines and " - " in lines[0]


def test_daemon_only_snapshot_refresh_preserves_sessions(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    sessions = [{
        "session_id": "session_" + "1" * 32,
        "task_id": "keep-me",
        "status": "running",
        "display_status": "running",
        "severity": "info",
        "updated_at": "2026-08-20T00:00:00Z",
        "age_seconds": 0,
        "is_abandoned": False,
        "lifecycle": "running",
        "workstream_id": "keep-me",
        "run_id": "run-1",
        "issue_id": None,
        "branch": None,
        "worktree": None,
        "worker_role": "builder",
        "runtime": "hermes",
        "segments": [],
    }]
    status.write_snapshot(sessions, snapshot_path)

    status.write_snapshot(None, snapshot_path, daemon={"status": "running", "claimed": []})

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert [item["task_id"] for item in doc["sessions"]] == ["keep-me"]
    assert doc["workstreams"][0]["workstream_id"] == "keep-me"
