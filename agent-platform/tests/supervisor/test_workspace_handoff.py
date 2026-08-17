from __future__ import annotations

import pytest

from runtime.execution.write_policy import WriteCaps, WritePolicyViolation
from supervisor.workspace_handoff import apply_incoming_changes


def test_applies_incoming_file_contents_to_an_existing_file(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "ranges.py").write_text("def sum_to(n):\n    return 0\n", encoding="utf-8")

    written = apply_incoming_changes(
        work_root=work_root,
        file_contents={"ranges.py": "def sum_to(n):\n    return n\n"},
        caps=WriteCaps(max_files=1, max_bytes_per_file=1024, max_changed_lines=10, max_executions=4),
    )

    assert written == ["ranges.py"]
    assert (work_root / "ranges.py").read_text(encoding="utf-8") == "def sum_to(n):\n    return n\n"


def test_raises_when_incoming_changes_exceed_caps(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "ranges.py").write_text("x = 1\n", encoding="utf-8")
    (work_root / "stats.py").write_text("y = 2\n", encoding="utf-8")

    with pytest.raises((WritePolicyViolation, Exception)):
        apply_incoming_changes(
            work_root=work_root,
            file_contents={"ranges.py": "x = 2\n", "stats.py": "y = 3\n"},
            caps=WriteCaps(max_files=1, max_bytes_per_file=1024, max_changed_lines=10, max_executions=4),
        )
