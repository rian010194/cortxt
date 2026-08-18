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


def test_dispatch_defaults_research_tag_to_researcher_hermes_profile(tmp_path):
    """Tonight's evidence: the `builder` profile is where both Fas 2
    Kanban-dispatch failures (#165, #166) and both admin-surface-CLI
    failures (#174, #175) happened. A research-shaped task defaulting to
    `builder` just because that was --hermes-profile's flag default,
    regardless of what actually matched, was never a deliberate choice."""
    store = tmp_path / "sessions"
    fake_result = {"status": "succeeded", "profile": "researcher", "stdout": "done", "stderr": "", "elapsed_seconds": 1.0}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result) as fake_invoke:
        main([
            "dispatch",
            "--tags", "research",
            "--task-id", "survey-something-else",
            "--prompt", "survey the landscape",
            "--store", str(store),
        ])
    assert fake_invoke.call_args.args[0] == "researcher"


def test_dispatch_explicit_hermes_profile_overrides_the_tag_default(tmp_path):
    store = tmp_path / "sessions"
    fake_result = {"status": "succeeded", "profile": "coordinator", "stdout": "done", "stderr": "", "elapsed_seconds": 1.0}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result) as fake_invoke:
        main([
            "dispatch",
            "--tags", "research",
            "--task-id", "survey-with-override",
            "--prompt", "survey the landscape",
            "--store", str(store),
            "--hermes-profile", "coordinator",
        ])
    assert fake_invoke.call_args.args[0] == "coordinator"


def test_dispatch_leaves_no_orphaned_running_session_when_invoke_raises(tmp_path):
    """A session is created, then hermes_invoker raises (e.g.
    HermesInvocationError) before the terminal event is written. Must not
    be left stuck showing "running" forever -- caught by review."""
    store = tmp_path / "sessions"
    with patch("routing.hermes_invoker.invoke_hermes", side_effect=RuntimeError("hermes not found")):
        exit_code = main([
            "dispatch",
            "--tags", "research",
            "--task-id", "invoker-raises",
            "--prompt", "survey the landscape",
            "--store", str(store),
        ])
    assert exit_code == 1
    terminal = _sessions(store)[0]["events"][-1]
    assert terminal["event_type"] == "session.terminal"
    assert terminal["payload"]["status"] == "failed"


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
