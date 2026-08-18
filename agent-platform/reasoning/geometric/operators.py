"""Geometric operators over the problem space (target architecture §10.2).

First operator set (Fas 6, deterministic): ``change_perspective`` builds a sub-graph viewed
from an alternative standpoint via ``alternative_to`` / ``analogous_to`` relations; degrades
to an empty graph + ``changed=False`` when no such relation exists. ``compare_paths`` (relative
to path scoring) lives here but is populated once ``score_path`` lands (Task 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph_space import ProblemSpace

_PERSPECTIVE_TYPES = {"alternative_to", "analogous_to"}


@dataclass
class PerspectiveResult:
    subgraph: ProblemSpace = field(default_factory=ProblemSpace)
    changed: bool = False


def change_perspective(space: ProblemSpace, nid: str, target: str) -> PerspectiveResult:
    """Build a sub-graph seen from an alternative view of ``target``.

    ``changed`` is True iff at least one ``alternative_to``/``analogous_to`` relation involves
    ``target``; the returned subgraph then holds ``target`` and every node connected to it via
    those perspective relations. Otherwise the subgraph is empty and ``changed`` is False
    (a controlled degradation, not an error).
    """
    related: set[str] = set()
    for (src, dst, types) in space.iter_edges():
        if target in (src, dst) and _PERSPECTIVE_TYPES.intersection(types):
            related.add(src)
            related.add(dst)
    if not related:
        return PerspectiveResult(changed=False)

    sub = ProblemSpace()
    for nid2 in related:
        n = space.node(nid2)
        if n is not None:
            sub.add_node(n)
    # include the perspective relations themselves (preserve type info)
    for (src, dst, types) in space.iter_edges():
        if src in related and dst in related:
            for t in types:
                if t in _PERSPECTIVE_TYPES:
                    sub.add_edge(src, dst, rel_type=t)
    return PerspectiveResult(subgraph=sub, changed=True)


def compare_paths(space, path_a, path_b, goal, policy=None) -> tuple[list[str], float]:
    """Rank two candidate paths via path scoring (Task 5/6); return (better_path, score)."""
    from .path_scoring import CandidatePathScore, score_path

    policy = policy or CandidatePathScore()
    sa = score_path(space, path_a, goal, policy)
    sb = score_path(space, path_b, goal, policy)
    if sb > sa:
        return path_b, sb
    return path_a, sa
