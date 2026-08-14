"""Deterministic reasoning operators.

Each operator is a bounded transformation on ProblemState (target architecture
§10.2). These four (inspect, decompose, integrate, verify) are model-free: they
run on the structure of ``content`` and leave an append-only traceable log.
No operator here ever calls a model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .problem_state import ProblemState


@dataclass
class OperatorResult:
    """A value produced by evaluating content (e.g. the combined total)."""

    value: object


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _flatten(obj):
    out = []
    stack = [obj]
    seen = set()  # guard against cyclic Python objects (P1)
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            i = id(cur)
            if i in seen:
                continue
            seen.add(i)
            stack.extend(reversed(cur))
        else:
            out.append(cur)
    return out


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #


def inspect(state: ProblemState) -> OperatorResult:
    """Read a bounded part of the content; record what was inspected."""
    contents = state.content
    leaf_values = (
        contents["values"]
        if isinstance(contents, dict) and "values" in contents
        else contents
    )
    flat = _flatten(leaf_values)
    state.record("inspect", f"inspected {len(flat)} scalar(s)")
    return OperatorResult(flat)


def decompose(state: ProblemState) -> None:
    """Split a nested problem into sub-problems (one node per top-level branch).

    Mutates ``state`` by attaching children. Each child keeps the same
    ``content`` semantics; the engine/strategy decides how to descend.
    """
    contents = state.content
    branches = (
        contents["branches"]
        if isinstance(contents, dict) and "branches" in contents
        else contents
    )
    if not isinstance(branches, list):
        branches = [branches]
    for branch in branches:
        child = ProblemState(content=branch)
        state.add_child(child)
    state.record("decompose", f"created {len(state.children)} sub-problem(s)")


def integrate(state: ProblemState) -> OperatorResult:
    """Fold children's values into the parent and record confidence.

    Requires each child to already carry ``._computed`` (set by ``verify``).
    Returns the parent's folded value.
    """
    total = 0
    for child in state.children:
        val = getattr(child, "_computed", None)
        if val is None:
            # fall back: evaluate the child content directly (flat list)
            val = sum(_flatten(child.content))
        total += val
    state._computed = total  # type: ignore[attr-defined]
    state.record("integrate", f"folded {len(state.children)} child result(s) -> {total}")
    return OperatorResult(total)


def verify(state: ProblemState, expected: object = None) -> OperatorResult:
    """Confirm a candidate value and set confidence.

    If ``expected`` is given, confidence=1.0 on match else 0.0. Otherwise the
    value is taken from the state (computed in place) and confidence reflects
    whether all leaves are scalar numbers.
    """
    if getattr(state, "_computed", None) is None:
        leaf_values = _flatten(state.content)
        total = sum(leaf_values)
        state._computed = total  # type: ignore[attr-defined]
    computed = state._computed  # type: ignore[attr-defined]
    if expected is not None:
        ok = computed == expected
        state.confidence = 1.0 if ok else 0.0
    else:
        all_scalar = all(isinstance(v, (int, float)) for v in _flatten(state.content))
        state.confidence = 1.0 if all_scalar else 0.0
    state.record("verify", f"verified {computed} with confidence {state.confidence:.2f}")
    return OperatorResult(computed)
