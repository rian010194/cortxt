"""Tool admission gate for Agent Runtime.

Every tool call is admitted (path-sandboxed to explicitly allowed roots,
no traversal) before it runs — a denied admission never reaches disk I/O,
so no cost or side effect occurs for an invalid attempt.
"""
from __future__ import annotations

from pathlib import Path


class ToolAdmissionError(Exception):
    pass


class ToolExecutionError(Exception):
    """Raised when an admitted tool call fails to execute (e.g. read/parse failure),
    as distinct from ToolAdmissionError which is reserved for the admission gate's
    own rejection (path outside sandbox, traversal, missing file)."""


class ToolGate:
    def __init__(self, allowed_roots: list[Path]) -> None:
        self._roots = [Path(r).resolve() for r in allowed_roots]

    def admit(self, tool_name: str, path: str) -> Path:
        candidate = Path(path)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise ToolAdmissionError(f"{tool_name}: path does not exist: {path}") from error
        for root in self._roots:
            if resolved == root or root in resolved.parents:
                return resolved
        raise ToolAdmissionError(f"{tool_name}: path outside allowed roots: {resolved}")


class WriteGate(ToolGate):
    """Admission gate for local_mutation tools (design spec decision 4, part 2).

    Stricter than ToolGate in three ways, all fail-closed and all checked
    before any file handle is opened:

    1. the pre-resolution path must NOT be a symlink (``Path.is_symlink()``),
       so a symlink planted inside the workspace cannot be used as a hop —
       this is checked independently of (3), not as a restatement of it;
    2. the resolved path must already exist AND be a regular file — v0.1 has
       no file creation and no file deletion (design spec decision 4);
    3. the resolved path must be contained in an allowed root (inherited).
    """

    def admit(self, tool_name: str, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_symlink():
            raise ToolAdmissionError(f"{tool_name}: path is a symlink: {path}")
        resolved = super().admit(tool_name, path)
        if not resolved.is_file():
            raise ToolAdmissionError(f"{tool_name}: path is not a regular file: {resolved}")
        return resolved
