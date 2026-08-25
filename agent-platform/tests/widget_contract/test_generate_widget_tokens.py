"""scripts/generate_widget_tokens.py -- site/public/widgets/tokens.json must
be a mechanically generated copy of the platform-owned tokens.json, not a
hand-maintained second copy (issue #373 acceptance criteria)."""
from __future__ import annotations

import importlib.util
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


def _load_script_module():
    """Import generate_widget_tokens.py as a module, in-process.

    Used only by tests that need to monkeypatch its SOURCE_PATH/GENERATED_PATH
    module globals so the script's file I/O lands in tmp_path instead of the
    real tracked repo files -- subprocess invocation can't be monkeypatched
    from the test process, so those tests call main() directly instead.
    """
    spec = importlib.util.spec_from_file_location("generate_widget_tokens", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_script_exists():
    assert SCRIPT_PATH.is_file()


def test_check_mode_passes_when_generated_file_matches_source():
    # The repo is expected to be committed with the generated file already
    # in sync with its source.
    result = _run(["--check"])
    assert result.returncode == 0, result.stderr
    assert "up to date" in result.stdout


def test_check_mode_fails_when_generated_file_is_stale(tmp_path, monkeypatch):
    module = _load_script_module()
    source_path = tmp_path / "source-tokens.json"
    generated_path = tmp_path / "generated-tokens.json"
    source_path.write_text(SOURCE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    generated_path.write_text(source_path.read_text(encoding="utf-8") + "\n// stale\n", encoding="utf-8")

    monkeypatch.setattr(module, "SOURCE_PATH", source_path)
    monkeypatch.setattr(module, "GENERATED_PATH", generated_path)

    assert module.main(["--check"]) == 1


def test_regenerate_writes_byte_identical_copy(tmp_path, monkeypatch):
    module = _load_script_module()
    source_path = tmp_path / "source-tokens.json"
    generated_path = tmp_path / "generated-tokens.json"
    source_path.write_text(SOURCE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    generated_path.write_text(source_path.read_text(encoding="utf-8") + "\n// stale\n", encoding="utf-8")

    monkeypatch.setattr(module, "SOURCE_PATH", source_path)
    monkeypatch.setattr(module, "GENERATED_PATH", generated_path)

    assert module.main([]) == 0
    assert generated_path.read_text(encoding="utf-8") == source_path.read_text(encoding="utf-8")
