"""apply_patch / diff_workspace: all-or-nothing writes, platform-computed diff.

Proving tests for the design spec's error-handling rows "Patch touches more
files than the cap" and "Patch exceeds max changed lines" — each asserts BOTH
that the call raised AND that every target file's bytes are unchanged.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from runtime.execution.write_policy import WriteCaps, WritePolicyViolation
from runtime.tools import PATCH_TOOL_MANIFESTS, PatchError, ToolAdmissionError, WriteGate, apply_patch, diff_workspace

BUGGY = "def sum_to(n):\n    total = 0\n    for i in range(1, n):\n        total += i\n    return total\n"
FIXED = "def sum_to(n):\n    total = 0\n    for i in range(1, n + 1):\n        total += i\n    return total\n"
TEST_FILE = "from ranges import sum_to\n\n\ndef test_sum_to_five():\n    assert sum_to(5) == 15\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    baseline = tmp_path / "baseline"
    work = tmp_path / "work"
    for root in (baseline, work):
        root.mkdir()
        (root / "ranges.py").write_text(BUGGY, encoding="utf-8")
        (root / "test_ranges.py").write_text(TEST_FILE, encoding="utf-8")
    return baseline, work


def test_apply_patch_writes_the_new_content(tmp_path):
    _, work = _workspace(tmp_path)
    gate = WriteGate(allowed_roots=[work])
    written = apply_patch(gate, work, [{"path": "ranges.py", "new_content": FIXED}], WriteCaps())
    assert written == ["ranges.py"]
    assert (work / "ranges.py").read_text(encoding="utf-8") == FIXED


def test_apply_patch_refuses_the_whole_patch_over_the_file_cap(tmp_path):
    _, work = _workspace(tmp_path)
    before = {p: _sha256(work / p) for p in ("ranges.py", "test_ranges.py")}
    gate = WriteGate(allowed_roots=[work])
    changes = [
        {"path": "ranges.py", "new_content": FIXED},
        {"path": "test_ranges.py", "new_content": "# neutered\n"},
    ]
    with pytest.raises(WritePolicyViolation) as exc:
        apply_patch(gate, work, changes, WriteCaps(max_files=1))
    assert exc.value.reason == "cap_max_files"
    assert {p: _sha256(work / p) for p in before} == before  # nothing written


def test_apply_patch_refuses_over_the_changed_line_cap_and_writes_nothing(tmp_path):
    _, work = _workspace(tmp_path)
    before = _sha256(work / "ranges.py")
    gate = WriteGate(allowed_roots=[work])
    oversized = "\n".join(f"# line {i}" for i in range(200)) + "\n"
    with pytest.raises(WritePolicyViolation) as exc:
        apply_patch(gate, work, [{"path": "ranges.py", "new_content": oversized}],
                    WriteCaps(max_changed_lines=20))
    assert exc.value.reason == "cap_max_changed_lines"
    assert _sha256(work / "ranges.py") == before


def test_apply_patch_refuses_over_the_byte_cap_and_writes_nothing(tmp_path):
    _, work = _workspace(tmp_path)
    before = _sha256(work / "ranges.py")
    gate = WriteGate(allowed_roots=[work])
    with pytest.raises(WritePolicyViolation) as exc:
        apply_patch(gate, work, [{"path": "ranges.py", "new_content": "x" * 100}],
                    WriteCaps(max_bytes_per_file=10))
    assert exc.value.reason == "cap_max_bytes"
    assert _sha256(work / "ranges.py") == before


def test_apply_patch_denies_traversal_before_any_write(tmp_path):
    _, work = _workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("PROTECTED\n", encoding="utf-8")
    before_outside = _sha256(outside)
    before_inside = _sha256(work / "ranges.py")
    gate = WriteGate(allowed_roots=[work])
    changes = [
        {"path": "ranges.py", "new_content": FIXED},
        {"path": "../outside.txt", "new_content": "PWNED\n"},
    ]
    with pytest.raises(ToolAdmissionError):
        apply_patch(gate, work, changes, WriteCaps(max_files=2))
    assert _sha256(outside) == before_outside
    assert _sha256(work / "ranges.py") == before_inside  # the valid change was not applied either


def test_apply_patch_rejects_a_malformed_changes_list(tmp_path):
    _, work = _workspace(tmp_path)
    gate = WriteGate(allowed_roots=[work])
    for bad in ([{"path": "ranges.py"}], [{"new_content": "x"}], ["ranges.py"], [{"path": 1, "new_content": "x"}]):
        with pytest.raises(PatchError) as exc:
            apply_patch(gate, work, bad, WriteCaps())
        assert exc.value.reason == "schema"


def test_apply_patch_rejects_an_absolute_path_in_changes(tmp_path):
    _, work = _workspace(tmp_path)
    gate = WriteGate(allowed_roots=[work])
    with pytest.raises(PatchError) as exc:
        apply_patch(gate, work, [{"path": str(work / "ranges.py"), "new_content": FIXED}], WriteCaps())
    assert exc.value.reason == "schema"


def test_diff_workspace_is_empty_before_any_change(tmp_path):
    baseline, work = _workspace(tmp_path)
    diff, changed = diff_workspace(baseline, work)
    assert diff == ""
    assert changed == []


def test_diff_workspace_reports_the_change_and_the_path(tmp_path):
    baseline, work = _workspace(tmp_path)
    (work / "ranges.py").write_text(FIXED, encoding="utf-8")
    diff, changed = diff_workspace(baseline, work)
    assert changed == ["ranges.py"]
    assert "-    for i in range(1, n):" in diff
    assert "+    for i in range(1, n + 1):" in diff
    assert "baseline/ranges.py" in diff and "work/ranges.py" in diff


def test_diff_workspace_uses_relative_posix_labels_not_host_paths(tmp_path):
    baseline, work = _workspace(tmp_path)
    (work / "ranges.py").write_text(FIXED, encoding="utf-8")
    diff, _ = diff_workspace(baseline, work)
    assert str(tmp_path) not in diff


def test_diff_workspace_reports_a_file_deleted_from_work(tmp_path):
    baseline, work = _workspace(tmp_path)
    (work / "test_ranges.py").unlink()
    _, changed = diff_workspace(baseline, work)
    assert changed == ["test_ranges.py"]


def test_manifests_declare_the_section_32_1_fields():
    assert PATCH_TOOL_MANIFESTS["apply_patch"]["effect_class"] == "local_mutation"
    assert PATCH_TOOL_MANIFESTS["diff_workspace"]["effect_class"] == "observe"
    for manifest in PATCH_TOOL_MANIFESTS.values():
        assert manifest["network"] == "none"
        assert manifest["credentials"] == []
