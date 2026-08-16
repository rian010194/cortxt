"""The only bounded_execution tool in v0.1 (design spec decision 2).

Deliberately thin: it names the allowlisted command id and delegates. All the
bounds — argv allowlist, pinned workdir, scrubbed env, timeout, output cap,
--network none — live in ExecutionSandbox, one layer down, where they are
tested in isolation. A tool that carried its own bounds would be a second place
to get them wrong.

The manifest mirrors §32.1's example verbatim in field shape; it is a Python
dict constant rather than YAML because v0.1 does not yet know which manifest
fields are load-bearing (design spec decision 2, "why not a full §32.1 tool
manifest yet").
"""
from __future__ import annotations

from pathlib import Path
from ..execution.subprocess_sandbox import ExecutionResult, ExecutionSandbox

RUN_TESTS_MANIFEST: dict = {
    "id": "repository.run_tests",
    "version": "1.0.0",
    "effect_class": "bounded_execution",
    "filesystem": "current-run-workspace",
    "network": "none",
    "credentials": [],
    "timeout_seconds": 60,
    "idempotency": "repeatable",
    "artifact_policy": "result-and-summary",
}


def run_tests(sandbox: ExecutionSandbox, workspace: Path) -> ExecutionResult:
    return sandbox.run("run_pytest", Path(workspace))
