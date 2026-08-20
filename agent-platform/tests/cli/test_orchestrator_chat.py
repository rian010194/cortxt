from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cli import unified_cli
from runtime import session_state


def _args(tmp_path: Path, ask: str, engine: str = "hermes", timeout=5, resume=None) -> SimpleNamespace:
    return SimpleNamespace(
        ask=ask,
        engine=engine,
        hermes_profile="researcher",
        timeout=timeout,
        model=None,
        provider=None,
        store=tmp_path / "sessions",
        snapshot=tmp_path / "snapshot.json",
        stale_after=300,
        workstream_id="branch-main",
        branch="main",
        resume=resume,
    )


def _projection(tmp_path: Path) -> dict:
    return {
        "orchestrator": {"status": "idle", "message": "No verified work"},
        "workstreams": [],
        "runtimes": [{"runtime_id": "hermes", "installed": True, "running": False}],
        "engines": [],
        "skills": [],
        "profiles": [],
        "snapshot_path": tmp_path / "snapshot.json",
    }


class FakeBroker:
    def __init__(self, session_ids=None, has_provider=True):
        self.calls = []
        self._session_ids = list(session_ids or [])
        self.has_provider = has_provider

    def invoke(self, profile, prompt, **kwargs):
        self.calls.append((profile, prompt, kwargs))
        session_id = self._session_ids.pop(0) if self._session_ids else "sess-1"
        return {"status": "succeeded", "stdout": "Advisory answer", "stderr": "", "session_id": session_id}


class FakeContext:
    def __init__(self, brokers: dict):
        self.brokers = brokers

    def get(self, engine_id):
        return self.brokers.get(engine_id, FakeBroker(has_provider=False))


def test_slash_command_stays_local_and_never_invokes_engine(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "/status"), engine_context=FakeContext({"hermes": broker})
    )

    assert result.status == "succeeded"
    assert broker.calls == []
    assert "idle: No verified work" in capsys.readouterr().out


def test_greeting_is_conversational_local_and_does_not_disclose_state(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "Hello"), engine_context=FakeContext({"hermes": broker})
    )

    output = capsys.readouterr().out
    assert result.status == "succeeded"
    assert broker.calls == []
    assert "Hello! I\u2019m the Cortxt orchestrator." in output
    assert "30 items" not in output
    assert "Attention required" not in output
    assert not (tmp_path / "sessions").exists()


def test_chat_invokes_hermes_broker_and_persists_metadata_only(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?"), engine_context=FakeContext({"hermes": broker})
    )

    assert result.status == "succeeded"
    assert broker.calls[0][0] == "researcher"
    assert "SANITIZED LOCAL PROJECTION" in broker.calls[0][1]
    session_id = next((tmp_path / "sessions").iterdir()).name
    doc = session_state.load(tmp_path / "sessions", session_id)
    records = [event["payload"] for event in doc["events"] if event["event_type"].startswith("chat.")]
    assert [record["role"] for record in records] == ["user", "assistant"]
    assert all("content" not in record for record in records)
    assert doc["events"][-1]["event_type"] == "session.terminal"
    assert "Advisory answer" in capsys.readouterr().out


def test_default_engine_is_hermes_when_flag_omitted(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "hi there is anything running?"), engine_context=FakeContext({"hermes": broker})
    )

    assert broker.calls  # hermes broker was the one invoked


def test_engine_flag_selects_the_broker_for_every_turn(tmp_path, monkeypatch, capsys):
    hermes_broker = FakeBroker()
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?", engine="codex"),
        engine_context=FakeContext({"hermes": hermes_broker, "codex": codex_broker}),
    )

    assert hermes_broker.calls == []
    assert codex_broker.calls


def test_slash_engine_command_switches_broker_for_the_next_turn(tmp_path, monkeypatch, capsys):
    hermes_broker = FakeBroker()
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))
    inputs = iter(["/engine codex", "what is running?", "/quit"])

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, None),
        engine_context=FakeContext({"hermes": hermes_broker, "codex": codex_broker}),
        input_fn=lambda prompt: next(inputs),
    )

    assert hermes_broker.calls == []
    assert codex_broker.calls
    assert "Active engine: codex" in capsys.readouterr().out


def test_transcript_engine_field_follows_the_active_engine(tmp_path, monkeypatch, capsys):
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?", engine="codex"),
        engine_context=FakeContext({"codex": codex_broker}),
    )

    session_id = next((tmp_path / "sessions").iterdir()).name
    doc = session_state.load(tmp_path / "sessions", session_id)
    records = [event["payload"] for event in doc["events"] if event["event_type"].startswith("chat.")]
    assert all(record["engine"] == "codex" for record in records)


def test_second_turn_to_the_same_engine_resumes_the_first_turns_session(tmp_path, monkeypatch, capsys):
    broker = FakeBroker(session_ids=["sess-first", "sess-second"])
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))
    inputs = iter(["what is running?", "and now?", "/quit"])

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, None),
        engine_context=FakeContext({"hermes": broker}),
        input_fn=lambda prompt: next(inputs),
    )

    assert broker.calls[0][2]["session_id"] is None
    assert broker.calls[1][2]["session_id"] == "sess-first"


def test_engine_session_id_is_persisted_on_the_assistant_record(tmp_path, monkeypatch, capsys):
    broker = FakeBroker(session_ids=["sess-first"])
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?"), engine_context=FakeContext({"hermes": broker})
    )

    session_id = next((tmp_path / "sessions").iterdir()).name
    doc = session_state.load(tmp_path / "sessions", session_id)
    assistant_record = next(
        event["payload"] for event in doc["events"]
        if event["event_type"] == "chat.assistant"
    )
    assert assistant_record["engine_session_id"] == "sess-first"


def test_codex_engine_does_not_receive_the_hermes_specific_profile_flag(tmp_path, monkeypatch, capsys):
    # args.hermes_profile ("researcher" in _args()) is a Hermes profile name
    # (hermes -p researcher); Codex's -p flag expects a Codex config-profile
    # name from $CODEX_HOME. Passing "researcher" through unchanged would
    # make --engine codex fail against a real codex CLI with no such
    # profile configured, so the REPL must not forward it to non-Hermes
    # engines.
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?", engine="codex"),
        engine_context=FakeContext({"codex": codex_broker}),
    )

    assert codex_broker.calls[0][0] is None


def test_hermes_engine_still_receives_the_hermes_profile_flag(tmp_path, monkeypatch, capsys):
    hermes_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?"), engine_context=FakeContext({"hermes": hermes_broker})
    )

    assert hermes_broker.calls[0][0] == "researcher"


def test_slash_engine_command_rejects_an_unavailable_engine_and_keeps_the_current_one(tmp_path, monkeypatch, capsys):
    hermes_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))
    inputs = iter(["/engine not-a-real-engine", "what is running?", "/quit"])

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, None),
        engine_context=FakeContext({"hermes": hermes_broker}),
        input_fn=lambda prompt: next(inputs),
    )

    output = capsys.readouterr().out
    assert "not-a-real-engine" in output and "not available" in output
    assert hermes_broker.calls  # the turn after the rejected switch still went to hermes


def test_timeout_omitted_uses_the_active_engines_default(tmp_path, monkeypatch, capsys):
    # --timeout is None (operator didn't override) -- the turn must fall
    # back to the per-engine default (spec Open question #5), not some
    # single global constant.
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?", engine="codex", timeout=None),
        engine_context=FakeContext({"codex": codex_broker}),
    )

    from runtime.engine_registry import default_timeout_seconds

    assert codex_broker.calls[0][2]["timeout_seconds"] == default_timeout_seconds("codex")


def test_timeout_explicit_value_overrides_the_per_engine_default(tmp_path, monkeypatch, capsys):
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?", engine="codex", timeout=7),
        engine_context=FakeContext({"codex": codex_broker}),
    )

    assert codex_broker.calls[0][2]["timeout_seconds"] == 7


def test_resume_restores_the_stored_engine_session_id_for_the_first_turn(tmp_path, monkeypatch, capsys):
    # A prior REPL run left behind a session with a Codex turn whose
    # engine_session_id was captured. A fresh REPL invocation with
    # --resume <that session_id> must pass it to the adapter on the very
    # first turn -- the whole point of spec Open question #4.
    from runtime import session_state as state
    from cli import orchestrator as orchestrator_cli

    store = tmp_path / "sessions"
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    doc = state.create(store, task_id="orchestrator-chat:prior", runtime="codex")
    prior_session_id = doc["session_id"]
    seq = 0
    user_record = orchestrator_cli.transcript_record(
        transcript_id="prior-transcript", turn_index=1, role="user",
        content="hi", engine="codex", status="submitted", redactions=[],
    )
    doc = state.append(store, prior_session_id, seq, "chat.user", user_record)
    seq += 1
    assistant_record = orchestrator_cli.transcript_record(
        transcript_id="prior-transcript", turn_index=1, role="assistant",
        content="hello", engine="codex", status="succeeded",
        engine_session_id="thread-from-last-run",
    )
    state.append(store, prior_session_id, seq, "chat.assistant", assistant_record)

    codex_broker = FakeBroker()

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "continue please", engine="codex", resume=prior_session_id),
        engine_context=FakeContext({"codex": codex_broker}),
    )

    assert codex_broker.calls[0][2]["session_id"] == "thread-from-last-run"


def test_resume_with_unknown_session_id_fails_without_crashing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))
    codex_broker = FakeBroker()

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "continue please", engine="codex", resume="session_" + "0" * 32),
        engine_context=FakeContext({"codex": codex_broker}),
    )

    assert result.status == "failed"
    assert codex_broker.calls == []
