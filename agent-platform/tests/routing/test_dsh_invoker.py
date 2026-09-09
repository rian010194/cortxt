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
    def __init__(self, result=None, error: Exception | None = None,
                 enter_error: Exception | None = None,
                 exit_error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        # #531: the real SDK spawns its JSON-RPC runtime in `__enter__`, not in
        # the constructor, so "the runtime is missing" is a failure of THIS
        # step. A fake that can only fail in `run` cannot express the defect.
        self.enter_error = enter_error
        # And `close()` really can fail -- it terminates a subprocess and waits
        # on it (`proc.terminate()`, `proc.wait()`, `proc.kill()`).
        self.exit_error = exit_error
        self.entered = False
        self.exited = False
        self.closed = False
        self.exit_exc_types: list[type | None] = []
        self.run_calls: list[tuple] = []

    def __enter__(self) -> "_FakeHarness":
        if self.enter_error is not None:
            raise self.enter_error
        self.entered = True
        return self

    def __exit__(self, exc_type=None, *_rest) -> bool:
        self.exited = True
        self.exit_exc_types.append(exc_type)
        if self.exit_error is not None:
            raise self.exit_error
        return False

    def close(self) -> None:
        self.closed = True
        if self.exit_error is not None:
            raise self.exit_error

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


# --- #531: a runtime that never started is not a worker that ran and failed

def test_a_runtime_that_cannot_start_raises_instead_of_reporting_a_failed_worker():
    """The defect, stated as the property that was violated.

    `DeepSeekHarness(...)` only builds a config object; the runtime subprocess
    is spawned by `__enter__`. On a host with no carrier the harness therefore
    constructs fine and fails on entry -- and a single `try` around
    `with harness:` returned that as `status: "failed"`, which
    `DshWorkerAdapter` maps to `worker_nonzero_exit`. The platform then asserts
    that a worker ran and exited badly when none ever started.
    """
    harness = _FakeHarness(enter_error=FileNotFoundError(
        "no dsh-jsonrpc-agent binary for platform win32"))

    with pytest.raises(DshInvocationError) as excinfo:
        invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness))

    # The SDK's own diagnosis must survive: it is the only text that says what
    # to obtain and for which platform.
    assert "no dsh-jsonrpc-agent binary for platform win32" in str(excinfo.value)
    assert "FileNotFoundError" in str(excinfo.value)
    # And it must be distinguishable from a factory failure, which is a
    # different environment fault with a different remedy.
    assert "could not start DSH runtime" in str(excinfo.value)
    assert harness.run_calls == [], "no worker may be invoked when the runtime never started"


def test_a_failed_launch_is_reaped_without_being_exited():
    """A failed launch can still have spawned a subprocess.

    The SDK's `start()` is `Popen` *followed by* a JSON-RPC handshake, so a
    handshake that fails -- wrong model, rejected key, timeout -- leaves a live
    runtime behind. `close()` is idempotent and is the SDK's documented way to
    reap it. `__exit__` is the wrong call: the harness never entered.
    """
    harness = _FakeHarness(enter_error=RuntimeError("runtime handshake failed"))

    with pytest.raises(DshInvocationError):
        invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness))

    assert harness.entered is False
    assert harness.exited is False, "a harness whose __enter__ raised was never entered"
    assert harness.closed is True, "a spawned runtime must not outlive the failed launch"


def test_a_failed_close_never_hides_the_launch_diagnosis():
    """Reaping is best-effort. The launch error names what to obtain; a second
    error from cleaning up after it must not replace that."""
    harness = _FakeHarness(enter_error=FileNotFoundError("no carrier for win32"),
                           exit_error=OSError("could not reap runtime"))

    with pytest.raises(DshInvocationError) as excinfo:
        invoke_dsh("p", timeout_seconds=60, harness_factory=_factory(harness))

    assert "no carrier for win32" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, FileNotFoundError), \
        "the SDK's own exception must stay reachable as the cause"


def test_a_worker_that_started_and_failed_keeps_its_own_status():
    """Regression guard on the half that must NOT change.

    This passed before the split too, and that is the point: making a launch
    failure raise is only correct if a worker failure keeps being returned.
    """
    harness = _FakeHarness(error=RuntimeError("model refused"))

    result = invoke_dsh("do the thing", timeout_seconds=60, harness_factory=_factory(harness))

    assert result["status"] == "failed"
    assert "model refused" in result["stderr"]
    assert harness.entered is True and harness.exited is True


def test_the_runtime_is_closed_on_every_outcome():
    """Entering by hand moved `with`'s closing guarantee into this function.

    Also a guard rather than a proof of new behaviour: `with` already gave
    this, and the split must not have cost it. A runtime left open outlives its
    Run and holds a subprocess for a dispatch that already ended.
    """
    outcomes = {
        "succeeded": _FakeHarness(result=_FakeRunResult("s", "ok", "completed")),
        "failed": _FakeHarness(error=RuntimeError("boom")),
        "timed_out": _FakeHarness(error=TimeoutError("too slow")),
    }
    for expected, harness in outcomes.items():
        result = invoke_dsh("p", timeout_seconds=60, harness_factory=_factory(harness))
        assert result["status"] == expected
        assert harness.exited is True, f"runtime left open after {expected}"


def test_exit_is_told_what_actually_went_wrong():
    """What `with` delivered and a hand-written `__exit__(None, None, None)`
    would quietly drop.

    Both arms matter, and the classified ones are the easy ones to lose: a
    worker error is caught here and turned into a status, so nothing propagates
    to carry the exc_info -- it has to be passed on deliberately. A harness that
    logs or reports on exc_info would otherwise be told every failed and timed
    out run ended cleanly.
    """
    class _Interrupt(BaseException):
        pass

    for error, expected in (
        (RuntimeError("model refused"), RuntimeError),
        (TimeoutError("too slow"), TimeoutError),
        (_Interrupt("operator stopped the run"), _Interrupt),
    ):
        harness = _FakeHarness(error=error)
        try:
            invoke_dsh("p", timeout_seconds=60, harness_factory=_factory(harness))
        except _Interrupt:
            pass
        assert harness.exit_exc_types == [expected], \
            f"the runtime must be told a {expected.__name__} was in flight"

    clean = _FakeHarness(result=_FakeRunResult("s", "ok", "completed"))
    invoke_dsh("p", timeout_seconds=60, harness_factory=_factory(clean))
    assert clean.exit_exc_types == [None], "a clean run must not be reported as an error"


def test_a_run_that_completed_is_never_reclassified_by_a_failing_close():
    """The inversion this change exists to remove, in the opposite direction.

    Closing the runtime happens after the worker's outcome is known. If that
    failure escaped `invoke_dsh` it would reach `DshWorkerAdapter`'s exception
    arm and be reported as `runtime_unavailable` -- "worker never started" for a
    worker that started and succeeded. Recorded, never reclassified, and never
    silently dropped either.
    """
    harness = _FakeHarness(result=_FakeRunResult("s-1", "the answer", "completed"),
                           exit_error=OSError("could not reap runtime"))

    result = invoke_dsh("p", timeout_seconds=60, harness_factory=_factory(harness))

    assert result["status"] == "succeeded"
    assert result["stdout"] == "the answer"
    assert "could not reap runtime" in result["stderr"], \
        "a runtime that will not close is a real fact about the host"


def test_a_failing_close_does_not_mask_a_worker_failure():
    """Same rule on the other arm: the worker's own diagnosis stays first."""
    harness = _FakeHarness(error=RuntimeError("model refused"),
                           exit_error=OSError("could not reap runtime"))

    result = invoke_dsh("p", timeout_seconds=60, harness_factory=_factory(harness))

    assert result["status"] == "failed"
    assert result["stderr"].startswith("RuntimeError: model refused")
    assert "could not reap runtime" in result["stderr"]


def test_a_factory_failure_and_a_launch_failure_are_told_apart():
    """Two environment faults with two different remedies: no SDK installed at
    all, versus an SDK that cannot start a runtime on this platform."""
    def failing_factory(_config):
        raise ImportError("no module named deepseek_harness")

    with pytest.raises(DshInvocationError) as from_factory:
        invoke_dsh("p", timeout_seconds=60, harness_factory=failing_factory)

    with pytest.raises(DshInvocationError) as from_launch:
        invoke_dsh("p", timeout_seconds=60, harness_factory=_factory(
            _FakeHarness(enter_error=FileNotFoundError("no carrier for win32"))))

    assert "could not start DSH harness" in str(from_factory.value)
    assert "could not start DSH runtime" in str(from_launch.value)
    assert isinstance(from_factory.value.__cause__, ImportError)
    assert isinstance(from_launch.value.__cause__, FileNotFoundError)
