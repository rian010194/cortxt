"""scripts/generate_widget_tokens.py -- site/public/widgets/tokens.json must
be a mechanically generated copy of the platform-owned tokens.json, not a
hand-maintained second copy (issue #373 acceptance criteria)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from subprocess_windows import no_window_kwargs

REPO = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO / "scripts" / "generate_widget_tokens.py"
SOURCE_PATH = REPO / "agent-platform" / "widget" / "tokens.json"
GENERATED_PATH = REPO / "site" / "public" / "widgets" / "tokens.json"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        **no_window_kwargs(),
    )


def test_script_exists():
    assert SCRIPT_PATH.is_file()


def test_check_mode_passes_when_generated_file_matches_source():
    # The repo is expected to be committed with the generated file already
    # in sync with its source.
    result = _run(["--check"])
    assert result.returncode == 0, result.stderr
    assert "up to date" in result.stdout


def test_check_mode_fails_when_generated_file_is_stale(tmp_path):
    original = GENERATED_PATH.read_text(encoding="utf-8")
    try:
        GENERATED_PATH.write_text(original + "\n// stale\n", encoding="utf-8")
        result = _run(["--check"])
        assert result.returncode == 1
        assert "stale" in result.stderr
    finally:
        GENERATED_PATH.write_text(original, encoding="utf-8")


def test_regenerate_writes_byte_identical_copy(tmp_path):
    original = GENERATED_PATH.read_text(encoding="utf-8")
    try:
        GENERATED_PATH.write_text(original + "\n// stale\n", encoding="utf-8")
        result = _run([])
        assert result.returncode == 0, result.stderr
        assert GENERATED_PATH.read_text(encoding="utf-8") == SOURCE_PATH.read_text(encoding="utf-8")
    finally:
        GENERATED_PATH.write_text(original, encoding="utf-8")
