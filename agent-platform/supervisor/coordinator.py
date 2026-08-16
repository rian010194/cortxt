"""Coordinator: root-session lifecycle, spawning, joins, integration
(design spec §7.2 state machine, decision 5's M1/M2 staging).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from runtime import session_state as state
from runtime.execution.write_policy import WriteCaps
from supervisor.budget import next_child_budget, reclaimable_surplus
from supervisor.process_spawner import ChildProcess, ProcessSpawner
from supervisor.run_tree import build_index
from supervisor.workspace_handoff import apply_incoming_changes


class CoordinatorError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


TERMINAL_CHILD_STATUSES = {"succeeded", "blocked", "failed", "cancelled", "lost"}


class Coordinator:
    def __init__(self, store: Path, spawner: ProcessSpawner | None = None) -> None:
        self._store = Path(store)
        self._spawner = spawner or ProcessSpawner()

    def _spawn_child(self, root_session_id: str, config: dict, allocated_budget: int) -> tuple[str, ChildProcess]:
        child_session = state.create(self._store, task_id=config["task_id"])
        child_session_id = child_session["session_id"]

        fd, config_path_str = tempfile.mkstemp(prefix="fas4-child-config-", suffix=".json")
        config_path = Path(config_path_str)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(config))

        args = [sys.executable, "-m", "runtime.coding_loop_cli",
                "--session-id", child_session_id, "--store", str(self._store),
                "--config-json", str(config_path)]
        child_process = self._spawner.spawn(session_id=child_session_id, args=args)

        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "child.spawned", {
            "session_id": child_session_id, "pid": child_process.pid, "pgid": child_process.pgid,
            "start_time": child_process.start_time, "allocated_budget": allocated_budget,
        })
        return child_session_id, child_process

    def _wait_for_terminal(self, session_id: str, poll_interval: float, deadline: float) -> dict:
        while time.monotonic() < deadline:
            doc = state.load(self._store, session_id)
            for event in doc["events"]:
                if event["event_type"] == "session.terminal":
                    return doc
            time.sleep(poll_interval)
        raise CoordinatorError("timeout", f"child session {session_id} never reached a terminal state")

    def run_m1(self, task_id: str, child_specs: list[dict], total_budget: int,
               poll_interval: float = 0.5, timeout: float = 120.0) -> dict:
        root_session = state.create(self._store, task_id=task_id)
        root_session_id = root_session["session_id"]

        child_processes: list[tuple[str, ChildProcess]] = []
        for spec in child_specs:
            session_id, process = self._spawn_child(root_session_id, spec["config"], spec["allocated_budget"])
            child_processes.append((session_id, process))

        deadline = time.monotonic() + timeout
        results = []
        for session_id, _process in child_processes:
            doc = self._wait_for_terminal(session_id, poll_interval, deadline)
            terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
            results.append({"session_id": session_id, "status": terminal["payload"]["status"],
                             "reason": terminal["payload"].get("reason")})

        root_doc = state.load(self._store, root_session_id)
        child_docs = {sid: state.load(self._store, sid) for sid, _ in child_processes}
        index = build_index(root_doc, child_docs, total_budget=total_budget)

        overall_status = "succeeded" if all(c["status"] == "succeeded" for c in results) else "blocked"
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": overall_status})

        return {"run_id": root_session_id, "status": overall_status, "children": results,
                "budget": {"total": index.total_budget, "allocated": index.allocated_budget}}

    def run_m2(self, task_id: str, child1_spec: dict, child2_spec: dict, total_budget: int,
               poll_interval: float = 0.5, timeout: float = 120.0) -> dict:
        root_session = state.create(self._store, task_id=task_id)
        root_session_id = root_session["session_id"]

        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "join.waiting", {"waiting_on": "child_1"})

        deadline = time.monotonic() + timeout
        child1_session_id, _ = self._spawn_child(root_session_id, child1_spec["config"],
                                                   child1_spec["allocated_budget"])
        child1_doc = self._wait_for_terminal(child1_session_id, poll_interval, deadline)
        child1_terminal = next(e for e in child1_doc["events"] if e["event_type"] == "session.terminal")
        child1_status = child1_terminal["payload"]["status"]

        results = [{"session_id": child1_session_id, "status": child1_status,
                    "reason": child1_terminal["payload"].get("reason")}]

        if child1_status != "succeeded":
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": f"child_1 terminated as {child1_status}; join cannot succeed"})
            return {"run_id": root_session_id, "status": "blocked", "children": results,
                    "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"]}}

        result_event = next(e for e in child1_doc["events"] if e["event_type"] == "result.available")
        file_contents = result_event["payload"]["file_contents"]

        spent = result_event["payload"].get("cost", {}).get("sandbox_executions_used", 0)
        surplus = reclaimable_surplus(child1_spec["allocated_budget"], spent)
        child2_budget = next_child_budget(child2_spec["allocated_budget"], surplus)
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "budget.reclaimed", {"amount": surplus})
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "budget.transferred", {"amount": surplus})

        handoff_dir = Path(tempfile.mkdtemp(prefix="fas4-m2-handoff-"))
        shutil.copytree(child2_spec["fixture_dir"], handoff_dir, dirs_exist_ok=True)
        try:
            apply_incoming_changes(
                work_root=handoff_dir / "workspace", file_contents=file_contents,
                caps=WriteCaps(max_files=len(file_contents) or 1, max_bytes_per_file=65536,
                                max_changed_lines=1000, max_executions=4),
            )
        except Exception as error:
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": f"patch handoff failed: {error}"})
            return {"run_id": root_session_id, "status": "blocked", "children": results,
                    "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"]}}

        child2_config = dict(child2_spec["config"], fixture_dir=str(handoff_dir))
        try:
            child2_session_id, _ = self._spawn_child(root_session_id, child2_config, child2_budget)
            child2_doc = self._wait_for_terminal(child2_session_id, poll_interval, deadline)
            child2_terminal = next(e for e in child2_doc["events"] if e["event_type"] == "session.terminal")
            child2_status = child2_terminal["payload"]["status"]
            results.append({"session_id": child2_session_id, "status": child2_status,
                             "reason": child2_terminal["payload"].get("reason")})
        finally:
            shutil.rmtree(handoff_dir, ignore_errors=True)

        if child2_status == "succeeded":
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "join.satisfied", {"child_session_id": child2_session_id})

        overall_status = "succeeded" if child2_status == "succeeded" else "blocked"
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": overall_status})

        return {"run_id": root_session_id, "status": overall_status, "children": results,
                "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"] + child2_budget}}
