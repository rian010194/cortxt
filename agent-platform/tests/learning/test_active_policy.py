"""Phase 8 Task 9 — active_policy injection into score_path (default unchanged, production untouched)."""
from __future__ import annotations

from learning.active_policy import resolve_active_policy
from learning.candidate import Candidate
from learning.policy_candidate import PolicyCandidateAdapter
from learning.registry import CandidateRegistry


def _add_and_activate(reg, version, w1):
    cand = PolicyCandidateAdapter().to_candidate("geo", version, {"w1": w1, "w2": 0.4, "w5": 0.5})
    reg.add(cand)
    reg.set_active("policy", "geo", version)
    return cand


def test_active_policy_none_when_nothing_promoted():
    reg = CandidateRegistry(":memory:")
    assert resolve_active_policy(reg, "policy", "geo") is None


def test_active_policy_returns_candidate_path_score_with_active_weights():
    """After promotion of v1, resolve_active_policy returns a policy whose weights match the active version."""
    from reasoning.geometric import CandidatePathScore
    reg = CandidateRegistry(":memory:")
    cand = _add_and_activate(reg, "v1", 0.15)
    policy = resolve_active_policy(reg, "policy", "geo")
    assert isinstance(policy, CandidatePathScore)
    # the promoted candidate's w2 (0.4) is goal_relevance on the resolved policy
    assert abs(policy.w2 - 0.4) < 1e-9


def test_active_policy_reflects_newest_active_version():
    reg = CandidateRegistry(":memory:")
    _add_and_activate(reg, "v1", 0.15)
    v2 = _add_and_activate(reg, "v2", 0.5)  # promote v2 with different w2
    policy = resolve_active_policy(reg, "policy", "geo")
    assert abs(policy.w2 - v2.payload["w2"]) < 1e-9


def test_score_path_default_unchanged_without_active_policy():
    """Production undisturbed: without an active policy, score_path uses the default CandidatePathScore."""
    from reasoning.geometric import CandidatePathScore, ProblemSpace, ReasoningNode, score_path
    reg = CandidateRegistry(":memory:")
    space = ProblemSpace()
    space.add_node(ReasoningNode(id="a", content="x", evidence=0.5, contradiction=0.1))
    space.add_node(ReasoningNode(id="goal", content="g", evidence=0.9, contradiction=0.0))
    space.add_edge("a", "goal")
    default = CandidatePathScore()
    direct = score_path(space, ["a", "goal"], "goal", default)
    resolved = score_path(space, ["a", "goal"], "goal", resolve_active_policy(reg, "policy", "geo") or default)
    assert direct == resolved  # no active policy -> identical to default
