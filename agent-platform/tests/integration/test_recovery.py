from __future__ import annotations

import sys
import time

from runtime import session_state as state
from supervisor.coordinator import Coordinator
from supervisor.process_spawner import ProcessSpawner


def test_recover_reattaches_a_still_running_child(tmp_path):
    store = tmp_path / "sessions"
    root_session = state.create(store, task_id="recovery-test")
    root_session_id = root_session["session_id"]
    child_session = state.create(store, task_id="recovery-test-child")
    child_session_id = child_session["session_id"]

    script = tmp_path / "sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=child_session_id, args=[sys.executable, str(script)])

    seq = state.latest_sequence(state.load(store, root_session_id))
    state.append(store, root_session_id, seq, "child.spawned", {
        "session_id": child_session_id, "pid": child.pid, "pgid": child.pgid,
        "start_time": child.start_time, "allocated_budget": 1,
    })

    try:
        # simulate a brand-new Supervisor process (fresh Coordinator instance)
        coordinator = Coordinator(store=store, spawner=ProcessSpawner())
        summaries = coordinator.recover()

        assert any(s["root_session_id"] == root_session_id for s in summaries)
        child_doc = state.load(store, child_session_id)
        event_types = [e["event_type"] for e in child_doc["events"]]
        assert "session.reattached" in event_types
    finally:
        spawner.terminate_gracefully(child, timeout=5.0)


def test_recover_marks_a_dead_child_as_lost(tmp_path):
    store = tmp_path / "sessions"
    root_session = state.create(store, task_id="recovery-lost-test")
    root_session_id = root_session["session_id"]
    child_session = state.create(store, task_id="recovery-lost-test-child")
    child_session_id = child_session["session_id"]

    script = tmp_path / "quick.py"
    script.write_text("pass\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=child_session_id, args=[sys.executable, str(script)])

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and spawner.is_alive(child):
        time.sleep(0.1)

    seq = state.latest_sequence(state.load(store, root_session_id))
    state.append(store, root_session_id, seq, "child.spawned", {
        "session_id": child_session_id, "pid": child.pid, "pgid": child.pgid,
        "start_time": child.start_time, "allocated_budget": 1,
    })

    coordinator = Coordinator(store=store, spawner=ProcessSpawner())
    coordinator.recover()

    child_doc = state.load(store, child_session_id)
    terminal = next(e for e in child_doc["events"] if e["event_type"] == "session.terminal")
    assert terminal["payload"]["status"] == "lost"

    root_doc = state.load(store, root_session_id)
    root_terminal = next(e for e in root_doc["events"] if e["event_type"] == "session.terminal")
    assert root_terminal["payload"]["status"] == "blocked"
