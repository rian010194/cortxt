#!/usr/bin/env python3
"""
Shared Memory — SQLite WAL implementation for multi-agent workspace memory.
Provides atomic operations, TTL support, and concurrent access safety.
"""

import sqlite3
import json
import time
import threading
import os
from pathlib import Path
from typing import Any, Optional, Dict, List
from contextlib import contextmanager

# Target (run-scoped) schema — shared verbatim by the initial CREATE and the
# legacy migration so the two can never drift (#50). `_FRESH` variants drop the
# IF-NOT-EXISTS guard because the migration creates a brand-new table after a
# rename and must fail loudly on a collision rather than silently no-op.
_MEMORY_TABLE_SQL = """CREATE TABLE IF NOT EXISTS memory (
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    expires_at INTEGER,
    owner_agent TEXT NOT NULL,
    run_id TEXT NOT NULL,
    trace_id TEXT,
    version INTEGER DEFAULT 1,
    PRIMARY KEY (run_id, key)
)"""
_MEMORY_TABLE_SQL_FRESH = _MEMORY_TABLE_SQL.replace(
    "CREATE TABLE IF NOT EXISTS", "CREATE TABLE", 1)

_LOCKS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS locks (
    key TEXT NOT NULL,
    owner_agent TEXT NOT NULL,
    acquired_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (run_id, key)
)"""
_LOCKS_TABLE_SQL_FRESH = _LOCKS_TABLE_SQL.replace(
    "CREATE TABLE IF NOT EXISTS", "CREATE TABLE", 1)


class SharedMemory:
    """Thread-safe shared memory using SQLite WAL mode."""

    # Reserved run scope for rows that predate run-scoping and carry no usable
    # run attribution (legacy `locks`). They are preserved under this reserved
    # scope so they can never leak into / contend with a real run (#50).
    LEGACY_RUN_ID = "__legacy__"

    def __init__(self, workspace_path: str, run_id: str):
        self.workspace_path = Path(workspace_path)
        self.run_id = run_id
        self.db_path = self.workspace_path / ".shared_memory" / "memory.db"
        self.lock = threading.RLock()
        self._init_db()

    @staticmethod
    def _table_exists(conn, name: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,)).fetchone() is not None

    @classmethod
    def _migrate_schema(cls, conn):
        """Upgrade a legacy DB to the run-scoped composite-PK schema.

        Two legacy shapes are migrated in place WITHOUT destroying data:
          * `memory` with a `key`-only primary key (keeps each row's run_id);
          * `locks` with no `run_id` column (rows go under `LEGACY_RUN_ID`).

        The whole upgrade runs in a SINGLE transaction: any failure rolls back
        and leaves the legacy DB exactly as it was (fail-closed, no dropped or
        half-migrated data). Fresh DBs (no tables) are left for the initial
        CREATE in `_init_db`.
        """
        memory_exists = cls._table_exists(conn, "memory")
        locks_exist = cls._table_exists(conn, "locks")
        if not (memory_exists or locks_exist):
            return  # fresh DB: nothing legacy to migrate

        memory_legacy = memory_exists and [
            r["name"] for r in conn.execute("PRAGMA table_info(memory)") if r["pk"]
        ] == ["key"]
        locks_legacy = locks_exist and "run_id" not in {
            r["name"] for r in conn.execute("PRAGMA table_info(locks)")
        }
        if not (memory_legacy or locks_legacy):
            return  # already target schema

        conn.execute("BEGIN")
        try:
            if memory_legacy:
                # Rebuild with composite (run_id,key) PK. Legacy `memory` already
                # had a run_id column, so each row's own run attribution is kept.
                conn.execute("ALTER TABLE memory RENAME TO __memory_legacy_backup")
                conn.execute(_MEMORY_TABLE_SQL_FRESH)
                conn.execute(
                    """INSERT INTO memory
                          (key, value, created_at, updated_at, expires_at,
                           owner_agent, run_id, trace_id, version)
                       SELECT key, value, created_at, updated_at, expires_at,
                              owner_agent, COALESCE(run_id, ?), trace_id, version
                       FROM __memory_legacy_backup""",
                    (cls.LEGACY_RUN_ID,))
                conn.execute("DROP TABLE __memory_legacy_backup")
            if locks_legacy:
                # Add run_id for the first time; legacy lock rows get a reserved
                # scope so they neither leak into nor block a real run.
                conn.execute("ALTER TABLE locks RENAME TO __locks_legacy_backup")
                conn.execute(_LOCKS_TABLE_SQL_FRESH)
                conn.execute(
                    """INSERT INTO locks (key, owner_agent, acquired_at, expires_at, run_id)
                       SELECT key, owner_agent, acquired_at, expires_at, ?
                       FROM __locks_legacy_backup""",
                    (cls.LEGACY_RUN_ID,))
                conn.execute("DROP TABLE __locks_legacy_backup")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def _init_db(self):
        """Initialize database with WAL mode, run-scoped schema, and a
        transactional, data-preserving migration for legacy DBs (#50)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._migrate_schema(conn)

            conn.execute(_MEMORY_TABLE_SQL)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_run ON memory(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory(expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_owner ON memory(owner_agent)")

            # Locks table for distributed locking — scoped per run_id so a lock
            # in one run never leaks/contends with another (#50).
            conn.execute(_LOCKS_TABLE_SQL)
            conn.commit()
    
    @contextmanager
    def _connect(self):
        """Thread-safe database connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _now_ms(self) -> int:
        return int(time.time() * 1000)
    
    def set(self, key: str, value: Any, ttl_ms: int = 0, owner_agent: str = "unknown") -> bool:
        """Set value with optional TTL. Returns True if successful."""
        now = self._now_ms()
        expires_at = now + ttl_ms if ttl_ms > 0 else None
        value_json = json.dumps(value, ensure_ascii=False)
        
        with self.lock:
            with self._connect() as conn:
                # UPSERT scoped to (run_id, key); version correctly bumps on
                # re-set (the old `WHERE memory.version = excluded.version - 1`
                # never matched because excluded.version is always the INSERT
                # literal 1 => an existing row's set() always returned False, #50).
                cursor = conn.execute("""
                    INSERT INTO memory (key, value, created_at, updated_at, expires_at, owner_agent, run_id, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(run_id, key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at,
                        owner_agent = excluded.owner_agent,
                        version = memory.version + 1
                """, (key, value_json, now, now, expires_at, owner_agent, self.run_id))
                
                success = cursor.rowcount > 0
                conn.commit()
                return success
    
    def get(self, key: str) -> Optional[Any]:
        """Get value if not expired."""
        now = self._now_ms()
        
        with self._connect() as conn:
            row = conn.execute("""
                SELECT value FROM memory 
                WHERE key = ? AND run_id = ? AND (expires_at IS NULL OR expires_at > ?)
            """, (key, self.run_id, now)).fetchone()
            
            if row:
                return json.loads(row["value"])
            return None
    
    def compare_and_swap(self, key: str, expected_version: int, new_value: Any, owner_agent: str = "unknown") -> bool:
        """Atomic compare-and-swap operation."""
        now = self._now_ms()
        value_json = json.dumps(new_value, ensure_ascii=False)
        
        with self.lock:
            with self._connect() as conn:
                cursor = conn.execute("""
                    UPDATE memory SET
                        value = ?,
                        updated_at = ?,
                        version = version + 1
                    WHERE key = ? AND run_id = ? AND version = ?
                """, (value_json, now, key, self.run_id, expected_version))
                
                success = cursor.rowcount > 0
                conn.commit()
                return success
    
    def get_version(self, key: str) -> Optional[int]:
        """Get current version of a key."""
        with self._connect() as conn:
            row = conn.execute("SELECT version FROM memory WHERE key = ? AND run_id = ?", 
                              (key, self.run_id)).fetchone()
            return row["version"] if row else None
    
    def delete(self, key: str) -> bool:
        """Delete a key."""
        with self.lock:
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM memory WHERE key = ? AND run_id = ?", 
                                     (key, self.run_id))
                conn.commit()
                return cursor.rowcount > 0
    
    def list_keys(self, prefix: str = "", owner_agent: str = None) -> List[Dict]:
        """List keys matching prefix."""
        with self._connect() as conn:
            query = "SELECT key, owner_agent, created_at, updated_at, expires_at, version FROM memory WHERE run_id = ?"
            params = [self.run_id]
            
            if prefix:
                query += " AND key LIKE ?"
                params.append(f"{prefix}%")
            
            if owner_agent:
                query += " AND owner_agent = ?"
                params.append(owner_agent)
            
            query += " ORDER BY updated_at DESC"
            
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    def acquire_lock(self, key: str, owner_agent: str, ttl_ms: int = 5000) -> bool:
        """Acquire a distributed lock, scoped to this run (#50)."""
        now = self._now_ms()
        expires_at = now + ttl_ms
        
        with self._connect() as conn:
            # Try to insert lock (fails if exists and not expired); run-scoped.
            cursor = conn.execute("""
                INSERT INTO locks (key, owner_agent, acquired_at, expires_at, run_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, key) DO UPDATE SET
                    owner_agent = excluded.owner_agent,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                WHERE locks.expires_at < excluded.acquired_at
            """, (key, owner_agent, now, expires_at, self.run_id))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def release_lock(self, key: str, owner_agent: str) -> bool:
        """Release a lock owned by this agent in this run (#50)."""
        with self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM locks WHERE key = ? AND owner_agent = ? AND run_id = ?
            """, (key, owner_agent, self.run_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        now = self._now_ms()
        
        with self.lock:
            with self._connect() as conn:
                # Clean memory
                cursor = conn.execute("""
                    DELETE FROM memory WHERE run_id = ? AND expires_at IS NOT NULL AND expires_at < ?
                """, (self.run_id, now))
                memory_removed = cursor.rowcount
                
                # Clean locks
                cursor = conn.execute("""
                    DELETE FROM locks WHERE expires_at < ?
                """, (now,))
                locks_removed = cursor.rowcount
                
                conn.commit()
                return memory_removed + locks_removed
    
    def get_stats(self) -> Dict:
        """Get memory statistics."""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT 
                    COUNT(*) as total_entries,
                    SUM(LENGTH(value)) as total_size_bytes,
                    COUNT(CASE WHEN expires_at IS NOT NULL AND expires_at < ? THEN 1 END) as expired_entries
                FROM memory WHERE run_id = ?
            """, (self._now_ms(), self.run_id)).fetchone()
            
            return dict(row) if row else {"total_entries": 0, "total_size_bytes": 0, "expired_entries": 0}


class SharedMemoryReaper:
    """Background cleanup service for shared memory."""
    
    def __init__(self, workspace_root: str, interval_seconds: int = 300):
        self.workspace_root = Path(workspace_root)
        self.interval_seconds = interval_seconds
        self.running = False
        self.thread = None
    
    def start(self):
        """Start the reaper thread."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop the reaper thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def _run(self):
        while self.running:
            try:
                self._cleanup_all()
            except Exception as e:
                print(f"SharedMemoryReaper error: {e}")
            time.sleep(self.interval_seconds)
    
    def _cleanup_all(self):
        """Clean expired entries from all run workspaces."""
        for run_dir in self.workspace_root.glob("run_*"):
            if run_dir.is_dir():
                memory_db = run_dir / ".shared_memory" / "memory.db"
                if memory_db.exists():
                    try:
                        conn = sqlite3.connect(str(memory_db))
                        conn.execute("PRAGMA journal_mode=WAL")
                        now = int(time.time() * 1000)
                        conn.execute("DELETE FROM memory WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
                        conn.execute("DELETE FROM locks WHERE expires_at < ?", (now,))
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass


# Convenience functions for agent usage
def create_shared_memory(run_id: str, workspace_root: str = "/tmp/hermes_runs") -> SharedMemory:
    """Create shared memory for a run."""
    workspace = Path(workspace_root) / f"run_{run_id}"
    return SharedMemory(str(workspace), run_id)


def get_reaper(workspace_root: str = "/tmp/hermes_runs") -> SharedMemoryReaper:
    """Get shared memory reaper instance."""
    return SharedMemoryReaper(workspace_root)


if __name__ == "__main__":
    # Test
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SharedMemory(tmpdir, "test-run")
        
        # Test basic operations
        assert sm.set("key1", {"data": "value1"}, owner_agent="agent1")
        assert sm.get("key1") == {"data": "value1"}
        
        # Test CAS
        v = sm.get_version("key1")
        assert sm.compare_and_swap("key1", v, {"data": "value2"})
        assert sm.get("key1") == {"data": "value2"}
        
        # Test lock
        assert sm.acquire_lock("lock1", "agent1")
        assert not sm.acquire_lock("lock1", "agent2")  # Should fail
        assert sm.release_lock("lock1", "agent1")
        assert sm.acquire_lock("lock1", "agent2")  # Should succeed now
        
        # Test TTL
        assert sm.set("ttl_key", "expires_soon", ttl_ms=100, owner_agent="agent1")
        assert sm.get("ttl_key") == "expires_soon"
        time.sleep(0.2)
        assert sm.get("ttl_key") is None  # Expired
        
        # Test reaper
        reaper = SharedMemoryReaper(tmpdir, interval_seconds=1)
        reaper.start()
        time.sleep(0.5)
        reaper.stop()
        
        print("All tests passed!")