from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from runtime import session_state as state

from cli.unified_cli import main


def _sessions(store: Path):
    return [state.load(store, d.name) for d in store.iterdir() if d.is_dir()]


def test_dispatch_routes_research_tag_to_hermes_and_invokes_it(tmp_path):
    store = tmp_path / "sessions"
    fake_result = {"status": "succeeded", "profile": "researcher", "stdout": "done", "stderr": "", "elapsed_seconds": 1.2}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result) as fake_invoke:
        exit_code = main([
            "dispatch",
            "--tags", "research",
            "--task-id", "survey-something",
            "--prompt", "survey the landscape",
            "--store", str(store),
        ])
    assert exit_code == 0
    fake_invoke.assert_called_once()
    sessions = _sessions(store)
    assert len(sessions) == 1
    terminal = sessions[0]["events"][-1]
    assert terminal["event_type"] == "session.terminal"
    assert terminal["payload"]["status"] == "succeeded"


def test_dispatch_reports_failure_when_hermes_invocation_fails(tmp_path):
    store = tmp_path / "sessions"
    fake_result = {"status": "failed", "profile": "researcher", "stdout": "", "stderr": "boom", "elapsed_seconds": 0.5}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result):
        exit_code = main([
            "dispatch",
            "--tags", "research",
            "--task-id", "survey-something",
            "--prompt", "survey the landscape",
            "--store", str(store),
        ])
    assert exit_code == 1
    terminal = _sessions(store)[0]["events"][-1]
    assert terminal["payload"]["status"] == "failed"


def test_dispatch_routes_widget_ui_tag_to_claude_direct_without_invoking_hermes(tmp_path):
    store = tmp_path / "sessions"
    with patch("routing.hermes_invoker.invoke_hermes") as fake_invoke:
        exit_code = main([
            "dispatch",
            "--tags", "widget-ui",
            "--task-id", "tweak-the-widget",
            "--prompt", "n/a",
            "--store", str(store),
        ])
    fake_invoke.assert_not_called()
    assert exit_code == 0
    terminal = _sessions(store)[0]["events"][-1]
    assert terminal["payload"]["status"] == "blocked"
    assert "claude-direct" in terminal["payload"]["reason"]


def test_dispatch_falls_back_to_claude_direct_for_unmatched_tags(tmp_path):
    store = tmp_path / "sessions"
    with patch("routing.hermes_invoker.invoke_hermes") as fake_invoke:
        exit_code = main([
            "dispatch",
            "--tags", "some-totally-unknown-shape",
            "--task-id", "mystery-task",
            "--prompt", "n/a",
            "--store", str(store),
        ])
    fake_invoke.assert_not_called()
    assert exit_code == 0
    terminal = _sessions(store)[0]["events"][-1]
    assert terminal["payload"]["status"] == "blocked"


def test_dispatch_records_routing_reason_in_evidence(tmp_path, capsys):
    store = tmp_path / "sessions"
    fake_result = {"status": "succeeded", "profile": "researcher", "stdout": "done", "stderr": "", "elapsed_seconds": 1.0}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result):
        main([
            "dispatch",
            "--tags", "research",
            "--task-id", "survey-something",
            "--prompt", "survey the landscape",
            "--store", str(store),
        ])
    out = capsys.readouterr().out
    assert "routing_reason" in out
