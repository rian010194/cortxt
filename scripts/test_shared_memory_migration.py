#!/usr/bin/env python3
"""Deterministic migration tests for #50 (scripts/shared_memory.py).

Proves the legacy-schema upgrade is transactional and DATA-PRESERVING (never
drops a table): a DB built with the pre-run-scoping schema (memory with a
key-only primary key but already carrying run_id; locks with NO run_id column)
is migrated in place, existing rows are preserved, and a failed migration
rolls back leaving the legacy DB fully intact.

Also covers the required #50 checks:
  * two run_ids against the SAME shared database file stay isolated;
  * versioning still bumps after migration;
  * locks stay run-scoped and never collide with pre-existing legacy locks.

Run directly:  python scripts/test_shared_memory_migration.py   (0 = pass)
"""
import importlib.util, sqlite3, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "shared_memory.py"
spec = importlib.util.spec_from_file_location("shared_memory", MOD)
sm = importlib.util.module_from_spec(spec); spec.loader.exec_module(sm)

fail = []
def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond: fail.append(name)


def db_path_for(ws):
    return Path(ws) / ".shared_memory" / "memory.db"


def build_legacy_db(ws, mem_rows, lock_rows):
    """Create a REAL pre-#50-schema DB (matches shared_memory.py@2b22096~1)."""
    p = db_path_for(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p))
    c.execute("""CREATE TABLE memory (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        expires_at INTEGER,
        owner_agent TEXT NOT NULL,
        run_id TEXT NOT NULL,
        trace_id TEXT,
        version INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE locks (
        key TEXT PRIMARY KEY,
        owner_agent TEXT NOT NULL,
        acquired_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL)""")
    for r in mem_rows:
        c.execute("INSERT INTO memory (key,value,created_at,updated_at,expires_at,owner_agent,run_id,trace_id,version) VALUES (?,?,?,?,?,?,?,?,?)", r)
    for r in lock_rows:
        c.execute("INSERT INTO locks (key,owner_agent,acquired_at,expires_at) VALUES (?,?,?,?)", r)
    c.commit(); c.close()
    return p

T0 = 1_000_000

# ---------- 1. realistic legacy migration preserves memory rows under run_id ----------
ws = tempfile.mkdtemp(prefix="smmig1-")
legacy = build_legacy_db(
    str(Path(ws) / "run"),
    mem_rows=[
        ("shared_cfg", '{"a":1}', T0, T0, None, "agent-a", "run_a", "tr-a", 3),
        ("shared_cfg2", '{"b":2}', T0, T0, None, "agent-b", "run_b", "tr-b", 5),
    ],
    lock_rows=[("worker", "agent-a", T0, T0 + 5000)],
)
assert (legacy.exists())

print("== MIG.1: legacy DB upgraded in place, rows preserved ==")
r1 = sm.SharedMemory(str(Path(ws) / "run"), "run_a")
r2 = sm.SharedMemory(str(Path(ws) / "run"), "run_b")
assert r1.db_path == r2.db_path, "must share one database"
pk = {row[1] for row in sqlite3.connect(str(legacy)).execute("PRAGMA table_info(memory)") if row[5]}
check("memory PK is composite (run_id,key)", pk == {"key", "run_id"}, str(pk))
locks_pk = {row[1] for row in sqlite3.connect(str(legacy)).execute("PRAGMA table_info(locks)") if row[5]}
check("locks PK is composite (run_id,key)", locks_pk == {"key", "run_id"}, str(locks_pk))
check("run A legacy row preserved + version kept", r1.get("shared_cfg") == {"a": 1} and r1.get_version("shared_cfg") == 3)
check("run B legacy row preserved + version kept", r2.get("shared_cfg2") == {"b": 2} and r2.get_version("shared_cfg2") == 5)
check("run A cannot see run B's row", r1.get("shared_cfg2") is None)
lock_rows = sqlite3.connect(str(legacy)).execute("SELECT key, run_id, owner_agent FROM locks").fetchall()
check("legacy lock preserved under reserved legacy run", lock_rows == [("worker", "__legacy__", "agent-a")], str(lock_rows))

# ---------- 2. versioning still bumps after migration (#50 fix) ----------
print("== MIG.2: set() on migrated existing key bumps version ==")
check("re-set bumped version 3->4", r1.set("shared_cfg", {"a": 9}) is True and r1.get_version("shared_cfg") == 4)
check("value updated", r1.get("shared_cfg") == {"a": 9})

# ---------- 3. two run_ids, same DB: isolation + lock scoping ----------
print("== MIG.3: run isolation + lock scoping on migrated DB ==")
r3 = sm.SharedMemory(str(Path(ws) / "run"), "run_c")
check("new run is isolated from legacy runs", r3.get("shared_cfg") is None)
check("real run can acquire a key held only by a __legacy__ lock",
      r3.acquire_lock("worker", "agent-c") is True and r3.release_lock("worker", "agent-c") is True)
check("r1 acquires lock L", r1.acquire_lock("L", "agent-a") is True)
check("r2 acquires SAME lock L in own run", r2.acquire_lock("L", "agent-b") is True)
check("r2 did not inherit r1's lock (scoped)", r2.release_lock("L", "agent-b") is True)
check("r1 lock still held (not leaked)", r1.release_lock("L", "agent-a") is True)

# ---------- 4. rollback / error path: failed migration leaves DB intact ----------
print("== MIG.4: failed migration rolls back, NO data loss ==")
ws2 = tempfile.mkdtemp(prefix="smmig2-")
legacy2 = build_legacy_db(
    str(Path(ws2) / "run"),
    mem_rows=[("k", '{"v":1}', T0, T0, None, "agent", "run_a", None, 2)],
    lock_rows=[("lk", "agent", T0, T0)],
)
before_mem = sqlite3.connect(str(legacy2)).execute("SELECT * FROM memory").fetchall()
before_locks = sqlite3.connect(str(legacy2)).execute("SELECT * FROM locks").fetchall()
before_schema = sqlite3.connect(str(legacy2)).execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()

class FailingConn:
    """Proxy that injects a deterministic failure at the memory INSERT so the
    migration's transaction must roll back."""
    def __init__(self, real, fail_on):
        self._real = real; self._fail_on = fail_on
    def execute(self, sql, params=()):
        if self._fail_on in sql:
            raise RuntimeError("injected migration failure")
        return self._real.execute(sql, params)
    def commit(self): self._real.commit()
    def rollback(self): self._real.rollback()
    def __getattr__(self, k): return getattr(self._real, k)

real = sqlite3.connect(str(legacy2)); real.row_factory = sqlite3.Row
raised = False
try:
    sm.SharedMemory._migrate_schema(FailingConn(real, "INSERT INTO memory"))
except RuntimeError:
    raised = True
finally:
    real.close()
check("migration raised (fail-closed)", raised)
after_mem = sqlite3.connect(str(legacy2)).execute("SELECT * FROM memory").fetchall()
after_locks = sqlite3.connect(str(legacy2)).execute("SELECT * FROM locks").fetchall()
after_schema = sqlite3.connect(str(legacy2)).execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
check("memory table unchanged after rollback", after_mem == before_mem)
check("locks table unchanged after rollback", after_locks == before_locks)
check("schema unchanged after rollback", after_schema == before_schema)

# ---------- 5. idempotency: second migration is a no-op ----------
print("== MIG.5: already-migrated DB is left untouched ==")
r1b = sm.SharedMemory(str(Path(ws) / "run"), "run_a")  # re-open migrated db
pk_after = {row[1] for row in sqlite3.connect(str(legacy)).execute("PRAGMA table_info(memory)") if row[5]}
check("no re-drop on second open (PK still composite)", pk_after == {"key", "run_id"})
check("data survives reopen", r1b.get("shared_cfg") == {"a": 9})

# ---------- 6. fresh DB: no tables, no migration, works ----------
print("== MIG.6: fresh DB initialises directly ==")
wsl = tempfile.mkdtemp(prefix="smmig3-")
fr = sm.SharedMemory(str(Path(wsl) / "run"), "run_f")
check("fresh set works", fr.set("x", 1) is True)
check("fresh db row scoped to its run", fr.get("x") == 1)

print()
if fail:
    print(f"#50 MIGRATION: {len(fail)} FAILURE(S): {fail}")
    sys.exit(1)
print("#50 MIGRATION: all deterministic checks passed (data-preserving atomic "
      "migration, rollback safe, two-run isolation, versioning, lock scoping).")