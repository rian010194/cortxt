"""Fas 3 exit-criterion proof: the vertical-02 off-by-one fixture solved by
CodingLoop end to end -- a real model call proposing the fix, a real container
running the test suite -- without Pi or Hermes. Excluded from default CI by
BOTH opt-in markers (same convention as every other real_inference-marked
test in this repo, and as Task 8/13's docker_required tests): run manually
once CORTXT_INFERENCE_URL/CORTXT_INFERENCE_API_KEY are set,
cortxt_resilient_inference is installed, a Docker daemon is reachable, and
Task 8's BASE_IMAGE digest has been resolved. See
docs/superpowers/specs/2026-08-16-fas3-coding-agent-v01-design.md and
docs/superpowers/plans/2026-08-16-fas3-exit-criterion-checklist.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from adapters.inference.budget_gate import BudgetGate
from runtime.coding.coding_loop import CodingLoop
from runtime.coding.coding_profile import CODING_PROFILE
from runtime.execution.subprocess_sandbox import ExecutionSandbox, SANDBOX_IMAGE_TAG, docker_available
from runtime.text_inference_port import TextInferencePort

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-02-code-fixture"
FIXTURE_DIR = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
PATCH_SCHEMA = json.loads((VERTICAL / "schemas" / "patch-proposal.schema.json").read_text(encoding="utf-8"))
SYSTEM_PROMPT = (VERTICAL / "instructions" / "system-prompt-fix.md").read_text(encoding="utf-8")


@pytest.mark.real_inference
def test_off_by_one_fixture_solved_without_pi_or_hermes(tmp_path):
    model = os.environ.get("CORTXT_INFERENCE_MODEL")
    if not model:
        pytest.skip("CORTXT_INFERENCE_MODEL not set")
    if not docker_available():
        pytest.skip(
            "Docker daemon is not reachable -- this test is ALSO gated by "
            "docker_required (Task 8/13); a skip here is not a pass for "
            "either exit-criterion half"
        )

    budget_gate = BudgetGate(max_calls=1, db_path=tmp_path / "spend.db")
    port = TextInferencePort(
        model=model,
        budget_gate=budget_gate,
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    sandbox = ExecutionSandbox(image=SANDBOX_IMAGE_TAG, max_executions=4)
    loop = CodingLoop(
        store=tmp_path / "sessions",
        port=port,
        patch_schema=PATCH_SCHEMA,
        system_prompt=SYSTEM_PROMPT,
        sandbox_factory=lambda caps: sandbox,
        profile=CODING_PROFILE,
    )

    envelope = loop.run(task_id="fas3-exit-criterion", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "succeeded", envelope.get("reason")
    assert envelope["result"]["tests_passed"] is True
    assert envelope["result"]["files_changed"] == ["ranges.py"]
    assert "range(1, n + 1)" in envelope["result"]["diff"] or "range(1,n+1)" in envelope["result"]["diff"].replace(" ", "")
