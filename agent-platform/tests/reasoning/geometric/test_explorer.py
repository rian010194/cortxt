"""Explorer tests — guided exploration beats naive BFS path cost."""

from reasoning.geometric import Explorer, ProblemSpace, ReasoningNode, exploration_cost
from reasoning.geometric.explorer import bfs_path


def low_cost_graph() -> ProblemSpace:
    """A: greedy-high-evidence route A->C->D->Z beats the short-hop A->B->Z,
    because B is low-evidence/high-contradiction (expensive by cost metric)."""
    s = ProblemSpace()
    for nid, ev, contra in [
        ("A", 0.5, 0.0), ("B", 0.1, 0.8), ("C", 0.9, 0.0),
        ("D", 0.9, 0.0), ("Z", 0.9, 0.0),
    ]:
        s.add_node(ReasoningNode(id=nid, evidence=ev, contradiction=contra))
    s.add_edge("A", "B")
    s.add_edge("B", "Z")
    s.add_edge("A", "C")
    s.add_edge("C", "D")
    s.add_edge("D", "Z")
    return s


def test_explorer_reaches_goal():
    s = low_cost_graph()
    res = Explorer(max_steps=10).explore(s, "A", "Z")
    assert res.found_goal is True
    assert res.path[-1] == "Z"


def test_explorer_path_cost_strictly_below_bfs():
    s = low_cost_graph()
    res = Explorer(max_steps=10).explore(s, "A", "Z")
    assert res.found_goal
    explorer_cost = exploration_cost(s, res.path)
    bfs = bfs_path(s, "A", "Z")
    bfs_cost = exploration_cost(s, bfs)
    assert explorer_cost < bfs_cost
    assert res.path[0] == "A"
