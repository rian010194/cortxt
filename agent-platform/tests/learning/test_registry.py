"""Fas 8 Task 2 — CandidateRegistry: SQLite persist, type@name@version key, active-pointer + promoted_from."""
from __future__ import annotations

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


def test_get_latest_without_version_returns_highest_semver():
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("policy", "np", "v1", 0.1))
    reg.add(_pol("policy", "np", "v2", 0.3))
    assert reg.get("policy", "np").version == "v2"


def test_key_conflict_different_payload_raises():
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("policy", "np", "v1", 0.1))
    with pytest.raises(Exception):
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
