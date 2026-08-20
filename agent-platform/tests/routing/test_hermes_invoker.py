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
        if argv[:3] == ["hermes", "sessions", "list"]:
            return _FakeCompletedProcess(0, stdout="")
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
        if argv[:3] == ["hermes", "sessions", "list"]:
            return _FakeCompletedProcess(0, stdout="")
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


def test_invoke_hermes_passes_resume_flag_when_session_id_given():
    def fake_run(argv, **kwargs):
        assert argv == ["hermes", "-p", "builder", "-z", "do the thing", "--resume", "sess-123"]
        return _FakeCompletedProcess(0, stdout="ok")

    result = invoke_hermes(
        "builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run,
        session_id="sess-123",
    )
    assert result["status"] == "succeeded"


def test_invoke_hermes_omits_resume_flag_when_session_id_is_none():
    def fake_run(argv, **kwargs):
        assert "--resume" not in argv
        return _FakeCompletedProcess(0, stdout="ok")

    invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)


_SESSIONS_TABLE = (
    "Preview                                Workspace          Last Active   Src    ID\n"
    "─" * 104 + "\n"
    "reply with exactly: ok                 agent-platform     just now      cli    20260820_112139_8c44cf\n"
)


def test_invoke_hermes_captures_new_session_id_on_fresh_success(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ["hermes", "sessions", "list"]:
            return _FakeCompletedProcess(0, stdout=_SESSIONS_TABLE)
        return _FakeCompletedProcess(0, stdout="ok")

    result = invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)

    assert result["session_id"] == "20260820_112139_8c44cf"
    assert calls[0][:4] == ["hermes", "-p", "builder", "-z"]
    assert calls[1][:3] == ["hermes", "sessions", "list"]


def test_invoke_hermes_echoes_back_resumed_session_id_without_a_lookup_call(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _FakeCompletedProcess(0, stdout="ok")

    result = invoke_hermes(
        "builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run,
        session_id="20260820_112139_8c44cf",
    )

    assert result["session_id"] == "20260820_112139_8c44cf"
    assert len(calls) == 1  # no extra "sessions list" lookup needed on resume


def test_invoke_hermes_session_id_is_none_when_call_fails():
    def fake_run(argv, **kwargs):
        return _FakeCompletedProcess(1, stdout="", stderr="model refused")

    result = invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)
    assert result["session_id"] is None


def test_parse_latest_session_id_reads_last_column_of_one_data_row():
    from routing.hermes_invoker import _parse_latest_session_id

    assert _parse_latest_session_id(_SESSIONS_TABLE) == "20260820_112139_8c44cf"


def test_parse_latest_session_id_returns_none_when_table_has_no_data_rows():
    from routing.hermes_invoker import _parse_latest_session_id

    header_only = "Preview   Workspace   Last Active   Src    ID\n" + ("─" * 40) + "\n"
    assert _parse_latest_session_id(header_only) is None


def test_parse_latest_session_id_strips_ansi_escapes_before_parsing():
    from routing.hermes_invoker import _parse_latest_session_id

    ansi_table = (
        "\x1b[1mPreview  Workspace  Last Active  Src  ID\x1b[0m\n"
        + "─" * 40 + "\n"
        + "\x1b[32mok\x1b[0m       agent-platform  just now    cli  20260820_112139_8c44cf\n"
    )
    assert _parse_latest_session_id(ansi_table) == "20260820_112139_8c44cf"


def test_invoke_hermes_stays_succeeded_when_session_capture_lookup_fails():
    def fake_run(argv, **kwargs):
        if argv[:3] == ["hermes", "sessions", "list"]:
            return _FakeCompletedProcess(1, stdout="", stderr="db locked")
        return _FakeCompletedProcess(0, stdout="ok")

    result = invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)

    assert result["status"] == "succeeded"
    assert result["session_id"] is None


def test_invoke_hermes_echoes_back_input_session_id_when_a_resumed_call_fails():
    # A resume call that fails (bad/expired session_id, or a transient
    # error) still echoes back the *input* session_id rather than clearing
    # it to None -- deliberate: the caller already had this id, a failed
    # turn doesn't prove it's invalid (could be a timeout, rate limit,
    # etc.), and the REPL's next turn to the same engine will just retry
    # with the same id rather than silently starting a fresh, un-announced
    # conversation.
    def fake_run(argv, **kwargs):
        return _FakeCompletedProcess(1, stdout="", stderr="model refused")

    result = invoke_hermes(
        "builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run,
        session_id="sess-existing",
    )

    assert result["status"] == "failed"
    assert result["session_id"] == "sess-existing"
