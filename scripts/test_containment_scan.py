#!/usr/bin/env python3
"""Offline tests for the post-run containment scan (#608).

`main()`-style program, run as `python scripts/test_containment_scan.py`;
keeps the shape of the other scripts/ suites (shared `check()`, `fail` list,
SystemExit at the end) and also exposes a pytest entry point, matching the
existing convention (see `scripts/test_work_launcher.py`).

Every fixture builds its own throwaway git repository under
`tempfile.TemporaryDirectory` -- no test touches any real checkout.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import containment_scan as cs  # noqa: E402 - scripts/ is sys.path[0] for this script

fail = []


def check(name, condition, detail=""):
    print(f"  {'ok' if condition else 'FAIL':4} {name}"
          + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        fail.append(name)


def _git(cwd, *args):
    proc = subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(cwd),
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.io",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.io",
                               "GIT_CONFIG_GLOBAL": "/dev/null", "PATH": __import__("os").environ["PATH"]})
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _scratch_repo(root: Path) -> Path:
    """A tiny git repo standing in for the launcher's dispatching checkout."""
    repo = root / "launcher-checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("scratch\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _registered_worktree(repo: Path, run_id: str, name: str) -> Path:
    """A registered linked worktree of the scratch repo, named like a real one."""
    trees = repo / "run-trees"
    trees.mkdir(exist_ok=True)
    wt = trees / name
    _git(repo, "worktree", "add", "-q", "-b", f"work/{run_id}", str(wt))
    return wt


def main() -> None:
    print("== regression fixture (#608): the misspelled-sibling escape ==")
    # The #606 shape: a worker told to work in .../s5-controlplane-a8a1ff0
    # re-orients from ambient context and writes its artifacts into
    # .../s5controlplane-a8a1ff0 (missing hyphen) instead. The registered
    # worktree stays untouched; only the launcher checkout's porcelain state
    # changes -- and the scan must catch exactly that.
    with tempfile.TemporaryDirectory(prefix="containment-typo-") as tmp:
        root = Path(tmp)
        repo = _scratch_repo(root)
        wt = _registered_worktree(repo, "run-606", "s5-controlplane-real")
        snapshot = cs.snapshot_checkout(repo)
        check("snapshot is a sorted list of porcelain lines",
              isinstance(snapshot.get("lines"), list)
              and snapshot["lines"] == sorted(snapshot["lines"]))
        # The escape: write into the misspelled SIBLING of the registered
        # worktree (s5controlplane- vs s5-controlplane-), outside it.
        sibling = wt.parent / "s5controlplane-typo"
        sibling.mkdir()
        (sibling / "artifact.md").write_text("escaped artifact\n")
        result = cs.scan_containment(repo, snapshot, wt)
        check("scan classifies the escape as launcher_checkout_dirty",
              result["code"] == cs.LAUNCHER_CHECKOUT_DIRTY, str(result))
        check("checkout_changed_paths names the escaped path",
              any("s5controlplane-typo" in p for p in result["checkout_changed_paths"]),
              str(result["checkout_changed_paths"]))
        check("the registered worktree porcelain is clean",
              result["worktree_changed_paths"] == [], str(result))
        # ...and the real worktree itself reports no tracked-file change.
        code = subprocess.run(["git", "status", "--porcelain"], cwd=str(wt),
                              capture_output=True, text=True).stdout
        check("registered worktree git status is empty", code.strip() == "", repr(code))

    print("== containment_clean: approved activity inside the registered worktree ==")
    with tempfile.TemporaryDirectory(prefix="containment-clean-") as tmp:
        root = Path(tmp)
        repo = _scratch_repo(root)
        wt = _registered_worktree(repo, "run-clean", "s5-controlplane-real")
        snapshot = cs.snapshot_checkout(repo)
        (wt / "docs").mkdir(exist_ok=True)
        (wt / "docs" / "note.md").write_text("approved work\n")
        # Uncommitted worktree activity is its own code (next section); here the
        # worker COMMITS inside its registered worktree, which is the approved
        # end state and must leave the launcher checkout's classification clean.
        _git(wt, "add", ".")
        _git(wt, "commit", "-q", "-m", "worker commit")
        result = cs.scan_containment(repo, snapshot, wt)
        check("committed worktree work is containment_clean",
              result["code"] == cs.CONTAINMENT_CLEAN, str(result))
        check("no checkout or worktree path changes are reported",
              result["checkout_changed_paths"] == []
              and result["worktree_changed_paths"] == [], str(result))

    print("== worktree_dirty_uncommitted is distinct from checkout dirt ==")
    with tempfile.TemporaryDirectory(prefix="containment-dirty-") as tmp:
        root = Path(tmp)
        repo = _scratch_repo(root)
        wt = _registered_worktree(repo, "run-dirty", "s5-controlplane-real")
        snapshot = cs.snapshot_checkout(repo)
        (wt / "uncommitted.txt").write_text("wip\n")
        result = cs.scan_containment(repo, snapshot, wt)
        check("uncommitted worktree work is worktree_dirty_uncommitted",
              result["code"] == cs.WORKTREE_DIRTY_UNCOMMITTED, str(result))
        check("the launcher checkout itself shows no change",
              result["checkout_changed_paths"] == [], str(result))
        # A change OUTSIDE the worktree in the same run is the violation code,
        # even with the worktree also dirty: containment fails closed.
        (repo / "stray.txt").write_text("outside\n")
        result = cs.scan_containment(repo, snapshot, wt)
        check("an outside write escalates to launcher_checkout_dirty",
              result["code"] == cs.LAUNCHER_CHECKOUT_DIRTY, str(result))

    print("== snapshot round-trip and error handling ==")
    with tempfile.TemporaryDirectory(prefix="containment-roundtrip-") as tmp:
        root = Path(tmp)
        repo = _scratch_repo(root)
        wt = _registered_worktree(repo, "run-rt", "s5-controlplane-real")
        snapshot = cs.snapshot_checkout(repo)
        # Nothing changed: scanning with the same snapshot is clean.
        result = cs.scan_containment(repo, snapshot, wt)
        check("unchanged checkout/worktree scans containment_clean",
              result["code"] == cs.CONTAINMENT_CLEAN, str(result))
        # A committed change inside the worktree is still not launcher dirt.
        (wt / "committed.txt").write_text("landed\n")
        _git(wt, "add", ".")
        _git(wt, "commit", "-q", "-m", "worker commit")
        result = cs.scan_containment(repo, snapshot, wt)
        check("committed worktree work is also containment_clean",
              result["code"] == cs.CONTAINMENT_CLEAN, str(result))
        # A snapshot that is not a porcelain snapshot degrades to the error
        # code instead of inventing a verdict.
        broken = cs.scan_containment(repo, {"nonsense": True}, wt)
        check("malformed snapshot records containment_scan_error",
              broken["code"] == cs.CONTAINMENT_SCAN_ERROR, str(broken))
        # A vanished worktree is not an error: nothing was registered to read.
        result = cs.scan_containment(repo, snapshot, root / "gone")
        check("vanished worktree still classifies from the checkout side",
              result["code"] in (cs.CONTAINMENT_CLEAN, cs.LAUNCHER_CHECKOUT_DIRTY),
              str(result))
        # The scan mutated nothing: the worktree's own status is unchanged.
        code = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=str(wt),
                              capture_output=True, text=True).stdout
        check("scan left the worktree untouched", code.strip() == "", repr(code))

    print(f"\n{'PASS' if not fail else 'FAIL'}: {len(fail)} failure(s)")
    raise SystemExit(1 if fail else 0)


def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script."""
    try:
        main()
    except SystemExit as exc:  # main() ends with raise SystemExit(0|1)
        assert exc.code == 0, f"{len(fail)} check(s) failed: {fail}"
    assert not fail, f"{len(fail)} check(s) failed: {fail}"


if __name__ == "__main__":
    main()
