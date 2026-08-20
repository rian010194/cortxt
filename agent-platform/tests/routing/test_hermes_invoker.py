from __future__ import annotations

import subprocess

import pytest

from routing.hermes_invoker import HermesInvocationError, invoke_hermes


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_invoke_hermes_returns_succeeded_on_zero_exit():
    def fake_run(argv, **kwargs):
        assert argv == ["hermes", "-p", "builder", "-z", "do the thing"]
        assert kwargs.get("timeout") == 60
        assert kwargs.get("encoding") == "utf-8"
        assert kwargs.get("errors") == "replace"
        return _FakeCompletedProcess(0, stdout="the response text\n")

    result = invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)
    assert result["status"] == "succeeded"
    assert result["stdout"] == "the response text\n"
    assert result["profile"] == "builder"
    assert isinstance(result["elapsed_seconds"], float)


def test_invoke_hermes_returns_failed_on_nonzero_exit():
    def fake_run(argv, **kwargs):
        return _FakeCompletedProcess(1, stdout="", stderr="model refused")

    result = invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)
    assert result["status"] == "failed"
    assert result["stderr"] == "model refused"


def test_invoke_hermes_passes_model_and_provider_overrides_when_given():
    def fake_run(argv, **kwargs):
        assert argv == [
            "hermes", "-p", "researcher", "-z", "do research",
            "-m", "deepseek-v4-flash-0731", "--provider", "custom:inferx",
        ]
        return _FakeCompletedProcess(0, stdout="ok")

    result = invoke_hermes(
        "researcher", "do research", timeout_seconds=60, run_subprocess=fake_run,
        model="deepseek-v4-flash-0731", provider="custom:inferx",
    )
    assert result["status"] == "succeeded"


def test_invoke_hermes_returns_timed_out_status_on_timeout():
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 0))

    result = invoke_hermes("builder", "do the thing", timeout_seconds=5, run_subprocess=fake_run)
    assert result["status"] == "timed_out"


def test_invoke_hermes_raises_on_missing_hermes_executable():
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("hermes not found")

    with pytest.raises(HermesInvocationError):
        invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)


def test_invoke_hermes_rejects_empty_prompt():
    with pytest.raises(ValueError):
        invoke_hermes("builder", "", timeout_seconds=60, run_subprocess=lambda *a, **k: None)
