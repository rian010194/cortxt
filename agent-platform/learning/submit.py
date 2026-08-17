"""submit_candidate — the candidate ingress door (Fas 8, Beslut 9.5 / P2.6 phase a).

Validates type registration + provenance, persists the candidate as ``eval_pending``, and runs
EvidenceClassifier ``phase_a`` at submit (Kimi P2.6). The actual promotion decision happens later via the
gate (which is internal-resolving, self-approval-safe — Beslut 3).
"""
from __future__ import annotations

from typing import Any, Mapping

from .registry import CandidateRegistry

# registered candidate types for v1 (future types are added here as adapters, Beslut 9.1)
_KNOWN_TYPES = {"policy", "skill", "tool"}


def submit_candidate(
    registry: CandidateRegistry,
    type_: str,
    name: str,
    version: str,
    payload: Mapping[str, Any],
    provenance: str,
) -> str:
    """Register a candidate as eval_pending; return its id (type@name@version)."""
    if type_ not in _KNOWN_TYPES:
        raise ValueError(f"unknown candidate type: {type_}")
    if not provenance or not provenance.strip():
        raise ValueError("provenance is required (who/why proposed this candidate)")
    from .candidate import Candidate

    candidate = Candidate(
        type=type_, name=name, version=version,
        payload=dict(payload), status="eval_pending", proposed_at=None,
    )
    registry.add(candidate)
    return candidate.id
