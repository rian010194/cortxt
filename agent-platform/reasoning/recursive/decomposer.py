"""Bounded problem decomposition."""

from __future__ import annotations

from ..kernel import ProblemState


def decompose_state(
    state: ProblemState,
    max_branches_per_node: int,
    max_children: int | None = None,
) -> list[ProblemState]:
    """Split ``state.content`` into at most ``max_branches_per_node`` sub-states.

    Deterministic: content may be a list (each element a branch) or a dict with
    a ``branches`` key. If the content is not decomposable, returns [].

    Fail-closed pruning: the structural fan-out is truncated to the per-node cap
    AND to ``max_children`` (a global remaining-children budget) when given, so a
    resource bound is never exceeded (target architecture §11.2).
    """
    content = state.content
    if isinstance(content, dict) and "branches" in content:
        branches = content["branches"]
    elif isinstance(content, list):
        branches = content
    else:
        return []

    branches = branches[:max_branches_per_node]
    if max_children is not None:
        branches = branches[:max_children]

    children: list[ProblemState] = []
    for b in branches:
        child = ProblemState(content=b)
        state.add_child(child)
        children.append(child)
    return children
