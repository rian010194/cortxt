"""Static config for Agent Runtime's coding profile (Fas 3 v0.1).

Mirrors research_profile.py's shape (design spec Components table): a
profile_id, an allowed_tools admission list, and a workflow reference. Unlike
research_profile.py, this profile also carries default_caps -- but as a
CEILING the platform is willing to grant, not the caps a given run actually
enforces. declared_scope and the effective caps are read per-fixture from
fixture.yaml (Task 11): they are properties of the TASK, per
docs/architecture/vertical-package-contract.md's "what a vertical owns" list,
and a static profile authored once cannot know a not-yet-written fixture's
file names or line budget. CodingLoop takes the tighter of the fixture's
declared caps and this ceiling for every field (see _effective_caps in
coding_loop.py), so a fixture cannot self-report a wider cap than the
platform is willing to grant.
"""
from __future__ import annotations

CODING_PROFILE = {
    "profile_id": "coding-v0.1",
    "allowed_tools": [
        "list_workspace",
        "read_workspace_file",
        "search_workspace",
        "apply_patch",
        "diff_workspace",
        "run_tests",
    ],
    "workflow": "vertical-02-code-fixture/fix-failing-test",
    "default_caps": {
        "max_files": 1,
        "max_bytes_per_file": 16384,
        "max_changed_lines": 20,
        "max_executions": 4,
    },
}
