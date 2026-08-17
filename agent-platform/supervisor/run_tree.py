"""RunTreeIndex: a derived, rebuildable, structurally-unwritable projection of
an RLM node's session log and (recursively) its children's (design spec
decision 3, extending Fas 4 decision 4 to arbitrary depth). The only
constructor is build_index(); there is no mutation API.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from reasoning.recursive.bounds import RLMConfig


@dataclass(frozen=True)
class NodeDocs:
    """Recursive collection of session docs for one RLM node and its children.

    Built by the caller (Coordinator, Task 6) from session_state.load() calls
    walking child.spawned events depth-first — this type only carries the
    already-loaded docs, it does no I/O itself (keeps build_index pure).
    """
    session_doc: dict
    children: dict[str, "NodeDocs"] = field(default_factory=dict)


@dataclass(frozen=True)
class RunTreeIndex:
    session_id: str
    depth: int
    root_status: str
    pid: int | None
    pgid: int | None
    start_time: float | None
    allocated_budget: int
    last_heartbeat_at: str | None
    join_satisfied: bool
    total_budget: RLMConfig
    children: tuple["RunTreeIndex", ...] = field(default_factory=tuple)


def _status_from_events(session_doc: dict) -> tuple[str, str | None]:
    status = "running"
    reason = None
    for event in session_doc["events"]:
        if event["event_type"] == "session.terminal":
            status = event["payload"]["status"]
            reason = event["payload"].get("reason")
        elif event["event_type"] == "session.reattached":
            status = "running"
    return status, reason


def _last_heartbeat(session_doc: dict) -> str | None:
    last = None
    for event in session_doc["events"]:
        if event["event_type"] == "heartbeat.ping":
            last = event["timestamp"]
    return last


def _build_node(node: NodeDocs, depth: int, total_budget: RLMConfig,
                 pid: int | None, pgid: int | None, start_time: float | None,
                 allocated_budget: int) -> RunTreeIndex:
    status, _reason = _status_from_events(node.session_doc)

    spawned: dict[str, tuple[int, int | None, int | None, float | None]] = {}
    for event in node.session_doc["events"]:
        if event["event_type"] == "child.spawned":
            payload = event["payload"]
            spawned[payload["session_id"]] = (
                payload.get("allocated_budget", 0),
                payload.get("pid"), payload.get("pgid"), payload.get("start_time"),
            )

    children = tuple(
        _build_node(node.children[sid], depth + 1, total_budget, pid_, pgid_, st_, budget_)
        for sid, (budget_, pid_, pgid_, st_) in spawned.items()
        if sid in node.children
    )

    join_satisfied = any(e["event_type"] == "join.satisfied" for e in node.session_doc["events"])

    return RunTreeIndex(
        session_id=node.session_doc["session_id"],
        depth=depth,
        root_status=status,
        pid=pid, pgid=pgid, start_time=start_time,
        allocated_budget=allocated_budget,
        last_heartbeat_at=_last_heartbeat(node.session_doc),
        join_satisfied=join_satisfied,
        total_budget=total_budget,
        children=children,
    )


def build_index(root: NodeDocs, total_budget: RLMConfig) -> RunTreeIndex:
    return _build_node(root, depth=0, total_budget=total_budget,
                        pid=None, pgid=None, start_time=None, allocated_budget=0)
