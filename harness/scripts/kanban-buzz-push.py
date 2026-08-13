#!/usr/bin/env python3
"""Push Hermes Kanban status changes into the Buzz operator channel.

Polls the Hermes Kanban board `cortxt-cp` and, for every task whose status has
changed since the last run, publishes one compact status line to the hosted
Vertical 01 Buzz channel by reusing `harness/scripts/buzz-return.py`.

Boundaries
----------
- This is a STATUS DISPLAY / feedback channel only. It never creates Buzz
  tasks and never dispatches work.
- No network call is made when nothing new to push (stdout stays empty so a
  cron watchdog stays silent).
- Secret handling is delegated to buzz-return.py (env / user-scope fallback,
  injected into the subprocess, never printed). We duplicate none of it.

State
-----
A JSON file (mirroring mirror-kanban-to-github.py's `.mirrored.json`
convention) records the last pushed status per task id. On first run the
current statuses are seeded as the baseline so historical cards are NOT
backfilled into the channel.

Usage:
    python harness/scripts/kanban-buzz-push.py --dry-run   # show what WOULD push
    python harness/scripts/kanban-buzz-push.py             # push new statuses
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

KANBAN_DB = os.path.expandvars(
    r"$LOCALAPPDATA\hermes\kanban\boards\cortxt-cp\kanban.db"
)
STATE_FILE = os.path.expandvars(
    r"$LOCALAPPDATA\hermes\kanban\boards\cortxt-cp\.pushed-status.json"
)
BUZZ_RETURN = Path(__file__).resolve().parent / "buzz-return.py"


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def get_tasks(db_path: str):
    """Tasks with their current run envelope, in completion order."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id, t.title, t.body, t.status, t.completed_at, t.result,
               r.summary, r.metadata, r.profile, r.started_at, r.ended_at
        FROM tasks t
        LEFT JOIN task_runs r ON t.current_run_id = r.id
        ORDER BY t.completed_at IS NULL, t.completed_at
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def extract_issue_ref(body):
    """Extract owner/repo#issue from a task body (same convention as mirror)."""
    if not body:
        return None
    m = re.search(r"(\S+/\S+)#(\d+)", body)
    if m:
        return f"{m.group(1)}#{m.group(2)}"
    m = re.search(r"github\.com/(\S+/\S+)/issues/(\d+)", body)
    if m:
        return f"{m.group(1)}#{m.group(2)}"
    return None


def extract_cost(metadata) -> str | None:
    """Pull an optional cost figure out of run metadata (est. $ / tokens)."""
    if not metadata:
        return None
    try:
        md = json.loads(metadata) if isinstance(metadata, str) else metadata
    except Exception:
        return None
    if not isinstance(md, dict):
        return None
    # Look for a top-level cost key, or nested under 'usage'/'cost'.
    for key in ("cost", "cost_usd", "estimate_cost", "estimated_cost"):
        if key in md and md[key] not in (None, ""):
            return str(md[key])
    usage = md.get("usage") if isinstance(md.get("usage"), dict) else {}
    for key in ("cost", "cost_usd", "total_cost"):
        if key in usage and usage[key] not in (None, ""):
            return str(usage[key])
    return None


def format_status(task: dict) -> str:
    tid = task["id"]
    issue = extract_issue_ref(task.get("body"))
    status = task["status"]
    title = (task.get("title") or "").strip()
    profile = task.get("profile")
    cost = extract_cost(task.get("metadata"))

    line = f"kanban {tid} → {status}"
    if issue:
        line += f" · {issue}"
    if title:
        line += f" · {title[:60]}"
    if profile:
        line += f" · profile={profile}"
    if cost:
        line += f" · cost≈{cost}"
    return line


def push_status(content: str, dry_run: bool = False) -> bool:
    """Reuse buzz-return.py's CLI so key handling is not duplicated."""
    cmd = [sys.executable, str(BUZZ_RETURN)]
    if dry_run:
        cmd.append("--dry-run")
    cmd += ["send", "--content", content]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if res.returncode == 0:
        return True
    print(f"PUSH_FAIL ({res.returncode}): {res.stderr.strip() or res.stdout.strip()}",
          file=sys.stderr)
    return False


def main(argv=None) -> int:
    dry_run = "--dry-run" in (argv if argv is not None else sys.argv[1:])

    if not os.path.exists(KANBAN_DB):
        print(f"Kanban DB not found: {KANBAN_DB}", file=sys.stderr)
        return 1

    state = load_state()
    tasks = get_tasks(KANBAN_DB)
    pushed = 0
    newly_seeded = 0
    # Dry-run is observation-only: it MUST NOT persist or mutate state, so a
    # later real run is never suppressed by a previous --dry-run (#51).
    # We compute the dry-run summary against a throwaway dict; the on-disk
    # state stays untouched until a real (non-dry-run) run saves it.
    write_state = state if not dry_run else {}

    for task in tasks:
        tid = task["id"]
        status = task["status"]

        # First sighting: seed the baseline so we never backfill history.
        if tid not in state:
            newly_seeded += 1
            if not dry_run:
                write_state[tid] = status
            continue

        if state[tid] == status:
            continue  # no change -> no network

        content = format_status(task)
        if push_status(content, dry_run=dry_run):
            pushed += 1
            if not dry_run:
                write_state[tid] = status
                print(f"PUSHED: {content}")  # stdout: only on real pushes
            else:
                print(f"[dry-run] WOULD PUSH: {content}")

    if not dry_run:
        save_state(write_state)
    # In dry-run we always print a summary; in real mode stdout stays empty
    # except for actual pushes (cron watchdog stays quiet on no-change).
    if dry_run:
        print(f"[dry-run] seeded={newly_seeded} new statuses; would push={pushed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
