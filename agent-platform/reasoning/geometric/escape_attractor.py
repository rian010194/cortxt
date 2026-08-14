"""Escape operator — break out of an attractor (target architecture §12.3).

When an attractor is detected, ``escape_attractor`` forces exploration toward a
previously-unvisited neighbor (change_perspective / novel region) so the loop
does not re-land on the same conclusion family.
"""

from __future__ import annotations

from dataclasses import dataclass

from .graph_space import ProblemSpace


@dataclass
class EscapeResult:
    escaped: bool
    next_node: str | None
    reason: str


def escape_attractor(space: ProblemSpace, node_id: str, visited: set[str]) -> EscapeResult:
    """Pick an unvisited neighbor of ``node_id``; fall back to highest-visited
    neighbor only if none is unvisited. Returns None when no neighbor exists."""
    nbrs = list(space.successors(node_id))
    unvisited = [n for n in nbrs if n not in visited]
    if unvisited:
        # prefer the unvisited neighbor closest to highest degree (best branching)
        pick = max(unvisited, key=lambda n: len(space.successors(n)))
        return EscapeResult(True, pick, "unvisited neighbor")
    if not nbrs:
        return EscapeResult(False, None, "no neighbors to escape to")
    pick = max(nbrs, key=lambda n: len(space.successors(n)))
    return EscapeResult(False, pick, "only visited neighbors remain")
