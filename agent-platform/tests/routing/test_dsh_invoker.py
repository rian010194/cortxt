"""Tests for routing/dsh_invoker.py -- the DSH Python-SDK wrapper.

The DSH SDK (deepseek_harness) is a library, not a bare CLI: it owns a
lazily-started JSON-RPC subprocess internally, so the injectable seam here
is a *harness factory* (a callable that returns a run()-capable object),
not a run_subprocess. Unit tests inject fake harnesses and never touch a
real runtime subprocess, model endpoint, or API key -- the same
0-model-call discipline as test_hermes_invoker.py.
"""
from __future__ import annotations

import pytest

from routing.dsh_invoker import DshInvocationError, invoke_dsh


class _FakeRunResult:
    def __init__(self, session_id: str, final_response: str, finish_reason: str | None) -> None:
        self.session_id = session_id
        self.final_response = final_response
        self.finish_reason = finish_reason


class _FakeHarness:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.entered = False
        self.exited = False
        self.run_calls: list[tuple] = []

    def __enter__(self) -> "_FakeHarness":
        self.entered = True
        return self

    def __exit__(self, *_exc) -> bool:
        self.exited = True
        return False

    def run(self, input: str, session_id: str | None = None) -> _FakeRunResult:
        self.run_calls.append((input, session_id))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("fake harness configured without a result")
        return self.result


def _factory(harness: _FakeHarness):
    def make(config: dict) -> _FakeHarness:
        harness.config = config
        return harness

    return make


def test_invoke_dsh_returns_succeeded_with_final_response():
    harness = _FakeHarness(result=_FakeRunResult("sess-1", "the answer", "completed"))
    result = invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness))

    assert result["status"] == "succeeded"
    assert result["stdout"] == "the answer"
    assert result["session_id"] == "sess-1"
    assert result["finish_reason"] == "completed"
    assert result["stderr"] == ""
    assert isinstance(result["elapsed_seconds"], float)
    assert harness.entered is True and harness.exited is True


def test_invoke_dsh_returns_failed_on_runtime_error():
    # Any SDK HarnessError subclass (JsonRpcError, TransportClosedError,
    # SdkProtocolError) is an Exception, and invoke_dsh maps every
    # in-run exception to the same failed envelope -- a generic RuntimeError
    # stands in for them so the test never imports the SDK (which is not a
    # test dependency of agent-platform).
    harness = _FakeHarness(error=RuntimeError("model refused"))
    result = invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness))

    assert result["status"] == "failed"
    assert "model refused" in result["stderr"]
    assert result["session_id"] is None


def test_invoke_dsh_returns_timed_out_on_timeout():
    harness = _FakeHarness(error=TimeoutError("request timed out"))
    result = invoke_dsh("do the thing", timeout_seconds=5, harness_factory=_factory(harness))

    assert result["status"] == "timed_out"
    assert "5" in result["stderr"]


def test_invoke_dsh_raises_when_sdk_not_installed():
    def missing_sdk(config: dict) -> None:
        raise ImportError("No module named 'deepseek_harness'")

    with pytest.raises(DshInvocationError):
        invoke_dsh("do the thing", timeout_seconds=60, harness_factory=missing_sdk)


def test_invoke_dsh_raises_when_harness_creation_fails():
    def broken_factory(config: dict) -> None:
        raise FileNotFoundError("dsh-jsonrpc-agent not found")

    with pytest.raises(DshInvocationError):
        invoke_dsh("do the thing", timeout_seconds=60, harness_factory=broken_factory)


def test_invoke_dsh_rejects_empty_prompt():
    with pytest.raises(ValueError):
        invoke_dsh("", timeout_seconds=60, harness_factory=lambda config: _FakeHarness())


def test_invoke_dsh_passes_config_timeout_and_resume_session_id():
    harness = _FakeHarness(result=_FakeRunResult("sess-9", "ok", "completed"))
    result = invoke_dsh(
        "do the thing", timeout_seconds=60, harness_factory=_factory(harness),
        model="deepseek-v4-flash-0731", provider="nous", session_id="sess-9",
    )

    assert result["status"] == "succeeded"
    assert harness.config["model"] == "deepseek-v4-flash-0731"
    assert harness.config["provider"] == "nous"
    assert harness.config["request_timeout_seconds"] == 60
    assert harness.run_calls[0][1] == "sess-9"  # resume passes session_id through


def test_invoke_dsh_uses_sdk_defaults_for_provider_and_model():
    harness = _FakeHarness(result=_FakeRunResult("sess-1", "ok", None))
    invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness))

    assert harness.config["provider"] == "deepseek-official"
    assert harness.config["model"] == "deepseek-v4-flash"


def test_invoke_dsh_passes_cwd_into_config():
    from pathlib import Path

    harness = _FakeHarness(result=_FakeRunResult("sess-1", "ok", None))
    invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness),
               cwd=Path("C:/work"))

    assert harness.config["cwd"] == str(Path("C:/work"))  # Path normalizes to native form


def test_invoke_dsh_finish_reason_none_is_preserved():
    harness = _FakeHarness(result=_FakeRunResult("sess-1", "ok", None))
    result = invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness))

    assert result["status"] == "succeeded"
    assert result["finish_reason"] is None


def test_invoke_dsh_stays_failed_with_input_session_id_on_error():
    # Mirrors hermes_invoker's resume-error convention: a failed turn does
    # not prove the input session_id is invalid, so echo it back rather than
    # clearing it to None (the caller can retry the same id).
    harness = _FakeHarness(error=RuntimeError("runtime stdout closed"))
    result = invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness),
                        session_id="sess-existing")

    assert result["status"] == "failed"
    assert result["session_id"] == "sess-existing"
