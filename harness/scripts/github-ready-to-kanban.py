#!/usr/bin/env python3
"""
Mirror GitHub issues labeled `workflow:ready` into Hermes Kanban tasks.

This is the direction that never existed before 2026-08-18: the archived
mirror scripts (mirror-kanban-to-github.py, kanban-buzz-push.py) only ever
went Kanban -> GitHub / Kanban -> Buzz. GitHub -> Kanban was always a manual
`hermes kanban create` step. This script closes that gap, following the same
state-file convention as the other two mirrors.

Boundaries
----------
- Only creates Kanban tasks for issues labeled `workflow:ready`. Never
  touches issue state, never moves labels, never comments.
- Assignee is taken from the issue's `agent:*` label (agent:researcher ->
  researcher, agent:builder -> builder). Issues without a recognized
  agent:* label are skipped and logged, not guessed.
- Idempotent: uses `issue-<number>` as the Kanban idempotency key, so
  re-running never creates duplicates.
- No network call / no kanban write when nothing new (stdout stays empty
  so a cron watchdog stays silent), matching kanban-buzz-push.py's contract.

Usage:
    python harness/scripts/github-ready-to-kanban.py --dry-run
    python harness/scripts/github-ready-to-kanban.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = "rian010194/cortxt"
STATE_FILE = os.path.expandvars(
    r"$LOCALAPPDATA\hermes\kanban\boards\cortxt-cp\.github-imported.json"
)
AGENT_LABEL_TO_ASSIGNEE = {
    "agent:researcher": "researcher",
    "agent:builder": "builder",
}


def load_state() -> set:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_state(imported: set) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(imported), f, indent=2)


def get_ready_issues() -> list[dict]:
    result = subprocess.run(
        [
            "gh", "issue", "list", "--repo", REPO,
            "--label", "workflow:ready", "--state", "open",
            "--json", "number,title,body,labels",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR listing issues: {result.stderr}", file=sys.stderr)
        return []
    return json.loads(result.stdout)


def resolve_assignee(labels: list[dict]) -> str | None:
    names = {l["name"] for l in labels}
    for label, assignee in AGENT_LABEL_TO_ASSIGNEE.items():
        if label in names:
            return assignee
    return None


def create_kanban_task(issue: dict, assignee: str, dry_run: bool) -> bool:
    title = issue["title"]
    number = issue["number"]
    body = f"issue: {REPO}#{number} — imported from GitHub workflow:ready."
    idem_key = f"issue-{number}"

    if dry_run:
        print(f"WOULD CREATE: #{number} '{title}' -> assignee={assignee}")
        return True

    cmd = [
        "hermes", "kanban", "create", title,
        "--assignee", assignee,
        "--workspace", r"worktree:C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane",
        "--branch", f"hermes/issue-{number}",
        "--body", body,
        "--idempotency-key", idem_key,
        "--json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR creating kanban task for #{number}: {result.stderr}", file=sys.stderr)
        return False
    print(f"OK: created kanban task for #{number} '{title}' (assignee={assignee})")
    return True


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    imported = load_state()
    issues = get_ready_issues()

    new_imports = set()
    for issue in issues:
        number = issue["number"]
        key = f"issue-{number}"
        if key in imported:
            continue
        assignee = resolve_assignee(issue.get("labels", []))
        if assignee is None:
            print(
                f"SKIP #{number} '{issue['title']}': no recognized agent:* label",
                file=sys.stderr,
            )
            continue
        if create_kanban_task(issue, assignee, dry_run):
            new_imports.add(key)

    if new_imports and not dry_run:
        save_state(imported | new_imports)

    return 0


if __name__ == "__main__":
    sys.exit(main())
