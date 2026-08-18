"""rollback — atomic pointer restore (Fas 8, Beslut 7; P1.5).

Rollback is a CONSEQUENCE of versioned state: restoring the active-pointer to ``promoted_from``. It is
atomic (each registry operation is a single SQLite transaction), audited (the displaced candidate is marked
``rolled_back`` + timestamp), and idempotent (rolling back when nothing precedes is a no-op, not corruption).
SQL lives in the registry (the schema owner); this module is the orchestration.
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

    registry.restore_active(type_, name, previous)
    registry.mark_rolled_back(type_, name, current)
    return previous
