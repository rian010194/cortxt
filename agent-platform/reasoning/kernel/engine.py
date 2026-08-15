"""Reasoning kernel engine — the core loop.

``Engine.solve`` selects a strategy from problem properties and drives a small,
deterministic operator graph to a terminal answer. It is model-free in this
vertical slice: the strategy/operator dispatch is structural, preparing for the
RLM (recursive) and Geometric engines that arrive in later milestones while
keeping the kernel boundary (target architecture §10) intact.
"""

from __future__ import annotations

from typing import Callable

from .operators import (
    OperatorResult,
    decompose,
    inspect,
    inspect_with_model,
    integrate,
    verify,
    verify_against_schema,
)
from .problem_state import ProblemState, new_problem
from .strategy import Strategy, select_strategy

# A terminal answer is a dict {strategy, value, confidence, steps}.
Result = dict


def _is_terminal(state: ProblemState) -> bool:
    """True once the root has a computed value, a full log, and no pending work."""
    # For this slice: the problem is solved when the root carries a computed value.
    return getattr(state, "_computed", None) is not None and len(state.transformation_log) > 0


def _solve_direct(state: ProblemState, expected=None) -> OperatorResult:
    inspect(state)
    return verify(state, expected)


def _is_decomposable(state: ProblemState) -> bool:
    """True when content is structurally nested (list-in-list) or has branches."""
    if isinstance(state.content, (list, tuple)):
        # decomposable if any element is itself a list/tuple
        return any(isinstance(x, (list, tuple)) for x in state.content)
    if isinstance(state.content, dict):
        return "branches" in state.content
    return False


def _solve_recursive(state: ProblemState, expected=None) -> OperatorResult:
    if not _is_decomposable(state):
        if state.children:
            return integrate(state)
        return verify(state, expected)
    decompose(state)
    for child in state.children:
        _solve_recursive(child, expected=None)
    integrate(state)
    # The parent's integrated total must still be verified to set confidence.
    return verify(state, expected)


def _solve_geometric(state: ProblemState, expected=None) -> OperatorResult:
    # Geometric strategy in this slice: respect explicit constraint-dependencies
    # by sorting the problem into independent value-groups then folding them,
    # which produces a different (constraint-aware) traversal than direct.
    contents = state.content
    if not isinstance(contents, dict):
        raise TypeError("geometric strategy requires dict content with 'branches'/'values'")  # P2 guard
    branches = contents.get("branches", contents.get("values", contents))
    inspect(state)
    total = 0
    for branch in branches:
        total += sum(_flatten_scalars(branch))
    state._computed = total  # type: ignore[attr-defined]
    return verify(state, expected)


def _solve_model_assisted(state: ProblemState, invoke, validate) -> OperatorResult:
    inspect_with_model(state, invoke)
    return verify_against_schema(state, validate)


def _flatten_scalars(obj):
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
        elif isinstance(cur, dict):
            i = id(cur)
            if i in seen:
                continue
            seen.add(i)
            # descend into dict values (constraint maps still carry numbers)
            stack.extend(reversed(list(cur.values())))
        else:
            out.append(cur)
    return out


# strategy -> solver
_SOLVERS: dict[Strategy, Callable[[ProblemState, object], OperatorResult]] = {
    Strategy.DIRECT: _solve_direct,
    Strategy.RECURSIVE: _solve_recursive,
    Strategy.GEOMETRIC: _solve_geometric,
    Strategy.MODEL_ASSISTED: _solve_model_assisted,
}


class Engine:
    """Small strategy-driven reasoning kernel."""

    def __init__(self, expected: object = None):
        self._expected = expected

    def solve(self, content) -> Result:
        state = new_problem(content)
        strategy = select_strategy(content)
        solver = _SOLVERS.get(strategy)
        if solver is None:
            state.record("human_escalation", "no solver for strategy")
            return {
                "strategy": strategy.value,
                "value": None,
                "confidence": 0.0,
                "steps": state.transformation_log,
                "escalated": True,
            }
        result = solver(state, self._expected)
        return {
            "strategy": strategy.value,
            "value": result.value,
            "confidence": state.confidence,
            "steps": state.transformation_log,
        }

    def solve_model_assisted(self, content, invoke, validate) -> Result:
        """Explicit entry point for MODEL_ASSISTED — never auto-selected by
        select_strategy(), always invoked directly by a caller that has a
        real inference callable and a real output validator (e.g. Agent
        Runtime's agent_loop)."""
        state = new_problem(content)
        result = _solve_model_assisted(state, invoke, validate)
        return {
            "strategy": Strategy.MODEL_ASSISTED.value,
            "value": result.value,
            "confidence": state.confidence,
            "steps": state.transformation_log,
        }
