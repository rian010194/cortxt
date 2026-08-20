from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from subprocess_windows import no_window_kwargs


def test_unique_entrypoint_survives_a_conflicting_cli_module(tmp_path):
    (tmp_path / "cli.py").write_text("VALUE = 'third-party collision'\n", encoding="utf-8")
    agent_platform = Path(__file__).parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(agent_platform), str(tmp_path)])
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import cortxt_entrypoint; "
                "raise SystemExit(cortxt_entrypoint.main(['sessions', '--store', r'"
                + str(tmp_path / "sessions")
                + "', '--snapshot', r'"
                + str(tmp_path / "snapshot.json")
                + "']))"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        **no_window_kwargs(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ModuleNotFoundError" not in result.stderr
