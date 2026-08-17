"""Path scoring — versioned search function (target architecture §12.4).

``CandidatePathScore`` is a versioned policy dataclass carrying the §12.4 weights and an
``embedder`` (default ``hash_embedding``); ``score_path`` ranks a candidate path. Weights are
policy data (normalized: additive weights sum to 1.0, subtractive weights sum to 1.0) — the
only place that consumes embeddings, so the §27 #10 provider swaps in as a drop-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .embeddings import EmbeddingFn, cosine, hash_embedding
from .graph_space import ProblemSpace
from .metrics import GraphMetrics


@dataclass
class CandidatePathScore:
    """Versioned, normalized path-scoring policy (§12.4)."""

    version: str = "v1"
    # additive (positive) weights — sum to 1.0
    w1: float = 0.15  # expected_information_gain
    w2: float = 0.40  # goal_relevance
    w3: float = 0.30  # evidence_coverage
    w4: float = 0.15  # path_novelty
    # subtractive (negative) weights — sum to 1.0
    w5: float = 0.50  # contradiction_risk
    w6: float = 0.25  # expected_cost
    w7: float = 0.25  # policy_risk
    embedder: EmbeddingFn = field(default=hash_embedding)


def _avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def score_path(
    space: ProblemSpace,
    path: list[str],
    goal: str,
    policy: CandidatePathScore | None = None,
) -> float:
    """Rank a candidate path; higher is better. ``policy`` default is created per call (P1.2)."""
    policy = policy or CandidatePathScore()
    if not path:
        return 0.0

    ig = [cosine(policy.embedder(n), policy.embedder(goal)) for n in path]
    gr = [GraphMetrics.graph_distance_to_goal(space, n, goal) for n in path]
    ev = [GraphMetrics.evidence_coverage(space, n) for n in path]
    distinct = len(set(path))
    novelty = distinct / len(path)
    cr = [GraphMetrics.contradiction_degree(space, n) for n in path]
    # expected_cost: penalize low evidence (1 - coverage), averaged
    ec = [(1.0 - GraphMetrics.evidence_coverage(space, n)) for n in path]
    # policy_risk: fraction of nodes above a contradiction policy threshold (a policy rule)
    pr = [1.0 if GraphMetrics.contradiction_degree(space, n) >= 0.5 else 0.0 for n in path]

    return (
        policy.w1 * _avg(ig)
        + policy.w2 * _avg(gr)
        + policy.w3 * _avg(ev)
        + policy.w4 * novelty
        - policy.w5 * _avg(cr)
        - policy.w6 * _avg(ec)
        - policy.w7 * _avg(pr)
    )
