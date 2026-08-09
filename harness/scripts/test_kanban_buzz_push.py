#!/usr/bin/env python3
"""Deterministic regression tests for #51: --dry-run must be fully
non-mutating.

Covered behaviours:
  1. --dry-run must NOT create or change the persistent state file.
  2. A later real (non-dry-run) run must NOT be suppressed by an earlier
     --dry-run (the previously-seeded ids must still be reported/pushed).
  3. Normal non-dry-run behaviour stays unchanged (state advances + persists).

The script under test is loaded with $LOCALAPPDATA pointed at a throwaway temp
dir, so both KANBAN_DB and STATE_FILE resolve off-test. push_status is stubbed
to return True so no network / credentials are involved. Run directly:

    python harness/scripts/test_kanban_buzz_push.py     # exit 0 = pass
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "harness" / "scripts" / "kanban-buzz-push.py"

_tmp = tempfile.mkdtemp(prefix="kanban-push-test-")
_boards = Path(_tmp) / "hermes" / "kanban" / "boards" / "cortxt-cp"
_boards.mkdir(parents=True, exist_ok=True)

# Set LOCALAPPDATA BEFORE loading the module (constants resolve at import).
os.environ["LOCALAPPDATA"] = _tmp

spec = importlib.util.spec_from_file_location("kanban_buzz_push", SCRIPT)
kbp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kbp)


def make_db(path: Path, task_ids_statuses):
    c = sqlite3.connect(path)
    c.execute("DROP TABLE IF EXISTS task_runs")
    c.execute("DROP TABLE IF EXISTS tasks")
    c.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, title TEXT, body TEXT, "
              "status TEXT, completed_at TEXT, result TEXT, current_run_id TEXT)")
    c.execute("CREATE TABLE task_runs(id TEXT PRIMARY KEY, summary TEXT, "
              "metadata TEXT, profile TEXT, started_at TEXT, ended_at TEXT)")
    for tid, st in task_ids_statuses:
        c.execute("INSERT INTO tasks VALUES(?,?,?,?,NULL,NULL,NULL)",
                  (tid, f"title-{tid}", f"https://github.com/rian010194/ai-workspace-control-plane/issues/58", st))
    c.commit(); c.close()


def state_bytes():
    p = kbp.STATE_FILE
    return Path(p).read_bytes() if os.path.exists(p) else None


def run(extra_args, push_return=True):
    """Call main(''[...]) with push_status stubbed (no network)."""
    kbp.push_status = lambda content, dry_run=False: push_return
    argv = ["prog"] + extra_args
    return kbp.main(argv)


fails = []
def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


print("== test 1: --dry-run must not create/change state ==")
db1 = kbp.KANBAN_DB
make_db(db1, [("t1", "done"), ("t2", "pending")])
# seed state as if a prior real run already saw t2=pending
os.makedirs(Path(kbp.STATE_FILE).parent, exist_ok=True)
Path(kbp.STATE_FILE).write_text(json.dumps({"t2": "pending"}))
before = state_bytes()
rc = run(["--dry-run"])
out_before = before
after = state_bytes()
check("rc=0", rc == 0, f"rc={rc}")
check("state file unchanged by --dry-run", after == before,
      f"before={before!r} after={after!r}")

print("== test 2: later real run not suppressed by earlier --dry-run ==")
# Run --dry-run again (sees t1 as NEW -- must NOT be persisted), then a REAL run.
rc = run(["--dry-run"])
mid = state_bytes()
check("dry-run still leaves state unchanged", mid == out_before)
rc_real = run([])   # real mode, stubbed push returns True
real_after = json.loads(state_bytes() or "{}")
check("real run persists state (rc=0)", rc_real == 0, f"rc={rc_real}")
# t1 was NEW and must now be present + advanced to 'done' (not suppressed)
check("real run advanced t1 (not suppressed by prior dry-run)",
      real_after.get("t1") == "done", repr(real_after))

print("== test 3: normal non-dry-run behaviour unchanged ==")
# fresh DB: t3 pending, then change t3 to done, run real -> state advances
db3 = kbp.KANBAN_DB
make_db(db3, [("t3", "done")])
Path(kbp.STATE_FILE).write_text(json.dumps({"t3": "pending"}))
rc = run([])
after3 = json.loads(state_bytes())
check("real run advanced t3 done", rc == 0 and after3.get("t3") == "done",
      repr(after3))

# cleanup
import shutil
shutil.rmtree(_tmp, ignore_errors=True)

print()
if fails:
    print(f"#51 REGRESSION: {len(fails)} FAILURE(S): {fails}")
    sys.exit(1)
print("#51 REGRESSION: all deterministic checks passed (dry-run non-mutating, "
      "real runs not suppressed, normal behaviour unchanged).")