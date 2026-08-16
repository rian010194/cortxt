"""ExecutionSandbox: argv construction, allowlist, env scrubbing, caps.

Every test in this file uses an injected fake runner, so the whole file runs
green with the Docker daemon stopped. The tests that need a real daemon live in
test_sandbox_boundaries_docker.py and are marked docker_required.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from runtime.execution.subprocess_sandbox import (
    ALLOWED_COMMANDS,
    BASE_IMAGE,
    ExecutionError,
    ExecutionSandbox,
    child_env,
)


class FakeRunner:
    """Stands in for subprocess.run — records calls, returns a canned result."""

    def __init__(self, stdout: str | bytes = "", stderr: str | bytes = "", returncode: int = 0, raise_exc=None):
        self.calls: list[dict] = []
        self._stdout, self._stderr, self._rc, self._raise = stdout, stderr, returncode, raise_exc

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        if self._raise is not None:
            raise self._raise
        errors = kwargs.get("errors", "strict")
        stdout = self._decode(self._stdout, kwargs.get("text"), errors)
        stderr = self._decode(self._stderr, kwargs.get("text"), errors)
        return subprocess.CompletedProcess(argv, self._rc, stdout, stderr)

    @staticmethod
    def _decode(value, text, errors):
        if not text or not isinstance(value, bytes):
            return value
        return value.decode("utf-8", errors)


def _workspace(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / "ranges.py").write_text("X = 1\n", encoding="utf-8")
    return work


def test_base_image_is_digest_pinned_never_a_mutable_tag():
    assert re.fullmatch(r"python@sha256:[0-9a-f]{64}", BASE_IMAGE), (
        f"BASE_IMAGE must be digest-pinned, got {BASE_IMAGE!r}. Resolve it with "
        "`docker pull python:3.12-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim`"
    )


def test_allowlist_has_exactly_one_entry_and_it_is_a_list_of_strings():
    assert list(ALLOWED_COMMANDS) == ["run_pytest"]
    argv = ALLOWED_COMMANDS["run_pytest"]
    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)


def test_build_argv_declares_network_none_rm_and_a_pinned_workdir(tmp_path):
    work = _workspace(tmp_path)
    argv = ExecutionSandbox(runner=FakeRunner()).build_argv("run_pytest", work)
    assert argv[0] == "docker"
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "--rm" in argv
    assert "--workdir" in argv and argv[argv.index("--workdir") + 1] == "/workspace"
    assert argv[-len(ALLOWED_COMMANDS["run_pytest"]):] == ALLOWED_COMMANDS["run_pytest"]


def test_build_argv_mounts_the_resolved_workspace_root(tmp_path):
    work = _workspace(tmp_path)
    argv = ExecutionSandbox(runner=FakeRunner()).build_argv("run_pytest", work)
    mount = argv[argv.index("-v") + 1]
    assert mount == f"{work.resolve()}:/workspace"


def test_build_argv_disables_the_pytest_cache_so_the_diff_stays_clean(tmp_path):
    work = _workspace(tmp_path)
    argv = ExecutionSandbox(runner=FakeRunner()).build_argv("run_pytest", work)
    assert "-p" in argv and "no:cacheprovider" in argv
    assert "-e" in argv and "PYTHONDONTWRITEBYTECODE=1" in argv


def test_run_refuses_an_unknown_command_before_the_runner_is_reached(tmp_path):
    work = _workspace(tmp_path)
    runner = FakeRunner()
    sandbox = ExecutionSandbox(runner=runner)
    with pytest.raises(ExecutionError) as exc:
        sandbox.run("rm_rf_slash", work)
    assert exc.value.reason == "unknown_command"
    assert runner.calls == []  # the launcher was never reached


def test_run_refuses_a_command_supplied_as_a_string(tmp_path):
    """A string command_id that happens to look like a shell line is still just an
    unknown key — there is no code path that turns a string into argv."""
    work = _workspace(tmp_path)
    runner = FakeRunner()
    sandbox = ExecutionSandbox(runner=runner)
    with pytest.raises(ExecutionError):
        sandbox.run("python -m pytest && curl http://evil", work)
    assert runner.calls == []


def test_run_never_passes_shell_true(tmp_path):
    work = _workspace(tmp_path)
    runner = FakeRunner()
    ExecutionSandbox(runner=runner).run("run_pytest", work)
    assert runner.calls[0].get("shell", False) is False


def test_run_refuses_a_workspace_that_is_not_a_directory(tmp_path):
    runner = FakeRunner()
    sandbox = ExecutionSandbox(runner=runner)
    with pytest.raises(ExecutionError) as exc:
        sandbox.run("run_pytest", tmp_path / "does-not-exist")
    assert exc.value.reason == "workspace_invalid"
    assert runner.calls == []


def test_child_env_is_allowlist_built_and_carries_no_credentials(monkeypatch):
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "canary-must-not-leak")
    monkeypatch.setenv("KIMI_API_KEY", "canary-must-not-leak")
    monkeypatch.setenv("GH_TOKEN", "canary-must-not-leak")
    env = child_env()
    assert "canary-must-not-leak" not in "".join(env.values())
    assert "CORTXT_INFERENCE_API_KEY" not in env
    assert "KIMI_API_KEY" not in env
    assert "GH_TOKEN" not in env
    assert env["PYTHONHASHSEED"] == "0"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_run_passes_the_scrubbed_env_to_the_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "canary-must-not-leak")
    work = _workspace(tmp_path)
    runner = FakeRunner()
    ExecutionSandbox(runner=runner).run("run_pytest", work)
    passed = runner.calls[0]["env"]
    assert "CORTXT_INFERENCE_API_KEY" not in passed


def test_run_truncates_output_over_the_cap_and_flags_it(tmp_path):
    work = _workspace(tmp_path)
    runner = FakeRunner(stdout="a" * 5000, stderr="b" * 5000)
    result = ExecutionSandbox(runner=runner, max_output_bytes=100).run("run_pytest", work)
    assert result.truncated is True
    assert len(result.stdout) <= 100
    assert len(result.stderr) <= 100


def test_run_does_not_flag_truncation_for_short_output(tmp_path):
    work = _workspace(tmp_path)
    result = ExecutionSandbox(runner=FakeRunner(stdout="ok\n")).run("run_pytest", work)
    assert result.truncated is False
    assert result.timed_out is False
    assert result.exit_code == 0


def test_run_replaces_invalid_utf8_bytes_instead_of_crashing(tmp_path):
    """If the container emits non-UTF-8 bytes, errors=\"replace\" must keep the
    sandbox run intact instead of letting a strict decode raise UnicodeDecodeError."""
    work = _workspace(tmp_path)
    runner = FakeRunner(stdout=b"out prefix \xff suffix", stderr=b"err \xfe marker")
    result = ExecutionSandbox(runner=runner).run("run_pytest", work)
    assert result.exit_code == 0
    assert "\ufffd" in result.stdout
    assert "out prefix" in result.stdout
    assert "\ufffd" in result.stderr
    assert "marker" in result.stderr
    assert runner.calls[0].get("errors") == "replace"


def test_run_reports_timed_out_without_raising(tmp_path):
    work = _workspace(tmp_path)
    runner = FakeRunner(raise_exc=subprocess.TimeoutExpired(cmd="docker", timeout=1))
    result = ExecutionSandbox(runner=runner, timeout_seconds=1).run("run_pytest", work)
    assert result.timed_out is True
    assert result.exit_code != 0


def test_run_refuses_past_the_execution_cap(tmp_path):
    work = _workspace(tmp_path)
    runner = FakeRunner()
    sandbox = ExecutionSandbox(runner=runner, max_executions=2)
    sandbox.run("run_pytest", work)
    sandbox.run("run_pytest", work)
    assert sandbox.executions_used == 2
    with pytest.raises(ExecutionError) as exc:
        sandbox.run("run_pytest", work)
    assert exc.value.reason == "cap_max_executions"
    assert len(runner.calls) == 2  # the third launch never happened


def test_run_counts_a_timed_out_execution_against_the_cap(tmp_path):
    """A run that timed out still consumed a sandbox slot — otherwise the cap is
    bypassable by making every run time out (same principle as BudgetGate
    recording attempt_started up front)."""
    work = _workspace(tmp_path)
    runner = FakeRunner(raise_exc=subprocess.TimeoutExpired(cmd="docker", timeout=1))
    sandbox = ExecutionSandbox(runner=runner, timeout_seconds=1, max_executions=1)
    sandbox.run("run_pytest", work)
    with pytest.raises(ExecutionError):
        sandbox.run("run_pytest", work)
