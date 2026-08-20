from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cli import unified_cli


def _args(tmp_path: Path, **overrides) -> SimpleNamespace:
    base = dict(
        store=tmp_path / "sessions",
        snapshot=tmp_path / "snapshot.json",
        stale_after=300,
        watch=False,
        interval=0.01,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _projection(tmp_path: Path, workstreams=None) -> dict:
    return {
        "orchestrator": {"status": "idle", "message": "No verified agent work is active"},
        "workstreams": workstreams or [],
        "runtimes": [],
        "engines": [],
        "skills": [],
        "profiles": [],
        "snapshot_path": tmp_path / "snapshot.json",
    }


def test_run_status_prints_ledger_and_succeeds(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(unified_cli, "_collect_session_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_status(_args(tmp_path))

    assert result.status == "succeeded"
    out = capsys.readouterr().out
    assert "idle" in out


def test_run_status_reports_error_result_on_failure(tmp_path, monkeypatch):
    def _boom(args):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(unified_cli, "_collect_session_projection", _boom)

    result = unified_cli._run_status(_args(tmp_path))

    assert result.status == "failed"
    assert "store unreadable" in result.error["message"]


def test_run_pipeline_without_watch_prints_a_single_frame(tmp_path, monkeypatch, capsys):
    workstreams = [
        {
            "workstream_id": "issue-180",
            "status": "running",
            "updated_at": "2026-08-20T00:00:00Z",
            "workspace": {"branch": "daemon/issue-180", "worktree": None},
            "lanes": [{"lane_id": "s1", "label": "builder", "status": "running"}],
        }
    ]
    monkeypatch.setattr(
        unified_cli, "_collect_session_projection", lambda args: _projection(tmp_path, workstreams)
    )

    result = unified_cli._run_pipeline(_args(tmp_path, watch=False))

    assert result.status == "succeeded"
    out = capsys.readouterr().out
    assert "issue-180" in out
    assert "builder" in out


def test_run_pipeline_watch_mode_redraws_and_stops_on_keyboard_interrupt(tmp_path, monkeypatch, capsys):
    calls = {"n": 0}

    def _collect(args):
        calls["n"] += 1
        if calls["n"] > 2:
            raise KeyboardInterrupt
        return _projection(tmp_path)

    monkeypatch.setattr(unified_cli, "_collect_session_projection", _collect)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    result = unified_cli._run_pipeline(_args(tmp_path, watch=True, interval=0.01))

    assert result.status == "succeeded"
    out = capsys.readouterr().out
    assert "Stopped" in out
