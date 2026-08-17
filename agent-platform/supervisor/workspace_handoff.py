"""M2 workspace handoff: reshape child 1's file_contents into Fas 3's
apply_patch changes schema and apply it to child 2's fresh copy-in workspace,
before child 2 starts. No new patch-application logic — Fas 3's apply_patch is
reused unmodified (design spec decision 5's "Implementation refinement").
"""
from __future__ import annotations

from pathlib import Path

from runtime.execution.write_policy import WriteCaps
from runtime.tools import WriteGate, apply_patch


def apply_incoming_changes(work_root: Path, file_contents: dict[str, str],
                           caps: WriteCaps) -> list[str]:
    work_root = Path(work_root)
    gate = WriteGate(allowed_roots=[work_root])
    changes = [{"path": path, "new_content": content} for path, content in file_contents.items()]
    return apply_patch(gate, work_root, changes, caps)
