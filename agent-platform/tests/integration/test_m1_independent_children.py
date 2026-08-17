from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from supervisor.coordinator import Coordinator

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-02-code-fixture"
FIXTURE_1 = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
FIXTURE_2 = VERTICAL / "evals" / "synthetic" / "002-independent-strings"
PATCH_SCHEMA_PATH = VERTICAL / "schemas" / "patch-proposal.schema.json"
SYSTEM_PROMPT_PATH = VERTICAL / "instructions" / "system-prompt-fix.md"


@pytest.mark.real_inference
@pytest.mark.docker_required
def test_m1_two_independent_children_succeed_and_merge(tmp_path):
    model = os.environ.get("CORTXT_INFERENCE_MODEL")
    if not model:
        pytest.skip("CORTXT_INFERENCE_MODEL not set")

    store = tmp_path / "sessions"
    coordinator = Coordinator(store=store)

    def _config(fixture_dir: Path, task_id: str) -> dict:
        return {
            "task_id": task_id, "model": model, "fixture_dir": str(fixture_dir),
            "patch_schema_path": str(PATCH_SCHEMA_PATH), "system_prompt_path": str(SYSTEM_PROMPT_PATH),
        }

    envelope = coordinator.run_m1(
        task_id="fas4-m1-exit-criterion",
        child_specs=[
            {"fixture_dir": FIXTURE_1, "config": _config(FIXTURE_1, "m1-child-1"), "allocated_budget": 1},
            {"fixture_dir": FIXTURE_2, "config": _config(FIXTURE_2, "m1-child-2"), "allocated_budget": 1},
        ],
        total_budget=2, timeout=180.0,
    )

    assert envelope["status"] == "succeeded", envelope
    assert len(envelope["children"]) == 2
    assert {c["status"] for c in envelope["children"]} == {"succeeded"}
