from __future__ import annotations

import json
import logging

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
