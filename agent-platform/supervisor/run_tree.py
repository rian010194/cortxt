"""RunTreeIndex: a derived, rebuildable, structurally-unwritable projection of a
root session and its children's session logs (design spec decision 4). The
only constructor is build_index(); there is no mutation API, so "always
rebuildable from session-log events" is a structural guarantee, not a
convention to remember.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChildStatus:
    session_id: str
    pid: int | None
    pgid: int | None
    start_time: float | None
    allocated_budget: int
    status: str
    reason: str | None
    last_heartbeat_at: str | None


@dataclass(frozen=True)
class RunTreeIndex:
    root_session_id: str
    root_status: str
    children: tuple[ChildStatus, ...]
    total_budget: int
    allocated_budget: int
    join_satisfied: bool


def _child_status_from_events(session_doc: dict, allocated_budget: int,
                               pid: int | None, pgid: int | None,
                               start_time: float | None,
                               last_heartbeat_at: str | None) -> ChildStatus:
    session_id = session_doc["session_id"]
    status = "running"
    reason = None
    for event in session_doc["events"]:
        if event["event_type"] == "heartbeat.ping":
            last_heartbeat_at = event["timestamp"]
        elif event["event_type"] == "session.terminal":
            status = event["payload"]["status"]
            reason = event["payload"].get("reason")
        elif event["event_type"] == "session.reattached":
            status = "running"
    return ChildStatus(session_id=session_id, pid=pid, pgid=pgid, start_time=start_time,
                        allocated_budget=allocated_budget, status=status, reason=reason,
                        last_heartbeat_at=last_heartbeat_at)


def build_index(root_session_doc: dict, child_session_docs: dict[str, dict],
                 total_budget: int) -> RunTreeIndex:
    root_status = "running"
    allocated = 0
    spawned: dict[str, tuple[int, int | None, int | None, float | None]] = {}

    for event in root_session_doc["events"]:
        if event["event_type"] == "child.spawned":
            payload = event["payload"]
            spawned[event["payload"]["session_id"]] = (
                payload.get("allocated_budget", 0),
                payload.get("pid"),
                payload.get("pgid"),
                payload.get("start_time"),
            )
            allocated += payload.get("allocated_budget", 0)
        elif event["event_type"] == "budget.transferred":
            allocated += event["payload"].get("amount", 0)
        elif event["event_type"] == "session.terminal":
            root_status = event["payload"]["status"]

    children = tuple(
        _child_status_from_events(child_session_docs[sid], budget, pid, pgid, start_time, None)
        for sid, (budget, pid, pgid, start_time) in spawned.items()
        if sid in child_session_docs
    )

    join_satisfied = any(e["event_type"] == "join.satisfied" for e in root_session_doc["events"])

    return RunTreeIndex(
        root_session_id=root_session_doc["session_id"],
        root_status=root_status,
        children=children,
        total_budget=total_budget,
        allocated_budget=allocated,
        join_satisfied=join_satisfied,
    )
