"""Result integration — fold child results into the parent, excluding any
child known to be lost (design spec error-handling table: a lost child is
"incomplete evidence", not silently summed as if its content were the result).
"""
from __future__ import annotations

from ..kernel import ProblemState


def integrate_results(state: ProblemState, lost_children: frozenset[str] = frozenset()) -> int:
    total = 0
    incomplete = False
    for child in state.children:
        if child.id in lost_children:
            incomplete = True
            continue
        val = getattr(child, "_computed", None)
        if val is None:
            val = _content_sum(child.content)
            child._computed = val  # type: ignore[attr-defined]
        total += val
    state._computed = total  # type: ignore[attr-defined]
    state._incomplete = incomplete  # type: ignore[attr-defined]
    return total


def _content_sum(obj) -> int:
    total = 0
    stack = [obj]
    seen = set()
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            i = id(cur)
            if i in seen:
                continue
            seen.add(i)
            stack.extend(cur.values())
        elif isinstance(cur, list):
            i = id(cur)
            if i in seen:
                continue
            seen.add(i)
            stack.extend(cur)
        else:
            try:
                total += int(cur)
            except (TypeError, ValueError):
                pass
    return total
