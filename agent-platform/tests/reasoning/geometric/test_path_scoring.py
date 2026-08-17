"""Path scoring tests (Fas 6, Task 6)."""

from reasoning.geometric import CandidatePathScore, ProblemSpace, ReasoningNode, score_path


def _fixture():
    s = ProblemSpace()
    # strong, low-contradiction path a->c->goal
    s.add_node(ReasoningNode(id="a", evidence=0.9, contradiction=0.0))
    s.add_node(ReasoningNode(id="b", evidence=0.2, contradiction=0.8))
    s.add_node(ReasoningNode(id="c", evidence=0.8, contradiction=0.1))
    s.add_node(ReasoningNode(id="goal", evidence=0.9, contradiction=0.0))
    s.add_edge("a", "c")
    s.add_edge("a", "b")
    s.add_edge("c", "goal")
    s.add_edge("b", "goal")
    return s


def test_score_path_prefers_high_evidence_low_contradiction():
    s = _fixture()
    good = score_path(s, ["a", "c", "goal"], "goal")
    bad = score_path(s, ["a", "b", "goal"], "goal")
    assert good > bad  # strong path ranks higher, no tautology (recomputing nothing)


def test_score_path_default_policy_none_works():
    s = _fixture()
    # mutable-default fix: policy=None instantiates internally; must not raise
    assert score_path(s, ["a", "c", "goal"], "goal") is not None


def test_score_path_contradiction_penalizes():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="x", evidence=0.8, contradiction=0.1))
    s.add_node(ReasoningNode(id="y", evidence=0.8, contradiction=0.9))
    s.add_node(ReasoningNode(id="goal", evidence=0.9))
    s.add_edge("x", "goal")
    s.add_edge("y", "goal")
    lo = score_path(s, ["x", "goal"], "goal")
    hi = score_path(s, ["y", "goal"], "goal")
    assert lo > hi  # higher contradiction lowers score


def test_candidate_path_score_version_present():
    assert CandidatePathScore().version == "v1"
