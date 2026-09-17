"""AcpConnection / AcpAdapter against a fake ACP agent over real stdio (B1.5a).

The fake (acp_fake_agent.py) runs the SDK's own agent side in a subprocess
and makes no network or model call. Every call passes a timeout of at most
30 seconds so a hang fails the test instead of stalling the suite.

This file imports no SDK at module level: where agent-client-protocol is
absent these tests fail with AcpUnavailable rather than skipping.
"""
from __future__ import annotations

import ast
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from runtime.adapters.acp_adapter import (
    AcpAdapter,
    AcpConnection,
    AcpConnectionLost,
    AcpSessionNotFound,
)
from runtime.engine_adapter import EngineAdapter, supports_events

FAKE_AGENT = Path(__file__).with_name("acp_fake_agent.py")
AGENT_PLATFORM = Path(__file__).resolve().parents[3]
ADAPTER_SOURCE = AGENT_PLATFORM / "runtime" / "adapters" / "acp_adapter.py"
WIRE_SOURCE = AGENT_PLATFORM / "runtime" / "adapters" / "acp_wire.py"
T = 30


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self._cond = threading.Condition()

    def __call__(self, event: dict) -> None:
        with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    def wait_for(self, predicate, timeout: float = T) -> dict:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for event in self.events:
                    if predicate(event):
                        return event
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"no matching event within {timeout}s: {self.events!r}")
                self._cond.wait(remaining)


def _chunk_text(event: dict) -> str:
    return event["payload"]["update"]["content"]["text"]


def _live_chunks(events):
    return [e for e in events if e["origin"] == "live" and e["kind"] == "session_update"]


@pytest.fixture
def connect(tmp_path):
    opened: list[AcpConnection] = []

    def _connect(*agent_args, sink=None, env=None, stderr_path=None, state_dir=None):
        recorder = _Recorder()
        connection = AcpConnection(
            command=sys.executable,
            args=[str(FAKE_AGENT), str(state_dir or tmp_path / "state"), *agent_args],
            cwd=tmp_path,
            env=env,
            event_sink=sink if sink is not None else recorder,
            stderr_path=stderr_path,
        )
        opened.append(connection)
        return connection, recorder

    yield _connect
    for connection in opened:
        connection.close()


def test_new_session_returns_exactly_the_agent_issued_id(connect):
    conn, rec = connect()
    info = conn.start(T)
    assert info["agent_name"] == "acp-fake-agent"
    assert info["protocol_version"] == 1
    assert info["sdk_version"] == "0.9.0"
    session_id = conn.new_session(T)
    conn.prompt(session_id, "hello", turn_id="turn-1", timeout_seconds=T)
    first = _live_chunks(rec.events)[0]
    assert _chunk_text(first) == f"session {session_id}"
    assert first["acp_session_id"] == session_id
    assert first["turn_id"] == "turn-1"


def test_prompt_streams_live_updates_before_turn_end(connect):
    conn, rec = connect()
    conn.start(T)
    session_id = conn.new_session(T)
    result = conn.prompt(session_id, "hello", turn_id=None, timeout_seconds=T)
    assert result["kind"] == "turn_end"
    assert result["stop_reason"] == "end_turn"
    live = _live_chunks(rec.events)
    assert len(live) >= 2
    assert all(e["wire_seq"] < result["wire_seq"] for e in live)
    assert [e for e in rec.events if e["kind"] == "turn_end"] == [result]


def test_permission_request_is_answered_with_the_reject_option(connect):
    conn, rec = connect()
    conn.start(T)
    session_id = conn.new_session(T)
    result = conn.prompt(session_id, "ASK-PERMISSION", turn_id="t", timeout_seconds=T)
    assert result["kind"] == "turn_end"
    requests = [e for e in rec.events if e["kind"] == "permission_request"]
    assert len(requests) == 1
    assert requests[0]["decision"] == "denied"
    assert requests[0]["origin"] == "live"
    echoed = [_chunk_text(e) for e in _live_chunks(rec.events)]
    assert echoed == ["deny"]


def test_load_session_classifies_replay_load_complete_out_of_turn_then_live(connect, tmp_path):
    first, _ = connect()
    first.start(T)
    session_id = first.new_session(T)
    first.close()

    conn, rec = connect("--replay", "200")
    conn.start(T)
    conn.load_session(session_id, T)
    commands = rec.wait_for(lambda e: e["update_type"] == "available_commands_update")

    replay = [e for e in rec.events if e["origin"] == "replay"]
    completes = [e for e in rec.events if e["kind"] == "load_complete"]
    assert len(replay) == 200
    assert all(e["kind"] == "session_update" and e["acp_session_id"] == session_id for e in replay)
    assert len(completes) == 1
    assert commands["origin"] == "out_of_turn"
    assert max(e["wire_seq"] for e in replay) < completes[0]["wire_seq"] < commands["wire_seq"]

    before = len(rec.events)
    result = conn.prompt(session_id, "hello again", turn_id="t2", timeout_seconds=T)
    after = rec.events[before:]
    chunks = [e for e in after if e["kind"] == "session_update"]
    assert len(chunks) >= 2
    assert all(e["origin"] == "live" for e in chunks)
    assert result["kind"] == "turn_end"


def test_null_load_result_raises_session_not_found(connect):
    # Result injection, no wire: an SDK 0.9.0 agent cannot put a null
    # session/load result on the wire, so the defensive contract is pinned here.
    conn, _ = connect()
    conn.start(T)
    sent: list[dict] = []

    async def load_session_returning_none(**kwargs):
        sent.append(kwargs)
        return None

    conn._conn.load_session = load_session_returning_none
    with pytest.raises(AcpSessionNotFound):
        conn.load_session("no-such-session", T)
    assert sent and sent[0]["session_id"] == "no-such-session"


def test_load_session_of_unknown_id_returns_normally_without_replay(connect):
    # hermes-faithful: the agent answers {} (SDK normalization of None), so
    # the only observable difference from a known id is the absence of replay.
    conn, rec = connect()
    conn.start(T)
    assert conn.load_session("no-such-session", T) is None
    assert [e for e in rec.events if e["origin"] == "replay"] == []
    completes = [e for e in rec.events if e["kind"] == "load_complete"]
    assert len(completes) == 1
    assert completes[0]["payload"] == {"result": {}}


def test_agent_exit_mid_turn_is_connection_lost_never_turn_end(connect):
    conn, rec = connect()
    conn.start(T)
    session_id = conn.new_session(T)
    with pytest.raises(AcpConnectionLost):
        conn.prompt(session_id, "EXIT-MIDTURN", turn_id="t", timeout_seconds=T)
    kinds = [e["kind"] for e in rec.events]
    assert "turn_failed" in kinds
    assert "turn_end" not in kinds
    failed = [e for e in rec.events if e["kind"] == "turn_failed"][0]
    assert failed["payload"] == {"reason": "connection_lost"}
    assert _live_chunks(rec.events)[0]["wire_seq"] < failed["wire_seq"]


def test_cancel_ends_the_turn_with_stop_reason_cancelled(connect):
    conn, rec = connect()
    conn.start(T)
    session_id = conn.new_session(T)
    outcome: dict = {}

    def run_prompt():
        try:
            outcome["result"] = conn.prompt(session_id, "WAIT-CANCEL", turn_id="t", timeout_seconds=T)
        except BaseException as exc:  # surfaced below
            outcome["error"] = exc

    worker = threading.Thread(target=run_prompt)
    worker.start()
    rec.wait_for(lambda e: e["origin"] == "live" and e["kind"] == "session_update")
    conn.cancel(session_id)
    worker.join(T)
    assert not worker.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert outcome["result"]["kind"] == "turn_end"
    assert outcome["result"]["stop_reason"] == "cancelled"


def test_client_capabilities_advertise_no_fs_and_no_terminal(connect):
    conn, rec = connect()
    conn.start(T)
    session_id = conn.new_session(T)
    conn.prompt(session_id, "ECHO-CAPS", turn_id=None, timeout_seconds=T)
    caps = json.loads(_chunk_text(_live_chunks(rec.events)[0]))
    assert caps["fs"]["readTextFile"] is False
    assert caps["fs"]["writeTextFile"] is False
    assert caps["terminal"] is False


def test_a_raising_sink_closes_the_connection(connect):
    seen: list[dict] = []

    def sink(event):
        seen.append(event)
        if event["kind"] == "session_update":
            raise ValueError("sink broke")

    conn, _ = connect(sink=sink)
    conn.start(T)
    session_id = conn.new_session(T)
    with pytest.raises(AcpConnectionLost):
        conn.prompt(session_id, "hello", turn_id=None, timeout_seconds=T)
    errors = [e for e in seen if e["kind"] == "protocol_error"]
    assert errors and errors[0]["payload"]["reason"] == "event_pipeline_failed"
    assert "turn_end" not in [e["kind"] for e in seen]
    with pytest.raises(AcpConnectionLost):
        conn.prompt(session_id, "hello", turn_id=None, timeout_seconds=T)


def test_calling_the_connection_from_its_own_loop_thread_is_refused(connect):
    errors: list[BaseException] = []
    holder: dict = {}

    def sink(event):
        if event["kind"] == "session_update" and not errors:
            try:
                holder["conn"].cancel(event["acp_session_id"])
            except RuntimeError as exc:
                errors.append(exc)

    conn, _ = connect(sink=sink)
    holder["conn"] = conn
    conn.start(T)
    session_id = conn.new_session(T)
    conn.prompt(session_id, "hello", turn_id=None, timeout_seconds=T)
    assert errors and "event-loop thread" in str(errors[0])


def test_start_completes_when_the_agent_floods_stderr(connect, tmp_path):
    conn, _ = connect("--stderr-bytes", str(1024 * 1024))
    assert conn.start(T)["agent_name"] == "acp-fake-agent"

    log = tmp_path / "agent-stderr.log"
    logged, _ = connect("--stderr-bytes", str(1024 * 1024), stderr_path=log)
    logged.start(T)
    logged.close()
    assert log.stat().st_size >= 1024 * 1024


def test_a_one_mebibyte_replay_line_is_received(connect):
    first, _ = connect()
    first.start(T)
    session_id = first.new_session(T)
    first.close()

    conn, rec = connect("--replay", "1", "--replay-line-bytes", str(1024 * 1024))
    conn.start(T)
    conn.load_session(session_id, T)
    replay = [e for e in rec.events if e["origin"] == "replay"]
    assert len(replay) == 1
    assert len(_chunk_text(replay[0])) > 1024 * 1024


def test_agent_environment_is_the_allowlist_plus_explicit_additions(connect, monkeypatch):
    monkeypatch.setenv("CORTXT_TEST_SECRET", "must-not-leak")
    conn, rec = connect(env={"CORTXT_TEST_PASSED": "1"})
    conn.start(T)
    session_id = conn.new_session(T)
    conn.prompt(session_id, "ECHO-ENV", turn_id=None, timeout_seconds=T)
    names = {name.upper() for name in json.loads(_chunk_text(_live_chunks(rec.events)[0]))}
    assert "CORTXT_TEST_SECRET" not in names
    assert "CORTXT_TEST_PASSED" in names


def test_acp_adapter_is_an_event_capable_engine_adapter(tmp_path):
    def make():
        return AcpAdapter(
            command=sys.executable,
            args=[str(FAKE_AGENT), str(tmp_path / "state")],
            cwd=tmp_path,
        )

    assert isinstance(make(), EngineAdapter)
    assert supports_events(make()) is True

    events: list[dict] = []
    result = make().invoke("any-profile", "hello", timeout_seconds=T, on_event=events.append)
    assert events
    assert result["status"] == "succeeded"
    assert result["stop_reason"] == "end_turn"
    assert result["text"].startswith(f"session {result['session_id']}")
    first_chunk = [e for e in events if e["kind"] == "session_update"][0]
    assert _chunk_text(first_chunk) == f"session {result['session_id']}"
    assert all(e["turn_id"] is None for e in events)


def _module_level_imports(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module or ""


def _all_imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module or ""


def test_import_discipline():
    wire = ast.parse(WIRE_SOURCE.read_text(encoding="utf-8"))
    for name in _all_imports(wire):
        top = name.split(".")[0]
        assert top == "__future__" or top in sys.stdlib_module_names, f"acp_wire imports non-stdlib {name}"

    adapter = ast.parse(ADAPTER_SOURCE.read_text(encoding="utf-8"))
    for name in _module_level_imports(adapter):
        top = name.split(".")[0]
        assert top != "acp", "acp_adapter imports the SDK at module level"
        assert top == "__future__" or top in sys.stdlib_module_names or name.startswith("runtime."), name
    forbidden = {"state", "widget_contract", "widget", "routing", "cli"}
    for name in _all_imports(adapter):
        assert name.split(".")[0] not in forbidden, f"acp_adapter imports {name}"


@pytest.mark.parametrize("source", [ADAPTER_SOURCE, WIRE_SOURCE], ids=lambda p: p.name)
def test_no_client_issued_identity(source):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assert "uuid" not in {name.split(".")[0] for name in _all_imports(tree)}
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert "session_" not in literals
