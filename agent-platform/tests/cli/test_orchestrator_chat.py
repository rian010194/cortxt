from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cli import unified_cli
from runtime import session_state


def _args(tmp_path: Path, ask: str) -> SimpleNamespace:
    return SimpleNamespace(
        ask=ask,
        hermes_profile="researcher",
        timeout=5,
        model=None,
        provider=None,
        store=tmp_path / "sessions",
        snapshot=tmp_path / "snapshot.json",
        stale_after=300,
        workstream_id="branch-main",
        branch="main",
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
    def __init__(self):
        self.calls = []

    def invoke(self, profile, prompt, **kwargs):
        self.calls.append((profile, prompt, kwargs))
        return {"status": "succeeded", "stdout": "Advisory answer", "stderr": ""}


class FakeContext:
    def __init__(self, broker):
        self.broker = broker

    def get(self, engine_id):
        assert engine_id == "hermes"
        return self.broker


def test_slash_command_stays_local_and_never_invokes_engine(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "/status"), engine_context=FakeContext(broker)
    )

    assert result.status == "succeeded"
    assert broker.calls == []
    assert "idle: No verified work" in capsys.readouterr().out


def test_greeting_is_conversational_local_and_does_not_disclose_state(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "Hello"), engine_context=FakeContext(broker)
    )

    output = capsys.readouterr().out
    assert result.status == "succeeded"
    assert broker.calls == []
    assert "Hello! I’m the Cortxt orchestrator." in output
    assert "30 items" not in output
    assert "Attention required" not in output
    assert not (tmp_path / "sessions").exists()


def test_chat_invokes_hermes_broker_and_persists_metadata_only(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?"), engine_context=FakeContext(broker)
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
