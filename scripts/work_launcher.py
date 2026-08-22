#!/usr/bin/env python3
"""Operator-facing parallel work launcher built on the dispatch contract."""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from dispatcher import Dispatcher, RunRegistry
from worker_adapters import dispatch_async

FORBIDDEN = re.compile(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]")
DEFAULT_ARTIFACT_POLICY = (
    "Commit only English project artifacts on a feature branch. Do not push, merge, "
    "close issues, expose secrets, copy full prompts, or record model reasoning."
)


class LauncherGitHub:
    """Small injectable GitHub port used by the launcher."""

    def create_issue(self, repo: str, title: str, body: str) -> str:
        proc = subprocess.run(
            ["gh", "issue", "create", "-R", repo, "--title", title, "--body", body,
             "--label", "workflow:inbox"], capture_output=True, text=True, timeout=20,
        )
        if proc.returncode:
            raise RuntimeError(proc.stderr.strip())
        number = proc.stdout.strip().rstrip("/").split("/")[-1]
        return f"{repo}#{number}"

    def approve(self, issue_id: str) -> None:
        repo, number = issue_id.split("#", 1)
        proc = subprocess.run(
            ["gh", "issue", "edit", number, "-R", repo, "--remove-label", "workflow:inbox",
             "--add-label", "workflow:ready"], capture_output=True, text=True, timeout=20,
        )
        if proc.returncode:
            raise RuntimeError(proc.stderr.strip())


def generate_worker_prompt(scope: str, acceptance_criteria: list[str], limits: dict,
                           artifact_policy: str = DEFAULT_ARTIFACT_POLICY) -> str:
    """Render the approved, content-limited worker handoff."""
    values = [scope, artifact_policy, *acceptance_criteria]
    if any(FORBIDDEN.search(value or "") for value in values):
        raise ValueError("scope content must contain only English ASCII letters")
    if not scope.strip() or not acceptance_criteria:
        raise ValueError("scope and acceptance criteria are required")
    limit_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(limits.items()))
    ac_lines = "\n".join(f"- {item}" for item in acceptance_criteria)
    return (
        "You are a bounded worker.\n\nScope\n-----\n" + scope.strip() +
        "\n\nAcceptance criteria\n-------------------\n" + ac_lines +
        "\n\nLimits\n------\n" + limit_lines +
        "\n\nArtifact policy\n---------------\n" + artifact_policy + "\n"
    )


def parse_scope_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if FORBIDDEN.search(text):
        raise ValueError("scope file contains forbidden diacritics")
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
    marker = "## Acceptance criteria"
    before, sep, after = text.partition(marker)
    criteria = [line[2:].strip() for line in after.splitlines() if line.startswith("- ")] if sep else []
    scope = before.replace(f"# {title}", "", 1).strip()
    return {"title": title, "scope": scope, "acceptance_criteria": criteria}


class WorkLauncher:
    def __init__(self, dispatcher: Dispatcher, github: LauncherGitHub,
                 dispatch: Callable = dispatch_async, worktree_root: Path | None = None,
                 run_worktree: Callable[..., object] = subprocess.run):
        self.dispatcher = dispatcher
        self.github = github
        self.dispatch = dispatch
        self.worktree_root = worktree_root or Path(".worktrees")
        self.run_worktree = run_worktree

    def create(self, repo: str, title: str, scope: str, acceptance_criteria: list[str], *,
               runtime: str, worker_role: str, workflow: str, max_runtime_seconds: int,
               max_cost_usd: float, approved: bool) -> dict:
        if not approved:
            raise ValueError("operator approval is required before claim and dispatch")
        limits = {"max_cost_usd": max_cost_usd, "max_runtime_seconds": max_runtime_seconds,
                  "max_parallel_workers": "operator policy", "delegation_depth": 0}
        prompt = generate_worker_prompt(scope, acceptance_criteria, limits)
        body = f"## Scope\n\n{scope}\n\n## Acceptance criteria\n\n" + "\n".join(f"- {x}" for x in acceptance_criteria)
        issue_id = self.github.create_issue(repo, title, body)
        self.github.approve(issue_id)
        run = self.dispatcher.claim(issue_id, workflow, worker_role, runtime, max_runtime_seconds)
        branch = f"work/{run.run_id}"
        worktree = self.worktree_root / run.run_id
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        proc = self.run_worktree(["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"],
                                 capture_output=True, text=True)
        if getattr(proc, "returncode", 0):
            self.dispatcher.complete(run.run_id, "blocked", {"error": "isolated worktree creation failed"})
            raise RuntimeError("isolated worktree creation failed")
        self.dispatch(self.dispatcher, run, prompt)
        return {"issue_id": issue_id, "run_id": run.run_id, "worktree": str(worktree), "branch": branch}

    def resume(self, issue_id: str, *, runtime: str, worker_role: str, workflow: str,
               max_runtime_seconds: int, prompt: str) -> dict:
        run = self.dispatcher.claim(issue_id, workflow, worker_role, runtime, max_runtime_seconds)
        self.dispatch(self.dispatcher, run, prompt)
        return {"issue_id": issue_id, "run_id": run.run_id}

    def submit(self, run_id: str, result: dict) -> dict:
        run = self.dispatcher.complete(run_id, result["status"], result)
        return {"issue_id": run.issue_id, "run_id": run.run_id, "status": run.status}

    def list_active(self) -> list[dict]:
        now = time.time()
        rows = []
        for run in self.dispatcher.registry._runs.values():
            if run.status != "in_progress":
                continue
            row = asdict(run)
            row.update(elapsed_seconds=now - run.claimed_at, last_update=run.heartbeat_at,
                       worker=run.worker_role)
            rows.append(row)
        return sorted(rows, key=lambda item: item["claimed_at"])


def default_launcher(registry_path: Path) -> WorkLauncher:
    return WorkLauncher(Dispatcher(RunRegistry(registry_path)), LauncherGitHub())
