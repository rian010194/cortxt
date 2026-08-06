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

class SharedMemory:
    """Thread-safe shared memory using SQLite WAL mode."""
    
    def __init__(self, workspace_path: str, run_id: str):
        self.workspace_path = Path(workspace_path)
        self.run_id = run_id
        self.db_path = self.workspace_path / ".shared_memory" / "memory.db"
        self.lock = threading.RLock()
        self._init_db()
    
    def _init_db(self):
        """Initialize database with WAL mode and schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    owner_agent TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    trace_id TEXT,
                    version INTEGER DEFAULT 1
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_run ON memory(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory(expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_owner ON memory(owner_agent)")
            
            # Locks table for distributed locking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS locks (
                    key TEXT PRIMARY KEY,
                    owner_agent TEXT NOT NULL,
                    acquired_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
            """)
            
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
                # UPSERT with optimistic locking
                cursor = conn.execute("""
                    INSERT INTO memory (key, value, created_at, updated_at, expires_at, owner_agent, run_id, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at,
                        owner_agent = excluded.owner_agent,
                        version = memory.version + 1
                    WHERE memory.version = excluded.version - 1
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
        """Acquire a distributed lock."""
        now = self._now_ms()
        expires_at = now + ttl_ms
        
        with self._connect() as conn:
            # Try to insert lock (fails if exists and not expired)
            cursor = conn.execute("""
                INSERT INTO locks (key, owner_agent, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    owner_agent = excluded.owner_agent,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                WHERE locks.expires_at < excluded.acquired_at
            """, (key, owner_agent, now, expires_at))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def release_lock(self, key: str, owner_agent: str) -> bool:
        """Release a distributed lock."""
        with self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM locks WHERE key = ? AND owner_agent = ?
            """, (key, owner_agent))
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