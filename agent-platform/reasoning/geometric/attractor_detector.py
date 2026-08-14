"""Attractor detection — stable conclusion families (target architecture §12.3)."""

from __future__ import annotations

from dataclasses import dataclass

from .graph_space import ProblemSpace, ReasoningNode


@dataclass
class AttractorResult:
    is_attractor: bool
    node_id: str
    visits: int
    stability: float
    reason: str = ""


class AttractorDetector:
    """Detect a stable conclusion family: a node re-visited >= K times with
    stability > T is classed as an attractor (target §12.3)."""

    def __init__(self, k_threshold: int = 2, stability_threshold: float = 0.5):
        self._k = k_threshold
        self._t = stability_threshold

    def detect(self, space: ProblemSpace, node_id: str) -> AttractorResult:
        node = space.node(node_id)
        if node is None:
            return AttractorResult(False, node_id, 0, 0.0, "missing node")
        if node.visited_count < self._k:
            return AttractorResult(
                False, node_id, node.visited_count,
                node.visited_count / self._k,
                "below visit threshold",
            )
        stability = self._stability(node)
        if stability <= self._t:
            return AttractorResult(
                False, node_id, node.visited_count, stability,
                "below stability threshold",
            )
        return AttractorResult(True, node_id, node.visited_count, stability, "attractor")

    @staticmethod
    def _stability(node: ReasoningNode) -> float:
        # Conservative: stability grows with revisits and high confidence.
        return min(1.0, (node.visited_count / 3.0) * node.confidence)
