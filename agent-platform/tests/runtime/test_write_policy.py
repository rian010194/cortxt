"""write_policy: pure fail-closed caps and scope checks, no I/O.

Proving tests for the design spec's error-handling rows "Patch touches more
files than the cap", "Patch exceeds max changed lines", "Max sandbox executions
per run exceeded" and the pure half of "Diff touches a path outside the
declared scope".
"""
from __future__ import annotations
import pytest
from runtime.execution.write_policy import (
    WriteCaps,
    WritePolicyViolation,
    changed_line_count,
    check_changed_lines,
    check_execution_count,
    check_file_count,
    check_file_size,
    check_scope,
    count_changed_lines,
    out_of_scope_paths,
)


def test_defaults_are_conservative():
    caps = WriteCaps()
    assert (caps.max_files, caps.max_bytes_per_file, caps.max_changed_lines, caps.max_executions) == (
        1, 16384, 20, 4,
    )


def test_from_mapping_overrides_and_ignores_unknown_keys():
    caps = WriteCaps.from_mapping({"max_files": 3, "max_executions": 9, "nonsense": True})
    assert caps.max_files == 3
    assert caps.max_executions == 9
    assert caps.max_bytes_per_file == 16384


def test_from_mapping_none_yields_defaults():
    assert WriteCaps.from_mapping(None) == WriteCaps()


def test_check_file_count_rejects_over_cap():
    with pytest.raises(WritePolicyViolation) as exc:
        check_file_count(["a.py", "b.py"], WriteCaps(max_files=1))
    assert exc.value.reason == "cap_max_files"


def test_check_file_count_rejects_duplicate_paths():
    with pytest.raises(WritePolicyViolation) as exc:
        check_file_count(["a.py", "a.py"], WriteCaps(max_files=2))
    assert exc.value.reason == "cap_max_files"


def test_check_file_size_rejects_over_cap():
    with pytest.raises(WritePolicyViolation) as exc:
        check_file_size("a.py", "x" * 100, WriteCaps(max_bytes_per_file=10))
    assert exc.value.reason == "cap_max_bytes"


def test_check_file_size_measures_utf8_bytes_not_characters():
    # "å" is 2 bytes in UTF-8; 6 characters would pass a naive len() check.
    with pytest.raises(WritePolicyViolation):
        check_file_size("a.py", "åååååå", WriteCaps(max_bytes_per_file=11))


def test_changed_line_count_counts_both_sides():
    old = "a\nb\nc\n"
    new = "a\nB\nc\n"
    assert changed_line_count(old, new) == 2  # one removed, one added


def test_changed_line_count_is_zero_for_identical_text():
    assert changed_line_count("a\nb\n", "a\nb\n") == 0


def test_count_changed_lines_ignores_diff_headers():
    diff = (
        "--- baseline/ranges.py\n"
        "+++ work/ranges.py\n"
        "@@ -1,3 +1,3 @@\n"
        "def sum_to(n):\n"
        "-    for i in range(1, n):\n"
        "+    for i in range(1, n + 1):\n"
    )
    assert count_changed_lines(diff) == 2


def test_check_changed_lines_rejects_over_cap():
    with pytest.raises(WritePolicyViolation) as exc:
        check_changed_lines(21, WriteCaps(max_changed_lines=20))
    assert exc.value.reason == "cap_max_changed_lines"


def test_check_execution_count_rejects_at_cap():
    check_execution_count(3, WriteCaps(max_executions=4))
    with pytest.raises(WritePolicyViolation) as exc:
        check_execution_count(4, WriteCaps(max_executions=4))
    assert exc.value.reason == "cap_max_executions"


def test_out_of_scope_paths_reports_only_the_violations():
    assert out_of_scope_paths(["ranges.py", "test_ranges.py"], ["ranges.py"]) == ["test_ranges.py"]
    assert out_of_scope_paths(["ranges.py"], ["*.py"]) == []


def test_check_scope_raises_with_scope_expansion_reason():
    with pytest.raises(WritePolicyViolation) as exc:
        check_scope(["test_ranges.py"], ["ranges.py"])
    assert exc.value.reason == "scope_expansion"
    assert "test_ranges.py" in exc.value.message


def test_empty_scope_globs_deny_everything():
    """Fail-closed: an empty allowlist admits nothing, it does not admit all."""
    assert out_of_scope_paths(["ranges.py"], []) == ["ranges.py"]
