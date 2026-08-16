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


def inspect_with_model(state: ProblemState, invoke) -> OperatorResult:
    """Read content by delegating to an external callable instead of flattening scalars.

    ``invoke`` is ``Callable[[Any], Any]``: takes the state's content, returns
    the model's raw response. Unlike ``inspect()``, this never touches
    arithmetic — the model performs the "reading" this operator would
    otherwise flatten deterministically.
    """
    response = invoke(state.content)
    state._computed = response  # type: ignore[attr-defined]
    state.record("inspect_with_model", "inspected content via an external model call")
    return OperatorResult(response)


def verify_against_schema(state: ProblemState, validate) -> OperatorResult:
    """Confirm ``state._computed`` satisfies an external validator; confidence 1.0/0.0.

    ``validate`` is ``Callable[[Any], bool]`` (e.g. JSON Schema validation).
    Unlike ``verify()``, this never falls back to summing ``state.content``.
    """
    computed = getattr(state, "_computed", None)
    ok = bool(validate(computed))
    state.confidence = 1.0 if ok else 0.0
    state.record("verify_against_schema", f"validated with confidence {state.confidence:.2f}")
    return OperatorResult(computed)


def propose_minimal_patch(state: ProblemState, propose) -> OperatorResult:
    """Ask an external callable for a patch proposal; store it on the state.

    ``propose`` is ``Callable[[Any], Any]``: takes the state's content (the
    assembled coding context) and returns the platform's patch record. This is
    the only model-assisted operator in the CODING_ASSISTED strategy — the
    other two are deterministic checks over what this one produced.
    """
    proposal = propose(state.content)
    state._computed = proposal  # type: ignore[attr-defined]
    state.record("propose_minimal_patch", "obtained a patch proposal via an external call")
    return OperatorResult(proposal)


def inspect_diff_against_scope(state: ProblemState, inspect_scope) -> OperatorResult:
    """Check the PLATFORM-COMPUTED diff against the declared scope; 1.0/0.0.

    ``inspect_scope`` is ``Callable[[Any], bool]`` over ``state._computed``.
    The model does not get to assert what it changed — the caller passes a
    check over a diff the platform derived itself.
    """
    computed = getattr(state, "_computed", None)
    in_scope = bool(inspect_scope(computed))
    state.confidence = 1.0 if in_scope else 0.0
    detail = "diff is within the declared scope" if in_scope else "scope_expansion detected"
    state.record("inspect_diff_against_scope", detail)
    return OperatorResult(computed)


def falsify_fix(state: ProblemState, verify) -> OperatorResult:
    """Try to falsify the fix; confidence 1.0 only if falsification failed.

    ``verify`` is ``Callable[[Any], bool]``. The caller's verifier is expected
    to be two-sided — the suite must pass WITH the patch and fail WITHOUT it —
    so a patch that "passes" by deleting or neutering the test is caught.
    Absence of evidence is not evidence of passing: a missing or unparsable
    sandbox result must make ``verify`` return False, not True.
    """
    computed = getattr(state, "_computed", None)
    survived = bool(verify(computed))
    state.confidence = 1.0 if survived else 0.0
    state.record("falsify_fix", f"falsification check gave confidence {state.confidence:.2f}")
    return OperatorResult(computed)
