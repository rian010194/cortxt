"""Attractor detection + escape tests (cyclic 3-node graph)."""

from reasoning.geometric import (
    AttractorDetector,
    ProblemSpace,
    ReasoningNode,
    escape_attractor,
)


def cycle3() -> ProblemSpace:
    """a->b->c->a cyclic graph (a strong conclusion family)."""
    s = ProblemSpace()
    for nid in "abc":
        s.add_node(ReasoningNode(id=nid, confidence=0.9))
    s.add_edge("a", "b")
    s.add_edge("b", "c")
    s.add_edge("c", "a")
    return s


def test_cycle_detected_as_attractor():
    s = cycle3()
    assert s.has_cycle() is True
    det = AttractorDetector(k_threshold=2, stability_threshold=0.5)
    # heavily revisit node 'a'
    for _ in range(3):
        s.node("a").touch()  # noqa: SLF001
    res = det.detect(s, "a")
    assert res.is_attractor is True
    assert res.visits == 3


def test_low_visits_not_attractor():
    s = cycle3()
    det = AttractorDetector(k_threshold=2, stability_threshold=0.5)
    s.node("b").touch()  # noqa: SLF001  (only 1 visit)
    res = det.detect(s, "b")
    assert res.is_attractor is False


def test_escape_breaks_cycle_to_unvisited():
    s = cycle3()
    # Visit a and b; escape from a should prefer the unvisited neighbor (c's
    # successor is c for a? a->b). Build a more branched cycle to test escaping.
    s.add_edge("a", "x")  # a has an off-cycle escape route to x
    s.add_node(ReasoningNode(id="x", confidence=0.3))
    visited = {"a", "b", "c"}
    res = escape_attractor(s, "a", visited)
    assert res.escaped is True
    assert res.next_node == "x"  # unvisited neighbor preferred
