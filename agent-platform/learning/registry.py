"""CandidateRegistry — SQLite-persisted, keyed on type@name@version, with active-pointer + promoted_from.

Controlled learning loop (Fas 8, Beslut 9.4 / P1.1 plan-review). Mirrors the persistence pattern of
``BudgetGate`` (``_ensure_table`` + row-level versioning) established in Fas 2a, and the deterministic
export/hash principles of ``SkillRegistry`` (PR #135).

Schema:
- ``candidates(type, name, version, manifest_hash, status, payload_json, proposed_at, promoted_by,
  promoted_at, rolled_back_at)`` — one row per immutable candidate; ``manifest_hash`` verified on add.
- ``active_candidates(type, name, active_version, promoted_from, updated_at)`` — the current promoted
  version plus the previous one, so rollback (Task 7) can atomically restore the prior version (P1.1).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable

from .candidate import Candidate

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    proposed_at TEXT,
    promoted_by TEXT,
    promoted_at TEXT,
    rolled_back_at TEXT,
    PRIMARY KEY (type, name, version)
);
CREATE TABLE IF NOT EXISTS active_candidates (
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    active_version TEXT,
    promoted_from TEXT,
    updated_at TEXT,
    PRIMARY KEY (type, name)
);
"""


class CandidateRegistry:
    """Persistent, typ-agnostic registry with active-pointer bookkeeping."""

    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add(self, candidate: Candidate) -> None:
        row = self._conn.execute(
            "SELECT manifest_hash FROM candidates WHERE type=? AND name=? AND version=?",
            (candidate.type, candidate.name, candidate.version),
        ).fetchone()
        if row is not None:
            if row[0] == candidate.manifest_hash:
                return  # idempotent add of identical manifest
            raise ValueError(
                f"key {candidate.id} already registered with a different manifest (hash mismatch)"
            )
        self._conn.execute(
            "INSERT INTO candidates (type,name,version,manifest_hash,status,payload_json,proposed_at,"
            "promoted_by,promoted_at,rolled_back_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                candidate.type, candidate.name, candidate.version, candidate.manifest_hash,
                candidate.status, json.dumps(dict(candidate.payload)),
                candidate.proposed_at, candidate.promoted_by, candidate.promoted_at, candidate.rolled_back_at,
            ),
        )
        self._conn.commit()

    def get(self, type_: str, name: str, version: str | None = None) -> Candidate | None:
        if version is not None:
            row = self._conn.execute(
                "SELECT type,name,version,manifest_hash,status,payload_json,proposed_at,promoted_by,"
                "promoted_at,rolled_back_at FROM candidates WHERE type=? AND name=? AND version=?",
                (type_, name, version),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT type,name,version,manifest_hash,status,payload_json,proposed_at,promoted_by,"
                "promoted_at,rolled_back_at FROM candidates WHERE type=? AND name=? "
                "ORDER BY version DESC LIMIT 1",
                (type_, name),
            ).fetchone()  # v1 < v2 < v10 (lexical); acceptable for short semver in v1, refined in plan if needed
        return self._row_to_candidate(row) if row else None

    def all(self) -> list[Candidate]:
        rows = self._conn.execute(
            "SELECT type,name,version,manifest_hash,status,payload_json,proposed_at,promoted_by,"
            "promoted_at,rolled_back_at FROM candidates ORDER BY type,name,version"
        ).fetchall()
        return [c for c in (self._row_to_candidate(r) for r in rows) if c is not None]

    def set_active(self, type_: str, name: str, version: str) -> None:
        promoted_from = self.get_active(type_, name)
        self._conn.execute(
            "INSERT INTO active_candidates (type,name,active_version,promoted_from,updated_at) "
            "VALUES (?,?,?,?,datetime('now')) "
            "ON CONFLICT(type,name) DO UPDATE SET active_version=excluded.active_version, "
            "promoted_from=excluded.promoted_from, updated_at=excluded.updated_at",
            (type_, name, version, promoted_from),
        )
        self._conn.execute(
            "UPDATE candidates SET status='promoted', promoted_at=datetime('now') "
            "WHERE type=? AND name=? AND version=?",
            (type_, name, version),
        )
        self._conn.commit()

    def get_active(self, type_: str, name: str) -> str | None:
        row = self._conn.execute(
            "SELECT active_version FROM active_candidates WHERE type=? AND name=?", (type_, name)
        ).fetchone()
        return row[0] if row else None

    def promoted_from(self, type_: str, name: str) -> str | None:
        """The previous active version (None if current is the first promotion). For rollback (Task 7)."""
        row = self._conn.execute(
            "SELECT promoted_from FROM active_candidates WHERE type=? AND name=?", (type_, name)
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _row_to_candidate(row) -> Candidate | None:
        if row is None:
            return None
        (type_, name, version, man, status, payload_json, proposed_at,
         promoted_by, promoted_at, rolled_back_at) = row
        return Candidate(
            type=type_, name=name, version=version,
            payload=json.loads(payload_json), status=status,
            proposed_at=proposed_at, promoted_by=promoted_by,
            promoted_at=promoted_at, rolled_back_at=rolled_back_at,
        )
