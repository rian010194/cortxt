"""WriteGate boundary-attempt suite — the literal evidence for "workspace-tak
maskinellt bevisat" (design spec decision 7, Workspace row).

Every test performs a REAL escape attempt against a REAL file and asserts both
that the attempt raised AND that the protected file's bytes are unchanged.
Asserting only that an exception was raised would prove the code raised, not
that nothing happened. The "outside" target is always inside tmp_path, so a bug
in the code under test can only damage a temp dir this test owns.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import pytest
from runtime.tools import ToolAdmissionError, WriteGate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Return (workspace_root, outside_file). outside_file is a sibling of the root."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "ranges.py").write_text("def sum_to(n):\n    return 0\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("PROTECTED CONTENT\n", encoding="utf-8")
    return work, outside


def test_admit_accepts_existing_file_inside_workspace(tmp_path):
    work, _ = _workspace(tmp_path)
    gate = WriteGate(allowed_roots=[work])
    assert gate.admit("apply_patch", str(work / "ranges.py")) == (work / "ranges.py").resolve()


def test_admit_rejects_traversal_and_leaves_target_untouched(tmp_path):
    work, outside = _workspace(tmp_path)
    before = _sha256(outside)
    gate = WriteGate(allowed_roots=[work])
    with pytest.raises(ToolAdmissionError):
        gate.admit("apply_patch", str(work / ".." / "outside.txt"))
    assert _sha256(outside) == before


def test_admit_rejects_absolute_path_outside_and_leaves_target_untouched(tmp_path):
    work, outside = _workspace(tmp_path)
    before = _sha256(outside)
    gate = WriteGate(allowed_roots=[work])
    with pytest.raises(ToolAdmissionError):
        gate.admit("apply_patch", str(outside.resolve()))
    assert _sha256(outside) == before


def test_admit_rejects_nonexistent_file(tmp_path):
    work, _ = _workspace(tmp_path)
    gate = WriteGate(allowed_roots=[work])
    with pytest.raises(ToolAdmissionError):
        gate.admit("apply_patch", str(work / "does_not_exist.py"))


def test_admit_rejects_directory(tmp_path):
    work, _ = _workspace(tmp_path)
    (work / "pkg").mkdir()
    gate = WriteGate(allowed_roots=[work])
    with pytest.raises(ToolAdmissionError):
        gate.admit("apply_patch", str(work / "pkg"))


def _can_symlink(tmp_path: Path) -> bool:
    probe = tmp_path / "_symlink_probe"
    target = tmp_path / "_symlink_target"
    target.write_text("x", encoding="utf-8")
    try:
        os.symlink(target, probe)
    except (OSError, NotImplementedError, AttributeError):
        return False
    probe.unlink()
    return True


def test_admit_rejects_symlink_pointing_outside_and_leaves_target_untouched(tmp_path):
    work, outside = _workspace(tmp_path)
    if not _can_symlink(tmp_path):
        pytest.skip(
            "symlink creation requires privileges (Windows without developer mode) — "
            "BOUNDARY TEST NOT VERIFIED IN THIS ENVIRONMENT; must pass in CI (Ubuntu)"
        )
    link = work / "escape.txt"
    os.symlink(outside, link)
    before = _sha256(outside)
    gate = WriteGate(allowed_roots=[work])
    with pytest.raises(ToolAdmissionError):
        gate.admit("apply_patch", str(link))
    assert _sha256(outside) == before


def test_admit_rejects_symlink_even_when_it_points_back_inside(tmp_path):
    """Post-resolution containment alone would ACCEPT this; is_symlink() must reject it.

    Proves the two checks are independent, not one check written twice.
    """
    work, _ = _workspace(tmp_path)
    if not _can_symlink(tmp_path):
        pytest.skip(
            "symlink creation requires privileges (Windows without developer mode) — "
            "BOUNDARY TEST NOT VERIFIED IN THIS ENVIRONMENT; must pass in CI (Ubuntu)"
        )
    link = work / "alias.py"
    os.symlink(work / "ranges.py", link)
    gate = WriteGate(allowed_roots=[work])
    with pytest.raises(ToolAdmissionError):
        gate.admit("apply_patch", str(link))
