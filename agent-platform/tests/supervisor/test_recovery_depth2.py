# agent-platform/tests/supervisor/test_recovery_depth2.py
from runtime import session_state as state
from supervisor.coordinator import Coordinator
from supervisor.process_spawner import ChildProcess


class DeadSpawner:
    """Reports every child as not alive — simulates a full outage."""
    def is_alive(self, child): return False
    def terminate_gracefully(self, child, timeout): pass


def test_recover_marks_grandchild_lost_and_propagates_to_root(tmp_path):
    store = tmp_path
    root = state.create(store, task_id="t")
    depth1 = state.create(store, task_id="t")
    depth2 = state.create(store, task_id="t")

    state.append(store, root["session_id"], 0, "child.spawned", {
        "session_id": depth1["session_id"], "pid": 100, "pgid": 100,
        "start_time": 1.0, "allocated_budget": 3})
    state.append(store, depth1["session_id"], 0, "child.spawned", {
        "session_id": depth2["session_id"], "pid": 200, "pgid": 200,
        "start_time": 2.0, "allocated_budget": 1})
    # depth1 and depth2 never reach a terminal event — simulates a mid-run outage

    coordinator = Coordinator(store=store, spawner=DeadSpawner())
    coordinator.recover()

    depth2_doc = state.load(store, depth2["session_id"])
    depth2_terminal = next(e for e in depth2_doc["events"] if e["event_type"] == "session.terminal")
    assert depth2_terminal["payload"]["status"] == "lost"

    depth1_doc = state.load(store, depth1["session_id"])
    depth1_terminal = next(e for e in depth1_doc["events"] if e["event_type"] == "session.terminal")
    assert depth1_terminal["payload"]["status"] == "blocked"

    root_doc = state.load(store, root["session_id"])
    root_terminal = next(e for e in root_doc["events"] if e["event_type"] == "session.terminal")
    assert root_terminal["payload"]["status"] == "blocked"
    assert "lost" in root_terminal["payload"]["reason"] or "child" in root_terminal["payload"]["reason"]
