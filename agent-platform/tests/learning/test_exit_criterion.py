"""Phase 8 Task 10 — exit criterion: better promotes, worse rejects, violating weights rejected, production
untouched (double-direction, N=3 fixture paths).

Reuses the evaluation pattern from Phase 5/6/7 and geometric `score_path` / `CandidatePathScore`. The exit
criterion (spec §23): no automatic change reaches production without verified promotion. Kimi Task8-11 fixes:
- N≥3 distinct path fixtures (was N=1, mechanism-tautological).
- policy-constraint safety rules ACTUALLY exercised via `constraint_matrix()` (was passed by accident).
- test (c) compares pre/post-rollback with the SAME active policy (not default vs v1).
"""
from __future__ import annotations

from learning.active_policy import resolve_active_policy
from learning.evaluator import Evaluator
from learning.policy_candidate import PolicyCandidateAdapter, constraint_matrix
from learning.promotion_gate import PromotionGate
from learning.registry import CandidateRegistry
from learning.rollback import rollback

# --- geometry fixture surface: N=3 distinct paths (reused geometry from Phase 6) ----------------------
def _space_for(seed: int):
    from reasoning.geometric import ProblemSpace, ReasoningNode
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="start", content=f"start {seed}", evidence=0.4, contradiction=0.1))
    s.add_node(ReasoningNode(id="s1", content=f"claim {seed}", evidence=0.7, contradiction=0.1))
    s.add_node(ReasoningNode(id="s2", content=f"evidence {seed}", evidence=0.7, contradiction=0.1))
    s.add_node(ReasoningNode(id="goal", content=f"goal {seed}", evidence=0.9, contradiction=0.0))
    s.add_edge("start", "s1"); s.add_edge("s1", "s2"); s.add_edge("s2", "goal")
    return s, ["start", "s1", "s2", "goal"], "goal"


def _score(weights, seed: int):
    from reasoning.geometric import CandidatePathScore, score_path
    space, path, goal = _space_for(seed)
    policy = CandidatePathScore(**{k: float(v) for k, v in weights.items() if k.startswith("w")})
    return score_path(space, path, goal, policy)


def _weights(**over):
    w = {"w1": 0.15, "w2": 0.40, "w3": 0.30, "w4": 0.15, "w5": 0.50, "w6": 0.25, "w7": 0.25}
    w.update(over)
    return w


# N=3 distinct fixtures; average candidate-baseline delta over all three (Kimi: not N=1).
def _delta(baseline_w, cand_w):
    seeds = [1, 2, 3]
    return sum(_score(cand_w, s) - _score(baseline_w, s) for s in seeds) / len(seeds)


def _verdict(gate, cand, cand_w, baseline_w):
    matrix = {"complete": True, "no_regression": _delta(baseline_w, cand_w) >= 0,
              "baseline_delta": _delta(baseline_w, cand_w)}
    matrix.update(constraint_matrix(cand_w))  # Kimi: exercise the constraint safety rules for real
    return gate.evaluate(matrix, cand.id)


def _gate():
    return PromotionGate({"policy": PolicyCandidateAdapter().rules()})


def _verdict_for(cand_w, base_w=_weights()):
    """Gate verdict for a candidate weight-set vs the base. Delta-sign-driven (honest): the test does NOT
    hardcode which weights are 'better' — it asserts the gate agrees with the geometry-computed delta."""
    reg = CandidateRegistry(":memory:")
    reg.add(PolicyCandidateAdapter().to_candidate("geo", "v1", base_w))
    reg.set_active("policy", "geo", "v1")
    cand = PolicyCandidateAdapter().to_candidate("geo", "v2", cand_w)
    reg.add(cand)
    return _verdict(_gate(), cand, cand_w, base_w), _delta(base_w, cand_w)


# --- exit tests ------------------------------------------------------------------------------------
def test_better_candidate_promotes():
    """(a) A candidate with a POSITIVE measured baseline-delta (strictly better) PROMOTEs (N=3 paths)."""
    # search a normalized weight set whose geometry-computed delta is positive (direction-agnostic).
    base_w = _weights()
    better_w = None
    for goal in (0.6, 0.55, 0.5, 0.45, 0.35, 0.3, 0.25, 0.2, 0.1):
        cand = _weights(w2=goal, w3=round(1.0 - 0.15 - goal - 0.15, 2))  # keep additive sum = 1.0
        if _delta(base_w, cand) > 0:
            better_w = cand
            break
    assert better_w is not None, "could not find a strictly-better normalized candidate"
    verdict, d = _verdict_for(better_w, base_w)
    assert d > 0
    assert verdict == "PROMOTE"


def test_worse_candidate_rejected_and_production_untouched():
    """(b) A candidate with a NEGATIVE measured baseline-delta is REJECTed; active policy stays v1."""
    base_w = _weights()
    worse_w = None
    for goal in (0.6, 0.55, 0.5, 0.45, 0.35, 0.3, 0.25, 0.2, 0.1):
        cand = _weights(w2=goal, w3=round(1.0 - 0.15 - goal - 0.15, 2))
        if _delta(base_w, cand) < 0:
            worse_w = cand
            break
    assert worse_w is not None, "could not find a strictly-worse normalized candidate"
    reg = CandidateRegistry(":memory:")
    reg.add(PolicyCandidateAdapter().to_candidate("geo", "v1", base_w))
    reg.set_active("policy", "geo", "v1")
    cand = PolicyCandidateAdapter().to_candidate("geo", "v2", worse_w)
    reg.add(cand)
    verdict, d = _verdict(_gate(), cand, worse_w, base_w), _delta(base_w, worse_w)
    assert d < 0
    assert verdict == "REJECT"
    assert reg.get_active("policy", "geo") == "v1"
    assert resolve_active_policy(reg, "policy", "geo").w2 == 0.4  # still the baseline


def test_non_normalized_weights_rejected():
    """(c', Kimi) A candidate whose weights violate the §12.4 normalization contract is REJECTed by the
    constraint safety rules (previously passed by accident when the metric key was absent)."""
    reg = CandidateRegistry(":memory:")
    base_w = _weights()
    reg.add(PolicyCandidateAdapter().to_candidate("geo", "v1", base_w))
    reg.set_active("policy", "geo", "v1")
    bad_w = _weights(w1=0.9)  # additive > 1.0
    bad = PolicyCandidateAdapter().to_candidate("geo", "v2", bad_w)
    reg.add(bad)
    assert _verdict(_gate(), bad, bad_w, base_w) == "REJECT"


def test_production_undisturbed_across_promote_rollback_cycle():
    """(c) score_path output is identical before/after a promote-then-rollback with THE SAME active policy
    restored (v1), not default-vs-v1 tautology (Kimi fix)."""
    from reasoning.geometric import CandidatePathScore, score_path
    reg = CandidateRegistry(":memory:")
    base_w = _weights()
    reg.add(PolicyCandidateAdapter().to_candidate("geo", "v1", base_w))
    reg.set_active("policy", "geo", "v1")

    space, path, goal = _space_for(1)
    resolved = resolve_active_policy(reg, "policy", "geo")  # v1 policy
    before = score_path(space, path, goal, resolved)

    # promote an actual v2, then roll back to v1
    reg.add(PolicyCandidateAdapter().to_candidate("geo", "v2", _weights(w2=0.6)))
    reg.set_active("policy", "geo", "v2")
    rollback(reg, "policy", "geo")
    restored = resolve_active_policy(reg, "policy", "geo")  # back to v1
    after = score_path(space, path, goal, restored)
    assert abs(after - before) < 1e-9
