"""run_workspace: disposable copy-in workspace, pristine baseline, guaranteed cleanup.

The agent never gets a handle on the repository — containment is structural
first and policy second (design spec decision 4, part 1).
"""
from __future__ import annotations

import contextlib
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


class RunWorkspaceError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class RunWorkspace:
    root: Path
    work: Path
    baseline: Path


@contextlib.contextmanager
def run_workspace(source: Path, prefix: str = "cortxt-run-") -> Iterator[RunWorkspace]:
    source = Path(source)
    if not source.is_dir():
        raise RunWorkspaceError("source_missing", f"fixture workspace not found: {source}")
    if not any(source.iterdir()):
        raise RunWorkspaceError("source_empty", f"fixture workspace is empty: {source}")

    root = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        work = root / "work"
        baseline = root / "baseline"
        shutil.copytree(source, work, symlinks=False)
        shutil.copytree(source, baseline, symlinks=False)
        yield RunWorkspace(root=root, work=work, baseline=baseline)
    finally:
        shutil.rmtree(root, ignore_errors=True)
