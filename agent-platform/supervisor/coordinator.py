"""Coordinator: root-session lifecycle, spawning, joins, integration
(design spec §7.2 state machine, decision 5's M1/M2 staging).
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from context_store.slicer import slice_for_children, SliceBudgetExhausted
from context_store.store import ContextReference
from reasoning.recursive.bounds import RLMConfig
from runtime import session_state as state
from runtime.execution.write_policy import WriteCaps
from runtime.rlm_child_cli import decide_child_refs
from runtime.tools.gate import ToolAdmissionError
from supervisor.budget import next_child_budget, reclaimable_surplus, split_rlm_config
from supervisor.process_spawner import (ChildProcess, ProcessSpawnError,
                                        ProcessSpawner)
from supervisor.run_tree import NodeDocs, RunTreeIndex, build_index
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


# module-level, deterministic decompose_fn used by decide_child_refs (Task 5)
# and duplicated (intentionally, see conftest.py's _fake_decompose docstring)
# by the test fakes — structural only, matches decomposer.py's fail-closed
# truncation discipline
def _decompose_context(ref: ContextReference, config: RLMConfig) -> list[ContextReference]:
    n = min(config.max_branches_per_node, config.max_total_children)
    if n <= 0:
        return []
    try:
        return slice_for_children(ref, n)
    except (SliceBudgetExhausted, ValueError):
        return []


def _index_to_result(index: RunTreeIndex, node: NodeDocs | None = None) -> dict:
    """Flatten a RunTreeIndex subtree into the plain nested dict shape
    run_node returns. Recurses — a grandchild that itself decomposed further
    is reflected here too, not discarded.

    If ``node`` is provided, metrics from the session log's ``result.available``
    event (model_invocations, context_reads, cost, output_size) are included so
    that parent-level post-hoc bounds aggregation (Task 9) can sum them.
    """
    extras: dict[str, int | float] = {}
    if node is not None:
        for event in node.session_doc.get("events", []):
            if event["event_type"] == "result.available":
                p = event["payload"]
                extras = {
                    "model_invocations": p.get("model_invocations", 0),
                    "context_reads": p.get("context_reads", 0),
                    "cost": p.get("cost", 0.0),
                    "output_size": p.get("output_size", 0),
                }
                break
    children: list[dict] = []
    if node is not None:
        children = [_index_to_result(c, node.children.get(c.session_id)) for c in index.children]
    else:
        children = [_index_to_result(c) for c in index.children]
    return {"session_id": index.session_id, "status": index.root_status,
            "children": children, **extras}


def _max_nested_depth(node: dict, current_depth: int) -> int:
    if not node["children"]:
        return current_depth
    return max(_max_nested_depth(c, current_depth + 1) for c in node["children"])


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

        overall_status = "succeeded" if all(c["status"] == "succeeded" for c in results) else "blocked"
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": overall_status})

        allocated = sum(spec["allocated_budget"] for spec in child_specs)
        return {"run_id": root_session_id, "status": overall_status, "children": results,
                "budget": {"total": total_budget, "allocated": allocated}}

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

        all_docs: dict[str, dict] = {}
        for session_dir in self._store.iterdir():
            if not session_dir.is_dir():
                continue
            try:
                all_docs[session_dir.name] = state.load(self._store, session_dir.name)
            except state.SessionError:
                continue

        # Build parent -> [children] edges from child.spawned events; process
        # children before parents (reverse topological / depth-first
        # post-order) so a parent's any_lost check sees its child's just-updated
        # status.
        children_of: dict[str, list[str]] = {}
        for sid, doc in all_docs.items():
            for event in doc["events"]:
                if event["event_type"] == "child.spawned":
                    child_sid = event["payload"].get("session_id")
                    if child_sid:
                        children_of.setdefault(sid, []).append(child_sid)

        visited: set[str] = set()
        order: list[str] = []

        def _visit(sid: str) -> None:
            if sid in visited or sid not in all_docs:
                return
            visited.add(sid)
            for child_sid in children_of.get(sid, []):
                _visit(child_sid)
            order.append(sid)  # post-order: children land in `order` before this sid

        for sid in list(all_docs):
            _visit(sid)

        for session_id in order:
            doc = all_docs[session_id]
            is_root_like = session_id in children_of  # has at least one child.spawned event
            if not is_root_like:
                continue
            already_terminal = any(e["event_type"] == "session.terminal" for e in doc["events"])
            if already_terminal:
                continue

            # re-read fresh: a child processed earlier in `order` may have just
            # been marked terminal/lost, and this session's own doc must
            # reflect that before its any_lost check runs
            doc = state.load(self._store, session_id)
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
                try:
                    child_doc = state.load(self._store, child_session_id)
                except state.SessionError as error:
                    any_lost = True
                    seq = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq, "session.terminal",
                                 {"status": "blocked", "reason": f"child session record is corrupt or missing: {error}"})
                    continue

                terminal_event = next((e for e in child_doc["events"] if e.get("event_type") == "session.terminal"), None)
                if terminal_event is not None:
                    if terminal_event["payload"]["status"] in ("lost", "blocked", "failed"):
                        any_lost = True
                    continue

                try:
                    child = ChildProcess(pid=event["payload"]["pid"], pgid=event["payload"]["pgid"],
                                          session_id=child_session_id, start_time=event["payload"]["start_time"])
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

    def _load_node_docs_tree(self, session_id: str) -> NodeDocs:
        """Recursively walk child.spawned events, reading each descendant's
        own session log, so the caller can build a real RunTreeIndex over
        however deep this subtree actually went — not just this node's own
        direct terminal event."""
        doc = state.load(self._store, session_id)
        children: dict[str, NodeDocs] = {}
        for event in doc["events"]:
            if event["event_type"] == "child.spawned":
                child_sid = event["payload"]["session_id"]
                try:
                    children[child_sid] = self._load_node_docs_tree(child_sid)
                except state.SessionError:
                    continue  # missing/corrupt — Task 7's recovery handles
                    # this case; here it is simply excluded from the tree
        return NodeDocs(session_doc=doc, children=children)

    def run_node(self, task_id: str, context_ref: ContextReference, config: RLMConfig,
                 depth: int = 0,
                 allowed_data_classes: frozenset[str] = frozenset({"L0", "internal"}),
                 poll_interval: float = 0.5, timeout: float | None = None) -> dict:
        if timeout is None:
            timeout = config.max_runtime_seconds
        session = state.create(self._store, task_id=task_id)
        session_id = session["session_id"]

        # in-process decision: leaf vs decompose — Coordinator never calls a
        # model itself (Fas 3 §32.1); decide_child_refs needs no inference
        # port at all, unlike the original draft's run_node_body+_NullInference
        try:
            child_refs = decide_child_refs(
                context_ref, config, depth, _decompose_context,
                data_class_check=lambda dc: dc in allowed_data_classes)
        except ToolAdmissionError as error:
            # fail-closed: an out-of-scope data class is denied before ANY
            # process is created — surface it as a controlled blocked result,
            # not an unhandled crash (Kimi review, Stage A checkpoint).
            seq = state.latest_sequence(state.load(self._store, session_id))
            state.append(self._store, session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": f"admission denied: {error}"})
            return {"run_id": session_id, "status": "blocked", "children": [],
                    "depth_reached": depth,
                    "termination_reason": "admission_denied",
                    "branches_explored": 0, "model_invocations": 0,
                    "contradictions_found": 0}

        if not child_refs:
            child_session_id, child_process, config_path, ref_path = self._spawn_rlm_node(
                session_id, task_id, context_ref, config, depth, allowed_data_classes)
            deadline = time.monotonic() + timeout
            doc = self._wait_for_terminal(child_session_id, child_process, poll_interval, deadline)
            for p in (config_path, ref_path):
                if p and p.is_file():
                    p.unlink()
            terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
            status = terminal["payload"]["status"]
            seq = state.latest_sequence(state.load(self._store, session_id))
            state.append(self._store, session_id, seq, "session.terminal", {"status": status})
            return {"run_id": session_id, "status": status, "children": [],
                    "depth_reached": depth, "termination_reason": terminal["payload"].get("reason"),
                    "branches_explored": 0, "model_invocations": 1, "contradictions_found": 0}

        child_configs = split_rlm_config(config, len(child_refs))
        results = []
        for ref in child_refs:
            seq = state.latest_sequence(state.load(self._store, session_id))
            state.append(self._store, session_id, seq, "context.sliced", {
                "locator": ref.locator, "range": list(ref.range), "data_class": ref.data_class})
        for ref, cfg in zip(child_refs, child_configs):
            child_session_id, child_process, config_path, ref_path = self._spawn_rlm_node(
                session_id, task_id, ref, cfg, depth + 1, allowed_data_classes)
            deadline = time.monotonic() + timeout
            doc = self._wait_for_terminal(child_session_id, child_process, poll_interval, deadline)
            for p in (config_path, ref_path):
                if p and p.is_file():
                    p.unlink()
            # the child may have decomposed further inside its own process —
            # project its full subtree (Task 4's NodeDocs/build_index), not
            # just its own direct terminal event, so results reflect the
            # real depth-2 structure instead of a flattened "children": []
            child_tree = self._load_node_docs_tree(child_session_id)
            child_index = build_index(child_tree, total_budget=cfg)
            results.append(_index_to_result(child_index, child_tree))

        # Remaining five §11.2 bounds are enforced post-hoc (same philosophy as
        # the cost cap): max_model_invocations/max_context_reads/max_cost/
        # max_output_size are aggregated from the projected subtree and checked
        # against this node's own (disjointly allocated) budget share.
        total_model_invocations = sum(r.get("model_invocations", 0) for r in results)
        total_context_reads = sum(r.get("context_reads", 0) for r in results)
        total_cost = sum(r.get("cost", 0.0) for r in results)
        total_output_size = sum(r.get("output_size", 0) for r in results)
        bounds_exceeded = (
            total_model_invocations > config.max_model_invocations
            or total_context_reads > config.max_context_reads
            or total_cost > config.max_cost
            or total_output_size > config.max_output_size
        )
        all_children_ok = all(r["status"] == "succeeded" for r in results)
        if all_children_ok and not bounds_exceeded:
            overall_status = "succeeded"
            termination_reason = None
        elif all_children_ok and bounds_exceeded:
            overall_status = "blocked"
            termination_reason = "budget_exhausted"
        else:
            overall_status = "blocked"
            termination_reason = None
        seq = state.latest_sequence(state.load(self._store, session_id))
        state.append(self._store, session_id, seq, "session.terminal", {"status": overall_status})

        depth_reached = max((_max_nested_depth(r, depth + 1) for r in results), default=depth + 1)
        return {"run_id": session_id, "status": overall_status, "children": results,
                "depth_reached": depth_reached, "termination_reason": termination_reason,
                "branches_explored": len(results),
                "model_invocations": total_model_invocations,
                "contradictions_found": sum(r.get("contradictions_found", 0) for r in results)}

    def _spawn_rlm_node(self, parent_session_id, task_id, context_ref, config, depth,
                        allowed_data_classes: frozenset[str]):
        """Shared spawn plumbing for both leaf and recursive RLM children —
        the child process's own main() (rlm_child_cli.py) decides, on its
        side, whether it is itself a leaf or a further decomposer. This
        mirrors _spawn_child (Fas 4) but targets rlm_child_cli instead of
        coding_loop_cli, and passes a context-ref file alongside the config.
        """
        child_session = state.create(self._store, task_id=task_id)
        child_session_id = child_session["session_id"]

        fd, config_path_str = tempfile.mkstemp(prefix="fas5-rlm-config-", suffix=".json")
        config_path = Path(config_path_str)
        fd2, ref_path_str = tempfile.mkstemp(prefix="fas5-rlm-ctxref-", suffix=".json")
        ref_path = Path(ref_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                # {"rlm": ...} wraps the RLMConfig fields so rlm_child_cli.py's
                # main() can read model/provider_evidence/data_class as sibling
                # keys in the same file, instead of a bare RLMConfig dict that
                # left no room for inference wiring.
                # allowed_data_classes is also written as a sibling key so the
                # child inherits its parent's policy instead of re-hardcoding
                # the default set.
                handle.write(json.dumps({
                    "rlm": dataclasses.asdict(config),
                    "allowed_data_classes": sorted(allowed_data_classes),
                }))
            with os.fdopen(fd2, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(dataclasses.asdict(context_ref)))

            args = [sys.executable, "-m", "runtime.rlm_child_cli",
                    "--session-id", child_session_id, "--store", str(self._store),
                    "--config-json", str(config_path), "--context-ref-json", str(ref_path),
                    "--depth", str(depth)]
            child_process = self._spawner.spawn(session_id=child_session_id, args=args)

            seq = state.latest_sequence(state.load(self._store, parent_session_id))
            state.append(self._store, parent_session_id, seq, "child.spawned", {
                "session_id": child_session_id, "pid": child_process.pid, "pgid": child_process.pgid,
                "start_time": child_process.start_time,
                "allocated_budget": config.max_total_children,
            })
            return child_session_id, child_process, config_path, ref_path
        except ProcessSpawnError as error:
            for p in (config_path, ref_path):
                if p.is_file():
                    p.unlink()
            seq = state.latest_sequence(state.load(self._store, parent_session_id))
            state.append(self._store, parent_session_id, seq, "spawn_failed", {
                "error": str(error), "error_reason": getattr(error, "reason", "unknown"),
            })
            raise
