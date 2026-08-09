#!/usr/bin/env python3
"""Deterministic regression tests for #50 (scripts/shared_memory.py).

Verifies the three Codex-U2 findings are fixed:
  1. set() on an EXISTING key returns True and bumps version (was: always False
     due to `WHERE memory.version = excluded.version - 1` never matching).
  2. Different runs are isolated (composite PK (run_id, key), not global key).
  3. Locks are run-scoped (a lock in one run does not leak/block another).
  4. compare_and_swap + version semantics still correct.

Run directly:  python scripts/test_shared_memory.py   (0 = pass)
"""
import importlib.util, sys, tempfile, os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "shared_memory.py"
spec = importlib.util.spec_from_file_location("shared_memory", MOD)
sm = importlib.util.module_from_spec(spec); spec.loader.exec_module(sm)

fail = []
def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond: fail.append(name)

# r1 and r2 SHARE the same workspace/database but have different run_ids — this
# actually exercises run isolation + lock scoping inside one shared SQLite file
# (#50), not two separate databases.
ws = tempfile.mkdtemp(prefix="sm51-")
r1 = sm.SharedMemory(str(Path(ws) / "run"), "run_a")
r2 = sm.SharedMemory(str(Path(ws) / "run"), "run_b")
assert r1.db_path == r2.db_path, "test must share one database"

print("== #50.1: set() on existing key returns True + bumps version ==")
check("fresh set True", r1.set("k", {"v": 1}) is True)
check("version 1 after first set", r1.get_version("k") == 1)
check("re-set existing returns True", r1.set("k", {"v": 2}) is True)
check("version bumped to 2", r1.get_version("k") == 2)
check("value updated", r1.get("k") == {"v": 2})

print("== #50.2: runs are isolated ==")
r2.set("k", {"v": 99})
check("run B has own value", r2.get("k") == {"v": 99})
check("run A unaffected by B", r1.get("k") == {"v": 2})
check("same key does not collide across runs", r1.get_version("k") == 2 and r2.get_version("k") == 1)

print("== #50.3: locks are run-scoped ==")
check("r1 acquires lock", r1.acquire_lock("L", "agenta") is True)
check("r2 acquires SAME lock name in own run", r2.acquire_lock("L", "agentb") is True)
check("r1 releases its lock", r1.release_lock("L", "agenta") is True)
check("r2 lock still held (not leaked) ", r2.release_lock("L", "agentb") is True)

print("== #50.4: compare_and_swap intact ==")
check("cas on current version succeeds",
      r1.compare_and_swap("k", expected_version=2, new_value={"v": 3}) is True)
check("value updated by cas", r1.get("k") == {"v": 3})
check("cas on stale version fails",
      r1.compare_and_swap("k", expected_version=99, new_value={"v": 4}) is False)
check("stale cas did not change value", r1.get("k") == {"v": 3})

print()
import shutil
shutil.rmtree(ws, ignore_errors=True)
if fail:
    print(f"#50 REGRESSION: {len(fail)} FAILURE(S): {fail}")
    sys.exit(1)
print("#50 REGRESSION: all deterministic checks passed (set bumps version, "
      "runs isolated, locks run-scoped, CAS intact).")