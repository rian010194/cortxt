"""resolve_active_policy — injection point (Phase 8, Decision 8; P2.1).

Returns the currently-promoted ``CandidatePathScore`` for a (type, name), or None when nothing is promoted.
It is the ONLY touchpoint between the learning loop and an existing execution path (geometric ``score_path``):
when no policy is active, the caller falls back to the default ``CandidatePathScore()`` and production is
unchanged (Kimi P2.1: fail-open to default on a missing row, DB-read pattern).
"""
from __future__ import annotations

from typing import Any, Mapping

from .registry import CandidateRegistry

# CandidatePathScore weight slots that a policy candidate may override (w1..w7).
_WEIGHT_FIELDS = {f"w{i}" for i in range(1, 8)}


def _build_policy(weights: Mapping[str, Any], embedder):
    from reasoning.geometric import CandidatePathScore

    override = {k: float(v) for k, v in weights.items() if k in _WEIGHT_FIELDS}
    return CandidatePathScore(embedder=embedder, **override)  # type: ignore[arg-type]


def resolve_active_policy(registry: CandidateRegistry, type_: str, name: str, embedder=None):
    """Return the active CandidatePathScore for (type_, name), or None if nothing is promoted.

    ``embedder`` (optional) is an ``EmbeddingFn`` used for the resolved policy's
    scoring; it defaults to the deterministic ``hash_embedding`` stub, so
    production is unchanged unless a caller explicitly selects a real embedder
    (e.g. ``runtime.embedding_port.configured_embedder`` per ADR-035).
    """
    if embedder is None:
        from reasoning.geometric.embeddings import hash_embedding

        embedder = hash_embedding
    active_version = registry.get_active(type_, name)
    if active_version is None:
        return None
    candidate = registry.get(type_, name, active_version)
    return _build_policy(candidate.payload, embedder) if candidate is not None else None
