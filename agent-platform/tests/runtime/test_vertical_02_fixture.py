"""Task 11: Write the failing test."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
import jsonschema
import yaml

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-02-code-fixture"
FIXTURE_DIR = VERTICAL / "evals" / "synthetic" / "001-off-by-one"


def test_package_has_the_declared_file_tree():
    for relative in (
        "vertical.yaml",
        "README.md",
        "schemas/patch-request.schema.json",
        "schemas/patch-proposal.schema.json",
        "instructions/system-prompt-fix.md",
        "evals/synthetic/001-off-by-one/fixture.yaml",
        "evals/synthetic/001-off-by-one/workspace/ranges.py",
        "evals/synthetic/001-off-by-one/workspace/test_ranges.py",
    ):
        assert (VERTICAL / relative).is_file(), f"missing {relative}"


def test_vertical_yaml_declares_the_workflow_and_no_platform_policy():
    manifest = yaml.safe_load((VERTICAL / "vertical.yaml").read_text(encoding="utf-8"))
    assert manifest["vertical_id"] == "vertical-02-code-fixture"
    assert [w["workflow_id"] for w in manifest["supported_workflows"]] == ["fix-failing-test"]
    # The vertical package contract forbids a vertical owning sandbox policy.
    forbidden = {"docker_image", "sandbox", "mounts", "timeout_seconds", "network", "credentials"}
    assert forbidden.isdisjoint(manifest.keys())


def test_patch_proposal_schema_accepts_the_expected_shape():
    schema = json.loads((VERTICAL / "schemas" / "patch-proposal.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(
        instance={
            "changes": [{"path": "ranges.py", "new_content": "def sum_to(n):\n    return n\n"}],
            "rationale": "range() excluded n",
        },
        schema=schema,
    )


def test_patch_proposal_schema_rejects_malformed_responses():
    schema = json.loads((VERTICAL / "schemas" / "patch-proposal.schema.json").read_text(encoding="utf-8"))
    for bad in (
        {"changes": [], "rationale": "empty"},
        {"changes": [{"path": "ranges.py"}], "rationale": "no content"},
        {"changes": [{"path": "ranges.py", "new_content": "x", "mode": "777"}], "rationale": "extra key"},
        {"rationale": "no changes key"},
        {"changes": [{"path": "ranges.py", "new_content": "x"}]},
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)


def test_fixture_yaml_declares_scope_caps_and_the_expected_failing_test():
    fixture = yaml.safe_load((FIXTURE_DIR / "fixture.yaml").read_text(encoding="utf-8"))
    assert fixture["fixture_id"] == "v02-syn-code-001"
    assert fixture["workspace_dir"] == "./workspace"
    assert fixture["declared_scope"] == ["ranges.py"]
    assert fixture["caps"]["max_files"] == 1
    assert fixture["expected_failing_test"] == "test_ranges.py::test_sum_to_five"


def test_the_fixture_workspace_really_is_broken():
    """The bug must be real: sum_to(5) must NOT equal 15 as shipped."""
    source = (FIXTURE_DIR / "workspace" / "ranges.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(compile(source, "ranges.py", "exec"), namespace)  # noqa: S102 - fixture is repo-owned
    assert namespace["sum_to"](5) == 10, "fixture is not broken; there would be no bug to fix"
    assert namespace["sum_to"](5) != 15


def test_the_declared_scope_excludes_the_test_file():
    """So a patch that neuters test_ranges.py is a scope violation, not a pass."""
    fixture = yaml.safe_load((FIXTURE_DIR / "fixture.yaml").read_text(encoding="utf-8"))
    from fnmatch import fnmatchcase

    assert not any(fnmatchcase("test_ranges.py", glob) for glob in fixture["declared_scope"])
