"""Contradiction detection tests (Phase 6, Task 4)."""

from reasoning.geometric import (
    Contradiction,
    ContradictionDetector,
    ProblemSpace,
    ReasoningNode,
    find_contradiction,
)


def test_detect_explicit_contradicts_edge_source_edge():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", contradiction=0.1))
    s.add_node(ReasoningNode(id="b", contradiction=0.1))
    s.add_edge("a", "b", rel_type="contradicts")
    res = ContradictionDetector().detect(s, "a")
    assert any(c.source == "edge" for c in res)
    assert any(c.b == "b" for c in res)


def test_detect_degree_threshold_source_degree():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", contradiction=0.9))  # over threshold
    s.add_node(ReasoningNode(id="b", contradiction=0.2))  # under
    s.add_edge("a", "b")  # opaque; not a contradicts edge
    res = ContradictionDetector(degree_threshold=0.7).detect(s, "b")
    # node b low contradiction but neighbor a is high -> detected via degree
    assert any(c.source == "degree" and c.b == "a" for c in res)


def test_detect_no_contradiction_returns_empty():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", contradiction=0.1))
    s.add_node(ReasoningNode(id="b", contradiction=0.1))
    s.add_edge("a", "b", rel_type="supports")
    assert ContradictionDetector().detect(s, "a") == []


def test_find_contradiction_module_function():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", contradiction=0.1))
    s.add_node(ReasoningNode(id="b", contradiction=0.1))
    s.add_edge("a", "b", rel_type="contradicts")
    res = find_contradiction(s, "a", threshold=0.7)
    assert any(c.source == "edge" for c in res)
