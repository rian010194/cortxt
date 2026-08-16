"""workspace_map: bounded, deterministic, hash-stable enumeration. No parsing."""
from __future__ import annotations
import hashlib
from pathlib import Path
import pytest
from runtime.coding.workspace_map import WorkspaceMapCaps, WorkspaceMapError, map_workspace


def _workspace(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / "ranges.py").write_text("def sum_to(n):\n    return 0\n", encoding="utf-8")
    (work / "test_ranges.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return work


def test_map_lists_files_sorted_with_relative_posix_paths(tmp_path):
    work = _workspace(tmp_path)
    result = map_workspace(work)
    assert [f["path"] for f in result["files"]] == ["ranges.py", "test_ranges.py"]
    assert result["file_count"] == 2


def test_map_records_size_hash_and_line_count(tmp_path):
    work = _workspace(tmp_path)
    result = map_workspace(work)
    entry = next(f for f in result["files"] if f["path"] == "ranges.py")
    raw = (work / "ranges.py").read_bytes()
    assert entry["size_bytes"] == len(raw)
    assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
    assert entry["line_count"] == 2
    assert result["total_bytes"] == sum(f["size_bytes"] for f in result["files"])


def test_map_is_deterministic_across_calls(tmp_path):
    work = _workspace(tmp_path)
    assert map_workspace(work) == map_workspace(work)


def test_map_output_contains_no_absolute_paths(tmp_path):
    work = _workspace(tmp_path)
    result = map_workspace(work)
    assert "root" not in result
    assert all(not Path(f["path"]).is_absolute() for f in result["files"])
    assert str(tmp_path) not in repr(result)


def test_map_descends_into_subdirectories_with_posix_separators(tmp_path):
    work = _workspace(tmp_path)
    (work / "pkg").mkdir()
    (work / "pkg" / "helper.py").write_text("X = 1\n", encoding="utf-8")
    result = map_workspace(work)
    assert "pkg/helper.py" in [f["path"] for f in result["files"]]


def test_map_excludes_files_outside_the_extension_allowlist(tmp_path):
    work = _workspace(tmp_path)
    (work / "blob.bin").write_bytes(b"\x00\x01\x02")
    result = map_workspace(work)
    assert "blob.bin" not in [f["path"] for f in result["files"]]


def test_map_refuses_when_file_count_cap_exceeded(tmp_path):
    work = _workspace(tmp_path)
    with pytest.raises(WorkspaceMapError) as exc:
        map_workspace(work, WorkspaceMapCaps(max_files=1))
    assert exc.value.reason == "cap_max_files"


def test_map_refuses_when_total_byte_cap_exceeded(tmp_path):
    work = _workspace(tmp_path)
    with pytest.raises(WorkspaceMapError) as exc:
        map_workspace(work, WorkspaceMapCaps(max_total_bytes=5))
    assert exc.value.reason == "cap_max_total_bytes"


def test_map_refuses_a_non_directory(tmp_path):
    work = _workspace(tmp_path)
    with pytest.raises(WorkspaceMapError) as exc:
        map_workspace(work / "ranges.py")
    assert exc.value.reason == "not_a_directory"
