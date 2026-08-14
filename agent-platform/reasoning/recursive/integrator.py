"""Result integration — fold child results into the parent."""

from __future__ import annotations

from ..kernel import ProblemState


def integrate_results(state: ProblemState) -> int:
    """Consolidate child results into the parent.

    Each child must carry ``._computed`` (an int). Returns the folded total and
    stores it on the parent. Raises if a child has no computed result yet.
    """
    total = 0
    for child in state.children:
        val = getattr(child, "_computed", None)
        if val is None:
            # child was evaluated but its result not stored -> treat content sum
            val = _content_sum(child.content)
            child._computed = val  # type: ignore[attr-defined]
        total += val
    state._computed = total  # type: ignore[attr-defined]
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
