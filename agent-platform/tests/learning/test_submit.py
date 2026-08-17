"""Fas 8 Task 3 — submit_candidate ingress + EvidenceClassifier phase (a)."""
from __future__ import annotations

import pytest

from learning import CandidateRegistry
from learning.evidence import EvidenceClassifier
from learning.submit import submit_candidate


def test_submit_creates_eval_pending_candidate_with_timestamp():
    reg = CandidateRegistry(":memory:")
    cid, evidence = submit_candidate(reg, type_="policy", name="np", version="v1",
                                     payload={"w1": 0.1, "w2": 0.4}, provenance="operator")
    assert cid == "policy@np@v1"
    c = reg.get("policy", "np", "v1")
    assert c is not None
    assert c.status == "eval_pending"
    assert c.proposed_at is not None  # Kimi P1: proposed_at is set at ingress
    assert reg.get_active("policy", "np") is None  # submitted, not yet active
    assert set(evidence.keys()) == {"facts", "events", "instructions", "tasks"}


def test_submit_unknown_type_rejected():
    reg = CandidateRegistry(":memory:")
    with pytest.raises(ValueError, match="unknown candidate type"):
        submit_candidate(reg, type_="bogus", name="np", version="v1", payload={}, provenance="operator")


def test_submit_validates_provenance_present():
    reg = CandidateRegistry(":memory:")
    with pytest.raises(ValueError, match="provenance"):
        submit_candidate(reg, type_="policy", name="np", version="v1", payload={}, provenance="")


def test_evidence_classifier_phase_a_returns_four_typed_groups():
    cls = EvidenceClassifier()
    ev = cls.phase_a(payload={"success_rate": 0.92, "baseline_delta": 0.03}, provenance="eval")
    assert set(ev.keys()) == {"facts", "events", "instructions", "tasks"}
    assert ev["facts"]["success_rate"] == 0.92
    assert ev["facts"]["baseline_delta"] == 0.03
    assert "provenance" in ev["events"]


def test_evidence_classifier_phase_a_buckets_all_four_groups():
    """Kimi P2: all four bucket categories are exercised deterministically."""
    cls = EvidenceClassifier()
    ev = cls.phase_a(
        payload={
            "success_rate": 0.9,                       # -> facts
            "eval_run_at": "2026-08-18T00:00:00Z",     # -> events
            "active_candidate": "geometric@v2",        # -> instructions
            "fixture_set": "geo-N3",                   # -> tasks
        },
        provenance="operator",
    )
    assert ev["facts"]["success_rate"] == 0.9
    assert ev["events"]["eval_run_at"] == "2026-08-18T00:00:00Z"
    assert ev["instructions"]["active_candidate"] == "geometric@v2"
    assert ev["tasks"]["fixture_set"] == "geo-N3"
    assert ev["events"]["provenance"] == "operator"
