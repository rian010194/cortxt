"""Bounded write policy — pure functions over a patch and its diff.

No I/O whatsoever, so every rule here is trivially testable (design spec
Components table). Everything is fail-closed: an empty scope allowlist admits
nothing, and a cap check refuses the whole patch rather than partially applying
it.

Scope globs use ``fnmatch.fnmatchcase`` semantics, in which ``*`` crosses ``/``.
That is adequate for v0.1's single-directory fixture; a multi-directory fixture
should revisit the dialect rather than assume it.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from fnmatch import fnmatchcase


class WritePolicyViolation(Exception):
    """A fail-closed refusal with a machine-readable reason."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class WriteCaps:
    max_files: int = 1
    max_bytes_per_file: int = 16384
    max_changed_lines: int = 20
    max_executions: int = 4

    @classmethod
    def from_mapping(cls, mapping: dict | None) -> "WriteCaps":
        if not mapping:
            return cls()
        known = {"max_files", "max_bytes_per_file", "max_changed_lines", "max_executions"}
        return cls(**{k: int(v) for k, v in mapping.items() if k in known})


def changed_line_count(old_text: str, new_text: str) -> int:
    """Lines added plus lines removed between two texts (both sides counted)."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    total = 0
    for line in difflib.ndiff(old_lines, new_lines):
        if line[:1] in ("+", "-"):
            total += 1
    return total


def count_changed_lines(diff_text: str) -> int:
    """Count +/- lines in a unified diff, excluding the ---/+++ file headers."""
    total = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            total += 1
    return total


def check_file_count(paths: list[str], caps: WriteCaps) -> None:
    unique = set(paths)
    if len(unique) != len(paths):
        raise WritePolicyViolation("cap_max_files", f"duplicate paths in patch: {sorted(paths)}")
    if len(unique) > caps.max_files:
        raise WritePolicyViolation(
            "cap_max_files", f"patch touches {len(unique)} files, cap is {caps.max_files}"
        )


def check_file_size(path: str, new_content: str, caps: WriteCaps) -> None:
    size = len(new_content.encode("utf-8"))
    if size > caps.max_bytes_per_file:
        raise WritePolicyViolation(
            "cap_max_bytes", f"{path} would be {size} bytes, cap is {caps.max_bytes_per_file}"
        )


def check_changed_lines(total: int, caps: WriteCaps) -> None:
    if total > caps.max_changed_lines:
        raise WritePolicyViolation(
            "cap_max_changed_lines",
            f"patch changes {total} lines, cap is {caps.max_changed_lines}",
        )


def check_execution_count(used: int, caps: WriteCaps) -> None:
    if used >= caps.max_executions:
        raise WritePolicyViolation(
            "cap_max_executions",
            f"sandbox executions used {used}, cap is {caps.max_executions}",
        )


def out_of_scope_paths(paths: list[str], scope_globs: list[str]) -> list[str]:
    return sorted(p for p in paths if not any(fnmatchcase(p, g) for g in scope_globs))


def check_scope(paths: list[str], scope_globs: list[str]) -> None:
    outside = out_of_scope_paths(paths, scope_globs)
    if outside:
        raise WritePolicyViolation(
            "scope_expansion",
            f"diff touches paths outside the declared scope {scope_globs}: {outside}",
        )
