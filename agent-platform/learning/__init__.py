"""Controlled learning loop — Fas 8. See docs/superpowers/specs/2026-08-18-fas8-controlled-learning-loop-v01-design.md."""
from __future__ import annotations

from .active_policy import resolve_active_policy
from .candidate import Candidate
from .evidence import EvidenceClassifier
from .evaluator import EvidenceRow, Evaluator, cached_embedder
from .promotion_gate import MANDATORY_OPERATOR_GATES, PromotionGate, PromotionRule
from .policy_candidate import PolicyCandidateAdapter, add_weights_constraint_rules, normalized
from .registry import CandidateRegistry
from .rollback import rollback
from .skill_candidate import SkillCandidateAdapter
from .submit import submit_candidate
from .tool_candidate import ToolCandidateAdapter

__all__ = [
    "Candidate", "CandidateRegistry", "EvidenceClassifier",
    "Evaluator", "EvidenceRow", "cached_embedder",
    "PromotionGate", "PromotionRule", "MANDATORY_OPERATOR_GATES",
    "PolicyCandidateAdapter", "add_weights_constraint_rules", "normalized",
    "SkillCandidateAdapter", "ToolCandidateAdapter",
    "resolve_active_policy",
    "rollback", "submit_candidate",
]
