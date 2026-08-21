from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from runtime import session_state as state

from cli.unified_cli import main


def _sessions(store: Path):
    return [state.load(store, d.name) for d in store.iterdir() if d.is_dir()]


def test_dispatch_routes_parallel_dispatch_tag_to_hermes_and_invokes_it(tmp_path):
    # research/background-task now route to dsh (cheap tie-break on engine_id,
    # deliberate operator decision 2026-08-21); hermes keeps parallel-dispatch.
    store = tmp_path / "sessions"
    fake_result = {"status": "succeeded", "profile": "researcher", "stdout": "done", "stderr": "", "elapsed_seconds": 1.2}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result) as fake_invoke:
        exit_code = main([
            "dispatch",
            "--tags", "parallel-dispatch",
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


def test_dispatch_writes_the_widget_snapshot_on_success(tmp_path):
    store = tmp_path / "sessions"
    snapshot = tmp_path / "widget" / "snapshot.json"
    fake_result = {"status": "succeeded", "profile": "researcher", "stdout": "done", "stderr": "", "elapsed_seconds": 1.0}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result):
        main([
            "dispatch",
            "--tags", "parallel-dispatch",
            "--task-id", "snapshot-on-success",
            "--prompt", "survey the landscape",
            "--store", str(store),
            "--snapshot", str(snapshot),
        ])
    doc = json.loads(snapshot.read_text(encoding="utf-8"))
    assert [s["task_id"] for s in doc["sessions"]] == ["snapshot-on-success"]
    assert doc["sessions"][0]["status"] == "succeeded"


def test_dispatch_writes_the_widget_snapshot_when_routed_to_claude_direct(tmp_path):
    store = tmp_path / "sessions"
    snapshot = tmp_path / "widget" / "snapshot.json"
    with patch("routing.hermes_invoker.invoke_hermes"):
        main([
            "dispatch",
            "--tags", "widget-ui",
            "--task-id", "snapshot-on-blocked",
            "--prompt", "n/a",
            "--store", str(store),
            "--snapshot", str(snapshot),
        ])
    doc = json.loads(snapshot.read_text(encoding="utf-8"))
    assert doc["sessions"][0]["status"] == "blocked"


def test_dispatch_writes_the_widget_snapshot_on_hermes_failure(tmp_path):
    store = tmp_path / "sessions"
    snapshot = tmp_path / "widget" / "snapshot.json"
    fake_result = {"status": "failed", "profile": "researcher", "stdout": "", "stderr": "boom", "elapsed_seconds": 0.5}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result):
        main([
            "dispatch",
            "--tags", "parallel-dispatch",
            "--task-id", "snapshot-on-failure",
            "--prompt", "survey the landscape",
            "--store", str(store),
            "--snapshot", str(snapshot),
        ])
    doc = json.loads(snapshot.read_text(encoding="utf-8"))
    assert doc["sessions"][0]["status"] == "failed"


def test_dispatch_writes_the_widget_snapshot_when_invoker_raises(tmp_path):
    """The orphaned-session fix already guarantees a terminal event on any
    exception -- the snapshot write must reflect that same outcome, not
    just the happy path."""
    store = tmp_path / "sessions"
    snapshot = tmp_path / "widget" / "snapshot.json"
    with patch("routing.hermes_invoker.invoke_hermes", side_effect=RuntimeError("hermes not found")):
        main([
            "dispatch",
            "--tags", "parallel-dispatch",
            "--task-id", "snapshot-on-raise",
            "--prompt", "survey the landscape",
            "--store", str(store),
            "--snapshot", str(snapshot),
        ])
    doc = json.loads(snapshot.read_text(encoding="utf-8"))
    assert doc["sessions"][0]["status"] == "failed"


def test_dispatch_default_snapshot_path_matches_sessions_default(tmp_path, monkeypatch):
    """No --snapshot given: dispatch should land in the same default place
    `cortxt sessions` writes to (agent-platform/widget/snapshot.json),
    so a widget already pointed at that file picks up dispatch results
    without the operator having to run `sessions` afterward."""
    import cli.unified_cli as unified_cli

    fake_ap_path = tmp_path / "agent-platform"
    monkeypatch.setattr(unified_cli, "_get_agent_platform_path", lambda: fake_ap_path)
    fake_result = {"status": "succeeded", "profile": "researcher", "stdout": "done", "stderr": "", "elapsed_seconds": 1.0}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result):
        main([
            "dispatch",
            "--tags", "parallel-dispatch",
            "--task-id", "default-snapshot-path",
            "--prompt", "survey the landscape",
        ])
    assert (fake_ap_path / "widget" / "snapshot.json").is_file()


def test_dispatch_logs_a_warning_when_snapshot_write_fails_without_masking_result(tmp_path, caplog):
    """Review finding: the snapshot-write failure path was a bare
    `except Exception: pass` -- silent, no trace anywhere. Must log (same
    visibility principle status.py's own load_sessions() already follows)
    without letting a snapshot failure change dispatch's own outcome."""
    import logging

    store = tmp_path / "sessions"
    fake_result = {"status": "succeeded", "profile": "researcher", "stdout": "done", "stderr": "", "elapsed_seconds": 1.0}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result), \
         patch("status.write_snapshot", side_effect=OSError("disk full")), \
         caplog.at_level(logging.WARNING):
        exit_code = main([
            "dispatch",
            "--tags", "parallel-dispatch",
            "--task-id", "snapshot-write-fails",
            "--prompt", "survey the landscape",
            "--store", str(store),
        ])
    assert exit_code == 0
    assert any("snapshot" in record.message.lower() for record in caplog.records)


def _context_with_fake_dsh_adapter(profile_log):
    """A default-shaped EngineContext whose dsh adapter records the profile
    argument it was invoked with (and the prompt) -- lets main()'s
    dispatch path exercise profile inference end-to-end without a real
    SDK/runtime."""
    from runtime.engine_registry import EngineContext

    class _FakeDshAdapter:
        def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
            profile_log.append((profile, prompt))
            return {"status": "succeeded", "stdout": "done", "stderr": "", "elapsed_seconds": 1.0}

    context = EngineContext()
    context.register("dsh", _FakeDshAdapter())
    return context


def _patch_default_context(monkeypatch, profile_log):
    # _run_dispatch imports build_default_engine_context from
    # runtime.default_engine_context at call time; patch the source module.
    import runtime.default_engine_context as dec

    monkeypatch.setattr(dec, "build_default_engine_context", lambda: _context_with_fake_dsh_adapter(profile_log))


def test_dispatch_research_tag_routes_to_dsh_and_passes_researcher_profile(tmp_path, monkeypatch):
    """Tonight's evidence: the `builder` profile is where both Fas 2
    Kanban-dispatch failures (#165, #166) and both admin-surface-CLI
    failures (#174, #175) happened. A research-shaped task must default to
    `researcher`, not `builder` -- route() now picks dsh for research, and
    the profile argument is still threaded through to the winning adapter."""
    profile_log = []
    _patch_default_context(monkeypatch, profile_log)
    store = tmp_path / "sessions"
    exit_code = main([
        "dispatch",
        "--tags", "research",
        "--task-id", "survey-something-else",
        "--prompt", "survey the landscape",
        "--store", str(store),
    ])
    assert exit_code == 0
    assert profile_log[0][0] == "researcher"


def test_dispatch_defaults_to_researcher_even_when_research_is_not_the_matched_tag(tmp_path, monkeypatch):
    """Review finding: route() picks matched_tag as the alphabetically-first
    tag in the intersection with the winning engine's task_shapes --
    "parallel-dispatch" sorts before "research", so --tags
    research,parallel-dispatch would silently fall back to "builder" if the
    profile lookup only checked choice.matched_tag instead of the full
    supplied tag set. dsh wins the research tie-break here, but the profile
    inference must still see the full supplied tag set."""
    profile_log = []
    _patch_default_context(monkeypatch, profile_log)
    store = tmp_path / "sessions"
    exit_code = main([
        "dispatch",
        "--tags", "research,parallel-dispatch",
        "--task-id", "research-shaped-background-task",
        "--prompt", "survey the landscape",
        "--store", str(store),
    ])
    assert exit_code == 0
    assert profile_log[0][0] == "researcher"


def test_dispatch_explicit_hermes_profile_overrides_the_tag_default(tmp_path, monkeypatch):
    profile_log = []
    _patch_default_context(monkeypatch, profile_log)
    store = tmp_path / "sessions"
    exit_code = main([
        "dispatch",
        "--tags", "research",
        "--task-id", "survey-with-override",
        "--prompt", "survey the landscape",
        "--store", str(store),
        "--hermes-profile", "coordinator",
    ])
    assert exit_code == 0
    assert profile_log[0][0] == "coordinator"


def test_dispatch_explicit_empty_hermes_profile_is_not_treated_as_unset(tmp_path, monkeypatch):
    """Review finding: `args.hermes_profile or next(...)` treated an
    explicitly-passed empty string the same as "not given", silently
    substituting the tag-inferred default instead of honoring the
    caller's (admittedly unusual, but explicit) empty value."""
    profile_log = []
    _patch_default_context(monkeypatch, profile_log)
    store = tmp_path / "sessions"
    exit_code = main([
        "dispatch",
        "--tags", "research",
        "--task-id", "explicit-empty-profile",
        "--prompt", "survey the landscape",
        "--store", str(store),
        "--hermes-profile", "",
    ])
    assert exit_code == 0
    assert profile_log[0][0] == ""


def test_dispatch_leaves_no_orphaned_running_session_when_invoke_raises(tmp_path):
    """A session is created, then hermes_invoker raises (e.g.
    HermesInvocationError) before the terminal event is written. Must not
    be left stuck showing "running" forever -- caught by review."""
    store = tmp_path / "sessions"
    with patch("routing.hermes_invoker.invoke_hermes", side_effect=RuntimeError("hermes not found")):
        exit_code = main([
            "dispatch",
            "--tags", "parallel-dispatch",
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
            "--tags", "parallel-dispatch",
            "--task-id", "survey-something",
            "--prompt", "survey the landscape",
            "--store", str(store),
        ])
    out = capsys.readouterr().out
    assert "routing_reason" in out


def test_dispatch_records_checkpoint_required_in_evidence(tmp_path, capsys):
    """Review finding: route()'s checkpoint_required field was threaded
    through EngineManifest/EngineChoice but never surfaced in `cortxt
    dispatch`'s own evidence -- the spec names dispatch specifically as
    Track 0's checkpoint-support surface, so an unread field there defeats
    the point of adding it."""
    store = tmp_path / "sessions"
    fake_result = {"status": "succeeded", "profile": "researcher", "stdout": "done", "stderr": "", "elapsed_seconds": 1.0}
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result):
        exit_code = main([
            "dispatch",
            "--tags", "parallel-dispatch",
            "--task-id", "checkpoint-evidence",
            "--prompt", "survey the landscape",
            "--store", str(store),
        ])
    assert exit_code == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["evidence"][0]["checkpoint_required"] is True
