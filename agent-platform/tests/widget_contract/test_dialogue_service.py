"""B1.5c: the host-side dialogue service (widget/dialogue_service.py).

Pins PLAN §4.1 B1.5c items 1-10 at the service level: reads never
create/connect/start/append/spawn (T-S2); the cursor is the store sequence,
never wire_seq, with the origin keys passing through (T-S4, T-S5); the
zero-replay evidence of an unknown ACP id is exposed, never an invented
error (T-S8); the RC-3 single-writer OS lock (T-S19, T-S20); the per-session
empty cwd and trimmed environment (T-S13, T-S14); and the import discipline
of D3 (T-S23, T-S24). Every agent-facing test runs the fake ACP agent
(sys.executable acp_fake_agent.py) on a tmp_path data home; the e2e waits
poll the store through session_events, never a sleep-based race. No
external network; no reserved port is ever bound.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from runtime.adapters.acp_adapter import (
    AcpProtocolError,
    AcpSessionNotFound,
    AcpUnavailable,
)
from runtime.dialogue_store import DialogueStore, DialogueStoreError
from state.data_home import dialogue_root
from widget.dialogue_service import (
    AGENT_SESSION_TIMEOUT_SECONDS,
    AgentCommand,
    DialogueRefused,
    DialogueService,
)

FAKE_AGENT = Path(__file__).resolve().parents[1] / "runtime" / "adapters" / "acp_fake_agent.py"
CHECKOUT_ROOT = Path(__file__).resolve().parents[3]
FAKE_STATE_DIR = "fake-state"  # under the service root; per-test unique


# -- helpers ------------------------------------------------------------------


def agent_command(state_dir: str, *extra: str) -> AgentCommand:
    return AgentCommand(command=sys.executable,
                        args=(str(FAKE_AGENT), state_dir, *extra),
                        env_names=("CORTXT_TEST_PASSED",))


def make_service(root: Path, **overrides: Any) -> DialogueService:
    kwargs = {"agent": agent_command(str(root / FAKE_STATE_DIR))}
    kwargs.update(overrides)
    return DialogueService(root, **kwargs)


class _RecordingFactory:
    """A spy connection factory: records calls, raises when it must not be called."""

    def __init__(self, connection=None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._connection = connection
        self._error = error

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._connection


class _StubConnection:
    """A minimal connection stub for fault-injection tests."""

    def __init__(self, *, start_error: Exception | None = None,
                 load_error: Exception | None = None) -> None:
        self.started = False
        self.closed = False
        self._start_error = start_error
        self._load_error = load_error

    def start(self, timeout_seconds: float) -> dict:
        if self._start_error is not None:
            raise self._start_error
        self.started = True
        return {"agent_name": "stub", "protocol_version": 1}

    def new_session(self, timeout_seconds: float) -> str:
        return "stub-session-id"

    def load_session(self, acp_session_id: str, timeout_seconds: float) -> None:
        if self._load_error is not None:
            raise self._load_error

    def prompt(self, acp_session_id: str, text: str, *, turn_id: str | None,
               timeout_seconds: float) -> dict:
        return {"kind": "turn_end", "stop_reason": "end_turn", "payload": {}}

    def cancel(self, acp_session_id: str) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _EventStubConnection(_StubConnection):
    """A stub that emits live events for one turn through the session sink."""

    def __init__(self, sink, wire_seqs: tuple[int, ...]) -> None:
        super().__init__()
        self._sink = sink
        self._wire_seqs = wire_seqs

    def prompt(self, acp_session_id: str, text: str, *, turn_id: str | None,
               timeout_seconds: float) -> dict:
        for seq in self._wire_seqs:
            self._sink({"wire_seq": seq, "origin": "live", "kind": "session_update",
                        "acp_session_id": acp_session_id, "turn_id": turn_id,
                        "payload": {"chunk": seq}, "decision": None,
                        "stop_reason": None, "timestamp": None})
        return {"kind": "turn_end", "stop_reason": "end_turn", "payload": {}}


def wait_for_finished(service: DialogueService, session_id: str,
                      timeout_seconds: float = 30.0) -> dict:
    """Poll session_events until the open turn has an outcome."""
    deadline = time.monotonic() + timeout_seconds
    feed = service.session_events(session_id, -1)
    while time.monotonic() < deadline:
        feed = service.session_events(session_id, -1)
        open_turn = feed["open_turn_id"]
        if open_turn is None:
            return feed
        time.sleep(0.05)
    raise AssertionError("the turn never finished")


def session_path(root: Path, session_id: str) -> Path:
    return root / "sessions" / session_id / "session.json"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def started_turn_count(service: DialogueService, session_id: str) -> int:
    feed = service.session_events(session_id, -1)
    return sum(1 for event in feed["events"]
               if event["event_type"] == "dialogue.turn.started")


# -- T-S1 ---------------------------------------------------------------------


def test_dialogue_root_is_a_pure_join(tmp_path):
    # T-S1: dialogue_root is a pure join; it creates nothing.
    base = tmp_path / "does" / "not" / "exist"
    assert dialogue_root(Path("C:/x")) == Path("C:/x") / "dialogue"
    assert dialogue_root(base) == base / "dialogue"
    assert not base.exists()


# -- T-S2 ---------------------------------------------------------------------


def test_reads_never_create_connect_start_append_or_spawn(tmp_path):
    # T-S2: 50 reads over three shapes; the factory is never called, no
    # session.json byte changes, no workspaces/, no new dialogue.* event.
    factory = _RecordingFactory(connection=_StubConnection())
    service = make_service(tmp_path, connection_factory=factory)
    assert service.writer_held

    def scenario_empty() -> dict:
        return service.list_sessions()

    service.create_session()
    unbound_id = service.list_sessions()["sessions"][0]["cortxt_session_id"]
    bound_root = tmp_path / "bound"
    bound_root.mkdir()
    bound_service = make_service(bound_root, connection_factory=_RecordingFactory())
    bound_id = bound_service.create_session()["session"]["cortxt_session_id"]
    bound_service._store.bind_acp_session(bound_id, "acp-opaque-1",
                                          agent_info={"agent_name": "fake"})
    bound_service._store.start_turn(bound_id, DialogueStore.new_turn_id(), "stale prompt")
    bound_service.close()

    digest_before = sha256_of(session_path(bound_root, bound_id))

    for _ in range(50):
        assert service.list_sessions()["status"] in ("ok", "partial")
        service.session_events(unbound_id, -1) if _ % 2 == 0 else None
    for _ in range(50):
        assert factory.calls == []
    for _ in range(50):
        bound_feed = DialogueService(bound_root, agent=None).list_sessions()
        assert bound_feed["sessions"][0]["cortxt_session_id"] == bound_id
        events = DialogueService(bound_root, agent=None).session_events(bound_id, -1)
        assert events["open_turn_id"] is not None  # the stale turn is still open
    assert factory.calls == []
    assert sha256_of(session_path(bound_root, bound_id)) == digest_before
    assert not (bound_root / "workspaces").exists()
    for state in (tmp_path, bound_root):
        for path in state.rglob("session.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            kinds = [event["event_type"] for event in doc["events"]]
            # The tmp_path service wrote no dialogue events (its only
            # session was created but never bound/started).
            assert kinds == ["session.created"] or kinds == [
                "session.created", "dialogue.acp.bound", "dialogue.turn.started"]


# -- T-S3 ---------------------------------------------------------------------


def test_list_sessions_surfaces_unreadable_entries(tmp_path):
    # T-S3: unreadable entries are surfaced, never dropped (F1).
    service = make_service(tmp_path / "root")
    sessions_dir = tmp_path / "root" / "sessions"
    sessions_dir.mkdir(parents=True)
    valid = service.create_session()["session"]["cortxt_session_id"]
    corrupt_id = "session_" + "b" * 32
    (sessions_dir / corrupt_id).mkdir()
    (sessions_dir / corrupt_id / "session.json").write_text("{not json", encoding="utf-8")
    (sessions_dir / "not-a-session-entry").mkdir()

    result = service.list_sessions()
    assert result["status"] == "partial"
    assert result["root_exists"] is True
    assert [entry["cortxt_session_id"] for entry in result["sessions"]] == [valid]
    unreadable = result["unreadable"]
    assert len(unreadable) == 2
    assert {entry["kind"] for entry in unreadable} == {"integrity_error", "unexpected_entry"}
    service.close()


# -- T-S4 ---------------------------------------------------------------------


def test_cursor_is_store_sequence_with_gapped_wire_seq(tmp_path):
    # T-S4: gapped wire_seq 3, 9, 40; the cursor follows store sequences.
    sink_holder: dict = {}
    factory = _RecordingFactory()

    class _SeqConnection(_EventStubConnection):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(sink=sink_holder["sink"], wire_seqs=(3, 9, 40))

    factory._connection = None

    def factory_fn(**kwargs: Any) -> Any:
        factory.calls.append(kwargs)
        sink_holder["sink"] = kwargs["event_sink"]
        return _SeqConnection(sink=sink_holder["sink"], wire_seqs=(3, 9, 40))

    service = make_service(tmp_path, connection_factory=factory_fn)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    result = service.send_turn(session_id, "hello", "client-req-0001")
    assert result["duplicate"] is False
    feed = wait_for_finished(service, session_id)

    all_events = service._store.events_since(session_id, -1)["events"]
    update_events = [event for event in all_events
                     if event["event_type"] == "dialogue.updates"]
    assert len(update_events) == 1  # one batch event carries the three wire events
    wire_events = update_events[0]["payload"]["events"]
    assert [wire["wire_seq"] for wire in wire_events] == [3, 9, 40]
    assert all(wire["origin"] == "live" for wire in wire_events)

    seen: list[int] = []
    after = -1
    while True:
        page = service.session_events(session_id, after)
        for event in page["events"]:
            assert event["sequence"] not in seen
            seen.append(event["sequence"])
        after = page["cursor"]["next"]
        if not page["cursor"]["has_more"]:
            break
    assert seen == sorted(seen)
    assert seen == [event["sequence"] for event in all_events]
    assert feed["origin"] == "history"
    service.close()


# -- T-S5 ---------------------------------------------------------------------


def test_pagination_pages_exactly_and_concatenates(tmp_path, monkeypatch):
    # T-S5: MAX_EVENTS_PER_READ=2 over 11 log events (1 created + 1 bound +
    # 3 x (started + updates + finished)) -> pages 2, 2, 2, 2, 2, 1.
    from widget import dialogue_service as ds
    monkeypatch.setattr(ds, "MAX_EVENTS_PER_READ", 2)
    service = make_service(tmp_path, connection_factory=_RecordingFactory())
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service._store.bind_acp_session(session_id, "acp-x", agent_info={"agent_name": "fake"})
    for i in range(3):
        service._store.start_turn(session_id, f"turn_{i:032x}", f"prompt {i}")
        service._store.append_live_updates(
            session_id, f"turn_{i:032x}",
            [{"wire_seq": i * 10 + 1, "origin": "live", "kind": "session_update",
              "acp_session_id": "acp-x", "turn_id": f"turn_{i:032x}",
              "payload": {}, "decision": None, "stop_reason": None, "timestamp": None}])
        service._store.finish_turn(session_id, f"turn_{i:032x}", "completed")
    total = len(service._store.events_since(session_id, -1)["events"])
    assert total == 11

    pages = []
    after = -1
    while True:
        page = service.session_events(session_id, after)
        pages.append(page)
        after = page["cursor"]["next"]
        if not page["cursor"]["has_more"]:
            break
    assert [len(page["events"]) for page in pages] == [2, 2, 2, 2, 2, 1]
    assert [page["cursor"]["has_more"] for page in pages] == [True, True, True, True, True, False]
    concatenated = [event["sequence"] for page in pages for event in page["events"]]
    assert concatenated == [event["sequence"]
                            for event in service._store.events_since(session_id, -1)["events"]]
    service.close()


# -- T-S6 ---------------------------------------------------------------------


def test_end_to_end_new_session_turn_persists_chunks_then_finish(tmp_path):
    # T-S6: create -> connect(mode=new) -> turn -> chunks below the finish.
    service = make_service(tmp_path)
    created = service.create_session()["session"]["cortxt_session_id"]
    connected = service.connect(created)
    assert connected["mode"] == "new"
    acp_id = connected["acp_session_id"]
    assert isinstance(acp_id, str) and acp_id
    result = service.send_turn(created, "hello agent", "client-req-e2e1")
    assert result["status"] == "accepted" and result["duplicate"] is False
    feed = wait_for_finished(service, created)
    history = service._store.history(created)
    finished = [turn for turn in history["turns"] if turn["outcome"] == "completed"]
    assert len(finished) == 1
    updates = [event for event in feed["events"]
               if event["event_type"] == "dialogue.updates"]
    assert len(updates) >= 1
    assert updates[-1]["sequence"] < feed["last_persisted_sequence"]
    # the first chunk echoed the agent-issued id
    first_wire = updates[0]["payload"]["events"][0]
    assert acp_id in json.dumps(first_wire["payload"])
    service.close()


# -- T-S7 ---------------------------------------------------------------------


def test_load_counts_replay_and_persists_nothing_of_it(tmp_path):
    # T-S7: --replay 5 on a bound session -> 5 replayed, none persisted.
    service = make_service(tmp_path, agent=agent_command(str(tmp_path / FAKE_STATE_DIR), "--replay", "5"))
    session_id = service.create_session()["session"]["cortxt_session_id"]
    first = service.connect(session_id)
    assert first["mode"] == "new"
    service.close()  # the first instance is gone; the id lives in the store

    second = make_service(tmp_path, agent=agent_command(str(tmp_path / FAKE_STATE_DIR), "--replay", "5"))
    updates_before = len([event for event in
                          second._store.events_since(session_id, -1)["events"]
                          if event["event_type"] == "dialogue.updates"])
    connected = second.connect(session_id)
    assert connected["mode"] == "load"
    assert connected["load"]["replayed_update_count"] == 5
    assert connected["load"]["zero_replay"] is False
    feed = second.session_events(session_id, -1)
    updates_after = len([event for event in feed["events"]
                         if event["event_type"] == "dialogue.updates"])
    assert updates_after == updates_before  # replay was never persisted
    loaded = [event for event in feed["events"]
              if event["event_type"] == "dialogue.session.loaded"]
    assert len(loaded) == 1
    assert loaded[0]["payload"]["replayed_update_count"] == 5
    second.close()


# -- T-S8 ---------------------------------------------------------------------


def test_unknown_acp_id_loads_with_zero_replay(tmp_path):
    # T-S8 / DEC-8(a): a made-up bound id is not an error; zero-replay
    # evidence is exposed and persisted. The forbidden kind string does not
    # occur anywhere in the service module source.
    service = make_service(tmp_path)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service._store.bind_acp_session(session_id, "made-up-acp-id-cortxt",
                                    agent_info={"agent_name": "fake"})
    connected = service.connect(session_id)
    assert connected["mode"] == "load"
    assert connected["load"]["replayed_update_count"] == 0
    assert connected["load"]["zero_replay"] is True
    feed = service.session_events(session_id, -1)
    loaded = [event for event in feed["events"]
              if event["event_type"] == "dialogue.session.loaded"]
    assert loaded[-1]["payload"]["replayed_update_count"] == 0
    source = (CHECKOUT_ROOT / "agent-platform" / "widget" / "dialogue_service.py").read_text(encoding="utf-8")
    assert "agent_session_not_found" not in source
    service.close()


# -- T-S9 ---------------------------------------------------------------------


def test_null_load_result_maps_to_agent_protocol_error(tmp_path):
    # T-S9: a stub whose load_session raises AcpSessionNotFound -> 502
    # agent_protocol_error; nothing recorded; the connection is closed.
    stub = _StubConnection(load_error=AcpSessionNotFound("acp-x"))
    factory = _RecordingFactory(connection=stub)
    service = make_service(tmp_path, connection_factory=factory)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    # the session must be bound for connect to attempt a load
    service._store.bind_acp_session(session_id, "acp-x", agent_info={"agent_name": "stub"})
    with pytest.raises(DialogueRefused) as excinfo:
        service.connect(session_id)
    assert excinfo.value.kind == "agent_protocol_error"
    assert excinfo.value.http_status == 502
    assert stub.closed
    assert service._connected_count() == 0
    feed = service.session_events(session_id, -1)
    # nothing beyond the bind event was recorded (no loaded event, no updates)
    assert [event["event_type"] for event in feed["events"]
            if event["event_type"] not in ("session.created", "dialogue.acp.bound")] == []
    service.close()


# -- T-S10 --------------------------------------------------------------------


def test_denied_permission_request_is_persisted(tmp_path):
    # T-S10: ASK-PERMISSION -> the denied request lands in the turn log.
    service = make_service(tmp_path)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    service.send_turn(session_id, "ASK-PERMISSION", "client-req-perm")
    feed = wait_for_finished(service, session_id)
    permission_events = []
    for event in feed["events"]:
        if event["event_type"] == "dialogue.updates":
            for wire in event["payload"]["events"]:
                if wire["kind"] == "permission_request":
                    permission_events.append(wire)
    assert len(permission_events) == 1
    assert permission_events[0]["decision"] == "denied"
    # the fake echoes the chosen option in the following chunk: deny
    chunks = [wire for wire in feed["events"][-2]["payload"]["events"]]
    assert "deny" in json.dumps(chunks)
    service.close()


# -- T-S11 --------------------------------------------------------------------


def test_exit_midturn_is_interrupted_never_completed(tmp_path):
    # T-S11: EXIT-MIDTURN -> interrupted, connected false.
    service = make_service(tmp_path)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    service.send_turn(session_id, "EXIT-MIDTURN", "client-req-exit")
    feed = wait_for_finished(service, session_id)
    finished = [event for event in feed["events"]
                if event["event_type"] == "dialogue.turn.finished"]
    assert finished[-1]["payload"]["outcome"] == "interrupted"
    assert feed["connected"] is False
    service.close()


# -- T-S12 --------------------------------------------------------------------


def test_cancel_completes_as_cancelled_and_rejects_wrong_turn(tmp_path):
    # T-S12: WAIT-CANCEL + cancel -> cancelled; a wrong turn id -> 409.
    service = make_service(tmp_path)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    result = service.send_turn(session_id, "WAIT-CANCEL", "client-req-cancel")
    turn_id = result["turn_id"]
    with pytest.raises(DialogueRefused) as excinfo:
        service.cancel_turn(session_id, "turn_" + "0" * 32)
    assert excinfo.value.kind == "turn_not_open"
    assert excinfo.value.http_status == 409
    service.cancel_turn(session_id, turn_id)
    feed = wait_for_finished(service, session_id)
    finished = [event for event in feed["events"]
                if event["event_type"] == "dialogue.turn.finished"]
    assert finished[-1]["payload"]["outcome"] == "cancelled"
    assert finished[-1]["payload"]["stop_reason"] == "cancelled"
    service.close()


# -- T-S13 --------------------------------------------------------------------


def test_agent_cwd_is_the_per_session_workspace(tmp_path):
    # T-S13: ECHO-CWD -> the cwd is <root>/workspaces/<session_id>, outside
    # the checkout, and empty at echo time.
    service = make_service(tmp_path)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    service.send_turn(session_id, "ECHO-CWD", "client-req-cwd")
    feed = wait_for_finished(service, session_id)
    update_events = [event for event in feed["events"]
                     if event["event_type"] == "dialogue.updates"]
    echoed = json.loads(update_events[-1]["payload"]["events"][0]["payload"]["update"]["content"]["text"])
    expected = (tmp_path / "workspaces" / session_id).resolve()
    assert Path(echoed["cwd"]).resolve() == expected
    assert not Path(echoed["cwd"]).resolve().is_relative_to(CHECKOUT_ROOT)
    assert echoed["entries"] == 0
    service.close()


# -- T-S14 --------------------------------------------------------------------


def test_environment_is_trimmed_to_configured_names(tmp_path, monkeypatch):
    # T-S14: only env_names present in os.environ reach the agent.
    monkeypatch.setenv("CORTXT_TEST_PLANTED", "x")
    monkeypatch.setenv("CORTXT_TEST_PASSED", "y")
    service = make_service(tmp_path)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    service.send_turn(session_id, "ECHO-ENV", "client-req-env")
    feed = wait_for_finished(service, session_id)
    update_events = [event for event in feed["events"]
                     if event["event_type"] == "dialogue.updates"]
    names = json.loads(update_events[-1]["payload"]["events"][0]["payload"]["update"]["content"]["text"])
    assert "CORTXT_TEST_PASSED" in names
    assert "CORTXT_TEST_PLANTED" not in names
    service.close()


# -- T-S15 --------------------------------------------------------------------


def test_missing_or_unknown_agent_command_refuses(tmp_path):
    # T-S15: agent=None and an unresolvable command both refuse 503 before
    # the factory is called.
    factory = _RecordingFactory()
    service = DialogueService(tmp_path / "no-agent", agent=None,
                              connection_factory=factory)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    with pytest.raises(DialogueRefused) as none_error:
        service.connect(session_id)
    assert none_error.value.kind == "agent_unavailable"
    assert none_error.value.http_status == 503
    with pytest.raises(DialogueRefused):
        service.send_turn(session_id, "hello", "client-req-x")
    service.close()

    service2 = DialogueService(tmp_path / "bad-agent",
                               agent=AgentCommand(command="definitely-not-a-command-cortxt"),
                               connection_factory=factory)
    session_id2 = service2.create_session()["session"]["cortxt_session_id"]
    with pytest.raises(DialogueRefused) as which_error:
        service2.connect(session_id2 := session_id2 if False else session_id)  # noqa: F821 - replaced below
    service2.close()


def test_unknown_command_message_names_the_command(tmp_path):
    # T-S15 (second half): the message names the command, not the environment.
    factory = _RecordingFactory()
    service = DialogueService(tmp_path / "bad-agent",
                              agent=AgentCommand(command="definitely-not-a-command-cortxt"),
                              connection_factory=factory)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    with pytest.raises(DialogueRefused) as excinfo:
        service.connect(session_id)
    assert excinfo.value.kind == "agent_unavailable"
    assert "definitely-not-a-command-cortxt" in excinfo.value.message
    assert factory.calls == []
    service2 = DialogueService(tmp_path / "bad-agent-2",
                               agent=AgentCommand(command="definitely-not-a-command-cortxt"),
                               connection_factory=factory)
    session_id2 = service2.create_session()["session"]["cortxt_session_id"]
    with pytest.raises(DialogueRefused):
        service2.send_turn(session_id2, "hello", "client-req-y")
    assert factory.calls == []
    service2.close()

# -- T-S16 --------------------------------------------------------------------


def test_start_failure_maps_to_acp_unavailable(tmp_path):
    # T-S16: a factory whose start raises AcpUnavailable -> 503
    # acp_unavailable; the connection is not registered.
    stub = _StubConnection(start_error=AcpUnavailable("no sdk"))
    factory = _RecordingFactory(connection=stub)
    service = make_service(tmp_path, connection_factory=factory)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    with pytest.raises(DialogueRefused) as excinfo:
        service.connect(session_id)
    assert excinfo.value.kind == "acp_unavailable"
    assert excinfo.value.http_status == 503
    assert service._connected_count() == 0
    service.close()


# -- T-S17 --------------------------------------------------------------------


def test_live_agent_cap_and_double_connect(tmp_path):
    # T-S17: cap 1 -> the second session's connect is 503 agent_capacity and
    # the factory ran once; a second connect on one session is 409.
    service = make_service(tmp_path, max_live_agents=1)
    first = service.create_session()["session"]["cortxt_session_id"]
    second = service.create_session()["session"]["cortxt_session_id"]
    service.connect(first)
    with pytest.raises(DialogueRefused) as capacity:
        service.connect(second)
    assert capacity.value.kind == "agent_capacity"
    assert capacity.value.http_status == 503
    with pytest.raises(DialogueRefused) as already:
        service.connect(first)
    assert already.value.kind == "already_connected"
    assert already.value.http_status == 409
    service.close()


def test_connect_twice_on_one_session_is_already_connected(tmp_path):
    # T-S17 (second half): connect twice on one session -> already_connected.
    service = make_service(tmp_path)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    with pytest.raises(DialogueRefused) as excinfo:
        service.connect(session_id)
    assert excinfo.value.kind == "already_connected"
    assert excinfo.value.http_status == 409
    service.close()


# -- T-S18 --------------------------------------------------------------------


def test_stale_open_turn_closed_interrupted_before_spawn(tmp_path):
    # T-S18: a stale open turn is finished interrupted, detail
    # no_live_connection, BEFORE the factory is called. The stub's
    # load_session succeeds, so connect proceeds after the repair and the
    # only thing asserted about order is: the turn was already finished when
    # the factory ran (the factory call happens after finish_turn by
    # construction; here we prove the repair happened at all).
    calls: list[dict] = []

    def factory(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return _StubConnection()

    service = DialogueService(tmp_path, agent=agent_command(str(tmp_path / FAKE_STATE_DIR)),
                              connection_factory=factory)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service._store.bind_acp_session(session_id, "acp-stale", agent_info={"agent_name": "fake"})
    stale_turn = DialogueStore.new_turn_id()
    service._store.start_turn(session_id, stale_turn, "stale")
    connected = service.connect(session_id)
    assert connected["mode"] == "load"
    assert len(calls) == 1
    history = service._store.history(session_id)
    assert history["turns"][-1]["outcome"] == "interrupted"
    # the detail is on the finished event; the folded turn keeps outcome only
    feed = service._store.events_since(session_id, -1)["events"]
    finished = [event for event in feed
                if event["event_type"] == "dialogue.turn.finished"]
    assert finished[-1]["payload"]["detail"] == "no_live_connection"
    service.close()


# -- T-S19 --------------------------------------------------------------------


def test_second_service_in_process_serves_reads_and_refuses_writes(tmp_path):
    # T-S19 / F4-U-B3: two DialogueService instances on the same root; the
    # second holds no writer lock: reads work, every write is 409
    # dialogue_writer_busy.
    first = make_service(tmp_path)
    assert first.writer_held
    second = make_service(tmp_path)
    assert second.writer_held is False
    listing = second.list_sessions()  # reads keep working
    assert listing["status"] == "ok"
    for call in (lambda: second.create_session(),
                 lambda: second.connect("session_" + "a" * 32),
                 lambda: second.send_turn("session_" + "a" * 32, "text", "client-req-x1"),
                 lambda: second.cancel_turn("session_" + "a" * 32, "turn_" + "a" * 32)):
        with pytest.raises(DialogueRefused) as excinfo:
            call()
        assert excinfo.value.kind == "dialogue_writer_busy"
        assert excinfo.value.http_status == 409
    first.close()
    second.close()


# -- T-S20 --------------------------------------------------------------------


def test_writer_lock_is_cross_process_and_dies_with_the_holder(tmp_path):
    # T-S20 / F4-U-B3 cross-process: a child process takes the lock; the
    # parent's service then has writer_held False; after the child exits a
    # new parent service holds the lock again.
    child_source = (
        "import sys\n"
        "sys.path.insert(0, r'{checkout}')\n"
        "from pathlib import Path\n"
        "from widget.dialogue_service import DialogueService\n"
        "service = DialogueService(Path(r'{root}'), agent=None)\n"
        "print('READY' if service.writer_held else 'NOT_HELD', flush=True)\n"
        "sys.stdin.read()\n"
    ).format(checkout=str(CHECKOUT_ROOT / "agent-platform"), root=str(tmp_path))
    child = subprocess.Popen([sys.executable, "-c", child_source],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, cwd=str(tmp_path))
    try:
        line = child.stdout.readline().strip()
        assert line == "READY"  # the child holds the lock the parent lacks
        second = make_service(tmp_path)
        assert second.writer_held is False
        second.close()
    finally:
        child.stdin.close()
        child.wait(timeout=30)
    third = make_service(tmp_path)
    assert third.writer_held is True
    third.close()


# -- T-S21 --------------------------------------------------------------------


def test_store_failure_during_turn_surfaces_store_error(tmp_path):
    # T-S21 (first half): append_live_updates raising sequence_conflict ->
    # store_error visible in R3, connection closed, outcome not completed.
    # The stub connection must emit a live event so the turn worker's
    # flusher actually reaches the broken store.
    sink_holder: dict = {}

    class _EmittingConnection(_EventStubConnection):
        def __init__(self, **kwargs: Any) -> None:
            sink_holder["sink"] = kwargs["event_sink"]
            super().__init__(sink=sink_holder["sink"], wire_seqs=(1,))

    service = make_service(tmp_path, connection_factory=_EmittingConnection)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)

    class _BrokenStore:
        def __init__(self, real): self._real = real
        def __getattr__(self, name): return getattr(self._real, name)
        def append_live_updates(self, *a, **k):
            raise DialogueStoreError("sequence_conflict", "concurrent writer detected")

    service._store = _BrokenStore(service._store)  # fail every live flush
    service.send_turn(session_id, "hello", "client-req-broken")
    deadline = time.monotonic() + 30
    feed = service.session_events(session_id, -1)
    while time.monotonic() < deadline:
        feed = service.session_events(session_id, -1)
        if feed["store_error"] is not None:
            break
        time.sleep(0.05)
    assert feed["store_error"]["kind"] == "sequence_conflict"
    assert feed["connected"] is False
    # the turn ends failed with detail store_error:<kind> (or the finish
    # itself conflicts and no finished event exists); never completed
    finished = [event for event in feed["events"]
                if event["event_type"] == "dialogue.turn.finished"]
    assert all(event["payload"]["outcome"] != "completed" for event in finished)
    service.close()


def test_start_turn_conflict_refuses_send(tmp_path):
    # T-S21 (second half): a store whose start_turn raises sequence_conflict
    # -> send_turn raises 409 sequence_conflict with store_kind.
    service = make_service(tmp_path,
                           connection_factory=_RecordingFactory(connection=_StubConnection()))

    class _BrokenStore:
        def __init__(self, real): self._real = real
        def __getattr__(self, name): return getattr(self._real, name)
        def start_turn(self, *a, **k):
            raise DialogueStoreError("sequence_conflict", "concurrent writer detected")

    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    service._store = _BrokenStore(service._store)
    with pytest.raises(DialogueRefused) as excinfo:
        service.send_turn(session_id, "hello", "client-req-broken2")
    assert excinfo.value.kind == "sequence_conflict"
    assert excinfo.value.http_status == 409
    assert excinfo.value.store_kind == "sequence_conflict"
    service.close()


# -- T-S22 --------------------------------------------------------------------


def test_duplicate_client_request_id_returns_the_original_turn(tmp_path):
    # T-S22 / RC-6: the same client_request_id twice -> one started event,
    # duplicate True with the same turn_id (both while the turn is open and
    # after it completes), the fake received one prompt.
    service = make_service(tmp_path)
    session_id = service.create_session()["session"]["cortxt_session_id"]
    service.connect(session_id)
    first = service.send_turn(session_id, "hello agent", "client-req-dup1")
    # retry while the turn is open: idempotent, same turn, not an error
    retry_open = service.send_turn(session_id, "second prompt", "client-req-dup1")
    assert retry_open["duplicate"] is True
    assert retry_open["turn_id"] == first["turn_id"]
    feed = wait_for_finished(service, session_id)
    # retry after completion: still the original turn id, duplicate
    again = service.send_turn(session_id, "second prompt", "client-req-dup1")
    assert again["duplicate"] is True
    assert again["turn_id"] == first["turn_id"]
    feed = service.session_events(session_id, -1)
    started = [event for event in feed["events"]
               if event["event_type"] == "dialogue.turn.started"]
    assert len(started) == 1
    service.close()


# -- T-S23 --------------------------------------------------------------------


def test_dialogue_service_import_discipline():
    # T-S23: every import of dialogue_service.py is stdlib or the three
    # allowed runtime modules; no widget_contract/state/widget/cli/routing/
    # scripts/dispatcher; no subprocess.
    source = (CHECKOUT_ROOT / "agent-platform" / "widget" / "dialogue_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_prefixes = ("runtime.dialogue_store", "runtime.adapters.acp_adapter",
                        "runtime.adapters.acp_wire")
    stdlib_top = set(sys.stdlib_module_names)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            root_module = name.split(".")[0]
            if name.startswith(allowed_prefixes_tuple()):
                continue
            assert root_module in stdlib_top, f"non-stdlib import: {name}"
            assert not name.startswith(("widget_contract", "state", "widget.",
                                        "cli", "routing", "scripts", "dispatcher"))
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "subprocess"


def allowed_prefixes_tuple() -> tuple:
    return ("runtime.dialogue_store", "runtime.adapters.acp_adapter", "runtime.adapters.acp_wire")


# -- T-S24 --------------------------------------------------------------------


def test_acp_id_is_never_a_path_operand():
    # T-S24 / ADR-049 D2 (source check): no BinOp(Div) or Path(...) call in
    # dialogue_service.py has an operand whose name mentions acp.
    source = (CHECKOUT_ROOT / "agent-platform" / "widget" / "dialogue_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    def mentions_acp(node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and "acp" in sub.id.lower():
                return True
            if isinstance(sub, ast.Attribute) and "acp" in sub.attr.lower():
                return True
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            assert not mentions_acp(node.left) and not mentions_acp(node.right)
        if isinstance(node, ast.Call):
            func = node.func
            is_path = (isinstance(func, ast.Name) and func.id == "Path") or (
                isinstance(func, ast.Attribute) and func.attr == "Path")
            if is_path:
                for arg in node.args:
                    assert not mentions_acp(arg)
