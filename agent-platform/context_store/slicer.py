"""Split one ContextReference into up-to-N child references (target
architecture §11.2's max_branches_per_node/max_context_reads bound this at
the caller — Coordinator.run_node, Task 6).
"""
from __future__ import annotations

from .store import ContextReference


class SliceBudgetExhausted(Exception):
    """Raised when a range cannot be split into N non-empty slices."""


def slice_for_children(ref: ContextReference, n: int) -> list[ContextReference]:
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    start, end = ref.range
    span = end - start
    if span < n:
        raise SliceBudgetExhausted(
            f"cannot split range of length {span} into {n} non-empty slices")
    step = span // n
    slices = []
    for i in range(n):
        s = start + i * step
        e = start + (i + 1) * step if i < n - 1 else end
        slices.append(ref.child_ref((s, e)))
    return slices
