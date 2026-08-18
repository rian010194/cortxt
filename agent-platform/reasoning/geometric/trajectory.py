"""Trajectory report — data contract + auditable report (target architecture §12, §23).

``TrajectoryReport`` is both the serializable data contract and the report for a geometric
exploration: it carries the problem space (typed nodes + typed edges), the chosen path, its
path score and policy version, plus attractor/contradiction flags. GUI viewer is DEFERRED
(operator decision 2026-08-17); the report fulfils §23's "trajectory viewer ELLER rapport"
via the report variant. 0 model calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .graph_space import ProblemSpace


@dataclass
class TrajectoryReport:
    version: str = "v1"
    space: ProblemSpace = field(default_factory=ProblemSpace)
    path: list[str] = field(default_factory=list)
    goal: str | None = None
    path_score: float | None = None
    policy_version: str | None = None
    attractor_nodes: list[str] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Expand the ProblemSpace explicitly into nodes/edges lists (P2.1: not json.dumps(space))."""
        nodes = []
        for nid in self.space.ids():
            n = self.space.node(nid)
            nodes.append({
                "id": nid,
                "node_type": n.node_type if n else None,
                "evidence": n.evidence if n else 0.0,
                "contradiction": n.contradiction if n else 0.0,
                "confidence": n.confidence if n else 0.0,
                "visited_count": n.visited_count if n else 0,
                "metadata": n.metadata if n else None,
            })
        edges = []
        for (src, dst, types) in self.space.iter_edges():
            edges.append({"src": src, "dst": dst, "types": list(types)})
        return {
            "version": self.version,
            "goal": self.goal,
            "path": list(self.path),
            "path_score": self.path_score,
            "policy_version": self.policy_version,
            "attractor_nodes": list(self.attractor_nodes),
            "contradictions": list(self.contradictions),
            "nodes": nodes,
            "edges": edges,
        }

    def to_json(self) -> str:
        """Deterministic JSON (stable key order, non-serializable -> str)."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    def render_text(self) -> str:
        lines = [f"TrajectoryReport v{self.version}"]
        if self.goal:
            lines.append(f"goal: {self.goal}")
        lines.append("path: " + " -> ".join(self.path) if self.path else "path: (empty)")
        if self.path_score is not None:
            lines.append(f"path_score: {self.path_score}")
        if self.policy_version:
            lines.append(f"policy_version: {self.policy_version}")
        if self.attractor_nodes:
            lines.append("attractors: " + ", ".join(self.attractor_nodes))
        if self.contradictions:
            lines.append(f"contradictions: {len(self.contradictions)}")
        lines.append(f"nodes: {len(self.space.ids())}")
        return "\n".join(lines)
