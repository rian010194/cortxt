"""Agent Runtime tool package.

Fas 2 shipped a single module ``runtime/tools.py``. Fas 3 converts it into a
package so the admission gate, the write policy and the subprocess launcher are
three separate trust boundaries in three separate files (design spec decision 2).
The conversion is a move plus a re-export — never a signature change. Fas 2's
import path ``from runtime.tools import ToolGate, ToolAdmissionError,
ToolExecutionError, read_fixture_file`` continues to work unchanged.
"""
from __future__ import annotations

from .fixtures import READ_FIXTURE_FILE_MANIFEST, read_fixture_file
from .gate import ToolAdmissionError, ToolExecutionError, ToolGate

__all__ = [
    "READ_FIXTURE_FILE_MANIFEST",
    "ToolAdmissionError",
    "ToolExecutionError",
    "ToolGate",
    "read_fixture_file",
]
