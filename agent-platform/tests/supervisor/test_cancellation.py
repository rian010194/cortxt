from __future__ import annotations

import sys
import time

from runtime import session_state as state
from supervisor.coordinator import Coordinator
from supervisor.process_spawner import ProcessSpawner


def test_cancel_root_terminates_a_running_child(tmp_path):
    store = tmp_path / "sessions"
    coordinator = Coordinator(store=store)
    root_session = state.create(store, task_id="cancel-test")
    root_session_id = root_session["session_id"]

    child_session = state.create(store, task_id="cancel-test-child")
    child_session_id = child_session["session_id"]
    script = tmp_path / "sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=child_session_id, args=[sys.executable, str(script)])
    coordinator._spawner = spawner

    seq = state.latest_sequence(state.load(store, root_session_id))
    state.append(store, root_session_id, seq, "child.spawned", {
        "session_id": child_session_id, "pid": child.pid, "pgid": child.pgid,
        "start_time": child.start_time, "allocated_budget": 1,
    })

    assert spawner.is_alive(child)
    result = coordinator.cancel_root(root_session_id)
    assert child_session_id in result["cancelled"]

    time.sleep(0.5)
    assert not spawner.is_alive(child)
    doc = state.load(store, child_session_id)
    terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
    assert terminal["payload"]["status"] == "cancelled"
