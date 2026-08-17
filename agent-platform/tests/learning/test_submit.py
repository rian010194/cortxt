"""Fas 8 Task 3 — submit_candidate ingress + EvidenceClassifier phase (a)."""
from __future__ import annotations

import pytest

from learning import Candidate, CandidateRegistry
from learning.evidence import EvidenceClassifier
from learning.submit import submit_candidate


def test_submit_creates_eval_pending_candidate():
    reg = CandidateRegistry(":memory:")
    cid = submit_candidate(reg, type_="policy", name="np", version="v1",
                           payload={"w1": 0.1, "w2": 0.4}, provenance="operator")
    assert cid == "policy@np@v1"
    c = reg.get("policy", "np", "v1")
    assert c is not None
    assert c.status == "eval_pending"
    assert reg.get_active("policy", "np") is None  # submitted, not yet active


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
    # Kimi P1.3 concrete example: facts/events/instructions/tasks
    assert set(ev.keys()) == {"facts", "events", "instructions", "tasks"}
    assert ev["facts"]["success_rate"] == 0.92
    assert "provenance" in ev["events"]
