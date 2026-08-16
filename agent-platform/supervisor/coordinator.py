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
from datetime import datetime, timezone
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

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0
DEFAULT_STALE_MULTIPLIER = 3


def _parse_event_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _is_heartbeat_stale(doc: dict, heartbeat_interval: float, stale_multiplier: int) -> bool:
    last_heartbeat_ts = None
    created_ts = None
    for event in doc["events"]:
        if event["event_type"] == "heartbeat.ping":
            last_heartbeat_ts = event["timestamp"]
        elif event["event_type"] == "session.created":
            created_ts = event["timestamp"]
    reference = last_heartbeat_ts or created_ts
    if reference is None:
        return False
    age = (datetime.now(timezone.utc) - _parse_event_timestamp(reference)).total_seconds()
    return age > heartbeat_interval * stale_multiplier


class Coordinator:
    def __init__(self, store: Path, spawner: ProcessSpawner | None = None) -> None:
        self._store = Path(store)
        self._spawner = spawner or ProcessSpawner()

    def _spawn_child(self, root_session_id: str, config: dict, allocated_budget: int) -> tuple[str, ChildProcess, Path | None]:
        """Spawn a child process and return (session_id, ChildProcess, config_path).
        
        On ProcessSpawnError, writes spawn_failed event and re-raises.
        The caller is responsible for cleaning up the config_path on spawn failure.
        """
        child_session = state.create(self._store, task_id=config["task_id"])
        child_session_id = child_session["session_id"]

        fd, config_path_str = tempfile.mkstemp(prefix="fas4-child-config-", suffix=".json")
        config_path = Path(config_path_str)
        # Note: fd is closed by os.fdopen, but config_path still exists
        # It will be cleaned up by caller on success (after child reads it)
        # or on spawn failure (immediately)

        try:
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
            return child_session_id, child_process, config_path
        except ProcessSpawnError as error:
            # Clean up the config file on spawn failure - child never started
            if config_path and config_path.is_file():
                config_path.unlink()
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "spawn_failed", {
                "error": str(error), "error_reason": error.reason if hasattr(error, "reason") else "unknown"
            })
            raise

    def _wait_for_terminal(self, session_id: str, child: ChildProcess, poll_interval: float,
                            deadline: float, heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
                            stale_multiplier: int = DEFAULT_STALE_MULTIPLIER) -> dict:
        while time.monotonic() < deadline:
            doc = state.load(self._store, session_id)
            for event in doc["events"]:
                if event["event_type"] == "session.terminal":
                    return doc
            if _is_heartbeat_stale(doc, heartbeat_interval, stale_multiplier):
                self._spawner.terminate_gracefully(child, timeout=5.0)
                seq = state.latest_sequence(state.load(self._store, session_id))
                return state.append(self._store, session_id, seq, "session.terminal",
                                     {"status": "blocked", "reason": "heartbeat timeout"})
            time.sleep(poll_interval)
        raise CoordinatorError("timeout", f"child session {session_id} never reached a terminal state")

    def run_m1(self, task_id: str, child_specs: list[dict], total_budget: int,
               poll_interval: float = 0.5, timeout: float = 120.0) -> dict:
        """Run mode 1: spawn children sequentially, wait for all to reach terminal state."""
        root_session = state.create(self._store, task_id=task_id)
        root_session_id = root_session["session_id"]

        child_processes: list[tuple[str, ChildProcess, Path | None]] = []
        config_paths: dict[str, Path] = {}  # session_id -> config_path for cleanup

        for spec in child_specs:
            try:
                session_id, process, config_path = self._spawn_child(root_session_id, spec["config"], spec["allocated_budget"])
                child_processes.append((session_id, process, config_path))
                config_paths[session_id] = config_path
            except ProcessSpawnError:
                # spawn_failed already written; treat as failed
                # Need a placeholder to track the failed spawn
                child_processes.append((None, None, None))

        deadline = time.monotonic() + timeout
        results = []
        for session_id, process, config_path in child_processes:
            if session_id is None:  # spawn failed
                results.append({"session_id": "unknown", "status": "failed", "reason": "spawn failed"})
                continue
            
            try:
                doc = self._wait_for_terminal(session_id, process, poll_interval, deadline)
            except CoordinatorError as error:
                if error.reason == "timeout":
                    # Write terminal event for ROOT session, then continue
                    seq = state.latest_sequence(state.load(self._store, root_session_id))
                    state.append(self._store, root_session_id, seq, "session.terminal",
                                 {"status": "blocked", "reason": "child session did not reach a terminal state within the timeout"})
                    results.append({"session_id": session_id, "status": "blocked", "reason": error.message})
                    # Clean up config file on timeout
                    if config_path and config_path.is_file():
                        config_path.unlink()
                    continue
                raise
            
            # Clean up config file after successful wait
            if config_path and config_path.is_file():
                config_path.unlink()
            
            terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
            results.append({"session_id": session_id, "status": terminal["payload"]["status"],
                             "reason": terminal["payload"].get("reason")})

        root_doc = state.load(self._store, root_session_id)
        child_docs = {sid: state.load(self._store, sid) for sid, _, _ in child_processes if sid is not None}
        index = build_index(root_doc, child_docs, total_budget=total_budget)

        overall_status = "succeeded" if all(c["status"] == "succeeded" for c in results) else "blocked"
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": overall_status})

        return {"run_id": root_session_id, "status": overall_status, "children": results,
                "budget": {"total": index.total_budget, "allocated": index.allocated_budget}}

    def run_m2(self, task_id: str, child1_spec: dict, child2_spec: dict, total_budget: int,
               poll_interval: float = 0.5, timeout: float = 120.0) -> dict:
        """Run mode 2: staging - child1 produces result, child2 applies handoff."""
        root_session = state.create(self._store, task_id=task_id)
        root_session_id = root_session["session_id"]

        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "join.waiting", {"waiting_on": "child_1"})

        deadline = time.monotonic() + timeout
        child1_config_path: Path | None = None
        
        try:
            child1_session_id, child1_process, child1_config_path = self._spawn_child(root_session_id, child1_spec["config"],
                                                           child1_spec["allocated_budget"])
            try:
                child1_doc = self._wait_for_terminal(child1_session_id, child1_process, poll_interval, deadline)
            except CoordinatorError as error:
                if error.reason == "timeout":
                    seq = state.latest_sequence(state.load(self._store, root_session_id))
                    state.append(self._store, root_session_id, seq, "session.terminal",
                                 {"status": "blocked", "reason": "child_1 did not reach a terminal state within the timeout"})
                    return {"run_id": root_session_id, "status": "blocked", "children": [{"session_id": child1_session_id, "status": "blocked", "reason": error.message}],
                            "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"]}}
                raise
        except ProcessSpawnError as error:
            # child.spawn_failed already written by _spawn_child
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": "child_1 spawn failed"})
            return {"run_id": root_session_id, "status": "blocked", "children": [{"session_id": "unknown", "status": "failed", "reason": "spawn failed"}],
                    "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"]}}
        
        # Clean up child1 config file
        if child1_config_path and child1_config_path.is_file():
            child1_config_path.unlink()

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
        handoff_dir_cleaned = False
        shutil.copytree(child2_spec["fixture_dir"], handoff_dir, dirs_exist_ok=True)
        
        # Try/finally around child2 spawning and waiting, NOT around handoff_dir creation
        handoff_failed = False
        try:
            try:
                apply_incoming_changes(
                    work_root=handoff_dir / "workspace", file_contents=file_contents,
                    caps=WriteCaps(max_files=len(file_contents) or 1, max_bytes_per_file=65536,
                                    max_changed_lines=1000, max_executions=4),
                )
            except Exception as error:
                # Clean up handoff_dir on apply_incoming_changes failure
                shutil.rmtree(handoff_dir, ignore_errors=True)
                handoff_dir_cleaned = True
                handoff_failed = True
                seq = state.latest_sequence(state.load(self._store, root_session_id))
                state.append(self._store, root_session_id, seq, "session.terminal",
                             {"status": "blocked", "reason": f"patch handoff failed: {error}"})
                return {"run_id": root_session_id, "status": "blocked", "children": results,
                        "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"]}}

            if handoff_failed:
                # Should not reach here, but just in case
                return {"run_id": root_session_id, "status": "blocked", "children": results,
                        "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"]}}

            child2_config = dict(child2_spec["config"], fixture_dir=str(handoff_dir))
            child2_config_path: Path | None = None
            
            try:
                child2_session_id, child2_process, child2_config_path = self._spawn_child(root_session_id, child2_config, child2_budget)
            except ProcessSpawnError as error:
                # child.spawn_failed already written by _spawn_child
                seq = state.latest_sequence(state.load(self._store, root_session_id))
                state.append(self._store, root_session_id, seq, "session.terminal",
                             {"status": "blocked", "reason": "child_2 spawn failed"})
                child2_status = "failed"
                results.append({"session_id": "unknown", "status": "failed", "reason": "spawn failed"})
            else:
                try:
                    child2_doc = self._wait_for_terminal(child2_session_id, child2_process, poll_interval, deadline)
                except CoordinatorError as error:
                    if error.reason == "timeout":
                        seq = state.latest_sequence(state.load(self._store, root_session_id))
                        state.append(self._store, root_session_id, seq, "session.terminal",
                                     {"status": "blocked", "reason": "child_2 did not reach a terminal state within the timeout"})
                        child2_status = "blocked"
                        results.append({"session_id": child2_session_id, "status": "blocked", "reason": error.message})
                    else:
                        raise
                
                # Clean up child2 config file
                if child2_config_path and child2_config_path.is_file():
                    child2_config_path.unlink()
                
                child2_terminal = next(e for e in child2_doc["events"] if e["event_type"] == "session.terminal")
                child2_status = child2_terminal["payload"]["status"]
                results.append({"session_id": child2_session_id, "status": child2_status,
                                 "reason": child2_terminal["payload"].get("reason")})
        finally:
            # Clean up handoff_dir in all cases
            if not handoff_dir_cleaned:
                shutil.rmtree(handoff_dir, ignore_errors=True)

        if child2_status == "succeeded":
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "join.satisfied", {"child_session_id": child2_session_id})

        overall_status = "succeeded" if child2_status == "succeeded" else "blocked"
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": overall_status})

        return {"run_id": root_session_id, "status": overall_status, "children": results,
                "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"] + child2_budget}}

    def cancel_root(self, root_session_id: str, poll_interval: float = 0.5, timeout: float = 30.0) -> dict:
        root_doc = state.load(self._store, root_session_id)
        cancelled: list[str] = []
        for event in root_doc["events"]:
            if event["event_type"] != "child.spawned":
                continue
            child_session_id = event["payload"]["session_id"]
            child_doc = state.load(self._store, child_session_id)
            already_terminal = any(e["event_type"] == "session.terminal" for e in child_doc["events"])
            if already_terminal:
                continue
            child = ChildProcess(pid=event["payload"]["pid"], pgid=event["payload"]["pgid"],
                                  session_id=child_session_id, start_time=event["payload"]["start_time"])
            self._spawner.terminate_gracefully(child, timeout=timeout)
            seq = state.latest_sequence(state.load(self._store, child_session_id))
            state.append(self._store, child_session_id, seq, "session.terminal", {"status": "cancelled"})
            cancelled.append(child_session_id)

        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": "cancelled"})
        return {"cancelled": cancelled}

    def recover(self) -> list[dict]:
        summaries: list[dict] = []
        if not self._store.is_dir():
            return summaries

        for session_dir in self._store.iterdir():
            if not session_dir.is_dir():
                continue
            session_id = session_dir.name
            try:
                doc = state.load(self._store, session_id)
            except state.SessionError:  # root session file missing/corrupt
                continue

            is_root = any(e["event_type"] == "child.spawned" for e in doc["events"])
            if not is_root:
                continue
            already_terminal = any(e["event_type"] == "session.terminal" for e in doc["events"])
            if already_terminal:
                continue

            any_lost = False
            for event in doc["events"]:
                if event["event_type"] != "child.spawned":
                    continue
                child_session_id = event["payload"].get("session_id")
                if not child_session_id:
                    any_lost = True
                    seq = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq, "session.terminal",
                                 {"status": "blocked", "reason": "child session record is malformed"})
                    continue
                
                # Try to load child session - handle corrupt/missing records
                try:
                    child_doc = state.load(self._store, child_session_id)
                except state.SessionError as error:
                    # child session record corrupt/missing - mark as lost
                    any_lost = True
                    seq = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq, "session.terminal",
                                 {"status": "blocked", "reason": f"child session record is corrupt or missing: {error}"})
                    continue
                
                # Check for terminal event - handle malformed payload
                try:
                    terminal_events = any(e.get("event_type") == "session.terminal" for e in child_doc.get("events", []))
                except (KeyError, TypeError, AttributeError) as error:
                    any_lost = True
                    seq = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq, "session.terminal",
                                 {"status": "blocked", "reason": f"child session event payload is malformed: {error}"})
                    continue
                
                if terminal_events:
                    continue

                # Check liveness - handle malformed payload
                try:
                    child = ChildProcess(
                        pid=event["payload"]["pid"], 
                        pgid=event["payload"]["pgid"],
                        session_id=child_session_id, 
                        start_time=event["payload"]["start_time"]
                    )
                    if self._spawner.is_alive(child):
                        seq = state.latest_sequence(state.load(self._store, child_session_id))
                        state.append(self._store, child_session_id, seq, "session.reattached", {})
                    else:
                        any_lost = True
                        seq = state.latest_sequence(state.load(self._store, child_session_id))
                        state.append(self._store, child_session_id, seq, "session.terminal",
                                     {"status": "lost", "reason": "child lost during supervisor outage"})
                except (KeyError, TypeError, ValueError, AttributeError) as error:
                    any_lost = True
                    seq = state.latest_sequence(state.load(self._store, child_session_id))
                    state.append(self._store, child_session_id, seq, "session.terminal",
                                 {"status": "lost", "reason": f"child session event payload is malformed: {error}"})

            if any_lost:
                seq = state.latest_sequence(state.load(self._store, session_id))
                state.append(self._store, session_id, seq, "session.terminal",
                             {"status": "blocked", "reason": "child lost during supervisor outage"})

            summaries.append({"root_session_id": session_id, "any_lost": any_lost})
        return summaries
