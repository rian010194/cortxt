from __future__ import annotations

import sys
import time

from runtime import session_state as state
from supervisor.coordinator import Coordinator, CoordinatorError
from supervisor.process_spawner import ProcessSpawner


def test_wait_for_terminal_cancels_a_child_with_no_recent_heartbeat(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="stale-heartbeat-test")
    session_id = session["session_id"]

    script = tmp_path / "silent_sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=session_id, args=[sys.executable, str(script)])

    coordinator = Coordinator(store=store, spawner=spawner)
    try:
        doc = coordinator._wait_for_terminal(
            session_id, child, poll_interval=0.05, deadline=time.monotonic() + 5.0,
            heartbeat_interval=0.1, stale_multiplier=2,
        )
        terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
        assert terminal["payload"]["status"] == "blocked"
        assert terminal["payload"]["reason"] == "heartbeat timeout"
        assert not spawner.is_alive(child)
    finally:
        if spawner.is_alive(child):
            spawner.terminate_gracefully(child, timeout=1.0)


def test_wait_for_terminal_does_not_cancel_a_child_with_recent_heartbeats(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="fresh-heartbeat-test")
    session_id = session["session_id"]
    from runtime.session_writer import SessionWriter

    writer = SessionWriter(store, session_id)
    writer.append("heartbeat.ping", {})

    script = tmp_path / "quick2.py"
    script.write_text("pass\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=session_id, args=[sys.executable, str(script)])

    seq = state.latest_sequence(state.load(store, session_id))
    state.append(store, session_id, seq, "session.terminal", {"status": "succeeded"})

    coordinator = Coordinator(store=store, spawner=spawner)
    doc = coordinator._wait_for_terminal(
        session_id, child, poll_interval=0.05, deadline=time.monotonic() + 5.0,
        heartbeat_interval=10.0, stale_multiplier=3,
    )
    terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
    assert terminal["payload"]["status"] == "succeeded"
