"""Policy-candidate adapter + concrete policy-constraint safety rules (Phase 8, Decision 1/10a; P1.1).

P1.1 correction: a ``CandidatePathScore`` weight-set is 7 scalars, NOT a graph node — so the geometric
``AttractorDetector``/``contradiction`` operators (which operate on ``ProblemSpace`` + node_id) do NOT apply
to a weight candidate. Instead, the honest, deterministic safety rules are policy CONSTRAINTS derived from
the §12.4 normalization contract:

- ``normalized_weights``: additive (w1..w4) sum == 1.0 AND subtractive (w5..w7) sum == 1.0.
- ``non_negative_weights``: no weight < 0.
- ``bounded_weights``: every weight in [0, 1].

These are registered as ``kind="safety"`` ``PromotionRule``s, so a violating weight candidate is REJECTed by
the gate purely as data. (For FUTURE candidate types where a candidate IS a graph node, AttractorDetector can
be reused as a genuine geometric safety-rule — noted in the spec's "The Road to the Bigger Goal", not v1.)
"""
from __future__ import annotations

from typing import Mapping

from .candidate import Candidate
from .promotion_gate import PromotionRule

# human-readable field -> CandidatePathScore weight slot (w2 = goal_relevance, etc.)
_FIELD_TO_W: dict[str, str] = {
    "expected_information_gain": "w1",
    "goal_relevance": "w2",
    "evidence_coverage": "w3",
    "path_novelty": "w4",
    "contradiction_risk": "w5",
    "expected_cost": "w6",
    "policy_risk": "w7",
}
_ADDITIVE = ("w1", "w2", "w3", "w4")
_SUBTRACTIVE = ("w5", "w6", "w7")


def normalized(weights: Mapping[str, float]) -> bool:
    """True iff additive (w1..w4) and subtractive (w5..w7) weights each sum to 1.0 and lie in [0,1]."""
    if not all(0.0 <= float(weights.get(k, 0.0)) <= 1.0 for k in _ADDITIVE + _SUBTRACTIVE):
        return False
    add = sum(float(weights.get(k, 0.0)) for k in _ADDITIVE)
    sub = sum(float(weights.get(k, 0.0)) for k in _SUBTRACTIVE)
    return abs(add - 1.0) < 1e-9 and abs(sub - 1.0) < 1e-9


def add_weights_constraint_rules() -> list[PromotionRule]:
    """The three concrete policy-constraint safety rules (P1.1), evaluated as data by the gate."""
    return [
        PromotionRule("policy", kind="safety", metric="normalized_weights"),
        PromotionRule("policy", kind="safety", metric="non_negative_weights"),
        PromotionRule("policy", kind="safety", metric="bounded_weights"),
    ]


def constraint_matrix(weights: Mapping[str, float]) -> dict[str, bool]:
    """Populate the matrix with the constraint-metric values so the gate's safety rules are actually
    exercised (Kimi Task8-11 P1: `normalized()` was never wired in — a violating weight set passed the gate
    by accident because the metric key was absent and `None is not False`)."""
    vals = {k: float(v) for k, v in weights.items()}
    return {
        "normalized_weights": normalized(weights),
        "non_negative_weights": all(v >= 0.0 for v in vals.values()),
        "bounded_weights": all(0.0 <= v <= 1.0 for v in vals.values()),
    }


class PolicyCandidateAdapter:
    """Maps a CandidatePathScore-style weight set to a versioned policy Candidate."""

    def to_candidate(self, name: str, version: str, weights: Mapping[str, float]) -> Candidate:
        payload: dict[str, float] = {}
        for field, value in weights.items():
            slot = _FIELD_TO_W.get(field, field)  # accept both human names and raw w1..w7
            payload[slot] = float(value)
        return Candidate(type="policy", name=name, version=version, payload=payload)

    def rules(self) -> list[PromotionRule]:
        """§31-equivalent for a policy candidate: constraint safety + no-regression + strictly-better eval
        (auto-promotable). Includes no_regression safety rule so the matrix field is not dead data (Kimi N1)."""
        return add_weights_constraint_rules() + [
            PromotionRule("policy", kind="safety", metric="no_regression"),
            PromotionRule("policy", kind="eval", metric="baseline_delta", threshold=0.0, comparator="gt")
        ]
