"""Bounded, deterministic enumeration of a run workspace (design spec decision 1).

Deliberately trivial: relative path, size, sha256, line count. No AST parsing,
no symbol index, no dependency graph — on a three-file fixture those would be
code written to satisfy a bullet, with no fixture able to falsify them. They
become real deliverables the first time a fixture spans enough files that
discovery can actually be wrong.

The output carries no absolute path. The workspace root is a temp directory;
putting it in the map would make the map non-deterministic and would leak host
layout into both the prompt and the session log.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


class WorkspaceMapError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class WorkspaceMapCaps:
    allowed_extensions: tuple[str, ...] = (
        ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    )
    max_files: int = 50
    max_total_bytes: int = 262144


def map_workspace(root: Path, caps: WorkspaceMapCaps = WorkspaceMapCaps()) -> dict:
    root = Path(root)
    if not root.is_dir():
        raise WorkspaceMapError("not_a_directory", f"not a directory: {root}")

    candidates = sorted(
        (p for p in root.rglob("*")
         if p.is_file() and not p.is_symlink() and p.suffix.lower() in caps.allowed_extensions),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    if len(candidates) > caps.max_files:
        raise WorkspaceMapError(
            "cap_max_files", f"workspace has {len(candidates)} files, cap is {caps.max_files}"
        )

    files: list[dict] = []
    total = 0
    for path in candidates:
        raw = path.read_bytes()
        total += len(raw)
        if total > caps.max_total_bytes:
            raise WorkspaceMapError(
                "cap_max_total_bytes",
                f"workspace exceeds {caps.max_total_bytes} bytes",
            )
        try:
            line_count: int | None = len(raw.decode("utf-8").splitlines())
        except UnicodeDecodeError:
            line_count = None
        files.append({
            "path": path.relative_to(root).as_posix(),
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "line_count": line_count,
        })

    return {"file_count": len(files), "total_bytes": total, "files": files}
