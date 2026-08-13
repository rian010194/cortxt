"""Challenger — validate partial results against expected values."""

from __future__ import annotations

from dataclasses import dataclass

from ..kernel import ProblemState


@dataclass
class ChallengeResult:
    ok: bool
    contradiction: bool = False
    message: str = ""


def challenge(state: ProblemState, expected=None) -> ChallengeResult:
    """Check the parent's integrated result.

    If ``expected`` is provided and mismatches, report a contradiction. Light and
    deterministic — a deeper adversarial challenger arrives with Geometric DM3.
    """
    value = getattr(state, "_computed", None)
    if value is None:
        return ChallengeResult(ok=False, message="no computed result to challenge")
    if expected is not None and value != expected:
        return ChallengeResult(
            ok=False, contradiction=True, message=f"{value} != expected {expected}"
        )
    return ChallengeResult(ok=True)
