"""Controlled learning loop — Fas 8. See docs/superpowers/specs/2026-08-18-fas8-controlled-learning-loop-v01-design.md."""
from __future__ import annotations

from .candidate import Candidate
from .evidence import EvidenceClassifier
from .promotion_gate import MANDATORY_OPERATOR_GATES, PromotionGate, PromotionRule
from .registry import CandidateRegistry
from .submit import submit_candidate

__all__ = [
    "Candidate", "CandidateRegistry", "EvidenceClassifier",
    "PromotionGate", "PromotionRule", "MANDATORY_OPERATOR_GATES",
    "submit_candidate",
]
