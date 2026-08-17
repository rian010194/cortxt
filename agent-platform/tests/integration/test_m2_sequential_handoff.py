from __future__ import annotations

import os
from pathlib import Path

import pytest

from supervisor.coordinator import Coordinator

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-02-code-fixture"
FIXTURE_1 = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
FIXTURE_2 = VERTICAL / "evals" / "synthetic" / "003-stats-depends-on-ranges"
PATCH_SCHEMA_PATH = VERTICAL / "schemas" / "patch-proposal.schema.json"
SYSTEM_PROMPT_PATH = VERTICAL / "instructions" / "system-prompt-fix.md"


@pytest.mark.real_inference
@pytest.mark.docker_required
def test_m2_child_two_only_succeeds_because_of_the_handoff(tmp_path):
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

    envelope = coordinator.run_m2(
        task_id="fas4-m2-exit-criterion",
        child1_spec={"fixture_dir": FIXTURE_1, "config": _config(FIXTURE_1, "m2-child-1"), "allocated_budget": 1},
        child2_spec={"fixture_dir": FIXTURE_2, "config": _config(FIXTURE_2, "m2-child-2"), "allocated_budget": 1},
        total_budget=2, timeout=180.0,
    )

    assert envelope["status"] == "succeeded", envelope
    assert len(envelope["children"]) == 2
    assert envelope["children"][0]["status"] == "succeeded"
    assert envelope["children"][1]["status"] == "succeeded"


def test_m2_child_two_never_spawned_if_child_one_fails(tmp_path):
    """child 1's fixture_dir points at an empty workspace, so run_workspace()
    raises RunWorkspaceError("source_empty", ...) before any inference call or
    sandbox use (confirmed against CodingLoop.run()'s actual source: the
    fixture.yaml read and the `with run_workspace(source) as ws:` block both
    happen before self._sandbox_factory(caps) or any port.invoke() call) --
    CodingLoop.run() returns status "blocked" deterministically, with no
    Docker daemon or real model needed. Proves the join-failure path without
    depending on real_inference/docker_required at all."""
    store = tmp_path / "sessions"
    coordinator = Coordinator(store=store)

    broken_fixture_dir = tmp_path / "broken-fixture"
    (broken_fixture_dir / "workspace").mkdir(parents=True)
    (broken_fixture_dir / "fixture.yaml").write_text(
        "fixture_id: broken\nfixture_type: positive\ndescription: deliberately empty\n"
        "workspace_dir: ./workspace\ndeclared_scope: []\n"
        "caps: {max_files: 1, max_bytes_per_file: 1024, max_changed_lines: 10, max_executions: 1}\n"
        "expected_failing_test: none\nhuman_review_required: false\n",
        encoding="utf-8",
    )
    # workspace/ deliberately left empty -> run_workspace() raises source_empty

    broken_config = {"task_id": "m2-child-1-broken", "model": "unused",
                      "fixture_dir": str(broken_fixture_dir), "patch_schema_path": str(PATCH_SCHEMA_PATH),
                      "system_prompt_path": str(SYSTEM_PROMPT_PATH)}
    good_config = {"task_id": "m2-child-2", "model": "unused",
                   "fixture_dir": str(FIXTURE_2), "patch_schema_path": str(PATCH_SCHEMA_PATH),
                   "system_prompt_path": str(SYSTEM_PROMPT_PATH)}

    envelope = coordinator.run_m2(
        task_id="fas4-m2-join-failure",
        child1_spec={"fixture_dir": broken_fixture_dir, "config": broken_config, "allocated_budget": 1},
        child2_spec={"fixture_dir": FIXTURE_2, "config": good_config, "allocated_budget": 1},
        total_budget=2, timeout=60.0,
    )

    assert envelope["status"] == "blocked"
    assert len(envelope["children"]) == 1  # child 2 never spawned
    assert envelope["children"][0]["status"] == "blocked"
