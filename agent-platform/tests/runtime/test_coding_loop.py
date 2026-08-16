"""Full coding loop: claim -> workspace -> baseline (must fail) -> discover ->
propose -> apply -> diff -> scope -> falsify -> envelope -> cleanup.

TextInferencePort is faked (0 cost, deterministic) and the sandbox uses a
scripted fake runner (0 cost, no Docker) -- the mechanism is proven here with
zero model calls and zero container launches, per the design spec's testing
strategy ("Integration test (0 cost, in default CI)").
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from adapters.inference.budget_gate import BudgetExhausted
from runtime.coding.coding_loop import CodingLoop
from runtime.coding.coding_profile import CODING_PROFILE
from runtime.execution.subprocess_sandbox import ExecutionSandbox
from runtime.execution.write_policy import WriteCaps
from runtime.session_state import load

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-02-code-fixture"
FIXTURE_DIR = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
PATCH_SCHEMA = json.loads((VERTICAL / "schemas" / "patch-proposal.schema.json").read_text(encoding="utf-8"))
SYSTEM_PROMPT = (VERTICAL / "instructions" / "system-prompt-fix.md").read_text(encoding="utf-8")

FIXED = (
    '"""Small numeric helpers."""\n\n\n'
    "def sum_to(n):\n"
    '    """Return the sum of all integers from 1 to n, inclusive."""\n'
    "    total = 0\n"
    "    for i in range(1, n + 1):\n"
    "        total += i\n"
    "    return total\n"
)


class FakePort:
    """Stands in for TextInferencePort -- same .invoke(prompt, schema) -> dict shape."""

    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.calls: list[tuple] = []

    def invoke(self, prompt, output_schema):
        self.calls.append((prompt, output_schema))
        if self._raise:
            raise self._raise
        return self._response


class ScriptedRunner:
    """Returns one canned CompletedProcess per call, consumed in order.

    Stands in for `docker run` without a daemon: the FIRST call is the
    baseline check (must fail as shipped), later calls are the patched
    workspace (must pass once the model's fix is applied).
    """

    def __init__(self, returncodes: list[int], stdout: str = "", stderr: str = ""):
        import subprocess
        self._subprocess = subprocess
        self._returncodes = list(returncodes)
        self._stdout, self._stderr = stdout, stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        rc = self._returncodes.pop(0) if self._returncodes else 0
        return self._subprocess.CompletedProcess(argv, rc, self._stdout, self._stderr)


def _sandbox_factory(runner):
    return lambda caps: ExecutionSandbox(runner=runner, max_executions=caps.max_executions)


def test_coding_loop_succeeds_end_to_end_against_the_real_fixture(tmp_path):
    port = FakePort(response={
        "changes": [{"path": "ranges.py", "new_content": FIXED}],
        "rationale": "range() excluded n; range(1, n + 1) includes it",
    })
    runner = ScriptedRunner(returncodes=[1, 0])  # baseline fails, patched passes
    loop = CodingLoop(store=tmp_path / "sessions", port=port, patch_schema=PATCH_SCHEMA,
                      system_prompt=SYSTEM_PROMPT, sandbox_factory=_sandbox_factory(runner))

    envelope = loop.run(task_id="fas3-happy-path", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "succeeded", envelope.get("reason")
    assert envelope["result"]["files_changed"] == ["ranges.py"]
    assert envelope["result"]["tests_passed"] is True
    assert "range(1, n + 1)" in envelope["result"]["diff"]
    assert len(runner.calls) == 2  # exactly one baseline run, one patched run


def test_session_log_records_the_expected_event_sequence(tmp_path):
    port = FakePort(response={
        "changes": [{"path": "ranges.py", "new_content": FIXED}],
        "rationale": "off by one",
    })
    runner = ScriptedRunner(returncodes=[1, 0])
    loop = CodingLoop(store=tmp_path / "sessions", port=port, patch_schema=PATCH_SCHEMA,
                      system_prompt=SYSTEM_PROMPT, sandbox_factory=_sandbox_factory(runner))
    envelope = loop.run(task_id="t1", fixture_dir=FIXTURE_DIR)

    session = load(tmp_path / "sessions", envelope["session_id"])
    event_types = [e["event_type"] for e in session["events"]]
    assert event_types == [
        "session.created", "workspace.created",
        "execution.requested", "execution.completed",  # baseline
        "discovery.completed",
        "inference.requested", "inference.completed",
        "patch.admitted", "patch.applied",
        "execution.requested", "execution.completed",  # patched
        "session.terminal",
    ]


def test_blocked_when_the_baseline_already_passes(tmp_path):
    """No bug to fix -> terminate blocked at step 3, before any model call."""
    port = FakePort(response={"changes": [], "rationale": "unused"})
    runner = ScriptedRunner(returncodes=[0])  # baseline passes as shipped
    loop = CodingLoop(store=tmp_path / "sessions", port=port, patch_schema=PATCH_SCHEMA,
                      system_prompt=SYSTEM_PROMPT, sandbox_factory=_sandbox_factory(runner))

    envelope = loop.run(task_id="t1", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "blocked"
    assert envelope["reason"] == "no_bug_to_fix"
    assert port.calls == []  # no model call once there's nothing to fix
    assert len(runner.calls) == 1


def test_blocked_on_schema_invalid_response_and_workspace_is_unchanged(tmp_path):
    port = FakePort(response={"changes": [{"path": "ranges.py", "new_content": FIXED}]})  # missing "rationale"
    runner = ScriptedRunner(returncodes=[1])
    loop = CodingLoop(store=tmp_path / "sessions", port=port, patch_schema=PATCH_SCHEMA,
                      system_prompt=SYSTEM_PROMPT, sandbox_factory=_sandbox_factory(runner))
    before = hashlib.sha256((FIXTURE_DIR / "workspace" / "ranges.py").read_bytes()).hexdigest()

    envelope = loop.run(task_id="t1", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "blocked"
    assert envelope["reason"] == "schema"
    after = hashlib.sha256((FIXTURE_DIR / "workspace" / "ranges.py").read_bytes()).hexdigest()
    assert after == before  # the SOURCE fixture is never touched -- only its disposable copy is


def test_blocked_on_scope_expansion_when_the_patch_touches_the_test_file(tmp_path):
    """Touches exactly ONE file (test_ranges.py) so this stays within the
    default fixture's max_files: 1 cap and CODING_PROFILE's default_caps
    ceiling (J9: the ceiling clamps every fixture to max_files=1 regardless of
    what the fixture itself declares) -- a two-file patch would always be
    rejected as cap_max_files before the scope check ever runs, per J11's
    mandated apply-then-diff-then-scope ordering, and so could never actually
    exercise scope_expansion under this profile. declared_scope is [ranges.py]
    only, so a single-file patch to test_ranges.py is still an out-of-scope
    expansion, not a cap violation -- it just proves the file-count and
    scope-membership checks are independent."""
    port = FakePort(response={
        "changes": [
            {"path": "test_ranges.py", "new_content": "def test_sum_to_five():\n    assert True\n"},
        ],
        "rationale": "'simplified' the test instead of fixing the bug",
    })
    runner = ScriptedRunner(returncodes=[1])
    loop = CodingLoop(store=tmp_path / "sessions", port=port, patch_schema=PATCH_SCHEMA,
                      system_prompt=SYSTEM_PROMPT, sandbox_factory=_sandbox_factory(runner))

    envelope = loop.run(task_id="t1", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "blocked"
    assert envelope["reason"] == "scope_expansion"
    assert len(runner.calls) == 1  # falsify_fix never ran -- short-circuited per Task 10's J5


def test_blocked_on_cap_violation_and_nothing_is_applied(tmp_path):
    oversized = FIXED + "\n".join(f"# padding {i}" for i in range(200)) + "\n"
    port = FakePort(response={
        "changes": [{"path": "ranges.py", "new_content": oversized}],
        "rationale": "way more than a minimal fix",
    })
    runner = ScriptedRunner(returncodes=[1])
    loop = CodingLoop(store=tmp_path / "sessions", port=port, patch_schema=PATCH_SCHEMA,
                      system_prompt=SYSTEM_PROMPT, sandbox_factory=_sandbox_factory(runner))

    envelope = loop.run(task_id="t1", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "blocked"
    assert envelope["reason"] == "cap_max_changed_lines"
    assert len(runner.calls) == 1  # never reached falsify_fix


def test_blocked_on_budget_exhausted_without_a_partial_success(tmp_path):
    port = FakePort(raise_exc=BudgetExhausted("no budget"))
    runner = ScriptedRunner(returncodes=[1])
    loop = CodingLoop(store=tmp_path / "sessions", port=port, patch_schema=PATCH_SCHEMA,
                      system_prompt=SYSTEM_PROMPT, sandbox_factory=_sandbox_factory(runner))

    envelope = loop.run(task_id="t1", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "blocked"
    assert envelope["reason"] == "budget_exhausted"
    session = load(tmp_path / "sessions", envelope["session_id"])
    assert session["events"][-1]["payload"]["status"] == "blocked"


def test_blocked_on_falsification_failure_when_the_patch_does_not_fix_the_bug(tmp_path, tmp_path_factory):
    """A patch that stays in scope but does not actually fix the bug must not
    read as success just because it applied cleanly. Uses a fixture variant
    with a scope wide enough to admit the change, and a scripted sandbox that
    reports the patched run as still failing."""
    variant = tmp_path_factory.mktemp("variant")
    workspace = variant / "workspace"
    workspace.mkdir()
    (workspace / "ranges.py").write_text(
        "def sum_to(n):\n    total = 0\n    for i in range(1, n):\n        total += i\n    return total\n",
        encoding="utf-8",
    )
    (workspace / "test_ranges.py").write_text(
        "from ranges import sum_to\n\n\ndef test_sum_to_five():\n    assert sum_to(5) == 15\n",
        encoding="utf-8",
    )
    (variant / "fixture.yaml").write_text(
        "fixture_id: v02-syn-code-variant\n"
        "fixture_type: positive\n"
        "workspace_dir: ./workspace\n"
        "declared_scope: [ranges.py]\n"
        "caps: {max_files: 1, max_bytes_per_file: 16384, max_changed_lines: 20, max_executions: 4}\n"
        "expected_failing_test: test_ranges.py::test_sum_to_five\n"
        "human_review_required: false\n",
        encoding="utf-8",
    )

    port = FakePort(response={
        "changes": [{"path": "ranges.py", "new_content": "def sum_to(n):\n    return 0\n"}],
        "rationale": "wrong fix",
    })
    runner = ScriptedRunner(returncodes=[1, 1])  # baseline fails, patched STILL fails
    loop = CodingLoop(store=tmp_path / "sessions", port=port, patch_schema=PATCH_SCHEMA,
                      system_prompt=SYSTEM_PROMPT, sandbox_factory=_sandbox_factory(runner))

    envelope = loop.run(task_id="t1", fixture_dir=variant)

    assert envelope["status"] == "blocked"
    assert envelope["reason"] == "falsification_failed"


def test_caps_are_clamped_to_the_profile_ceiling_not_trusted_from_the_fixture(tmp_path):
    """J9: a fixture cannot self-report a wider cap than the platform grants."""
    from runtime.coding.coding_loop import _effective_caps

    ceiling = WriteCaps(max_files=1, max_bytes_per_file=100, max_changed_lines=5, max_executions=2)
    wider = WriteCaps(max_files=99, max_bytes_per_file=99999, max_changed_lines=99, max_executions=99)
    effective = _effective_caps(fixture_caps=wider, ceiling=ceiling)
    assert effective == ceiling  # every field clamped down, none loosened
