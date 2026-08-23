from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from cli.unified_cli import _run_widget
from widget_contract.adapters.store_reads import ReadAdapterError, read_session_agents_v1
from widget_contract.loader import load_widget_file
from widget_contract.registry import PRIMITIVES, READ_OPERATIONS, TYPES
from widget_contract.renderer import render
from widget_contract.swimlane_text import render_swimlane_text
from widget_contract.validation import ValidationError, validate

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "session-agents-0.1.yaml"


def fake_agents_data():
    return {
        "schema_version": 1,
        "agents": [
            {
                "id": "agent-hermes",
                "name": "Hermes",
                "runtime": "hermes",
                "status": "running",
                "current_task": "Execute session plan",
                "tasks": [
                    {"id": "t1", "title": "Load context", "state": "done", "progress": 100},
                    {"id": "t2", "title": "Execute session plan", "state": "running", "progress": 65},
                    {"id": "t3", "title": "Verification", "state": "queued", "progress": 0},
                ],
            },
            {
                "id": "agent-pi",
                "name": "Pi",
                "runtime": "pi",
                "status": "running",
                "current_task": "Analyze codebase invariants",
                "tasks": [
                    {"id": "t4", "title": "Inspect AST", "state": "done", "progress": 100},
                    {"id": "t5", "title": "Analyze codebase invariants", "state": "running", "progress": 40},
                ],
            },
            {
                "id": "agent-codex",
                "name": "Codex",
                "runtime": "codex",
                "status": "done",
                "current_task": None,
                "tasks": [
                    {"id": "t6", "title": "Contract validation", "state": "done", "progress": 100},
                ],
            },
        ],
    }


def test_swimlane_primitive_is_registered_with_closed_props():
    assert "swimlane" in PRIMITIVES
    entry = PRIMITIVES["swimlane"]
    assert entry.props == frozenset({"label", "columns", "empty", "error"})
    assert entry.bindings == {"rows": "core.array.v1"}
    assert entry.empty_state == "empty"
    assert entry.error_state == "error"


def test_session_agents_spec_loads_and_declares_exact_reads_and_capabilities():
    widget = load_widget_file(SPEC)
    assert widget.id == "session-agents"
    assert widget.version == "0.1"
    assert widget.actions == ()
    assert len(widget.reads) == 1
    (read_op,) = widget.reads
    assert (read_op.id, read_op.source, read_op.operation, read_op.output_type) == (
        "agents", "store", "session-agents.v1", "session-agents.v1")
    assert read_op.on_error == "stale"
    assert read_op.refresh["mode"] == "manual"
    assert set(widget.capabilities) == {"read:session-agents"}
    assert READ_OPERATIONS["session-agents.v1"].capability == "read:session-agents"
    assert TYPES["session-agents.v1"].data_class == "operational"


def test_session_agents_render_tree_shape():
    widget = load_widget_file(SPEC)
    data = fake_agents_data()
    tree = render(widget, {"agents": data}, {"agents": "fresh"})
    assert tree["render"]["primitive"] == "stack"
    children = tree["render"]["children"]
    assert len(children) == 3
    assert children[0]["primitive"] == "heading"
    assert children[1]["primitive"] == "text"
    assert children[2]["primitive"] == "swimlane"
    assert children[2]["props"]["label"] == "Agents"
    assert children[2]["props"]["columns"] == ["Agent", "Tasks"]
    assert len(children[2]["props"]["rows"]) == 3
    assert children[2]["props"]["rows"][0]["name"] == "Hermes"


def test_read_session_agents_v1_adapter_safe_projection_and_rejection():
    source = fake_agents_data()
    source["agents"][0]["command"] = "do dangerous thing"
    source["agents"][0]["tasks"][0]["secret_payload"] = "secret"

    safe = read_session_agents_v1(source)
    assert "command" not in safe["agents"][0]
    assert "secret_payload" not in safe["agents"][0]["tasks"][0]

    callable_safe = read_session_agents_v1(lambda: source)
    assert callable_safe["agents"][0]["id"] == "agent-hermes"

    with pytest.raises(ReadAdapterError):
        read_session_agents_v1({"agents": "invalid"})

    with pytest.raises(ReadAdapterError):
        read_session_agents_v1({"agents": [{"id": "a1", "tasks": []}]})

    with pytest.raises(ReadAdapterError):
        read_session_agents_v1({"agents": [{"id": "a1", "name": "A", "runtime": "r", "status": "unknown", "current_task": None, "tasks": []}]})


def test_cli_session_agents_view_artifact_path(tmp_path):
    target = tmp_path / "session-agents.json"
    result = _run_widget(
        Namespace(widget_command=None, view="session-agents", repo=None, snapshot=target),
        agents_reader=fake_agents_data,
    )
    assert result.status == "succeeded"
    assert target.is_file()
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "session-agents", "version": "0.1"}
    assert artifact["render"]["state"] == "ready"
    swimlane_node = next(c for c in artifact["render"]["children"] if c["primitive"] == "swimlane")
    assert len(swimlane_node["props"]["rows"]) == 3


def test_cli_session_agents_view_failing_reader_produces_error_state(tmp_path):
    def broken():
        raise OSError("failed to load sessions")

    target = tmp_path / "session-agents-err.json"
    result = _run_widget(
        Namespace(widget_command=None, view="session-agents", repo=None, snapshot=target),
        agents_reader=broken,
    )
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["error"]["kind"] == "session_agents_read"
    assert artifact["render"]["primitive"] == "error-state"
    assert artifact["render"]["state"] == "error"


def test_render_swimlane_text_fallback():
    node = {
        "primitive": "swimlane",
        "props": {
            "label": "Agents",
            "columns": ["Agent", "Tasks"],
            "rows": [
                {"name": "Hermes", "tasks": [{"title": "spec", "state": "done"}, {"title": "build", "state": "running"}]},
                {"name": "Codex", "tasks": [{"title": "test", "state": "queued"}]},
            ],
        },
    }
    rendered = render_swimlane_text(node)
    assert "Agents" in rendered
    assert "Agent | Tasks" in rendered
    assert "Hermes |" in rendered
    assert "build \u25cf" in rendered
    assert "Codex | test" in rendered
