from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.adapters.codex_adapter import CodexAdapter, CodexInvocationError
from runtime.engine_adapter import EngineAdapter


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_THREAD_STARTED = '{"type":"thread.started","thread_id":"01a01e79-1e13-7643-b676-e02307b4b1be"}\n'


def _fake_run_writing_output_file(stdout=_THREAD_STARTED, returncode=0, message="ok"):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_text(message, encoding="utf-8")
        return _FakeCompletedProcess(returncode, stdout=stdout)

    return fake_run, calls


def test_codex_adapter_is_an_engine_adapter():
    assert isinstance(CodexAdapter(), EngineAdapter)


def test_fresh_call_builds_exec_argv_without_resume():
    fake_run, calls = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    result = adapter.invoke("researcher", "do it", timeout_seconds=60)

    argv, kwargs = calls[0]
    assert argv[:2] == ["codex", "exec"]
    assert "resume" not in argv
    assert "-p" in argv and argv[argv.index("-p") + 1] == "researcher"
    assert argv[-1] == "do it"
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert result["status"] == "succeeded"
    assert result["session_id"] == "01a01e79-1e13-7643-b676-e02307b4b1be"
    assert result["stdout"] == "ok"


def test_resume_call_includes_resume_and_session_id_before_json_flag():
    fake_run, calls = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    adapter.invoke("researcher", "continue", timeout_seconds=60, session_id="01a01e79-1e13-7643-b676-e02307b4b1be")

    argv, _ = calls[0]
    assert argv[:4] == ["codex", "exec", "resume", "01a01e79-1e13-7643-b676-e02307b4b1be"]


def test_model_and_cwd_are_forwarded():
    fake_run, calls = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    adapter.invoke("researcher", "do it", timeout_seconds=60, model="o3", cwd=Path("/repo"))

    argv, kwargs = calls[0]
    assert "-m" in argv and argv[argv.index("-m") + 1] == "o3"
    assert "-C" in argv and argv[argv.index("-C") + 1] == str(Path("/repo"))
    assert kwargs["cwd"] == str(Path("/repo"))


def test_provider_argument_raises_not_implemented():
    fake_run, _ = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    with pytest.raises(NotImplementedError):
        adapter.invoke("researcher", "do it", timeout_seconds=60, provider="anything")


def test_nonzero_exit_is_a_failed_status():
    fake_run, _ = _fake_run_writing_output_file(returncode=1, message="")
    adapter = CodexAdapter(run_subprocess=fake_run)

    result = adapter.invoke("researcher", "do it", timeout_seconds=60)

    assert result["status"] == "failed"


def test_timeout_returns_timed_out_status_and_echoes_session_id():
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 0))

    adapter = CodexAdapter(run_subprocess=fake_run)
    result = adapter.invoke("researcher", "do it", timeout_seconds=5, session_id="prior-id")

    assert result["status"] == "timed_out"
    assert result["session_id"] == "prior-id"


def test_missing_executable_raises_codex_invocation_error():
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("codex not found")

    adapter = CodexAdapter(run_subprocess=fake_run)
    with pytest.raises(CodexInvocationError):
        adapter.invoke("researcher", "do it", timeout_seconds=60)


def test_empty_prompt_is_rejected():
    adapter = CodexAdapter(run_subprocess=lambda *a, **k: None)
    with pytest.raises(ValueError):
        adapter.invoke("researcher", "", timeout_seconds=60)


def test_missing_thread_started_event_falls_back_to_prior_session_id():
    fake_run, _ = _fake_run_writing_output_file(stdout='{"type":"turn.completed"}\n')
    adapter = CodexAdapter(run_subprocess=fake_run)

    result = adapter.invoke("researcher", "do it", timeout_seconds=60, session_id="prior-id")

    assert result["session_id"] == "prior-id"


def test_fresh_call_missing_thread_started_event_returns_none_session_id():
    # A fresh call (no prior session_id to fall back to) whose JSONL stream
    # never emits thread.started -- accepted v1 behavior per the plan's
    # revision note: the call still succeeds, but the next REPL turn starts
    # a new conversation instead of resuming, since there is nothing to
    # resume with. Not silently wrong -- just degraded, and now covered.
    fake_run, _ = _fake_run_writing_output_file(stdout='{"type":"turn.completed"}\n')
    adapter = CodexAdapter(run_subprocess=fake_run)

    result = adapter.invoke("researcher", "do it", timeout_seconds=60)

    assert result["status"] == "succeeded"
    assert result["session_id"] is None


def test_falls_back_to_raw_stdout_when_output_file_is_empty():
    # Codex exits 0 but writes nothing to the -o file (e.g. a turn that
    # produced no final agent_message) -- stdout must still carry
    # something displayable rather than an empty string, matching
    # invoke_hermes's contract of stdout always being what the caller
    # should show.
    def fake_run(argv, **kwargs):
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_text("", encoding="utf-8")
        return _FakeCompletedProcess(0, stdout=_THREAD_STARTED + "raw fallback text\n")

    adapter = CodexAdapter(run_subprocess=fake_run)
    result = adapter.invoke("researcher", "do it", timeout_seconds=60)

    assert result["stdout"] == _THREAD_STARTED + "raw fallback text\n"


def test_default_codex_launch_prefix_resolves_node_and_codex_js_to_bypass_cmd_shim(monkeypatch, tmp_path):
    from runtime.adapters.codex_adapter import _default_codex_launch_prefix
    import runtime.adapters.codex_adapter as codex_adapter_module

    shim_dir = tmp_path / "npm"
    node_dir = shim_dir / "node_modules" / "@openai" / "codex" / "bin"
    node_dir.mkdir(parents=True)
    (node_dir / "codex.js").write_text("", encoding="utf-8")
    node_exe = shim_dir / "node.exe"
    node_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(codex_adapter_module.sys, "platform", "win32")
    monkeypatch.setattr(
        codex_adapter_module.shutil, "which",
        lambda name: str(shim_dir / "codex.cmd") if name == "codex.cmd" else None,
    )

    prefix = _default_codex_launch_prefix()

    assert prefix == [str(node_exe), str(node_dir / "codex.js")]


def test_default_codex_launch_prefix_falls_back_to_exe_when_node_layout_missing(monkeypatch):
    from runtime.adapters.codex_adapter import _default_codex_launch_prefix
    import runtime.adapters.codex_adapter as codex_adapter_module

    monkeypatch.setattr(codex_adapter_module.sys, "platform", "win32")
    monkeypatch.setattr(
        codex_adapter_module.shutil, "which",
        lambda name: r"C:\npm\codex.exe" if name == "codex.exe" else None,
    )

    assert _default_codex_launch_prefix() == [r"C:\npm\codex.exe"]


def test_default_codex_launch_prefix_never_falls_back_to_a_bat_shim(monkeypatch):
    # A .bat target has the exact same implicit-cmd.exe-routing risk this
    # function exists to close -- it must fall through to the bare "codex"
    # name rather than silently reopening the injection vector.
    from runtime.adapters.codex_adapter import _default_codex_launch_prefix
    import runtime.adapters.codex_adapter as codex_adapter_module

    monkeypatch.setattr(codex_adapter_module.sys, "platform", "win32")
    monkeypatch.setattr(
        codex_adapter_module.shutil, "which",
        lambda name: r"C:\npm\codex.bat" if name == "codex.bat" else None,
    )

    assert _default_codex_launch_prefix() == ["codex"]


def test_default_codex_launch_prefix_falls_back_to_bare_name_on_posix(monkeypatch):
    from runtime.adapters.codex_adapter import _default_codex_launch_prefix
    import runtime.adapters.codex_adapter as codex_adapter_module

    monkeypatch.setattr(codex_adapter_module.sys, "platform", "linux")

    assert _default_codex_launch_prefix() == ["codex"]


def test_fake_injected_run_subprocess_receives_logical_codex_argv_not_resolved_path():
    # The Windows executable-resolution only applies to the real
    # subprocess.run default (see _default_codex_executable) -- every
    # other test in this file injects a fake run_subprocess and asserts
    # argv[0] == "codex" literally, which this test makes explicit as its
    # own guarantee rather than an implicit side effect of the others.
    fake_run, calls = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    adapter.invoke("researcher", "do it", timeout_seconds=60)

    assert calls[0][0][0] == "codex"


def test_non_object_jsonl_lines_do_not_crash_thread_id_parsing():
    # A JSON scalar/array/null line (not an object) must not raise --
    # _parse_thread_id has to check the parsed value is a dict before
    # calling .get() on it.
    fake_run, _ = _fake_run_writing_output_file(
        stdout='"just a string"\n[1, 2, 3]\nnull\n{"type":"thread.started","thread_id":"real-id"}\n'
    )
    adapter = CodexAdapter(run_subprocess=fake_run)

    result = adapter.invoke("researcher", "do it", timeout_seconds=60)

    assert result["session_id"] == "real-id"
