from __future__ import annotations

import json
from pathlib import Path

from adapters.inference.budget_gate import BudgetGate
from runtime.coding.coding_loop import CodingLoop
from runtime.coding.coding_profile import CODING_PROFILE
from runtime.execution.subprocess_sandbox import ExecutionSandbox
import pytest

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-02-code-fixture"
FIXTURE_DIR = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
PATCH_SCHEMA = json.loads((VERTICAL / "schemas" / "patch-proposal.schema.json").read_text(encoding="utf-8"))
SYSTEM_PROMPT = (VERTICAL / "instructions" / "system-prompt-fix.md").read_text(encoding="utf-8")

_FIXED_RANGES_PY = (
    '"""Small numeric helpers."""\n\n\n'
    'def sum_to(n):\n'
    '    """Return the sum of all integers from 1 to n, inclusive."""\n'
    '    total = 0\n'
    '    for i in range(1, n + 1):\n'
    '        total += i\n'
    '    return total\n'
)


class _ScriptedPort:
    def invoke(self, prompt: str, schema: dict) -> dict:
        return {"changes": [{"path": "ranges.py", "new_content": _FIXED_RANGES_PY}],
                "rationale": "range() excluded n; widen to n + 1"}


@pytest.mark.docker_required
def test_succeeded_result_includes_file_contents_for_changed_files(tmp_path, sandbox_image):
    sandbox = ExecutionSandbox(image=sandbox_image, max_executions=4)
    loop = CodingLoop(store=tmp_path / "sessions", port=_ScriptedPort(),
                       patch_schema=PATCH_SCHEMA, system_prompt=SYSTEM_PROMPT,
                       sandbox_factory=lambda caps: sandbox, profile=CODING_PROFILE)

    envelope = loop.run(task_id="file-contents-check", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "succeeded"
    assert envelope["result"]["files_changed"] == ["ranges.py"]
    assert envelope["result"]["file_contents"] == {"ranges.py": _FIXED_RANGES_PY}
