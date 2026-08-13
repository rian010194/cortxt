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
        goal_shortest = space.shortest_path(start, goal)
        goal_edges = max(0, len(goal_shortest) - 1)

        for _ in range(self._max_steps):
            path.append(current)
            visited.add(current)
            if current == goal:
                return ExplorationResult(path, True)
            if len(path) - 1 > goal_edges * 2 and goal_shortest:
                # we've strayed too far; do not claim a superior - only goal is
                # reaching it within bound; keep exploring guides
                pass

            nbrs = space.successors(current)
            if not nbrs:
                break
            unvisited_nbrs = [n for n in nbrs if n not in visited]
            candidates = unvisited_nbrs if unvisited_nbrs else nbrs
            next_node = max(
                candidates,
                key=lambda n: GraphMetrics.guidance(
                    space, n, goal, visited,
                    space.node(n).visited_count if space.node(n) else 0,
                ),
            )
            current = next_node

        return ExplorationResult(path, False)


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
