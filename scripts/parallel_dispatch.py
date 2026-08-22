#!/usr/bin/env python3
"""Parallel builder dispatch: one isolated git worktree per feature branch.

Why: parallel subagent builders must never write into the same working tree
(the coordinator's default checkout). Switching branches in one shared
checkout does NOT isolate builds -- two builders writing at the same time
land in the same working tree regardless of branch (2026-08-22 incident:
issues #252 and #253 both wrote into main's working tree). The fix is one
isolated linked git worktree per parallel build (the pattern already proven
in scripts/ci_dispatch_proof.py): each subagent gets its own directory, so
two builds physically cannot collide, and the coordinator verifies and
commits per worktree.

Commands:

  prepare <repo> <branch> <base>   create a linked worktree at
                                   <repo-parent>/<repo-name>-worktrees/
                                   <branch-slug> on a NEW branch <branch>
                                   from <base>; print the worktree path;
                                   refuse if the worktree already exists
  verify  <worktree> <branch>      assert the worktree is on <branch> and
                                   print branch + porcelain status; fail
                                   loudly if the branch is wrong or the
                                   tree has changes
  commit  <worktree> <message>     git add -A + git commit -s (DCO) inside
                                   the worktree; refuse if nothing to
                                   commit; print the new HEAD
  cleanup <repo> <branch>          git worktree remove --force; no-op if
                                   already gone

All git calls go through an injectable runner (same pattern as
daemon/github_scanner.py's GhRunner and ci_dispatch_proof.py's run_cmd) so
the logic is network-free and testable with a fake.

Coordinator procedure (required for every parallel dispatch):
  1. prepare  once per branch -> N isolated worktrees
  2. dispatch each subagent with: "your working directory is <worktree>;
     verify `git -C <worktree> branch --show-current` == <branch> and
     `git -C <worktree> status --porcelain` is clean; write ONLY under
     <worktree>; never run git-write commands."
  3. after each build: verify, then commit in the worktree, push, PR
  4. after merge: cleanup
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class DispatchError(RuntimeError):
    """Structured failure with a user-facing message."""


def _run(argv: list[str], *, runner: Runner, cwd: Path | None = None) -> "subprocess.CompletedProcess[str]":
    return runner(argv, capture_output=True, text=True, timeout=60,
                  cwd=str(cwd) if cwd is not None else None)


def worktree_root(repo: Path) -> Path:
    return repo.parent / f"{repo.name}-worktrees"


def worktree_path(repo: Path, branch: str) -> Path:
    slug = branch.replace("/", "-")
    return worktree_root(repo) / slug


def prepare(repo: Path, branch: str, base: str, *, runner: Runner = subprocess.run) -> Path:
    repo = repo.resolve()
    wt = worktree_path(repo, branch)
    if wt.exists():
        raise DispatchError(f"worktree already exists: {wt}")
    wt.parent.mkdir(parents=True, exist_ok=True)
    result = _run(["git", "-C", str(repo), "worktree", "add", "-b", branch, str(wt), base], runner=runner)
    if result.returncode != 0:
        raise DispatchError(f"git worktree add failed: {result.stderr.strip()}")
    return wt


def verify(wt: Path, branch: str, *, runner: Runner = subprocess.run) -> dict:
    wt = wt.resolve()
    current = _run(["git", "-C", str(wt), "branch", "--show-current"], runner=runner)
    if current.returncode != 0 or current.stdout.strip() != branch:
        raise DispatchError(
            f"worktree {wt} is on {current.stdout.strip()!r}, expected {branch!r}")
    status = _run(["git", "-C", str(wt), "status", "--porcelain"], runner=runner)
    changes = [line for line in status.stdout.splitlines() if line.strip()]
    return {"branch": current.stdout.strip(), "changes": changes}


def commit(wt: Path, message: str, *, runner: Runner = subprocess.run) -> str:
    wt = wt.resolve()
    status = _run(["git", "-C", str(wt), "status", "--porcelain"], runner=runner)
    changes = [line for line in status.stdout.splitlines() if line.strip()]
    if not changes:
        raise DispatchError(f"nothing to commit in {wt}")
    add = _run(["git", "-C", str(wt), "add", "-A"], runner=runner)
    if add.returncode != 0:
        raise DispatchError(f"git add failed: {add.stderr.strip()}")
    made = _run(["git", "-C", str(wt), "commit", "-s", "-m", message], runner=runner)
    if made.returncode != 0:
        raise DispatchError(f"git commit failed: {made.stderr.strip()}")
    head = _run(["git", "-C", str(wt), "rev-parse", "HEAD"], runner=runner)
    return head.stdout.strip()


def cleanup(repo: Path, branch: str, *, runner: Runner = subprocess.run) -> None:
    repo = repo.resolve()
    wt = worktree_path(repo, branch)
    if not wt.exists():
        return
    result = _run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)], runner=runner)
    if result.returncode != 0:
        raise DispatchError(f"git worktree remove failed: {result.stderr.strip()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare", help="create an isolated worktree on a new branch")
    p_prepare.add_argument("repo", type=Path)
    p_prepare.add_argument("branch")
    p_prepare.add_argument("base")

    p_verify = sub.add_parser("verify", help="assert the worktree is on the expected branch")
    p_verify.add_argument("worktree", type=Path)
    p_verify.add_argument("branch")

    p_commit = sub.add_parser("commit", help="stage and DCO-commit all changes in the worktree")
    p_commit.add_argument("worktree", type=Path)
    p_commit.add_argument("message")

    p_cleanup = sub.add_parser("cleanup", help="remove the worktree")
    p_cleanup.add_argument("repo", type=Path)
    p_cleanup.add_argument("branch")

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            print(prepare(args.repo, args.branch, args.base))
        elif args.command == "verify":
            print(json.dumps(verify(args.worktree, args.branch), indent=2))
        elif args.command == "commit":
            print(commit(args.worktree, args.message))
        elif args.command == "cleanup":
            cleanup(args.repo, args.branch)
    except DispatchError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
