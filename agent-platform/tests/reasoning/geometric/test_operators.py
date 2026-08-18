"""Operator tests — change_perspective (Fas 6, Task 5). compare_paths tested in Task 6."""

from reasoning.geometric import (
    PerspectiveResult,
    ProblemSpace,
    ReasoningNode,
    change_perspective,
)


def _space_with_alternatives():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", evidence=0.8))
    s.add_node(ReasoningNode(id="b", evidence=0.7))
    s.add_node(ReasoningNode(id="target", evidence=0.9))
    s.add_edge("a", "b", rel_type="supports")
    s.add_edge("a", "target", rel_type="alternative_to")  # alternative perspective to target
    s.add_edge("target", "b", rel_type="analogous_to")
    return s


def test_change_perspective_detects_alternative_relation():
    s = _space_with_alternatives()
    res = change_perspective(s, "a", "target")
    assert isinstance(res, PerspectiveResult)
    assert res.changed is True
    # subgraph should contain the target node and its alternative-related neighbours
    assert "target" in res.subgraph.ids()


def test_change_perspective_no_alternative_degrades():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="x"))
    s.add_node(ReasoningNode(id="y"))
    s.add_edge("x", "y", rel_type="supports")
    res = change_perspective(s, "x", "y")
    assert res.changed is False
    assert res.subgraph.ids() == []


def test_change_perspective_analogous_to_target():
    s = _space_with_alternatives()
    res = change_perspective(s, "b", "target")
    assert res.changed is True
    assert "b" in res.subgraph.ids()


def test_compare_paths_returns_better_path_and_score():
    from reasoning.geometric import CandidatePathScore, ReasoningNode, compare_paths, score_path
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", evidence=0.9, contradiction=0.0))
    s.add_node(ReasoningNode(id="b", evidence=0.2, contradiction=0.8))
    s.add_node(ReasoningNode(id="goal", evidence=0.9, contradiction=0.0))
    s.add_edge("a", "goal")
    s.add_edge("a", "b")
    s.add_edge("b", "goal")
    good_path = ["a", "goal"]
    bad_path = ["a", "b", "goal"]
    best, best_score = compare_paths(s, good_path, bad_path, "goal")
    assert best == good_path
    assert best_score == score_path(s, good_path, "goal")
