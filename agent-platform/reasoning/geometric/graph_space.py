"""Directed problem-space graph over reasoning nodes (target architecture §12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReasoningNode:
    """A node in the reasoning space: a claim/hypothesis/state."""

    id: str
    content: str = ""
    # Observable/derived scores used by the metrics (see target architecture §12).
    evidence: float = 0.0      # evidenstäckning basis [0,1]
    contradiction: float = 0.0  # motsägelsegrad [0,1]
    confidence: float = 0.5
    visited_count: int = 0     # for återbesök/attractor detection

    def touch(self) -> None:
        self.visited_count += 1


class ProblemSpace:
    """A directed graph of ReasoningNodes."""

    def __init__(self) -> None:
        self._nodes: dict[str, ReasoningNode] = {}
        self._edges: dict[str, set[str]] = {}

    # -- construction ----------------------------------------------------- #
    def add_node(self, node: ReasoningNode) -> None:
        self._nodes[node.id] = node
        self._edges.setdefault(node.id, set())

    def add_edge(self, src: str, dst: str) -> None:
        self.add_node_id(src)
        self.add_node_id(dst)
        self._edges[src].add(dst)

    def add_node_id(self, nid: str) -> None:
        if nid not in self._nodes:
            self.add_node(ReasoningNode(id=nid))

    def node(self, nid: str) -> Optional[ReasoningNode]:
        return self._nodes.get(nid)

    def nodes(self) -> list[ReasoningNode]:
        return list(self._nodes.values())

    def ids(self) -> list[str]:
        return list(self._nodes.keys())

    def successors(self, nid: str) -> list[str]:
        return sorted(self._edges.get(nid, set()))

    # -- graph algorithms ------------------------------------------------- #
    def neighbors(self, nid: str, hops: int = 1) -> set[str]:
        """All nodes reachable within ``hops`` directed edges."""
        frontier = {nid}
        seen = set()
        for _ in range(hops):
            nxt: set[str] = set()
            for f in frontier:
                seen.add(f)
                nxt |= self._edges.get(f, set())
            frontier = nxt - seen
            seen |= frontier
        seen.discard(nid)
        return seen

    def shortest_path(self, start: str, goal: str) -> list[str]:
        """BFS shortest directed path; [] if unreachable."""
        if start not in self._nodes or goal not in self._nodes:
            return []
        from collections import deque

        prev: dict[str, Optional[str]] = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == goal:
                path: list[str] = []
                while cur is not None:
                    path.append(cur)
                    cur = prev[cur]
                return list(reversed(path))
            for nxt in sorted(self._edges.get(cur, set())):
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
        return []

    def has_cycle(self) -> bool:
        """True if the graph contains a directed cycle (used by attractor tests)."""

        state: dict[str, int] = {}  # 0 unvisited, 1 visiting, 2 done
        for nid in self._nodes:
            state[nid] = 0

        def dfs(u: str) -> bool:
            state[u] = 1
            for v in self._edges.get(u, set()):
                if state.get(v, 0) == 1:
                    return True
                if state.get(v, 0) == 0 and dfs(v):
                    return True
            state[u] = 2
            return False

        return any(state[n] == 0 and dfs(n) for n in self._nodes)
