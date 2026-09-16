"""Discover the repositories in a read area, with their revision state.

A discovery result that names a repository by path and stops there is worse
than no result, because it reads as complete. On 2026-09-16 none of the five
Cortxt repositories was on `main`, and local `main` in the primary checkout
was four days behind GitHub and did not contain that day's work. A proposal
built on "the repository is at <path>" would have been confidently wrong
about every one of them. Path alone is insufficient; the revision state is
what makes a proposal explainable.

So every observation carries what was actually established -- branch, head,
dirty state, origin URL, the local `origin/main` ref -- and, in ``caveats``,
plain language for every fact it could *not* establish. A field that could
not be determined is ``None`` with a caveat beside it. Never a guess, never
an empty string standing in for a value, never a default that reads like an
answer.

``caveats`` is the point of this module. The most important entry is the one
attached to ``origin_main_ref``: it is a *local* ref reflecting whatever the
last fetch brought down, never verified against the remote, and the remote may
be arbitrarily far ahead. That is precisely the trap of 2026-09-16, and a
consumer reading the field without the caveat would walk back into it.

**No network. Ever.** No `git fetch`, no `git ls-remote`, no remote call of
any kind, no HTTP. Discovery must be fast and must work offline, and a
network call would also make the `origin/main` caveat above a lie by
appearing to resolve it. Every subprocess call passes ``encoding="utf-8"``:
the repository's own convention, and the exact defect fixed in commit
5c44425 was its absence.

**Read is not write.** Nothing here mutates a repository, and nothing here
produces an allowlist, a write target, or any other record that could later
be read as permission. Every git subcommand used is a read.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

# Long enough for a cold filesystem cache on a large repository, short enough
# that one wedged repository cannot stall a discovery over a whole workspace.
GIT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class RepoObservation:
    """One repository as it was observed locally, with what stayed unknown.

    Every optional field is ``None`` exactly when it could not be
    established, and every such ``None`` has a matching entry in ``caveats``.
    """

    path: Path
    name: str
    origin_url: str | None
    branch: str | None
    head: str | None
    dirty: bool | None
    origin_main_ref: str | None
    caveats: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryCaps:
    """Bounds on the scan, so a mistyped root cannot walk a whole disk.

    ``max_depth`` is counted below each root: a root that is itself a
    repository is depth 0. ``max_repositories`` truncates the result, and
    truncation is always reported as a caveat -- never silently.

    The caps are validated on construction, because that promise is only
    keepable for caps that can produce a reportable result. A truncation
    caveat has to ride on an observation -- the return type is a list, with
    nowhere to put a result-level flag -- so a cap below 1 would truncate
    before anything existed to carry the notice, and the caller would get an
    empty list indistinguishable from an empty read area. Refusing that
    configuration is the honest answer; returning a result that cannot
    describe itself is exactly the failure this module exists to prevent.
    """

    max_depth: int = 3
    max_repositories: int = 64

    def __post_init__(self) -> None:
        if self.max_repositories < 1:
            raise ValueError(
                f"max_repositories must be at least 1, not {self.max_repositories}. "
                f"A cap below 1 truncates before any repository can be observed, "
                f"and the truncation caveat has nowhere to ride -- discovery would "
                f"return an empty list that cannot be told apart from a read area "
                f"with no repositories in it. To scan nothing, pass no roots.")
        if self.max_depth < 0:
            raise ValueError(
                f"max_depth must be zero or greater, not {self.max_depth}. "
                f"Depth is counted below each root, so 0 already means 'look at "
                f"the roots themselves and descend no further'; a negative value "
                f"silently behaves as 0 rather than meaning anything of its own.")


def _git(runner, path: Path, *args: str) -> tuple[bool, str]:
    """Run one read-only git command in ``path``.

    Returns ``(ok, text)``. ``ok`` is False for a missing git binary, a
    non-zero exit, or a timeout -- the caller turns that into ``None`` plus a
    caveat rather than into a guess.

    ``-C`` rather than ``cwd`` so the command names the repository it reads
    explicitly, and ``encoding="utf-8"`` on every call: without it Python
    decodes subprocess output with the platform code page (cp1252 here),
    which is the defect commit 5c44425 fixed.
    """
    try:
        proc = runner(["git", "-C", str(path), *args], capture_output=True,
                      text=True, encoding="utf-8", errors="replace",
                      timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if getattr(proc, "returncode", 1) != 0:
        return False, (getattr(proc, "stderr", "") or "").strip()
    return True, (getattr(proc, "stdout", "") or "")


def _observe(path: Path, runner) -> RepoObservation:
    """Gather one repository's revision state, locally and offline only."""
    caveats: list[str] = []

    ok_branch, branch_text = _git(runner, path, "rev-parse", "--abbrev-ref", "HEAD")
    branch: str | None = branch_text.strip() if ok_branch else None
    if not ok_branch:
        caveats.append(
            "The current branch could not be read, so which branch this "
            f"repository is on is unknown (git rev-parse --abbrev-ref HEAD "
            f"failed: {branch_text or 'no detail'}).")
        branch = None
    elif branch == "HEAD":
        # Detached HEAD. "HEAD" is git's answer, not a branch name; reporting
        # it as one would name a branch that does not exist.
        branch = None
        caveats.append(
            "HEAD is detached: this repository is not on any branch, so there "
            "is no branch name to report.")
    elif not branch:
        branch = None
        caveats.append("The current branch read returned nothing, so the branch is unknown.")

    ok_head, head_text = _git(runner, path, "rev-parse", "HEAD")
    head: str | None = head_text.strip() if ok_head else None
    if not head:
        head = None
        caveats.append(
            "The checked-out commit could not be read, so what this working "
            f"copy actually contains is unknown (git rev-parse HEAD failed: "
            f"{head_text.strip() or 'no detail'}). This usually means the "
            f"repository has no commits yet.")

    ok_origin, origin_text = _git(runner, path, "remote", "get-url", "origin")
    origin_url: str | None = origin_text.strip() if ok_origin else None
    if not origin_url:
        origin_url = None
        caveats.append(
            "No 'origin' remote could be read, so this repository's "
            "relationship to any hosted copy is unknown.")

    ok_status, status_text = _git(runner, path, "status", "--porcelain")
    dirty: bool | None
    if ok_status:
        dirty = bool(status_text.strip())
        if dirty:
            caveats.append(
                "The working copy is dirty: it has uncommitted changes, so its "
                "contents do not match the commit named by 'head'. Anything "
                "reasoned from the commit alone may not describe what is on disk.")
    else:
        dirty = None
        caveats.append(
            "The working-copy state could not be read, so whether there are "
            f"uncommitted changes is unknown (git status --porcelain failed: "
            f"{status_text or 'no detail'}).")

    ok_main, main_text = _git(runner, path, "rev-parse", "--verify", "--quiet",
                              "refs/remotes/origin/main")
    origin_main_ref: str | None = main_text.strip() if ok_main else None
    if origin_main_ref:
        # The caveat this whole module exists for. See the module docstring.
        caveats.append(
            "'origin_main_ref' is a LOCAL ref (refs/remotes/origin/main). It "
            "reflects whatever the last fetch brought down and has NOT been "
            "verified against the remote -- discovery makes no network calls. "
            "The real origin/main may be ahead of it by any amount, so this "
            "commit is not evidence of what is on the remote now.")
    else:
        origin_main_ref = None
        caveats.append(
            "There is no local refs/remotes/origin/main, so this repository's "
            "relation to 'main' cannot be established locally at all -- not "
            "even approximately. Determining it would require a network call, "
            "which discovery deliberately does not make.")

    return RepoObservation(
        path=path, name=path.name, origin_url=origin_url, branch=branch,
        head=head, dirty=dirty, origin_main_ref=origin_main_ref,
        caveats=tuple(caveats))


def _is_repository(path: Path) -> bool:
    """True when ``path`` holds a ``.git`` entry.

    A file counts as well as a directory: a linked worktree's ``.git`` is a
    file containing a gitdir pointer, and treating only directories as
    repositories would make every worktree invisible -- exactly the
    repositories a Cortxt workspace has most of.
    """
    try:
        return (path / ".git").exists()
    except OSError:  # pragma: no cover - permission or transient IO
        return False


def _children(path: Path) -> list[Path]:
    """Sub-directories of ``path``, sorted, so discovery is deterministic."""
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    kept = []
    for entry in entries:
        try:
            if entry.is_dir() and not entry.is_symlink():
                kept.append(entry)
        except OSError:  # pragma: no cover - transient IO
            continue
    return kept


def discover_repositories(roots: Iterable[Path] | Sequence[Path], *,
                          caps: DiscoveryCaps = DiscoveryCaps(),
                          runner: Callable[..., object] | None = None,
                          ) -> list[RepoObservation]:
    """Every repository beneath ``roots``, each with its revision state.

    A repository is a directory containing a ``.git`` entry (file or
    directory). Discovery does not descend into one once found: the
    repository is the unit, and its own subdirectories are its contents, not
    further repositories.

    ``runner`` is injectable with ``subprocess.run``'s signature so tests
    never shell out. It defaults to ``subprocess.run``.

    An empty ``roots`` yields an empty list. That is the unconfigured state,
    not a failure -- nothing is gated on having a read area.
    """
    runner = subprocess.run if runner is None else runner
    observations: list[RepoObservation] = []
    truncated = False

    for root in roots:
        if truncated:
            break
        root = Path(root)
        # (directory, depth below this root)
        queue: list[tuple[Path, int]] = [(root, 0)]
        while queue:
            current, depth = queue.pop(0)
            if _is_repository(current):
                # The cap is tested here, against a repository actually found,
                # rather than at the top of the loop. Testing it earlier would
                # report truncation whenever the queue still held directories
                # that turned out to contain nothing -- a complete result
                # labelled incomplete is its own dishonesty.
                if len(observations) >= caps.max_repositories:
                    truncated = True
                    break
                observations.append(_observe(current, runner))
                # Deliberately no descent: what is inside a repository is its
                # contents, not more repositories.
                continue
            if depth >= caps.max_depth:
                continue
            queue.extend((child, depth + 1) for child in _children(current))

    if truncated:
        # Truncation is reported, never silent: a caller that could not tell a
        # complete result from a capped one would reason about a workspace it
        # only partly saw. It rides on the last observation because that is
        # the only channel this return type has.
        note = (f"Discovery stopped at the cap of {caps.max_repositories} "
                f"repositories. This result is TRUNCATED -- there are further "
                f"repositories in the read area that were not observed, and "
                f"the ones missing are not knowable from this result. Raise "
                f"max_repositories or narrow the read area.")
        # Unconditional, and safe because DiscoveryCaps refuses a cap below 1:
        # `truncated` can only be set after at least one observation has been
        # appended, so there is always something to carry the notice. This was
        # guarded by `if observations:` before, which silently dropped the
        # notice in exactly the state that guard was hiding. A dead branch that
        # swallows the truncation marker is worse than an IndexError: if the
        # invariant above ever breaks, this must fail loudly rather than return
        # an empty list that reads as an empty read area.
        last = observations[-1]
        observations[-1] = RepoObservation(
            path=last.path, name=last.name, origin_url=last.origin_url,
            branch=last.branch, head=last.head, dirty=last.dirty,
            origin_main_ref=last.origin_main_ref,
            caveats=last.caveats + (note,))

    return observations
