# agent-platform/tests/supervisor/test_run_tree.py
from __future__ import annotations

from supervisor.run_tree import RunTreeIndex, build_index


def _event(event_type: str, payload: dict) -> dict:
    return {"sequence": 0, "event_type": event_type, "payload": payload,
            "previous_hash": "0" * 64, "timestamp": "2026-08-16T00:00:00Z", "hash": "x"}


def test_build_index_reflects_spawned_children_and_budget():
    root = {
        "session_id": "session_root",
        "events": [
            _event("session.created", {"task_id": "t"}),
            _event("child.spawned", {"session_id": "session_c1", "pid": 111, "pgid": 111,
                                      "start_time": 1.0, "allocated_budget": 5}),
        ],
    }
    child1 = {
        "session_id": "session_c1",
        "events": [
            _event("session.created", {"task_id": "t"}),
            _event("session.terminal", {"status": "succeeded"}),
        ],
    }

    index = build_index(root, {"session_c1": child1}, total_budget=10)

    assert index.root_session_id == "session_root"
    assert index.allocated_budget == 5
    assert index.total_budget == 10
    assert len(index.children) == 1
    assert index.children[0].status == "succeeded"
    assert index.children[0].pid == 111
    assert index.join_satisfied is False


def test_join_satisfied_reflects_the_event():
    root = {
        "session_id": "session_root",
        "events": [
            _event("session.created", {"task_id": "t"}),
            _event("join.satisfied", {"child_session_id": "session_c2"}),
        ],
    }
    index = build_index(root, {}, total_budget=10)
    assert index.join_satisfied is True


def test_no_mutation_api_exists():
    import supervisor.run_tree as run_tree_module

    assert not hasattr(run_tree_module, "update_index")
    assert not hasattr(RunTreeIndex, "update")
    # frozen dataclass: attribute assignment must fail
    root = {"session_id": "session_root", "events": [_event("session.created", {"task_id": "t"})]}
    index = build_index(root, {}, total_budget=10)
    import dataclasses
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        index.root_status = "tampered"
