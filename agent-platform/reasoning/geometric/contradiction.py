"""Contradiction detection — first-class mechanism (target architecture §12.1).

A contradiction is an incompatibility between two reasoning nodes, detected either via an
explicit ``contradicts`` relation edge or via a node whose contradiction degree exceeds a
threshold. Complements (does not replace) ``AttractorDetector``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .graph_space import ProblemSpace
from .metrics import GraphMetrics


@dataclass
class Contradiction:
    """A detected incompatibility between two nodes."""

    a: str
    b: str
    source: str  # "edge" | "degree"
    degree: float


class ContradictionDetector:
    """Detect contradictions for a node: explicit ``contradicts`` edges or degree threshold."""

    def __init__(self, degree_threshold: float = 0.7):
        self._threshold = degree_threshold

    def detect(self, space: ProblemSpace, node_id: str) -> list[Contradiction]:
        out: list[Contradiction] = []
        nbrs = set(space.successors(node_id)) | _predecessors(space, node_id)

        # 1) explicit contradicts edges (either direction)
        other = list(space.ids())
        for o in other:
            if o == node_id:
                continue
            if "contradicts" in space.edge_types(node_id, o) or "contradicts" in space.edge_types(o, node_id):
                deg = GraphMetrics.contradiction_degree(space, o)
                out.append(Contradiction(a=node_id, b=o, source="edge", degree=deg))

        # 2) degree-based: a neighbor whose contradiction degree exceeds the threshold
        for o in nbrs:
            if o == node_id:
                continue
            if GraphMetrics.contradiction_degree(space, o) >= self._threshold:
                deg = GraphMetrics.contradiction_degree(space, o)
                out.append(Contradiction(a=node_id, b=o, source="degree", degree=deg))

        # de-duplicate by (a, b, source)
        seen: set[tuple[str, str, str]] = set()
        dedup = []
        for c in out:
            key = (c.a, c.b, c.source)
            if key not in seen:
                seen.add(key)
                dedup.append(c)
        return dedup


def _predecessors(space: ProblemSpace, node_id: str) -> set[str]:
    return {u for u in space.ids() if node_id in space.successors(u)}


def find_contradiction(space: ProblemSpace, node_id: str, threshold: float = 0.7) -> list[Contradiction]:
    """Module-level operator over a node (see §10.2 find_contradiction)."""
    return ContradictionDetector(degree_threshold=threshold).detect(space, node_id)
