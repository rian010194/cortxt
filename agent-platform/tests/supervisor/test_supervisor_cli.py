# agent-platform/tests/supervisor/test_supervisor_cli.py
from __future__ import annotations


def test_status_command_still_reports_child_status_after_run_tree_rewrite(tmp_path):
    from runtime import session_state as state
    from supervisor.supervisor_cli import _status

    root = state.create(tmp_path, task_id="t")
    child = state.create(tmp_path, task_id="t")
    state.append(tmp_path, root["session_id"], 0, "child.spawned", {
        "session_id": child["session_id"], "pid": 1, "pgid": 1,
        "start_time": 0.0, "allocated_budget": 1})
    state.append(tmp_path, child["session_id"], 0, "session.terminal", {"status": "succeeded"})
    state.append(tmp_path, root["session_id"], 1, "session.terminal", {"status": "succeeded"})

    result = _status(tmp_path, root["session_id"])
    assert result["root_status"] == "succeeded"
    assert result["children"] == [{"session_id": child["session_id"], "status": "succeeded"}]
