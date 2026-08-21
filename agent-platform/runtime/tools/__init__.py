"""Agent Runtime tool package.

Phase 2 shipped a single module ``runtime/tools.py``. Phase 3 converts it into a
package so the admission gate, the write policy and the subprocess launcher are
three separate trust boundaries in three separate files (design spec decision 2).
The conversion is a move plus a re-export — never a signature change. Phase 2's
import path ``from runtime.tools import ToolGate, ToolAdmissionError,
ToolExecutionError, read_fixture_file`` continues to work unchanged.
"""
from __future__ import annotations

from .execution import RUN_TESTS_MANIFEST, run_tests
from .fixtures import READ_FIXTURE_FILE_MANIFEST, read_fixture_file
from .gate import ToolAdmissionError, ToolExecutionError, ToolGate, WriteGate
from .patch import PATCH_TOOL_MANIFESTS, PatchError, apply_patch, diff_workspace
from .workspace import (
    WORKSPACE_TOOL_MANIFESTS,
    list_workspace,
    read_workspace_file,
    search_workspace,
)

__all__ = [
    "PATCH_TOOL_MANIFESTS",
    "READ_FIXTURE_FILE_MANIFEST",
    "RUN_TESTS_MANIFEST",
    "WORKSPACE_TOOL_MANIFESTS",
    "PatchError",
    "ToolAdmissionError",
    "ToolExecutionError",
    "ToolGate",
    "WriteGate",
    "apply_patch",
    "diff_workspace",
    "list_workspace",
    "read_fixture_file",
    "read_workspace_file",
    "run_tests",
    "search_workspace",
]
