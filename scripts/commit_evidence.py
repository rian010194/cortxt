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
#
# Deliberately permissive about shape: a repository-relative path may be a
# single segment with no separator and no extension (`LICENSE`, `Makefile`,
# `Dockerfile`), and the earlier pattern -- which required a `/` or a `.ext` --
# silently dropped those. Dropping a path is the dangerous direction: it turned
# a scoped policy into an empty set, and an empty set used to mean
# *unrestricted*. Over-matching is the safe direction: an extra token only ever
# narrows what a commit may touch, and a policy whose wording confuses the
# parser fails closed with `artifact_policy_violation` for the operator to see
# and reword, rather than quietly permitting everything.
POLICY_PATH_RE = re.compile(r"`([A-Za-z0-9][A-Za-z0-9._/-]*)`")

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

    An empty result means the policy named nothing the parser could read. That
    is **not** "unrestricted" -- callers must treat it as a fail-closed
    condition. An earlier version returned an empty set for an unscoped policy
    and let the gate permit any path; combined with a pattern that could not
    see single-segment paths like `LICENSE`, a real scoped policy could be
    downgraded to no restriction at all.
    """
    if not artifact_policy:
        return ()
    return tuple(dict.fromkeys(POLICY_PATH_RE.findall(artifact_policy)))


def normalize_repo_path(path: str) -> Optional[str]:
    """A repository-relative POSIX path, or None if it is not one.

    Rejects what must never be compared as if it were inside the repository:
    absolute paths, Windows drive letters, UNC paths, and any `..` segment that
    could walk out of the permitted subtree. Returns None rather than a
    best-effort string, so a caller cannot accidentally treat an unsafe path as
    merely non-matching -- the gate turns None into an explicit failure.
    """
    if not isinstance(path, str) or not path.strip():
        return None
    candidate = path.strip().replace("\\", "/")
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        return None
    segments = []
    for segment in candidate.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            return None
        segments.append(segment)
    return "/".join(segments) or None


def _within(path: str, permitted: Sequence[str]) -> bool:
    """True when `path` is exactly a permitted entry or inside a permitted one.

    Both sides are normalized first, so `docs/./agents/x.md` matches
    `docs/agents/` and no unsafe path can match anything at all.
    """
    normalized = normalize_repo_path(path)
    if normalized is None:
        return False
    for allowed in permitted:
        allowed_norm = normalize_repo_path(allowed)
        if allowed_norm is None:
            continue
        if normalized == allowed_norm or normalized.startswith(allowed_norm + "/"):
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

    # Correlation is mandatory, not opportunistic. Previously each of these was
    # checked only when the worker happened to supply it, so a result envelope
    # that simply omitted `run_id` skipped its own correlation check -- the
    # worker chose whether to be checked. All three must now be present and
    # match the approved Run record exactly.
    for field, expected, code in (
        ("run_id", run.run_id, "run_correlation_mismatch"),
        ("issue_id", run.issue_id, "issue_correlation_mismatch"),
        ("request_id", getattr(run, "request_id", None), "request_correlation_mismatch"),
    ):
        if expected is None:
            return CorrelationFailure(
                f"{field}_not_recorded",
                f"the Run record carries no {field}, so nothing can be correlated against it",
                f"A mutating Run must record its approved {field} before dispatch; "
                "re-launch it through the sanctioned path.")
        claimed = envelope.get(field)
        if claimed is None:
            return CorrelationFailure(
                code,
                f"result envelope omits {field}; correlation cannot be established",
                f"A mutating Run's result must state its {field}. An omitted field is "
                "not a passed check.")
        if claimed != expected:
            return CorrelationFailure(
                code,
                f"result envelope reports {field} {claimed!r}, Run record is {expected!r}",
                "The worker returned a result for a different Run, Issue or approved "
                "request; discard it and re-run this Run.")

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
    claimed_second = int(getattr(run, "claimed_at", 0))
    # Strictly after, not "not before". Git commit timestamps have one-second
    # resolution, so a commit made in the same second as the claim -- including
    # one made just *before* it -- used to compare equal and pass. That is the
    # whole window an attacker or a confused worker needs to present
    # pre-existing work as this Run's output. Requiring a strictly later second
    # closes it in the fail-closed direction: the cost is that a run which
    # claims and commits inside one second must retry, which no real worker
    # does.
    if committed_at <= claimed_second:
        return CorrelationFailure(
            "commit_predates_run",
            f"{commit} was committed at {committed_at}, not strictly after the Run was "
            f"claimed at {claimed_second} (same-second commits are refused: a one-second "
            "timestamp resolution cannot order them against the claim)",
            "A pre-existing or same-second commit is not verifiably this Run's work; "
            "the Run landed nothing that can be ordered after its claim.")

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

    # The approved scope, resolved fail-closed at every step. There is no
    # "unrestricted" outcome: a mutating Run either has a readable approved
    # path set or it is blocked. Explicit `artifact_paths` win over prose,
    # because prose is what the parser can misread.
    permitted = tuple(getattr(run, "artifact_paths", None) or ())
    if not permitted:
        policy = getattr(run, "artifact_policy", None)
        if not policy or not str(policy).strip():
            return CorrelationFailure(
                "artifact_policy_missing",
                "the Run record carries neither approved artifact paths nor an artifact policy",
                "A mutating Run must carry the approved artifact scope on its Run record "
                "before dispatch. Nothing can be checked against an absent policy.")
        permitted = policy_paths(policy)
        if not permitted:
            return CorrelationFailure(
                "artifact_policy_unparsable",
                "the approved artifact policy names no path this gate can read",
                "Name the permitted paths in backticks in the issue's artifact policy "
                "(for example `docs/agents/work-launcher.md` or `LICENSE`), or record "
                "them explicitly as artifact_paths on the approved request.")
    unsafe_permitted = [p for p in permitted if normalize_repo_path(p) is None]
    if unsafe_permitted:
        return CorrelationFailure(
            "artifact_policy_unsafe_path",
            "the approved artifact scope contains entries that are not repository-relative "
            "paths: " + ", ".join(sorted(unsafe_permitted)),
            "An absolute path, a drive letter, or a `..` segment cannot bound a commit. "
            "Correct the approved scope.")
    unsafe_files = [path for path in files if normalize_repo_path(path) is None]
    if unsafe_files:
        return CorrelationFailure(
            "artifact_path_unsafe",
            f"{commit} touches paths that are not repository-relative: "
            + ", ".join(sorted(unsafe_files)),
            "A commit whose paths cannot be normalized cannot be bounded by any policy.")
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
