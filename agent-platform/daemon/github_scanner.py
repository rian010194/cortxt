"""Lists workflow:ready GitHub issues (dispatch-contract.md's source of
truth) via the gh CLI -- same subprocess pattern scripts/dispatcher.py's
GitHubOps uses, reimplemented narrowly here rather than imported across the
scripts/ <-> agent-platform/ packaging boundary routing/hermes_invoker.py's
docstring already documents avoiding.
"""
from __future__ import annotations

import json
import subprocess
from typing import Callable

GhRunner = Callable[..., "subprocess.CompletedProcess[str]"]


def list_ready_issues(
    repo: str,
    *,
    label: str = "workflow:ready",
    run_subprocess: GhRunner = subprocess.run,
    timeout_seconds: int = 30,
) -> list[dict]:
    result = run_subprocess(
        ["gh", "issue", "list", "--repo", repo, "--label", label,
         "--state", "open", "--json", "number,title,labels"],
        capture_output=True, text=True, timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh issue list failed: {result.stderr.strip()}")
    return json.loads(result.stdout)
