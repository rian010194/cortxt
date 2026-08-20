from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from runtime import session_state as state

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


def test_run_pipeline_watch_mode_republishes_the_widget_snapshot_each_tick(tmp_path, monkeypatch):
    """The terminal redraw and the widget's snapshot.json must come from the
    same generation, not drift apart. This runs `_run_pipeline` with the
    real (unmocked) `_collect_session_projection`, so every redraw actually
    calls `write_snapshot`, and asserts the on-disk `generated_at` advances
    across ticks -- i.e. the web widget polling snapshot.json would see
    fresh data on each terminal redraw, not a file frozen at the first
    write.

    Termination is driven from the `collect` hook, not from `time.sleep`:
    `pipeline.run_watch`'s `sleep_fn` default is bound to the real
    `time.sleep` function object at module-import time, so monkeypatching
    the `time` module's `sleep` attribute afterwards does not intercept
    it -- the loop would just keep calling the real (fast but real) sleep
    forever since nothing else ends it. Raising `KeyboardInterrupt` from
    inside the wrapped collector, the same way the pre-existing
    `test_run_pipeline_watch_mode_redraws_and_stops_on_keyboard_interrupt`
    does, reliably ends the loop regardless of how sleep is wired.
    """
    store = tmp_path / "sessions"
    snapshot_path = tmp_path / "snapshot.json"
    state.create(store, task_id="live-refresh-check")

    from runtime import session_state as state_module

    counter = {"n": 0}

    def fake_utc_now() -> str:
        counter["n"] += 1
        return f"2026-08-20T00:00:{counter['n']:02d}Z"

    monkeypatch.setattr(state_module, "utc_now", fake_utc_now)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    real_collect = unified_cli._collect_session_projection
    seen_generated_at = []
    calls = {"n": 0}

    def spy_collect(args):
        result = real_collect(args)
        calls["n"] += 1
        if calls["n"] > 1:
            # Skip the pre-loop projection call `_run_pipeline` makes before
            # deciding watch vs. non-watch mode -- only count real loop ticks.
            seen_generated_at.append(json.loads(snapshot_path.read_text(encoding="utf-8"))["generated_at"])
        if calls["n"] >= 3:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(unified_cli, "_collect_session_projection", spy_collect)

    args = _args(tmp_path, store=store, snapshot=snapshot_path, watch=True, interval=0.01)
    result = unified_cli._run_pipeline(args)

    assert result.status == "succeeded"
    assert len(seen_generated_at) == 2
    assert seen_generated_at[0] != seen_generated_at[1]
