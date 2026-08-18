"""Challenger — validate partial results against expected values."""

from __future__ import annotations

from dataclasses import dataclass

from ..kernel import ProblemState


@dataclass
class ChallengeResult:
    ok: bool
    contradiction: bool = False
    message: str = ""


def challenge(state: ProblemState, expected=None,
              lost_children: frozenset[str] = frozenset()) -> ChallengeResult:
    """Check the parent's integrated result.

    If ``expected`` is provided and mismatches, report a contradiction. Light and
    deterministic — a deeper adversarial challenger arrives with Geometric DM3.

    ``lost_children`` is accepted for API parity with ``integrate_results`` — a
    result computed from partial (lost-child-excluded) evidence should not be
    treated as fully-confirmed. ``state._incomplete`` (set by integrate_results
    when any child was lost) surfaces that partial-evidence state, so a
    challenger can distinguish a confirmed value from a partial one.
    """
    value = getattr(state, "_computed", None)
    if value is None:
        return ChallengeResult(ok=False, message="no computed result to challenge")
    incomplete = bool(getattr(state, "_incomplete", False))
    if incomplete:
        return ChallengeResult(ok=False, message="result is partial (lost children excluded)")
    if expected is not None and value != expected:
        return ChallengeResult(
            ok=False, contradiction=True, message=f"{value} != expected {expected}"
        )
    return ChallengeResult(ok=True)
