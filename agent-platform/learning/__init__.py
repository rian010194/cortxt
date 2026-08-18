"""Controlled learning loop — Fas 8. See docs/superpowers/specs/2026-08-18-fas8-controlled-learning-loop-v01-design.md."""
from __future__ import annotations

from .candidate import Candidate
from .evidence import EvidenceClassifier
from .evaluator import EvidenceRow, Evaluator, cached_embedder
from .promotion_gate import MANDATORY_OPERATOR_GATES, PromotionGate, PromotionRule
from .registry import CandidateRegistry
from .rollback import rollback
from .submit import submit_candidate

__all__ = [
    "Candidate", "CandidateRegistry", "EvidenceClassifier",
    "Evaluator", "EvidenceRow", "cached_embedder",
    "PromotionGate", "PromotionRule", "MANDATORY_OPERATOR_GATES",
    "rollback", "submit_candidate",
]
