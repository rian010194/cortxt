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


def test_load_sessions_marks_old_unfinished_work_as_stale(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="abandoned-run")
    created = session["events"][0]["timestamp"]
    now = datetime.fromisoformat(created.replace("Z", "+00:00")) + timedelta(minutes=6)

    entry = status.load_sessions(store, now=now, stale_after_seconds=300)[0]

    assert entry["status"] == "running"
    assert entry["display_status"] == "stale"
    assert entry["is_stale"] is True
    assert entry["segments"][-1]["state"] == "stale"


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
        "is_stale": False,
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
