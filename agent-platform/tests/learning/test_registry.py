"""Phase 8 Task 2 — CandidateRegistry: SQLite persist, type@name@version key, active-pointer + promoted_from."""
from __future__ import annotations

import sqlite3

import pytest

from learning.candidate import Candidate
from learning.registry import CandidateRegistry


def _pol(type_: str, name: str, version: str, w1: float) -> Candidate:
    return Candidate(type=type_, name=name, version=version, payload={"w1": w1, "w2": 0.4})


def test_add_and_get_roundtrip():
    reg = CandidateRegistry(":memory:")
    c = _pol("policy", "np", "v1", 0.1)
    reg.add(c)
    assert reg.get("policy", "np", "v1").manifest_hash == c.manifest_hash
    assert len(reg.all()) == 1


def test_add_is_idempotent_for_identical_manifest():
    """Kimi P2.2: re-adding an identical candidate is a no-op (still one row)."""
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("policy", "np", "v1", 0.1))
    reg.add(_pol("policy", "np", "v1", 0.1))  # same key, identical manifest
    assert len(reg.all()) == 1


def test_get_latest_without_version_returns_highest_semver():
    """Kimi F-05: 'latest' is SEMVER-ordered (v10 > v2), not lexical."""
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("policy", "np", "v1", 0.1))
    reg.add(_pol("policy", "np", "v2", 0.3))
    assert reg.get("policy", "np").version == "v2"
    reg.add(_pol("policy", "np", "v10", 0.5))
    assert reg.get("policy", "np").version == "v10"  # semver: 10 > 2


def test_key_conflict_different_payload_raises():
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("policy", "np", "v1", 0.1))
    with pytest.raises(ValueError, match="hash mismatch"):
        reg.add(_pol("policy", "np", "v1", 0.9))  # same key, different manifest


def test_sqlite_roundtrip_persists_across_instances(tmp_path):
    db = tmp_path / "reg.db"
    reg1 = CandidateRegistry(str(db))
    reg1.add(_pol("policy", "np", "v1", 0.1))
    reg1.set_active("policy", "np", "v1")
    del reg1
    reg2 = CandidateRegistry(str(db))
    assert reg2.get("policy", "np", "v1") is not None
    assert reg2.get_active("policy", "np") == "v1"


def test_read_detects_tampered_manifest():
    """Kimi P1.1: hash is verified on READ — a direct DB write that diverges from the stored hash raises."""
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("policy", "np", "v1", 0.1))
    # tamper the payload_json in the DB directly, leaving the manifest_hash unchanged
    conn = reg._conn  # private access in test only — verifies the integrity invariant surface
    conn.execute("UPDATE candidates SET payload_json='{\"w1\": 0.99}' WHERE name='np'")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="hash mismatch"):
        reg.get("policy", "np", "v1")


def test_set_active_records_promoted_from():
    """P1.1 (plan-review): active-pointer table records promoted_from for atomic rollback lookup."""
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("policy", "np", "v1", 0.1))
    reg.add(_pol("policy", "np", "v2", 0.3))
    reg.set_active("policy", "np", "v1")
    reg.set_active("policy", "np", "v2")
    assert reg.get_active("policy", "np") == "v2"
    assert reg.promoted_from("policy", "np") == "v1"


def test_promoted_from_none_when_first_promotion():
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("policy", "np", "v1", 0.1))
    reg.set_active("policy", "np", "v1")
    assert reg.promoted_from("policy", "np") is None


def test_set_active_unknown_candidate_raises():
    """Kimi N-01: activating a version that does not exist must fail (no ghost active-pointer)."""
    reg = CandidateRegistry(":memory:")
    with pytest.raises(ValueError, match="unknown candidate"):
        reg.set_active("policy", "ghost", "v1")
