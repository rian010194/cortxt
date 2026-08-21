"""Import-path continuity for the tools.py -> tools/ package move (Phase 3 Task 1).

The move must be behaviour-preserving: every name Phase 2 exported from
runtime.tools must still be importable from runtime.tools, AND from its new
submodule, AND be the same object in both places.
"""
from __future__ import annotations

import runtime.tools as pkg
from runtime.tools import ToolAdmissionError, ToolExecutionError, ToolGate, read_fixture_file
from runtime.tools.fixtures import read_fixture_file as fixtures_read
from runtime.tools.gate import ToolAdmissionError as gate_admission
from runtime.tools.gate import ToolExecutionError as gate_execution
from runtime.tools.gate import ToolGate as gate_class


def test_tools_is_a_package_not_a_module():
    assert hasattr(pkg, "__path__"), "runtime.tools must be a package after the move"


def test_reexports_are_the_same_objects_as_the_submodules():
    assert ToolGate is gate_class
    assert ToolAdmissionError is gate_admission
    assert ToolExecutionError is gate_execution
    assert read_fixture_file is fixtures_read


def test_admission_error_and_execution_error_are_distinct_types():
    assert not issubclass(ToolExecutionError, ToolAdmissionError)
    assert not issubclass(ToolAdmissionError, ToolExecutionError)
