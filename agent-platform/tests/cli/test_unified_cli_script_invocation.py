"""Regression guard: pytest's own pyproject.toml pythonpath config
(`pythonpath = [".", ".."]`) puts agent-platform on sys.path automatically,
which masked a real bug -- _run_dispatch and _run_widget imported
`routing`/`runtime`/`widget` without bootstrapping agent-platform onto
sys.path themselves, so a bare `python cli/unified_cli.py dispatch ...`
invocation (no pytest, no installed package) failed with
ModuleNotFoundError. Caught by manual smoke testing, not by the mocked
unit tests. These tests run the CLI as a real subprocess, the same way an
operator or a script would, so this class of bug can't hide behind
pytest's own path setup again.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CLI_PATH = Path(__file__).parent.parent.parent / "cli" / "unified_cli.py"


def _run_as_bare_script(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_dispatch_does_not_modulenotfounderror_as_a_bare_script(tmp_path):
    result = _run_as_bare_script(
        [
            "dispatch",
            "--tags", "widget-ui",
            "--task-id", "bare-script-smoke-test",
            "--prompt", "n/a",
            "--store", str(tmp_path / "sessions"),
        ],
        cwd=tmp_path,
    )
    assert "ModuleNotFoundError" not in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


def test_sessions_does_not_modulenotfounderror_as_a_bare_script(tmp_path):
    result = _run_as_bare_script(
        ["sessions", "--store", str(tmp_path / "sessions"), "--snapshot", str(tmp_path / "snapshot.json")],
        cwd=tmp_path,
    )
    assert "ModuleNotFoundError" not in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
