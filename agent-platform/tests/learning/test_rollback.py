"""Phase 8 Task 7 — rollback(type, name): atomic pointer restore + audit (P1.5)."""
from __future__ import annotations

import pytest

from learning.candidate import Candidate
from learning.registry import CandidateRegistry
from learning.rollback import rollback


def _pol(name, version, w1):
    return Candidate(type="policy", name=name, version=version, payload={"w1": w1, "w2": 0.4})


def _setup_two_promoted(reg, name="np"):
    reg.add(_pol(name, "v1", 0.1))
    reg.add(_pol(name, "v2", 0.3))
    reg.set_active("policy", name, "v1")
    reg.set_active("policy", name, "v2")
    assert reg.get_active("policy", name) == "v2"


def test_rollback_restores_previous_version():
    reg = CandidateRegistry(":memory:")
    _setup_two_promoted(reg)
    rollback(reg, "policy", "np")
    assert reg.get_active("policy", "np") == "v1"
    assert reg.promoted_from("policy", "np") is None  # nothing before v1 now
    assert reg.get("policy", "np", "v2").status == "rolled_back"  # v2 audit-marked


def test_rollback_selects_correct_name_among_same_type():
    """P1.5: rollback(type, name) targets ONE candidate among several names under the same type."""
    reg = CandidateRegistry(":memory:")
    _setup_two_promoted(reg, "np")
    _setup_two_promoted(reg, "other")
    rollback(reg, "policy", "np")
    # only np rolled back; other untouched
    assert reg.get_active("policy", "np") == "v1"
    assert reg.get_active("policy", "other") == "v2"


def test_rollback_idempotent_when_already_at_first():
    """Rolling back when there is nothing before (promoted_from None) is a no-op, not corruption."""
    reg = CandidateRegistry(":memory:")
    reg.add(_pol("np", "v1", 0.1))
    reg.set_active("policy", "np", "v1")
    rollback(reg, "policy", "np")
    assert reg.get_active("policy", "np") == "v1"  # unchanged


def test_rollback_unknown_name_fails_closed():
    reg = CandidateRegistry(":memory:")
    with pytest.raises(ValueError, match="no active"):
        rollback(reg, "policy", "missing")
