"""Tool admission gate for Agent Runtime's read-only research profile.

Every tool call is admitted (path-sandboxed to explicitly allowed roots,
no traversal) before it runs — a denied admission never reaches disk I/O,
so no cost or side effect occurs for an invalid attempt.
"""
from __future__ import annotations

import json
from pathlib import Path


class ToolAdmissionError(Exception):
    pass


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


def read_fixture_file(gate: ToolGate, path: str) -> dict:
    resolved = gate.admit("read_fixture_file", path)
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError) as error:
        raise ToolAdmissionError(f"read_fixture_file: could not read/parse {resolved}") from error
