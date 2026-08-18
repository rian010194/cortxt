"""Fas 8 Task 8 — policy-candidate adapter + concrete policy-constraint safety rules (P1.1)."""
from __future__ import annotations

from learning.candidate import Candidate
from learning.policy_candidate import (
    PolicyCandidateAdapter,
    add_weights_constraint_rules,
    normalized,
)


def _weights(**over):
    w = {"w1": 0.15, "w2": 0.40, "w3": 0.30, "w4": 0.15,
         "w5": 0.50, "w6": 0.25, "w7": 0.25}
    w.update(over)
    return w


def test_valid_weights_pass_normalization():
    """Additive (w1..w4) and subtractive (w5..w7) each sum to 1.0; all in [0,1]."""
    w = _weights()
    assert normalized(w) is True


def test_additive_weights_must_sum_to_one():
    assert normalized(_weights(w1=0.9)) is False  # 0.9+0.4+0.3+0.15 > 1.0


def test_subtractive_weights_must_sum_to_one():
    assert normalized(_weights(w5=0.9)) is False  # 0.9+0.25+0.25 > 1.0


def test_negative_weight_rejected():
    assert normalized(_weights(w2=-0.1)) is False


def test_weight_above_one_rejected():
    assert normalized(_weights(w3=1.5)) is False


def test_adapter_builds_candidate_with_candidate_path_score_payload():
    """P1.1: the adapter maps a CandidatePathScore weight-set to a versioned policy candidate."""
    adapter = PolicyCandidateAdapter()
    c = adapter.to_candidate(name="geo-path", version="v2",
                             weights=_weights(goal_relevance=0.5))
    assert isinstance(c, Candidate)
    assert c.type == "policy"
    assert c.id == "policy@geo-path@v2"
    assert c.payload["w2"] == 0.5  # goal_relevance maps to w2 (matching CandidatePathScore field)


def test_constraint_rules_enforce_normalization_via_gate():
    """P1.1: the safety rules reject a non-normalized weight candidate through the gate."""
    from learning.promotion_gate import PromotionGate, PromotionRule

    rules = add_weights_constraint_rules()
    gate = PromotionGate({"policy": rules})
    good = {"w1": 0.15, "w2": 0.40, "w3": 0.30, "w4": 0.15, "w5": 0.50, "w6": 0.25, "w7": 0.25}
    bad = {"w1": 0.9, "w2": 0.40, "w3": 0.30, "w4": 0.15, "w5": 0.50, "w6": 0.25, "w7": 0.25}  # additive > 1
    # policy constraints are 'safety' rules evaluated against the matrix of the candidate's own weights
    m_good = _constraint_matrix(good)
    m_bad = _constraint_matrix(bad)
    # with an eval rule requiring baseline_delta>0 too
    eval_rule = PromotionRule("policy", kind="eval", metric="baseline_delta", threshold=0.0, comparator="gt")
    gate_w_eval = PromotionGate({"policy": rules + [eval_rule]})
    assert gate_w_eval.evaluate({**m_good, "baseline_delta": 0.1}, "policy@np@v1") == "PROMOTE"
    assert gate_w_eval.evaluate({**m_bad, "baseline_delta": 0.1, "normalized_weights": False},
                                "policy@np@v1") == "REJECT"


def _constraint_matrix(weights):
    return {"normalized_weights": normalized(weights),
            "non_negative_weights": all(v >= 0 for v in weights.values()),
            "bounded_weights": all(0 <= v <= 1 for v in weights.values()),
            "no_regression": True, "complete": True}
