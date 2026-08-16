"""Workspace observe-class tools: gated, capped, literal-substring search."""
from __future__ import annotations

from pathlib import Path

import pytest

from runtime.tools import (
    WORKSPACE_TOOL_MANIFESTS,
    ToolAdmissionError,
    ToolExecutionError,
    ToolGate,
    list_workspace,
    read_workspace_file,
    search_workspace,
)


def _workspace(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / "ranges.py").write_text(
        "def sum_to(n):\n    total = 0\n    for i in range(1, n):\n        total += i\n    return total\n",
        encoding="utf-8",
    )
    (work / "test_ranges.py").write_text(
        "from ranges import sum_to\n\n\ndef test_sum_to_five():\n    assert sum_to(5) == 15\n",
        encoding="utf-8",
    )
    return work


def test_list_workspace_returns_sorted_relative_posix_paths(tmp_path):
    work = _workspace(tmp_path)
    gate = ToolGate(allowed_roots=[work])
    assert list_workspace(gate, str(work)) == ["ranges.py", "test_ranges.py"]


def test_list_workspace_rejects_a_root_outside_the_gate(tmp_path):
    work = _workspace(tmp_path)
    gate = ToolGate(allowed_roots=[work])
    with pytest.raises(ToolAdmissionError):
        list_workspace(gate, str(tmp_path))


def test_read_workspace_file_returns_text(tmp_path):
    work = _workspace(tmp_path)
    gate = ToolGate(allowed_roots=[work])
    assert "def sum_to(n):" in read_workspace_file(gate, str(work / "ranges.py"))


def test_read_workspace_file_rejects_admission_before_reading(tmp_path):
    work = _workspace(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET\n", encoding="utf-8")
    gate = ToolGate(allowed_roots=[work])
    with pytest.raises(ToolAdmissionError):
        read_workspace_file(gate, str(outside))


def test_read_workspace_file_refuses_a_file_over_the_byte_cap(tmp_path):
    work = _workspace(tmp_path)
    gate = ToolGate(allowed_roots=[work])
    with pytest.raises(ToolExecutionError):
        read_workspace_file(gate, str(work / "ranges.py"), max_bytes=10)


def test_search_workspace_finds_literal_substring_with_line_numbers(tmp_path):
    work = _workspace(tmp_path)
    gate = ToolGate(allowed_roots=[work])
    hits = search_workspace(gate, str(work), "range(1, n)")
    assert hits == [{"path": "ranges.py", "line_number": 3, "line": "    for i in range(1, n):"}]


def test_search_workspace_treats_the_needle_as_literal_not_regex(tmp_path):
    work = _workspace(tmp_path)
    gate = ToolGate(allowed_roots=[work])
    assert search_workspace(gate, str(work), "d.f sum_to") == []


def test_search_workspace_caps_result_count_and_line_length(tmp_path):
    work = _workspace(tmp_path)
    (work / "wide.py").write_text("X = '" + "a" * 500 + "'\n", encoding="utf-8")
    gate = ToolGate(allowed_roots=[work])
    hits = search_workspace(gate, str(work), "a", max_results=1, max_line_length=20)
    assert len(hits) == 1
    assert len(hits[0]["line"]) <= 20


def test_manifests_declare_the_section_32_1_fields():
    for name in ("list_workspace", "read_workspace_file", "search_workspace"):
        manifest = WORKSPACE_TOOL_MANIFESTS[name]
        assert manifest["effect_class"] == "observe"
        assert manifest["network"] == "none"
        assert manifest["credentials"] == []
        assert set(manifest) >= {
            "id", "version", "effect_class", "filesystem", "network",
            "credentials", "timeout_seconds", "idempotency", "artifact_policy",
        }
