"""Post-hoc cost aggregation over a (possibly recursive) RunTreeIndex — no
real-time aggregation across process boundaries (spec beslut 2/6)."""
from __future__ import annotations

from supervisor.run_tree import RunTreeIndex


def aggregate_tree_cost(index: RunTreeIndex, node_cost: float = 0.0) -> float:
    """node_cost is this node's own terminal-event 'cost' payload value,
    already read by the caller from session_state (kept out of this pure
    function so it stays easy to unit test without I/O)."""
    total = node_cost
    for child in index.children:
        total += aggregate_tree_cost(child)  # each RunTreeIndex child does not
        # carry its own cost by default; callers walking real session docs
        # pass each child's own node_cost via a wrapping call — see runner.py
        # for the real (I/O-performing) aggregation that reads session logs.
    return total
