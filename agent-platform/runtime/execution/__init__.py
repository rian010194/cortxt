"""Execution subpackage for the Phase 3 coding runtime.

Holds the pure write-policy functions (Task 3) and the container-backed
``ExecutionSandbox`` (Task 8). This ``__init__.py`` is required for
``runtime.execution`` to be importable as a package; it is not listed
explicitly among Task 8's files in the plan, but the module path
``runtime.execution.subprocess_sandbox`` the plan specifies cannot exist
without it.
"""
from __future__ import annotations
