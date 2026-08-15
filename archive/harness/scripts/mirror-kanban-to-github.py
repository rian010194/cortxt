#!/usr/bin/env python3
"""
Mirror Hermes Kanban completed tasks to GitHub issue comments.

This script polls the kanban board for 'done' tasks that have not yet been
mirrored to GitHub, and posts a result envelope as a comment on the
corresponding GitHub issue.

Run manually or via cron.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

KANBAN_DB = os.path.expandvars(r"$LOCALAPPDATA\hermes\kanban\boards\cortxt-cp\kanban.db")
STATE_FILE = os.path.expandvars(r"$LOCALAPPDATA\hermes\kanban\boards\cortxt-cp\.mirrored.json")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()

def save_state(mirrored):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(mirrored), f, indent=2)

def get_done_tasks(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT t.id, t.title, t.body, t.status, t.assignee,
               t.completed_at, t.result,
               r.summary, r.metadata, r.started_at, r.ended_at
        FROM tasks t
        LEFT JOIN task_runs r ON t.current_run_id = r.id
        WHERE t.status = 'done'
        ORDER BY t.completed_at
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def extract_issue_ref(body):
    """Extract owner/repo#issue from task body."""
    if not body:
        return None
    m = re.search(r'(\S+/\S+)#(\d+)', body)
    if m:
        return m.group(1), int(m.group(2))
    m = re.search(r'github\.com/(\S+/\S+)/issues/(\d+)', body)
    if m:
        return m.group(1), int(m.group(2))
    return None

def post_comment(repo, issue_num, body_text):
    """Post a comment via gh CLI."""
    cmd = ["gh", "issue", "comment", str(issue_num), "--repo", repo, "--body", body_text]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR posting to {repo}#{issue_num}: {result.stderr}")
        return False
    print(f"OK: posted to {repo}#{issue_num}")
    return True

def format_comment(task):
    result = task.get("result") or "(no result)"
    summary = task.get("summary") or ""
    metadata = task.get("metadata") or "{}"
    started = task.get("started_at") or "?"
    finished = task.get("ended_at") or "?"
    assignee = task.get("assignee") or "?"

    try:
        md = json.loads(metadata)
        meta_str = "\n".join(f"- {k}: {v}" for k, v in md.items())
    except Exception:
        meta_str = f"- metadata: {metadata}"

    body = f"""## 📋 Kanban Run Complete

**Task:** `{task['id']}` — {task['title']}
**Assignee:** {assignee}
**Started:** {started}
**Finished:** {finished}

### Result
{result}

### Summary
{summary}

### Metadata
{meta_str}

---
*Mirrored automatically from Hermes Kanban `cortxt-cp`.*
"""
    return body

def main():
    if not os.path.exists(KANBAN_DB):
        print(f"Kanban DB not found: {KANBAN_DB}")
        sys.exit(1)

    mirrored = load_state()
    tasks = get_done_tasks(KANBAN_DB)
    new_mirrors = 0

    for task in tasks:
        tid = task["id"]
        if tid in mirrored:
            continue

        ref = extract_issue_ref(task.get("body", ""))
        if not ref:
            print(f"SKIP {tid}: no GitHub issue reference in body")
            mirrored.add(tid)
            continue

        repo, issue_num = ref
        comment_body = format_comment(task)
        if post_comment(repo, issue_num, comment_body):
            mirrored.add(tid)
            new_mirrors += 1
        else:
            print(f"FAIL {tid}: will retry next run")

    save_state(mirrored)
    print(f"Done. Mirrored {new_mirrors} new task(s). Total mirrored: {len(mirrored)}.")

if __name__ == "__main__":
    main()
