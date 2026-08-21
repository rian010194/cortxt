"""rollback — atomic pointer restore (Phase 8, Decision 7; P1.5).

Rollback is a CONSEQUENCE of versioned state: restoring the active-pointer to ``promoted_from``. It is
atomic (Kimi F-02: pointer restore + audit mark happen in ONE registry transaction), audited (the displaced
candidate is marked ``rolled_back`` + timestamp), and idempotent (rolling back when nothing precedes is a
no-op, not corruption). SQL lives in the registry (the schema owner); this module is the orchestration.

Documented v1 limitation (Kimi F-06): rollback restores exactly ONE step (``promoted_from`` is cleared to
NULL after a rollback), so rollback is depth-1, not a full undo-history chain.
"""
from __future__ import annotations

from .registry import CandidateRegistry


def rollback(registry: CandidateRegistry, type_: str, name: str) -> str | None:
    """Restore the active pointer to the previous version for (type_, name).

    Returns the newly-active version, or None if there was nothing to roll back to (no-op).
    Raises ValueError if no candidate of this type/name is currently active (fail-closed).
    """
    current = registry.get_active(type_, name)
    if current is None:
        raise ValueError(f"no active candidate for {type_}@{name} — nothing to roll back")

    previous = registry.promoted_from(type_, name)
    if previous is None:
        return None  # already at the first promotion — idempotent no-op

    registry.apply_rollback(type_, name, previous, current)
    return previous
