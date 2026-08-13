"""Guided exploration over the problem space (target architecture §12.4).

The Explorer ranks candidate moves by the weighted metric sum (goal-direction +
novelty - contradiction), stepping greedily while tracking visited nodes so it
does not immediately loop back into an attractor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph_space import ProblemSpace
from .metrics import GraphMetrics


@dataclass
class ExplorationResult:
    path: list[str] = field(default_factory=list)
    found_goal: bool = False
    attractor_escaped: bool = False


class Explorer:
    def __init__(self, max_steps: int = 50):
        self._max_steps = max_steps

    def explore(self, space: ProblemSpace, start: str, goal: str) -> ExplorationResult:
        visited: set[str] = set()
        current = start
        path: list[str] = []
        escaped = False

        for _ in range(self._max_steps):
            node = space.node(current)
            if node is None:
                break
            node.touch()            # CP3.1 fix: visited_count must update (attractor feed)
            path.append(current)
            visited.add(current)
            if current == goal:
                return ExplorationResult(path, True, escaped)

            nbrs = space.successors(current)
            if not nbrs:
                break
            unvisited_nbrs = [n for n in nbrs if n not in visited]
            candidates = unvisited_nbrs if unvisited_nbrs else nbrs
            next_node = max(
                candidates,
                key=lambda n: GraphMetrics.guidance(space, n, goal, visited),
            )
            # If the best candidate was already explored, we are turning back into
            # a visited region -> treat it as an attractor escape signal.
            if next_node in visited and not escaped:
                escaped = True
            current = next_node

        return ExplorationResult(path, False, escaped)


def bfs_path(space: ProblemSpace, start: str, goal: str) -> list[str]:
    """Brute-force BFS path (comparison baseline for explorer tests)."""
    return space.shortest_path(start, goal)


def exploration_cost(space: ProblemSpace, path: list[str]) -> float:
    """Sum of *negative* metrics along a path: lower is better (used to show the
    guided explorer beats naive BFS on cost)."""
    total = 0.0
    for i, nid in enumerate(path):
        node = space.node(nid)
        evidence = node.evidence if node else 0.0
        # cost = (1 - evidence) penalized by contradiction; path-length normalized
        total += (1.0 - evidence) + (node.contradiction if node else 0.0)
    return total
