"""Post-hoc budget rollover between sequential children (design spec decision
7). Only unused surplus from an already-terminal child rolls forward; there is
no mid-flight borrowing, since Fas 4 v0.1's M1/M2 scenarios never run two
children that both need to draw against the same pool concurrently.
"""
from __future__ import annotations


def reclaimable_surplus(child_allocated: int, child_spent: int) -> int:
    if child_spent >= child_allocated:
        return 0
    return child_allocated - child_spent


def next_child_budget(base_allocation: int, reclaimed_surplus: int) -> int:
    return base_allocation + reclaimed_surplus
