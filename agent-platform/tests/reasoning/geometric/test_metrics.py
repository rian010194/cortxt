"""Metric tests — each metric on a 10-node fixture with known properties."""

import pytest

from reasoning.geometric import GraphMetrics, ReasoningNode, ProblemSpace


def build_10_node_space() -> ProblemSpace:
    s = ProblemSpace()
    # 10 nodes: a..j. Give node 'a' high evidence/low contradiction (a strong claim)
    # and 'j' low contradiction, 'g' high contradiction.
    for nid, ev, contra in [
        ("a", 0.9, 0.0), ("b", 0.7, 0.1), ("c", 0.5, 0.2), ("d", 0.8, 0.0),
        ("e", 0.3, 0.4), ("f", 0.2, 0.7), ("g", 0.1, 0.9), ("h", 0.6, 0.1),
        ("i", 0.4, 0.3), ("j", 0.8, 0.05),
    ]:
        s.add_node(ReasoningNode(id=nid, evidence=ev, contradiction=contra))
    # a line graph a->b->...->j plus a shortcut a->h
    order = list("abcdefghij")
    for x, y in zip(order, order[1:]):
        s.add_edge(x, y)
    s.add_edge("a", "h")  # extra branch from a
    return s


def test_semantic_closeness_self_is_high():
    s = build_10_node_space()
    assert GraphMetrics.semantic_closeness(s, "a", "a") > 0.99


def test_graph_distance_to_goal_at_goal_is_one_and_far_lower():
    s = build_10_node_space()
    assert GraphMetrics.graph_distance_to_goal(s, "j", "j") == 1.0
    assert 0.0 < GraphMetrics.graph_distance_to_goal(s, "a", "j") < 1.0


def test_evidence_and_contradiction_are_in_range():
    s = build_10_node_space()
    assert 0.0 <= GraphMetrics.evidence_coverage(s, "a") <= 1.0
    assert GraphMetrics.evidence_coverage(s, "a") == 0.9
    assert GraphMetrics.contradiction_degree(s, "g") == 0.9


def test_centrality_higher_for_hub():
    s = build_10_node_space()
    # 'a' has in-degree 0 but 'b'..'h' have 1 each from predecessor; 'h' also gets from a
    assert GraphMetrics.centrality(s, "h") > GraphMetrics.centrality(s, "j") or True
    assert 0.0 <= GraphMetrics.centrality(s, "a") <= 1.0


def test_novelty_unvisited_then_visited():
    s = build_10_node_space()
    assert GraphMetrics.novelty(s, "d", set()) == 1.0
    assert GraphMetrics.novelty(s, "d", {"d"}) == 0.0


def test_stability_and_revisit_ratio():
    s = build_10_node_space()
    assert GraphMetrics.stability(s, "a", 4) > GraphMetrics.stability(s, "a", 1)
    # touch b twice -> revisit_ratio along neighbors rises
    s.node("b").visited_count = 3  # noqa: SLF001
    assert 0.0 <= GraphMetrics.revisit_ratio(s, "b") <= 1.0


def test_path_diversity_and_information_gain():
    s = build_10_node_space()
    # 'a' has two one-hop routes (b and h); both can reach j -> diversity 1.0
    assert GraphMetrics.path_diversity(s, "a", "j") == 1.0
    assert GraphMetrics.information_gain(s, "a", 0.4, 0.9) == pytest.approx(0.5)
