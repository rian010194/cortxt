"""Full agent loop: claim -> admit tool -> read fixture -> kernel (model-assisted)
-> verify -> result envelope. TextInferencePort is faked (0 cost, deterministic).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.inference.budget_gate import BudgetExhausted
from runtime.agent_loop import AgentLoop
from runtime.session_state import load
from runtime.tools import ToolGate

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["classification"],
    "properties": {"classification": {"type": "string", "enum": ["high_risk", "minimal_risk"]}},
}


class FakePort:
    """Stands in for TextInferencePort — same .invoke(prompt, schema) -> dict shape."""

    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.calls = []

    def invoke(self, prompt, output_schema):
        self.calls.append((prompt, output_schema))
        if self._raise:
            raise self._raise
        return self._response


def _fixture(tmp_path, data):
    d = tmp_path / "fixtures"
    d.mkdir()
    path = d / "case.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return d, path


def test_run_succeeds_end_to_end(tmp_path):
    fdir, fpath = _fixture(tmp_path, {"case_id": "SYNTH-1"})
    gate = ToolGate(allowed_roots=[fdir])
    port = FakePort(response={"classification": "high_risk"})
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt="classify this system")
    envelope = loop.run(task_id="synth-classify-001", fixture_path=str(fpath))

    assert envelope["status"] == "succeeded"
    assert envelope["result"] == {"classification": "high_risk"}
    assert port.calls[0][1] == OUTPUT_SCHEMA

    session = load(tmp_path / "sessions", envelope["session_id"])
    event_types = [e["event_type"] for e in session["events"]]
    assert event_types == [
        "session.created", "tool.admitted", "tool.completed",
        "inference.requested", "inference.completed", "session.terminal",
    ]


def test_run_blocks_when_schema_validation_fails(tmp_path):
    fdir, fpath = _fixture(tmp_path, {"case_id": "SYNTH-1"})
    gate = ToolGate(allowed_roots=[fdir])
    port = FakePort(response={"classification": "not-a-valid-enum-value"})
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt="classify this system")
    envelope = loop.run(task_id="t1", fixture_path=str(fpath))

    assert envelope["status"] == "blocked"
    assert envelope["result"] is None
    assert "schema" in envelope["reason"].lower()


def test_run_blocks_on_budget_exhausted_without_leaving_partial_success(tmp_path):
    fdir, fpath = _fixture(tmp_path, {"case_id": "SYNTH-1"})
    gate = ToolGate(allowed_roots=[fdir])
    port = FakePort(raise_exc=BudgetExhausted("no budget"))
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt="classify this system")
    envelope = loop.run(task_id="t1", fixture_path=str(fpath))

    assert envelope["status"] == "blocked"
    assert "budget" in envelope["reason"].lower()
    session = load(tmp_path / "sessions", envelope["session_id"])
    assert session["events"][-1]["event_type"] == "session.terminal"
    assert session["events"][-1]["payload"]["status"] == "blocked"


def test_run_blocks_when_fixture_path_outside_allowed_root(tmp_path):
    fdir, fpath = _fixture(tmp_path, {"case_id": "SYNTH-1"})
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"case_id": "SYNTH-2"}), encoding="utf-8")
    gate = ToolGate(allowed_roots=[fdir])  # fpath's sibling dir only, not tmp_path itself
    port = FakePort(response={"classification": "high_risk"})
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt="classify this system")
    envelope = loop.run(task_id="t1", fixture_path=str(outside))

    assert envelope["status"] == "blocked"
    assert port.calls == []  # no model call for a denied tool admission
