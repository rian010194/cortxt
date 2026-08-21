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


def _build_policy(weights: Mapping[str, Any]):
    from reasoning.geometric import CandidatePathScore

    override = {k: float(v) for k, v in weights.items() if k in _WEIGHT_FIELDS}
    return CandidatePathScore(**override)  # type: ignore[arg-type]


def resolve_active_policy(registry: CandidateRegistry, type_: str, name: str):
    """Return the active CandidatePathScore for (type_, name), or None if nothing is promoted."""
    active_version = registry.get_active(type_, name)
    if active_version is None:
        return None
    candidate = registry.get(type_, name, active_version)
    return _build_policy(candidate.payload) if candidate is not None else None
