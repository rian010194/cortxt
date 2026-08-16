from __future__ import annotations

import json
from pathlib import Path

import pytest
from runtime import session_state as state
from runtime.coding.coding_profile import CODING_PROFILE
from runtime.coding_loop_cli import run_child
from runtime.execution.subprocess_sandbox import ExecutionSandbox

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-02-code-fixture"
FIXTURE_DIR = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
PATCH_SCHEMA = json.loads((VERTICAL / "schemas" / "patch-proposal.schema.json").read_text(encoding="utf-8"))
SYSTEM_PROMPT = (VERTICAL / "instructions" / "system-prompt-fix.md").read_text(encoding="utf-8")

_FIXED_RANGES_PY = (
    '"\"\"\"Small numeric helpers.\"\"\"\n\n\n'
    'def sum_to(n):\n'
    '    "\"\"\"Return the sum of all integers from 1 to n, inclusive.\"\"\"\n'
    '    total = 0\n'
    '    for i in range(1, n + 1):\n'
    '        total += i\n'
    '    return total\n'
)


class _ScriptedPort:
    """Stub with CodingLoop's expected .invoke(prompt, schema) -> dict shape,
    returning the known-correct fix. Proves coding_loop_cli's wiring without a
    live model call."""

    def invoke(self, prompt: str, schema: dict) -> dict:
        return {"changes": [{"path": "ranges.py", "new_content": _FIXED_RANGES_PY}],
                "rationale": "range() excluded n; widen to n + 1"}


@pytest.mark.docker_required
def test_run_child_emits_heartbeats_and_a_result_available_event(tmp_path, sandbox_image):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="fas4-cli-wiring")
    session_id = session["session_id"]
    sandbox = ExecutionSandbox(image=sandbox_image, max_executions=4)

    envelope = run_child(
        store=store, session_id=session_id, task_id="fas4-cli-wiring",
        fixture_dir=FIXTURE_DIR, port=_ScriptedPort(), patch_schema=PATCH_SCHEMA,
        system_prompt=SYSTEM_PROMPT, sandbox_factory=lambda caps: sandbox,
        profile=CODING_PROFILE, heartbeat_interval=0.05,
    )

    assert envelope["status"] == "succeeded", envelope.get("reason")
    doc = state.load(store, session_id)
    event_types = [e["event_type"] for e in doc["events"]]
    assert "heartbeat.ping" in event_types
    assert "result.available" in event_types
    # session.create is never called a second time -- exactly one session.created
    assert event_types.count("session.created") == 1
