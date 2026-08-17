"""Research-class tools consuming context_store references (spec beslut 5).
Reads only from an approved, already-copied-in fixture workspace, admitted
through ToolGate (path sandbox) and DataClassGate (Task 9) before any I/O —
same containment discipline as Fas 3's read/search tools.
"""
from __future__ import annotations

from pathlib import Path

from context_store.store import ContextReference
from runtime.tools.gate import DataClassGate, ToolGate


def list_fixture_documents(gate: ToolGate, document_set_locator: str) -> list[str]:
    doc_dir = gate.admit("list_fixture_documents", document_set_locator)
    return sorted(p.name for p in doc_dir.iterdir() if p.is_file())


def read_fixture_file_sliced(tool_gate: ToolGate, data_class_gate: DataClassGate,
                              ref: ContextReference) -> str:
    data_class_gate.admit("read_fixture_file_sliced", ref.data_class)
    resolved = tool_gate.admit("read_fixture_file_sliced", ref.locator)
    content = resolved.read_text(encoding="utf-8")
    start, end = ref.range
    return content[start:end]
