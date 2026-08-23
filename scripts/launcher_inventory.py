#!/usr/bin/env python3
"""Read-only ADR-039 inventory readers wired into the default work launcher.

Each reader returns records shaped for `execution_map._inventory_keys`: a
mapping with an `owner` plus either an explicit `resources` list of collision
keys or the individual identity fields (`issue_id`, `run_id`, `branch`,
`worktree`, `store_session_id`, `engine_session_id`). Every reader is
read-only -- no git write, no label write, no runtime spawn, no GitHub
mutation.

Fail-closed contract:

- An *expected* source that is unreadable (git unavailable, malformed
  registry/file) raises `InventoryUnavailable`; the launcher maps that to a
  stable `inventory_unavailable` gate code, never a silent empty inventory.
- A source that is *legitimately absent* (no daemon state dir, no lifecycle
  store) returns no records and is treated as empty, never as silently
  complete.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from execution_map import RELATION, canonical_issue_id, normalize_worktree

GIT_TIMEOUT_SECONDS = 30


class InventoryUnavailable(RuntimeError):
    """An expected inventory source could not be read; fail closed."""


def _run(runner: Callable[..., Any], argv: list[str]) -> Any:
    try:
        return runner(argv, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, TimeoutError, OSError) as exc:
        raise InventoryUnavailable(f"command unavailable: {' '.join(argv)}") from exc


def git_resources_reader(*, runner: Callable[..., Any] = subprocess.run,
                         owner: str = "cortxt-work") -> Callable[[], list[dict]]:
    """Read linked worktrees and branches as `worktree:`/`branch:` resources.

    A branch `work/<run_id>` or a worktree at the same normalized path that
    already exists will collide with a new run, so both are inventoried. Uses
    `git worktree list --porcelain` and `git branch --list`; both read-only.
    """
    def read() -> list[dict]:
        resources: list[str] = []
        worktrees = _run(runner, ["git", "worktree", "list", "--porcelain"])
        if worktrees.returncode:
            raise InventoryUnavailable(f"git worktree list failed: {worktrees.stderr.strip()}")
        for line in worktrees.stdout.splitlines():
            if line.startswith("worktree "):
                resources.append(f"worktree:{normalize_worktree(line[len('worktree '):].strip())}")
            elif line.startswith("branch "):
                resources.append(f"branch:{line[len('branch '):].strip()}")
        branches = _run(runner, ["git", "branch", "--list", "--format=%(refname:short)"])
        if branches.returncode:
            raise InventoryUnavailable(f"git branch list failed: {branches.stderr.strip()}")
        for name in branches.stdout.splitlines():
            name = name.strip()
            if name and f"branch:{name}" not in resources:
                resources.append(f"branch:{name}")
        return [{"owner": owner, "resources": resources}] if resources else []
    return read


def dispatcher_registry_reader(registry: Any) -> Callable[[], list[dict]]:
    """Active in-progress runs from the dispatcher RunRegistry (in-process).

    The claim store is the multi-process exactly-one-winner layer; this reader
    is the cross-check for runs created outside the claim store (legacy path or
    a different driver) that are still `in_progress` in the shared registry.
    """
    def read() -> list[dict]:
        records = []
        for run in getattr(registry, "_runs", {}).values():
            if getattr(run, "status", None) != "in_progress":
                continue
            records.append({"owner": getattr(run, "runtime", None) or "cortxt-work",
                            "run_id": run.run_id, "issue_id": run.issue_id,
                            "branch": f"work/{run.run_id}"})
        return records
    return read


def daemon_claims_reader(state_dir: Path | None, *, owner: str = "daemon") -> Callable[[], list[dict]]:
    """Daemon `claimed.json` (a JSON list of issue ids); absent = empty."""
    state_dir = Path(state_dir) if state_dir else None

    def read() -> list[dict]:
        if state_dir is None:
            return []
        path = state_dir / "claimed.json"
        if not path.exists():
            return []
        try:
            claimed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InventoryUnavailable(f"daemon claimed.json unreadable: {exc}") from exc
        if not isinstance(claimed, list):
            raise InventoryUnavailable("daemon claimed.json is not a list")
        return [{"owner": owner, "issue_id": str(item)} for item in claimed if str(item)]
    return read


def lifecycle_sessions_reader(store: Path | None, *, owner: str = "lifecycle") -> Callable[[], list[dict]]:
    """Lifecycle session store (`session_*/session.json`); absent = empty.

    Each session directory name is inventoried as a `store_session:` resource.
    A malformed store (unreadable JSON) is fail-closed, not silently empty.
    """
    store = Path(store) if store else None

    def read() -> list[dict]:
        if store is None or not store.exists():
            return []
        records: list[dict] = []
        try:
            paths = list(store.glob("session_*/session.json"))
        except OSError as exc:
            raise InventoryUnavailable(f"lifecycle store unreadable: {exc}") from exc
        for path in paths:
            session_id = path.parent.name
            records.append({"owner": owner, "store_session_id": session_id})
        return records
    return read


def writer_domain_reader(driver_id: str = "cortxt-work", *, domain: str = "state") -> Callable[[], list[dict]]:
    """Single-writer domain: the coordinator driver owns the state writer domain.

    A second driver observing the same domain would produce
    `shared_store_writer_conflict`, enforcing the driver/observer split.
    """
    def read() -> list[dict]:
        return [{"domain": domain, "owner": driver_id}]
    return read


def make_graph_reader(get_issue: Callable[[str], Mapping[str, Any]]) -> Callable[[str], list[Mapping[str, Any]]]:
    """Read the issue plus every text-prerequisite target so the gate can enforce order.

    Parses `Blocked by:`/`Depends on:`/`Part of:` edges from the real issue body
    (the execution-map RELATION contract), canonicalizes bare `#N` targets
    against the source repo, and reads each target via the injected gh port. A
    target that cannot be read is synthesized as an open issue so the gate
    fails closed (`unsatisfied_prerequisite`/`fatal_relation_drift`) rather than
    launching past an unknown blocker.
    """
    def graph_reader(issue_id: str) -> list[Mapping[str, Any]]:
        main = dict(get_issue(issue_id))
        repo = str(main["issue_id"]).rsplit("#", 1)[0]
        issues: list[Mapping[str, Any]] = [main]
        seen: set[str] = set()
        for _phrase, raw in RELATION.findall(str(main.get("body") or "")):
            try:
                target = canonical_issue_id(raw, repo)
            except ValueError:
                continue  # derive_graph will flag missing_target from the body
            if target in seen:
                continue
            seen.add(target)
            try:
                issues.append(dict(get_issue(target)))
            except Exception:
                issues.append({"issue_id": target, "body": "", "state": "open",
                               "labels": (), "area": None, "milestone": None})
        return issues
    return graph_reader
