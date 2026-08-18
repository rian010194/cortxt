"""submit_candidate — the candidate ingress door (Fas 8, Beslut 9.5 / 10c / P2.6 phase a).

Validates type registration + provenance, persists the candidate as ``eval_pending``, and runs
EvidenceClassifier ``phase_a`` at submit (Beslut 10c, Kimi P2.6 phase a), returning the typed evidence so it
is bound to the candidate for later gate evaluation. The actual promotion decision happens later via the gate
(which is internal-resolving, self-approval-safe — Beslut 3).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .candidate import Candidate
from .evidence import EvidenceClassifier
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
) -> tuple[str, dict[str, Any]]:
    """Register a candidate as eval_pending with typed phase-(a) evidence.

    Returns ``(candidate_id, evidence)`` where ``evidence`` is the four-group classification
    (facts/events/instructions/tasks) produced by EvidenceClassifier.phase_a (Beslut 10c / P2.6).
    """
    if type_ not in _KNOWN_TYPES:
        raise ValueError(f"unknown candidate type: {type_}")
    if not provenance or not provenance.strip():
        raise ValueError("provenance is required (who/why proposed this candidate)")

    candidate = Candidate(
        type=type_, name=name, version=version,
        payload=dict(payload), status="eval_pending",
        proposed_at=datetime.now(timezone.utc).isoformat(),
    )
    registry.add(candidate)

    evidence = EvidenceClassifier().phase_a(payload=dict(payload), provenance=provenance)
    return candidate.id, evidence
