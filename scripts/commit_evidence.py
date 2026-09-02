#!/usr/bin/env python3
"""Commit-correlation Evidence Gate for mutating Runs (#490).

A mutating Run is one whose approved mandate expects it to change the
repository. Before #490, nothing between the worker and the durable Run
record required a landed artifact, so a self-reported ``succeeded`` with no
commit SHA, no branch and no worktree was accepted and relayed onward to the
Issue (the #485 forensics: ``run-6d936b467f804939a4ce734ac5f45dd8`` reported
success while ``git log --all`` for the mandated path returned zero commits).

This module is the verification half of that gate. It is pure with respect to
the platform: it reads git and the durable Run record, and returns either
``CommitEvidence`` (a correlated, durable record of what actually landed) or a
``CorrelationFailure`` carrying a stable code. It never decides what to do
with either -- ``Dispatcher.complete()`` owns that, because it is the single
choke point every launch path reaches (``WorkLauncher.submit()`` and
``worker_adapters.dispatch_async``'s background thread both call it directly).

Every check fails closed. A missing, unverifiable or non-correlating commit is
a structured failure, never a pass, and never reported onward as success.
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DCO_RE = re.compile(r"^Signed-off-by:\s*\S.*<[^>@\s]+@[^>\s]+>\s*$", re.MULTILINE)
# Path tokens as an operator writes them in an artifact policy, e.g.
# "Only `docs/agents/work-launcher.md` inside the run's isolated worktree".
POLICY_PATH_RE = re.compile(r"`([A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9](?:/|\.[A-Za-z0-9]+))`")

GitRunner = Callable[[Sequence[str]], "tuple[int, str]"]


@dataclass(frozen=True)
class CommitEvidence:
    """Durable, correlated proof that a mutating Run landed a real commit."""

    run_id: str
    issue_id: str
    commit: str
    branch: str
    committed_at: int
    files: tuple
    verified_at: float
    request_id: Optional[str] = None
    worktree: Optional[str] = None
    policy_paths: tuple = ()

    def as_record(self) -> dict:
        """The shape written onto the durable Run record and its result envelope."""
        return {
            "run_id": self.run_id,
            "issue_id": self.issue_id,
            "request_id": self.request_id,
            "commit": self.commit,
            "branch": self.branch,
            "worktree": self.worktree,
            "committed_at": self.committed_at,
            "files": list(self.files),
            "policy_paths": list(self.policy_paths),
            "verified_at": self.verified_at,
        }


@dataclass(frozen=True)
class CorrelationFailure:
    """A stable, content-free rejection. `code` is the durable identifier."""

    code: str
    detail: str
    recovery: str


def _subprocess_git(repo_path: Optional[Path]) -> GitRunner:
    def run(args: Sequence[str]) -> tuple:
        proc = subprocess.run(["git", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30,
                              cwd=str(repo_path) if repo_path else None)
        return proc.returncode, proc.stdout
    return run


def policy_paths(artifact_policy: Optional[str]) -> tuple:
    """The path set a scoped artifact policy names, in prose, in backticks.

    A policy that names no path is *unscoped*, not invalid: it restricts what a
    commit may say (see the launcher's default policy), not which files it may
    touch. An unscoped policy therefore yields an empty set and the gate falls
    back to requiring a real, non-empty change -- it never silently widens a
    scoped policy, and never rejects an unscoped one for saying nothing.
    """
    if not artifact_policy:
        return ()
    return tuple(dict.fromkeys(POLICY_PATH_RE.findall(artifact_policy)))


def _within(path: str, permitted: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/")
    for allowed in permitted:
        allowed = allowed.replace("\\", "/").rstrip("/")
        if normalized == allowed or normalized.startswith(allowed + "/"):
            return True
    return False


def verify_commit_correlation(
    run,
    result_envelope: dict,
    *,
    git: Optional[GitRunner] = None,
    repo_path: Optional[Path] = None,
    clock: Callable[[], float] = time.time,
):
    """Verify that `run`'s claimed success is backed by a correlated commit.

    The conditions, in the order #490 states them: the commit exists; it belongs
    to this Run and this request; it sits on the Run's registered isolated
    worktree branch; it satisfies the approved artifact policy; and it comes
    back as durable, correlated evidence.

    Returns ``CommitEvidence`` on success, ``CorrelationFailure`` otherwise.
    """
    git = git or _subprocess_git(repo_path)
    envelope = result_envelope or {}

    claimed_run = envelope.get("run_id")
    if claimed_run is not None and claimed_run != run.run_id:
        return CorrelationFailure(
            "run_correlation_mismatch",
            f"result envelope reports run_id {claimed_run!r}, Run record is {run.run_id!r}",
            "The worker returned a result for a different Run; discard it and re-run this Run.")
    claimed_issue = envelope.get("issue_id")
    if claimed_issue is not None and claimed_issue != run.issue_id:
        return CorrelationFailure(
            "issue_correlation_mismatch",
            f"result envelope reports issue_id {claimed_issue!r}, Run record is {run.issue_id!r}",
            "The worker returned a result for a different Issue; discard it and re-run this Run.")
    claimed_request = envelope.get("request_id")
    if (claimed_request is not None and getattr(run, "request_id", None) is not None
            and claimed_request != run.request_id):
        return CorrelationFailure(
            "request_correlation_mismatch",
            "result envelope reports a request_id other than the approved dispatch request",
            "Re-read the live dispatch request and approve exactly that request before running.")

    commit = envelope.get("commit") or envelope.get("commit_sha")
    if not isinstance(commit, str) or not SHA_RE.fullmatch(commit.strip().lower()):
        return CorrelationFailure(
            "commit_missing",
            f"no full 40-hex commit SHA in the result envelope (got {commit!r})",
            "A mutating Run must return the SHA of the commit it landed, in the envelope's "
            "`commit` field. Self-reported status is not evidence.")
    commit = commit.strip().lower()

    if getattr(run, "isolation", None) != "worktree" or not getattr(run, "branch", None):
        return CorrelationFailure(
            "isolation_not_recorded",
            f"Run records isolation={getattr(run, 'isolation', None)!r} "
            f"branch={getattr(run, 'branch', None)!r}",
            "A mutating Run must run in its own isolated worktree with a registered branch; "
            "launch it with isolation instead of the launcher's shared checkout.")
    branch = run.branch

    code, out = git(["cat-file", "-t", commit])
    if code != 0 or out.strip() != "commit":
        return CorrelationFailure(
            "commit_not_found",
            f"{commit} is not a commit object in this repository",
            "The reported commit does not exist. Nothing landed; treat the Run as failed.")

    code, _ = git(["merge-base", "--is-ancestor", commit, f"refs/heads/{branch}"])
    if code != 0:
        return CorrelationFailure(
            "commit_not_on_run_branch",
            f"{commit} is not reachable from refs/heads/{branch}",
            f"The commit is not on this Run's registered branch {branch!r}; a commit made "
            "outside the Run's isolated worktree is not this Run's evidence.")

    code, out = git(["show", "-s", "--format=%ct", commit])
    if code != 0 or not out.strip().isdigit():
        return CorrelationFailure(
            "commit_time_unreadable",
            f"could not read the commit timestamp of {commit}",
            "Re-run the gate against a readable repository.")
    committed_at = int(out.strip())
    if committed_at < int(getattr(run, "claimed_at", 0)):
        return CorrelationFailure(
            "commit_predates_run",
            f"{commit} was committed at {committed_at}, before the Run was claimed "
            f"at {int(run.claimed_at)}",
            "A pre-existing commit is not this Run's work; the Run landed nothing.")

    code, message = git(["show", "-s", "--format=%B", commit])
    if code != 0:
        return CorrelationFailure(
            "commit_message_unreadable",
            f"could not read the commit message of {commit}",
            "Re-run the gate against a readable repository.")
    if not DCO_RE.search(message):
        return CorrelationFailure(
            "dco_trailer_missing",
            f"{commit} carries no `Signed-off-by:` trailer",
            "Every landed commit must carry a DCO sign-off; amend the commit and re-run.")

    code, out = git(["show", "--name-only", "--format=", commit])
    if code != 0:
        return CorrelationFailure(
            "commit_files_unreadable",
            f"could not list the files changed by {commit}",
            "Re-run the gate against a readable repository.")
    files = tuple(line.strip() for line in out.splitlines() if line.strip())
    if not files:
        return CorrelationFailure(
            "no_files_changed",
            f"{commit} changes no files",
            "An empty commit is not an artifact; the Run produced nothing to review.")

    permitted = tuple(getattr(run, "artifact_paths", None) or ()) or policy_paths(
        getattr(run, "artifact_policy", None))
    if permitted:
        outside = [path for path in files if not _within(path, permitted)]
        if outside:
            return CorrelationFailure(
                "artifact_policy_violation",
                f"{commit} touches paths outside the approved artifact policy: "
                + ", ".join(sorted(outside)),
                f"The approved policy permits only {', '.join(permitted)}. Re-run within scope.")

    return CommitEvidence(
        run_id=run.run_id,
        issue_id=run.issue_id,
        commit=commit,
        branch=branch,
        committed_at=committed_at,
        files=files,
        verified_at=clock(),
        request_id=getattr(run, "request_id", None),
        worktree=envelope.get("worktree"),
        policy_paths=permitted,
    )


def make_commit_gate(repo_path: Optional[Path] = None,
                     clock: Callable[[], float] = time.time) -> Callable:
    """Bind the gate to a repository, for injection into `Dispatcher`."""

    def gate(run, result_envelope: dict):
        return verify_commit_correlation(run, result_envelope,
                                         repo_path=repo_path, clock=clock)
    return gate
