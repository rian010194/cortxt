"""Normalized geometric metrics [0,1] (target architecture §12.2).

Each metric is a pure function over a ProblemSpace + a node id (and a goal when
relevant). They are independent of each other (no circular definitions).
"""

from __future__ import annotations

from .embeddings import cosine, hash_embedding
from .graph_space import ProblemSpace


class GraphMetrics:
    """Stateless collection of the v1 geometric metrics."""

    @staticmethod
    def semantic_closeness(space: ProblemSpace, a: str, b: str, embedder=hash_embedding) -> float:
        """Cosine similarity of embedding vectors for two nodes.

        ``embedder`` is injectable (default ``hash_embedding``) so path scoring and this
        diagnostic proximity metric share one source (P1.1: swap the provider at §27 #10 as
        a drop-in).
        """
        return cosine(embedder(a), embedder(b))

    @staticmethod
    def graph_distance_to_goal(space: ProblemSpace, nid: str, goal: str) -> float:
        """Normalized inverse of shortest graph distance: 1.0 at goal, lower when far."""
        path = space.shortest_path(nid, goal)
        if not path:
            return 0.0  # unreachable -> no progress toward goal
        if nid == goal:
            return 1.0
        return 1.0 / (1.0 + len(path) - 1)  # len-1 edges; closer -> higher

    @staticmethod
    def evidence_coverage(space: ProblemSpace, nid: str) -> float:
        node = space.node(nid)
        return node.evidence if node else 0.0

    @staticmethod
    def contradiction_degree(space: ProblemSpace, nid: str) -> float:
        node = space.node(nid)
        return node.contradiction if node else 0.0

    @staticmethod
    def centrality(space: ProblemSpace, nid: str) -> float:
        """Normalized in-degree centrality of the node."""
        total = len(space.nodes())
        if total <= 1:
            return 0.0
        # count how many nodes point TO nid
        indegree = sum(1 for u in space.ids() if nid in space.successors(u))
        return min(1.0, indegree / (total - 1))

    @staticmethod
    def novelty(space: ProblemSpace, nid: str, visited: set[str]) -> float:
        """1.0 when the node has never been visited before, else lower."""
        return 1.0 if nid not in visited else 0.0

    @staticmethod
    def stability(space: ProblemSpace, nid: str, revisit_count: int) -> float:
        """Confidence-scaled stability; single source for the metric (=== attractor).

        Matches AttractorDetector._stability so there is one definition of what a
        stable re-visit is (CP3.1 fix: unify the two formulas).
        """
        node = space.node(nid)
        confidence = node.confidence if node else 0.5
        return min(1.0, (revisit_count / 3.0) * confidence)

    @staticmethod
    def revisit_ratio(space: ProblemSpace, nid: str) -> float:
        """Fraction of the node's neighbors that have been visited before."""
        node = space.node(nid)
        if node is None:
            return 0.0
        nbr = space.neighbors(node.id)
        if not nbr:
            return 0.0
        visited_nbr = sum(1 for x in nbr if (space.node(x) and space.node(x).visited_count > 0))
        return visited_nbr / len(nbr)

    @staticmethod
    def path_diversity(space: ProblemSpace, nid: str, goal: str) -> float:
        """Fraction of distinct one-hop routes from ``nid`` that can still reach goal."""
        routes = space.successors(nid)
        if not routes:
            return 0.0
        reachable = sum(1 for r in routes if space.shortest_path(r, goal))
        return reachable / len(routes)

    @staticmethod
    def information_gain(space: ProblemSpace, nid: str, before: float, after: float) -> float:
        """Information gain = |confidence change|, clamped to [0,1] (CP3.1 fix)."""
        return min(1.0, abs(after - before))

    # -- aggregate guidance (used by Explorer) ---------------------------- #
    @staticmethod
    def guidance(space: ProblemSpace, nid: str, goal: str, visited: set[str]) -> float:
        """Weighted exploration score: goal-direction + evidence + novelty,
        penalized by contradiction and by stability (avoid re-visiting an
        attractor). Higher = more attractive next step. (CP3.1 fix: stability used,
        unused revisit_count param removed.)"""
        st = GraphMetrics.stability(space, nid, space.node(nid).visited_count if space.node(nid) else 0)
        return (
            0.4 * GraphMetrics.graph_distance_to_goal(space, nid, goal)
            + 0.3 * GraphMetrics.evidence_coverage(space, nid)
            + 0.2 * GraphMetrics.novelty(space, nid, visited)
            - 0.1 * GraphMetrics.contradiction_degree(space, nid)
            - 0.1 * st
        )
