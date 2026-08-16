"""Fixture-reading tool (Fas 2, moved unchanged into the tools package)."""
from __future__ import annotations
import json
from .gate import ToolExecutionError, ToolGate


def read_fixture_file(gate: ToolGate, path: str) -> dict:
    resolved = gate.admit("read_fixture_file", path)
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError) as error:
        raise ToolExecutionError(f"read_fixture_file: could not read/parse {resolved}") from error


READ_FIXTURE_FILE_MANIFEST = {
    "id": "repository.read_fixture_file",
    "version": "1.0.0",
    "effect_class": "observe",
    "filesystem": "allowed-roots",
    "network": "none",
    "credentials": [],
    "timeout_seconds": 10,
    "idempotency": "repeatable",
    "artifact_policy": "result-only",
}
