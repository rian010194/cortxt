"""run_tests: the single bounded_execution tool. Thin by design — it names the
command id and nothing else, so no caller can steer it at a different command."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from runtime.execution.subprocess_sandbox import ExecutionError, ExecutionSandbox
from runtime.tools import RUN_TESTS_MANIFEST, run_tests


class FakeRunner:
    def __init__(self, returncode: int = 0):
        self.calls: list[list[str]] = []
        self._rc = returncode

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self._rc, "1 passed\n", "")


def _workspace(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return work


def test_run_tests_uses_the_run_pytest_command_id(tmp_path):
    work = _workspace(tmp_path)
    runner = FakeRunner()
    result = run_tests(ExecutionSandbox(runner=runner), work)
    assert result.command_id == "run_pytest"
    assert result.exit_code == 0
    assert runner.calls[0][0] == "docker"


def test_run_tests_surfaces_a_non_zero_exit_code(tmp_path):
    work = _workspace(tmp_path)
    result = run_tests(ExecutionSandbox(runner=FakeRunner(returncode=1)), work)
    assert result.exit_code == 1


def test_run_tests_propagates_the_execution_cap(tmp_path):
    work = _workspace(tmp_path)
    sandbox = ExecutionSandbox(runner=FakeRunner(), max_executions=1)
    run_tests(sandbox, work)
    with pytest.raises(ExecutionError) as exc:
        run_tests(sandbox, work)
    assert exc.value.reason == "cap_max_executions"


def test_manifest_declares_bounded_execution_with_no_network_or_credentials():
    assert RUN_TESTS_MANIFEST["id"] == "repository.run_tests"
    assert RUN_TESTS_MANIFEST["effect_class"] == "bounded_execution"
    assert RUN_TESTS_MANIFEST["network"] == "none"
    assert RUN_TESTS_MANIFEST["credentials"] == []
    assert RUN_TESTS_MANIFEST["filesystem"] == "current-run-workspace"
