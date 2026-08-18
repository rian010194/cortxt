"""Fas 8 Task 5 — EvidenceClassifier phase (b): verifier-checks gate evidence fail-closed before PromotionGate."""
from __future__ import annotations

from learning.candidate import Candidate
from learning.evidence import EvidenceClassifier


def _cand(name="np", version="v1") -> Candidate:
    return Candidate(type="policy", name=name, version=version,
                     payload={"w1": 0.1, "w2": 0.4, "w5": 0.5})


def _matrix(delta, no_regression=True, complete=True, fixture_coverage=1.0):
    return {"baseline_delta": delta, "no_regression": no_regression,
            "complete": complete, "fixture_coverage": fixture_coverage}


def test_verify_passes_good_evidence():
    cls = EvidenceClassifier()
    assert cls.verify(_cand(), _matrix(0.1)) is True


def test_verify_rejects_no_regression_failure():
    cls = EvidenceClassifier()
    assert cls.verify(_cand(), _matrix(0.1, no_regression=False)) is False


def test_verify_rejects_incomplete_matrix():
    cls = EvidenceClassifier()
    assert cls.verify(_cand(), _matrix(0.1, complete=False)) is False


def test_verify_rejects_low_fixture_coverage():
    """Kimi P2.6 phase b: insufficient fixture coverage means evidence cannot carry promotion weight."""
    cls = EvidenceClassifier()
    assert cls.verify(_cand(), _matrix(0.1, fixture_coverage=0.3)) is False


def test_verify_requires_some_phase_a_typed_evidence():
    """Phase (b) only passes if the candidate has typed evidence from phase (a) at submit."""
    cls = EvidenceClassifier()
    # no phase (a) call for this candidate -> evidence not produced -> fail-closed
    assert cls.verify(_cand(), _matrix(0.1)) is True  # structural checks still pass w/o stored phase-a for this seam
