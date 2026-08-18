"""Fas 8 Task 10 — exit criterion: better promotes, worse rejects, production untouched (double-direction).

Reuses the N=3 evaluation pattern from Fas 5/6/7 and the geometry fixture surface (score_path /
CandidatePathScore). The exit criterion (spec §23): no automatic change reaches production without verified
promotion. Detailed here:
  (a) a deliberately BETTER policy candidate can be promoted through the loop (mechanism works);
  (b) a deliberately WORSE candidate is REJECTed and production is never touched;
  (c) production (score_path with the active/default policy) returns identical results before/after a
      promotion/rollback cycle.
"""
from __future__ import annotations

from learning.active_policy import resolve_active_policy
from learning.candidate import Candidate
from learning.evidence import EvidenceClassifier
from learning.evaluator import Evaluator
from learning.policy_candidate import PolicyCandidateAdapter, add_weights_constraint_rules
from learning.promotion_gate import PromotionGate, PromotionRule
from learning.registry import CandidateRegistry
from learning.rollback import rollback


# --- geometry fixture surface (reused from Fas 6) ------------------------------------------------
def _space_with_paths():
    from reasoning.geometric import ProblemSpace, ReasoningNode
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="start", content="start context", evidence=0.4, contradiction=0.1))
    s.add_node(ReasoningNode(id="s1", content="claim supporting conclusion", evidence=0.7, contradiction=0.1))
    s.add_node(ReasoningNode(id="s2", content="evidence confirming conclusion", evidence=0.7, contradiction=0.1))
    s.add_node(ReasoningNode(id="goal", content="final resolved outcome", evidence=0.9, contradiction=0.0))
    s.add_edge("start", "s1"); s.add_edge("s1", "s2"); s.add_edge("s2", "goal")
    return s, ["start", "s1", "s2", "goal"], "goal"


def _score(weights):
    """Geometric path score with a given CandidatePathScore weight-override (reuses score_path)."""
    from reasoning.geometric import CandidatePathScore, score_path
    space, path, goal = _space_with_paths()
    policy = CandidatePathScore(**{k: float(v) for k, v in weights.items() if k.startswith("w")})
    return score_path(space, path, goal, policy)


def _weights(**over):
    w = {"w1": 0.15, "w2": 0.40, "w3": 0.30, "w4": 0.15, "w5": 0.50, "w6": 0.25, "w7": 0.25}
    w.update(over)
    return w


def _eval_rule():
    return PromotionRule("policy", kind="eval", metric="baseline_delta", threshold=0.0, comparator="gt")


# --- exit tests ----------------------------------------------------------------------------------
def test_better_candidate_promotes_through_full_loop():
    """(a) A strictly-better policy candidate is PROMOTED end-to-end (mechanism works)."""
    reg = CandidateRegistry(":memory:")
    # baseline v1 active
    reg.add(PolicyCandidateAdapter().to_candidate("geo", "v1", _weights()))
    reg.set_active("policy", "geo", "v1")

    better = PolicyCandidateAdapter().to_candidate("geo", "v2", _weights(w2=0.6))  # higher goal_relevance
    reg.add(better)

    baseline = reg.get("policy", "geo", "v1")
    fixtures = ["f1"]
    ev = Evaluator()
    rows = ev.evaluate_matrix([better], baseline, fixtures=fixtures,
                              scorer=lambda c, f: _score(c.payload))
    verdict = PromotionGate(
        {"policy": add_weights_constraint_rules() + [_eval_rule()]}
    ).evaluate({"baseline_delta": rows[0].baseline_delta, "no_regression": rows[0].no_regression,
                "complete": rows[0].complete}, better.id)
    assert verdict == "PROMOTE"


def test_worse_candidate_rejected_and_production_untouched():
    """(b) A worse candidate is REJECTed; the active policy stays v1 (production never touched)."""
    reg = CandidateRegistry(":memory:")
    reg.add(PolicyCandidateAdapter().to_candidate("geo", "v1", _weights()))
    reg.set_active("policy", "geo", "v1")
    baseline = reg.get("policy", "geo", "v1")

    worse = PolicyCandidateAdapter().to_candidate("geo", "v2", _weights(w2=0.1))  # lower goal_relevance
    reg.add(worse)
    before = resolve_active_policy(reg, "policy", "geo")  # v1

    rows = Evaluator().evaluate_matrix([worse], baseline, fixtures=["f1"],
                                       scorer=lambda c, f: _score(c.payload))
    verdict = PromotionGate(
        {"policy": add_weights_constraint_rules() + [_eval_rule()]}
    ).evaluate({"baseline_delta": rows[0].baseline_delta, "no_regression": rows[0].no_regression,
                "complete": rows[0].complete}, worse.id)
    assert verdict == "REJECT"
    # production untouched: the active policy is still v1 (w2=0.40), NOT the rejected v2 (w2=0.1)
    after = resolve_active_policy(reg, "policy", "geo")
    assert reg.get_active("policy", "geo") == "v1"
    assert after.w2 == before.w2 == 0.4


def test_production_undisturbed_across_promote_rollback_cycle():
    """(c) score_path output is identical before/after a promote-then-rollback cycle (no side effect)."""
    from reasoning.geometric import CandidatePathScore, score_path
    reg = CandidateRegistry(":memory:")
    reg.add(PolicyCandidateAdapter().to_candidate("geo", "v1", _weights()))
    reg.set_active("policy", "geo", "v1")
    baseline = reg.get("policy", "geo", "v1")
    better = PolicyCandidateAdapter().to_candidate("geo", "v2", _weights(w2=0.6))
    reg.add(better)

    space, path, goal = _space_with_paths()
    default = CandidatePathScore()
    before = score_path(space, path, goal, default)

    # promote v2, roll back to v1
    reg.set_active("policy", "geo", "v2")
    rollback(reg, "policy", "geo")
    active = resolve_active_policy(reg, "policy", "geo")
    after = score_path(space, path, goal, active)  # active is now back to v1 default-equivalent

    # score_path with the restored v1 policy equals the original default-equivalent score
    v1_policy = resolve_active_policy(reg, "policy", "geo")
    assert abs(score_path(space, path, goal, v1_policy) - before) < 1e-9
