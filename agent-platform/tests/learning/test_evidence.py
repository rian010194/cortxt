"""Phase 8 Task 5 — EvidenceClassifier phase (b): verifier-checks gate evidence fail-closed before PromotionGate."""
from __future__ import annotations

from learning.evidence import EvidenceClassifier


def _matrix(delta, no_regression=True, complete=True, fixture_coverage=1.0):
    return {"baseline_delta": delta, "no_regression": no_regression,
            "complete": complete, "fixture_coverage": fixture_coverage}


def test_verify_passes_good_evidence():
    assert EvidenceClassifier().verify(_matrix(0.1)) is True


def test_verify_rejects_no_regression_failure():
    assert EvidenceClassifier().verify(_matrix(0.1, no_regression=False)) is False


def test_verify_rejects_incomplete_matrix():
    assert EvidenceClassifier().verify(_matrix(0.1, complete=False)) is False


def test_verify_fail_closed_when_complete_key_missing():
    """Kimi F-01: a matrix missing the 'complete' key must FAIL CLOSED (not default to trusted)."""
    m = {"baseline_delta": 0.1, "no_regression": True}  # no 'complete' key
    assert EvidenceClassifier().verify(m) is False


def test_verify_rejects_low_fixture_coverage():
    """Kimi P2.6 phase b: insufficient fixture coverage means evidence cannot carry promotion weight."""
    assert EvidenceClassifier().verify(_matrix(0.1, fixture_coverage=0.3)) is False
