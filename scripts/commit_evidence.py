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
    # The whole change the Run contributed on top of its recorded base (#509),
    # so the durable record describes what the Run landed rather than the one
    # commit its envelope happened to present.
    base_commit: Optional[str] = None
    contributed_commits: tuple = ()
    contributed_files: tuple = ()

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
            "base_commit": self.base_commit,
            "contributed_commits": list(self.contributed_commits),
            "contributed_files": list(self.contributed_files),
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


def _commit_files(git, sha):
    """`(files, failure)` for one commit: the paths it changed, or why not."""
    code, out = git(["show", "--name-only", "--format=", sha])
    if code != 0:
        return None, ("commit_files_unreadable",
                      f"could not list the files changed by {sha}",
                      "Re-run the gate against a readable repository.")
    files = tuple(line.strip() for line in out.splitlines() if line.strip())
    if not files:
        return None, ("no_files_changed", f"{sha} changes no files",
                      "An empty commit is not an artifact; the Run produced nothing to review.")
    return files, None


def _commit_basics(git, sha, claimed_second):
    """The per-commit rules that need no artifact policy: `((files, committed_at), failure)`.

    Split from the scope check so the presented commit is still judged in the
    order it was before #509 -- an empty commit is `no_files_changed` whatever
    the policy says, and an unparsable policy does not preempt it.
    """
    code, out = git(["show", "-s", "--format=%ct", sha])
    if code != 0 or not out.strip().isdigit():
        return None, ("commit_time_unreadable",
                      f"could not read the commit timestamp of {sha}",
                      "Re-run the gate against a readable repository.")
    committed_at = int(out.strip())
    if committed_at <= claimed_second:
        return None, ("commit_predates_run",
                      f"{sha} was committed at {committed_at}, not strictly after the Run was "
                      f"claimed at {claimed_second} (same-second commits are refused: a one-second "
                      "timestamp resolution cannot order them against the claim)",
                      "A pre-existing or same-second commit is not verifiably this Run's work; "
                      "the Run landed nothing that can be ordered after its claim.")

    code, message = git(["show", "-s", "--format=%B", sha])
    if code != 0:
        return None, ("commit_message_unreadable",
                      f"could not read the commit message of {sha}",
                      "Re-run the gate against a readable repository.")
    if not DCO_RE.search(message):
        return None, ("dco_trailer_missing", f"{sha} carries no `Signed-off-by:` trailer",
                      "Every landed commit must carry a DCO sign-off; amend the commit and re-run.")

    files, failure = _commit_files(git, sha)
    if failure is not None:
        return None, failure
    return (files, committed_at), None


def _verify_commit_scope(sha, files, permitted):
    """The approved-scope half: `failure` or None.

    Applied to *every* commit the Run contributed, not only the one a result
    envelope happens to present (#509). A commit that breaches the approved
    scope must block the Run whichever commit is offered as its evidence.
    """
    unsafe_files = [path for path in files if normalize_repo_path(path) is None]
    if unsafe_files:
        return ("artifact_path_unsafe",
                f"{sha} touches paths that are not repository-relative: "
                + ", ".join(sorted(unsafe_files)),
                "A commit whose paths cannot be normalized cannot be bounded by any policy.")
    outside = [path for path in files if not _within(path, permitted)]
    if outside:
        return ("artifact_policy_violation",
                f"{sha} touches paths outside the approved artifact policy: "
                + ", ".join(sorted(outside)),
                f"The approved policy permits only {', '.join(permitted)}. "
                "Re-run within scope.")
    return None


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

    # The presented commit's policy-free rules first, so an empty commit is
    # still `no_files_changed` and an unreadable timestamp still
    # `commit_time_unreadable`, whatever the policy says.
    claimed_second = int(getattr(run, "claimed_at", 0))
    verified, failure = _commit_basics(git, commit, claimed_second)
    if failure is not None:
        return CorrelationFailure(*failure)
    files, committed_at = verified

    # The approved scope, resolved fail-closed. Every commit in the contributed
    # range is measured against it. There is no "unrestricted" outcome: a
    # mutating Run either
    # has a readable approved path set or it is blocked. Explicit
    # `artifact_paths` win over prose, because prose is what the parser can
    # misread.
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

    failure = _verify_commit_scope(commit, files, permitted)
    if failure is not None:
        return CorrelationFailure(*failure)

    # #509: the presented commit passing is not the Run passing. The artifact
    # policy, the DCO trailer and the strictly-after-claim ordering used to be
    # checked against ONE commit's file list, so a Run could land commit A
    # outside the approved scope and then commit B inside it, present B, and
    # have the gate record `commit_correlated` while the branch that becomes a
    # pull request carried A. Multiple commits are legitimate; hiding one
    # behind another is not. Every commit the Run contributed on top of its
    # recorded base is now held to the same rules, and one breach blocks the
    # Run whichever commit is offered as its evidence.
    base = getattr(run, "base_commit", None)
    if not isinstance(base, str) or not SHA_RE.fullmatch(base.strip().lower()):
        return CorrelationFailure(
            "base_commit_not_recorded",
            f"the Run record carries no usable base_commit (got {base!r})",
            "A mutating Run must record the commit its branch was created from, so the "
            "gate can verify everything the Run contributed rather than one commit of it. "
            "Re-launch it through the sanctioned path.")
    base = base.strip().lower()

    code, out = git(["cat-file", "-t", base])
    if code != 0 or out.strip() != "commit":
        return CorrelationFailure(
            "base_commit_not_found",
            f"{base} is not a commit object in this repository",
            "The Run's recorded base does not exist here, so the contributed change "
            "cannot be bounded. Treat the result as unproven.")
    code, _ = git(["merge-base", "--is-ancestor", base, f"refs/heads/{branch}"])
    if code != 0:
        return CorrelationFailure(
            "branch_not_from_recorded_base",
            f"refs/heads/{branch} does not descend from the recorded base {base}",
            "The Run's branch was rewritten, or is not the branch its base was recorded "
            "for; a range computed from that base would not describe what the Run did.")

    code, out = git(["rev-list", f"{base}..refs/heads/{branch}"])
    if code != 0:
        return CorrelationFailure(
            "contributed_range_unreadable",
            f"could not list the commits between {base} and refs/heads/{branch}",
            "Re-run the gate against a readable repository.")
    contributed = tuple(line.strip().lower() for line in out.splitlines() if line.strip())
    if not contributed:
        return CorrelationFailure(
            "no_contributed_commits",
            f"refs/heads/{branch} is unchanged from its recorded base {base}",
            "The Run landed nothing on its own branch; there is no contributed change "
            "to verify.")
    if commit not in contributed:
        return CorrelationFailure(
            "commit_not_contributed_by_run",
            f"{commit} is reachable from refs/heads/{branch} but is not among the commits "
            f"the Run added on top of {base}",
            "The presented commit predates this Run's base; it is inherited history, not "
            "this Run's output.")

    contributed_files: list = []
    for sha in contributed:
        if sha == commit:
            contributed_files.extend(files)
            continue
        verified_other, failure = _commit_basics(git, sha, claimed_second)
        if failure is None:
            failure = _verify_commit_scope(sha, verified_other[0], permitted)
        if failure is not None:
            failed_code, detail, recovery = failure
            # Distinguished from the presented commit's own failure, so a
            # reviewer can tell "the commit you showed me is bad" from
            # "another commit on this branch is bad".
            return CorrelationFailure(f"contributed_{failed_code}", detail, recovery)
        contributed_files.extend(verified_other[0])

    return CommitEvidence(
        run_id=run.run_id,
        issue_id=run.issue_id,
        commit=commit,
        branch=branch,
        committed_at=committed_at,
        files=files,
        verified_at=clock(),
        request_id=getattr(run, "request_id", None),
        # The Run record, never the envelope (#514). The launcher created the
        # worktree; a worker naming a different one must not redirect the
        # review that later reads this path.
        worktree=getattr(run, "worktree", None),
        policy_paths=permitted,
        base_commit=base,
        contributed_commits=contributed,
        contributed_files=tuple(sorted(set(contributed_files))),
    )


def make_commit_gate(repo_path: Optional[Path] = None,
                     clock: Callable[[], float] = time.time) -> Callable:
    """Bind the gate to a repository, for injection into `Dispatcher`."""

    def gate(run, result_envelope: dict):
        return verify_commit_correlation(run, result_envelope,
                                         repo_path=repo_path, clock=clock)
    return gate
