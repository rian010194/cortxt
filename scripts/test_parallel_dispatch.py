#!/usr/bin/env python3
"""Offline fake-injection tests for scripts/parallel_dispatch.py.

Same check-style convention as scripts/test_work_launcher.py and
scripts/test_dispatcher.py: run directly with `python scripts/
test_parallel_dispatch.py`; prints ok/FAIL lines and exits non-zero on any
failure. Never touches a real git repository.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import parallel_dispatch as pd

fail = []
_ROOT = Path(tempfile.mkdtemp(prefix="parallel-dispatch-test-"))


def check(name, condition):
    print(f"  {'ok' if condition else 'FAIL':4} {name}")
    if not condition:
        fail.append(name)


class FakeRunner:
    """Records argv; canned responses keyed by command prefix."""

    def __init__(self):
        self.calls = []
        self.responses = {}

    def set(self, predicate, returncode=0, stdout="", stderr=""):
        self.responses[predicate] = (returncode, stdout, stderr)

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        for predicate, (returncode, stdout, stderr) in self.responses.items():
            if predicate in argv:
                return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_prepare():
    runner = FakeRunner()
    repo = _ROOT / "repo"
    wt = pd.worktree_path(repo, "feat/alpha")
    runner.set("worktree", 0, "")
    result = pd.prepare(repo, "feat/alpha", "origin/main", runner=runner)
    check("prepare returns the worktree path", result == wt)
    check("prepare runs git worktree add -b <branch> <wt> <base>",
          any(a[1:] == ["-C", str(repo), "worktree", "add", "-b", "feat/alpha", str(wt), "origin/main"]
              for a in runner.calls))
    wt.mkdir(parents=True, exist_ok=True)
    check("prepare refuses an existing worktree", _raises(
        lambda: pd.prepare(repo, "feat/alpha", "origin/main", runner=runner), pd.DispatchError))
    runner.set("worktree", 1, "", "boom")
    check("prepare raises on git failure", _raises(
        lambda: pd.prepare(_ROOT / "repo2", "feat/beta", "origin/main", runner=runner),
        pd.DispatchError))


def test_verify():
    runner = FakeRunner()
    wt = Path("/fake/wt")
    runner.set("branch", 0, "feat/alpha\n")
    runner.set("status", 0, "")
    info = pd.verify(wt, "feat/alpha", runner=runner)
    check("verify returns branch", info["branch"] == "feat/alpha")
    check("verify reports no changes", info["changes"] == [])
    runner.set("branch", 0, "main\n")
    check("verify fails on wrong branch", _raises(
        lambda: pd.verify(wt, "feat/alpha", runner=runner), pd.DispatchError))
    runner.set("branch", 0, "feat/alpha\n")
    runner.set("status", 0, " M file.py\n")
    info = pd.verify(wt, "feat/alpha", runner=runner)
    check("verify reports changes", info["changes"] == [" M file.py"])


def test_commit():
    runner = FakeRunner()
    wt = Path("/fake/wt")
    runner.set("status", 0, "")
    check("commit refuses empty tree", _raises(
        lambda: pd.commit(wt, "msg", runner=runner), pd.DispatchError))
    runner.set("status", 0, " M file.py\n")
    runner.set("rev-parse", 0, "abc123\n")
    head = pd.commit(wt, "feat: x", runner=runner)
    check("commit returns HEAD", head == "abc123")
    check("commit runs add -A", any(a[3:6] == ["add", "-A"] for a in runner.calls))
    check("commit runs commit -s -m", any(
        a[3:8] == ["commit", "-s", "-m", "feat: x"] for a in runner.calls))
    runner.set("commit", 1, "", "nope")
    runner.set("status", 0, " M file.py\n")
    check("commit raises on failure", _raises(
        lambda: pd.commit(wt, "msg", runner=runner), pd.DispatchError))


def test_cleanup():
    runner = FakeRunner()
    repo = _ROOT / "repo"
    wt = pd.worktree_path(repo, "feat/alpha")
    check("cleanup skips a missing worktree", pd.cleanup(repo, "feat/alpha", runner=runner) is None)
    wt.mkdir(parents=True, exist_ok=True)
    runner.set("worktree", 0, "")
    check("cleanup removes an existing worktree",
          pd.cleanup(repo, "feat/alpha", runner=runner) is None
          and any(a[1:4] == ["-C", str(repo), "worktree"] and "remove" in a for a in runner.calls))


def _raises(fn, exc_type):
    try:
        fn()
        return False
    except exc_type:
        return True


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import parallel_dispatch  # noqa: F401  (re-import for direct run)

    test_prepare()
    test_verify()
    test_commit()
    test_cleanup()
    print("")
    if fail:
        print(f"FAILED: {len(fail)}: {fail}")
        raise SystemExit(1)
    print("ALL PARALLEL DISPATCH TESTS PASSED")
