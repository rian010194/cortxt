#!/usr/bin/env python3
"""Post-run containment scan for isolated dispatches (#608).

The Evidence Gate verifies a mutating Run's commit-scoped artifacts, but all
of its path containment is repo-relative against a commit: with no commit
nothing runs, and a worker that writes outside its registered worktree leaves
no error behind. This module closes the second half of that gap (#608): the
launcher snapshots its dispatching checkout's `git status --porcelain` state
before the worker starts, and after the worker reaches ANY terminal status
compares that snapshot against both the launcher checkout and the registered
worktree, recording a stable containment code on the durable Run record so it
is visible in `runs.json`, not only in a log.

Codes (exactly three, plus one internal error code):

- `containment_clean`: the launcher checkout's porcelain output is unchanged
  from the snapshot. The worktree's porcelain may show approved activity.
- `worktree_dirty_uncommitted`: launcher checkout unchanged; the registered
  worktree has uncommitted changes. That is the worker doing approved work it
  has not committed yet -- visible, not a violation.
- `launcher_checkout_dirty`: the launcher checkout's porcelain output differs
  from the snapshot, meaning files outside the registered worktree changed
  during the run. This is the misspelled-sibling escape #606/#607 observed,
  and the code the Evidence Gate later refuses on.

The scan is read-only: it never mutates either checkout and never fails a
launch. Every git call runs with `cwd=<dir>` (never `git -C`) and every
diff is a list of paths, never file contents, so nothing here can carry
prompt or reasoning material into the Run record.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

CONTAINMENT_CLEAN = "containment_clean"
WORKTREE_DIRTY_UNCOMMITTED = "worktree_dirty_uncommitted"
LAUNCHER_CHECKOUT_DIRTY = "launcher_checkout_dirty"
CONTAINMENT_SCAN_ERROR = "containment_scan_error"

# `-uall` so untracked files are listed individually: a directory-level `??`
# entry collapses every file inside it into one line, which would both hide
# which paths changed and make the snapshot differ on an internal rename.
_PORCELAIN_ARGS = ["git", "status", "--porcelain", "-uall"]


def _porcelain(repo_path: Path) -> "tuple[int, str]":
    """Run `git status --porcelain -uall` with cwd=<dir>, returning
    (returncode, stdout). Never `git -C`."""
    try:
        proc = subprocess.run(_PORCELAIN_ARGS, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30,
                              cwd=str(repo_path))
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[containment_scan] git status failed in {repo_path}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1, ""
    return proc.returncode, proc.stdout


def snapshot_checkout(repo_path: Path) -> dict:
    """Capture the dispatching checkout's porcelain state, pre-launch.

    Returns a plain dict (`{"lines": [...]}`) so the snapshot is JSON-serializable
    and can be held in memory by the launcher for the run's lifetime. A checkout
    that git cannot read snapshots as an error marker; the scan then degrades to
    `containment_scan_error` rather than inventing a clean verdict.
    """
    code, out = _porcelain(repo_path)
    if code != 0:
        return {"error": f"git status failed (rc={code})"}
    return {"lines": sorted(out.splitlines())}


def _diff(before: list, after: list) -> list:
    """Changed porcelain lines between two snapshots, as sorted path strings.

    Porcelain lines are `<XY> <path>`; the status columns of an unchanged
    path can legitimately move (a file going from untracked to tracked), and
    quoting of non-ASCII paths varies, so the comparison is on the whole
    normalized line and the result keeps the raw path portion for display.
    """
    return sorted(set(after) ^ set(before))


def scan_containment(repo_path: Path, snapshot: dict,
                     worktree_path: Optional[Path]) -> dict:
    """Classify what changed since `snapshot_checkout` was taken.

    Both directories are read with `git status --porcelain -uall` under
    `cwd`; the launcher checkout's current output is compared with the
    snapshot, and the registered worktree's output is reported as its own
    path list. A path inside `worktree_path` seen from the launcher checkout
    is excluded before classification: a registered linked worktree's files
    are legitimately visible from the parent checkout's `git status`, and
    counting them would mark every isolated run dirty.

    The result is `{"code": ..., "checkout_changed_paths": [...],
    "worktree_changed_paths": [...]}`. Never raises, never mutates anything:
    an unreadable checkout or worktree records `containment_scan_error` and
    prints to stderr, so a scan defect can never fail a launch or a
    completion that already happened.
    """
    try:
        if not isinstance(snapshot, dict) or "lines" not in snapshot:
            raise ValueError("snapshot has no porcelain lines")
        before = list(snapshot["lines"])
        code, after_out = _porcelain(repo_path)
        if code != 0:
            raise RuntimeError(f"launcher checkout unreadable (rc={code})")
        after = sorted(after_out.splitlines())
        if worktree_path is not None and worktree_path.is_dir():
            wt_code, wt_out = _porcelain(worktree_path)
            if wt_code != 0:
                raise RuntimeError(f"worktree unreadable (rc={wt_code})")
            worktree_lines = sorted(wt_out.splitlines())
        else:
            # No (or vanished) worktree: nothing was registered to read, so
            # the worktree side is empty by definition, never an error.
            worktree_lines = []

        # Exclude the registered worktree (and anything under it) from the
        # launcher checkout's view before diffing, per the module docstring.
        # Porcelain prints paths relative to the repo root with forward
        # slashes, so the exclusion prefix is normalized to that same shape:
        # the worktree's own (possibly relative, OS-native) path made absolute
        # and re-rooted under the checkout. A worktree outside the checkout
        # has no prefix here, and correctly needs none: git never reports a
        # separate worktree's files in the parent's status.
        prefix = None
        if worktree_path is not None:
            try:
                prefix = worktree_path.resolve().relative_to(
                    repo_path.resolve()).as_posix()
            except ValueError:
                prefix = None

        def _inside_worktree(line: str) -> bool:
            if not prefix:
                return False
            path_part = line[3:] if len(line) > 3 else ""
            if path_part.startswith('"'):
                # git quotes non-ASCII paths: `"prefix/..."` with backslash
                # escapes; compare on the quoted prefix only.
                return path_part.startswith('"' + prefix) \
                    and (len(path_part) == len(prefix) + 3
                         or path_part[len(prefix) + 2] in ("/", "\\"))
            return path_part == prefix or path_part.startswith(prefix + "/")

        checkout_after = [line for line in after if not _inside_worktree(line)]
        checkout_before = [line for line in before if not _inside_worktree(line)]
        checkout_changed = _diff(checkout_before, checkout_after)
        worktree_changed = [line[3:] if len(line) > 3 else line for line in worktree_lines]

        if checkout_changed:
            return {"code": LAUNCHER_CHECKOUT_DIRTY,
                    "checkout_changed_paths": checkout_changed,
                    "worktree_changed_paths": worktree_changed}
        if worktree_changed:
            return {"code": WORKTREE_DIRTY_UNCOMMITTED,
                    "checkout_changed_paths": [],
                    "worktree_changed_paths": worktree_changed}
        return {"code": CONTAINMENT_CLEAN,
                "checkout_changed_paths": [],
                "worktree_changed_paths": []}
    except Exception as exc:  # noqa: BLE001 - the scan never fails its caller
        print(f"[containment_scan] scan error: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return {"code": CONTAINMENT_SCAN_ERROR,
                "checkout_changed_paths": [], "worktree_changed_paths": []}


def main() -> int:
    """Operator entry point: scan a checkout/worktree pair by path."""
    if len(sys.argv) not in (2, 3):
        print("usage: containment_scan.py <checkout> [worktree]", file=sys.stderr)
        return 2
    checkout = Path(sys.argv[1])
    worktree = Path(sys.argv[2]) if len(sys.argv) == 3 else None
    import json
    result = scan_containment(checkout, snapshot_checkout(checkout), worktree)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
