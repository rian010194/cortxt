"""Observe-class workspace tools (design spec decision 2).

Every call is admitted through the gate before any disk I/O. Search is literal
substring matching, never a regex — a model-supplied regex is an unbounded
backtracking risk and v0.1 has no fixture that needs one.
"""
from __future__ import annotations

from .gate import ToolExecutionError, ToolGate

WORKSPACE_TOOL_MANIFESTS: dict[str, dict] = {
    "list_workspace": {
        "id": "repository.list_workspace",
        "version": "1.0.0",
        "effect_class": "observe",
        "filesystem": "current-run-workspace",
        "network": "none",
        "credentials": [],
        "timeout_seconds": 10,
        "idempotency": "repeatable",
        "artifact_policy": "result-only",
    },
    "read_workspace_file": {
        "id": "repository.read_workspace_file",
        "version": "1.0.0",
        "effect_class": "observe",
        "filesystem": "current-run-workspace",
        "network": "none",
        "credentials": [],
        "timeout_seconds": 10,
        "idempotency": "repeatable",
        "artifact_policy": "result-only",
    },
    "search_workspace": {
        "id": "repository.search_workspace",
        "version": "1.0.0",
        "effect_class": "observe",
        "filesystem": "current-run-workspace",
        "network": "none",
        "credentials": [],
        "timeout_seconds": 30,
        "idempotency": "repeatable",
        "artifact_policy": "result-only",
    },
}


def list_workspace(gate: ToolGate, root: str) -> list[str]:
    resolved = gate.admit("list_workspace", root)
    return sorted(
        p.relative_to(resolved).as_posix()
        for p in resolved.rglob("*")
        if p.is_file() and not p.is_symlink()
    )


def read_workspace_file(gate: ToolGate, path: str, max_bytes: int = 65536) -> str:
    resolved = gate.admit("read_workspace_file", path)
    try:
        raw = resolved.read_bytes()
    except OSError as error:
        raise ToolExecutionError(f"read_workspace_file: could not read {resolved}") from error
    if len(raw) > max_bytes:
        raise ToolExecutionError(
            f"read_workspace_file: {resolved} is {len(raw)} bytes, cap is {max_bytes}"
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ToolExecutionError(f"read_workspace_file: {resolved} is not valid UTF-8") from error


def search_workspace(gate: ToolGate, root: str, needle: str, max_results: int = 50,
                     max_line_length: int = 200) -> list[dict]:
    resolved = gate.admit("search_workspace", root)
    hits: list[dict] = []
    for path in sorted(resolved.rglob("*"), key=lambda p: p.relative_to(resolved).as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line:
                hits.append({
                    "path": path.relative_to(resolved).as_posix(),
                    "line_number": number,
                    "line": line[:max_line_length],
                })
                if len(hits) >= max_results:
                    return hits
    return hits
