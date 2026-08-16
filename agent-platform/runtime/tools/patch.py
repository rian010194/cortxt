"""Patch application and platform-computed diff (design spec decisions 4 and 6).

The model returns whole-file content, never a unified diff — applying a
model-emitted unified diff means writing a hunk applier, and hunk appliers are
where fuzzy matching creeps in ("context didn't match exactly, apply anyway at
offset ±3"), which is precisely the class of silent unverified mutation this
phase exists to eliminate.

The diff is derived AFTERWARDS by this module against the pristine baseline, so
it is ground truth rather than a model claim. The model has no way to
under-report what it changed.

apply_patch is all-or-nothing: every change is shape-checked, cap-checked and
admitted BEFORE the first byte is written. A diff of a half-applied patch is
worse than no diff, so a failure part-way through writing is reported as
``workspace_inconsistent`` and the caller must discard the workspace rather
than diff it.
"""
from __future__ import annotations

import difflib
from pathlib import Path, PurePosixPath

from ..execution.write_policy import (
    WriteCaps,
    changed_line_count,
    check_changed_lines,
    check_file_count,
    check_file_size,
)
from .gate import WriteGate

PATCH_TOOL_MANIFESTS: dict[str, dict] = {
    "apply_patch": {
        "id": "repository.apply_patch",
        "version": "1.0.0",
        "effect_class": "local_mutation",
        "filesystem": "current-run-workspace",
        "network": "none",
        "credentials": [],
        "timeout_seconds": 30,
        "idempotency": "repeatable",
        "artifact_policy": "result-and-summary",
    },
    "diff_workspace": {
        "id": "repository.diff_workspace",
        "version": "1.0.0",
        "effect_class": "observe",
        "filesystem": "current-run-workspace",
        "network": "none",
        "credentials": [],
        "timeout_seconds": 30,
        "idempotency": "repeatable",
        "artifact_policy": "result-and-summary",
    },
}


class PatchError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def _validate_shape(changes: object) -> list[dict]:
    if not isinstance(changes, list) or not changes:
        raise PatchError("schema", "changes must be a non-empty list")
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "new_content"}:
            raise PatchError("schema", f"each change must be {{path, new_content}}, got {change!r}")
        path, content = change["path"], change["new_content"]
        if not isinstance(path, str) or not isinstance(content, str):
            raise PatchError("schema", "path and new_content must both be strings")
        pure = PurePosixPath(path.replace("\\", "/"))
        if pure.is_absolute() or path.startswith("/") or (len(path) > 1 and path[1] == ":"):
            raise PatchError("schema", f"path must be workspace-relative, got {path!r}")
    return list(changes)


def apply_patch(gate: WriteGate, work_root: Path, changes: list[dict],
                caps: WriteCaps) -> list[str]:
    work_root = Path(work_root).resolve()
    validated = _validate_shape(changes)

    paths = [c["path"].replace("\\", "/") for c in validated]
    check_file_count(paths, caps)

    # Validate EVERYTHING before writing ANYTHING.
    planned: list[tuple[Path, str]] = []
    total_changed = 0
    for change in validated:
        relative = change["path"].replace("\\", "/")
        new_content = change["new_content"]
        check_file_size(relative, new_content, caps)
        resolved = gate.admit("apply_patch", str(work_root / relative))
        try:
            old_content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise PatchError(
                "workspace_inconsistent",
                f"existing file is not valid UTF-8: {relative}",
            ) from error
        total_changed += changed_line_count(old_content, new_content)
        planned.append((resolved, new_content))
    check_changed_lines(total_changed, caps)

    written: list[str] = []
    for resolved, new_content in planned:
        try:
            resolved.write_text(new_content, encoding="utf-8", newline="")
        except OSError as error:
            if written:
                raise PatchError(
                    "workspace_inconsistent",
                    f"patch failed after writing {written}; workspace must be discarded, not diffed",
                ) from error
            raise PatchError("workspace_inconsistent",
                             f"patch could not be written: {error}") from error
        written.append(resolved.relative_to(work_root).as_posix())
    return sorted(written)


def _read(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return []


def diff_workspace(baseline_root: Path, work_root: Path) -> tuple[str, list[str]]:
    baseline_root = Path(baseline_root).resolve()
    work_root = Path(work_root).resolve()

    relatives = sorted({
        p.relative_to(root).as_posix()
        for root in (baseline_root, work_root)
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    })

    chunks: list[str] = []
    changed: list[str] = []
    for relative in relatives:
        old = _read(baseline_root / relative)
        new = _read(work_root / relative)
        if old == new:
            continue
        changed.append(relative)
        chunks.extend(difflib.unified_diff(
            old, new,
            fromfile=f"baseline/{relative}",
            tofile=f"work/{relative}",
        ))
    text = "".join(chunk if chunk.endswith("\n") else chunk + "\n" for chunk in chunks)
    return text, changed
