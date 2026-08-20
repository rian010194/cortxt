from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.adapters.claude_adapter import ClaudeAdapter, ClaudeInvocationError
from runtime.engine_adapter import EngineAdapter


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _json_result(session_id="a301f8d2-cd32-4df1-a6ae-57319f084a34", result="ok", is_error=False):
    return (
        '{"is_error":%s,"session_id":"%s","result":%s,"type":"result"}'
        % ("true" if is_error else "false", session_id, __import__("json").dumps(result))
    )


def _fake_run(stdout=None, returncode=0, stderr=""):
    calls = []
    if stdout is None:
        stdout = _json_result()

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _FakeCompletedProcess(returncode, stdout=stdout, stderr=stderr)

    return fake_run, calls


def test_claude_adapter_is_an_engine_adapter():
    assert isinstance(ClaudeAdapter(), EngineAdapter)


def test_fresh_call_builds_print_argv_without_resume():
    fake_run, calls = _fake_run()
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    result = adapter.invoke("", "do it", timeout_seconds=60)

    argv, kwargs = calls[0]
    assert argv[:2] == ["claude", "-p"]
    assert "--resume" not in argv
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert argv[-1] == "do it"
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert result["status"] == "succeeded"
    assert result["session_id"] == "a301f8d2-cd32-4df1-a6ae-57319f084a34"
    assert result["stdout"] == "ok"


def test_resume_call_includes_resume_flag_and_session_id():
    fake_run, calls = _fake_run()
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    adapter.invoke("", "continue", timeout_seconds=60, session_id="prior-session-id")

    argv, _ = calls[0]
    assert "--resume" in argv
    assert argv[argv.index("--resume") + 1] == "prior-session-id"


def test_profile_maps_to_agent_flag():
    fake_run, calls = _fake_run()
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    adapter.invoke("reviewer", "do it", timeout_seconds=60)

    argv, _ = calls[0]
    assert "--agent" in argv and argv[argv.index("--agent") + 1] == "reviewer"


def test_empty_profile_omits_agent_flag():
    fake_run, calls = _fake_run()
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    adapter.invoke("", "do it", timeout_seconds=60)

    argv, _ = calls[0]
    assert "--agent" not in argv


def test_model_and_cwd_are_forwarded():
    fake_run, calls = _fake_run()
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    adapter.invoke("", "do it", timeout_seconds=60, model="sonnet", cwd=Path("/repo"))

    argv, kwargs = calls[0]
    assert "--model" in argv and argv[argv.index("--model") + 1] == "sonnet"
    assert kwargs["cwd"] == str(Path("/repo"))
    # Unlike Codex, the Claude CLI has no "-C"-style cwd flag -- the
    # subprocess's own cwd kwarg is sufficient and no extra argv is added.
    assert "-C" not in argv


def test_provider_argument_raises_not_implemented():
    fake_run, _ = _fake_run()
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    with pytest.raises(NotImplementedError):
        adapter.invoke("", "do it", timeout_seconds=60, provider="anything")


def test_is_error_true_is_a_failed_status_even_with_zero_exit():
    fake_run, _ = _fake_run(stdout=_json_result(is_error=True, result="oops"))
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    result = adapter.invoke("", "do it", timeout_seconds=60)

    assert result["status"] == "failed"


def test_nonzero_exit_is_a_failed_status():
    fake_run, _ = _fake_run(returncode=1, stderr="boom")
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    result = adapter.invoke("", "do it", timeout_seconds=60)

    assert result["status"] == "failed"
    assert result["stderr"] == "boom"


def test_timeout_returns_timed_out_status_and_echoes_session_id():
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 0))

    adapter = ClaudeAdapter(run_subprocess=fake_run)
    result = adapter.invoke("", "do it", timeout_seconds=5, session_id="prior-id")

    assert result["status"] == "timed_out"
    assert result["session_id"] == "prior-id"


def test_missing_executable_raises_claude_invocation_error():
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("claude not found")

    adapter = ClaudeAdapter(run_subprocess=fake_run)
    with pytest.raises(ClaudeInvocationError):
        adapter.invoke("", "do it", timeout_seconds=60)


def test_empty_prompt_is_rejected():
    adapter = ClaudeAdapter(run_subprocess=lambda *a, **k: None)
    with pytest.raises(ValueError):
        adapter.invoke("", "", timeout_seconds=60)


def test_invalid_json_stdout_falls_back_to_raw_stdout_and_prior_session_id():
    fake_run, _ = _fake_run(stdout="not json at all")
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    result = adapter.invoke("", "do it", timeout_seconds=60, session_id="prior-id")

    assert result["status"] == "succeeded"
    assert result["stdout"] == "not json at all"
    assert result["session_id"] == "prior-id"


def test_invalid_json_stdout_with_nonzero_exit_is_failed():
    fake_run, _ = _fake_run(stdout="", returncode=1, stderr="crashed")
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    result = adapter.invoke("", "do it", timeout_seconds=60)

    assert result["status"] == "failed"


def test_fake_injected_run_subprocess_receives_logical_claude_argv_not_resolved_path():
    # Windows executable resolution only applies to the real subprocess.run
    # default -- every other test in this file injects a fake
    # run_subprocess and asserts argv[0] == "claude" literally; this test
    # makes that guarantee explicit rather than an implicit side effect.
    fake_run, calls = _fake_run()
    adapter = ClaudeAdapter(run_subprocess=fake_run)

    adapter.invoke("", "do it", timeout_seconds=60)

    assert calls[0][0][0] == "claude"


def test_default_claude_launch_prefix_resolves_node_and_script_to_bypass_cmd_shim(monkeypatch, tmp_path):
    from runtime.adapters.claude_adapter import _default_claude_launch_prefix
    import runtime.adapters.claude_adapter as claude_adapter_module

    shim_dir = tmp_path / "npm"
    script_dir = shim_dir / "node_modules" / "@anthropic-ai" / "claude-code"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "cli.js"
    script_path.write_text("", encoding="utf-8")
    node_exe = shim_dir / "node.exe"
    node_exe.write_text("", encoding="utf-8")
    shim_path = shim_dir / "claude.cmd"
    shim_path.write_text(
        '@ECHO off\r\n"%~dp0\\node.exe"  "%~dp0\\node_modules\\@anthropic-ai\\claude-code\\cli.js" %*\r\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(claude_adapter_module.sys, "platform", "win32")
    monkeypatch.setattr(
        claude_adapter_module.shutil, "which",
        lambda name: str(shim_path) if name == "claude.cmd" else None,
    )

    prefix = _default_claude_launch_prefix()

    assert prefix == [str(node_exe), str(script_path)]


def test_default_claude_launch_prefix_falls_back_to_exe_when_shim_layout_missing(monkeypatch):
    from runtime.adapters.claude_adapter import _default_claude_launch_prefix
    import runtime.adapters.claude_adapter as claude_adapter_module

    monkeypatch.setattr(claude_adapter_module.sys, "platform", "win32")
    monkeypatch.setattr(
        claude_adapter_module.shutil, "which",
        lambda name: r"C:\npm\claude.exe" if name == "claude.exe" else None,
    )

    assert _default_claude_launch_prefix() == [r"C:\npm\claude.exe"]


def test_default_claude_launch_prefix_never_falls_back_to_a_bat_shim(monkeypatch):
    # Same reasoning as Codex's equivalent guard: a .bat target has the
    # exact same implicit-cmd.exe-routing risk this function exists to
    # close, so it must fall through to the bare "claude" name rather than
    # silently reopening the injection vector.
    from runtime.adapters.claude_adapter import _default_claude_launch_prefix
    import runtime.adapters.claude_adapter as claude_adapter_module

    monkeypatch.setattr(claude_adapter_module.sys, "platform", "win32")
    monkeypatch.setattr(
        claude_adapter_module.shutil, "which",
        lambda name: r"C:\npm\claude.bat" if name == "claude.bat" else None,
    )

    assert _default_claude_launch_prefix() == ["claude"]


def test_default_claude_launch_prefix_falls_back_to_bare_name_on_posix(monkeypatch):
    from runtime.adapters.claude_adapter import _default_claude_launch_prefix
    import runtime.adapters.claude_adapter as claude_adapter_module

    monkeypatch.setattr(claude_adapter_module.sys, "platform", "linux")

    assert _default_claude_launch_prefix() == ["claude"]


def test_default_claude_launch_prefix_falls_back_to_bare_name_when_shim_script_unparseable(monkeypatch, tmp_path):
    # A .cmd shim exists but its content doesn't match the expected
    # npm-generated template (e.g. a hand-rolled or future-format shim) --
    # must not guess a script path, and must not fall back to launching the
    # .cmd itself (that would reopen the cmd.exe routing risk).
    from runtime.adapters.claude_adapter import _default_claude_launch_prefix
    import runtime.adapters.claude_adapter as claude_adapter_module

    shim_dir = tmp_path / "npm"
    shim_dir.mkdir(parents=True)
    node_exe = shim_dir / "node.exe"
    node_exe.write_text("", encoding="utf-8")
    shim_path = shim_dir / "claude.cmd"
    shim_path.write_text("@ECHO off\r\necho unexpected shim format\r\n", encoding="utf-8")

    monkeypatch.setattr(claude_adapter_module.sys, "platform", "win32")
    monkeypatch.setattr(
        claude_adapter_module.shutil, "which",
        lambda name: str(shim_path) if name == "claude.cmd" else None,
    )

    assert _default_claude_launch_prefix() == ["claude"]
