# agent-platform/tests/supervisor/test_run_tree.py
from __future__ import annotations

from supervisor.run_tree import build_index, NodeDocs
from reasoning.recursive.bounds import RLMConfig


def _doc(session_id, events):
    return {"session_id": session_id, "events": events}


def test_build_index_projects_depth_2_tree():
    grandchild_doc = _doc("gc-1", [
        {"event_type": "session.terminal", "timestamp": "2026-01-01T00:00:02Z",
         "payload": {"status": "succeeded"}},
    ])
    child_doc = _doc("c-1", [
        {"event_type": "child.spawned", "timestamp": "2026-01-01T00:00:01Z",
         "payload": {"session_id": "gc-1", "pid": 111, "pgid": 111,
                     "start_time": 1.0, "allocated_budget": 1}},
        {"event_type": "session.terminal", "timestamp": "2026-01-01T00:00:03Z",
         "payload": {"status": "succeeded"}},
    ])
    root_doc = _doc("root-1", [
        {"event_type": "child.spawned", "timestamp": "2026-01-01T00:00:00Z",
         "payload": {"session_id": "c-1", "pid": 100, "pgid": 100,
                     "start_time": 0.5, "allocated_budget": 3}},
        {"event_type": "session.terminal", "timestamp": "2026-01-01T00:00:04Z",
         "payload": {"status": "succeeded"}},
    ])
    tree = NodeDocs(session_doc=root_doc, children={
        "c-1": NodeDocs(session_doc=child_doc, children={
            "gc-1": NodeDocs(session_doc=grandchild_doc, children={}),
        }),
    })
    index = build_index(tree, RLMConfig(max_total_children=6))
    assert index.depth == 0
    assert index.root_status == "succeeded"
    assert len(index.children) == 1
    assert index.children[0].depth == 1
    assert index.children[0].root_status == "succeeded"
    assert len(index.children[0].children) == 1
    assert index.children[0].children[0].depth == 2
    assert index.children[0].children[0].root_status == "succeeded"


def test_build_index_still_handles_flat_depth_1_fas4_shape():
    child_a = _doc("a", [{"event_type": "session.terminal",
                           "timestamp": "2026-01-01T00:00:01Z",
                           "payload": {"status": "succeeded"}}])
    child_b = _doc("b", [{"event_type": "session.terminal",
                           "timestamp": "2026-01-01T00:00:01Z",
                           "payload": {"status": "succeeded"}}])
    root_doc = _doc("root", [
        {"event_type": "child.spawned", "timestamp": "2026-01-01T00:00:00Z",
         "payload": {"session_id": "a", "pid": 1, "pgid": 1, "start_time": 0.0,
                     "allocated_budget": 3}},
        {"event_type": "child.spawned", "timestamp": "2026-01-01T00:00:00Z",
         "payload": {"session_id": "b", "pid": 2, "pgid": 2, "start_time": 0.0,
                     "allocated_budget": 3}},
        {"event_type": "session.terminal", "timestamp": "2026-01-01T00:00:02Z",
         "payload": {"status": "succeeded"}},
    ])
    tree = NodeDocs(session_doc=root_doc, children={
        "a": NodeDocs(session_doc=child_a, children={}),
        "b": NodeDocs(session_doc=child_b, children={}),
    })
    index = build_index(tree, RLMConfig(max_total_children=6))
    assert index.depth == 0
    assert len(index.children) == 2
    assert all(c.depth == 1 for c in index.children)


def test_no_mutation_api_exists():
    import dataclasses
    import supervisor.run_tree as run_tree_module

    assert not hasattr(run_tree_module, "update_index")
    assert not hasattr(build_index, "update")
    tree = NodeDocs(session_doc=_doc("root", []), children={})
    index = build_index(tree, RLMConfig())
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        index.root_status = "tampered"
